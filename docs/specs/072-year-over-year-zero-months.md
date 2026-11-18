# SPEC-072：過去年份的圖表看得到全年

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-040](040-highlights-review-and-mobile-navigation.md)、[SPEC-055](055-correctness-fixes-and-strava-deletions.md)

## Problem

- 年度月跑量對比把沒有月跑量資料的月份當成空白，線會斷開。Strava 紀錄從 2024 年 9 月開始，2024 年的線只從 9 月畫起，看起來像資料遺失。
- 每週跑量與每週最長一次固定顯示選定年份的最後 16 週，過去的年份只看得到 9～12 月，無法回頭看 1～8 月。
- 過去年份的最後一週被 12/31 截斷，說明文字仍寫「本週 0.0 km」。

## Goals

- 已經開始的月份沒有資料時畫 0：過去的年份 12 個月都畫，今年畫到本月。
- 還沒開始的月份（今年之後的月份、未來的年份）仍留白，不把未來畫成 0。
- 每週圖表可以在選定年份內往前、往後切換 16 週，最早到含 1 月 1 日的那一週。
- 只有今天所在的那一週才叫「本週」；過去年份被截斷的最後一週標示「只算到 12/31」。

## Non-goals

- 不改月跑量資料、年度總跑量、暴增判斷或週目標的計算。
- AI 工具的 `training_trends` 仍回傳最近 16 週。
- 不自動建立空白的月份資料。

## Proposed design

- `app-monthly-charts.yearOverYearSeries(months, year, todayISO)`：依 `localDateISO()` 判斷每年已開始的月數，沒有資料的已開始月份補 0，其餘為 `null`。`renderYearOverYearChart` 的每條線都經過它。
- `GET /api/analytics/trends` 新增選填的 `weeks_end`（日期）。`trends.weekly_window` 把它限制在這一年內（不晚於資料最後一天、不早於含 1/1 那週往後 16 週），回傳 `weekly_window: {end, has_earlier, has_later}`；4 週平均與暴增仍以視窗前 4 週為基準，`partial` 仍以資料最後一天判斷。
- 前端 `weeklyWindowEnd` 為 `null` 時取最近 16 週，換年份時重設；兩張每週圖表的「‹ 較早／較晚 ›」共用同一個視窗，以 `年份|視窗結束日` 為 resource key 快取。只有一個視窗時隱藏切換鈕。

## Security and data isolation

- `weeks_end` 只改變日期範圍，查詢仍限定 `Run.user_id == current_user.id`；格式錯誤回 422。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：選 2024 年，年度月跑量對比的線從 1 月的 0 開始；每週跑量按「‹ 較早」可以看到 1～8 月。
- 回滾方式與資料相容性：可直接回滾到 v4.19.1 image。

## Acceptance criteria

- [x] AC-1：Given 2024 年只有 1、7、9～12 月的資料，When 今天是 2026-11-18，Then 2024 年的線 12 個月都有值，沒有資料的月份為 0。
- [x] AC-2：Given 今年 1 月與 11 月有資料，When 今天是 11 月，Then 2～10 月為 0、12 月留白；未來的年份全部留白。
- [x] AC-3：Given 2024 年與另一個帳號的跑步，When 以 `weeks_end` 讀取 2024 年較早的 16 週，Then 只計自己的跑步、視窗不超出這一年，最早一頁從 2024-01-01 那週開始且沒有更早的頁。
- [x] AC-4：Given 選擇 2024 年，When 按「‹ 較早」，Then 以 `weeks_end` 讀取前 16 週、兩個按鈕依可否切換啟用，說明文字列出區間日期，且不出現「本週」。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/highlights.test.cjs::SPEC-072 the comparison line starts at 0 before the first recorded month instead of breaking` |
| AC-2 | `unit_tests/frontend/highlights.test.cjs::SPEC-040 the shared year selector redraws every year view and the comparison chart` |
| AC-3 | `unit_tests/test_trends.py::test_weekly_window_pages_through_a_past_year_and_stays_inside_it`、`unit_tests/test_trends.py::test_trends_api_accepts_a_weekly_window_end` |
| AC-4 | `unit_tests/frontend/trends.test.cjs::SPEC-072 a past year pages back 16 weeks at a time and never calls its last week "本週"` |
