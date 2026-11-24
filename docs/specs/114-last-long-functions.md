# SPEC-114：拆完最後 4 個超過 80 行的前端函式

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-111](111-frontend-function-length.md)

## Problem

SPEC-111 為前端函式訂了 80 行上限，當時仍有 4 個函式超過、記錄在 `scripts/architecture_ratchet.json` 的 `long_functions`：工作區 controller `createWorkspaceController`（120 行）、輪替時間軸 `renderShoeTimeline`（113）、IndexedDB adapter `openLocalWorkspaceStore`（109）與月報產生 `generateReport`（105）。

## Goals

- `renderShoeTimeline` 拆出讀取 `loadShoeTimeline`、資料 view `shoeTimelineView`、圖表設定 `shoeTimelineChart` 與今天線 `timelineTodayPlugin`。
- `generateReport` 拆出 `startReportGeneration`、`isCurrentReport`、`scheduleReportMarkdown`、`handleReportEvent`、`finishReportStream`、`showReportFailure`、`endReportGeneration`，一次產生的狀態集中在 report 物件。
- `openLocalWorkspaceStore` 拆出 `openWorkspaceDatabase`、`runWorkspaceTransaction`、共用的讀改寫步驟 `changeWorkspaceRecord`、`consumeRunDraft` 與紀錄 API `workspaceStoreRecords`，連線狀態放在 handle 物件。
- `createWorkspaceController` 把逐筆同步 `syncQueueItem` 與紀錄規則 `savedRecord`、`queuedRecord`、`repairedRecord`、`removedRecord`、`refuseLeasedQueue` 移到 factory 外。
- `long_functions` 清空：前端沒有任何函式超過 80 行。行為完全相同。

## Non-goals

- 不改 API、本機資料庫格式（`running-shoes-workspace` v1）、離線佇列規則或畫面。

## Proposed design

- 純粹抽出函式；runtime module 的新函式仍不碰 DOM 或 transport（架構檢查照舊限制）。
- 讀改寫三種寫法（update、enqueue、move）共用 `changeWorkspaceRecord()`，差別只在寫回的方式，寫入順序與交易內容不變。

## Security and data isolation

- 本機紀錄仍以帳號分區、不含憑證；同步仍以 lease 防止重複送出，帳號切換後的回應只刪除原帳號分區的紀錄。

## Migration, rollout, and rollback

- Schema／資料 migration：無（schema 13、IndexedDB v1 不變）。
- 上線與 smoke test：Asset 4.29.10／shell v116；部署前自動快照，部署後 `release-check`。
- 回滾方式與資料相容性：可直接回滾至 v4.29.9 image。

## Acceptance criteria

- [x] AC-1：Given 目前的前端，Then 沒有函式超過 80 行，`long_functions` 為空。
- [x] AC-2：Given 輪替時間軸、月報串流、本機儲存與離線佇列的既有測試，Then 全部通過，結果與之前相同。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_architecture_boundaries.py::test_frontend_functions_stay_short_or_only_shrink`、`python3 scripts/task.py architecture-check` |
| AC-2 | `unit_tests/frontend/trends.test.cjs::the shoes panel redraws its rotation timeline and distance mix when runs arrive mid-read`、`unit_tests/frontend/goals-transport.test.cjs::report streaming distinguishes saved completion from an interrupted response`、`unit_tests/frontend/workspace.test.cjs::SPEC-030 local clearing preserves replacement sessions and newer input`、`python3 scripts/task.py frontend-e2e` |
