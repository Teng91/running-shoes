# SPEC-132：月報、跑鞋匯出與課表模組載入修正

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-049](049-pwa-update-prompt.md)、[SPEC-127](127-race-plan-view-module.md)

## Problem

2026-11-26 對月報、支出、匯出與 PWA 更新的逐行檢查找到：

- 產生月報時切到別的分頁再切回來，月報分頁會重新讀取已儲存的報告。那次讀取在報告存好前發出，可能把畫面蓋成「載入中…」或「此月份尚無報告」，看起來像報告不見了。
- 跑鞋 CSV／XLSX 匯出沒有檢查登入狀態：網路慢時登出、換帳號登入後，前一個帳號的檔案仍會下載到這台裝置。帳號備份下載已有這項檢查。
- `runtime/race-plan-view.mjs`（SPEC-127）是唯一在第一次顯示課表時才載入的模組。新版的 service worker 啟用後會刪掉舊版快取，還開著的舊版頁面之後才載入這個模組，會從網路拿到新版內容；新舊版不相容時課表就會出錯。

## Goals

- 產生月報期間，切換分頁不會改寫正在串流的報告。
- 跑鞋匯出只下載到發出請求的那個登入工作階段。
- 課表模組和其他 native module 一樣在頁面載入時就匯入，所以一定和頁面同一版。

## Non-goals

- 不改變 service worker 的快取策略，仍只保留目前版本的 shell 快取。
- 不改變月報產生與儲存的後端流程（見 SPEC-133）。

## Proposed design

- `app-reports.loadSavedReport()` 在 `reportGenerationController` 存在時直接返回；產生結束後原本的流程會重新載入。
- `app-exports.doExport()` 開始時先取得當下的登入工作階段，收到檔案後若登入已改變就不下載。
- `app-pace-charts.js` 在載入時就呼叫 `loadRacePlanModule()` 開始匯入；`renderRacePlan` 等待它完成，第一次載入失敗時（例如還沒快取就離線）重試一次，仍失敗就拋出錯誤並記錄。

## Security and data isolation

- 匯出檔只會存進發出請求的那個登入工作階段，不會在換帳號後才下載。
- 其他修正只影響畫面狀態，不新增資料讀取。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：產生月報時切換分頁，報告持續顯示；課表照常出現。
- 回滾方式與資料相容性：直接回滾 v5.2.3 image。

## Acceptance criteria

- [x] AC-1：Given 正在產生月報，When 切回月報分頁，Then 不發出已儲存報告的讀取，畫面維持串流內容；產生結束後才正常讀取。
- [x] AC-2：Given 跑鞋匯出進行中，When 登入工作階段改變後才收到檔案，Then 不下載；同一個工作階段照常下載。
- [x] AC-3：Given 頁面載入，When 執行 `app-pace-charts.js`，Then 立即開始匯入課表模組；第一次失敗時顯示課表前會重試，仍失敗就拋出錯誤。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/crud-reports.test.cjs::SPEC-132 opening the report tab during a generation leaves the streaming report alone` |
| AC-2 | `unit_tests/frontend/workspace.test.cjs::SPEC-132 a shoe export that arrives after sign-out is never downloaded` |
| AC-3 | `unit_tests/frontend/pace-analysis.test.cjs::SPEC-132 the plan module is imported while the page loads and retried after a failed load` |
