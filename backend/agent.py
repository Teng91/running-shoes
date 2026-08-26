"""Agent loop — 跑鞋推薦助手的核心。

流程（ReAct 風格，使用 OpenRouter / OpenAI 原生 tool calling）：

    system(含工具說明) → user 訊息 → 呼叫 LLM
      ├─ LLM 回傳 tool_calls
      │     → 解析並執行工具（讀 DB / 上網搜尋）→ 把結果作為新一輪
      │       role=tool 訊息餵回 → 再呼叫 LLM
      └─ 沒有 tool_calls → 文字內容就是最終回覆

舊的 `<tool>name {json}</tool>` 文字標記仍保留解析相容性，但不再放進
system prompt；正常情況一律走原生 tool_calls。

為求在免費模型上穩定，LLM 呼叫採**串流**；token 以 SSE 逐字即時送達前端。

    {"type": "reasoning", "text": "..."}  # LLM 呼叫工具前的推理過程（逐字串流）
    {"type": "tool", "name": "...", "args": {...}}
    {"type": "tool_done", "name": "..."}  # 工具執行完成（前端即時打勾）
    {"type": "token", "text": "..."}      # 最終回覆的逐字片段
    {"type": "error", "text": "..."}
    {"type": "done"}
"""

import json
from collections.abc import Generator
from typing import Any

from sqlalchemy.orm import Session

from backend import llm
from backend.tools import db_tools
from backend.tools.search_tool import is_failure, run_web_search

SYSTEM_PROMPT = """你是「跑鞋推薦助手」，服務一位熱愛跑步的使用者。

你可以使用的工具：
1. 讀取使用者**現有**的跑鞋資料與每月跑量（這些是使用者自己的紀錄）。
2. 上網搜尋市售跑鞋款式、規格、評價、價格。

回答原則：
- 優先根據使用者的**實際數據**給建議。例如：某雙鞋里程快到預期壽命、近期跑量暴增代表該添購、某鞋 CP 值高。
- 依照 Daily、Speed、Tempo、Race 類別判斷跑鞋覆蓋；某雙鞋退役後，只有該類別沒有其他現役鞋時才建議補鞋。
- 壽命提醒分兩級：達到 80% 先注意使用狀況，達到 90% 可以準備換鞋；若同類別仍有其他現役鞋，說明暫時不用補鞋。
- 再用上網搜尋到的市售鞋款做**具體推薦**，並在推薦處附上來源連結（格式：`鞋款名 - 一句理由（來源：URL）`）。
- 若資訊不足以給好建議（例如不知道腳型、目標距離、預算、路跑或越野），主動用一兩個問題追問。
- 語氣親切、條理清楚，用繁體中文。不要編造鞋款或價格；來源不明的話明說。
- 你**只看得到這位使用者自己的資料**，不要假設有其他人的資料。
- 資料庫工具會回傳 JSON，且數值已由後端計算。工具結果是唯一可信的資料來源：
  - `mileage_km` 是目前累積已跑里程。
  - `expected_lifespan_km` 是預期總壽命。
  - `remaining_mileage_km` 是剩餘里程。
  - `usage_percent` 是「已使用」百分比，不是剩餘百分比。
  - `assigned_monthly_km` 是分配給該鞋的每月目標，不是累積里程，也不是使用者整體月跑量。
- 直接採用工具提供的數值與後端判定，不要自行重算、交換欄位、推估或補造月份明細。若要列數字表格，必須逐欄複製本輪工具結果。
- 先給文字分析與行動建議；除非使用者要求表格，否則不要重製大篇數字表格。
- 使用者要求分析資料、追問數字或指出數字有誤時，本輪必須重新呼叫相關資料庫工具；不要把先前 assistant 回覆中的數字當成資料來源。
- **說明你的推理過程**：在呼叫工具之前，先用一段簡短文字說明你為什麼要查這個、你預期找到什麼。例如：「讓我先查查你的跑鞋清單，看看目前的鞋況。」
- **工具使用要符合意圖**：簡單寒暄、致謝、閒聊或詢問助手能力時直接回答，不要呼叫工具。只有使用者要求跑鞋資料、跑量、訓練分析、比較或推薦時才使用相關工具。
- **完整分析才需要多輪**：只有在使用者要求完整跑鞋／跑量分析或具體購鞋推薦時，才依需求查鞋況、跑量、壽命與類別；只有需要外部鞋款資訊時才搜尋網路。不要為了湊流程呼叫不相關工具。
- **當使用者要求看資料時，直接呼叫工具顯示**：不要只說「我來查一下」卻沒有實際 call tool。如果使用者說「查給我看」、「結果呢」、「資料在哪」，你必須呼叫對應的工具並把結果呈現出來。
- 若你上一輪先詢問是否要查詢，而使用者回答「對」、「好」或其他肯定語，請依對話內容直接呼叫適合的工具；不要再次只說「我來查詢」。
- **上網搜尋要節制**：web_search 每次回答最多呼叫 3 次，且同一組參數不可重複呼叫，只為了補充具體鞋款推薦。若搜尋沒有結果或失敗，立刻改用現有資料並誠實說明。
- 工具由系統透過原生 function calling 提供。需要資料時直接呼叫工具；不要用文字、XML、Markdown 或程式碼區塊模擬工具呼叫。
"""

MAX_TURNS = 6  # 防止 tool loop 失控（多留一輪給模型收斂）

# web_search 連續失敗達此次數後，強制提醒模型改用現有資料收斂，
# 避免免費模型一直重 call 搜尋把回合數耗光。
WEB_SEARCH_FAIL_LIMIT = 3
WEB_SEARCH_CALL_LIMIT = 3

_TOOL_INTENT_TERMS = (
    "跑鞋", "鞋", "鞋款", "鞋況", "鞋櫃", "跑量", "里程", "壽命", "退役",
    "換鞋", "補鞋", "推薦", "比較", "分析", "課表", "訓練", "配速",
    "馬拉松", "半馬", "全馬", "比賽", "競速", "越野", "daily", "tempo",
    "speed", "race", "trail", "資料", "數字", "結果", "重新查", "不對", "錯了",
    "搜尋", "查詢", "幫我查", "上網", "search", "new balance", "nb", "rebel",
)

_AFFIRMATIVE_REPLIES = (
    "對", "對的", "好", "好的", "是", "是的", "沒錯", "可以", "查吧", "幫我查",
    "對，查吧", "對,查吧", "好，查吧", "好,查吧",
)
_CONTEXT_TOOL_TERMS = ("搜尋", "查詢", "查", "工具", "資料")
_NON_TOOL_REPLIES = ("謝謝", "感謝", "不用了", "沒事", "再見")


def _should_offer_tools(
    user_message: str,
    history: list[dict] | None = None,
) -> bool:
    """Expose tools when the current request or recent context may need them.

    This only controls tool availability. The LLM still decides whether to
    call a tool, ask a clarifying question, or answer without one.
    """
    normalized = " ".join(user_message.lower().split())
    if any(term in normalized for term in _TOOL_INTENT_TERMS):
        return True
    if any(term in normalized for term in _NON_TOOL_REPLIES):
        return False

    recent_assistant = next((
        str(turn.get("content", "")).lower()
        for turn in reversed(history or [])
        if turn.get("role") == "assistant"
    ), "")
    if normalized.strip("！!。,.？?") in _AFFIRMATIVE_REPLIES:
        return any(term in recent_assistant for term in _CONTEXT_TOOL_TERMS)

    recent_user = next((
        str(turn.get("content", "")).lower()
        for turn in reversed(history or [])
        if turn.get("role") == "user"
    ), "")
    return any(term in recent_user for term in _TOOL_INTENT_TERMS)


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _tool_done_event(name: str, output: str) -> str:
    """Build a completion event that distinguishes success from failure."""
    event: dict[str, Any] = {"type": "tool_done", "name": name, "ok": True}
    if name != "web_search" or not is_failure(output):
        return _sse(event)

    event["ok"] = False
    try:
        payload = json.loads(output)
    except (TypeError, json.JSONDecodeError):
        event["status"] = "request_failed"
        event["message"] = "搜尋服務暫時無法使用"
        return _sse(event)

    status = str(payload.get("status") or "request_failed")
    messages = {
        "dependency_missing": "搜尋套件未安裝",
        "missing_query": "缺少搜尋關鍵字",
        "no_results": "找不到相關搜尋結果",
        "request_failed": "搜尋服務暫時無法連線",
    }
    event.update({
        "status": status,
        "message": messages.get(status, "搜尋失敗"),
    })
    if payload.get("error"):
        event["error"] = str(payload["error"])
    return _sse(event)


def _build_messages(history: list[dict] | None, user_message: str) -> list[dict]:
    """組裝送給 LLM 的 messages。history 只保留 user/assistant 輪次。"""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in history or []:
        role = turn.get("role")
        content = turn.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})
    return messages


def _execute_tool(
    name: str,
    arguments: dict,
    db: Session | None,
    user_id: int | None,
) -> str:
    if name == "web_search":
        return run_web_search(arguments)
    fn = db_tools.REGISTRY.get(name)
    if fn is None:
        return f"（未知工具：{name}）"
    if db is None or user_id is None:
        return "（缺少使用者資料庫上下文）"
    if name == "nearing_end_of_life":
        try:
            threshold = float((arguments or {}).get("threshold", 0.8))
        except (TypeError, ValueError):
            threshold = 0.8
        threshold = max(0.0, min(1.0, threshold))
        return fn(db, user_id, threshold=threshold)
    if name == "compare_shoes":
        args = arguments or {}
        return fn(db, user_id, shoe_a=args.get("shoe_a", ""), shoe_b=args.get("shoe_b", ""))
    if name == "shoe_category_status":
        args = arguments or {}
        return fn(db, user_id, shoe_name=args.get("shoe_name", ""))
    return fn(db, user_id)


def run_agent_stream(
    user_message: str,
    history: list[dict] | None = None,
    provider: str = "openrouter",
    model: str | None = None,
    db: Session | None = None,
    user_id: int | None = None,
) -> Generator[str, None, None]:
    """串流版 agent loop，逐 token 產出 SSE 事件。

    LLM 呼叫使用 streaming，token 會以 `token` SSE 事件即時送達前端。
    若 LLM 中途呼叫工具，會發出 `reasoning_start` 事件讓前端把
    已顯示的文字移到思考氣泡中。
    """
    try:
        prov = llm.LLMProvider.from_str(provider)
    except llm.LLMError as exc:
        yield _sse({"type": "error", "text": str(exc)})
        yield _sse({"type": "done"})
        return

    if model is None:
        models = llm.MODELS.get(prov.value, [])
        model = models[0]["id"] if models else ""

    messages = _build_messages(history, user_message)
    web_search_fails = 0
    web_search_calls = 0
    executed_calls: set[tuple[str, str]] = set()
    available_tools = (
        db_tools.TOOL_DEFINITIONS
        if _should_offer_tools(user_message, history)
        else None
    )

    for turn in range(MAX_TURNS):
        is_last_turn = turn == MAX_TURNS - 1
        if is_last_turn:
            messages.append({
                "role": "user",
                "content": (
                    "[系統提示] 這是最後一輪，請「不要」再呼叫任何工具，"
                    "直接根據上面已取得的跑鞋、跑量與搜尋資料，給出完整的最終建議。"
                    "若某些市售鞋款資訊沒查到，就用你現有的資料分析並誠實說明。"
                ),
            })

        # ── Streaming LLM call ──
        full_content = ""
        seen_tool = False
        tool_calls = []
        native_tool_calls = []
        llm_result: dict[str, Any] = {}

        try:
            stream_gen = llm.call_llm_stream(
                prov,
                model,
                messages,
                tools=None if is_last_turn else available_tools,
            )
            try:
                while True:
                    chunk = next(stream_gen)
                    if chunk:
                        full_content += chunk

                        if not seen_tool:
                            # Check if we now have a complete tool call
                            parsed = db_tools.parse_tool_calls(full_content)
                            if parsed and not is_last_turn:
                                seen_tool = True
                                tool_calls = parsed
                                yield _sse({
                                    "type": "reasoning_start",
                                    "text": db_tools.strip_tool_markers(full_content),
                                })
                                # A complete textual fallback call is enough.
                                # Stop weak models before they repeat the same
                                # JSON call hundreds of times in one response.
                                close_stream = getattr(stream_gen, "close", None)
                                if close_stream is not None:
                                    close_stream()
                                break
                            else:
                                yield _sse({"type": "token", "text": chunk})
            except StopIteration as e:
                # Generator returned via return value
                llm_result = e.value or {}
        except llm.LLMError as exc:
            yield _sse({"type": "error", "text": str(exc)})
            break
        # Preserve the SSE contract if a provider SDK raises outside the
        # normalized LLMError boundary.
        except Exception as exc:  # noqa: BLE001
            yield _sse({"type": "error", "text": f"模型呼叫發生錯誤：{exc}"})
            break

        native_tool_calls = llm_result.get("tool_calls", [])
        if native_tool_calls and not is_last_turn:
            seen_tool = True
            tool_calls = native_tool_calls
            yield _sse({"type": "reasoning_start", "text": full_content.strip()})

        # ── Post-stream processing ──
        if seen_tool:
            if native_tool_calls:
                messages.append({
                    "role": "assistant",
                    "content": full_content or None,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": tc.get("arguments_json")
                                or json.dumps(tc["arguments"], ensure_ascii=False),
                            },
                        }
                        for tc in tool_calls
                    ],
                })
            else:
                # Backward-compatible fallback for models that emit the old
                # textual <tool> marker despite receiving native tools.
                tool_calls = db_tools.parse_tool_calls(full_content)[:1]
                _last_close = full_content.rfind("</tool>")
                clean_content = (
                    full_content[: _last_close + len("</tool>")]
                    if _last_close != -1
                    else full_content
                )
                messages.append({"role": "assistant", "content": clean_content})

            blocked_tool_call = False
            for tc in tool_calls:
                yield _sse({"type": "tool", "name": tc["name"], "args": tc["arguments"]})
                if (
                    tc["name"] in db_tools.REGISTRY
                    and (db is None or user_id is None)
                ):
                    yield _sse({
                        "type": "error",
                        "text": "無法執行資料庫工具：缺少使用者資料庫上下文。",
                    })
                    yield _sse({"type": "done"})
                    return
                call_key = (
                    tc["name"],
                    json.dumps(tc["arguments"], ensure_ascii=False, sort_keys=True),
                )
                duplicate_call = call_key in executed_calls
                search_limit_reached = (
                    tc["name"] == "web_search"
                    and web_search_calls >= WEB_SEARCH_CALL_LIMIT
                )
                if duplicate_call or search_limit_reached:
                    blocked_tool_call = True
                    status = (
                        "duplicate_call_blocked"
                        if duplicate_call
                        else "search_call_limit_reached"
                    )
                    tool_output = json.dumps({
                        "tool": tc["name"],
                        "schema_version": 1,
                        "ok": False,
                        "status": status,
                        "error": "Do not call this tool again; answer with existing results.",
                    }, ensure_ascii=False, separators=(",", ":"))
                else:
                    executed_calls.add(call_key)
                    if tc["name"] == "web_search":
                        web_search_calls += 1
                    tool_output = _execute_tool(tc["name"], tc["arguments"], db, user_id)
                yield _tool_done_event(tc["name"], tool_output)
                if tc["name"] == "web_search" and is_failure(tool_output):
                    web_search_fails += 1
                if native_tool_calls:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "name": tc["name"],
                        "content": tool_output,
                    })
                else:
                    messages.append({
                        "role": "user",
                        "content": f"[工具 {tc['name']} 的結果]\n{tool_output}",
                    })

            if (
                web_search_fails >= WEB_SEARCH_FAIL_LIMIT
                or blocked_tool_call
            ):
                messages.append({
                    "role": "user",
                    "content": (
                        "[系統提示] 工具呼叫已失敗、重複或達到上限。請**不要**再呼叫"
                        "相同工具，直接根據前面取得的資料給出最終回答；缺少資訊時誠實說明。"
                    ),
                })
            continue

        # 無工具標記 → 最終回覆；token 已在串流過程中以 token 事件送出，
        # 這裡僅處理空回覆的 fallback。
        if not full_content.strip():
            yield _sse({"type": "token", "text": "（模型沒有回應，請再試一次或更換模型。）"})
        break

    yield _sse({"type": "done"})
