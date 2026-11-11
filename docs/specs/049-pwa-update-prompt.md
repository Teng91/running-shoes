# SPEC-049：新版部署提示與主動偵測

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-017](017-consistent-statistics-and-feature-lifecycles.md)、[SPEC-048](048-push-to-main-deploy-and-release.md)

## Problem

v4.0.0 起，PWA 偵測到新 shell 時會直接重新載入，不詢問使用者；而且只有在 App 啟動、註冊 service worker 時才會檢查新部署。

SPEC-048 讓每次 push 到 main 都自動部署。v4.7.3 上線後，維護者手機上一直開著的 App 沒有檢查更新，仍停在舊版，因而誤以為沒有部署。另外，自動重新載入會清掉記憶體中的 AI 對話。

## Goals

- App 開著時也會主動檢查新部署：回到前景、視窗取得焦點、網路恢復，以及每 30 分鐘一次；同時觸發的事件 60 秒內只檢查一次，隱藏或離線時不檢查。
- 偵測到新版時顯示「有新版本 v<版號>」提示，附「立即更新」與「稍後」；只有按下「立即更新」才重新載入，且只載入一次。
- 提示說明重新載入的影響：表單草稿會保留，AI 對話會清除。
- 按「稍後」先隱藏提示；之後再有新部署會再提示；下次開啟 App 一定是最新已安裝的 shell。

## Non-goals

- 不改 service worker 的安裝、驗證與啟用流程：新 shell 仍完整預先快取後才啟用，失敗時保留舊 shell。
- 不新增 `/version` API；新部署由 service worker 腳本的位元組比對偵測。
- 不在未啟用 service worker 的瀏覽器顯示提示。

## Proposed design

- `frontend/app-updates.js`：
  - `initializeAppUpdates()` 保留 controller 版本比對。不同版本時改呼叫 `showAppUpdate(version)`，不再 `location.reload()`。
  - 註冊成功後保存 registration；`visibilitychange`、`focus`、`online` 與 30 分鐘 `setInterval` 共用 `checkForUpdate()`，在可見、連線且距上次檢查至少 60 秒時呼叫 `registration.update()`，失敗則忽略。
  - `applyAppUpdate()` 停用按鈕後重新載入一次；`dismissAppUpdate()` 只隱藏提示。
- `frontend/templates/index.html` 新增固定位置的 `#app-update-notice`（`role="status"`），按鈕以 `data-click="apply-app-update"`／`dismiss-app-update` 委派到 `app-actions.js`。
- `frontend/css/02-shell.css`：提示固定在右下角，層級低於彈窗；手機版位於底部分頁列上方。
- 舊頁面在提示期間繼續執行。native module 只在啟動時載入，所以不會混用新舊版本程式。

## Security and data isolation

- 不涉及使用者資料、API 或 secret；檢查只向同源 `/service-worker.js` 發出請求。
- 不快取 API，也不改動既有快取範圍。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：
  - Asset 4.8.0／shell v58。
  - 已開著 v4.7.3 的頁面，仍依舊邏輯在新 shell 啟用時自動重新載入一次；從 v4.8.0 起改為提示。
  - 部署後在手機上保持 App 開啟，切到背景再回來，應看到下一版的提示。
- 回滾方式與資料相容性：部署 v4.7.3 即回到自動重新載入，資料不受影響。

## Acceptance criteria

- [x] AC-1：Given 新 shell 已啟用，When 頁面收到不同版本，Then 顯示含版號的提示且不自動重新載入；相同版本不提示；按「稍後」隱藏、之後的新部署再提示；按「立即更新」只重新載入一次。
- [x] AC-2：Given App 保持開啟，When 回到前景、取得焦點、網路恢復或滿 30 分鐘，Then 檢查新部署；隱藏、離線或 60 秒內重複觸發時不檢查，檢查失敗不拋錯。
- [x] AC-3：Given 真實瀏覽器裡的 service worker 升級（含舊版 worker 遷移），When 新 shell 啟用，Then 頁面先顯示提示、維持舊版，按下更新後才載入新版 shell。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/statistics-lifecycle.test.cjs::SPEC-049 a newer shell shows an update prompt and reloads only after confirmation` |
| AC-2 | `unit_tests/frontend/statistics-lifecycle.test.cjs::SPEC-049 an open app looks for new deployments on focus, visibility, reconnect and every 30 minutes` |
| AC-3 | `unit_tests/frontend/statistics-lifecycle.test.cjs::SPEC-049 a newer shell shows an update prompt and reloads only after confirmation`、`python3 scripts/task.py frontend-pwa` |
