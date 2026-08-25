"""驗證 web_search 對 ddgs 的封裝與錯誤降級。"""

import builtins
import json
from unittest.mock import MagicMock, patch

from backend.tools import search_tool


def test_web_search_formats_results():
    fake_ddgs = MagicMock()
    fake_ddgs.__enter__.return_value.text.return_value = [
        {"title": "Nike Vaporfly 評價", "body": "很棒的競速鞋", "href": "https://example.com/a"},
        {"title": "適合半馬的跑鞋", "body": "推薦輕量款", "href": "https://example.com/b"},
    ]
    with patch("ddgs.DDGS", return_value=fake_ddgs):
        out = json.loads(search_tool.web_search("半馬 跑鞋 推薦"))
    assert out["ok"] is True
    assert out["status"] == "available"
    assert out["results"][0] == {
        "title": "Nike Vaporfly 評價",
        "snippet": "很棒的競速鞋",
        "url": "https://example.com/a",
    }
    assert out["results"][1]["title"] == "適合半馬的跑鞋"


def test_web_search_handles_empty():
    fake_ddgs = MagicMock()
    fake_ddgs.__enter__.return_value.text.return_value = []
    with patch("ddgs.DDGS", return_value=fake_ddgs):
        out = json.loads(search_tool.web_search("zzz 不存在的鞋"))
    assert out["ok"] is False
    assert out["status"] == "no_results"
    assert out["results"] == []


def test_web_search_handles_exception_gracefully():
    fake_ddgs = MagicMock()
    fake_ddgs.__enter__.return_value.text.side_effect = RuntimeError("blocked")
    with patch("ddgs.DDGS", return_value=fake_ddgs):
        out = json.loads(search_tool.web_search("任何查詢"))
    assert out["status"] == "request_failed"
    assert out["error"] == "blocked"


def test_is_failure_flags_all_failure_modes():
    """agent.py counts consecutive web_search failures via is_failure(); every
    non-success branch of web_search must be recognised, and a real result must not."""
    assert search_tool.is_failure("（搜尋工具未安裝：缺少 ddgs 套件）")
    assert search_tool.is_failure("（沒有找到與「x」相關的結果）")
    assert search_tool.is_failure("（web_search 需要 query 參數）")
    assert search_tool.is_failure("（網路搜尋暫時失敗：blocked；請改用你現有的跑鞋資料回答。）")
    assert not search_tool.is_failure("網路搜尋「半馬 跑鞋 推薦」結果：\n1. ...")
    assert search_tool.is_failure(search_tool.run_web_search({}))
    assert not search_tool.is_failure(json.dumps({"tool": "web_search", "ok": True}))
    assert not search_tool.is_failure(json.dumps({"tool": "another_tool", "ok": False}))


def test_run_web_search_validates_and_delegates(monkeypatch):
    missing = json.loads(search_tool.run_web_search({}))
    assert missing["status"] == "missing_query"
    web_search = MagicMock(return_value="results")
    monkeypatch.setattr(search_tool, "web_search", web_search)
    assert search_tool.run_web_search({"query": "daily trainer"}) == "results"
    web_search.assert_called_once_with("daily trainer")


def test_web_search_handles_missing_ddgs_package(monkeypatch):
    original_import = builtins.__import__

    def fail_ddgs_import(name, *args, **kwargs):
        if name == "ddgs":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_ddgs_import)
    out = json.loads(search_tool.web_search("跑鞋"))
    assert out["status"] == "dependency_missing"
    assert out["error"] == "ddgs package is not installed"
