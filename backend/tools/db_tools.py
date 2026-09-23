"""讀取使用者跑鞋資料的 agent 工具。

設計重點：
- 每個查詢都帶 `user_id`，永遠只看「目前登入使用者」的資料，與現有
  Dashboard 的 user 隔離一致。工具本身不接收 user_id 參數（由 agent
  在呼叫時自動注入），避免 LLM 去讀別人的資料。
- 資料庫工具一律回傳具名 JSON。里程、百分比、成本與分類結論都由
  後端計算，LLM 只負責把結果轉成自然語言，不自行猜測欄位含義。
- 這裡只定義 tool 的 schema 與執行器；真正的派發在 agent.py。

所有函式都接受 `(db, user_id)`，回傳 JSON 字串。
"""

import json
from collections.abc import Callable

from sqlalchemy.orm import Session

from backend import models
from backend.schemas import SHOE_CATEGORIES


def _json_result(tool: str, **payload) -> str:
    """Serialize a stable, machine-readable tool result for the LLM."""
    return json.dumps(
        {"tool": tool, "schema_version": 1, **payload},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _round(value: float | None, digits: int = 2) -> float:
    return round(float(value or 0), digits)


def _lifecycle(shoe: models.Shoe) -> dict:
    mileage = _round(shoe.mileage)
    expected = _round(shoe.expected_mileage)
    if expected <= 0:
        return {
            "mileage_km": mileage,
            "expected_lifespan_km": None,
            "remaining_mileage_km": None,
            "usage_percent": None,
            "lifecycle_status": "lifespan_not_configured",
        }

    usage_percent = _round(mileage / expected * 100, 1)
    if usage_percent >= 90:
        lifecycle_status = "replace_soon"
    elif usage_percent >= 80:
        lifecycle_status = "monitor"
    else:
        lifecycle_status = "healthy"
    return {
        "mileage_km": mileage,
        "expected_lifespan_km": expected,
        "remaining_mileage_km": _round(max(0, expected - mileage)),
        "usage_percent": usage_percent,
        "lifecycle_status": lifecycle_status,
    }


def _shoe_data(shoe: models.Shoe) -> dict:
    return {
        "shoe_id": shoe.id,
        "brand": shoe.brand,
        "model": shoe.model,
        "categories": [
            category for category in (shoe.categories or []) if category in SHOE_CATEGORIES
        ],
        "status": "retired" if shoe.is_retired else "active",
        "purchase_date": shoe.date,
        "size": shoe.size,
        "purchase_price_twd": _round(shoe.price),
        "original_price_twd": _round(shoe.orig_price),
        # This is a user-assigned allocation target, not accumulated mileage.
        "assigned_monthly_km": _round(shoe.monthly_km),
        **_lifecycle(shoe),
    }


# ── 工具實作 ────────────────────────────────────────────────────
def list_my_shoes(db: Session, user_id: int) -> str:
    shoes = (
        db.query(models.Shoe)
        .filter(models.Shoe.user_id == user_id, models.Shoe.is_deleted.is_(False))
        .order_by(models.Shoe.is_retired, models.Shoe.date.desc())
        .all()
    )
    return _json_result(
        "list_my_shoes",
        ok=True,
        shoe_count=len(shoes),
        field_definitions={
            "mileage_km": "此鞋目前累積已跑里程，不是剩餘里程",
            "expected_lifespan_km": "此鞋設定的預期總壽命",
            "remaining_mileage_km": "後端計算的剩餘里程",
            "usage_percent": "後端計算的已使用壽命百分比，不是剩餘百分比",
            "assigned_monthly_km": "使用者分配給此鞋的每月目標里程，不是累積里程",
        },
        shoes=[_shoe_data(shoe) for shoe in shoes],
    )


def shoe_summary(db: Session, user_id: int) -> str:
    shoes = db.query(models.Shoe).filter(
        models.Shoe.user_id == user_id, models.Shoe.is_deleted.is_(False)
    ).all()
    active = [s for s in shoes if not s.is_retired]
    retired = [s for s in shoes if s.is_retired]
    active_lifecycle = sorted(
        (_shoe_data(shoe) for shoe in active),
        key=lambda item: item["usage_percent"] if item["usage_percent"] is not None else -1,
        reverse=True,
    )
    return _json_result(
        "shoe_summary",
        ok=True,
        total_shoe_count=len(shoes),
        active_shoe_count=len(active),
        retired_shoe_count=len(retired),
        all_shoes_accumulated_mileage_km=_round(sum(s.mileage or 0 for s in shoes)),
        active_shoes_purchase_price_twd=_round(sum(s.price or 0 for s in active)),
        active_shoes_original_price_twd=_round(sum(s.orig_price or 0 for s in active)),
        active_shoes_lifecycle=active_lifecycle,
    )


def monthly_mileage_stats(db: Session, user_id: int) -> str:
    rows = (
        db.query(models.MonthlyMileage)
        .filter(models.MonthlyMileage.user_id == user_id)
        .order_by(models.MonthlyMileage.year, models.MonthlyMileage.month)
        .all()
    )
    recorded_rows = rows
    rows = [r for r in rows if r.km > 0]
    if not rows:
        return _json_result(
            "monthly_mileage_stats",
            ok=True,
            status="no_records" if not recorded_rows else "all_months_zero",
            recorded_month_count=len(recorded_rows),
            nonzero_month_count=0,
            total_mileage_km=0.0,
            recent_nonzero_months=[],
        )

    total = sum(r.km for r in rows)
    avg = total / len(rows)
    recent = rows[-6:]
    recent_total = sum(r.km for r in recent)
    recent_avg = recent_total / len(recent)
    trend = "up" if (recent_avg > avg) else ("down" if recent_avg < avg else "flat")

    last = rows[-1]
    return _json_result(
        "monthly_mileage_stats",
        ok=True,
        status="available",
        recorded_month_count=len(recorded_rows),
        nonzero_month_count=len(rows),
        total_mileage_km=_round(total),
        overall_nonzero_month_average_km=_round(avg),
        recent_period_definition="latest_6_months_with_positive_mileage",
        recent_period_month_count=len(recent),
        recent_period_total_km=_round(recent_total),
        recent_period_average_km=_round(recent_avg),
        recent_vs_overall_trend=trend,
        latest_record={"year": last.year, "month": last.month, "mileage_km": _round(last.km)},
        recent_nonzero_months=[
            {"year": row.year, "month": row.month, "mileage_km": _round(row.km)}
            for row in recent
        ],
    )


def nearing_end_of_life(db: Session, user_id: int, threshold: float = 0.8) -> str:
    shoes = (
        db.query(models.Shoe)
        .filter(
            models.Shoe.user_id == user_id,
            models.Shoe.is_retired.is_(False),
            models.Shoe.is_deleted.is_(False),
        )
        .all()
    )
    candidates = []
    for s in shoes:
        # Guard against expected_mileage = 0 (user-editable) to avoid division by zero
        if s.expected_mileage and s.expected_mileage > 0:
            pct = s.mileage / s.expected_mileage
            if pct >= threshold:
                remain = max(0, s.expected_mileage - s.mileage)
                candidates.append((pct, s, remain))

    candidates.sort(key=lambda item: item[0], reverse=True)
    results = []
    for _pct, s, _remain in candidates:
        target_categories = [
            category for category in (s.categories or []) if category in SHOE_CATEGORIES
        ]
        category_coverage = {
            category: sum(
                other.id != s.id and category in (other.categories or [])
                for other in shoes
            )
            for category in target_categories
        }
        uncovered_categories = [
            category for category, count in category_coverage.items() if count == 0
        ]
        all_categories_covered = bool(target_categories) and not uncovered_categories
        other_active_same_category = sum(
            other.id != s.id and any(
                cat in (other.categories or []) for cat in (s.categories or [])
            ) for other in shoes
        )
        results.append({
            **_shoe_data(s),
            "active_replacement_count_sharing_any_category": other_active_same_category,
            "category_replacement_coverage": category_coverage,
            "uncovered_categories": uncovered_categories,
            "all_categories_have_active_replacement": all_categories_covered,
            "has_active_category_replacement": all_categories_covered,
            "replacement_recommendation": (
                "monitor_only_no_purchase_needed"
                if all_categories_covered
                else "prepare_replacement_purchase"
            ),
        })
    return _json_result(
        "nearing_end_of_life",
        ok=True,
        threshold_fraction=_round(threshold, 3),
        threshold_percent=_round(threshold * 100, 1),
        matching_shoe_count=len(results),
        shoes=results,
    )


def compare_shoes(db: Session, user_id: int, shoe_a: str = "", shoe_b: str = "") -> str:
    """比較目前使用者的兩雙鞋，名稱可用「品牌 鞋款」或其中一段文字。"""
    shoes = db.query(models.Shoe).filter(
        models.Shoe.user_id == user_id, models.Shoe.is_deleted.is_(False)
    ).all()

    def find_shoe(query: str):
        query = (query or "").strip().lower()
        if not query:
            return None
        exact = next(
            (s for s in shoes if f"{s.brand} {s.model}".lower() == query),
            None,
        )
        if exact:
            return exact
        return next(
            (s for s in shoes if query in f"{s.brand} {s.model}".lower()),
            None,
        )

    first = find_shoe(shoe_a)
    second = find_shoe(shoe_b)
    if not first or not second:
        missing = []
        if not first:
            missing.append(f"shoe_a={shoe_a or '未提供'}")
        if not second:
            missing.append(f"shoe_b={shoe_b or '未提供'}")
        return _json_result(
            "compare_shoes",
            ok=False,
            error="shoe_not_found",
            missing_queries=missing,
            available_shoes=[f"{s.brand} {s.model}" for s in shoes],
        )
    if first.id == second.id:
        return _json_result(
            "compare_shoes", ok=False, error="same_shoe_selected",
            matched_shoe=f"{first.brand} {first.model}",
        )

    def details(shoe: models.Shoe) -> dict:
        actual_cost = shoe.price / shoe.mileage if shoe.mileage > 0 else None
        expected_cost = shoe.price / shoe.expected_mileage if shoe.expected_mileage > 0 else None
        return {
            **_shoe_data(shoe),
            "actual_cost_per_completed_km_twd": _round(actual_cost) if actual_cost is not None else None,
            "projected_cost_per_lifespan_km_twd": _round(expected_cost) if expected_cost is not None else None,
        }

    return _json_result(
        "compare_shoes", ok=True, shoe_a=details(first), shoe_b=details(second)
    )


def shoe_category_status(db: Session, user_id: int, shoe_name: str = "") -> str:
    """分析鞋款用途的現役覆蓋，以及指定鞋款退役後是否要補鞋。

    一雙鞋可對應多個用途（例如 Daily + Tempo）。退役分析會檢查該鞋
    涵蓋的每個類別是否還有其他現役鞋作為替代。
    """
    shoes = db.query(models.Shoe).filter(
        models.Shoe.user_id == user_id, models.Shoe.is_deleted.is_(False)
    ).all()
    active = [s for s in shoes if not s.is_retired]
    retired = [s for s in shoes if s.is_retired]

    if shoe_name:
        query = shoe_name.strip().lower()
        # Search in ALL shoes (active + retired) so user can query retired shoes too
        target = next(
            (s for s in shoes if query in f"{s.brand} {s.model}".lower()),
            None,
        )
        if not target:
            return _json_result(
                "shoe_category_status", ok=False, error="shoe_not_found", query=shoe_name
            )
        target_cats = [
            category for category in (target.categories or []) if category in SHOE_CATEGORIES
        ]
        if not target_cats:
            return _json_result(
                "shoe_category_status", ok=True, mode="specific_shoe",
                shoe=_shoe_data(target), category_status="categories_not_configured",
            )

        coverage = []
        for cat in target_cats:
            backup = [s for s in active if s.id != target.id and cat in (s.categories or [])]
            coverage.append({
                "category": cat,
                "other_active_shoe_count": len(backup),
                "covered_after_target_retirement": bool(backup),
                "other_active_shoes": [f"{s.brand} {s.model}" for s in backup],
            })
        all_covered = all(
            any(s.id != target.id and cat in (s.categories or []) for s in active)
            for cat in target_cats
        )
        return _json_result(
            "shoe_category_status",
            ok=True,
            mode="specific_shoe",
            shoe=_shoe_data(target),
            coverage_after_target_retirement=coverage,
            all_categories_remain_covered=all_covered,
            purchase_recommendation=(
                "no_purchase_needed" if all_covered else "prepare_replacement_purchase"
            ),
        )

    coverage = []
    for category in SHOE_CATEGORIES:
        active_count = sum(category in (s.categories or []) for s in active)
        retired_count = sum(category in (s.categories or []) for s in retired)
        coverage.append({
            "category": category,
            "active_shoe_count": active_count,
            "retired_shoe_count": retired_count,
            "has_active_coverage": active_count > 0,
            "purchase_recommendation": (
                "no_purchase_needed" if active_count > 0 else "category_missing_consider_purchase"
            ),
        })
    return _json_result(
        "shoe_category_status", ok=True, mode="all_categories", categories=coverage
    )


# ── 派發表：讓 agent 用 tool name 找到對應函式 ────────────────
REGISTRY: dict[str, Callable[..., str]] = {
    "list_my_shoes": list_my_shoes,
    "shoe_summary": shoe_summary,
    "monthly_mileage_stats": monthly_mileage_stats,
    "nearing_end_of_life": nearing_end_of_life,
    "compare_shoes": compare_shoes,
    "shoe_category_status": shoe_category_status,
}


# ── OpenRouter / OpenAI 原生 function-calling schema ─────────────
# 不啟用 provider-specific strict mode，讓更多 OpenRouter 免費模型能使用。
TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "list_my_shoes",
            "description": "以 JSON 列出所有跑鞋；後端已分別計算累積里程、剩餘里程、已使用百分比與分配月跑量。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shoe_summary",
            "description": "以 JSON 取得跑鞋總覽；所有數量、金額、里程與壽命皆由後端計算。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "monthly_mileage_stats",
            "description": "以 JSON 取得後端計算的跑量統計及最近六個有跑量月份；必須逐字採用 mileage_km，不可自行重算或杜撰。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "nearing_end_of_life",
            "description": "以 JSON 找出接近壽命的現役鞋；剩餘里程、使用率與是否需要補鞋均由後端判定。",
            "parameters": {
                "type": "object",
                "properties": {
                    "threshold": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "description": "提醒門檻，0.8 代表達預期壽命 80%。",
                    }
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_shoes",
            "description": "以 JSON 比較兩雙鞋；壽命、剩餘里程與每公里成本均由後端計算。",
            "parameters": {
                "type": "object",
                "properties": {
                    "shoe_a": {"type": "string", "description": "第一雙鞋的品牌或鞋款名稱。"},
                    "shoe_b": {"type": "string", "description": "第二雙鞋的品牌或鞋款名稱。"},
                },
                "required": ["shoe_a", "shoe_b"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shoe_category_status",
            "description": "以 JSON 分析用途覆蓋與補鞋需求；也可指定鞋款取得退役後的後端判定。",
            "parameters": {
                "type": "object",
                "properties": {
                    "shoe_name": {"type": "string", "description": "選填，指定品牌或鞋款名稱。"}
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "以 JSON 搜尋市售跑鞋、規格、評價或價格，結果欄位為 title、snippet、url；只在需要外部資訊時使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "具體搜尋關鍵字。"}
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
]


# ── 舊文字工具呼叫相容層（原生 tool calling 失敗時使用）──────
def parse_tool_calls(text: str) -> list[dict]:
    """Parse legacy XML markers and bare JSON tool-call fallbacks.

    Some free models ignore native function calling and emit
    ``{"tool":"web_search","arguments":{...}}`` as content. Only registered
    tool names are accepted, and identical calls are deduplicated.
    """
    import json as _json
    import re

    allowed_names = set(REGISTRY) | {"web_search"}
    positioned_calls: list[tuple[int, int, dict]] = []

    for m in re.finditer(r"<tool>\s*([A-Za-z_]+)\s*(\{.*?\})\s*</tool>", text, re.DOTALL):
        name = m.group(1)
        if name not in allowed_names:
            continue
        raw = m.group(2) or "{}"
        try:
            args = _json.loads(raw)
        except (TypeError, _json.JSONDecodeError):
            args = {}
        if not isinstance(args, dict):
            args = {}
        positioned_calls.append((m.start(), m.end(), {"name": name, "arguments": args}))

    decoder = _json.JSONDecoder()
    cursor = 0
    while True:
        start = text.find("{", cursor)
        if start == -1:
            break
        try:
            payload, consumed = decoder.raw_decode(text[start:])
        except _json.JSONDecodeError:
            cursor = start + 1
            continue
        end = start + consumed
        cursor = end
        if not isinstance(payload, dict):
            continue
        name = payload.get("tool")
        arguments = payload.get("arguments", {})
        if name in allowed_names and isinstance(arguments, dict):
            positioned_calls.append((start, end, {"name": name, "arguments": arguments}))

    out = []
    seen = set()
    for _start, _end, call in sorted(positioned_calls, key=lambda item: item[0]):
        key = (call["name"], _json.dumps(call["arguments"], sort_keys=True, ensure_ascii=False))
        if key not in seen:
            seen.add(key)
            out.append(call)
    return out


def strip_tool_markers(text: str) -> str:
    """Remove recognized XML and bare-JSON calls from user-visible reasoning."""
    import re

    cleaned = re.sub(r"<tool>.*?</tool>", "", text, flags=re.DOTALL)
    decoder = json.JSONDecoder()
    spans = []
    cursor = 0
    allowed_names = set(REGISTRY) | {"web_search"}
    while True:
        start = cleaned.find("{", cursor)
        if start == -1:
            break
        try:
            payload, consumed = decoder.raw_decode(cleaned[start:])
        except json.JSONDecodeError:
            cursor = start + 1
            continue
        end = start + consumed
        cursor = end
        if isinstance(payload, dict) and payload.get("tool") in allowed_names:
            spans.append((start, end))
    for start, end in reversed(spans):
        cleaned = cleaned[:start] + cleaned[end:]
    return cleaned.strip()
