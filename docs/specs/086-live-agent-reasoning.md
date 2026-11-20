# SPEC-086：AI 對話即時顯示思考過程

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-059](059-automatic-updates-at-safe-moments.md)

## Problem

- 今日免費清單裡的熱門模型多半是推理模型，回答前會先思考一段時間。OpenRouter 會把思考內容串流過來（`delta.reasoning`），但後端只轉送回答文字，思考的那段時間畫面只有一個空白泡泡，答案出現時才一口氣冒出來，體感上像卡住。

## Goals

- 模型思考時，在答案上方即時顯示思考內容；開始回答或呼叫工具時收合成「💭 已思考 N 秒」，點開可再看。
- 泡泡還是空的、也沒有正在顯示的思考內容時，泡泡顯示「思考中… N 秒」，模型不輸出思考內容時也看得到它還在跑。
- 每一輪模型呼叫各有一個思考區塊，依時間順序和工具呼叫穿插排列。

## Non-goals

- 不改變模型的推理設定：請求不帶 `reasoning` 參數，各模型維持自己的預設（不會因此讓模型變慢或多耗額度）。
- 不保存思考內容：不放進對話歷史、`sessionStorage`，也不送回下一輪 prompt；重新整理後只還原回答。
- 月報產生不顯示思考內容。

## Proposed design

- `backend/llm.py`：`call_llm_stream(..., include_reasoning=False)`。為 `True` 時，每個 delta 依序讀 `reasoning`、`reasoning_content`，沒有才讀 `reasoning_details` 中 `reasoning.text`／`reasoning.summary` 的文字（加密內容略過），以 `ReasoningText`（`str` 子類別）產出；思考內容不併入回傳的 `content`。預設 `False`，月報 adapter 與既有呼叫方的行為不變。
- `backend/agent.py`：以 `include_reasoning=True` 呼叫，遇到 `ReasoningText` 送出 SSE `{"type": "thinking", "text": ...}`，不加入 `full_content`，因此不影響文字工具標記解析、tool 訊息與歷史。
- `frontend/app-agent.js`：`createAgentReasoning()` 在答案泡泡前插入 `<details class="agent-reasoning" open>`，以 text node `appendData` 累加內容並自動捲到底；`token`、`tool`、`reasoning_start`、`error` 或串流結束時 `finish()` 收合並顯示秒數。每秒的計時器更新思考區塊或泡泡內的 `.agent-wait` 標籤，`tool_done` 與 `reasoning_start` 時重新起算；串流結束、錯誤或取消時停止。
- `frontend/css/07-agent.css`：`.agent-reasoning` 與 `.agent-wait` 樣式；思考內容最多顯示約 11 行，超過可捲動。

## Security and data isolation

- 思考內容是不可信的模型輸出：前端只用 text node 顯示，不經 Markdown 或 `innerHTML`。後端不記錄思考內容到 log。內容只來自本帳號這次請求的模型回應，不跨帳號、不持久化。頁面 CSP 不變（`<details>` 原生展開，沒有 inline handler）。

## Migration, rollout, and rollback

- Schema／資料 migration：無。API 新增一種 SSE 事件 `thinking`，舊前端會忽略。
- 上線與 smoke test：選一個推理模型送出「hi」，答案出現前看得到「💭 思考中…」與思考內容，回答開始後收合成「已思考 N 秒」。
- 回滾方式與資料相容性：可直接回滾到 v4.23.1 image；沒有資料變更。

## Acceptance criteria

- [x] AC-1：Given 模型串流 `reasoning`／`reasoning_details`，When 以 `include_reasoning=True` 呼叫，Then 產出標示為思考的片段（同一個 delta 不重複、加密內容略過），回答 `content` 不含思考內容；預設呼叫只產出回答。
- [x] AC-2：Given Agent 對話，When 模型先思考再呼叫工具、再思考後回答，Then SSE 依序送出 `thinking`、工具事件、`thinking`、`token`，第二輪 prompt 不含第一輪的思考內容。
- [x] AC-3：Given 前端收到 `thinking`，Then 在答案上方顯示展開的思考區塊與秒數，第一個回答 token 時收合為「已思考 N 秒」，思考內容以純文字顯示且不寫入對話歷史與 `sessionStorage`。
- [x] AC-4：Given 多輪工具呼叫或模型不輸出思考內容，Then 每輪各有一個思考區塊並與工具列依序排列；泡泡在等待時顯示「思考中… N 秒」，工具完成後重新計時，串流結束後計時器停止。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_llm.py::test_call_llm_stream_yields_reasoning_only_when_requested`、`unit_tests/test_llm.py::test_call_llm_stream_reads_openrouter_reasoning_from_real_sdk_deltas` |
| AC-2 | `unit_tests/test_agent.py::test_model_thinking_streams_as_its_own_event_and_never_joins_the_answer` |
| AC-3 | `unit_tests/frontend/agent-thinking.test.cjs::SPEC-086 reasoning streams live above the answer, folds when it answers and is never kept` |
| AC-4 | `unit_tests/frontend/agent-thinking.test.cjs::SPEC-086 each model round gets its own block and the bubble waits again between rounds`、`unit_tests/frontend/agent-thinking.test.cjs::SPEC-086 a model that never thinks out loud still shows the waiting seconds, then the answer` |
