"""驗證 DB 工具對 seed 資料的輸出，以及 user 隔離。"""

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
    assert "建議準備替換" in out


def test_nearing_end_of_life_none_below_threshold(seeded_db):
    db, uid = seeded_db
    # 最高才 67.5%，0.9 不該觸發
    out = db_tools.nearing_end_of_life(db, uid, threshold=0.9)
    assert "暫時都不需要急著換" in out


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


def test_strip_tool_markers_removes_tags():
    text = "Wave Sky 7 快換了。<tool>nearing_end_of_life {}</tool> 記得看預算。"
    assert "<tool>" not in db_tools.strip_tool_markers(text)
    assert "Wave Sky 7 快換了。" in db_tools.strip_tool_markers(text)
