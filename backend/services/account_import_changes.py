"""Field patches and projected totals shared by account preview and execution."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from backend.backup_contract import AccountBackup

if TYPE_CHECKING:
    from backend.services.account_import_plan import ImportPlan


@dataclass
class ImportChanges:
    shoes: dict[int, dict[str, Any]] = field(default_factory=dict)
    runs: dict[int, dict[str, Any]] = field(default_factory=dict)
    months: dict[tuple[int, int], dict[str, Any]] = field(default_factory=dict)
    reports: dict[tuple[int, int], dict[str, Any]] = field(default_factory=dict)
    goal: dict[str, Any] = field(default_factory=dict)
    new_shoe_mileages: dict[int, float] = field(default_factory=dict)


def changed_fields(row: Any, values: dict[str, Any]) -> dict[str, Any]:
    def comparable(name, value):
        if name in {"mileage", "baseline_mileage", "km", "adjustment_km", "monthly_km", "yearly_km", "expected_mileage"} and isinstance(value, (int, float)):
            return round(value, 2)
        return value.replace(tzinfo=UTC) if isinstance(value, datetime) and value.tzinfo is None else value
    return {name: value for name, value in values.items() if comparable(name, getattr(row, name)) != comparable(name, value)}


def build_changes(plan: 'ImportPlan', backup: AccountBackup) -> ImportChanges:
    changes = ImportChanges()
    # New source shoe IDs occupy a separate namespace until execution allocates IDs.
    final_runs = {('existing', row.id): (('existing', row.shoe_id), row.date, row.km) for row in plan.runs.values()}
    for run_item in backup.runs:
        target = plan.run_targets[run_item.id]
        shoe_target = plan.existing('shoe', run_item.shoe_id)
        shoe_key = ('existing', shoe_target) if shoe_target is not None else ('source', run_item.shoe_id)
        if target is None:
            final_runs[('source', run_item.id)] = (shoe_key, run_item.date, run_item.km)
        elif target in plan.runs:
            run_row = plan.runs[target]
            patch = changed_fields(run_row, run_item.model_dump(exclude={'id', 'shoe_id', 'aliases'}))
            if run_row.shoe_id != shoe_target:
                # This field contains a source ID; execution resolves it after shoe creation.
                patch['shoe_id'] = run_item.shoe_id
            if patch:
                changes.runs[target] = patch
            final_runs[('existing', target)] = (shoe_key, run_item.date, run_item.km)
        # Missing mapped runs are deletion tombstones and remain absent.
    by_shoe: dict[tuple[str, int], float] = {}
    by_month: dict[tuple[int, int], float] = {}
    for shoe_key, date, km in final_runs.values():
        by_shoe[shoe_key] = by_shoe.get(shoe_key, 0) + km
        period = (int(date[:4]), int(date[5:7]))
        by_month[period] = by_month.get(period, 0) + km
    baselines = {row.id: row.baseline_mileage for row in plan.shoes.values()}
    for shoe_item in backup.shoes:
        target = plan.existing('shoe', shoe_item.id)
        if target is None:
            changes.new_shoe_mileages[shoe_item.id] = round(float(shoe_item.baseline_mileage or 0) + by_shoe.get(('source', shoe_item.id), 0), 2)
        elif target in plan.shoes:
            patch = changed_fields(plan.shoes[target], shoe_item.model_dump(exclude={'id', 'mileage'}))
            if patch:
                changes.shoes[target] = patch
            baselines[target] = float(shoe_item.baseline_mileage or 0)
    for identifier, shoe_row in plan.shoes.items():
        total = round(baselines[identifier] + by_shoe.get(('existing', identifier), 0), 2)
        if round(shoe_row.mileage, 2) != total:
            changes.shoes.setdefault(identifier, {})['mileage'] = total
    incoming_months = {(item.year, item.month): item for item in backup.monthly_mileages}
    for period in plan.months.keys() | incoming_months.keys() | by_month.keys():
        current = plan.months.get(period)
        incoming = incoming_months.get(period)
        adjustment = float(incoming.adjustment_km or 0) if incoming else float(current.adjustment_km or 0) if current else 0
        values = {'adjustment_km': adjustment, 'km': round(adjustment + by_month.get(period, 0), 2)}
        patch = changed_fields(current, values) if current else values
        if patch:
            changes.months[period] = patch
    if backup.running_goal and plan.goal:
        goal = backup.running_goal
        changes.goal = changed_fields(plan.goal, {'start_year': goal.start_year, 'monthly_km': goal.monthly_km,
                                                  'yearly_km': round(goal.monthly_km * 12, 2)})
    for report_item in backup.monthly_reports:
        period = (report_item.year, report_item.month)
        if period in plan.reports:
            patch = changed_fields(plan.reports[period], report_item.model_dump(exclude_none=True))
            if patch:
                changes.reports[period] = patch
    return changes
