# SPEC-134：帳號識別碼的瀏覽器設定、回滾腳本與前端解耦

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-059](059-automatic-updates-at-safe-moments.md)、[SPEC-084](084-new-account-onboarding.md)、[SPEC-100](100-architecture-ratchet.md)、[SPEC-129](129-local-data-account-key.md)

## Problem

2026-11-26 的全專案檢查找到：

- SPEC-129 把離線資料改依帳號識別碼（`aid`）存放，但「略過引導」、Strava 匯入日期範圍與 AI 對話暫存仍以帳號名稱為鍵；帳號刪除後同名重新註冊的新帳號會沿用舊帳號的設定，且前兩者大小寫規則不一致。
- `app-strava.js` 直接讀 `localStorage`，沒有用共用的 `readStoredValue`。
- 正式映像只帶 `rollback_preview_schema.sql`，文件化的 schema 回滾腳本要另外傳到機器上才能執行；基底映像只以 tag 指定，每次建置可能不同。
- 前端有跨 script 的可變狀態：`raceGoalSaving` 宣告在 `app-pace-charts.js` 卻由 `app-race-goal.js` 寫入，`registrationMode` 宣告在 `app-auth.js` 卻由 `app-account.js` 寫入；`app-account.js` 自己串接 `clearAuth`、`showLoginView`、`showAuthError`；`app-history.js` 為了時間格式依賴 `app-reports.js`。

## Goals

- 這三項瀏覽器設定只屬於同一個帳號識別碼；沒有識別碼時不保存。
- 正式映像內含所有回滾腳本，基底映像可重現且會定期更新。
- 可變狀態由寫入它的 script 持有；其他功能只透過一個入口回到登入畫面；`cross_script_names` 下降。

## Non-goals

- 不搬移 Strava 日期範圍與 AI 對話暫存的舊名稱鍵：前者只是預設值的便利，後者只活在分頁內。
- 跑鞋看板與圖表共用的 `calc`、`progressColor`、`floorShoeKm`、`fmtDate` 保留在 `app-dashboard.js`：搬到其他檔案不會減少依賴，只會換位置。

## Proposed design

- 鍵改為 `onboarding-dismissed:aid:<aid>`、`strava-import-range:aid:<aid>`；AI 對話暫存記錄 `account` 而非 `user`。`onboardingDismissed()` 找不到新鍵時接手一次舊的小寫名稱鍵並刪除它。
- Dockerfile `COPY scripts/database_backup.py scripts/*.sql scripts/`；`FROM python:3.11-slim@sha256:…`；`dependabot.yml` 新增 docker 生態系，每月最多一個 PR。
- `raceGoalSaving` 與它的重置移到 `app-race-goal.js`；`registrationMode` 移到 `app-account.js`，並寫入 `#reg-invite-group` 的 `data-required`，`handleRegister()` 只讀它；`app-auth.js` 新增 `signOutWithNotice(message)`、`showLoginNotice(message)`；`formatLocalTimestamp` 移到 `app-dates.js`。`architecture_ratchet.json` 的 `cross_script_names` 166 → 163。

## Security and data isolation

- 瀏覽器設定改以不重複使用的帳號識別碼區分，同名的新帳號看不到舊帳號的設定。API 與查詢不變。

## Migration, rollout, and rollback

- Schema／資料 migration：無。舊的「略過引導」鍵在下次顯示時被接手。
- 上線與 smoke test：登入、註冊（邀請制）、刪除帳號、登出所有裝置、Strava 匯入視窗照常運作。
- 回滾方式與資料相容性：直接回滾 v5.2.5 image；新的鍵會被舊版忽略，只會再顯示一次引導或預設日期範圍。

## Acceptance criteria

- [x] AC-1：Given 一個帳號略過了引導，When 同名的新帳號（不同識別碼）登入，Then 仍看到引導；Given 舊版以名稱保存的略過，When 同名帳號登入，Then 接手一次並刪除舊鍵。
- [x] AC-2：Given 保存的 AI 對話，When 另一個識別碼的帳號在同一分頁登入，Then 不恢復且捨棄它。
- [x] AC-3：Given Strava 匯入視窗，When 保存日期範圍，Then 以帳號識別碼為鍵，不以名稱為鍵。
- [x] AC-4：Given 正式映像，When 建置，Then 內含每個文件化的回滾腳本，基底以 digest 固定且 Dependabot 會更新它。
- [x] AC-5：Given 邀請制註冊，When 未填邀請碼，Then 由 `data-required` 判斷並擋下；刪除帳號、登出所有裝置與改密碼都經 `signOutWithNotice` 回到登入畫面。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/onboarding.test.cjs::SPEC-134 skipping belongs to the account ID: a reused name starts fresh, a pre-SPEC-134 choice is adopted once` |
| AC-2 | `unit_tests/frontend/updates.test.cjs::SPEC-059 completed AI turns survive a reload for the same account only` |
| AC-3 | `unit_tests/test_security_config.py::test_strava_frontend_uses_account_range_and_automatic_mileage_sync` |
| AC-4 | `unit_tests/test_deploy_workflow.py::test_image_ships_every_rollback_script_and_pins_its_base_by_digest` |
| AC-5 | `unit_tests/frontend/account.test.cjs::SPEC-075 registration sends the invite code and requires it in invite mode` |
