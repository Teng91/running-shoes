"""Shoe inventory, lifecycle and identity read models (no tool serialization)."""

from sqlalchemy.orm import Session

from backend import analytics, models
from backend.read_models.shoe_matching import resolve_shoe
from backend.schemas import SHOE_CATEGORIES
from backend.shoe_metrics import shoe_metrics


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

    usage_percent = _round(shoe_metrics(shoe)["usage_percent"], 1)
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
def list_my_shoes(db: Session, user_id: int) -> dict:
    shoes = (
        db.query(models.Shoe)
        .filter(models.Shoe.user_id == user_id, models.Shoe.is_deleted.is_(False))
        .order_by(models.Shoe.is_retired, models.Shoe.date.desc())
        .all()
    )
    return dict(
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


def shoe_summary(db: Session, user_id: int) -> dict:
    shoes = (
        db.query(models.Shoe)
        .filter(models.Shoe.user_id == user_id, models.Shoe.is_deleted.is_(False))
        .all()
    )
    active = [s for s in shoes if not s.is_retired]
    retired = [s for s in shoes if s.is_retired]
    active_lifecycle = sorted(
        (_shoe_data(shoe) for shoe in active),
        key=lambda item: item["usage_percent"] if item["usage_percent"] is not None else -1,
        reverse=True,
    )
    return dict(
        ok=True,
        total_shoe_count=len(shoes),
        active_shoe_count=len(active),
        retired_shoe_count=len(retired),
        all_shoes_accumulated_mileage_km=_round(sum(s.mileage or 0 for s in shoes)),
        active_shoes_purchase_price_twd=_round(sum(s.price or 0 for s in active)),
        active_shoes_original_price_twd=_round(sum(s.orig_price or 0 for s in active)),
        active_shoes_lifecycle=active_lifecycle,
    )


def nearing_end_of_life(db: Session, user_id: int, threshold: float = 0.8) -> dict:
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
                other.id != s.id and category in (other.categories or []) for other in shoes
            )
            for category in target_categories
        }
        uncovered_categories = [
            category for category, count in category_coverage.items() if count == 0
        ]
        all_categories_covered = bool(target_categories) and not uncovered_categories
        other_active_same_category = sum(
            other.id != s.id
            and any(cat in (other.categories or []) for cat in (s.categories or []))
            for other in shoes
        )
        results.append(
            {
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
            }
        )
    return dict(
        ok=True,
        threshold_fraction=_round(threshold, 3),
        threshold_percent=_round(threshold * 100, 1),
        matching_shoe_count=len(results),
        shoes=results,
    )


def compare_shoes(
    db: Session,
    user_id: int,
    shoe_a: str = "",
    shoe_b: str = "",
    *,
    shoe_a_id: int | None = None,
    shoe_b_id: int | None = None,
) -> dict:
    """比較目前使用者的兩雙鞋，名稱可用「品牌 鞋款」或其中一段文字。"""
    shoes = (
        db.query(models.Shoe)
        .filter(models.Shoe.user_id == user_id, models.Shoe.is_deleted.is_(False))
        .all()
    )

    first, first_error = resolve_shoe(shoes, shoe_a, shoe_a_id)
    second, second_error = resolve_shoe(shoes, shoe_b, shoe_b_id)
    for error in (first_error, second_error):
        if error and error["error"] == "ambiguous_shoe":
            return error
    if not first or not second:
        missing = []
        if not first:
            missing.append(f"shoe_a={shoe_a or '未提供'}")
        if not second:
            missing.append(f"shoe_b={shoe_b or '未提供'}")
        return dict(
            ok=False,
            error="shoe_not_found",
            missing_queries=missing,
            available_shoes=[f"{s.brand} {s.model}" for s in shoes],
        )
    if first.id == second.id:
        return dict(
            ok=False,
            error="same_shoe_selected",
            matched_shoe=f"{first.brand} {first.model}",
        )

    def details(shoe: models.Shoe) -> dict:
        metrics = shoe_metrics(shoe)
        return {
            **_shoe_data(shoe),
            "actual_cost_per_completed_km_twd": metrics["cost_per_km"],
            "projected_cost_per_lifespan_km_twd": metrics["expected_cost_per_km"],
        }

    return dict(ok=True, shoe_a=details(first), shoe_b=details(second))


def shoe_category_status(
    db: Session, user_id: int, shoe_name: str = "", *, shoe_id: int | None = None
) -> dict:
    """分析鞋款用途的現役覆蓋，以及指定鞋款退役後是否要補鞋。

    一雙鞋可對應多個用途（例如 Daily + Tempo）。退役分析會檢查該鞋
    涵蓋的每個類別是否還有其他現役鞋作為替代。
    """
    shoes = (
        db.query(models.Shoe)
        .filter(models.Shoe.user_id == user_id, models.Shoe.is_deleted.is_(False))
        .all()
    )
    active = [s for s in shoes if not s.is_retired]
    retired = [s for s in shoes if s.is_retired]

    if shoe_name or shoe_id is not None:
        target, error = resolve_shoe(shoes, shoe_name, shoe_id)
        if error and error["error"] == "ambiguous_shoe":
            return error
        if not target:
            return dict(ok=False, error="shoe_not_found", query=shoe_name)
        target_cats = [
            category for category in (target.categories or []) if category in SHOE_CATEGORIES
        ]
        if not target_cats:
            return dict(
                ok=True,
                mode="specific_shoe",
                shoe=_shoe_data(target),
                category_status="categories_not_configured",
            )

        coverage = []
        for cat in target_cats:
            backup = [s for s in active if s.id != target.id and cat in (s.categories or [])]
            coverage.append(
                {
                    "category": cat,
                    "other_active_shoe_count": len(backup),
                    "covered_after_target_retirement": bool(backup),
                    "other_active_shoes": [f"{s.brand} {s.model}" for s in backup],
                }
            )
        all_covered = all(
            any(s.id != target.id and cat in (s.categories or []) for s in active)
            for cat in target_cats
        )
        return dict(
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
        coverage.append(
            {
                "category": category,
                "active_shoe_count": active_count,
                "retired_shoe_count": retired_count,
                "has_active_coverage": active_count > 0,
                "purchase_recommendation": (
                    "no_purchase_needed"
                    if active_count > 0
                    else "category_missing_consider_purchase"
                ),
            }
        )
    return dict(ok=True, mode="all_categories", categories=coverage)


def shoe_usage_analytics(
    db: Session, user_id: int, shoe_name: str = "", *, shoe_id: int | None = None
) -> dict:
    """Return deterministic run-log usage and retirement forecasts per shoe."""
    query = db.query(models.Shoe).filter(
        models.Shoe.user_id == user_id,
        models.Shoe.is_deleted.is_(False),
    )
    shoes = query.all()
    if shoe_name.strip() or shoe_id is not None:
        selected, error = resolve_shoe(shoes, shoe_name, shoe_id)
        if error:
            return error
        shoes = [selected] if selected is not None else []
    results = []
    for shoe, payload in zip(
        shoes, analytics.batch_shoe_analytics(db, user_id, shoes, include_details=False), strict=True
    ):
        life = payload["lifecycle"]
        usage = payload["usage"]
        results.append(
            {
                "shoe_id": shoe.id,
                "shoe": f"{shoe.brand} {shoe.model}",
                "status": "retired" if shoe.is_retired else "active",
                "total_mileage_km": life["total_mileage_km"],
                "logged_mileage_km": life["logged_mileage_km"],
                "historical_adjustment_km": life["historical_adjustment_km"],
                "wear_count": usage["count"],
                "last_run_date": usage["last_run_date"],
                "km_30_days": usage["km_30_days"],
                "km_90_days": usage["km_90_days"],
                "actual_monthly_km_90_days": usage["actual_monthly_km_90_days"],
                "forecast_retirement_date": life["forecast_retirement_date"],
                "forecast_source": life["forecast_source"],
            }
        )
    return dict(ok=True, shoe_count=len(results), shoes=results)
