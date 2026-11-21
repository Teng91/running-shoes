# SPEC-093：整體審查修正：日曆時區、帳號識別、管理員名稱、連線釋放與一致的捨入

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-087](087-session-binding-and-hardening.md)、[SPEC-085](085-auth-hardening.md)、[SPEC-090](090-module-decoupling.md)

## Problem

對整個專案（v4.26.1）的審查找到：

- 前端用裝置時區算「今天」，後端固定用台灣時間（UTC+8）。在比台灣快的時區（例如日本）午夜後新增跑步，預設日期是台灣的明天，後端回「run date must not be in the future」。
- 只改距離時沒有檢查已記錄的跑步時間，10 km／50 分鐘改成 0.5 km 會留下每公里 100 分鐘的配速，拉歪平均配速與賽事準備度。
- SQLite 會重複使用最大的 user id，而 AI、上傳、寄信與驗證碼的限流以 id 當 key；刪帳號沒有清掉，下一個帳號會沿用當天的額度。
- 「忘記密碼」寄信的每帳號上限以輸入的文字當 key，同一個帳號用名稱與 email 各申請一次就能寄出兩倍的信。
- `ADMIN_USERNAMES` 裡尚未註冊的名稱，在 `REGISTRATION_MODE=open` 時任何人都能搶先註冊而成為管理員。
- 沒有 `aid` 的舊格式 token（v4.24.2 以前）都已過期，相容分支只剩下沒有用處的例外。
- 同一把 `SECRET_KEY` 同時簽登入 token 與 email 驗證碼的 HMAC。
- `find_user` 用 Python 的 `lower()` 比對 SQLite 的 `lower(username)`；SQLite 只轉換 A–Z，所以「Ärger」註冊後無法登入。
- AI 對話串流在整段串流（可達數分鐘）中占用驗證時開啟的 SQLite 連線。
- `llm.py` 在 import 時讀取 API key、`OR_MODEL` 與輸出上限；`agent.py` 留著只轉呼叫 planner／protocol 的函式；read model 直接用 Python 的 `round()`（銀行家捨入），與輸入端的四捨五入不一致；`operations.legacy_operation` 沒有型別註記。

## Goals

- 前端的「今天」、預設月份與年份都依台灣日曆計算，與 `backend/clock.py` 一致。
- 只改距離而會讓已記錄時間的配速不合理時回 400，請使用者一併修改或清除時間。
- 刪除帳號時一併刪除以該帳號 id 為 key 的限流紀錄。
- 同一帳號的名稱與 email 共用一個重設密碼寄信上限。
- 尚未註冊的管理員名稱只有全新部署（沒有任何帳號）在 open 模式下的第一個帳號能註冊。
- 登入 token 必須帶 `aid`。
- email 驗證碼改用由 `SECRET_KEY` 衍生、只用於驗證碼的金鑰。
- 帳號名稱的比對、唯一性與登入鎖定都只忽略 ASCII 字母大小寫，與 SQLite 索引相同。
- AI 串流在等待模型時不占用資料庫連線。
- `create_app` 注入 LLM 設定；移除 agent 轉接函式；read model 統一用 `round_metric`（四捨五入）；補上型別。

## Non-goals

- 不改 JWT 的 7 天有效期與 localStorage 儲存方式（使用者於 2026-11-19 決定維持）。
- 不搬移前端的全域狀態；那是跨多個 PR 的重構，需要另開規格。
- 不改 Strava 匯入的台灣日期換算（單一時區的既有設計，README 已說明）。

## Proposed design

- `frontend/app-state.js` 的 `APP_UTC_OFFSET_MINUTES`（480，Python 測試比對 `clock.APP_TIMEZONE`）與 `appCalendarDate()`；`localDateISO()`、`previousMonthValue()`、Strava 預設區間、儀表板日期與年份選單都改用它。
- `services/runs.update_run`：只送 `km`、且已有 `duration_seconds` 時以新距離檢查 `is_plausible_duration`。
- `services/accounts.account_rate_limit_keys()` 列出 `rate_limits` 以帳號命名的 key，`delete_account` 在同一交易刪除。
- `routers/auth.request_password_reset` 以 `email_codes.attempt_key()` 組成寄信 key。
- `accounts.register`：`username.casefold() in admin_names` 時，除非是 open 模式且沒有任何帳號，否則回「Username already registered」。
- `auth.get_current_user`：`payload.get("aid") != user.backup_id` 一律 401。測試用 `unit_tests/token_helpers.token_for()` 簽發含 `aid` 的 token。
- `email_codes.code_key()`：`HMAC(SECRET_KEY, "running-shoes/email-code/v1")`。部署時尚未使用的驗證碼失效（10 分鐘內），重新寄送即可。
- `accounts.username_key()`：trim 後只把 A–Z 轉小寫；`find_user` 與登入鎖定共用。
- `agent._execute_tool_safely` 每次工具呼叫後 `close()` session；`routers/agent.agent_chat_stream` 在開始串流前 `close()`。
- `llm.LLMConfig`／`configure()`／`current_config()`；`Settings.openrouter_api_key`；`create_app` 呼叫 `llm.configure(LLMConfig.from_settings(...))`。沒有 app 設定時（腳本、單元測試）才在呼叫當下讀環境。`Settings` 與 `LLMConfig` 的 `repr` 不含密鑰。
- `read_models/rounding.round_metric` 以 `Decimal(repr(x))` 與 `ROUND_HALF_UP` 捨入；read model 的 `round(x, n)` 全部改用它，測試禁止再出現。
- `schemas.MutationKind` 與 `operations.legacy_operation` 的型別註記。

## Security and data isolation

- 限流紀錄只刪除被刪帳號自己的 key；IP 與全站視窗不動。
- 管理員名稱規則讓一般註冊無法取得管理員權限；既有管理員不受影響。
- token 必須帶 `aid`，只是移除已過期格式的相容；目前登入不受影響。
- 驗證碼與 session token 的金鑰分開；回應內容與次數規則不變。

## Migration, rollout, and rollback

- Schema／資料 migration：無（schema 12 不變）。
- 上線與 smoke test：部署前自動快照；部署後 `release-check`。部署當下尚未使用的 email 驗證碼會失效。
- 回滾方式與資料相容性：可直接回滾至 v4.26.1 image；回滾後新版發出的驗證碼同樣失效，token 照常可用。

## Acceptance criteria

- [x] AC-1：Given 東京 00:30（台灣前一天 23:30），Then 前端的今天與預設月份是台灣的日期；前端偏移量與 `backend/clock.py` 一致，且不以裝置時區取年、月、日。
- [x] AC-2：Given 10 km、3000 秒的跑步，When 只把距離改成 0.5 km，Then 回 400 且資料不變；改成 12 km 或同時清除時間則成功。
- [x] AC-3：Given 有 AI、上傳、寄信與驗證碼限流紀錄的帳號，When 刪除帳號，Then 以它 id 命名的紀錄都被刪除，全站與 IP 視窗保留。
- [x] AC-4：Given 名稱與 email 輪流申請重設密碼，Then 第 4 次回 429，只寄出 3 封。
- [x] AC-5：Given open 模式且已有帳號，When 註冊尚未註冊的管理員名稱，Then 回「Username already registered」；全新部署的第一個帳號可以；後來的管理員先註冊一般名稱再加入 `ADMIN_USERNAMES`。
- [x] AC-6：Given 註冊「Ärger」，Then 可以登入、ASCII 字母不分大小寫、「ärger」是另一個帳號。
- [x] AC-7：Given 寄出驗證碼，Then 儲存的雜湊以衍生金鑰計算而不是 `SECRET_KEY` 本身，驗證仍成功；沒有 `aid` 的 token 回 401。
- [x] AC-8：Given 工具呼叫或 AI 對話串流開始，Then session 不在交易中（連線已歸還）。
- [x] AC-9：Given 2.675 等半數，Then read model 四捨五入為 2.68，且 read model 不再直接呼叫 `round(x, n)`；`create_app` 注入 LLM 金鑰、偏好模型與輸出上限，`llm.py` 不讀環境變數，`repr` 不含密鑰。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_review_hardening.py::test_frontend_calendar_mirrors_the_backend_time_zone`、`unit_tests/frontend/crud-reports.test.cjs::SPEC-093 today is the service calendar day, not the device time zone` |
| AC-2 | `unit_tests/test_review_hardening.py::test_a_distance_edit_keeps_a_stored_moving_time_plausible` |
| AC-3 | `unit_tests/test_review_hardening.py::test_deleting_an_account_clears_the_throttling_windows_named_by_its_id` |
| AC-4 | `unit_tests/test_review_hardening.py::test_a_username_and_its_email_share_one_password_reset_mail_budget` |
| AC-5 | `unit_tests/test_review_hardening.py::test_admin_names_cannot_be_claimed_after_the_first_account`、`unit_tests/test_invites_and_accounts.py::test_an_invite_cannot_claim_an_admin_name_that_is_not_registered` |
| AC-6 | `unit_tests/test_review_hardening.py::test_a_non_ascii_name_logs_in_and_lockouts_share_its_identity` |
| AC-7 | `unit_tests/test_review_hardening.py::test_email_codes_use_a_key_derived_for_that_purpose_only`、`unit_tests/test_invites_and_accounts.py::test_a_token_names_its_account_and_one_without_it_is_refused` |
| AC-8 | `unit_tests/test_review_hardening.py::test_tool_calls_and_the_chat_route_release_the_database_connection` |
| AC-9 | `unit_tests/test_review_hardening.py::test_aggregates_round_halves_up_like_entered_values`、`unit_tests/test_llm.py::test_spec_093_create_app_injects_the_key_and_limits_without_import_time_reads` |
