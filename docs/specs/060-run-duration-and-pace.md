# SPEC-060：跑步時間與配速

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-047](047-review-hardening-and-decoupling.md)、[SPEC-055](055-correctness-fixes-and-strava-deletions.md)

## Problem

- 跑步紀錄只有日期、距離與鞋款，看不出跑得多快，也無法比較不同鞋款或月份的配速。
- Strava 匯出的 `activities.csv` 其實有移動時間（`移動時間`／`Moving Time`，單位秒），匯入時沒有讀取。
- 已經匯入過的活動重新匯入時會被當成重複而略過，所以舊紀錄沒有辦法補上時間。

## Goals

- 手動新增與編輯跑步時可以選填跑步時間；後端依時間與距離自動算出配速。
- 跑步列表顯示時間與配速；月份卡片與單雙鞋分析顯示平均配速。
- Strava 匯入新活動時一併存下移動時間；重新匯入同一份 CSV 時，替既有紀錄補上還沒有的時間。
- 平均配速以時間加權：總時間 ÷ 有時間紀錄的總距離，不是把每筆配速相加平均。

## Non-goals

- 不存心率、步頻、爬升等其他欄位。
- 不串接 Strava API／OAuth，仍以 CSV 匯入。
- 不新增配速趨勢圖或 AI 配速工具；之後另開規格。
- 不改月報提示詞。

## Proposed design

- **資料模型**：`runs.duration_seconds`（INTEGER，可為 NULL）存移動時間的整數秒。配速不存，由 `backend/run_metrics.py` 的 `pace_seconds_per_km()` 推導（四捨五入到整秒）。
- **合理範圍**：時間 1 秒～7 天，換算配速須在每公里 1:00～60:00（`is_plausible_duration()`）。超出範圍通常是把分鐘打成秒或 GPS 異常。前端 `app-state.js` 鏡像同樣的上下限，Python 測試確保兩邊一致。
- **API**
  - `POST /api/runs`、`PUT /api/runs/{run_id}` 接受選填的 `duration_seconds`（嚴格整數）。更新時明確傳 `null` 會清除時間，這是 `RunUpdate` 唯一接受 null 的欄位；省略則保留。
  - 只更新時間時，`services/runs.py` 用已存的距離檢查配速，不合理回 400。只改距離時保留原時間，配速跟著新距離。
  - `RunOut` 回傳 `duration_seconds` 與計算欄位 `pace_seconds_per_km`。
  - `GET /api/runs/summary` 新增 `timed_run_count` 與 `average_pace_seconds_per_km`；`GET /api/shoes/{shoe_id}/analytics` 的 `usage` 新增 `average_pace_seconds_per_km`，`recent_runs` 每筆加上 `pace_seconds_per_km`。
- **Strava**
  - `strava_import.parse_csv()` 讀 `移動時間`／`Moving Time`，沒有或不可用時退回 `經過時間`／`Elapsed Time`。時間缺漏或配速不合理時只是不存時間，活動照常匯入。
  - `duration_backfills()` 找出 CSV 中已存在、但 `duration_seconds` 為 NULL 的活動；已存的時間絕不覆寫，與已存距離換算不合理的也略過（例如距離被手動改過）。
  - 預覽回傳 `duration_backfill_count`；匯入在同一個交易中補上時間並遞增 `version`，結果回傳 `backfilled_durations`。只補時間、沒有新活動的匯入也能執行。
  - 只處理日期範圍內的活動，與既有的匯入範圍一致。
- **備份**：帳號備份升為 v4，跑步多了 `duration_seconds`。v1～v3 不得含時間；v1～v3 的指紋不含此欄位，保持不變。合併匯入時，備份裡沒有時間的跑步不會清除既有時間。刪除復原從稽核快照帶回時間。
- **前端**
  - 新增與編輯表單多一欄「跑步時間（選填）」，接受 `32:15`、`1:05:30` 或整數分鐘 `45`，下方即時顯示配速提示；送出前檢查格式與合理範圍。編輯時清空欄位會清除時間。
  - 跑步列表新增「時間」「配速」欄；月份總里程卡片顯示「平均配速」；單雙鞋分析的總里程卡片與最近跑步表格顯示配速。
  - 草稿與離線佇列一併保存時間欄位。

## Security and data isolation

- 時間屬於使用者自己的跑步紀錄。所有讀寫沿用既有 `user_id` 條件：回填只更新 `Run.user_id == user_id` 且 `strava_id` 相符的列，其他帳號的同一個 Strava 活動不受影響。
- 不涉及密鑰或外部服務。配速完全由後端程式計算，不交給 LLM。

## Migration, rollout, and rollback

- Schema／資料 migration：schema 9 只執行 `ALTER TABLE runs ADD COLUMN duration_seconds INTEGER`，既有資料保持 NULL，不改寫任何列。上線前依 SPEC-048 流程建立並驗證資料庫快照。
- 上線與 smoke test：部署後 `release-check`；登入後新增一筆含時間的跑步，確認列表顯示配速；用 Strava CSV 預覽確認「補上跑步時間」筆數。
- 回滾方式與資料相容性：
  1. 停止寫入並確認 schema 9 備份。
  2. 以 `sqlite3.Connection.executescript` 執行 [`scripts/rollback_schema_nine.sql`](../../scripts/rollback_schema_nine.sql)：守衛確認目前是 9，只把 marker 改回 8。
  3. `duration_seconds` 欄位保留；schema 8 程式不讀寫它，之後再升級即可沿用。回滾期間改過距離的跑步保留舊時間，配速依新距離計算。
  4. v4 備份無法由舊版讀取，舊版會拒絕而不會靜默遺失時間。

## Acceptance criteria

- [x] AC-1：Given 手動新增跑步填了時間，When 儲存，Then 回應與列表含 `duration_seconds` 與正確的 `pace_seconds_per_km`；沒填時兩者為 null。
- [x] AC-2：Given 時間格式錯誤或配速超出每公里 1:00～60:00，When 新增或只更新時間，Then 回 422／400 且不寫入；明確傳 null 會清除時間、省略則保留。
- [x] AC-3：Given 一個月有含時間與不含時間的跑步，When 讀取月份摘要或單雙鞋分析，Then 平均配速為總時間 ÷ 有時間的距離，排除其他帳號。
- [x] AC-4：Given 真實欄位排列的 Strava CSV（重複的「經過時間」「距離」），When 解析，Then 使用移動時間、缺漏時退回經過時間；時間不可用時活動照常匯入但沒有時間。
- [x] AC-5：Given 既有 Strava 跑步沒有時間，When 重新預覽並匯入同一份 CSV，Then 只補上缺少且合理的時間、遞增版本，不覆寫既有時間，也不影響其他帳號。
- [x] AC-6：Given 含時間的帳號，When 匯出備份、合併匯入、刪除再復原，Then v4 保留時間；v3 帶時間被拒絕；備份沒有時間不會清除既有時間。
- [x] AC-7：Given schema 9 資料庫，When 執行回滾腳本並再次升級，Then 守衛防止重複執行，時間資料保留。
- [x] AC-8：Given 使用者在表單輸入時間，When 輸入或送出，Then 支援 `m:ss`、`h:mm:ss` 與整數分鐘，即時顯示配速，格式錯誤時顯示提示且不送出；編輯清空欄位會傳送 null。
- [x] AC-9：Given 跑步資料含時間，When 顯示跑步列表、月份卡片、單雙鞋分析與 Strava 預覽，Then 顯示後端算好的配速與補時間筆數，只補時間的匯入仍可執行。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_run_pace.py::test_manual_run_records_duration_and_returns_pace` |
| AC-2 | `unit_tests/test_run_pace.py::test_manual_run_rejects_invalid_or_implausible_duration`、`unit_tests/test_run_pace.py::test_run_update_sets_keeps_and_clears_duration`、`unit_tests/test_run_pace.py::test_pace_is_derived_and_plausibility_bounds_typos` |
| AC-3 | `unit_tests/test_run_pace.py::test_month_summary_and_shoe_analytics_average_pace_is_time_weighted` |
| AC-4 | `unit_tests/test_run_pace.py::test_strava_csv_uses_moving_time_and_never_rejects_a_run_for_its_time` |
| AC-5 | `unit_tests/test_run_pace.py::test_strava_reimport_backfills_missing_times_without_overwriting`、`unit_tests/test_run_pace.py::test_duration_backfills_only_fill_missing_plausible_times` |
| AC-6 | `unit_tests/test_run_pace.py::test_backup_v4_round_trips_duration_and_merges_never_clear_it`、`unit_tests/test_run_pace.py::test_history_recovery_restores_the_moving_time` |
| AC-7 | `unit_tests/test_run_pace.py::test_schema_nine_rollback_keeps_times_and_reupgrades` |
| AC-8 | `unit_tests/frontend/run-pace.test.cjs::SPEC-060 run duration accepts m:ss, h:mm:ss and whole minutes and rejects other text`、`unit_tests/frontend/run-pace.test.cjs::SPEC-060 the pace hint follows the form and flags an implausible pace`、`unit_tests/frontend/run-pace.test.cjs::SPEC-060 adding a run sends the moving time and clears it after saving`、`unit_tests/frontend/run-pace.test.cjs::SPEC-060 editing a run shows the stored time and an emptied field clears it`、`unit_tests/test_run_pace.py::test_frontend_pace_bounds_mirror_the_backend` |
| AC-9 | `unit_tests/frontend/run-pace.test.cjs::SPEC-060 the run table, month card and shoe analysis show backend paces`、`unit_tests/frontend/run-pace.test.cjs::SPEC-060 a Strava re-import that only fills moving times can still be imported` |
