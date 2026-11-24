# SPEC-113：每個功能登記自己的介面動作，`app-actions.js` 只負責分派

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-047](047-review-hardening-and-decoupling.md)、[SPEC-100](100-architecture-ratchet.md)

## Problem

SPEC-047 讓畫面只宣告動作名稱（`data-click="run-page"`），由 `app-actions.js` 的 `UI_ACTIONS` 對照到函式。但這張表把 88 個動作全寫在同一個檔案：`app-actions.js` 用了 86 個其他 script 的名稱，是前端最大的依賴源；每新增一個按鈕都要改這個共用檔，跨 script 名稱也因此居高不下（237 個）。

## Goals

- 登記表 `UI_ACTIONS` 與 `registerUiActions(actionsByType)` 移到最早載入的 `app-lifecycle.js`；每個動作搬到擁有其處理函式的 script（共 21 個），在載入時登記。
- `app-actions.js` 只保留分派：等所有功能登記完（它在功能之後載入）就凍結表格，並對每種事件安裝一個委派 listener。
- 同一事件類型的名稱重複登記、或在凍結後才登記，都直接丟錯，不會被靜靜忽略。
- 跨 script 名稱由 237 降到 170；行為不變。

## Non-goals

- 不改任何動作名稱、HTML 或 CSP；分派規則（最近的宣告元素、表單與連結不導航）不變。

## Proposed design

- 以腳本依「處理函式第一個呼叫的名稱屬於哪個 script」自動分配每個動作，動作的程式碼與前置註解原樣搬移。
- 擁有者都在 `app-lifecycle.js` 之後、`app-actions.js` 之前載入，符合 SPEC-106 的載入順序規則（架構檢查會擋住違反者）。

## Security and data isolation

- 畫面仍不含任何內嵌事件處理器，CSP 不變；未知的動作只記警告、不執行。

## Migration, rollout, and rollback

- Schema／資料 migration：無（schema 13 不變）。
- 上線與 smoke test：Asset 4.29.9／shell v115；部署前自動快照，部署後 `release-check`。
- 回滾方式與資料相容性：可直接回滾至 v4.29.8 image。

## Acceptance criteria

- [x] AC-1：Given HTML 與產生的列宣告的每個 `data-*` 動作，Then 各功能的登記恰好提供一個處理函式，沒有多餘的登記；分派仍只執行最近的動作並負責導航預設行為。
- [x] AC-2：Given 重複的名稱或凍結後的登記，Then 丟出說明錯誤；`app-actions.js` 不再以名稱呼叫任何功能函式。
- [x] AC-3：Given 目前的前端，Then architecture-check 的基準為 170 個名稱、0 對，載入順序檢查通過。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/presentation-shell.test.cjs::SPEC-047 every declared data action has exactly one registered handler`、`unit_tests/frontend/presentation-shell.test.cjs::SPEC-047 delegated dispatch runs only the nearest action and owns navigation defaults` |
| AC-2 | `unit_tests/frontend/presentation-shell.test.cjs::SPEC-113 features register their own UI actions; duplicates fail and the table freezes` |
| AC-3 | `unit_tests/test_architecture_boundaries.py::test_frontend_coupling_matches_the_recorded_ratchet`、`python3 scripts/task.py frontend-e2e` |
