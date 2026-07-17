"""Agent loop — 跑鞋推薦助手的核心。

流程（ReAct 風格，但用「文字標記」而非各家原生 tool-calling，
因為免費模型多半不支援 function calling，送 `tools` 參數會直接 404）：

    system(含工具說明) → user 訊息 → 呼叫 LLM
      ├─ LLM 回傳文字中含 <tool>name {json}</tool> 標記
      │     → 解析並執行工具（讀 DB / 上網搜尋）→ 把結果作為新一輪
      │       user 訊息餵回 → 再呼叫 LLM
      └─ 文字中無標記 → 那就是最終回覆（去掉標記後）

為求在免費模型上穩定，LLM 呼叫採**非串流**；最終文字的「逐字」
效果由這裡切成小塊模擬。輸出是 SSE 事件 generator：

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
from backend.tools.search_tool import run_web_search

SYSTEM_PROMPT = """你是「跑鞋推薦助手」，服務一位熱愛跑步的使用者。

你可以使用的工具：
1. 讀取使用者**現有**的跑鞋資料與每月跑量（這些是使用者自己的紀錄）。
2. 上網搜尋市售跑鞋款式、規格、評價、價格。

回答原則：
- 優先根據使用者的**實際數據**給建議。例如：某雙鞋里程快到預期壽命、近期跑量暴增代表該添購、某鞋 CP 值高。
- 再用上網搜尋到的市售鞋款做**具體推薦**，並在推薦處附上來源連結（格式：`鞋款名 - 一句理由（來源：URL）`）。
- 若資訊不足以給好建議（例如不知道腳型、目標距離、預算、路跑或越野），主動用一兩個問題追問。
- 語氣親切、條理清楚，用繁體中文。不要編造鞋款或價格；來源不明的話明說。
- 你**只看得到這位使用者自己的資料**，不要假設有其他人的資料。
- **說明你的推理過程**：在呼叫工具之前，先用一段簡短文字說明你為什麼要查這個、你預期找到什麼。例如：「讓我先查查你的跑鞋清單，看看目前的鞋況。」
- **多輪分析**：不要只查一輪就給結論。先查鞋況，再查跑量趨勢，再查快退役的鞋，最後上網搜尋具體推薦款。像一個真正的分析師一樣，逐步深入。
- **當使用者要求看資料時，直接呼叫工具顯示**：不要只說「我來查一下」卻沒有實際 call tool。如果使用者說「查給我看」、「結果呢」、「資料在哪」，你必須呼叫對應的工具並把結果呈現出來。

{tools}
""".format(tools=db_tools.TOOL_SPEC_TEXT)

MAX_TURNS = 5  # 防止 tool loop 失控


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
    return fn(db, user_id)


def run_agent(
    user_message: str,
    history: Optional[list[dict]] = None,
    provider: str = "openrouter",
    model: Optional[str] = None,
    db: Optional[Session] = None,
    user_id: Optional[int] = None,
) -> Generator[str, None, None]:
    """產生 SSE 事件串流。

    注意：db session 由呼叫方提供並在請求結束時關閉；這裡在多次
    tool 呼叫間重複使用同一個 session（FastAPI 單請求內是安全的）。
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

    for _ in range(MAX_TURNS):
        try:
            result = llm.call_llm(prov, model, messages)
        except llm.LLMError as exc:
            yield _sse({"type": "error", "text": str(exc)})
            break
        except Exception as exc:  # 任何非預期錯誤都優雅降級
            yield _sse({"type": "error", "text": f"模型呼叫發生錯誤：{exc}"})
            break

        content = result["content"]
        tool_calls = db_tools.parse_tool_calls(content)

        if tool_calls:
            # 先把推理文字切成小塊逐字串流，讓使用者看到 LLM 是
            # 「怎麼想的」，而不是一次跳出來
            reasoning = db_tools.strip_tool_markers(content).strip()
            if not reasoning:
                # 如果 LLM 沒給推理文字，根據工具名稱自動產生描述
                tool_desc = {
                    "list_my_shoes": "查詢你的跑鞋清單，看看目前的鞋況",
                    "shoe_summary": "彙整你的跑鞋總覽，分析各鞋剩餘壽命",
                    "monthly_mileage_stats": "查看你的月跑量趨勢，判斷訓練強度",
                    "nearing_end_of_life": "檢查哪些跑鞋接近退役，需要準備替換",
                    "web_search": "上網搜尋市售鞋款的最新資訊與評價",
                }
                descs = [tool_desc.get(tc["name"], f"查詢 {tc['name']}") for tc in tool_calls]
                reasoning = "讓我先" + "，然後".join(descs) + "。"
            for i in range(0, len(reasoning), 4):
                yield _sse({"type": "reasoning", "text": reasoning[i : i + 4]})

            # 把這輪含標記的回覆也留給 LLM 當上下文（標記本身無害）
            messages.append({"role": "assistant", "content": content})
            for tc in tool_calls:
                yield _sse({"type": "tool", "name": tc["name"], "args": tc["arguments"]})
                tool_output = _execute_tool(tc["name"], tc["arguments"], db, user_id)
                # 每個工具執行完立刻通知前端打勾
                yield _sse({"type": "tool_done", "name": tc["name"]})
                messages.append({
                    "role": "user",
                    "content": f"[工具 {tc['name']} 的結果]\n{tool_output}",
                })
            # 回到迴圈頂端，讓 LLM 根據工具結果繼續
            continue

        # 無標記 → 最終回覆，去掉可能殘留的標記後切成小塊模擬打字機
        final_text = db_tools.strip_tool_markers(content).strip()
        if not final_text:
            final_text = "（模型沒有回應，請再試一次或更換模型。）"
        for i in range(0, len(final_text), 4):
            yield _sse({"type": "token", "text": final_text[i : i + 4]})
        break
    else:
        yield _sse({"type": "error", "text": "（模型在多次工具呼叫後仍未給出結論，請簡化你的問題。）"})

    yield _sse({"type": "done"})
