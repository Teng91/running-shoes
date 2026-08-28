"""驗證 DB 工具的結構化輸出、後端計算，以及 user 隔離。"""

import json

from backend import agent
from backend.models import MonthlyMileage, Shoe, User
from backend.tools import db_tools


def _result(raw: str) -> dict:
    return json.loads(raw)


def test_shoe_summary_counts(seeded_db):
    db, uid = seeded_db
    out = _result(db_tools.shoe_summary(db, uid))
    assert out["tool"] == "shoe_summary"
    assert out["total_shoe_count"] == 5
    assert out["active_shoe_count"] == 4
    assert out["retired_shoe_count"] == 1
    sky = next(shoe for shoe in out["active_shoes_lifecycle"] if shoe["model"] == "Wave Sky 7")
    assert sky["mileage_km"] == 540
    assert sky["remaining_mileage_km"] == 260
    assert sky["usage_percent"] == 67.5


def test_nearing_end_of_life_flags_worn_shoe(seeded_db):
    db, uid = seeded_db
    # Wave Sky 7: 540/800 = 67.5%；threshold 0.5 應觸發
    out = _result(db_tools.nearing_end_of_life(db, uid, threshold=0.5))
    sky = next(shoe for shoe in out["shoes"] if shoe["model"] == "Wave Sky 7")
    assert sky["lifecycle_status"] == "healthy"
    assert sky["usage_percent"] == 67.5


def test_nearing_end_of_life_distinguishes_90_percent_and_category_coverage(seeded_db):
    db, uid = seeded_db
    shoe = Shoe(
        user_id=uid, brand="PUMA", model="Deviate Nitro", date="2026-01-01",
        mileage=460, expected_mileage=500, monthly_km=30, categories=["Race"],
    )
    db.add(shoe)
    db.commit()
    out = _result(db_tools.nearing_end_of_life(db, uid))
    shoe_out = out["shoes"][0]
    assert shoe_out["model"] == "Deviate Nitro"
    assert shoe_out["lifecycle_status"] == "replace_soon"
    assert shoe_out["remaining_mileage_km"] == 40
    assert shoe_out["has_active_category_replacement"] is False
    assert shoe_out["replacement_recommendation"] == "prepare_replacement_purchase"


def test_lifecycle_marks_80_to_90_percent_for_monitoring(seeded_db):
    db, uid = seeded_db
    sky = db.query(Shoe).filter(Shoe.user_id == uid, Shoe.model == "Wave Sky 7").one()
    sky.mileage = 680  # 85% of 800 km
    db.commit()

    out = _result(db_tools.list_my_shoes(db, uid))
    shoe_out = next(shoe for shoe in out["shoes"] if shoe["model"] == "Wave Sky 7")
    assert shoe_out["usage_percent"] == 85
    assert shoe_out["remaining_mileage_km"] == 120
    assert shoe_out["lifecycle_status"] == "monitor"


def test_nearing_end_of_life_none_below_threshold(seeded_db):
    db, uid = seeded_db
    # 最高才 67.5%，0.9 不該觸發
    out = _result(db_tools.nearing_end_of_life(db, uid, threshold=0.9))
    assert out["matching_shoe_count"] == 0
    assert out["shoes"] == []


def test_agent_passes_nearing_end_of_life_threshold(seeded_db):
    db, uid = seeded_db
    out = _result(agent._execute_tool("nearing_end_of_life", {"threshold": 0.5}, db, uid))
    assert out["threshold_fraction"] == 0.5
    assert any(shoe["model"] == "Wave Sky 7" for shoe in out["shoes"])


def test_compare_shoes_returns_both_shoes(seeded_db):
    db, uid = seeded_db
    out = _result(db_tools.compare_shoes(db, uid, "Wave Sky 7", "Wave Rider 29"))
    assert out["ok"] is True
    assert out["shoe_a"]["model"] == "Wave Sky 7"
    assert out["shoe_b"]["model"] == "Wave Rider 29"
    assert out["shoe_a"]["actual_cost_per_completed_km_twd"] == 4.43


def test_compare_shoes_is_user_isolated(seeded_db):
    db, _uid = seeded_db
    other = User(username="stranger", hashed_password="x")
    db.add(other)
    db.commit()
    out = _result(db_tools.compare_shoes(db, other.id, "Wave Sky 7", "Wave Rider 29"))
    assert out["ok"] is False
    assert out["error"] == "shoe_not_found"
    assert out["available_shoes"] == []


def test_shoe_category_status_detects_replacement_need(seeded_db):
    db, uid = seeded_db
    out = _result(db_tools.shoe_category_status(db, uid))
    categories = {item["category"]: item for item in out["categories"]}
    assert categories["Daily"]["active_shoe_count"] == 2
    assert categories["Race"]["active_shoe_count"] == 0
    assert categories["Race"]["retired_shoe_count"] == 0
    assert categories["Race"]["purchase_recommendation"] == "category_missing_consider_purchase"


def test_shoe_category_status_checks_specific_retirement(seeded_db):
    db, uid = seeded_db
    out = _result(db_tools.shoe_category_status(db, uid, "Wave Sky 7"))
    assert out["coverage_after_target_retirement"][0]["other_active_shoe_count"] == 1
    assert out["all_categories_remain_covered"] is True
    assert out["purchase_recommendation"] == "no_purchase_needed"


def test_shoe_category_status_includes_trail(seeded_db):
    db, uid = seeded_db
    shoe = Shoe(
        user_id=uid, brand="Salomon", model="Sense Ride", date="2026-01-01",
        mileage=500, expected_mileage=500, categories=["Trail"],
    )
    db.add(shoe)
    db.commit()
    out = _result(db_tools.shoe_category_status(db, uid, "Sense Ride"))
    assert out["shoe"]["model"] == "Sense Ride"
    assert out["coverage_after_target_retirement"][0]["category"] == "Trail"
    assert out["all_categories_remain_covered"] is False
    assert out["purchase_recommendation"] == "prepare_replacement_purchase"


def test_shoe_category_status_counts_walk(seeded_db):
    """Walk is a valid category in the analysis tuple (frontend allows selecting it)."""
    db, uid = seeded_db
    shoe = Shoe(
        user_id=uid, brand="Nike", model="Free RN", date="2026-01-01",
        categories=["Walk"],
    )
    db.add(shoe)
    db.commit()
    out = _result(db_tools.shoe_category_status(db, uid))
    walk = next(item for item in out["categories"] if item["category"] == "Walk")
    assert walk["active_shoe_count"] == 1
    assert walk["has_active_coverage"] is True


def test_shoe_category_status_multi_category_counts_for_all_purposes(seeded_db):
    """A shoe with multiple categories (e.g. Daily+Tempo) is counted in BOTH
    the Speed and Tempo category tallies — not just the first one."""
    db, uid = seeded_db
    shoe = Shoe(
        user_id=uid, brand="Hoka", model="Mach 6", date="2026-06-01",
        categories=["Speed", "Tempo"],
    )
    db.add(shoe)
    db.commit()
    out = _result(db_tools.shoe_category_status(db, uid))
    categories = {item["category"]: item for item in out["categories"]}
    assert categories["Speed"]["active_shoe_count"] == 2
    assert categories["Tempo"]["active_shoe_count"] == 2
    assert categories["Trail"]["active_shoe_count"] == 0


def test_nearing_end_of_life_requires_backup_for_every_category(seeded_db):
    """One shared category must not hide an uncovered second category."""
    db, uid = seeded_db
    shoe = Shoe(
        user_id=uid, brand="Saucony", model="Endorphin", date="2026-01-01",
        mileage=460, expected_mileage=500, monthly_km=30,
        categories=["Daily", "Trail"],
    )
    db.add(shoe)
    db.commit()
    out = _result(db_tools.nearing_end_of_life(db, uid, threshold=0.8))
    result = next(shoe for shoe in out["shoes"] if shoe["model"] == "Endorphin")
    assert result["usage_percent"] == 92
    assert result["has_active_category_replacement"] is False
    assert result["all_categories_have_active_replacement"] is False
    assert result["uncovered_categories"] == ["Trail"]
    assert result["category_replacement_coverage"] == {"Daily": 2, "Trail": 0}
    assert result["replacement_recommendation"] == "prepare_replacement_purchase"
    assert result["active_replacement_count_sharing_any_category"] == 2


def test_monthly_mileage_stats(seeded_db):
    db, uid = seeded_db
    out = _result(db_tools.monthly_mileage_stats(db, uid))
    assert out["status"] == "available"
    assert out["total_mileage_km"] == 747.48
    assert out["recent_period_total_km"] == 747.48
    assert out["latest_record"] == {"year": 2026, "month": 6, "mileage_km": 128.2}
    assert out["recent_nonzero_months"][1]["mileage_km"] == 135.91


def test_list_my_shoes_includes_all(seeded_db):
    db, uid = seeded_db
    out = _result(db_tools.list_my_shoes(db, uid))
    assert out["shoe_count"] == 5
    models = {shoe["model"] for shoe in out["shoes"]}
    assert {"Wave Sky 7", "Boston 12"} <= models
    sky = next(shoe for shoe in out["shoes"] if shoe["model"] == "Wave Sky 7")
    assert sky["assigned_monthly_km"] == 60
    assert sky["mileage_km"] == 540
    assert sky["remaining_mileage_km"] == 260
    assert "不是累積里程" in out["field_definitions"]["assigned_monthly_km"]


def test_isolation_other_user_sees_nothing(seeded_db):
    db, _uid = seeded_db
    other = User(username="stranger", hashed_password="x")
    db.add(other)
    db.commit()
    db.refresh(other)
    assert _result(db_tools.shoe_summary(db, other.id))["total_shoe_count"] == 0
    assert _result(db_tools.list_my_shoes(db, other.id))["shoes"] == []
    mileage = _result(db_tools.monthly_mileage_stats(db, other.id))
    assert mileage["status"] == "no_records"
    assert mileage["recent_nonzero_months"] == []


def test_parse_tool_calls_extracts_markers():
    text = (
        "我查一下：\n"
        "<tool>nearing_end_of_life {\"threshold\": 0.8}</tool>\n"
        "還有：<tool>web_search {\"query\": \"半馬 跑鞋\"}</tool>\n"
        "以上是依據。"
    )
    calls = db_tools.parse_tool_calls(text)
    assert len(calls) == 2
    assert calls[0]["name"] == "nearing_end_of_life"
    assert calls[0]["arguments"] == {"threshold": 0.8}
    assert calls[1]["name"] == "web_search"
    assert calls[1]["arguments"]["query"] == "半馬 跑鞋"


def test_tool_edge_cases_for_missing_lifespan_and_zero_mileage(seeded_db):
    db, uid = seeded_db
    zero_life = Shoe(
        user_id=uid,
        brand="Zero",
        model="No Target",
        date="2026-01-01",
        expected_mileage=0,
        categories=[],
    )
    db.add(zero_life)
    for row in db.query(MonthlyMileage).filter(MonthlyMileage.user_id == uid):
        row.km = 0
    db.commit()

    shoes = _result(db_tools.list_my_shoes(db, uid))["shoes"]
    no_target = next(shoe for shoe in shoes if shoe["model"] == "No Target")
    assert no_target["expected_lifespan_km"] is None
    assert no_target["remaining_mileage_km"] is None
    assert no_target["lifecycle_status"] == "lifespan_not_configured"
    assert _result(db_tools.monthly_mileage_stats(db, uid))["status"] == "all_months_zero"
    near = _result(db_tools.nearing_end_of_life(db, uid, threshold=0))
    assert all(shoe["model"] != "No Target" for shoe in near["shoes"])
    category = _result(db_tools.shoe_category_status(db, uid, "No Target"))
    assert category["category_status"] == "categories_not_configured"


def test_compare_and_category_lookup_edge_cases(seeded_db):
    db, uid = seeded_db
    missing_both = _result(db_tools.compare_shoes(db, uid, "", ""))
    assert missing_both["missing_queries"] == ["shoe_a=未提供", "shoe_b=未提供"]
    missing_b = _result(db_tools.compare_shoes(db, uid, "Wave Sky 7", "不存在"))
    assert missing_b["missing_queries"] == ["shoe_b=不存在"]
    missing_a = _result(db_tools.compare_shoes(db, uid, "不存在", "Wave Sky 7"))
    assert missing_a["missing_queries"] == ["shoe_a=不存在"]
    same = _result(db_tools.compare_shoes(db, uid, "Mizuno Wave Sky 7", "Wave Sky 7"))
    assert same["error"] == "same_shoe_selected"
    not_found = _result(db_tools.shoe_category_status(db, uid, "不存在的鞋"))
    assert not_found["error"] == "shoe_not_found"


def test_parse_invalid_tool_json_and_strip_markers():
    calls = db_tools.parse_tool_calls("<tool>web_search {not-json}</tool>")
    assert calls == [{"name": "web_search", "arguments": {}}]
    assert db_tools.strip_tool_markers(
        "前文\n<tool>shoe_summary {}</tool>\n後文"
    ) == "前文\n\n後文"


def test_parse_bare_json_tool_calls_deduplicates_and_ignores_provider_errors():
    call = (
        '{"tool":"web_search","arguments":'
        '{"query":"New Balance Rebel v1"}}'
    )
    text = (
        f"準備搜尋 {call} {call} "
        '{"tool":"tool_call_error","arguments":{"error":"not found"}} 完成'
    )

    assert db_tools.parse_tool_calls(text) == [
        {
            "name": "web_search",
            "arguments": {"query": "New Balance Rebel v1"},
        }
    ]
    assert db_tools.strip_tool_markers(text) == (
        "準備搜尋   "
        '{"tool":"tool_call_error","arguments":{"error":"not found"}} 完成'
    )


def test_parse_bare_json_rejects_unknown_tools_and_non_object_arguments():
    text = (
        '{"tool":"delete_everything","arguments":{}} '
        '{"tool":"web_search","arguments":[]} '
        '{"tool":"shoe_summary","arguments":{}}'
    )

    assert db_tools.parse_tool_calls(text) == [
        {"name": "shoe_summary", "arguments": {}}
    ]


def test_native_tool_definitions_match_dispatchable_tools():
    names = {
        definition["function"]["name"]
        for definition in db_tools.TOOL_DEFINITIONS
    }
    assert names == set(db_tools.REGISTRY) | {"web_search"}
    for definition in db_tools.TOOL_DEFINITIONS:
        function = definition["function"]
        assert definition["type"] == "function"
        assert function["description"]
        assert function["parameters"]["type"] == "object"
