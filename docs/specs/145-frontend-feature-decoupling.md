# SPEC-145：前端共用格式化模組與功能間解耦

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-100](100-architecture-ratchet.md)、[SPEC-101](101-panel-registry.md)、[SPEC-135](135-feature-registries.md)

## Problem

`cross_script_names` 為 153，其中許多是功能之間的直接依賴：

- `formatPace`、`formatRunDuration`、`parseRunDuration`、`runActivityLabel` 定義在 `app-runs.js`，五個功能在用；`shoeColor`、`shoeName`、`calc` 等跑鞋顯示工具定義在 `app-dashboard.js`，五個功能在用。
- 比賽目標狀態 `raceGoal` 放在 `app-pace-charts.js`，`app-race-goal.js` 直接改寫它並呼叫 `renderPaceAnalysis()`。
- `app-monthly-charts.js` 直接呼叫 `renderGoalProgress()`、`renderTrends()` 並改寫 `weeklyWindowEnd`；`app-strava.js` 呼叫 `renderStravaStatus()`；`app-goals.js` 呼叫 `dashboardGoalSummary()`。
- 依賴方向相反：基礎層 `app-resources.js` 與 `app-monthly-charts.js` 讀寫 `runController.state.annualRequest`；`app-workspace.js` 以名稱呼叫 `loadWorkspaceHistory()`、`resetAccountRestore()`。

## Goals

- 新的 `app-format.js`（載入於 `app-api.js` 之前）以凍結的 `runFormat`、`shoeFormat`、`raceFormat`、`goalFormat` 提供共用格式化；其他 script 只透過 namespace 使用。
- 比賽目標由 `app-race-goal.js` 擁有：`onRaceGoalShown(goal)` 交付讀到的值，存檔／刪除後 `refreshPanels('race')` 重畫月度分頁。
- 目標進度與訓練趨勢各自登記 `registerPanel('monthly', { render })`；換年度只讓月度分頁重畫；訓練趨勢自己在年度改變時回到最新 16 週。
- Strava 匯入歷史以 `refreshPanels('strava-history')` 通知跑步紀錄；帳號還原以 `refreshPanels('account-history')` 通知異動歷史。
- `onWorkspaceModalOpen(opened, { closed })` 讓異動歷史與帳號還原自行登記；年度堆疊圖的請求計數移到 `app-monthly-charts.js`，`run-controller` 不再持有它。
- `cross_script_names` 由 153 降為 132，沒有新的互相引用 script。

## Non-goals

- 不改變畫面、文字、API 或資料；不把 classic script 改寫成 ES module。

## Proposed design

- 格式化函式原封搬移（含註解），namespace 以 `Object.freeze` 建立。測試的 `featureContext` 以 `installFormatNamespaces()` 提供同名 namespace，測試原本的 stub 仍會被使用。
- `app-goals.js` 移到 `app-monthly-charts.js` 之後載入，確保年度選單先建立；`invalidatePanels` 新增 `race: ['monthly']`。

## Security and data isolation

- 只搬移前端程式碼，不改變請求、資料或 session 邊界；HTML 仍由既有的 `esc` 處理。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：`release-check`（資產數由 59 增為 60）、`frontend-e2e`、`frontend-layout`。
- 回滾方式與資料相容性：可直接回滾至 v5.3.7 image；Service Worker 以新的 shell 版本更新快取。

## Acceptance criteria

- [x] AC-1：Given 前端 script，When 執行 `architecture-check`，Then `cross_script_names` 為 132、沒有互相引用的 script，且列出的功能不再呼叫或改寫彼此的名稱。
- [x] AC-2：Given 共用格式化，When 載入 `app-format.js`，Then 四個 namespace 都是凍結的且輸出與搬移前相同。
- [x] AC-3：Given 設定視窗，When 開啟與關閉，Then 依序執行功能登記的 open／close hook；異動歷史與還原自行登記。
- [x] AC-4：Given 月度分頁，When 換年度或畫面重畫，Then 目標進度、訓練趨勢與比賽準備由各自的 hook 畫出，訓練趨勢回到新年度的最新 16 週；比賽目標存檔後要求重畫比賽區塊。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/registries.test.cjs::SPEC-145 shared formatting lives in app-format.js and features no longer call each other`、`python3 scripts/task.py architecture-check` |
| AC-2 | `unit_tests/frontend/registries.test.cjs::SPEC-145 shared formatting lives in app-format.js and features no longer call each other` |
| AC-3 | `unit_tests/frontend/registries.test.cjs::SPEC-145 the settings modal runs the open and close hooks features register` |
| AC-4 | `unit_tests/frontend/highlights.test.cjs::SPEC-040 the shared year selector redraws every year view and the comparison chart`、`unit_tests/frontend/streams-rendering.test.cjs::panel rendering is lazy, reused, and invalidated by data or theme changes`、`unit_tests/frontend/trends.test.cjs::SPEC-072 a past year pages back 16 weeks at a time and never calls its last week "本週"`、`unit_tests/frontend/pace-analysis.test.cjs::SPEC-065 the race form validates its fields and saves the parsed goal` |
