# SPEC-111：前端函式長度上限與兩個最長函式的拆解

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-100](100-architecture-ratchet.md)、[SPEC-110](110-tooling-complexity.md)

## Problem

後端與開發工具都有複雜度上限（SPEC-100、SPEC-110），前端卻沒有任何量測。量測時有 6 個頂層函式超過 80 行：AI 對話的 `sendAgentMessage`（243 行）把請求、畫面準備、串流事件、等待提示與結尾都寫在同一個函式；鞋款圖表的 `renderCharts`（193 行）一次建立四張圖；另外是 `createWorkspaceController`（120）、`renderShoeTimeline`（113）、`openLocalWorkspaceStore`（109）與 `generateReport`（105）。

## Goals

- `architecture-check` 量測 classic script 與 runtime module 的頂層函式行數：超過 80 行的新函式失敗；超過的既有函式記在 `scripts/architecture_ratchet.json` 的 `long_functions`，只能變短（變短後必須更新紀錄，降到 80 行以下就移除）。
- `sendAgentMessage` 只負責請求與流程：畫面準備 `showAgentRequest`、回答狀態 `createAgentTurn`／`refreshAgentWait`、事件分派 `handleAgentEvent`（思考、工具、工具完成、改為思考、token、錯誤、來源摘要各一個處理函式）、結尾 `finishAgentAnswer` 與錯誤 `showAgentFailure`。
- `renderCharts` 建立共用的 view（標籤、顏色、壽命數字、主題色）後呼叫 `renderProgressChart`、`renderCostChart`、`renderRetireChart`、`renderValueChart`。
- 行為完全相同：SSE 事件的畫面變化、重試、歷史保存、圖表設定都不變。

## Non-goals

- 其餘 4 個長函式（工作區 controller、輪替時間軸、IndexedDB adapter、月報產生）先記錄，之後再拆。
- 不引入 ESLint 或其他 Node 依賴（公司網路的代理擋住部分套件）。

## Proposed design

- 行數從 `function` 宣告行算到第一個位於行首的 `}`，與專案的縮排慣例一致；巢狀函式算在外層函式裡。
- 一次回答的狀態集中在 turn 物件，各事件處理函式只更新它，取代原本閉包裡的多個 `let`。

## Security and data isolation

- 只重組前端程式碼；回答仍以 `textContent` 串流、完成後才以安全 Markdown 渲染，來源卡片規則不變，session 檢查不變。

## Migration, rollout, and rollback

- Schema／資料 migration：無（schema 13 不變）。
- 上線與 smoke test：Asset 4.29.8／shell v114；部署前自動快照，部署後 `release-check`。
- 回滾方式與資料相容性：可直接回滾至 v4.29.7 image。

## Acceptance criteria

- [x] AC-1：Given 目前的前端，Then 沒有未記錄的長函式，`sendAgentMessage` 與 `renderCharts` 都在 80 行以內；Given 新的長函式、記錄的函式變長、變短或刪除，Then 檢查指出並說明怎麼修。
- [x] AC-2：Given AI 對話的串流、思考、工具與重試，Then 畫面與保存的歷史與之前相同。
- [x] AC-3：Given 鞋款圖表，Then 四張圖的資料與標籤與之前相同。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_architecture_boundaries.py::test_frontend_functions_stay_short_or_only_shrink`、`python3 scripts/task.py architecture-check` |
| AC-2 | `unit_tests/frontend/agent-thinking.test.cjs::SPEC-086 reasoning streams live above the answer, folds when it answers and is never kept`、`unit_tests/frontend/updates.test.cjs::SPEC-059 completed AI turns survive a reload for the same account only` |
| AC-3 | `unit_tests/frontend/presentation-shell.test.cjs::SPEC-050 the share doughnut shows each active shoe’s 90-day monthly average and their total` |
