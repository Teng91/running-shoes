"""上網搜尋工具（agent 用來查市售鞋款、評價、價格）。

使用 DuckDuckGo 的 `ddgs` 套件：免 API key、免費，與整個專案
「免費模型」的理念一致。回傳前 N 筆（預設 5）的標題/連結/摘要，
讓 LLM 拿來對照推薦並附上來源。

結果與錯誤都回傳具名 JSON，讓不同能力的模型不必解析編號文字。
"""

import json
import time
from datetime import UTC, datetime
from hashlib import sha256
from threading import Lock
from typing import Any
from urllib.parse import urlsplit, urlunsplit

MAX_RESULTS = 5
SEARCH_ATTEMPTS = 2
SEARCH_CACHE_TTL_SECONDS = 15 * 60
PRICE_CACHE_TTL_SECONDS = 5 * 60
MAX_CACHE_ENTRIES = 256
MAX_QUERY_CHARS = 500
MAX_TITLE_CHARS = 300
MAX_SNIPPET_CHARS = 1_000
MAX_URL_CHARS = 2_048
MAX_TOTAL_RESULT_CHARS = 6_000

_search_cache: dict[tuple[str, int], tuple[float, str]] = {}
_search_cache_lock = Lock()

_OFFICIAL_DOMAINS = (
    "adidas.com", "newbalance.com", "nike.com", "asics.com", "puma.com",
    "mizuno.com", "hoka.com", "saucony.com", "brooksrunning.com",
    "adidas.com.tw", "newbalance.com.tw", "nike.com.tw", "asics.com.tw",
    "puma.com.tw", "mizuno.com.tw", "hoka.com.tw", "saucony.com.tw",
)
_REVIEW_DOMAINS = (
    "runrepeat.com", "roadtrailrun.com", "doctorsofrunning.com",
    "believeintherun.com", "runnersworld.com", "solereview.com",
    "runningwarehouse.com",
)
_LOW_PRIORITY_DOMAINS = (
    "vk.ru", "facebook.com", "instagram.com", "tiktok.com", "x.com",
    "reddit.com", "shopee.", "amazon.", "ebay.",
)
_PRICE_TERMS = ("price", "taiwan", "市價", "售價", "價格", "定價", "優惠", "折扣")

# All failure messages (missing package, network error, no results) start with a
# fullwidth left paren 「（」. agent.py relies on this prefix to count consecutive
# web_search failures and force the model to converge. Define it here as the
# single source of truth so the contract stays explicit.
FAILURE_PREFIX = "（"


def _result(
    *,
    ok: bool,
    status: str,
    query: str,
    results=None,
    error=None,
    attempts: int = 1,
    cached: bool = False,
) -> str:
    payload = {
        "tool": "web_search",
        "schema_version": 1,
        "ok": ok,
        "status": status,
        "query": query,
        "attempts": attempts,
        "cached": cached,
        "searched_at": datetime.now(UTC).isoformat(),
        "results": results or [],
    }
    if error:
        payload["error"] = error
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def is_failure(result: str) -> bool:
    """True for structured failures and legacy text failures."""
    try:
        payload = json.loads(result)
    except (TypeError, json.JSONDecodeError):
        return result.lstrip().startswith(FAILURE_PREFIX)
    return payload.get("tool") == "web_search" and payload.get("ok") is False


def run_web_search(arguments: dict) -> str:
    query = (arguments or {}).get("query", "")
    if not isinstance(query, str) or not query.strip():
        return _result(ok=False, status="missing_query", query="", error="query is required")
    query = " ".join(query.split())
    if len(query) > MAX_QUERY_CHARS:
        return _result(
            ok=False,
            status="invalid_query",
            query=query[:MAX_QUERY_CHARS],
            error=f"query must be at most {MAX_QUERY_CHARS} characters",
        )
    return web_search(query)


def _normalize_url(raw_url: str) -> str | None:
    if len(raw_url) > MAX_URL_CHARS:
        return None
    try:
        parsed = urlsplit((raw_url or "").strip())
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, parsed.query, "")
    )


def _domain(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def _source_type(domain: str) -> str:
    if any(domain == item or domain.endswith("." + item) for item in _OFFICIAL_DOMAINS):
        return "official"
    if any(domain == item or domain.endswith("." + item) for item in _REVIEW_DOMAINS):
        return "review"
    if any(item in domain for item in _LOW_PRIORITY_DOMAINS):
        return "community_or_marketplace"
    return "other"


def _source_rank(domain: str, source_type: str) -> tuple[int, int]:
    type_rank = {
        "official": 0,
        "review": 2,
        "other": 3,
        "community_or_marketplace": 5,
    }[source_type]
    taiwan_rank = 0 if domain.endswith(".tw") or domain.startswith("tw.") else 1
    return type_rank, taiwan_rank


def _normalize_results(results) -> list[dict[str, str]]:
    normalized = []
    seen_urls = set()
    total_chars = 0

    def clean_text(value, limit: int) -> str:
        text = " ".join(str(value or "").split())
        text = "".join(char for char in text if char >= " " or char == "\n")
        return text[:limit]

    for position, item in enumerate(results or []):
        if not isinstance(item, dict):
            continue
        url = _normalize_url(str(item.get("href") or ""))
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        domain = _domain(url)
        source_type = _source_type(domain)
        title = clean_text(item.get("title") or domain, MAX_TITLE_CHARS)
        snippet = clean_text(item.get("body"), MAX_SNIPPET_CHARS)
        remaining = MAX_TOTAL_RESULT_CHARS - total_chars
        if remaining <= 0:
            break
        title = title[:remaining]
        snippet = snippet[:max(0, remaining - len(title))]
        total_chars += len(title) + len(snippet)
        normalized.append({
            "id": "S-" + sha256(url.encode("utf-8")).hexdigest()[:8],
            "title": title,
            "snippet": snippet,
            "url": url,
            "domain": domain,
            "source_type": source_type,
            "_position": str(position),
        })
    normalized.sort(
        key=lambda item: (
            *_source_rank(item["domain"], item["source_type"]),
            int(item["_position"]),
        )
    )
    for item in normalized:
        item.pop("_position", None)
    return normalized


def _cache_ttl(query: str) -> int:
    lowered = query.casefold()
    if any(term in lowered for term in _PRICE_TERMS):
        return PRICE_CACHE_TTL_SECONDS
    return SEARCH_CACHE_TTL_SECONDS


def web_search(query: str, max_results: int = MAX_RESULTS) -> str:
    """搜尋網路，回傳已驗證、排序且帶穩定來源 ID 的 JSON。"""
    normalized_query = " ".join(query.split())
    cache_key = (normalized_query.casefold(), max_results)
    now = time.monotonic()
    cached = _cached_result(cache_key, normalized_query, now)
    if cached is not None:
        return cached

    try:
        from ddgs import DDGS
    except ImportError:
        return _result(
            ok=False, status="dependency_missing", query=normalized_query,
            error="ddgs package is not installed",
        )

    results, last_error, attempts = _search_with_retry(DDGS, normalized_query, max_results)
    if not results:
        if last_error is not None:
            return _result(
                ok=False,
                status="request_failed",
                query=normalized_query,
                error=last_error[:500],
                attempts=attempts,
            )
        return _result(
            ok=False,
            status="no_results",
            query=normalized_query,
            attempts=attempts,
        )

    normalized = _normalize_results(results)
    if not normalized:
        return _result(
            ok=False,
            status="no_valid_results",
            query=normalized_query,
            attempts=attempts,
        )
    output = _result(
        ok=True,
        status="available",
        query=normalized_query,
        results=normalized,
        attempts=attempts,
    )
    _remember_result(cache_key, now, output)
    return output


def _cached_result(cache_key: tuple[str, int], normalized_query: str, now: float) -> str | None:
    """A fresh cached answer for the same query, marked as cached."""
    with _search_cache_lock:
        cached_entry = _search_cache.get(cache_key)
        if cached_entry and now - cached_entry[0] < _cache_ttl(normalized_query):
            payload = json.loads(cached_entry[1])
            payload["cached"] = True
            return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return None


def _search_with_retry(ddgs_class: Any, normalized_query: str, max_results: int) -> tuple[list, str | None, int]:
    """Results, the last provider error and the attempts made, stopping at the first results."""
    results: list = []
    last_error = None
    attempts = 0
    for attempt in range(1, SEARCH_ATTEMPTS + 1):
        attempts = attempt
        try:
            with ddgs_class() as ddgs:
                results = ddgs.text(normalized_query, max_results=max_results)
        # Search providers can intermittently reject or time out a request.
        # Retry once inside the tool so weak models do not need to invent a
        # second query merely to recover from a transient provider failure.
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            continue
        if results:
            break
    return results, last_error, attempts


def _remember_result(cache_key: tuple[str, int], now: float, output: str) -> None:
    """Cache a successful answer, dropping expired entries and the oldest one when full."""
    with _search_cache_lock:
        expired = [
            key for key, (saved_at, _) in _search_cache.items()
            if now - saved_at >= _cache_ttl(key[0])
        ]
        for key in expired:
            _search_cache.pop(key, None)
        if len(_search_cache) >= MAX_CACHE_ENTRIES:
            oldest_key = min(_search_cache, key=lambda key: _search_cache[key][0])
            _search_cache.pop(oldest_key, None)
        _search_cache[cache_key] = (now, output)
