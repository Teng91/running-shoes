"""Spreadsheet-safe row generation for shoe exports."""

from datetime import tzinfo

from backend import clock, models
from backend.shoe_metrics import shoe_metrics


def spreadsheet_safe(value):
    """Prevent user-controlled text becoming a CSV/XLSX formula."""
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def generate_shoe_rows(
    shoes: list[models.Shoe], include_retired_status: bool = True
):
    """Generate CSV/XLSX rows without discarding stored decimal precision."""
    for shoe in shoes:
        status = "已退役" if shoe.is_retired else "使用中"
        metrics = shoe_metrics(shoe)
        discount = metrics["discount_percent"] or 0
        cost_per_km = metrics["cost_per_km"] or 0
        expected_cost = metrics["expected_cost_per_km"] or 0
        life_pct = metrics["usage_percent"] or 0
        row = {
            "品牌": spreadsheet_safe(shoe.brand),
            "鞋款": spreadsheet_safe(shoe.model),
            "暱稱": spreadsheet_safe(shoe.nickname),
            "購買日期": spreadsheet_safe(shoe.date),
            "尺寸": spreadsheet_safe(shoe.size),
            "買價": round(float(shoe.price), 2),
            "原價": round(float(shoe.orig_price), 2),
            "折數(%)": discount,
            "跑鞋里程(km)": shoe.mileage,
            "預期里程(km)": shoe.expected_mileage,
            "每km成本": cost_per_km,
            "預期每km成本": expected_cost,
            "生命進度(%)": life_pct,
            "類別": spreadsheet_safe(", ".join(shoe.categories) if shoe.categories else ""),
        }
        if include_retired_status:
            row["狀態"] = status
        yield row


def export_filename(file_format: str, mode: str, zone: tzinfo = clock.DEFAULT_ZONE) -> str:
    # Fly machines run in UTC; filenames follow the account's calendar instead (SPEC-147).
    timestamp = clock.local_now(zone).strftime("%Y%m%d_%H%M%S")
    return f"running_shoes_{mode}_{timestamp}.{file_format}"
