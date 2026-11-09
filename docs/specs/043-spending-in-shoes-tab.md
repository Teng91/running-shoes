# SPEC-043：支出併入跑鞋分頁

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-042](042-run-log-tiles-distance-colors-and-ai-tab.md)

## Problem

導覽列分頁太多。支出只跟跑鞋的購買價格有關，使用者希望併進跑鞋分頁，減少一個分頁。

## Goals

- 移除「支出」分頁；支出卡片、年度支出總覽、年度月支出與支出明細移到跑鞋分頁最下方的「支出」區塊，內容不變。
- 導覽剩 4 個分頁：跑步日誌、跑鞋、月跑量、AI；手機底部分頁列改為 4 欄。

## Non-goals

- 不刪減支出卡片、圖表或明細欄位；不改 API 或 schema。

## Proposed design

- `frontend/templates/index.html`：支出面板內容移入跑鞋面板的 `<section class="shoe-spending">`，刪除支出導覽按鈕與面板。
- `frontend/app-core.js`：跑鞋面板繪製時一併呼叫 `renderSpendingCharts()`；跑鞋資源異動只需讓跑鞋、跑步、月跑量面板失效。
- `frontend/app-spending.js`：支出資料晚到時，若目前在跑鞋分頁才繪製；仍維持只在需要時讀取。

## Security and data isolation

- 只搬動前端區塊；`/api/spending/summary` 不變，仍需登入並只回傳自己的資料。

## Migration, rollout, and rollback

- Schema／資料 migration：無；schema 6 不變。
- 上線與 smoke test：Asset 4.4.0／shell v50；部署後執行匿名 `release-check`。
- 回滾方式與資料相容性：可直接回滾至 v4.3.0 image。

## Acceptance criteria

- [x] AC-1：Given 導覽列，When 載入，Then 沒有支出分頁，手機底部分頁列為 4 欄；跑鞋分頁包含支出卡片、兩張支出圖與支出明細。
- [x] AC-2：Given 首頁，When 切到跑鞋分頁，Then 才讀取支出資料；讀取失敗可在跑鞋分頁重試，購買明細與退役狀態正確顯示。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/highlights.test.cjs::SPEC-040 phones use a fixed bottom tab bar while the header menu keeps account actions`、`python3 scripts/task.py frontend-layout` |
| AC-2 | `unit_tests/frontend/resource-editing.test.cjs::SPEC-026 resource views invalidate only their dependent panels`、`python3 scripts/task.py frontend-e2e` |
