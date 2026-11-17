# SPEC-064：配速分析圖表

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-060](060-run-duration-and-pace.md)、[SPEC-056](056-weekly-goal-long-run-and-weekday-analysis.md)

## Problem

- SPEC-060 之後每筆跑步都可以有時間，但配速只出現在列表、月份卡片與單雙鞋分析，看不出長期變化。
- 使用者想知道跑量和速度的關係；實際資料顯示當月跑量和配速只有弱相關，前幾個月的累積跑量才和配速強相關，這需要圖表與後端算好的結論才看得出來。

## Goals

- 月跑量分頁新增「配速分析」，涵蓋全部紀錄、不隨年份切換：配速趨勢、月跑量與配速、累積跑量與配速、距離與配速、配速分布。
- 所有配速、平均、分組、相關係數與趨勢線係數都由後端計算，前端只排版。

## Non-goals

- 不做心率、坡度或天氣校正，也不推測比賽成績。
- 不提供 AI 工具（之後可以用 adapter 讀同一個 read model）。

## Proposed design

- **`backend/read_models/pace.py`** 的 `pace_analysis(db, user_id, as_of)`，由 `GET /api/analytics/pace` 回傳：
  - `summary`：最早 90 天、最近 90 天、最近 30 天的平均配速。
  - `runs`、`rolling`：每筆有時間的跑步配速，以及每個跑步日往前 30 天的時間加權平均。
  - `monthly`、`monthly_lag`：每月跑量（含沒有時間的跑步）、有時間的距離與平均配速；當月跑量、前 3 個月平均跑量各自和當月配速的相關係數。
  - `load`：每週配速對前 4 週平均週跑量（含沒有時間的跑步）的散點、相關係數、線性趨勢（每 10 km 的秒數）、每 10 km 一組的配速中位數（至少 3 週），以及最低一組和最快一組的比較。
  - `distance`：<5、5–8、8–12、12–16、16–22、22 km 以上的平均配速與最快一次。
  - `distribution`：每 15 秒一格的次數，最快和最慢各 5% 併入兩端，以及中位數。
  - 平均配速一律是時間加權（總秒數 ÷ 有時間的距離）；相關係數至少 8 個點才回傳。
- **`frontend/app-pace-charts.js`** 以 Chart.js 畫 5 張圖，配速軸反向（越上面越快），每張圖下方說明後端給的數字；資源快取 `pace-analysis` 在跑步資料變動時失效。

## Security and data isolation

- 只查詢 `runs.user_id == user_id` 且日期不晚於今天的跑步；另一個帳號的資料不影響結果。
- 唯讀，不涉及 secret 或外部服務。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：月跑量分頁出現配速分析 5 張圖；沒有時間的帳號顯示提示而不是空圖。
- 回滾方式與資料相容性：可直接回滾到 v4.16.1 image。

## Acceptance criteria

- [x] AC-1：Given 有時間與沒有時間的跑步，When 讀取配速分析，Then 平均配速以時間加權計算、跑量包含沒有時間的跑步，趨勢、月份、距離與分布的數字正確，另一個帳號與未來日期的跑步不列入。
- [x] AC-2：Given 至少 8 週可比較的資料，When 計算累積跑量與配速，Then 回傳前 4 週平均週跑量、相關係數、趨勢線、各組中位數與最低一組和最快一組的差距；資料不足時不回傳相關係數。
- [x] AC-3：Given 沒有任何跑步時間，When 讀取或顯示配速分析，Then API 回傳空結構，畫面顯示提示而不畫圖。
- [x] AC-4：Given 配速分析資料，When 顯示月跑量分頁，Then 畫出 5 張圖，配速軸反向，說明文字只使用後端的數字。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_pace_analysis.py::test_pace_analysis_is_time_weighted_user_scoped_and_ignores_the_future` |
| AC-2 | `unit_tests/test_pace_analysis.py::test_training_load_relates_prior_weeks_to_pace` |
| AC-3 | `unit_tests/test_pace_analysis.py::test_pace_analysis_without_times_is_empty`、`unit_tests/frontend/pace-analysis.test.cjs::SPEC-064 an account without times shows a hint instead of charts` |
| AC-4 | `unit_tests/frontend/pace-analysis.test.cjs::SPEC-064 pace charts render backend values with reversed pace axes` |
