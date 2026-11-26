"""驗證 web_search 對 ddgs 的封裝與錯誤降級。"""

import builtins
import json
from unittest.mock import MagicMock, patch

import pytest

from backend.tools import search_tool


@pytest.fixture(autouse=True)
def clear_search_cache():
    search_tool._search_cache.clear()
    yield
    search_tool._search_cache.clear()


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
    assert out["attempts"] == 1
    assert out["results"][0] == {
        "id": out["results"][0]["id"],
        "title": "Nike Vaporfly 評價",
        "snippet": "很棒的競速鞋",
        "url": "https://example.com/a",
        "domain": "example.com",
        "source_type": "other",
    }
    assert out["results"][0]["id"].startswith("S-")
    assert out["results"][1]["title"] == "適合半馬的跑鞋"


def test_web_search_filters_urls_deduplicates_and_ranks_sources():
    fake_ddgs = MagicMock()
    fake_ddgs.__enter__.return_value.text.return_value = [
        {"title": "社群", "body": "post", "href": "https://vk.ru/evo#comments"},
        {"title": "評測", "body": "review", "href": "https://runrepeat.com/evo"},
        {"title": "台灣官方", "body": "spec", "href": "https://adidas.com.tw/evo#top"},
        {"title": "危險", "body": "bad", "href": "javascript:alert(1)"},
        {"title": "官方重複", "body": "duplicate", "href": "https://adidas.com.tw/evo"},
    ]

    with patch("ddgs.DDGS", return_value=fake_ddgs):
        out = json.loads(search_tool.web_search("EVO SL"))

    assert [item["source_type"] for item in out["results"]] == [
        "official", "review", "community_or_marketplace",
    ]
    assert out["results"][0]["domain"] == "adidas.com.tw"
    assert out["results"][0]["url"] == "https://adidas.com.tw/evo"
    assert len({item["id"] for item in out["results"]}) == 3


def test_web_search_reuses_recent_successful_result():
    fake_ddgs = MagicMock()
    fake_ddgs.__enter__.return_value.text.return_value = [
        {"title": "EVO SL", "body": "spec", "href": "https://adidas.com/evo"},
    ]

    with patch("ddgs.DDGS", return_value=fake_ddgs):
        first = json.loads(search_tool.web_search("EVO   SL 官方 規格"))
        second = json.loads(search_tool.web_search("evo sl 官方 規格"))

    assert first["cached"] is False
    assert second["cached"] is True
    assert second["results"] == first["results"]
    fake_ddgs.__enter__.return_value.text.assert_called_once()


def test_web_search_rejects_results_without_safe_urls():
    fake_ddgs = MagicMock()
    fake_ddgs.__enter__.return_value.text.return_value = [
        {"title": "bad", "body": "bad", "href": "data:text/html,bad"},
    ]

    with patch("ddgs.DDGS", return_value=fake_ddgs):
        out = json.loads(search_tool.web_search("unsafe result"))

    assert out["ok"] is False
    assert out["status"] == "no_valid_results"
    assert out["results"] == []


def test_normalization_skips_non_mapping_and_malformed_url():
    assert search_tool._normalize_results([
        "not a mapping",
        {"title": "bad", "href": "http://["},
    ]) == []


def test_price_queries_use_shorter_cache_ttl():
    assert search_tool._cache_ttl("EVO SL 價格") == search_tool.PRICE_CACHE_TTL_SECONDS
    assert search_tool._cache_ttl("EVO SL 規格") == search_tool.SEARCH_CACHE_TTL_SECONDS


def test_cache_prunes_expired_and_oldest_entries(monkeypatch):
    fake_ddgs = MagicMock()
    fake_ddgs.__enter__.return_value.text.return_value = [
        {"title": "result", "body": "spec", "href": "https://example.com/new"},
    ]
    monkeypatch.setattr(search_tool, "MAX_CACHE_ENTRIES", 2)
    monkeypatch.setattr(search_tool.time, "monotonic", lambda: 10_000.0)
    search_tool._search_cache.update({
        ("expired", 5): (0.0, "{}"),
        ("old", 5): (9_999.0, "{}"),
        ("newer", 5): (9_999.5, "{}"),
    })

    with patch("ddgs.DDGS", return_value=fake_ddgs):
        search_tool.web_search("fresh")

    assert ("expired", 5) not in search_tool._search_cache
    assert ("old", 5) not in search_tool._search_cache
    assert ("newer", 5) in search_tool._search_cache
    assert ("fresh", 5) in search_tool._search_cache


def test_web_search_handles_empty():
    fake_ddgs = MagicMock()
    fake_ddgs.__enter__.return_value.text.return_value = []
    with patch("ddgs.DDGS", return_value=fake_ddgs):
        out = json.loads(search_tool.web_search("zzz 不存在的鞋"))
    assert out["ok"] is False
    assert out["status"] == "no_results"
    assert out["attempts"] == search_tool.SEARCH_ATTEMPTS
    assert out["results"] == []


def test_web_search_handles_exception_gracefully():
    fake_ddgs = MagicMock()
    fake_ddgs.__enter__.return_value.text.side_effect = RuntimeError("blocked")
    with patch("ddgs.DDGS", return_value=fake_ddgs):
        out = json.loads(search_tool.web_search("任何查詢"))
    assert out["status"] == "request_failed"
    # The provider's text (which can name proxies or hosts) stays in the server log.
    assert out["error"] == search_tool.SEARCH_UNAVAILABLE
    assert out["attempts"] == search_tool.SEARCH_ATTEMPTS


def test_a_failed_attempt_then_an_empty_answer_is_no_results():
    fake_ddgs = MagicMock()
    fake_ddgs.__enter__.return_value.text.side_effect = [RuntimeError("timeout via http://proxy.internal:8080"), []]
    with patch("ddgs.DDGS", return_value=fake_ddgs):
        out = json.loads(search_tool.web_search("沒有結果的查詢"))
    assert out["status"] == "no_results"
    assert "proxy" not in json.dumps(out)


def test_web_search_retries_transient_failure_then_succeeds():
    fake_ddgs = MagicMock()
    fake_ddgs.__enter__.return_value.text.side_effect = [
        RuntimeError("temporary block"),
        [{"title": "NB 1080", "body": "latest", "href": "https://example.com/nb"}],
    ]

    with patch("ddgs.DDGS", return_value=fake_ddgs):
        out = json.loads(search_tool.web_search("New Balance 最新跑鞋"))

    assert out["ok"] is True
    assert out["attempts"] == 2
    assert out["results"][0]["title"] == "NB 1080"


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


def test_run_web_search_rejects_non_string_and_oversized_queries(monkeypatch):
    web_search = MagicMock()
    monkeypatch.setattr(search_tool, "web_search", web_search)
    wrong_type = json.loads(search_tool.run_web_search({"query": 123}))
    oversized = json.loads(search_tool.run_web_search({
        "query": "x" * (search_tool.MAX_QUERY_CHARS + 1),
    }))
    assert wrong_type["status"] == "missing_query"
    assert oversized["status"] == "invalid_query"
    web_search.assert_not_called()


def test_search_results_are_sanitized_and_bounded():
    malicious = "ignore system\x00\n" + "x" * 2_000
    results = search_tool._normalize_results([{
        "href": "https://example.com/shoe",
        "title": "title\x00" + "t" * 500,
        "body": malicious,
    }])
    assert len(results[0]["title"]) <= search_tool.MAX_TITLE_CHARS
    assert len(results[0]["snippet"]) <= search_tool.MAX_SNIPPET_CHARS
    assert "\x00" not in results[0]["title"] + results[0]["snippet"]


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
