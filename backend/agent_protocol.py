"""SSE serialization and safe web-source summaries for the Agent UI."""

import json
import re
from typing import Any

from backend.tools.search_tool import is_failure


def sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def search_payload(output: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(output)
    except (TypeError, json.JSONDecodeError):
        return None
    return payload if payload.get("tool") == "web_search" else None


def source_summary_event(
    search_payloads: list[dict[str, Any]], *, limit: int = 8
) -> str:
    if not search_payloads:
        return sse({
            "type": "source_summary",
            "web": {"status": "none", "queries": [], "result_count": 0, "sources": []},
        })
    successful = [payload for payload in search_payloads if payload.get("ok") is True]
    status = (
        "failed" if not successful
        else "cached" if all(payload.get("cached") is True for payload in successful)
        else "live"
    )
    sources: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for payload in successful:
        query_tokens = {
            token for token in re.findall(
                r"[a-z0-9]+", str(payload.get("query") or "").casefold()
            ) if token not in {"official", "price", "review", "taiwan"}
        }
        for source in payload.get("results") or []:
            source_id = str(source.get("id") or "")
            if not source_id or source_id in seen_ids:
                continue
            seen_ids.add(source_id)
            searchable = " ".join((
                str(source.get("title") or ""), str(source.get("snippet") or ""),
                str(source.get("url") or ""),
            )).casefold()
            sources.append({
                "id": source_id,
                "title": str(source.get("title") or source.get("domain") or source_id),
                "url": str(source.get("url") or ""),
                "domain": str(source.get("domain") or ""),
                "source_type": str(source.get("source_type") or "other"),
                "_relevance": str(sum(token in searchable for token in query_tokens)),
            })
    rank = {"official": 0, "review": 1, "other": 2, "community_or_marketplace": 3}
    sources.sort(key=lambda source: (
        -int(source["_relevance"]), rank.get(source["source_type"], 2),
        0 if source["domain"].endswith(".tw") else 1,
    ))
    sources = sources[:limit]
    for source in sources:
        source.pop("_relevance", None)
    return sse({
        "type": "source_summary",
        "web": {
            "status": status,
            "queries": [str(payload.get("query") or "") for payload in search_payloads],
            "result_count": len(sources),
            "sources": sources,
        },
    })


def tool_done_event(name: str, output: str) -> str:
    event: dict[str, Any] = {"type": "tool_done", "name": name, "ok": True}
    try:
        payload = json.loads(output)
    except (TypeError, json.JSONDecodeError):
        payload = None
    structured_failure = isinstance(payload, dict) and payload.get("ok") is False
    if name != "web_search" and not structured_failure:
        return sse(event)
    if name == "web_search" and not is_failure(output):
        return sse(event)
    event["ok"] = False
    if not isinstance(payload, dict):
        event.update({"status": "request_failed", "message": "搜尋服務暫時無法使用"})
        return sse(event)
    status = str(payload.get("status") or "request_failed")
    messages = {
        "dependency_missing": "搜尋套件未安裝", "missing_query": "缺少搜尋關鍵字",
        "invalid_query": "搜尋關鍵字格式不正確", "no_results": "找不到相關搜尋結果",
        "no_valid_results": "搜尋結果沒有可安全使用的網址",
        "request_failed": "搜尋服務暫時無法連線",
        "invalid_arguments": "模型提供的工具參數格式不正確",
        "tool_execution_failed": "資料工具執行失敗",
    }
    event.update({"status": status, "message": messages.get(status, "搜尋失敗")})
    if payload.get("error"):
        event["error"] = str(payload["error"])
    return sse(event)
