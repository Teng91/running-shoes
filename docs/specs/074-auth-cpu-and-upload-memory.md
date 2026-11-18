# SPEC-074：登入耗用的 CPU 與 Strava 上傳記憶體

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-073](073-api-flood-guard.md)、[SPEC-047](047-review-hardening-and-decoupling.md)

## Problem

- 每次登入、註冊與改密碼都做一次 bcrypt（cost 12，本機約 0.2 秒，Fly 共用 CPU 更慢）。原本的上限是每個 IP 每分鐘 120 次、全站 300 次，全站額度約等於每分鐘 60 秒以上的 CPU，可以把唯一的一顆 CPU 吃滿。
- Strava CSV 上限 10 MB，但解析時會有好幾份副本。備份還原已經限制同時只處理一個，Strava 預覽與匯入沒有，也沒有每個帳號的次數上限；同時丟幾個大檔可能讓 256 MB 機器記憶體不足。

## Goals

- 登入、註冊、改密碼的預設上限降為每個 IP 每分鐘 20 次、全站 60 次（約 18 秒 CPU／分鐘）。
- Strava 預覽與匯入每個程序同時只處理一個，忙碌時立即回 429；每個帳號每分鐘最多 10 次（`STRAVA_UPLOAD_RATE_LIMIT_PER_MINUTE`）。

## Non-goals

- 不改 bcrypt cost、登入失敗鎖定或 CSV 大小上限。
- 不改前端；忙碌與超量時沿用既有的錯誤訊息顯示。

## Proposed design

- `settings` 的 `AUTH_RATE_LIMIT_PER_MINUTE`／`AUTH_GLOBAL_RATE_LIMIT_PER_MINUTE` 預設改為 20／60。
- `routers/strava.strava_upload_slot()` 比照 `restore_slot`：`app.state.strava_upload_slot` 為每個程序一個的鎖，非阻塞取得，失敗回 429 與 `Retry-After: 5`。取得鎖之後才消耗 `rate_limits.enforce_strava_upload_limits()` 的帳號視窗，再讀檔與解析。

## Security and data isolation

- 帳號視窗以 user id 為鍵；忙碌的拒絕不讀取檔案、不消耗額度。
- 被攻擊時，正常使用者可能要等一分鐘才能登入；這是用 CPU 保護換來的代價。

## Migration, rollout, and rollback

- Schema／資料 migration：無，沿用 `rate_limit_buckets`。
- 上線與 smoke test：`release-check` 通過；登入與 Strava 匯入照常。
- 回滾方式與資料相容性：可直接回滾到 v4.19.3 image。

## Acceptance criteria

- [x] AC-1：Given 一個 Strava 上傳正在解析，When 同一程序再收到上傳，Then 立即回 429 且不消耗帳號額度。
- [x] AC-2：Given 帳號每分鐘上限 1，When 第二次預覽，Then 回 429。
- [x] AC-3：Given 預設設定，When 讀取登入限額，Then 每個 IP 20 次、全站額度的 bcrypt 時間低於一分鐘。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_strava_import.py::test_strava_worker_keeps_event_loop_responsive` |
| AC-2 | `unit_tests/test_api_extra.py::test_strava_uploads_have_a_per_account_budget` |
| AC-3 | `unit_tests/test_api_extra.py::test_default_auth_budget_keeps_bcrypt_under_a_minute_of_cpu` |
