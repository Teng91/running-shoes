# SPEC-105：共用的前端小工具放到共用的位置，拆掉三對互相引用

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-100](100-architecture-ratchet.md)、[SPEC-101](101-panel-registry.md)

## Problem

SPEC-101 之後前端還有 16 對互相使用的 script。其中三對只是因為共用的小工具放錯地方，或一方直接呼叫另一方：

- `app-dashboard.js` ↔ `app-run-insights.js`：所有圖表與磨耗色條都用的 `getThemeColor()` 定義在跑步洞察裡，dashboard 只好依賴它，而洞察又用 dashboard 的鞋款顏色與里程格式。
- `app-monthly-charts.js` ↔ `app-pace-charts.js`：年度回顧與比賽準備共用的 `reviewCard()` 在月度圖表裡，月度圖表又在 `renderMonthlyCharts()` 結尾直接呼叫 `renderPaceAnalysis()`。
- `app-pace-charts.js` ↔ `app-race-goal.js`：比賽準備載入目標後直接呼叫表單的 `prepareRaceForm()`，表單又讀比賽準備的共用狀態。

## Goals

- `getThemeColor()` 移到 `app-state.js`（主題狀態旁），`reviewCard()` 移到 `app-charts.js`（共用圖表工具）。
- 比賽準備以 `registerPanel('monthly', …)` 自行登記在月度分頁，接在月度圖表之後繪製；`renderMonthlyCharts()` 不再呼叫它。
- `app-pace-charts.js` 提供 `onRaceGoalShown(view)`，載入比賽目標後通知已登記的畫面；`app-race-goal.js` 以它登記表單的 `prepareRaceForm()`。
- 互相使用的 script 對由 16 降到 13，基準同步降低；畫面與行為不變。

## Non-goals

- 與 `app-auth.js`、`app-workspace.js`、`app-resources.js` 有關的 13 對牽涉登入、草稿與資料快取的生命週期，留待後續規格。
- 不改 API、資料或畫面。

## Proposed design

- 純粹搬移函式與改用登記；script 載入順序不變（`app-state.js` 在所有使用者之前，`app-charts.js` 在月度與比賽準備之前），比賽準備的登記在 `app-monthly-charts.js` 之後，因此繪製順序與之前相同。
- 比賽表單只在使用者沒有展開編輯時才帶入載入的目標，這個條件仍在 `prepareRaceForm()` 裡。

## Security and data isolation

- 只調整前端 script 之間的呼叫方式，資料來源與 session 檢查不變。

## Migration, rollout, and rollback

- Schema／資料 migration：無（schema 13 不變）。
- 上線與 smoke test：Asset 4.29.3／shell v109；部署前自動快照，部署後 `release-check`。
- 回滾方式與資料相容性：可直接回滾至 v4.29.2 image。

## Acceptance criteria

- [x] AC-1：Given 月度分頁，When 打開，Then 月度圖表之後繪製比賽準備，資料或主題改變時一起重畫。
- [x] AC-2：Given 比賽準備載入目標，Then 表單帶入目標、刪除按鈕與按鈕文字依目標顯示；沒有目標時邀請設定。
- [x] AC-3：Given 目前的前端，Then architecture-check 的基準為 13 對，三對不再互相使用。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/streams-rendering.test.cjs::panel rendering is lazy, reused, and invalidated by data or theme changes` |
| AC-2 | `unit_tests/frontend/pace-analysis.test.cjs::SPEC-065 race prep shows the backend prediction, long-run gap and intensity mix`、`unit_tests/frontend/pace-analysis.test.cjs::SPEC-065 without a race goal only the pace trend is drawn and the form invites one` |
| AC-3 | `unit_tests/test_architecture_boundaries.py::test_frontend_coupling_matches_the_recorded_ratchet`、`python3 scripts/task.py architecture-check` |
