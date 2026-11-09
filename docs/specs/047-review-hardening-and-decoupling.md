# SPEC-047：程式審查修正、有界歷史與模組解耦

- 狀態：Implemented（v4.7.1 修訂：AC-12～AC-16）
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[ADR-0004](../adr/0004-request-reliability-and-release-gates.md)、[SPEC-019](019-reliable-requests-and-release-gates.md)、[SPEC-033](033-recovery-and-sync-identity.md)、[SPEC-036](036-security-hardening-and-portable-locks.md)

## Problem

一次全面程式審查（v4.6.0，`verify` 全綠）找到下列問題：

- **Strava 日期**：`activities.csv` 的 Activity Date 是 UTC。舊解析只取日期部分，台灣早上 8 點前的跑步會記到前一天；如果是每月 1 日，還會算到上個月。
- **版本 null**：`PUT /api/runs/{id}` 送 `expected_version: null` 時，查詢變成 `version IS NULL`，永遠回 409「已被更新」；鞋款與月跑量同樣情況回 422。
- **匯出檔名時區**：檔名用伺服器時區，Fly（UTC）上比台灣慢 8 小時。
- **測試寫法**：一個測試字串含無效跳脫字元，在 Python 3.14 出現 SyntaxWarning。
- **月跑量 ID 浪費**：每新增一筆跑步就配置一個月跑量 ID，即使該月份已存在。
- **稽核 trigger**：以 `CREATE TRIGGER IF NOT EXISTS` 建立，欄位清單寫死。日後加欄位時，復原會遺失新欄位；刪除欄位則會讓所有寫入失敗。
- **資料表無上限成長**：`audit_events`、`mutation_receipts`、`run_creation_requests` 沒有保留上限。刪除墓碑又是從稽核紀錄推導，無法安全清理。
- **帳號鎖定**：只以帳號計算，任何人都能把已知帳號鎖在外面。
- **密鑰長度**：正式環境不檢查 SECRET_KEY 長度。
- **重複收據**：建立跑步有兩套收據；內層重播分支永遠跑不到（coverage 證實）。
- **import 時期副作用**：`auth`、`rate_limits`、`database` 在 import 時讀全域設定、建立 engine 或結束程序，繞過 `create_app(config)` 的注入。
- **限流雙重計算**：同一限額在記憶體與 SQLite 各算一次，限流還會 commit 請求的 session。
- **Router 與重複程式碼**：Router 仍持有查詢，上傳上限文字寫死。鞋款驗證器重複三次，操作分派每次重建字典。
- **前端 inline 事件**：前端有約 80 個 inline `on*=` 事件，markup 直接耦合全域函式名稱。
- **測試資源**：測試留下 330 個未關閉 SQLite 連線警告。

## Goals

- **Strava 日期**：時間戳轉成台灣日期。重新匯入時只修正「仍停在舊 UTC 日期」的跑步，手動改過的日期保留，月跑量跟著移到正確月份。
- **錯誤與時間**：null 版本回 422；匯出檔名使用 `clock.local_now()`；月份已存在時不配置新 ID。
- **Schema 7**：啟動時重建全部稽核 trigger；新增 `run_tombstones`；替 `mutation_receipts` 加上 `recorded_at`；移除 `run_creation_requests`。
- **保留上限**：每次寫入時，每個帳號保留最新 5,000 筆稽核、1,000 筆收據、50,000 個墓碑。
- **登入鎖定**：同一來源對同一帳號失敗 10 次只鎖該來源；跨來源累計 100 次才鎖整個帳號。
- **密鑰**：正式環境要求 SECRET_KEY 至少 32 bytes；開發環境的預設密鑰也達 32 bytes。
- **模組解耦**：
  - 匯入 backend 模組不做任何 I/O。
  - 限流只用 SQLite，在獨立交易中以 all-or-nothing 方式消耗。
  - Router 委派查詢；上傳上限文字依實際限制產生。
  - 驗證規則各只定義一次；操作分派使用固定註冊表。
  - 前端改以 `data-*` 動作委派事件。
  - 測試不留未關閉連線。

### v4.7.1 修訂

v4.7.0 上線後再審查發現：

- 保留上限只依 id 排序，匯入含大量歷史的備份會擠掉本機可復原的紀錄（已重現）。
- 過期的還原預覽只有同一帳號再預覽時才清除。
- 年目標 `monthly_km * 12` 沒有四捨五入，會寫進資料庫並出現在備份。
- 模型刷新冷卻若設定超過限流紀錄保留時間（1 小時）會被提早清除。

## Non-goals

- 不把 30 個前端 classic script 全面改成 ES modules；全域狀態維持現況，只解除 markup 與函式名稱的耦合。
- 不改 `backend/llm.py` 的模型清單快取（仍在 import 時讀取 `OR_MODEL`／token 上限）。
- 不新增一般 CRUD 的請求頻率限制；儲存空間由保留上限約束。
- 不自動改寫沒有重新匯入的舊 Strava 紀錄；沒有原始時間戳就無法判斷正確日期。

## Proposed design

- **Strava**（`strava_import.py`）：`parse_activity_dates()` 回傳（台灣日期, UTC 日期），中英文 12 小時制都支援，只有日期時直接採用。`date_corrections()` 只選出儲存日期等於 UTC 日期、且不同於台灣日期的既有活動。預覽回傳 `date_correction_count` 與最多 5 筆樣本；匯入在同一交易修正日期、版本 +1，並把里程從舊月移到新月，結果回傳 `corrected_dates`。
- **身分與保留**：
  - `run_identity.record_tombstone()` 由 `delete_run` 呼叫，`add_local_tombstones()` 只讀 `run_tombstones`。
  - `services/retention.py` 的 `prune_account_history()` 由 `write_transaction` 在 commit 前呼叫，只刪除該帳號超出上限的最舊資料。
  - `fingerprints.py` 取代 `run_requests.py`，只保留 `payload_hash`。
- **組合根**：
  - `settings.runtime_settings()` 驗證密鑰；`create_app()` 是唯一建立預設 engine 的地方。
  - `database.py` 只提供 Base、連線 pragma 與 `create_database_engine()`。
  - `dependencies.get_db()` 從 `app.state.session_factory` 取得 session。
- **限流**（`rate_limits.py`）：只用 `Window` 與 `consume()`／`reject_if_full()`，透過 `app.state.db_engine` 在獨立交易中執行；超限時整個交易回滾，所有視窗都不計數。登入失敗分成「來源＋帳號」與「帳號」兩個視窗。
- **其他後端**：
  - `audit_schema.install_audit_triggers()` 在同一交易中先 `DROP` 再 `CREATE`。
  - `apply_run_mileage_deltas()` 先 UPDATE 月份，不存在時才配置 ID 並新增。
  - 鞋款欄位以 `Annotated[..., AfterValidator]` 型別共用；`operations._HANDLERS` 固定註冊表。
- **前端**：
  - `frontend/app-actions.js` 以 `UI_ACTIONS` 對應 `data-click`／`data-change`／`data-input`／`data-submit`／`data-dblclick`／`data-keydown`。
  - 只處理最近的宣告元素；送出表單與 `<a>` 由動作接管預設行為。
  - 開機重試按鈕在 inline boot script 綁定。唯一保留的 inline 事件是非阻塞樣式表的 `onload`，它必須在任何 app script 之前執行。

- **v4.7.1**：`retention.prune_account_history()` 對本機（`imported=0`）與備份帶入（`imported=1`）的稽核紀錄分開保留各 5,000 筆。`account_restore.discard_expired_previews()` 由 `create_app` 的 lifespan 在啟動時呼叫，只刪已過期的暫存預覽。`goals.yearly_goal_km()` 統一推算、寫入與匯出的年目標。`settings.RATE_LIMIT_BUCKET_RETENTION_SECONDS` 同時限制冷卻設定與限流紀錄保留時間。

## Security and data isolation

- 墓碑、收據、稽核清理與 Strava 日期修正都以 `user_id` 限定；保留上限不會刪除其他帳號的資料。
- 限流只寫 `rate_limit_buckets`，不再 commit 請求 session 中未完成的業務資料。
- 正式環境拒絕缺少或過短的 SECRET_KEY；開發用密鑰只在非 production 環境使用。
- 前端動作只讀資料屬性，不再在 markup 中組合 JavaScript 字串。

## Migration, rollout, and rollback

- **Schema／資料 migration**：Schema 6 → 7。
  - 從未匯入的稽核刪除事件回填 `run_tombstones`。
  - 替 `mutation_receipts` 新增 `recorded_at`（既有收據為 0，最先被清理）。
  - 移除 `run_creation_requests`；同一筆收據早已同時寫在 `mutation_receipts`。
  - 每次啟動都重建稽核 trigger。
- **上線與 smoke test**：
  1. 部署前建立並驗證異地備份，在私有副本重複執行升級兩次，確認業務資料雜湊不變。
  2. 確認 Fly 的 SECRET_KEY 至少 32 bytes；README 的 `openssl rand -hex 32` 會產生 64 字元。
  3. Asset 4.7.0／shell v54／51 個 release assets。部署後執行匿名 `release-check`。
  4. 用自己的 Strava 匯出檔預覽一次，確認某筆清晨跑步的修正方向正確（例如 10/31 → 11/01）再匯入。
- **回滾方式與資料相容性**：
  1. 停止寫入並另做 schema 7 備份。
  2. 執行 [`scripts/rollback_schema_seven.sql`](../../scripts/rollback_schema_seven.sql)：重建空的 `run_creation_requests`，marker 改回 6。
  3. 部署 v4.6.0 image。`run_tombstones` 與 `recorded_at` 會保留，舊版程式不讀取它們。
  4. 之後再升級時，會重新從稽核紀錄回填期間的刪除。

## Acceptance criteria

- [x] AC-1：Given Strava 匯出的 UTC 時間戳，When 解析、預覽與匯入，Then 跑步記在台灣日期。仍停在舊 UTC 日期的既有跑步會被修正並移動月跑量，手動改過日期的保留；只有修正時也可匯入。
- [x] AC-2：Given 跑步更新送 `expected_version: null`，When 呼叫 API，Then 回 422 且資料不變；匯出檔名使用台灣時間；同月份新增跑步不消耗新的月跑量 ID。
- [x] AC-3：Given 舊版欄位清單的稽核 trigger，When 啟動 migration，Then trigger 依目前欄位重建，快照包含新欄位。
- [x] AC-4：Given 帳號持續寫入，When 超過保留上限，Then 只刪除該帳號最舊的稽核、收據與墓碑。稽核被清理後，本機刪除的跑步仍不會被備份復原；匯入的歷史不產生墓碑；schema 7 會回填既有墓碑並移除舊收據表，且可依文件回滾。
- [x] AC-5：Given 單一來源連續輸錯密碼，When 達到上限，Then 只鎖該來源，帳號擁有者從其他來源仍可登入；跨多個來源累計達上限才鎖整個帳號。
- [x] AC-6：Given 正式環境，When SECRET_KEY 缺少或少於 32 bytes，Then 建立 app 失敗；匯入 backend 模組不建立資料庫目錄、engine，也不驗證密鑰。
- [x] AC-7：Given 限流，When 任一視窗已滿，Then 同一請求的所有視窗都不計數、請求的 session 不被 commit，限額來自注入的 settings。
- [x] AC-8：Given 帶 `Idempotency-Key` 的建立跑步，When 重送或並行，Then 只由 `mutation_receipts` 回放同一結果。
- [x] AC-9：Given Router 與上傳限制，When 列出跑步或超過上限，Then 查詢由 read model 執行、錯誤文字依實際上限產生。
- [x] AC-10：Given 前端 markup 與動態列，When 檢查來源與觸發事件，Then 除了樣式表 `onload` 沒有 inline 事件；每個 `data-*` 動作都有唯一註冊，巢狀元素只執行最近的動作；開機重試不依賴 app bundle。
- [x] AC-11：Given 測試建立的 engine，When 測試結束，Then 連線全部關閉，不產生 ResourceWarning。

- [x] AC-12：Given 本機有可復原的刪除，When 匯入含大量歷史的備份，Then 本機紀錄保留且仍可復原，帶入的歷史另受自己的上限限制。
- [x] AC-13：Given 多個帳號已過期與未過期的還原預覽，When 服務啟動，Then 只刪除已過期的預覽。
- [x] AC-14：Given 月目標 12.3 km，When 更新、讀取或匯出，Then 年目標為 147.6；修正前寫入的舊值也輸出 147.6。
- [x] AC-15：Given `MODEL_REFRESH_COOLDOWN_SECONDS` 大於 3600，When 讀取設定，Then 冷卻限制為 3600，且所有限流視窗都不超過紀錄保留時間。
- [x] AC-16：Given 歷史復原遇到較新的資料或資料庫未就緒，When 復原或讀取 `/health/ready`，Then 分別回衝突且不覆寫較新資料、回 503。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_strava_import.py::test_strava_utc_timestamps_become_taipei_calendar_dates`、`unit_tests/test_strava_import.py::test_reimport_moves_runs_stored_on_the_old_utc_date`、`unit_tests/frontend/feature-operations.test.cjs::SPEC-047 Strava preview explains UTC date corrections and allows a correction-only import` |
| AC-2 | `unit_tests/test_runs_api.py::test_run_log_update_rejects_explicit_nulls`、`unit_tests/test_clock.py::test_export_filename_uses_the_application_timezone_not_the_server_zone`、`unit_tests/test_runs_api.py::test_runs_in_an_existing_month_do_not_consume_monthly_identifiers` |
| AC-3 | `unit_tests/test_history.py::test_startup_rebuilds_stale_audit_triggers_from_current_columns` |
| AC-4 | `unit_tests/test_history.py::test_each_write_keeps_only_the_newest_history_per_account`、`unit_tests/test_history.py::test_run_deletion_tombstones_survive_audit_retention`、`unit_tests/test_history.py::test_schema_seven_backfills_tombstones_from_audit_history`、`unit_tests/test_account_restore.py::test_local_deletion_tombstone_is_preserved_after_audit_rows_are_pruned`、`unit_tests/test_account_restore.py::test_imported_history_cannot_create_local_tombstones`、`unit_tests/test_request_reliability.py::test_schema_seven_drops_superseded_run_receipts_without_changing_business_rows`、`unit_tests/test_request_reliability.py::test_schema_seven_rollback_restores_the_schema_six_contract_and_reupgrades` |
| AC-5 | `unit_tests/test_api_extra.py::test_failed_logins_lock_one_address_before_the_whole_account`、`unit_tests/test_api_extra.py::test_repeated_password_failures_lock_only_that_account` |
| AC-6 | `unit_tests/test_import_paths.py::test_production_refuses_a_missing_or_short_secret_key`、`unit_tests/test_import_paths.py::test_development_without_secret_uses_a_long_fallback_and_warns`、`unit_tests/test_import_paths.py::test_importing_backend_modules_performs_no_database_io` |
| AC-7 | `unit_tests/test_api_extra.py::test_rate_limit_checks_never_commit_the_request_session`、`unit_tests/test_api_extra.py::test_throttled_client_does_not_consume_global_auth_budget`、`unit_tests/test_api_extra.py::test_model_refresh_has_global_limit_across_users`、`unit_tests/test_api_extra.py::test_rate_limit_windows_reset_after_their_fixed_window` |
| AC-8 | `unit_tests/test_request_reliability.py::test_replayed_run_returns_original_snapshot_and_updates_mileage_once`、`unit_tests/test_request_reliability.py::test_concurrent_requests_share_one_committed_receipt` |
| AC-9 | `unit_tests/test_runs_api.py::test_run_list_read_model_scopes_users_and_calendar_filters`、`unit_tests/test_strava_import.py::test_upload_limit_messages_follow_the_configured_limits` |
| AC-10 | `unit_tests/frontend/presentation-shell.test.cjs::SPEC-047 markup declares UI actions instead of inline JavaScript handlers`、`unit_tests/frontend/presentation-shell.test.cjs::SPEC-047 every declared data action has exactly one registered handler`、`unit_tests/frontend/presentation-shell.test.cjs::SPEC-047 delegated dispatch runs only the nearest action and owns navigation defaults` |
| AC-11 | `unit_tests/test_database.py::test_engines_opened_inside_a_test_are_disposed_afterwards`、`python3 scripts/task.py test-fast` |
| AC-12 | `unit_tests/test_account_restore.py::test_imported_history_never_evicts_local_recoverable_events` |
| AC-13 | `unit_tests/test_account_restore.py::test_startup_discards_every_accounts_expired_previews_only` |
| AC-14 | `unit_tests/test_goals.py::test_derived_yearly_goal_is_stored_returned_and_exported_at_two_decimals` |
| AC-15 | `unit_tests/test_security_config.py::test_rate_limit_windows_never_outlive_bucket_retention` |
| AC-16 | `unit_tests/test_history.py::test_restore_refuses_to_overwrite_later_changes`、`unit_tests/test_health.py::test_readiness_reports_503_for_missing_stale_or_unavailable_databases` |
