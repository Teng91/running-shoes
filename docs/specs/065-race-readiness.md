# SPEC-065：比賽準備（目標賽事、預估成績、強度分布與長距離）

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-064](064-pace-analytics.md)、[SPEC-056](056-weekly-goal-long-run-and-weekday-analysis.md)

## Problem

- SPEC-064 的配速圖大多只是在描述資料：每筆跑步只有總距離與總時間，沒有心率、分段或課表類型，平均配速同時受體能與課表組合影響，月份、累積跑量、距離區間與配速分布都無法告訴跑者下一步該怎麼練。
- 備賽真正需要的是一個參考點：目標賽事與目標時間。有了目標配速，才能判斷強度分配、長距離是否足夠，並用近期比賽成績預估完賽時間。
- 使用者的實際情況：12/6 半馬目標破二、最近一場 10.3 km 比賽 54:21（29°C）。近 8 週達到半馬 75% 的長距離只有 1 次，且有 54% 的時間跑在比賽配速附近。

## Goals

- 每個帳號可以設定一個目標賽事：日期、距離、目標時間，以及選填的參考成績（距離、時間、氣溫）。
- 依參考成績以 Riegel 公式（`T2 = T1 × (D2/D1)^1.06`）預估完賽時間，並標示氣溫 25°C 以上的參考成績偏保守。
- 以目標配速為基準把每次跑步分成輕鬆、穩定、比賽配速、更快四個強度，顯示近 8 週的時間占比。
- 以比賽距離的 75% 為長距離門檻，檢查近 8 週的次數（建議至少 2 次）、最長一次占比、近 12 週每週最長一次，以及最後一次長距離的建議日期（賽前 14 天）。
- 配速趨勢依強度上色並畫出目標配速；移除月跑量與配速、累積跑量與配速、距離與配速、配速分布；保留星期幾跑量與配速。

## Non-goals

- 不推算心率區間、乳酸閾值或 VDOT 訓練表；只有平均配速，強度分類以整次跑步為單位。
- 不自動判斷哪一筆跑步是比賽；參考成績由使用者填寫。
- 比賽目標不納入 JSON 帳號備份（v4 格式不變），也不寫入異動歷史；刪除後需重新填寫。
- AI 教練暫不讀取比賽目標。

## Proposed design

- **資料模型（schema 10）**：新增 `race_goals`，每個帳號一筆（`user_id` 唯一）：`version`、`race_name`、`race_date`、`distance_km`、`target_seconds`、`reference_distance_km`、`reference_seconds`、`reference_temperature_c`。`migrations._migrate_schema_ten` 只建立資料表；回滾腳本 `scripts/rollback_schema_ten.sql` 只把版本標記改回 9 並保留資料表。
- **API**：`GET/PUT/DELETE /api/race-goal`（`routers/race_goal.py`，寫入在 `services/race_goals.py`，以 `version` 做樂觀鎖），`GET /api/analytics/race` 回傳準備度。
- **`read_models/race_readiness.py`**：目標配速、Riegel 預估與差距、強度分區（相對目標配速：輕鬆慢 45 秒以上、穩定慢 15–45 秒、比賽配速快 10 秒到慢 15 秒、更快）、近 8 週強度時間占比、長距離統計與近 12 週每週最長一次。所有平均都是時間加權。
- **`read_models/pace.py`**：只保留配速趨勢；有比賽目標時每筆跑步帶 `zone`，並回傳目標配速與分區。
- **前端**：「訓練分析」的「配速分析」改為「比賽準備」：比賽設定表單、四張摘要卡（倒數、目標配速、預估完賽、長距離準備）、長距離準備圖（含門檻與比賽距離虛線）、強度分布圖與依強度上色的配速趨勢。建議文字依後端數字產生：長距離不足時提示在最後期限前補一次輕鬆長距離，進入賽前兩週則改為減量。

## Security and data isolation

- 比賽目標與準備度的每個查詢與寫入都限定 `user_id`；測試以兩個帳號驗證互不影響。
- 不涉及 secret 或外部服務。

## Migration, rollout, and rollback

- Schema／資料 migration：schema 9 → 10，只新增 `race_goals` 資料表，不改既有資料。
- 上線與 smoke test：`/health/ready` 回傳 schema 10；在「訓練分析」設定比賽後出現摘要卡與三張圖。
- 回滾方式與資料相容性：停止寫入並確認 schema 10 備份後，以 Python `sqlite3.Connection.executescript` 執行 `scripts/rollback_schema_ten.sql`（守衛確認目前是 10），再部署 v4.17.1 image；`race_goals` 保留，再次升級後沿用。

## Acceptance criteria

- [x] AC-1：Given 一個帳號，When 儲存、更新或刪除比賽目標，Then 以版本防止覆寫、不合理的日期／時間／參考成績被拒絕，另一個帳號看不到也改不到。
- [x] AC-2：Given 參考成績與目標，When 計算準備度，Then 回傳 Riegel 預估、與目標的差距、炎熱參考成績標記、目標配速與四個強度區間。
- [x] AC-3：Given 近 8 週有時間與沒有時間的跑步，When 計算強度與長距離，Then 時間占比只用有時間的跑步、長距離次數與門檻依比賽距離計算、未來與另一個帳號的跑步不列入、兩次以上才算足夠。
- [x] AC-4：Given 準備度資料，When 顯示「比賽準備」，Then 摘要卡、長距離圖、強度圖與配速趨勢只使用後端數字，長距離不足時提示補跑期限，賽前兩週改為減量；沒有比賽目標時只畫配速趨勢並提示設定。
- [x] AC-5：Given 比賽設定表單，When 送出，Then 時間以 `h:mm:ss`／`m:ss` 解析，缺日期、格式錯誤或參考成績不完整時不呼叫 API。
- [x] AC-6：Given schema 10 的資料庫，When 執行回滾腳本並重新升級，Then 版本回到 9 再回到 10，比賽目標保留，重複執行回滾會被守衛擋下。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_race_readiness.py::test_race_goal_is_saved_versioned_validated_and_user_scoped` |
| AC-2 | `unit_tests/test_race_readiness.py::test_prediction_and_zones_follow_the_goal_race_pace`、`unit_tests/test_race_readiness.py::test_readiness_reports_prediction_intensity_and_long_runs` |
| AC-3 | `unit_tests/test_race_readiness.py::test_readiness_reports_prediction_intensity_and_long_runs`、`unit_tests/test_race_readiness.py::test_a_second_long_run_makes_the_build_enough`、`unit_tests/test_pace_analysis.py::test_pace_trend_points_carry_their_zone_once_a_race_goal_exists` |
| AC-4 | `unit_tests/frontend/pace-analysis.test.cjs::SPEC-065 race prep shows the backend prediction, long-run gap and intensity mix`、`unit_tests/frontend/pace-analysis.test.cjs::SPEC-065 inside the last two weeks the advice is to taper, not to add a long run`、`unit_tests/frontend/pace-analysis.test.cjs::SPEC-065 without a race goal only the pace trend is drawn and the form invites one` |
| AC-5 | `unit_tests/frontend/pace-analysis.test.cjs::SPEC-065 the race form validates its fields and saves the parsed goal` |
| AC-6 | `unit_tests/test_race_readiness.py::test_schema_ten_rollback_keeps_the_race_goal_and_reupgrades` |
