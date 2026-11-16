# SPEC-056：週目標、每週最長一次與星期幾分析

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-038](038-training-trends-and-shoe-rotation.md)、[SPEC-044](044-annual-goal-overview.md)

## Problem

- 目標只有每月與年度兩級。跑者每週安排訓練，卻看不到「這週該跑多少、已跑多少」，只能自己把月目標換算成週。
- 準備半馬、全馬時最重要的指標之一是長距離（每週最長一次）的進展，但訓練趨勢只有每週總量。
- 使用者想知道自己習慣哪幾天跑、哪幾天從不跑，目前要自己翻月曆。
- 這些都能從現有的日期與距離算出，不需要新資料。

## Goals

- 每週目標與年度目標線同一斜率：年度目標 × 7 ÷ 全年天數，由後端計算；每週標示是否達標。
- 近 16 週每週回傳最長一次的距離。
- 回傳所選年份每個星期幾的總里程與跑步天數。
- 月跑量分頁的訓練趨勢顯示：每週跑量圖的週目標虛線與達標說明、「每週最長一次」折線圖、「星期幾跑量」長條圖。

## Non-goals

- 不新增可自訂的週目標欄位，不改 `running_goals` schema；週目標永遠由每月目標推導。
- 不分析配速、心率或爬升（目前只記錄日期、距離與鞋款）。
- 星期幾分布只看所選年份，不跨年累積。

## Proposed design

- **`read_models/trends.py`**
  - 每日查詢同時取 `SUM(km)` 與 `MAX(km)`，仍是一個依日期分組的 query。
  - `_weekly()` 每週加上 `longest_km`，以及目標啟用時的 `goal_met`（`km + 0.005 >= weekly_goal`）。
  - `_weekday_mix()` 依週一到週日加總該年 1/1 到 `end` 的里程與有跑步的天數。
  - 回應新增 `weekly_goal: {active, km}` 與 `weekday`（7 筆）。未來年份回傳全為 0 的星期分布與空的每週資料。
  - 週目標以 `goals.yearly_goal_to_date(yearly_goal, year, 7)` 計算，和年度目標線共用同一個函式。
- **前端 `app-monthly-charts.js`**
  - 每週跑量圖在目標啟用時加一條「週目標」虛線，說明文字加上「本週 a／b km；已結束的 N 週有 M 週達標」。
  - `renderLongRunChart()` 畫近 16 週的最長一次，說明近 16 週最長與近 4 週平均。
  - `renderWeekdayChart()` 畫週一到週日的里程，tooltip 顯示天數與平均，說明跑最多的星期幾與沒跑過的日子。
  - 兩張圖放在訓練趨勢第二列，沿用 `.charts`／`.chart-box` 版面；月跑量分頁的圖表由 6 張變 8 張。
- 所有數字仍由後端計算，前端只排版（SPEC-038 的原則）。
- **修訂（v4.14.1，使用者回饋）**：
  - 進行中的一週還沒跑長距離時，「近 4 週平均最長一次」把它當 0 km 一起平均，數字偏低，折線也掉到 0。改為只平均已結束的週（「過去 4 週（不含本週）」），本週沒跑步時不畫點，已跑過則照常顯示並在 tooltip 標「本週進行中」。
  - 每週跑量圖的「4 週平均」同樣不為進行中的週畫點，避免線尾下墜。
  - 週目標說明列出計算依據「年度目標 ÷ 52.1 週」。一個月約 4.35 週，若以每月目標 ÷ 4，全年會多出約 8%（125 ÷ 4 × 52 ≈ 1625 km）。
  - 每日查詢多取跑步次數，星期分布回傳 `runs`；說明改為「跑最多的是週六：270.3 km、30 次，平均每次跑 9.0 km」，拿掉沒有資訊量的「每個星期幾都有跑」。

## Security and data isolation

- 只多讀本帳號的跑步日期與距離；每日查詢沿用 `Run.user_id == user_id` 範圍。
- 不新增端點，`GET /api/analytics/trends` 的權限不變。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：
  - 與 SPEC-055 同版（asset 4.13.0／shell v63）。
  - CI 的 40 組版面矩陣檢查新圖表不溢出、不被擠壓、全部初始化。
- 回滾方式與資料相容性：回應只新增欄位；舊前端忽略它們，回滾 image 即可。

## Acceptance criteria

- [x] AC-1：Given 每月目標 100 km 與一週內同日兩跑及一次 21.1 km 長跑，When 讀取訓練趨勢，Then 週目標為 1200 × 7 ÷ 365、該週 `longest_km` 為 21.1 且達標，星期分布只計當年並正確累計天數；目標開始前的年份 `active` 為 false 且沒有達標週；未來年份分布全為 0。
- [x] AC-2：Given 啟用中的週目標，When 畫每週跑量圖，Then 多一條虛線「週目標」，說明顯示本週進度與已結束週的達標數；目標未啟用時維持兩條線與原本說明。
- [x] AC-3：Given 訓練趨勢資料，When 進入月跑量分頁，Then 顯示每週最長一次折線與星期幾長條圖，說明文字與 tooltip 來自後端數字；版面矩陣下圖表全部初始化且不溢出。
- [x] AC-4：Given 未來年份，When 進入月跑量分頁，Then 兩張新圖都不建立，說明顯示「還沒開始」。
- [x] AC-5：Given 進行中的一週，When 畫每週跑量與最長一次，Then 該週沒有 4 週平均點、還沒跑步時沒有 0 km 的長跑點，近期平均只用已結束的週；週目標說明列出「年度目標 ÷ 52.1 週」；星期分布以次數算平均每次距離，每天都有跑時不加多餘說明。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_trends.py::test_weekly_goal_longest_run_and_weekday_mix` |
| AC-2 | `unit_tests/frontend/trends.test.cjs::SPEC-056 the weekly chart draws the weekly goal and counts finished weeks that met it` |
| AC-3 | `unit_tests/frontend/trends.test.cjs::SPEC-056 long-run and weekday charts lay out the backend values`、`python3 scripts/task.py frontend-layout` |
| AC-4 | `unit_tests/frontend/trends.test.cjs::SPEC-056 future years draw no long-run or weekday chart` |
| AC-5 | `unit_tests/frontend/trends.test.cjs::SPEC-056 an unfinished week without a run is not drawn as a 0 km long run`、`unit_tests/frontend/trends.test.cjs::SPEC-056 long-run and weekday charts lay out the backend values`、`unit_tests/frontend/trends.test.cjs::SPEC-056 the weekly chart draws the weekly goal and counts finished weeks that met it`、`unit_tests/test_trends.py::test_weekly_goal_longest_run_and_weekday_mix` |
