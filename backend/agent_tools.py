"""Trusted Agent tool dispatch without streaming or planning concerns."""

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from backend.tools import db_tools
from backend.tools.search_tool import run_web_search


def execute_tool(
    name: str,
    arguments: Any,
    db: Session | None,
    user_id: int | None,
    *,
    web_search_fn: Callable[[dict[str, Any]], str] = run_web_search,
) -> str:
    args = arguments if isinstance(arguments, dict) else {}
    if name == "web_search":
        return web_search_fn(args)
    fn = db_tools.REGISTRY.get(name)
    if fn is None:
        return f"（未知工具：{name}）"
    if db is None or user_id is None:
        return "（缺少使用者資料庫上下文）"
    if name == "nearing_end_of_life":
        try:
            threshold = float(args.get("threshold", 0.8))
        except (TypeError, ValueError):
            threshold = 0.8
        return fn(db, user_id, threshold=max(0.0, min(1.0, threshold)))
    if name == "compare_shoes":
        shoe_a = args.get("shoe_a", "")
        shoe_b = args.get("shoe_b", "")
        identifiers = {key: value for key in ("shoe_a_id", "shoe_b_id")
                       if isinstance(value := args.get(key), int) and not isinstance(value, bool) and value > 0}
        return fn(
            db, user_id,
            shoe_a=shoe_a if isinstance(shoe_a, str) else "",
            shoe_b=shoe_b if isinstance(shoe_b, str) else "",
            **identifiers,
        )
    if name in {"running_goal_progress", "training_trends", "year_review"}:
        year = args.get("year")
        valid = isinstance(year, int) and not isinstance(year, bool) and 1900 <= year <= 2100
        return fn(db, user_id, year=year if valid else None)
    if name in {"shoe_category_status", "shoe_usage_analytics"}:
        shoe_name = args.get("shoe_name", "")
        shoe_id = args.get("shoe_id")
        identifiers = {"shoe_id": shoe_id} if isinstance(shoe_id, int) and not isinstance(shoe_id, bool) and shoe_id > 0 else {}
        return fn(
            db, user_id,
            shoe_name=shoe_name if isinstance(shoe_name, str) else "",
            **identifiers,
        )
    return fn(db, user_id)
