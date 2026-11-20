# SPEC-085：寄信憑證、管理員名稱與驗證碼次數

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-075](075-invites-and-account-controls.md)、[SPEC-079](079-email-recovery.md)

## Problem

公開 repo 的資安檢查找到三個問題：

- 寄信用 `smtplib.SMTP.starttls()` 不帶參數，Python 3.11 的預設 context 不驗證憑證與主機名稱；能攔截 Fly 到 Gmail 之間連線的人可以讀到 Gmail 應用程式密碼和驗證碼。
- 管理員權限跟著 `ADMIN_USERNAMES` 裡的名稱走。管理員刪掉帳號，或名單裡有還沒註冊的名稱時，拿到任何一組邀請碼的人都能註冊那個名稱成為管理員，再替任何帳號產生臨時密碼。
- 驗證碼每組最多試 5 次，但每次重寄都重新計算；檢查次數和累加次數也是兩個步驟，同時送出的猜測可以超過 5 次。用帳號與 email 輪流申請，持續一個月約有 6～12% 機率猜中重設碼。

## Goals

- SMTP STARTTLS 驗證伺服器憑證與主機名稱。
- 邀請制下不能註冊 `ADMIN_USERNAMES` 裡的名稱；管理員帳號不能刪除。
- 每組驗證碼的 5 次在比對前就以單一條件式 UPDATE 計入；每個帳號每天最多試 10 次驗證碼（帳號與 email 共用），重寄不重算。

## Non-goals

- 不改成以 user id 記錄管理員，也不新增資料表或欄位。
- 不改變驗證碼長度、有效時間與寄送上限。
- 不處理刪帳號後同名重新註冊時舊 token 的問題（另案）。

## Proposed design

- `backend/mailer.py`：`client.starttls(context=ssl.create_default_context())`。正式映像（`python:3.11-slim`）已含系統 CA。
- `services/accounts.register(..., admin_names)`：`mode == "invite"` 且名稱（casefold）在管理員名單時，回與「名稱已被註冊」相同的 `Username already registered`，不透露哪些名稱是管理員；檢查在同一個寫入交易裡，邀請碼不會被消耗。`open` 模式仍可註冊，供第一個管理員使用。
- `services/accounts.delete_account(..., is_admin)`：管理員回 400 `Admin accounts cannot be deleted`，不登出；要刪除須先從 `ADMIN_USERNAMES` 移除。前端翻成中文並說明。
- `services/email_codes._redeem`：在寫入交易內 `UPDATE ... SET attempts = attempts + 1 WHERE 未過期 AND attempts < 5`，更新到一列才讀出雜湊比對；錯的那次已經計入。
- `rate_limits.enforce_code_attempt_limit(request, purpose, key)`：`code-attempt` 視窗每天 10 次，在比對前計入（對或錯都算），並行請求無法繞過。重設密碼的 key 由 `email_codes.attempt_key` 以帳號 id 決定，帳號與 email 共用；不存在的帳號以輸入值為 key，行為相同。綁定 email 以登入帳號的 id 為 key。

## Security and data isolation

- 不新增或讀取其他帳號的資料；限流 key 只含帳號 id 或使用者輸入的識別字。
- 被拒的註冊與管理員名稱的回應和名稱已被使用時相同。
- 每天 10 次的上限可能讓被攻擊的帳號當天無法用 email 重設；仍可用密碼登入或請管理員產生臨時密碼。

## Migration, rollout, and rollback

- Schema／資料 migration：無；`code-attempt` 使用既有的 `rate_limit_buckets`。
- 上線與 smoke test：部署前自動快照；部署後在 Fly 主機上以 `ssl.create_default_context()` 對 `smtp.gmail.com:587` 完成 STARTTLS（不登入、不寄信）。
- 回滾方式與資料相容性：可直接回滾至 v4.23.0 image；`code-attempt` 桶 24 小時後自動清除。

## Acceptance criteria

- [x] AC-1：Given 設定 SMTP，When 寄信，Then STARTTLS 使用要求憑證且檢查主機名稱的 context。
- [x] AC-2：Given 邀請制與管理員名單裡尚未註冊的名稱，When 用有效邀請碼註冊該名稱（不分大小寫、前後空白），Then 回「名稱已被註冊」且邀請碼未被使用；open 模式可以註冊並成為管理員。
- [x] AC-3：Given 管理員，When 刪除帳號，Then 回 400 且帳號與登入都保留，前端說明要先從 `ADMIN_USERNAMES` 移除；移出名單後可以刪除。
- [x] AC-4：Given 一組驗證碼，When 輸入，Then 比對時次數已經寫入；用完 5 次後連正確的碼也不比對。
- [x] AC-5：Given 一個帳號，When 一天內以帳號或 email 輸入第 11 次驗證碼（即使重寄過、即使正確），Then 回 429；不存在的帳號同樣在第 11 次回 429，密碼登入不受影響。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_email_recovery.py::test_smtp_starttls_verifies_the_server_certificate` |
| AC-2 | `unit_tests/test_invites_and_accounts.py::test_an_invite_cannot_claim_an_admin_name_that_is_not_registered` |
| AC-3 | `unit_tests/test_invites_and_accounts.py::test_an_admin_account_cannot_be_deleted`、`unit_tests/frontend/account.test.cjs::SPEC-085 an admin who tries to delete the account is told why and stays signed in` |
| AC-4 | `unit_tests/test_email_recovery.py::test_an_attempt_is_counted_before_the_code_is_compared` |
| AC-5 | `unit_tests/test_email_recovery.py::test_code_attempts_are_capped_per_account_and_day_across_new_codes` |
