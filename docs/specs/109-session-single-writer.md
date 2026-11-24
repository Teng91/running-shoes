# SPEC-109：登入身分只由 `app-session.js` 寫入，單一使用者的狀態搬到使用者身邊

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-108](108-session-module-and-run-drafts.md)、[SPEC-095](095-core-data-store.md)

## Problem

SPEC-108 把登入身分（`authToken`、`currentUser`、`authGeneration`）移到 `app-session.js`，但實際改值的仍是 `app-auth.js`（5 處直接賦值），也沒有檢查擋住其他 script 改寫；核心資料早已只有一個寫入點（SPEC-095），登入身分卻沒有。另外有 4 個狀態變數宣告在共用 script，卻只有一個使用者：月報的 `reportLoadRequestId`、`reportLoadController`、`reportGenerationRequestId`（在 `app-state.js`），以及單鞋分析的 `shoeAnalyticsRequestId`（在 `app-charts.js`）。

## Goals

- `app-session.js` 提供唯一的寫入函式：`startAuthSession(token, username)`（設定並保存）與 `endAuthSession(beforeForget, { persist })`（先推進世代、執行功能重設、再清除身分與保存值）。`app-auth.js` 的 `setAuth()`／`clearAuth()` 改用它們，登入操作的世代也改以 `captureAuthSession()` 讀取。
- `architecture-check` 新增 `session_write_violations()`：`app-session.js` 以外對這三個名稱的賦值、`+=`、`++` 都失敗；同名的區域變數不算。
- 4 個單一使用者的狀態搬到 `app-reports.js` 與 `app-run-insights.js`。
- 跨 script 名稱由 240 降到 237；行為不變。

## Non-goals

- 不改登入流程、storage key 或跨分頁同步的行為。

## Proposed design

- `endAuthSession()` 保留原本的順序：世代先遞增，讓重設期間仍在進行的舊工作被視為過期；身分在重設之後才清除；`persist: false`（另一個分頁已改變登入）時不動 storage。
- 檢查規則沿用 `core_data_violations()` 的寫法：先去掉行尾註解，再找出不在擁有者裡的寫入。

## Security and data isolation

- 登入身分只能經兩個函式改變，任何新的直接改寫都會被 CI 擋下；token 的保存與清除規則不變。

## Migration, rollout, and rollback

- Schema／資料 migration：無（schema 13 不變）。
- 上線與 smoke test：Asset 4.29.7／shell v113；部署前自動快照，部署後 `release-check`。
- 回滾方式與資料相容性：可直接回滾至 v4.29.6 image。

## Acceptance criteria

- [x] AC-1：Given 目前的前端，Then 沒有 `app-session.js` 以外的身分寫入；Given 其他 script 的賦值或遞增，Then 檢查逐行指出，註解、物件 key 與同名區域變數不算。
- [x] AC-2：Given 登入、登出與封鎖 storage 的瀏覽器，Then 身分、世代與保存值的變化與之前相同。
- [x] AC-3：Given 目前的前端，Then architecture-check 的基準為 237 個名稱、0 對。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_architecture_boundaries.py::test_only_the_session_module_writes_the_signed_in_identity` |
| AC-2 | `unit_tests/frontend/reliability.test.cjs::SPEC-087 a browser that blocks site storage still starts and keeps the login in memory`、`unit_tests/frontend/goals-transport.test.cjs::current 401 expires login, but an identical token from a new session is protected` |
| AC-3 | `unit_tests/test_architecture_boundaries.py::test_frontend_coupling_matches_the_recorded_ratchet`、`python3 scripts/task.py architecture-check` |
