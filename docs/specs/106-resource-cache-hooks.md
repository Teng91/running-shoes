# SPEC-106：資料快取的重設由各功能登記，`refreshCoreData` 回到殼層

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-101](101-panel-registry.md)、[SPEC-105](105-frontend-shared-helpers.md)

## Problem

資料快取 bridge `app-resources.js` 直接改寫功能的狀態，又被那些功能使用，形成三對互相引用：

- `app-resources.js` ↔ `app-spending.js`：快取失效時 bridge 直接重設支出的 `spendingLoadRequestId`／`spendingLoadPending`，支出又用 bridge 的 `applyCoreResource`。
- `app-resources.js` ↔ `app-goals.js`：bridge 直接遞增目標的 `goalProgressRequestId`，目標又用 bridge 的 store。
- `app-core.js` ↔ `app-resources.js`：bridge 的 `refreshCoreData()` 呼叫殼層的 `loadData()`，殼層又用 bridge 的 store。殼層也直接呼叫工作區的 `workspaceDataArrived()`。

## Goals

- `app-resources.js` 提供 `registerResourceCache(name, onInvalidate)`；支出與目標在載入時登記自己的重設，`registerResourceCaches()` 在 store 建立後一併安裝。bridge 不再知道功能的狀態名稱。
- `refreshCoreData()` 移到 `app-core.js`，放在 `loadData()` 旁邊。
- 資料到達的 hook 改為 `arrived(resource, value, current)`；工作區以 `registerDataHooks` 登記，只在資料仍符合畫面範圍時對帳草稿，殼層不再直接呼叫它。
- 互相使用的 script 由 13 對降到 10 對，跨 script 名稱由 244 降到 241；行為不變。

## Non-goals

- 其餘 10 對（登入、工作區草稿與各功能表單）留待後續規格。
- 不改 API、資料或畫面。

## Proposed design

- 登記發生在 script 載入時，`initializeDataResources()` 由最後載入的 `app.js` 呼叫，因此安裝時所有登記都已完成；登記順序是 script 順序（目標在支出之前）。
- `loadData()` 套用資源時依序執行各 `arrived` hook：工作區（載入順序較早）先於 dashboard 重畫，與之前相同。

## Security and data isolation

- 只調整前端 script 之間的呼叫方式；session 檢查與資料來源不變，失效重設仍作廢進行中的舊讀取。

## Migration, rollout, and rollback

- Schema／資料 migration：無（schema 13 不變）。
- 上線與 smoke test：Asset 4.29.4／shell v110；部署前自動快照，部署後 `release-check`。
- 回滾方式與資料相容性：可直接回滾至 v4.29.3 image。

## Acceptance criteria

- [x] AC-1：Given 支出與目標的登記，When 鞋款或目標資料被接受，Then 支出摘要清空並作廢進行中的讀取、目標進度的請求序號遞增。
- [x] AC-2：Given 資料到達，Then 工作區只收到仍符合畫面範圍的資料；殼層擁有 `refreshCoreData()`，bridge 不再提到功能狀態或 `loadData()`。
- [x] AC-3：Given 既有的資料載入、快取與草稿測試，Then 全部通過；architecture-check 的基準為 241 個名稱、10 對。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/streams-rendering.test.cjs::SPEC-106 features own their cache resets and the workspace hears only current data` |
| AC-2 | `unit_tests/frontend/streams-rendering.test.cjs::SPEC-106 features own their cache resets and the workspace hears only current data` |
| AC-3 | `unit_tests/frontend/feature-operations.test.cjs::SPEC-023 mutation refresh limits requests and preserves unrelated caches`、`unit_tests/test_architecture_boundaries.py::test_frontend_coupling_matches_the_recorded_ratchet`、`python3 scripts/task.py frontend-test` |
