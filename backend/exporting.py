"""Spreadsheet-safe row generation for shoe exports."""

from datetime import datetime

from backend import models


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
        discount = round(shoe.price / shoe.orig_price * 100, 2) if shoe.orig_price > 0 else 0
        cost_per_km = round(shoe.price / shoe.mileage, 2) if shoe.mileage > 0 else 0
        expected_cost = (
            round(shoe.price / shoe.expected_mileage, 2) if shoe.expected_mileage > 0 else 0
        )
        life_pct = (
            round(shoe.mileage / shoe.expected_mileage * 100, 2)
            if shoe.expected_mileage > 0 else 0
        )
        row = {
            "品牌": spreadsheet_safe(shoe.brand),
            "鞋款": spreadsheet_safe(shoe.model),
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
            "月跑量(km)": shoe.monthly_km,
            "類別": spreadsheet_safe(", ".join(shoe.categories) if shoe.categories else ""),
        }
        if include_retired_status:
            row["狀態"] = status
        yield row


def export_filename(file_format: str, mode: str) -> str:
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    return f"running_shoes_{mode}_{timestamp}.{file_format}"
