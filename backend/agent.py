"""Agent loop — 跑鞋推薦助手的核心。

流程（ReAct 風格，但用「文字標記」而非各家原生 tool-calling，
因為免費模型多半不支援 function calling，送 `tools` 參數會直接 404）：

    system(含工具說明) → user 訊息 → 呼叫 LLM
      ├─ LLM 回傳文字中含 <tool>name {json}</tool> 標記
      │     → 解析並執行工具（讀 DB / 上網搜尋）→ 把結果作為新一輪
      │       user 訊息餵回 → 再呼叫 LLM
      └─ 文字中無標記 → 那就是最終回覆（去掉標記後）

為求在免費模型上穩定，LLM 呼叫採**串流**；token 以 SSE 逐字即時送達前端。

    {"type": "reasoning", "text": "..."}  # LLM 呼叫工具前的推理過程（逐字串流）
    {"type": "tool", "name": "...", "args": {...}}
    {"type": "tool_done", "name": "..."}  # 工具執行完成（前端即時打勾）
    {"type": "token", "text": "..."}      # 最終回覆的逐字片段
    {"type": "error", "text": "..."}
    {"type": "done"}
"""

import json
from typing import Generator, Optional

from sqlalchemy.orm import Session

from backend import llm
from backend.tools import db_tools
from backend.tools.search_tool import run_web_search, is_failure

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
- **說明你的推理過程**：在呼叫工具之前，先用一段簡短文字說明你為什麼要查這個、你預期找到什麼。例如：「讓我先查查你的跑鞋清單，看看目前的鞋況。」
- **多輪分析**：不要只查一輪就給結論。先查鞋況，再查跑量趨勢，再查快退役的鞋，最後上網搜尋具體推薦款。像一個真正的分析師一樣，逐步深入。
- **當使用者要求看資料時，直接呼叫工具顯示**：不要只說「我來查一下」卻沒有實際 call tool。如果使用者說「查給我看」、「結果呢」、「資料在哪」，你必須呼叫對應的工具並把結果呈現出來。
- **上網搜尋要節制**：web_search 最多呼叫 2~3 次，且只為了補充具體鞋款推薦。若某次 web_search 回傳「沒有找到結果」或「搜尋失敗」，代表這次查不到，**不要重複狂 call 同一類搜尋**——立刻改用你已經讀到的跑鞋/跑量資料給出建議，並誠實說明「網路搜尋暫時查不到，以下依你的現有資料分析」。

{tools}
""".format(tools=db_tools.TOOL_SPEC_TEXT)

MAX_TURNS = 6  # 防止 tool loop 失控（多留一輪給模型收斂）

# web_search 連續失敗達此次數後，強制提醒模型改用現有資料收斂，
# 避免免費模型一直重 call 搜尋把回合數耗光。
WEB_SEARCH_FAIL_LIMIT = 3


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _build_messages(history: list[dict], user_message: str) -> list[dict]:
    """組裝送給 LLM 的 messages。history 只保留 user/assistant 輪次。"""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in history or []:
        role = turn.get("role")
        content = turn.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})
    return messages


def _execute_tool(name: str, arguments: dict, db: Session, user_id: int) -> str:
    if name == "web_search":
        return run_web_search(arguments)
    fn = db_tools.REGISTRY.get(name)
    if fn is None:
        return f"（未知工具：{name}）"
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
    history: Optional[list[dict]] = None,
    provider: str = "openrouter",
    model: Optional[str] = None,
    db: Optional[Session] = None,
    user_id: Optional[int] = None,
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
        pending_tool_text = ""
        seen_tool = False
        tool_calls = []

        try:
            stream_gen = llm.call_llm_stream(prov, model, messages)
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
                                yield _sse({"type": "reasoning_start"})
                            else:
                                yield _sse({"type": "token", "text": chunk})
                        else:
                            # Already streaming a tool round — keep buffering the
                            # raw assistant text instead of emitting leftover
                            # `<tool>` markers to the user. parse_tool_calls()
                            # only returns the first marker, so drop any frozen
                            # tools at freeze time (below) to keep indices
                            # aligned if the model concatenates multiple.
                            pending_tool_text += chunk

                    if seen_tool and not is_last_turn and "</tool>" in pending_tool_text:
                        # Another complete tool marker arrived while we were
                        # buffering. Its text is still part of the assistant
                        # turn (so keep it for the LLM context), but we only
                        # ever execute the first tool.
                        break
            except StopIteration as e:
                # Generator returned via return value
                _ = e.value
        except llm.LLMError as exc:
            yield _sse({"type": "error", "text": str(exc)})
            break
        except Exception as exc:
            yield _sse({"type": "error", "text": f"模型呼叫發生錯誤：{exc}"})
            break

        # ── Post-stream processing ──
        if seen_tool:
            # full_content already contains every streamed chunk (including any
            # buffered second <tool> marker). Only the FIRST tool gets executed;
            # the raw marker text stays in the assistant turn for LLM context.
            tool_calls = db_tools.parse_tool_calls(full_content)[:1]
            _last_close = full_content.rfind("</tool>")
            clean_content = (
                full_content[: _last_close + len("</tool>")] if _last_close != -1 else full_content
            )
            messages.append({"role": "assistant", "content": clean_content})

            for tc in tool_calls:
                yield _sse({"type": "tool", "name": tc["name"], "args": tc["arguments"]})
                tool_output = _execute_tool(tc["name"], tc["arguments"], db, user_id)
                yield _sse({"type": "tool_done", "name": tc["name"]})
                if tc["name"] == "web_search" and is_failure(tool_output):
                    web_search_fails += 1
                messages.append({
                    "role": "user",
                    "content": f"[工具 {tc['name']} 的結果]\n{tool_output}",
                })

            if web_search_fails >= WEB_SEARCH_FAIL_LIMIT:
                messages.append({
                    "role": "user",
                    "content": (
                        "[系統提示] 網路搜尋已多次查不到結果，請**不要**再呼叫 web_search。"
                        "直接根據前面已讀到的跑鞋清單、剩餘壽命與跑量資料，給出最終建議，"
                        "並說明網路搜尋暫時無法取得市售鞋款資訊。"
                    ),
                })
            continue

        # 無工具標記 → 最終回覆；token 已在串流過程中以 token 事件送出，
        # 這裡僅處理空回覆的 fallback。
        if not full_content.strip():
            yield _sse({"type": "token", "text": "（模型沒有回應，請再試一次或更換模型。）"})
        break

    yield _sse({"type": "done"})
