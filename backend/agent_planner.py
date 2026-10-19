"""Deterministic intent detection and minimum Agent query planning."""

import re
from dataclasses import dataclass

_TOOL_INTENT_TERMS = (
    "跑鞋", "鞋", "鞋款", "鞋況", "鞋櫃", "跑量", "里程", "壽命", "退役",
    "換鞋", "補鞋", "推薦", "比較", "分析", "課表", "訓練", "馬拉松", "半馬",
    "全馬", "比賽", "競速", "越野", "daily", "tempo", "speed", "race", "trail",
    "資料", "數字", "結果", "重新查", "不對", "錯了", "類別", "缺什麼", "搜尋",
    "查詢", "幫我查", "上網", "search", "new balance", "nb", "rebel",
)
AFFIRMATIVE_REPLIES = (
    "對", "對的", "好", "好的", "是", "是的", "沒錯", "可以", "查吧", "幫我查",
    "對，查吧", "對,查吧", "好，查吧", "好,查吧",
)
_CONTEXT_TOOL_TERMS = ("搜尋", "查詢", "查", "工具", "資料")
_NON_TOOL_REPLIES = ("謝謝", "感謝", "不用了", "沒事", "再見")
_WEB_RESEARCH_TERMS = (
    "市價", "售價", "價格", "定價", "評價", "規格", "上市", "哪裡買", "哪裡有",
    "通路", "折扣", "優惠", "查網路", "上網查",
)
_SHOE_RESEARCH_QUESTIONS = ("怎樣的鞋", "怎麼樣的鞋", "適合我", "值得買", "值得入手", "好穿嗎")
_PERSONAL_FIT_TERMS = ("適合我", "適不適合我", "我適合", "適合我的")
_PRIVATE_DATA_TERMS = (
    "我的跑量", "我最新的月跑量", "我的月跑量", "我的里程", "我的跑鞋", "我的鞋",
    "我的鞋櫃", "我目前", "我的資料", "跑鞋里程", "月跑量", "鞋櫃", "鞋況", "退役", "壽命",
)
_MONTHLY_DATA_TERMS = ("月跑量", "跑量", "跑量趨勢")
_SHOE_DATA_TERMS = ("我的跑鞋", "我的鞋", "鞋櫃", "鞋況", "跑鞋里程")
_LIFECYCLE_TERMS = ("壽命", "退役", "快壞", "換鞋", "剩餘里程")
_CATEGORY_TERMS = ("缺什麼", "缺少", "類別", "覆蓋", "補鞋")
_USAGE_ANALYTICS_TERMS = (
    "穿幾次", "穿著次數", "使用次數", "輪替", "平均距離", "最後穿", "最近里程", "實際月跑量",
)
_PRODUCT_FRESHNESS_TERMS = (
    "跑鞋", "鞋款", "new balance", "nb", "nike", "adidas", "asics", "mizuno", "puma",
    "hoka", "brooks", "saucony", "rebel", "elite",
)


@dataclass(frozen=True)
class QueryPlan:
    web_queries: tuple[str, ...] = ()
    database_tools: tuple[str, ...] = ()


def should_offer_tools(user_message: str, history: list[dict] | None = None) -> bool:
    normalized = " ".join(user_message.lower().split())
    if any(term in normalized for term in _TOOL_INTENT_TERMS):
        return True
    if any(term in normalized for term in _NON_TOOL_REPLIES):
        return False
    recent_assistant = next((
        str(turn.get("content", "")).lower()
        for turn in reversed(history or []) if turn.get("role") == "assistant"
    ), "")
    if normalized.strip("！!。,.？?") in AFFIRMATIVE_REPLIES:
        return any(term in recent_assistant for term in _CONTEXT_TOOL_TERMS)
    recent_user = next((
        str(turn.get("content", "")).lower()
        for turn in reversed(history or []) if turn.get("role") == "user"
    ), "")
    return any(term in recent_user for term in _TOOL_INTENT_TERMS)


def requires_web_search(user_message: str) -> bool:
    normalized = " ".join(user_message.lower().split())
    is_personal_data = any(term in normalized for term in _PRIVATE_DATA_TERMS) and any(
        marker in normalized for marker in ("我", "我的", "目前", "最近")
    )
    if is_personal_data:
        return any(term in normalized for term in _WEB_RESEARCH_TERMS)
    if any(term in normalized for term in _WEB_RESEARCH_TERMS):
        return True
    if "最新" in normalized and any(term in normalized for term in _PRODUCT_FRESHNESS_TERMS):
        return True
    if any(term in normalized for term in _SHOE_RESEARCH_QUESTIONS):
        return True
    has_model_like_token = bool(re.search(r"[a-z]{2,}[^\n]{0,30}\d", normalized))
    return has_model_like_token and normalized.rstrip("？?!！。 ").endswith("呢")


def search_subject(user_message: str) -> str:
    subject = user_message.strip()
    for phrase in (
        "幫我查", "查一下", "查", "適合我嗎", "適不適合我", "適合我", "是一雙怎樣的鞋",
        "是一雙怎麼樣的鞋", "怎樣的鞋", "怎麼樣的鞋", "值得買嗎", "值得入手嗎", "好穿嗎",
        "最新評價", "市價",
    ):
        subject = subject.replace(phrase, " ")
    tokens = subject.strip("？?!！。,.，～~ ").split()
    return " ".join(token for token in tokens if token not in {"的", "與", "和"}) or user_message.strip()


def build_query_plan(user_message: str, history: list[dict] | None = None) -> QueryPlan:
    effective_message = user_message
    normalized = " ".join(user_message.casefold().split()).strip("？?!！。,.， ")
    if normalized in AFFIRMATIVE_REPLIES:
        recent_user = next((
            str(turn.get("content", "")) for turn in reversed(history or [])
            if turn.get("role") == "user" and turn.get("content")
        ), "")
        recent_assistant = next((
            str(turn.get("content", "")).casefold() for turn in reversed(history or [])
            if turn.get("role") == "assistant"
        ), "")
        if recent_user and any(term in recent_assistant for term in _CONTEXT_TOOL_TERMS):
            effective_message = recent_user
    lowered = effective_message.casefold()
    web_queries: tuple[str, ...] = ()
    if requires_web_search(effective_message):
        subject = search_subject(effective_message)
        web_queries = (f"{subject} 官方 規格", f"{subject} 評價 價格 台灣")
    database_tool_list: list[str] = []
    has_personal_marker = any(marker in lowered for marker in ("我", "我的", "目前", "最近"))
    if has_personal_marker:
        needs_usage = any(term in lowered for term in _USAGE_ANALYTICS_TERMS)
        if any(term in lowered for term in _SHOE_DATA_TERMS) and not needs_usage:
            database_tool_list.append("list_my_shoes")
        if any(term in lowered for term in _MONTHLY_DATA_TERMS):
            database_tool_list.append("monthly_mileage_stats")
        if any(term in lowered for term in _LIFECYCLE_TERMS):
            database_tool_list.append("nearing_end_of_life")
        if any(term in lowered for term in _CATEGORY_TERMS):
            database_tool_list.append("shoe_category_status")
        if needs_usage:
            database_tool_list.append("shoe_usage_analytics")
    if any(term in lowered for term in _PERSONAL_FIT_TERMS):
        database_tool_list.extend(("list_my_shoes", "monthly_mileage_stats"))
    return QueryPlan(
        web_queries=web_queries,
        database_tools=tuple(dict.fromkeys(database_tool_list)),
    )
