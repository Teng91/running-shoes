"""Thin JSON tool adapters; computation lives in shared read models."""

import json
from collections.abc import Callable

from sqlalchemy.orm import Session

from backend.read_models import mileage, shoes
from backend.tools import legacy_calls
from backend.tools.tool_definitions import TOOL_DEFINITIONS as TOOL_DEFINITIONS


def _json_result(tool: str, **payload) -> str:
    return json.dumps(
        {"tool": tool, "schema_version": 1, **payload}, ensure_ascii=False, separators=(",", ":")
    )


def list_my_shoes(db: Session, user_id: int) -> str:
    return _json_result("list_my_shoes", **shoes.list_my_shoes(db, user_id))


def shoe_summary(db: Session, user_id: int) -> str:
    return _json_result("shoe_summary", **shoes.shoe_summary(db, user_id))


def monthly_mileage_stats(db: Session, user_id: int) -> str:
    return _json_result("monthly_mileage_stats", **mileage.monthly_mileage_stats(db, user_id))


def nearing_end_of_life(db: Session, user_id: int, threshold: float = 0.8) -> str:
    return _json_result(
        "nearing_end_of_life", **shoes.nearing_end_of_life(db, user_id, threshold=threshold)
    )


def compare_shoes(
    db: Session,
    user_id: int,
    shoe_a: str = "",
    shoe_b: str = "",
    *,
    shoe_a_id: int | None = None,
    shoe_b_id: int | None = None,
) -> str:
    return _json_result(
        "compare_shoes",
        **shoes.compare_shoes(
            db, user_id, shoe_a=shoe_a, shoe_b=shoe_b, shoe_a_id=shoe_a_id, shoe_b_id=shoe_b_id
        ),
    )


def shoe_category_status(
    db: Session, user_id: int, shoe_name: str = "", *, shoe_id: int | None = None
) -> str:
    return _json_result(
        "shoe_category_status",
        **shoes.shoe_category_status(db, user_id, shoe_name=shoe_name, shoe_id=shoe_id),
    )


def shoe_usage_analytics(
    db: Session, user_id: int, shoe_name: str = "", *, shoe_id: int | None = None
) -> str:
    return _json_result(
        "shoe_usage_analytics",
        **shoes.shoe_usage_analytics(db, user_id, shoe_name=shoe_name, shoe_id=shoe_id),
    )


REGISTRY: dict[str, Callable[..., str]] = {
    "list_my_shoes": list_my_shoes,
    "shoe_summary": shoe_summary,
    "monthly_mileage_stats": monthly_mileage_stats,
    "nearing_end_of_life": nearing_end_of_life,
    "compare_shoes": compare_shoes,
    "shoe_category_status": shoe_category_status,
    "shoe_usage_analytics": shoe_usage_analytics,
}


def parse_tool_calls(text: str) -> list[dict]:
    return legacy_calls.parse_tool_calls(text, set(REGISTRY) | {"web_search"})


def strip_tool_markers(text: str) -> str:
    return legacy_calls.strip_tool_markers(text, set(REGISTRY) | {"web_search"})
