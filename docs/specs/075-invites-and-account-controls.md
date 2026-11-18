# SPEC-075：邀請制註冊與帳號管理

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-071](071-public-site-hardening.md)、[SPEC-074](074-auth-cpu-and-upload-memory.md)

## Problem

- 任何人都能註冊（上限 100 個帳號），站長無法決定誰可以使用。
- 使用者無法刪除自己的帳號與資料。
- 沒有 email，忘記密碼就無法登入，站長也沒有協助的方式。
- 帳號名稱分大小寫，`Joy` 與 `joy` 可以是兩個帳號，容易混淆。
- 頁面沒有說明保存哪些資料、誰看得到。

## Goals

- 註冊預設需要邀請碼，可切換為開放或關閉。
- 管理員可以產生、查看、停用邀請碼，並替忘記密碼的人產生臨時密碼。
- 使用者輸入密碼後可以永久刪除帳號與所有資料。
- 帳號名稱不分大小寫。
- 登入與註冊頁有隱私說明。
- AI 每個帳號每天的預設上限降為 20 次，讓多人共用全站額度。

## Non-goals

- 不做 email 驗證碼找回密碼（另一版，需要寄信帳號）。
- 不做多層級權限；管理員看不到其他帳號的跑步資料。
- 不改登入憑證效期。

## Proposed design

- 設定：`REGISTRATION_MODE`（`invite` 預設、`open`、`closed`，其他值視為 `closed`）、`ADMIN_USERNAMES`（逗號分隔、不分大小寫）。
- Schema 11：`invites`（`code_hash` 唯一、備註、`max_uses`、`used_count`、`expires_at`、`revoked`），不參照 users；在沒有大小寫重複時建立 `uq_users_username_lower`。
- `services/invites.py`：8 碼邀請碼（排除易混淆字元），只存 SHA-256、只在產生時回傳；`redeem_invite` 以條件 UPDATE 扣用，在註冊交易內執行。
- `services/accounts.py`：`find_user` 以 `lower(username)` 查詢；`register` 依模式檢查邀請碼；`delete_account` 重新檢查密碼（錯誤回 400），依 metadata 由子表到父表刪除所有含 `user_id` 的表，最後刪除稽核紀錄、write context 與使用者；`admin_reset_password` 產生臨時密碼並讓舊 token 失效。
- `routers/admin.py`：`require_admin` 依 `settings.is_admin` 回 403；`routers/auth.py` 新增 `GET /registration`、`POST /delete-account`，`/me` 回傳 `is_admin`，登入失敗鎖定以 case-fold 後的名稱計算。
- 前端 `app-account.js`：註冊表單依模式顯示邀請碼欄位；「資料與同步」的管理員面板（只對管理員顯示）與刪除帳號。

## Security and data isolation

- 邀請碼、臨時密碼只在產生時顯示一次；資料庫只存邀請碼雜湊與密碼 bcrypt。
- 管理員路由需要登入且名稱在 `ADMIN_USERNAMES`；臨時密碼只改指定帳號，不讀取其資料。
- 刪除帳號只刪 `user_id` 等於自己的資料列，在單一交易內完成。
- 註冊、刪除帳號、臨時密碼都受登入頻率限制（SPEC-074）。

## Migration, rollout, and rollback

- Schema／資料 migration：schema 10 → 11，新增 `invites` 與名稱索引；既有帳號與資料不變。
- 上線與 smoke test：部署前自動備份；設定 `ADMIN_USERNAMES` secret；註冊頁顯示邀請碼欄位，管理員可產生邀請碼。
- 回滾方式與資料相容性：停止寫入並備份後執行 `scripts/rollback_schema_eleven.sql`（保留 `invites`、移除名稱索引），部署 v4.19.4 image；舊版會恢復開放註冊。

## Acceptance criteria

- [x] AC-1：Given 邀請制，When 沒有邀請碼、邀請碼用完、停用或過期，Then 註冊失敗；有效邀請碼註冊成功並扣用一次，失敗的註冊不扣用。
- [x] AC-2：Given closed 或 open 模式，When 註冊，Then 分別拒絕或直接成功；未知設定值視為 closed。
- [x] AC-3：Given 非管理員，When 呼叫任一管理員路由，Then 回 403；`/me` 標示是否為管理員。
- [x] AC-4：Given 管理員替帳號產生臨時密碼，When 對方使用舊 token 或舊密碼，Then 失敗，臨時密碼可登入。
- [x] AC-5：Given 大小寫不同的帳號名稱，When 註冊、登入或登入失敗，Then 視為同一個帳號。
- [x] AC-6：Given 刪除帳號，When 密碼錯誤回 400；正確時，Then 所有含 `user_id` 的表都沒有該帳號資料，其他帳號不受影響。
- [x] AC-7：Given schema 10 資料庫，When 升級，Then 建立 `invites` 與名稱索引；回滾腳本有守衛並可重新升級；舊資料有大小寫重複時仍能啟動。
- [x] AC-8：Given 前端，When 開啟註冊表單、管理員面板或刪除帳號，Then 依模式顯示邀請碼欄位、只對管理員顯示面板且跳脫備註、打錯密碼不登出。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_invites_and_accounts.py::test_invite_only_registration_spends_one_use_and_rejects_every_bad_code`、`unit_tests/test_invites_and_accounts.py::test_revoked_and_expired_invites_are_rejected` |
| AC-2 | `unit_tests/test_invites_and_accounts.py::test_closed_registration_and_open_mode`、`unit_tests/test_invites_and_accounts.py::test_settings_default_to_invite_only_and_fail_closed` |
| AC-3 | `unit_tests/test_invites_and_accounts.py::test_only_admins_reach_admin_routes_and_me_says_who_is_admin` |
| AC-4 | `unit_tests/test_invites_and_accounts.py::test_admin_reset_gives_a_temporary_password_and_ends_old_sessions` |
| AC-5 | `unit_tests/test_invites_and_accounts.py::test_usernames_are_case_insensitive_for_sign_up_login_and_lockout` |
| AC-6 | `unit_tests/test_invites_and_accounts.py::test_deleting_an_account_removes_every_row_it_owns_and_nothing_else` |
| AC-7 | `unit_tests/test_invites_and_accounts.py::test_schema_eleven_adds_invites_and_a_case_insensitive_name_index_then_rolls_back`、`unit_tests/test_invites_and_accounts.py::test_schema_eleven_skips_the_name_index_when_old_accounts_differ_only_by_case` |
| AC-8 | `unit_tests/frontend/account.test.cjs::SPEC-075 the sign-up form asks for an invite only when the server requires one`、`unit_tests/frontend/account.test.cjs::SPEC-075 registration sends the invite code and requires it in invite mode`、`unit_tests/frontend/account.test.cjs::SPEC-075 only admins see the invite panel; codes are escaped and spent ones cannot be revoked`、`unit_tests/frontend/account.test.cjs::SPEC-075 deleting the account needs the password and signs out only after the server confirms` |
