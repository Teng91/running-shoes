# SPEC-055：資料正確性修正與 Strava 刪除記憶

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-005](005-startup-loading-screen.md)、[SPEC-040](040-highlights-review-and-mobile-navigation.md)、[SPEC-047](047-review-hardening-and-decoupling.md)、[SPEC-050](050-recent-shoe-share.md)

## Problem

2026-11-15 的全面檢查找到幾個會讓畫面或 AI 給出錯誤資訊的問題：

- **刪掉的 Strava 跑步會被重新匯入。**
  - 以臨時測試重現：刪除一筆 Strava 匯入的跑步，再匯入同一份 CSV，那筆會重建，鞋子與月份里程也會再加一次。
  - README 說「重複選擇同一份 CSV 不會重複建立紀錄或再次增加里程」，備份還原也保證「重複匯入不撤銷後續刪除」，Strava 匯入卻沒有做到。
  - 原因是 `run_tombstones` 只存跑步 ID，跑步被實體刪除後就失去 Strava 活動 ID，匯入只拿現有跑步比對。
- **年度回顧的「比去年」在年中偏低。**`year_review` 把今年 1/1 到今天的里程拿去比前一年全年，11 月時常顯示負成長，即使實際比去年同期多。
- **已退役的鞋仍有「預估退役日期」。**`retirement_forecast` 沒有判斷 `is_retired`，單鞋分析與 AI 工具 `shoe_usage_analytics` 會說一雙已退役的鞋「預估 2027/03 退役」。
- **換鞋提醒門檻不一致。**
  - 首頁提醒、跑鞋壽命狀態與 AI 規則都是 90% 起算「可以準備換鞋」。
  - 跑步日誌頁的洞察（`dashboard_analytics`）卻要到 100% 才標為緊急，同一雙 95% 的鞋在兩頁顏色不同。
- **跑步日誌卡片寫死「本月」。**看過去月份時，「本月總里程／本月主力鞋」的標籤是錯的。
- **登入表單關閉了自動完成。**SPEC-005 設了 `autocomplete="off"`，密碼管理器無法填入帳密；token 7 天到期後必須手動輸入密碼。
- **iOS meta 過時。**`apple-mobile-web-app-capable` 已被標準的 `mobile-web-app-capable` 取代，瀏覽器會警告。

## Goals

- 刪除過的 Strava 活動，重新匯入時一律略過；預覽與結果告訴使用者略過了幾筆、可從異動歷史復原。
- 升級前已刪除的 Strava 跑步，在稽核紀錄還保留時一併記住。
- 年度回顧在年份進行中時與前一年同期比較，已結束的年份才比全年。
- 已退役的鞋不產生退役預估，所有介面與 AI 工具一致。
- 80%／90% 兩級換鞋門檻只定義一次，前後端與 AI 共用。
- 跑步日誌卡片顯示所選月份；登入欄位使用標準的 `autocomplete` 值；加上標準的 capability meta。

## Non-goals

- 不做 token 自動續期。前端以 token 字串辨識 session，任何分頁更換 token 都會讓其他分頁登出（SPEC-019）；續期需要先設計跨分頁接手同一帳號的新 token，另立規格。
- 不改備份還原的比對方式：同來源還原已由 `add_local_tombstones` 保留刪除。
- 不讓使用者在匯入時選擇「把刪除過的活動加回來」；需要時以異動歷史復原（仍檢查 Strava 重複與配額）。

## Proposed design

- **Schema 8：`run_tombstones.strava_id`**
  - 新增 nullable 欄位與部分索引 `idx_run_tombstones_user_strava (user_id, strava_id) WHERE strava_id IS NOT NULL`。
  - `run_identity.record_tombstone(db, user_id, run_id, strava_id)` 在 `delete_run` 的同一交易寫入；同一跑步重複寫入時保留已知的活動 ID（`COALESCE`）。
  - `run_identity.deleted_strava_ids(db, user_id)` 只讀本帳號的活動 ID。
  - Migration（`applied_version < 8`）從同一跑步的本機刪除稽核事件 `before_json.strava_id` 回填，稽核已被保留上限清掉的無法回填。
- **Strava 預覽與匯入**
  - 比對順序：已存在（重複）→ 同檔重複 → 刪除過（`deleted_count`／`skipped_deleted`）→ 鞋款配對。
  - 刪除過的活動不進鞋款分組與可匯入合計，不增加里程。匯入摘要歷史的欄位不變。
  - 前端預覽顯示「另有 N 筆先前刪除過的活動不會重新匯入（可從異動歷史復原）」，匯入結果附上略過筆數。
- **年度回顧**：`previous_year_km` 改為前一年 1/1 到 `end` 的同月同日（2/29 對應 2/28），新增 `previous_year_end`。前端在未完成的年份顯示「比 YYYY 年同期」。
- **退役預估**：`retirement_forecast` 對 `is_retired` 回傳 `forecast_retirement_date: null`、`forecast_source: "retired"`，月均改用實際值。`ShoeOut.forecast_source` 的 Literal 加入 `"retired"`；單鞋分析顯示「已退役／退役後不再預估」。
- **門檻**：
  - `shoe_metrics.MONITOR_USAGE_PERCENT = 80`、`REPLACE_SOON_USAGE_PERCENT = 90`，由 `read_models/shoes.py`、`read_models/highlights.py` 與 `analytics.py` 共用。
  - 前端 `app-state.js` 的 `LIFECYCLE_MONITOR_PERCENT`／`LIFECYCLE_REPLACE_SOON_PERCENT` 鏡像這兩個值，pytest 比對兩邊相同。
- **跑步日誌卡片**：標籤改為「9 月總里程」「9 月主力鞋」。
- **登入表單（取代 SPEC-005 停用自動完成的決定）**：
  - 帳號欄位 `autocomplete="username"`、`autocapitalize="none"`。
  - 登入與舊密碼欄位用 `current-password`；註冊與新密碼欄位用 `new-password`。
  - 登入、登出與換帳號時仍清空所有欄位（`resetAuthInputs`），多人共用裝置的保護維持。密碼管理器只在裝置擁有者同意時填入。
- **Meta**：在 `apple-mobile-web-app-capable` 前加入 `mobile-web-app-capable`，舊 iOS 仍讀得到。

## Security and data isolation

- `deleted_strava_ids` 與回填都以 `user_id` 限定；另一個帳號刪除同一活動不影響本帳號匯入（具名測試涵蓋）。
- Tombstone 只多存使用者自己匯入的 Strava 活動 ID，不含其他資料；仍受每帳號 50,000 筆保留上限。
- 自動完成屬性不送出任何資料；欄位清空與 token 處理不變。

## Migration, rollout, and rollback

- Schema／資料 migration：
  - Schema 7 → 8：`ALTER TABLE run_tombstones ADD COLUMN strava_id VARCHAR`、建立部分索引，並從稽核紀錄回填。
  - 業務資料、里程與帳號都不變。部署流程照 SPEC-048 先在 Fly 主機建立並驗證資料庫快照。
- 上線與 smoke test：
  - Asset 4.13.0／shell v63，已安裝的 PWA 透過 SPEC-049 提示更新。
  - 部署後 `release-check` 檢查 readiness 回報 schema 8。
  - 在正式站以自己的 Strava 匯出檔預覽一次，先前刪除的活動應出現在「先前刪除過」的筆數裡。
- 回滾方式與資料相容性：
  1. 停止寫入，確認 schema 8 備份可讀。
  2. 以 `sqlite3.Connection.executescript` 執行 [`scripts/rollback_schema_eight.sql`](../../scripts/rollback_schema_eight.sql)：守衛確認目前是 8，只把 marker 改回 7。
  3. 部署 v4.12.0 image。`strava_id` 欄位與索引保留，schema 7 程式不讀寫它們；之後再升級時會回填回滾期間刪除的活動。

## Acceptance criteria

- [x] AC-1：Given 一筆已刪除的 Strava 匯入跑步，When 再預覽或匯入同一份 CSV，Then 它計入 `deleted_count`／`skipped_deleted`，不進鞋款分組、不建立跑步、不增加里程；另一個帳號匯入同一活動不受影響；前端預覽說明略過的筆數。
- [x] AC-2：Given schema 7 資料庫中已刪除的 Strava 與手動跑步，When 升級到 schema 8，Then Strava 活動 ID 由稽核紀錄回填、手動跑步維持空值；8 → 7 回滾有守衛、保留所有資料，且可再升級。
- [x] AC-3：Given 進行中的年份，When 讀取年度回顧，Then 前一年里程只算到同月同日並回傳 `previous_year_end`，2/29 對應 2/28；已結束的年份比全年；前端標示「同期」。
- [x] AC-4：Given 已退役但仍有剩餘壽命的鞋，When 讀取跑鞋清單、單鞋分析或 AI 使用分析，Then 退役日期為 null、來源為 `retired`，畫面顯示「已退役」而非日期。
- [x] AC-5：Given 使用率 95%、85%、79.9% 的現役鞋，When 讀取首頁提醒、跑步日誌洞察與 AI 壽命狀態，Then 都是「緊急／準備換鞋」、「注意」與「無提醒」，前端常數與後端相同。
- [x] AC-6：Given 查看 9 月的跑步日誌，When 顯示摘要卡片，Then 標籤是「9 月總里程」「9 月主力鞋」，沒有「本月」。
- [x] AC-7：Given 登入、註冊與改密碼表單，When 讀取 markup，Then 沒有 `autocomplete="off"`，帳號與密碼欄位使用標準值；登出仍清空欄位；頁面帶標準 capability meta。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_strava_import.py::test_deleted_strava_activity_is_not_reimported_and_preview_counts_it`、`unit_tests/frontend/corrections.test.cjs::SPEC-055 the Strava preview explains activities deleted earlier` |
| AC-2 | `unit_tests/test_history.py::test_schema_eight_backfills_deleted_strava_activities_from_audit_history`、`unit_tests/test_request_reliability.py::test_schema_eight_rollback_keeps_rows_and_reupgrades` |
| AC-3 | `unit_tests/test_highlights.py::test_year_review_compares_an_unfinished_year_with_the_same_span_last_year`、`unit_tests/frontend/highlights.test.cjs::SPEC-055 an unfinished year is compared with the same span of the previous year` |
| AC-4 | `unit_tests/test_forecasting.py::test_retired_shoes_have_no_retirement_forecast_in_analysis_or_ai_tools`、`unit_tests/test_forecasting.py::test_batch_forecast_is_scoped_bounded_and_matches_analysis`、`unit_tests/frontend/corrections.test.cjs::SPEC-055 a retired shoe analysis says retired instead of forecasting a date` |
| AC-5 | `unit_tests/test_analytics.py::test_lifespan_thresholds_are_one_policy_for_alerts_status_and_frontend`、`unit_tests/frontend/corrections.test.cjs::SPEC-055 every lifespan alert uses the shared 80% watch and 90% replace thresholds` |
| AC-6 | `unit_tests/frontend/corrections.test.cjs::SPEC-055 run log cards name the selected month instead of this month` |
| AC-7 | `unit_tests/frontend/corrections.test.cjs::SPEC-055 sign-in fields let password managers fill and save credentials`、`unit_tests/frontend/presentation-shell.test.cjs::successful login and logout clear every authentication field` |
