# SPEC-143：登入自動續期（最長 30 天）

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-109](109-session-single-writer.md)、[SPEC-129](129-local-data-account-key.md)

## Problem

登入 token 7 天後過期且沒有續期，每天使用的人每週也會被登出一次、重新輸入密碼。單純延長 token 效期會讓被複製的 token 長期有效。

## Goals

- `POST /api/auth/refresh` 以仍有效的 token 換一個新的 7 天 token，帳號、`token_version` 與 `aid` 不變。
- token 記錄 `auth_time`（輸入密碼的時間），續期沿用它；任何 token 的效期都不超過 `auth_time` 後 30 天。v5.4 前的 token 以「到期時間 − 7 天」當作登入時間。
- 前端在 App 顯示時與回到前景時，若 token 剩不到一半效期就續期，每個分頁每小時最多試一次；離線失敗下次再試，401 照常登出。
- 續期不中斷畫面上進行中的工作；另一個分頁續期同一帳號時直接採用新 token，不再要求重新登入；同名但不同帳號（`aid` 不同）的 token 一律不採用。

## Non-goals

- 不改用 HttpOnly cookie、refresh token 資料表或伺服器端 session；不改變「登出所有裝置」與改密碼讓舊 token 失效的行為。

## Proposed design

- `credentials.create_access_token(data, now=…)` 加入 `auth_time` 並把 `exp` 限制在 `auth_time + SESSION_MAX_AGE_DAYS`；`session_started_at(claims)` 處理舊 token。
- `auth.get_current_session()` 回傳帳號與驗證過的 claims，`get_current_user` 建立在它上面；`services.accounts.renew_session()` 簽發新 token；`routers/auth.refresh` 只轉交。
- 前端：`app-session.js` 的 `captureAuthSession()` 多回傳 `expiresAt`；`startAuthSession(token, name, { renewal: true })` 只接受同一個 `aid` 與 `sub` 的 token，世代不變；`isCurrentAuthSession` 在同一世代、同一帳號時視為同一個 session。`app-auth.js` 的 `renewSessionIfDue()` 在 `showAppView` 與 `visibilitychange` 時執行，`adoptRenewedToken()` 處理其他分頁的 `storage` 事件。

## Security and data isolation

- 續期需要有效且未撤銷的 token（簽章、效期、`token_version`、`aid` 都檢查）；撤銷後無法續期。
- 30 天上限寫在 token 內並由伺服器計算，用戶端無法延長。
- 新 token 只回給持有舊 token 的請求，不寫入資料庫，不記錄 token 內容。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：`release-check`；`/api/openapi.json` 列出 `POST /api/auth/refresh`。
- 回滾方式與資料相容性：可直接回滾至 v5.3.7 image；新 token 多出的 `auth_time` 會被舊版忽略，已續期的 token 照常有效到期滿。

## Acceptance criteria

- [x] AC-1：Given 登入，When 取得 token，Then 它記錄 `auth_time`；Given 有效 token，When 呼叫 `/api/auth/refresh`，Then 得到同一帳號、`auth_time` 不變、到期更晚的 token，且能用來呼叫 API。
- [x] AC-2：Given 登入 28 天的 token，When 續期，Then 新 token 在登入後 30 天到期；舊版 token 以到期前 7 天為登入時間。
- [x] AC-3：Given 過期、缺少或已撤銷的 token，When 續期，Then 回 401／403。
- [x] AC-4：Given 前端 token 過半，When App 顯示，Then 續期一次並保留進行中的工作；未過半不送請求、失敗每小時最多重試一次；另一個分頁續期同帳號時採用新 token，不同帳號則登出。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_session_renewal.py::test_login_tokens_record_when_the_password_was_entered`、`unit_tests/test_session_renewal.py::test_renewal_keeps_the_identity_and_the_sign_in_time` |
| AC-2 | `unit_tests/test_session_renewal.py::test_renewal_never_extends_a_session_past_30_days`、`unit_tests/test_session_renewal.py::test_tokens_issued_before_renewal_count_from_their_expiry` |
| AC-3 | `unit_tests/test_session_renewal.py::test_revoked_expired_or_missing_tokens_cannot_be_renewed` |
| AC-4 | `unit_tests/frontend/reliability.test.cjs::SPEC-143 a renewed token of the same account continues the session in this and other tabs`、`unit_tests/frontend/reliability.test.cjs::SPEC-143 renewal waits until half the token has passed and retries at most hourly` |
