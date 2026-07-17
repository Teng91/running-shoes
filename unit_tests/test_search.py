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
