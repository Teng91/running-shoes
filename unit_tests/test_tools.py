"""驗證 DB 工具對 seed 資料的輸出，以及 user 隔離。"""

from backend import agent
from backend.tools import db_tools
from backend.models import User, Shoe


def test_shoe_summary_counts(seeded_db):
    db, uid = seeded_db
    out = db_tools.shoe_summary(db, uid)
    assert "共 5 雙" in out
    assert "使用中 4 / 已退役 1" in out
    assert "Mizuno Wave Sky 7" in out


def test_nearing_end_of_life_flags_worn_shoe(seeded_db):
    db, uid = seeded_db
    # Wave Sky 7: 540/800 = 67.5%；threshold 0.5 應觸發
    out = db_tools.nearing_end_of_life(db, uid, threshold=0.5)
    assert "Mizuno Wave Sky 7" in out
    assert "先注意這雙鞋的使用狀況" in out


def test_nearing_end_of_life_distinguishes_90_percent_and_category_coverage(seeded_db):
    db, uid = seeded_db
    shoe = Shoe(
        user_id=uid, brand="PUMA", model="Deviate Nitro", date="2026-01-01",
        mileage=460, expected_mileage=500, monthly_km=30, categories=["Race"],
    )
    db.add(shoe)
    db.commit()
    out = db_tools.nearing_end_of_life(db, uid)
    assert "Deviate Nitro" in out
    assert "可以準備換鞋" in out
    assert "同類別沒有其他現役鞋，建議準備補鞋" in out


def test_nearing_end_of_life_none_below_threshold(seeded_db):
    db, uid = seeded_db
    # 最高才 67.5%，0.9 不該觸發
    out = db_tools.nearing_end_of_life(db, uid, threshold=0.9)
    assert "暫時都不需要急著換" in out


def test_agent_passes_nearing_end_of_life_threshold(seeded_db):
    db, uid = seeded_db
    out = agent._execute_tool("nearing_end_of_life", {"threshold": 0.5}, db, uid)
    assert "Mizuno Wave Sky 7" in out


def test_compare_shoes_returns_both_shoes(seeded_db):
    db, uid = seeded_db
    out = db_tools.compare_shoes(db, uid, "Wave Sky 7", "Wave Rider 29")
    assert "Wave Sky 7" in out
    assert "Wave Rider 29" in out
    assert "每 km 成本" in out


def test_compare_shoes_is_user_isolated(seeded_db):
    db, uid = seeded_db
    other = User(username="stranger", hashed_password="x")
    db.add(other)
    db.commit()
    out = db_tools.compare_shoes(db, other.id, "Wave Sky 7", "Wave Rider 29")
    assert "找不到比較對象" in out


def test_shoe_category_status_detects_replacement_need(seeded_db):
    db, uid = seeded_db
    out = db_tools.shoe_category_status(db, uid)
    assert "Daily：現役 2 雙" in out
    assert "Race：現役 0 雙" in out
    assert "Race：現役 0 雙、退役 0 雙，需要補鞋" in out


def test_shoe_category_status_checks_specific_retirement(seeded_db):
    db, uid = seeded_db
    out = db_tools.shoe_category_status(db, uid, "Wave Sky 7")
    assert "還有 1 雙現役鞋" in out
    assert "不需要補鞋" in out


def test_shoe_category_status_includes_trail(seeded_db):
    db, uid = seeded_db
    shoe = Shoe(
        user_id=uid, brand="Salomon", model="Sense Ride", date="2026-01-01",
        mileage=500, expected_mileage=500, categories=["Trail"],
    )
    db.add(shoe)
    db.commit()
    out = db_tools.shoe_category_status(db, uid, "Sense Ride")
    assert "Trail" in out
    assert "Sense Ride" in out
    assert "尚未設定" not in out  # Trail shoe has a category, so not "unset"
    assert "補鞋" in out  # Either "不需要補鞋" or "建議準備補鞋" — tells us replacement status


def test_shoe_category_status_counts_walk(seeded_db):
    """Walk is a valid category in the analysis tuple (frontend allows selecting it)."""
    db, uid = seeded_db
    shoe = Shoe(
        user_id=uid, brand="Nike", model="Free RN", date="2026-01-01",
        categories=["Walk"],
    )
    db.add(shoe)
    db.commit()
    out = db_tools.shoe_category_status(db, uid)
    assert "Walk：現役 1 雙" in out


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
    out = db_tools.shoe_category_status(db, uid)
    # Mach 6 adds to both Speed and Tempo counts
    assert "Speed：現役 2 雙" in out       # Rebel v5 + Mach 6
    assert "Tempo：現役 2 雙" in out       # Boston 12 + Mach 6
    assert "Trail：現役 0 雙" in out       # No Trail shoes in seeded data


def test_nearing_end_of_life_multi_category_find_backup_via_shared_category(seeded_db):
    """A shoe near end-of-life that has [Daily, Tempo] categories should
    find backup coverage via any other active shoe sharing at least one category."""
    db, uid = seeded_db
    shoe = Shoe(
        user_id=uid, brand="Saucony", model="Endorphin", date="2026-01-01",
        mileage=460, expected_mileage=500, monthly_km=30,
        categories=["Daily", "Tempo"],
    )
    db.add(shoe)
    db.commit()
    out = db_tools.nearing_end_of_life(db, uid, threshold=0.8)
    # 460/500 = 92% → flagged; backup exists via shared "Daily" category
    assert "Saucony Endorphin" in out
    assert "同類別還有" in out  # Has backup via shared "Daily" category


def test_monthly_mileage_stats(seeded_db):
    db, uid = seeded_db
    out = db_tools.monthly_mileage_stats(db, uid)
    assert "總跑量" in out
    assert "趨勢" in out
    assert "2026-06" in out


def test_list_my_shoes_includes_all(seeded_db):
    db, uid = seeded_db
    out = db_tools.list_my_shoes(db, uid)
    assert "Mizuno Wave Sky 7" in out
    assert "Adidas Boston 12" in out


def test_isolation_other_user_sees_nothing(seeded_db):
    db, uid = seeded_db
    other = User(username="stranger", hashed_password="x")
    db.add(other)
    db.commit()
    db.refresh(other)
    assert "沒有任何跑鞋" in db_tools.shoe_summary(db, other.id)
    assert "沒有任何跑鞋" in db_tools.list_my_shoes(db, other.id)
    assert "沒有每月跑量" in db_tools.monthly_mileage_stats(db, other.id)


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
