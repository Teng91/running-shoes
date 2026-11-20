"""月報統計與提示詞：後端計算數字，LLM adapter 使用此唯讀快照。

與 agent.py 的差別：不走 agent loop、不提供工具。所有數字由後端
計算後以 JSON 餵給模型，LLM 只負責把數字寫成文字（zh-TW markdown）。
生成身分與保存由 application service 管理；本模組只提供統計及提示詞。
已保存報告由 GET endpoint 讀取，不必重打 LLM。
"""

import json
from datetime import date

from sqlalchemy.orm import Session

from backend import models
from backend.clock import local_today
from backend.read_models import goal_progress
from backend.read_models import mileage as mileage_stats
from backend.read_models import shoes as shoe_stats
from backend.read_models.rounding import round_metric
from backend.read_models.run_statistics import month_bounds, period_distances, run_period

REPORT_SECTIONS = ["本月總覽", "趨勢解讀", "鞋款壽命與退役提醒", "下月建議"]


def _month_run_stats(
    db: Session,
    user_id: int,
    year: int,
    month: int,
    *,
    through_date: str | None = None,
) -> dict:
    """以跑步日誌（runs）為準計算單月統計；0 跑量月份也要回傳合法結構。"""
    start, end = month_bounds(year, month)
    query = (
        db.query(models.Run)
        .filter(models.Run.user_id == user_id, models.Run.date >= start, models.Run.date <= end)
    )
    if through_date is not None:
        query = query.filter(models.Run.date <= through_date)
    runs = query.all()
    total_km = round_metric(sum(r.km for r in runs))
    run_days = len({r.date for r in runs})
    per_shoe: dict[int, float] = {}
    per_shoe_count: dict[int, int] = {}
    shoe_names: dict[int, str] = {}
    if runs:
        shoe_rows = (
            db.query(models.Shoe.id, models.Shoe.brand, models.Shoe.model)
            .filter(
                models.Shoe.user_id == user_id,
                models.Shoe.id.in_({r.shoe_id for r in runs}),
            )
            .all()
        )
        shoe_names = {row.id: f"{row.brand} {row.model}" for row in shoe_rows}
        for run in runs:
            per_shoe[run.shoe_id] = per_shoe.get(run.shoe_id, 0.0) + run.km
            per_shoe_count[run.shoe_id] = per_shoe_count.get(run.shoe_id, 0) + 1

    totals = sorted(per_shoe.items(), key=lambda pair: pair[1], reverse=True)
    shoe_breakdown = [
        {
            "shoe": shoe_names[shoe_id],
            "km": round_metric(km),
            "wear_count": per_shoe_count[shoe_id],
        }
        for shoe_id, km in totals
    ]
    primary = (
        {"shoe": shoe_breakdown[0]["shoe"], "km": shoe_breakdown[0]["km"]}
        if shoe_breakdown else None
    )

    return {
        "month_km": total_km,
        "run_count": len(runs),
        "run_days": run_days,
        "primary_shoe": primary,
        "runs_per_shoe": shoe_breakdown,
    }


def _shoe_context(shoe: dict) -> dict:
    keys = (
        "brand",
        "model",
        "categories",
        "status",
        "mileage_km",
        "expected_lifespan_km",
        "remaining_mileage_km",
        "usage_percent",
        "lifecycle_status",
    )
    return {key: shoe.get(key) for key in keys if key in shoe}


def _end_of_life_context(shoe: dict) -> dict:
    return {
        **_shoe_context(shoe),
        "uncovered_categories": shoe.get("uncovered_categories", []),
        "replacement_recommendation": shoe.get("replacement_recommendation"),
    }


def build_report_stats(
    db: Session,
    user_id: int,
    year: int,
    month: int,
    *,
    today: date | None = None,
) -> dict:
    """組出餵給 LLM 與存入 stats_json 的精簡統計快照。"""
    as_of = today or local_today()
    period = run_period(year, month, as_of)
    distances = period_distances(db, user_id, period)
    month_stats = _month_run_stats(db, user_id, year, month, through_date=period.month_end)
    prev_km = distances["previous_km"]
    ytd_km = distances["ytd_km"]
    comparison_label = period.comparison_label
    comparison_through_day = period.comparison_day

    mileage_payload = mileage_stats.monthly_mileage_stats(db, user_id)
    mileage_keys = (
        "status",
        "recorded_month_count",
        "nonzero_month_count",
        "total_mileage_km",
        "overall_nonzero_month_average_km",
        "recent_period_month_count",
        "recent_period_total_km",
        "recent_period_average_km",
        "recent_vs_overall_trend",
        "latest_record",
        "recent_nonzero_months",
    )
    overall = {key: mileage_payload.get(key) for key in mileage_keys}

    shoes_payload = shoe_stats.list_my_shoes(db, user_id)
    shoes_context = [_shoe_context(shoe) for shoe in shoes_payload.get("shoes", [])]

    end_of_life_payload = shoe_stats.nearing_end_of_life(db, user_id)
    end_of_life = [
        _end_of_life_context(shoe) for shoe in end_of_life_payload.get("shoes", [])
    ]

    return {
        "report_month": {"year": year, "month": month},
        "month_run_stats": month_stats,
        "prev_month_run_km": prev_km,
        "prev_month_delta_km": round_metric(month_stats["month_km"] - prev_km),
        "comparison_label": comparison_label,
        "comparison_through_day": comparison_through_day,
        "ytd_run_km": ytd_km,
        "running_goal": goal_progress.goal_progress(db, user_id, year, month, as_of=as_of, distances=distances),
        "overall_monthly_stats": overall,
        "shoes": shoes_context,
        "nearing_end_of_life": end_of_life,
    }


def build_report_messages(stats: dict) -> list[dict]:
    sections = "、".join(f"「{name}」" for name in REPORT_SECTIONS)
    system = (
        "你是專業的跑步教練與跑鞋顧問，請用繁體中文撰寫一份月度跑步報告。\n"
        f"報告必須包含以下章節，依序使用 markdown 標題：{sections}。\n"
        "規則：\n"
        "1. 所有數字只能使用使用者訊息中提供的 JSON 數據，不得自行計算、估算或杜撰。\n"
        "2. JSON 中沒有的資訊（如天氣、心率或其他未記錄的訓練欄位）一律不提。\n"
        "3. 里程與壽命數據逐字採用 JSON 欄位值，單位為公里（km）。\n"
        "4. 鞋款壽命與退役提醒只參考 nearing_end_of_life，不提供輪替或購鞋建議。\n"
        "5. 下月建議必須具體可行，若當月沒有任何跑步紀錄請如實說明並鼓勵使用者。\n"
        "6. running_goal.active 為 true 時，必須說明當月與年度目標達成率及差距。"
        "當 month_state 為 current 時，也要依 pace_delta_km 說明進度超前或落後，"
        "並參考 remaining_days 與 required_daily_km；為 false 時不得套用目標。\n"
        "7. 語氣親切務實，總長度控制在 600 字以內。"
        "\n排版格式：\n"
        "- 不要輸出一級標題（#），開頭先用 markdown 引用（>）寫一行『本月一句話摘要』。\n"
        "- 接著用 markdown 表格整理 3 到 6 個 JSON 已提供的關鍵指標；沒有的指標不要補。\n"
        "- 四個指定章節一律使用二級標題（##），段落以短句與條列為主。\n"
        "- 關鍵數字可用粗體標示，但不要使用 HTML、程式碼區塊或額外章節。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(stats, ensure_ascii=False)},
    ]
