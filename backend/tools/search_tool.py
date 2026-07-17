"""上網搜尋工具（agent 用來查市售鞋款、評價、價格）。

使用 DuckDuckGo 的 `ddgs` 套件：免 API key、免費，與整個專案
「免費模型」的理念一致。回傳前 N 筆（預設 5）的標題/連結/摘要，
讓 LLM 拿來對照推薦並附上來源。

若 `ddgs` 呼叫失敗（被擋/網路錯），回傳一段說明文字而不是噴例外，
讓 agent 能優雅降級（只靠現有資料回答）。
"""

MAX_RESULTS = 5


def web_search(query: str, max_results: int = MAX_RESULTS) -> str:
    """搜尋網路，回傳給 LLM 看的文字摘要（含來源連結）。"""
    try:
        from ddgs import DDGS
    except ImportError:
        return "（搜尋工具未安裝：缺少 ddgs 套件）"

    try:
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=max_results)
    except Exception as exc:
        return f"（網路搜尋暫時失敗：{exc}；請改用你現有的跑鞋資料回答。）"

    if not results:
        return f"（沒有找到與「{query}」相關的結果）"

    lines = [f"網路搜尋「{query}」結果："]
    for i, r in enumerate(results, 1):
        title = (r.get("title") or "").strip()
        body = (r.get("body") or "").strip()
        href = (r.get("href") or "").strip()
        lines.append(f"{i}. {title}\n   {body}\n   來源：{href}")
    return "\n".join(lines)


def run_web_search(arguments: dict) -> str:
    query = (arguments or {}).get("query", "")
    if not query:
        return "（web_search 需要 query 參數）"
    return web_search(query)


# 工具說明統一由 db_tools.TOOL_SPEC_TEXT 提供（文字標記格式），
# 這裡不再維護 OpenAI 格式的 schema。

