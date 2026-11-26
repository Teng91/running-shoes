# SPEC-135：對話框、更新忙碌判斷與重繪改由功能登記

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-059](059-automatic-updates-at-safe-moments.md)、[SPEC-100](100-architecture-ratchet.md)、[SPEC-101](101-panel-registry.md)、[SPEC-108](108-session-module-and-run-drafts.md)

## Problem

2026-11-27 的檢查找到三處共用 script 直接呼叫功能的函式或讀功能的狀態，方向與 SPEC-101 相反：

- `app-dialogs.js` 的 Escape 對照表列出七個功能的關閉函式，`app.js` 再為其中四個對話框各接一個點背景關閉的監聽。
- `app-auth.js` 登入時直接呼叫 `resetAgentChat()`、`loadAgentModels()`，`app.js` 啟動時呼叫 `restoreAgentChat()`；`app-updates.js` 的 `appUpdateBusy()` 直接讀 `agentController`、`reportGenerationController`、`activeHttpRequests`、`inlineEditors` 與 AI 輸入框、登入表單的 DOM。
- 跑鞋看板 `app-dashboard.js` 的 `render()` 是「資料變了就重繪」的入口，`app-auth.js`、`app-shoes.js`、`app-workspace.js` 都呼叫它，它再呼叫 `app-onboarding.js`；`app-goals.js`、`app-dates.js` 則自己串 `invalidatePanels()` 和 `renderActivePanel()`。

## Goals

- 共用 script 不再以名稱呼叫任何功能；功能在載入時向 `app-lifecycle.js` 登記。
- 行為不變：Escape 關最上層對話框，點背景只關原本會關的四個（紀錄編輯、匯出、跑鞋分析、資料與同步）；SPEC-059 的忙碌判斷與 AI 對話恢復照舊。
- `cross_script_names` 下降。

## Non-goals

- 不搬動 `formatPace`、`shoeColor` 等共用格式函式：搬位置不會減少跨 script 名稱。
- `app-runs.js` 篩選單日時只重繪紀錄頁（`renderedPanels.delete('runs')`），不改成 `refreshPanels('runs')`，以免連帶重繪跑鞋與月度圖表。

## Proposed design

- `app-lifecycle.js` 新增 `registerDialog(id, { close, backdrop })` 與 `closeDialog(id, { fromBackdrop })`：未登記的 ID 與重複登記會丟錯；`initializeDialogs()` 為每個對話框接一個點背景的監聽，只有 `backdrop: true` 會關。七個功能各登記自己的對話框，`app-account.js` 用 `closeDialog('workspace-modal')`。
- `app-lifecycle.js` 新增 `registerBusyCheck(check)` 與 `featureBusy()`；`app-api.js`、`app-auth.js`、`app-inline-editors.js`、`app-agent.js`、`app-reports.js` 各登記自己的判斷，`appUpdateBusy()` 只剩「有開著的對話框」加 `featureBusy()`。`reportGenerationController` 從 `app-state.js` 移到唯一寫它的 `app-reports.js`。
- `app-agent.js` 以 `onAuthView({ appShown })` 恢復本帳號的對話並載入模型清單，登入與啟動流程不再呼叫它；`restoreAgentChat()` 在已有對話時不再重複加入（啟動時離線退路會第二次打開主畫面）。
- `app-core.js` 新增 `refreshPanels(resource)`：更新「資料日期」、失效並重繪目前面板，再呼叫資料 hook 的 `refreshed(resource)`。`loadData()` 套用每個資源後呼叫它；`app-dashboard.js` 刪除 `render()`；`app-onboarding.js` 以 `registerDataHooks({ refreshed })` 更新入門卡。
- `architecture_ratchet.json` 的 `cross_script_names` 163 → 153。

## Security and data isolation

- 無資料或 API 變更。AI 對話仍只恢復同一個帳號識別碼的暫存（SPEC-134），且每次工作階段結束都會被清除。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：開關每個對話框（Escape、點背景）、登入後 AI 對話與模型清單、App 更新提示。
- 回滾方式與資料相容性：直接回滾 v5.2.6 image，沒有保存格式變更。

## Acceptance criteria

- [x] AC-1：Given 頁面上的每個對話框，When 按 Escape 或點背景，Then 經登記的關閉函式關閉，點背景只關 `backdrop: true` 的四個；`app-dialogs.js`、`app.js` 不提任何功能的關閉函式。
- [x] AC-2：Given AI 回答串流中、月報產生中、請求進行中、行內編輯中、AI 輸入框有字或登入表單有字，When 有新版本，Then 自動更新延後；`app-updates.js` 不讀任何功能狀態。
- [x] AC-3：Given 登入、註冊或啟動時主畫面打開，When `appShown` 觸發，Then AI 對話恢復本帳號的暫存並載入模型，`app-auth.js`、`app.js` 不呼叫 AI 功能，且同一份對話不會加入兩次。
- [x] AC-4：Given 任一功能改了資料，When 呼叫 `refreshPanels(resource)`，Then 更新資料日期、重繪受影響的目前面板並通知 `refreshed` hook；看板沒有 `render()`。
- [x] AC-5：Given 架構檢查，When 執行，Then `cross_script_names` 為 153。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/registries.test.cjs::SPEC-135 every dialog registers how it closes; Escape and backdrop clicks go through the registry` |
| AC-2 | `unit_tests/frontend/updates.test.cjs::SPEC-059 work in progress postpones the automatic update until it is safe` |
| AC-2 | `unit_tests/frontend/registries.test.cjs::SPEC-135 features register what postpones an automatic update; the updater names none of them` |
| AC-3 | `unit_tests/frontend/updates.test.cjs::SPEC-059 completed AI turns survive a reload for the same account only` |
| AC-3 | `unit_tests/frontend/workspace.test.cjs::SPEC-108 runs and sign-in hooks reach the workspace only through registrations` |
| AC-4 | `unit_tests/frontend/registries.test.cjs::SPEC-135 a data change redraws through the shell, which tells the data hooks` |
| AC-5 | `unit_tests/test_architecture_boundaries.py::test_frontend_coupling_matches_the_recorded_ratchet` |
