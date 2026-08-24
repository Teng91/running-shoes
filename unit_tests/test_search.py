"""驗證 web_search 對 ddgs 的封裝與錯誤降級。"""

from unittest.mock import MagicMock, patch

from backend.tools import search_tool


def test_web_search_formats_results():
    fake_ddgs = MagicMock()
    fake_ddgs.__enter__.return_value.text.return_value = [
        {"title": "Nike Vaporfly 評價", "body": "很棒的競速鞋", "href": "https://example.com/a"},
        {"title": "適合半馬的跑鞋", "body": "推薦輕量款", "href": "https://example.com/b"},
    ]
    with patch("ddgs.DDGS", return_value=fake_ddgs):
        out = search_tool.web_search("半馬 跑鞋 推薦")
    assert "Nike Vaporfly 評價" in out
    assert "https://example.com/a" in out
    assert "適合半馬的跑鞋" in out


def test_web_search_handles_empty():
    fake_ddgs = MagicMock()
    fake_ddgs.__enter__.return_value.text.return_value = []
    with patch("ddgs.DDGS", return_value=fake_ddgs):
        out = search_tool.web_search("zzz 不存在的鞋")
    assert "沒有找到" in out


def test_web_search_handles_exception_gracefully():
    fake_ddgs = MagicMock()
    fake_ddgs.__enter__.return_value.text.side_effect = RuntimeError("blocked")
    with patch("ddgs.DDGS", return_value=fake_ddgs):
        out = search_tool.web_search("任何查詢")
    assert "暫時失敗" in out


def test_is_failure_flags_all_failure_modes():
    """agent.py counts consecutive web_search failures via is_failure(); every
    non-success branch of web_search must be recognised, and a real result must not."""
    assert search_tool.is_failure("（搜尋工具未安裝：缺少 ddgs 套件）")
    assert search_tool.is_failure("（沒有找到與「x」相關的結果）")
    assert search_tool.is_failure("（web_search 需要 query 參數）")
    assert search_tool.is_failure("（網路搜尋暫時失敗：blocked；請改用你現有的跑鞋資料回答。）")
    assert not search_tool.is_failure("網路搜尋「半馬 跑鞋 推薦」結果：\n1. ...")
