"""上網搜尋工具（agent 用來查市售鞋款、評價、價格）。

使用 DuckDuckGo 的 `ddgs` 套件：免 API key、免費，與整個專案
「免費模型」的理念一致。回傳前 N 筆（預設 5）的標題/連結/摘要，
讓 LLM 拿來對照推薦並附上來源。

結果與錯誤都回傳具名 JSON，讓不同能力的模型不必解析編號文字。
"""

import json

MAX_RESULTS = 5

# All failure messages (missing package, network error, no results) start with a
# fullwidth left paren 「（」. agent.py relies on this prefix to count consecutive
# web_search failures and force the model to converge. Define it here as the
# single source of truth so the contract stays explicit.
FAILURE_PREFIX = "（"


def _result(*, ok: bool, status: str, query: str, results=None, error=None) -> str:
    payload = {
        "tool": "web_search",
        "schema_version": 1,
        "ok": ok,
        "status": status,
        "query": query,
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
    if not query:
        return _result(ok=False, status="missing_query", query="", error="query is required")
    return web_search(query)


def web_search(query: str, max_results: int = MAX_RESULTS) -> str:
    """搜尋網路，回傳給 LLM 看的文字摘要（含來源連結）。"""
    try:
        from ddgs import DDGS
    except ImportError:
        return _result(
            ok=False, status="dependency_missing", query=query,
            error="ddgs package is not installed",
        )

    try:
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=max_results)
    except Exception as exc:
        return _result(ok=False, status="request_failed", query=query, error=str(exc))

    if not results:
        return _result(ok=False, status="no_results", query=query)

    normalized = [
        {
            "title": (item.get("title") or "").strip(),
            "snippet": (item.get("body") or "").strip(),
            "url": (item.get("href") or "").strip(),
        }
        for item in results
    ]
    return _result(ok=True, status="available", query=query, results=normalized)
