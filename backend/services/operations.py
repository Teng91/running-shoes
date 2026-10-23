"""One transaction owns the business mutation, audit context and replay receipt."""

from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.forecasting import forecasts_for_shoes
from backend.services import goals, history, monthly, runs, shoes
from backend.services.errors import Conflict, Invalid
from backend.services.run_requests import payload_hash
from backend.services.transactions import write_transaction
from backend.settings import Settings
from backend.shoe_metrics import shoe_metrics


def execute_operation(db: Session, user_id: int, command: schemas.MutationCommand, config: Settings) -> dict:
    fingerprint = payload_hash(command.model_dump(exclude={"operation_id"}))
    with write_transaction(db, user_id, reason=command.kind, operation_id=command.operation_id):
        receipt = db.query(models.MutationReceipt).filter_by(
            user_id=user_id, operation_id=command.operation_id
        ).first()
        if receipt is not None:
            if receipt.payload_hash != fingerprint:
                raise Conflict("操作識別碼已用於不同內容")
            return receipt.response_json
        response = _dispatch(db, user_id, command, config)
        db.add(models.MutationReceipt(user_id=user_id, operation_id=command.operation_id,
                                       payload_hash=fingerprint, response_json=response))
        return response


def _dispatch(db: Session, user_id: int, command: schemas.MutationCommand, config: Settings) -> dict:
    kind, payload, entity_id = command.kind, command.payload, command.entity_id
    if kind == "history.restore":
        return history.restore_deleted(db, user_id, int(entity_id or 0), config)
    entity, action = kind.split(".")
    create: dict[str, tuple[Any, Any, dict[str, Any]]] = {"run": (schemas.RunCreate, runs.create_run, {"max_runs": config.max_runs_per_user}),
              "shoe": (schemas.ShoeCreate, shoes.create_shoe, {"max_shoes": config.max_shoes_per_user}),
              "monthly": (schemas.MonthlyMileageCreate, monthly.create_monthly_mileage, {})}
    update: dict[str, tuple[Any, Any]] = {"run": (schemas.RunUpdate, runs.update_run), "shoe": (schemas.ShoeUpdate, shoes.update_shoe),
              "monthly": (schemas.MonthlyMileageUpdate, monthly.update_monthly_mileage)}
    output: dict[str, Any] = {"run": schemas.RunOut, "shoe": schemas.ShoeOut, "monthly": schemas.MonthlyMileageOut}
    allowed = {"run": schemas.RunCreate if action == "create" else schemas.RunUpdate,
               "shoe": schemas.ShoeCreate if action == "create" else schemas.ShoeUpdate,
               "monthly": schemas.MonthlyMileageCreate if action == "create" else schemas.MonthlyMileageUpdate,
               "goal": schemas.RunningGoalUpdate}[entity]
    if set(payload) - set(allowed.model_fields):
        raise Invalid("操作包含不支援的欄位")
    if entity == "goal":
        return goals.update_goal(db, user_id, schemas.RunningGoalUpdate.model_validate(
            {**payload, "expected_version": command.expected_version}
        ))
    if action == "create":
        schema, create_fn, kwargs = create[entity]
        if entity == "run":
            kwargs = {**kwargs, "idempotency_key": command.operation_id}
        row = create_fn(db, user_id, schema.model_validate(payload), **kwargs)
    elif action == "update":
        schema, update_fn = update[entity]
        row = update_fn(db, user_id, entity_id, schema.model_validate(
            {**payload, "expected_version": command.expected_version}
        ))
    elif action == "delete":
        delete_fn = {"run": runs.delete_run, "shoe": shoes.delete_shoe,
                     "monthly": monthly.delete_monthly_mileage}[entity]
        return delete_fn(db, user_id, int(entity_id or 0), command.expected_version)
    else:
        raise Invalid("未知操作")
    if isinstance(row, dict):
        return row
    db.flush()
    db.refresh(row)
    response = output[entity].model_validate(row).model_dump(mode="json")
    if entity == "shoe":
        response.update(shoe_metrics(row))
        response.update({key: value for key, value in forecasts_for_shoes(db, user_id, [row])[row.id].items()
                         if key.startswith("forecast_")})
    return response


def legacy_operation(db, user_id, kind, config, key, payload=None, entity_id=None, expected_version=None):
    data = dict(payload or {})
    version = data.pop("expected_version", expected_version)
    try:
        command = schemas.MutationCommand(operation_id=key, kind=kind, payload=data,
                                           entity_id=entity_id, expected_version=version)
        return execute_operation(db, user_id, command, config)
    except ValidationError as exc:
        raise Invalid("操作內容格式錯誤；更新或刪除必須提供版本") from exc
