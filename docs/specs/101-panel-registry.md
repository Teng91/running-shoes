# SPEC-101：畫面殼層不再呼叫各功能，改由功能自行註冊（拆解 app-core.js 中心節點）

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-100](100-architecture-ratchet.md)、[SPEC-095](095-core-data-store.md)

## Problem

`app-core.js` 是前端的中心節點：`renderActivePanel()` 直接呼叫 dashboard、鞋款圖表、支出、跑步紀錄、首頁摘要、新帳號引導與月度圖表的函式；`switchTab()` 直接呼叫目標表單與月報載入；`loadData()` 自己組出跑步紀錄的讀取與套用，並呼叫 dashboard 的 `render()` 與 Strava 的 `loadStravaHistory()`。這些功能又回呼 `loadData`、`renderActivePanel`、`renderedPanels`，所以 `app-core.js` 和 8 個功能 script 互相使用（SPEC-100 量到 25 對中的 8 對）。新增一個面板要改殼層，殼層也必須知道每個功能的函式名稱。

## Goals

- 殼層提供三個註冊函式，功能 script 在載入時登記自己：
  - `registerPanel(name, { render, enter, key })`：面板要畫什麼、分頁打開前要準備什麼、重畫鍵要加入什麼（跑步分頁加入所選月份）。
  - `registerResourceReader(name, { scope, read, current, apply })`：`loadData()` 的額外資源（跑步紀錄）。
  - `registerDataHooks({ arrived, invalidated, history })`：資源套用後、整體重畫時、需要重新載入匯入紀錄時。
- `app-core.js` 不再以名稱呼叫任何功能函式；同一面板依 `assets.json` 的 script 順序執行，畫面順序與之前相同。
- `localDateISO()` 是共用的日期函式，從 `app-runs.js` 移到 `app-state.js`（緊接在 `appCalendarDate()` 之後）。
- 互相使用的 script 對由 25 降到 16，跨 script 名稱由 255 降到 244，並更新 `scripts/architecture_ratchet.json`。

## Non-goals

- `app-core.js` 與 `app-auth.js`、`app-resources.js` 之間的互相使用保留（登入後載入資料、核心資料的寫入 bridge），留待後續處理。
- 不改變任何畫面、API 或資料；不新增 native module。

## Proposed design

- `app-core.js` 宣告 `panelHooks`（面板名稱 → hooks 陣列）、`resourceReaders`、`dataHooks`。
  - `renderActivePanel()` 的重畫鍵是 `panelRevision|主題|今天|各 hook 的 key()`，鍵不同時依序執行各 hook 的 `render()`。
  - `switchTab()` 在切換前執行目標面板各 hook 的 `enter()`。
  - `invalidatePanels()` 整體失效時呼叫各 `invalidated()`（跑步分頁藉此作廢進行中的年度跑量讀取）。
  - `loadData()` 在開始時取得各 reader 的 `scope()`，讀取順序維持鞋款、月跑量、跑步、目標；套用時只有 `current(scope)` 成立才呼叫 `apply()` 與 `workspaceDataArrived()`，接著呼叫各 `arrived(resource)`；需要匯入紀錄時呼叫各 `history()`。
- 註冊位置：`app-runs.js`（跑步紀錄 reader、跑鞋選單、年度讀取作廢）、`app-run-insights.js`（紀錄與首頁摘要）、`app-onboarding.js`（引導卡）、`app-dashboard.js`（卡片與表格、資源到達時重畫）、`app-shoe-charts.js`、`app-spending.js`、`app-monthly-charts.js`、`app-goals.js`（月度分頁的目標表單基準）、`app-reports.js`（登入後打開月報分頁時載入）、`app-strava.js`（匯入紀錄）。
- hook 以箭頭函式延後取用函式，測試或後載入的 script 替換函式時仍呼叫最新的版本。

## Security and data isolation

- 只調整前端 script 之間的呼叫方式。資料仍只來自目前帳號的回應，session 檢查（`captureAuthSession`／`isCurrentAuthSession`）與月報需登入的條件不變。

## Migration, rollout, and rollback

- Schema／資料 migration：無（schema 13 不變）。
- 上線與 smoke test：Asset 4.29.2／shell v108；部署前自動快照，部署後 `release-check`。
- 回滾方式與資料相容性：可直接回滾至 v4.29.1 image，沒有資料相依。

## Acceptance criteria

- [x] AC-1：Given 實際的註冊，When 依序打開鞋款、跑步分頁，Then 鞋款依卡片、提醒、分類、表格、退役表、圖表、支出的順序繪製，跑步依跑鞋選單、紀錄、首頁摘要、引導卡繪製；所選月份改變時跑步分頁重畫；月度分頁打開前建立目標表單基準；資源到達時 dashboard 重畫，整體失效時作廢年度讀取。
- [x] AC-2：Given `app-core.js`，Then 不以名稱呼叫任何功能函式；Given 月報分頁，Then 只有登入後打開才載入月報。
- [x] AC-3：Given 既有的資料載入、面板快取與目標表單回歸測試，Then 透過真實的註冊全部通過；architecture-check 的基準降為 244 個名稱、16 對。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/streams-rendering.test.cjs::SPEC-101 features register their panels and data in script order; the shell names none of them` |
| AC-2 | `unit_tests/frontend/streams-rendering.test.cjs::SPEC-101 features register their panels and data in script order; the shell names none of them`、`unit_tests/frontend/crud-reports.test.cjs::the report tab wires its panel and only loads data after login` |
| AC-3 | `unit_tests/frontend/streams-rendering.test.cjs::panel rendering is lazy, reused, and invalidated by data or theme changes`、`unit_tests/frontend/draft-resources.test.cjs::SPEC-024 coalesced dashboard loads apply run rows once despite partial failures`、`unit_tests/frontend/strava-resources.test.cjs::SPEC-025 goal baseline exists before the first deferred panel render`、`unit_tests/test_architecture_boundaries.py::test_frontend_coupling_matches_the_recorded_ratchet`、`python3 scripts/task.py frontend-test` |
