"""One transaction owns the business mutation, audit context and replay receipt."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.forecasting import forecasts_for_shoes
from backend.services import goals, history, monthly, runs, shoes
from backend.services.errors import Conflict, Invalid
from backend.services.fingerprints import payload_hash
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


@dataclass(frozen=True)
class _EntityHandlers:
    create_schema: type[BaseModel]
    create: Callable[..., Any]
    create_limits: Callable[[Settings], dict[str, int]]
    update_schema: type[BaseModel]
    update: Callable[..., Any]
    delete: Callable[..., dict]
    output: type[BaseModel]


_HANDLERS: dict[str, _EntityHandlers] = {
    "run": _EntityHandlers(
        schemas.RunCreate, runs.create_run, lambda config: {"max_runs": config.max_runs_per_user},
        schemas.RunUpdate, runs.update_run, runs.delete_run, schemas.RunOut,
    ),
    "shoe": _EntityHandlers(
        schemas.ShoeCreate, shoes.create_shoe, lambda config: {"max_shoes": config.max_shoes_per_user},
        schemas.ShoeUpdate, shoes.update_shoe, shoes.delete_shoe, schemas.ShoeOut,
    ),
    "monthly": _EntityHandlers(
        schemas.MonthlyMileageCreate, monthly.create_monthly_mileage, lambda config: {},
        schemas.MonthlyMileageUpdate, monthly.update_monthly_mileage,
        monthly.delete_monthly_mileage, schemas.MonthlyMileageOut,
    ),
}


def _reject_unknown_fields(payload: dict, schema: type[BaseModel]) -> None:
    if set(payload) - set(schema.model_fields):
        raise Invalid("操作包含不支援的欄位")


def _dispatch(db: Session, user_id: int, command: schemas.MutationCommand, config: Settings) -> dict:
    kind, payload, entity_id = command.kind, command.payload, command.entity_id
    if kind == "history.restore":
        return history.restore_deleted(db, user_id, int(entity_id or 0), config)
    entity, action = kind.split(".")
    if entity == "goal":
        _reject_unknown_fields(payload, schemas.RunningGoalUpdate)
        return goals.update_goal(db, user_id, schemas.RunningGoalUpdate.model_validate(
            {**payload, "expected_version": command.expected_version}
        ))
    handlers = _HANDLERS[entity]
    if action == "create":
        _reject_unknown_fields(payload, handlers.create_schema)
        row = handlers.create(
            db, user_id, handlers.create_schema.model_validate(payload), **handlers.create_limits(config)
        )
    elif action == "update":
        _reject_unknown_fields(payload, handlers.update_schema)
        row = handlers.update(db, user_id, entity_id, handlers.update_schema.model_validate(
            {**payload, "expected_version": command.expected_version}
        ))
    elif action == "delete":
        _reject_unknown_fields(payload, handlers.update_schema)
        return handlers.delete(db, user_id, int(entity_id or 0), command.expected_version)
    else:
        raise Invalid("未知操作")
    if isinstance(row, dict):
        return row
    db.flush()
    db.refresh(row)
    response = handlers.output.model_validate(row).model_dump(mode="json")
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
