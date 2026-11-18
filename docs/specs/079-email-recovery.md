# SPEC-079：Email 驗證碼找回密碼

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-075](075-invites-and-account-controls.md)、[SPEC-074](074-auth-cpu-and-upload-memory.md)

## Problem

- 忘記密碼只能請管理員產生臨時密碼，使用者無法自己重設。

## Goals

- 使用者可以綁定 email；綁定前要輸入寄到該信箱的驗證碼。
- 登入頁的「忘記密碼」用帳號或 email 收驗證碼，輸入驗證碼與新密碼後重設，舊的登入全部失效。
- 寄信用專用 Gmail 與應用程式密碼（`SMTP_USERNAME`／`SMTP_PASSWORD`），沒有設定時這些功能自動隱藏。

## Non-goals

- 不強制註冊時綁定 email，也不做 email 登入。
- 不使用付費寄信服務或自有網域。

## Proposed design

- Schema 12：`users.email`（只在驗證後寫入，`lower(email)` 部分唯一索引）與 `email_codes`（每個帳號、每種用途一筆）。回滾腳本 `scripts/rollback_schema_twelve.sql`。
- `backend/mailer.py`：`smtp_mailer(settings)` 以 STARTTLS 登入 Gmail SMTP 寄出純文字信；未設定時為 `None`。`create_app` 放在 `app.state.mailer`，測試注入假的寄信函式。log 不含收件人、驗證碼或密碼。
- `services/email_codes.py`：6 位數驗證碼，10 分鐘內有效、最多試 5 次，只存以 `SECRET_KEY` 為金鑰的 HMAC；新的驗證碼取代舊的。綁定、確認、移除 email；忘記密碼的請求不論帳號或 email 是否存在都回同樣結果。
- `routers/auth.py`：`POST /api/auth/email/request|confirm|remove`、`POST /api/auth/password-reset/request|confirm`；`/registration` 回傳 `mail_enabled`，`/me` 回傳 `email`。忘記密碼的信在回應之後才寄（BackgroundTasks），回應時間不洩漏帳號是否存在；寄信失敗只記 log。
- `rate_limits.enforce_mail_limits`：每個 IP 10 分鐘 5 封、每個目標帳號 10 分鐘 3 封、全站每小時 100 封；確認驗證碼與重設受登入頻率限制。
- 前端 `app-account.js`：登入頁「忘記密碼？」與重設表單（打開表單時才查詢 `mail_enabled`，登入頁啟動時不發請求）；「資料與同步」的 Email 區塊。

## Security and data isolation

- 驗證碼只存 HMAC，DB 外洩也無法還原；嘗試 5 次或過期即失效，用過即刪除。
- 不揭露帳號或 email 是否存在；同一 email 不能綁兩個帳號（綁定時已登入，可以回覆衝突）。
- 刪除帳號時一併刪除驗證碼（`email_codes` 含 `user_id`）。
- 應用程式密碼只存在 Fly secret。

## Migration, rollout, and rollback

- Schema／資料 migration：11 → 12，新增欄位、索引與資料表；既有資料不變。
- 上線與 smoke test：部署前自動備份；`/api/auth/registration` 回 `mail_enabled: true`；以自己的帳號綁定 email 並收到驗證碼。
- 回滾方式與資料相容性：停止寫入並備份後執行 `scripts/rollback_schema_twelve.sql`（保留欄位與資料表、移除 email 索引），部署 v4.20.4 image。

## Acceptance criteria

- [x] AC-1：Given SMTP 設定，When 讀取設定，Then 兩個值都有才啟用；寄信使用 STARTTLS，失敗訊息不含憑證。
- [x] AC-2：Given 登入的帳號，When 申請綁定 email，Then 確認正確驗證碼後才綁定；錯誤碼、過期或錯 5 次被拒；同一 email 不能綁兩個帳號；可以移除。
- [x] AC-3：Given 已綁定 email，When 用帳號或 email 申請重設並輸入驗證碼，Then 密碼更新、舊 token 失效、驗證碼只能用一次。
- [x] AC-4：Given 不存在的帳號或沒有 email 的帳號，When 申請重設，Then 回應相同且不寄信；寄信失敗時回應也相同。
- [x] AC-5：Given 沒有 SMTP 設定或寄送過於頻繁，When 申請驗證碼，Then 回 503 或 429。
- [x] AC-6：Given schema 11，When 升級，Then 建立欄位、索引與資料表；回滾腳本有守衛並可重新升級；刪除帳號一併刪除驗證碼。
- [x] AC-7：Given 前端，When 打開「忘記密碼」表單，Then 才檢查是否有 email 功能（登入頁啟動時不發請求，PWA／離線不受影響），沒有時提示找管理員；Email 區塊依設定顯示或隱藏；重設流程顯示中性訊息並檢查新密碼。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_email_recovery.py::test_settings_enable_mail_only_with_both_credentials`、`unit_tests/test_email_recovery.py::test_smtp_sender_uses_starttls_login_and_hides_failures` |
| AC-2 | `unit_tests/test_email_recovery.py::test_email_is_bound_only_after_the_emailed_code_is_confirmed`、`unit_tests/test_email_recovery.py::test_codes_expire_and_lock_after_five_wrong_attempts` |
| AC-3 | `unit_tests/test_email_recovery.py::test_password_reset_by_username_or_email_ends_old_sessions` |
| AC-4 | `unit_tests/test_email_recovery.py::test_reset_requests_never_reveal_whether_an_account_or_email_exists`、`unit_tests/test_email_recovery.py::test_reset_mail_failure_keeps_the_same_answer` |
| AC-5 | `unit_tests/test_email_recovery.py::test_mail_routes_are_off_without_smtp_and_rate_limited` |
| AC-6 | `unit_tests/test_email_recovery.py::test_schema_twelve_adds_email_and_codes_then_rolls_back`、`unit_tests/test_email_recovery.py::test_deleting_an_account_removes_its_email_codes` |
| AC-7 | `unit_tests/frontend/account-email.test.cjs::SPEC-079 the forgot-password form checks for email only when opened and explains when it is off`、`unit_tests/frontend/account-email.test.cjs::SPEC-079 password reset sends the code request, answers neutrally and needs matching passwords`、`unit_tests/frontend/account-email.test.cjs::SPEC-079 the email section binds only after the code and can remove the address` |
