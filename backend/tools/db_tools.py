"""Thin JSON tool adapters; computation lives in shared read models."""

import json
from collections.abc import Callable

from sqlalchemy.orm import Session

from backend import models
from backend.clock import local_today
from backend.read_models import (
    goal_progress,
    highlights,
    mileage,
    race_plan,
    shoes,
    spending,
    trends,
)
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


WEEKDAY_NAMES = ("週一", "週二", "週三", "週四", "週五", "週六", "週日")
SPENDING_RECENT_MONTHS = 12


def _shoe_names(db: Session, user_id: int) -> dict[int, str]:
    rows = db.query(models.Shoe.id, models.Shoe.brand, models.Shoe.model, models.Shoe.is_deleted).filter(
        models.Shoe.user_id == user_id
    )
    return {shoe_id: f"{brand} {model}" + ("（已刪除）" if deleted else "") for shoe_id, brand, model, deleted in rows}


def running_goal_progress(db: Session, user_id: int, year: int | None = None) -> str:
    today = local_today()
    overview = goal_progress.year_goal_overview(db, user_id, year or today.year, as_of=today)
    return _json_result(
        "running_goal_progress",
        ok=True,
        field_definitions={
            "monthly_km": "每月目標里程",
            "yearly_km": "年度目標里程（每月目標 × 12）",
            "ytd_km": "年度累計已跑里程",
            "year_expected_km_to_date": "依年度目標，今天應累計的里程",
            "year_pace_delta_km": "年度累計減應有進度；正數代表超前",
            "months": "每月逐筆日誌里程與是否達標（met）",
            "required_weekly_km": "年底前每週還需要的里程；只在進行中的年份提供",
        },
        **overview,
    )


def training_trends(db: Session, user_id: int, year: int | None = None) -> str:
    today = local_today()
    data = trends.training_trends(db, user_id, year or today.year, today)
    cumulative = data["cumulative"]
    return _json_result(
        "training_trends",
        ok=True,
        year=data["year"],
        end_date=data["end_date"],
        run_days=len(data["daily"]),
        streaks=data["streaks"],
        weekly_goal=data["weekly_goal"],
        thresholds=data["thresholds"],
        field_definitions={
            "weekly": "近 16 週（週一起算）的跑量、4 週平均、相對前 4 週的變化百分比與最長一次",
            "spike": "比前 4 週平均多 thresholds.spike_percent% 以上的週次，代表跑量增加太快",
            "goal_met": "該週跑量是否達到 weekly_goal.km（年度目標 × 7 ÷ 全年天數）",
            "partial": "進行中、尚未結束的一週",
            "weekday": "這一年每個星期幾的總里程、有跑步的天數（run_days）、跑步次數（runs）與平均配速（pace，每公里秒數，總時間 ÷ 有時間的距離；沒有時間為 null）",
        },
        weekly=data["weekly"],
        weekday=[{**row, "name": WEEKDAY_NAMES[row["weekday"]]} for row in data["weekday"]],
        cumulative={key: cumulative[key] for key in (
            "goal_active", "yearly_goal_km", "ytd_km", "expected_km", "delta_km", "projected_km",
        )},
    )


def year_review(db: Session, user_id: int, year: int | None = None) -> str:
    today = local_today()
    review = highlights.year_review(db, user_id, year or today.year, today)
    names = _shoe_names(db, user_id)
    for key in ("longest_run", "top_shoe"):
        if isinstance(review.get(key), dict):
            review[key] = {**review[key], "shoe_name": names.get(review[key]["shoe_id"], "未知鞋款")}
    return _json_result(
        "year_review",
        ok=True,
        field_definitions={
            "complete": "false 代表年份進行中，數字統計到 end_date",
            "previous_year_km": "前一年同期（1/1 到 previous_year_end）的里程",
            "shoe_spend": "這一年購買的鞋款花費",
            "cost_per_km": "當年買鞋花費 ÷ 當年跑量",
        },
        **review,
    )


def spending_summary(db: Session, user_id: int) -> str:
    summary = spending.spending_summary(db, user_id)
    monthly = summary.get("monthly", [])
    return _json_result(
        "spending_summary",
        ok=True,
        field_definitions={
            "total_paid": "現有跑鞋（含退役、不含已刪除）的實際花費合計",
            "average_discount_percent": "實付 ÷ 原價 × 100；75 代表約 7.5 折",
            "recent_monthly": f"最近 {SPENDING_RECENT_MONTHS} 個有買鞋的月份",
        },
        **{key: value for key, value in summary.items() if key != "monthly"},
        recent_monthly=monthly[-SPENDING_RECENT_MONTHS:],
    )


def race_training_plan(db: Session, user_id: int) -> str:
    preparation = race_plan.race_preparation(db, user_id, local_today())
    if preparation["goal"] is None:
        return _json_result("race_training_plan", ok=True, goal=None,
                            message="尚未設定目標賽事；請到訓練分析分頁的「比賽準備」按「設定比賽」。")
    return _json_result(
        "race_training_plan",
        ok=True,
        field_definitions={
            "days_left": "距離比賽的天數，負數代表已結束",
            "goal_pace": "目標配速，每公里秒數",
            "zones": "依目標配速劃分的強度區間（每公里秒數）；min_pace 是快的一端",
            "prediction": "依參考成績以 Riegel 公式預估的完賽時間；margin_seconds 正數代表比目標快",
            "long_runs": "近 8 週長距離（≥ 比賽距離 75%）的次數與是否足夠",
            "plan.weeks": "每週課表：km 是建議週跑量、long_km 是建議最長一次、zone_runs 是該週有填時間的路跑落在各強度區間（zones）的次數；"
                          "phase 為 build（累積）、recovery（恢復週）、peak（高峰）、taper（減量）、race（比賽週）",
            "plan.weeks.status": "done 達成、partial 部分完成、missed 未達、current 本週進行中、upcoming 未開始",
            "plan.weeks.quality_runs": "該週建議在各強度區間（zones）跑幾次，其餘都是輕鬆跑；與 zone_runs 的實際次數對照",
            "plan.weeks.adjusted": "true 代表前兩週不到建議跑量的 6 成，這週起改從實際跑量重新累積；已開始的週不會再變，之後的週跟著調整",
            "plan.baseline_km": "課表開始前 4 週的平均週跑量，課表由此每週最多增加 10%",
            "plan.weeks_total": "課表週數（含比賽週）；weeks_chosen 為 false 時沿用距離預設的 default_weeks，使用者可在比賽設定改成 4～24 週",
            "plan.long_below_threshold": "true 代表依目前跑量，課表的最長一次仍不到比賽距離的 75%",
            "plan.long_weeks_needed": "最長一次不足時，課表改成幾週就排得到（仍從本週以後開始）；null 代表拉長也不夠",
            "plan.long_base_needed_km": "最長一次不足且課表尚未開始時，平常週跑量提高到幾 km 就排得到；null 代表不適用",
            "plan": "比賽結束後為 null",
        },
        **{key: value for key, value in preparation.items() if key != "intensity"},
        intensity_zones=preparation["intensity"]["zones"],
    )


REGISTRY: dict[str, Callable[..., str]] = {
    "list_my_shoes": list_my_shoes,
    "shoe_summary": shoe_summary,
    "monthly_mileage_stats": monthly_mileage_stats,
    "nearing_end_of_life": nearing_end_of_life,
    "compare_shoes": compare_shoes,
    "shoe_category_status": shoe_category_status,
    "shoe_usage_analytics": shoe_usage_analytics,
    "running_goal_progress": running_goal_progress,
    "training_trends": training_trends,
    "year_review": year_review,
    "spending_summary": spending_summary,
    "race_training_plan": race_training_plan,
}


def parse_tool_calls(text: str) -> list[dict]:
    return legacy_calls.parse_tool_calls(text, set(REGISTRY) | {"web_search"})


def strip_tool_markers(text: str) -> str:
    return legacy_calls.strip_tool_markers(text, set(REGISTRY) | {"web_search"})
