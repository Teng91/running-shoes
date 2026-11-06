# SPEC-038：訓練趨勢與跑鞋輪替視覺化

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-017](017-consistent-statistics-and-feature-lifecycles.md)、[SPEC-019](019-reliable-requests-and-release-gates.md)

## Problem

月跑量分頁只有月與年層級的圖表，看不出每週負荷變化、每天是否持續在跑，也無法一眼判斷年度目標目前超前或落後。
跑鞋分頁只顯示預估退役日期，看不出各雙鞋實際使用的期間、哪些鞋同時在輪替，以及哪雙現役鞋已經很久沒穿。
跑步紀錄只保存日期、公里數與鞋款，因此本規格只使用這些既有資料。

## Goals

- 年度跑步熱力圖：每天一格（週一起始），依當天合計公里分五級，並顯示有跑天數、最長連續與目前連續天數。
- 近 16 週每週跑量與 4 週移動平均；當週比前 4 週平均多 30% 以上（且前 4 週平均至少 5 km）時標示為跑量暴增。
- 年度累計跑量與目標進度線：顯示超前／落後公里數與全年推估。
- 跑鞋輪替時間軸：每雙鞋從第一次到最後一次跑步的期間；現役鞋超過 30 天沒穿時標示提醒。

## Non-goals

- 不新增配速、時間或心率欄位，也不改資料庫 schema。
- 月跑量的手動／歷史調整只有月份層級，不分配到熱力圖或每週跑量；年度累計與既有目標進度一致，只計入跑步日誌。
- 不提供可調整的暴增門檻或閒置天數設定。

## Proposed design

- `backend/read_models/trends.py`：`training_trends(db, user_id, year, as_of)` 以一次 `GROUP BY date` 讀取年度與每週視窗內的每日合計，計算熱力圖資料、連續天數、每週跑量、4 週平均、暴增旗標，以及每日累計與目標線；`shoe_timeline(db, user_id, as_of)` 以一次聚合查詢取得每雙未刪除鞋的首次／最後跑步日期、公里與次數。
- 計算全部在後端（AGENTS 規則）；前端只排版。目標線使用既有 `goals.goal_values()` 的年度目標，與目標進度卡一致。
- API：`GET /api/analytics/trends?year=YYYY`、`GET /api/analytics/shoe-timeline`，皆需登入。
- 前端：月跑量分頁新增「訓練趨勢」區塊（熱力圖、每週跑量、累計與目標），區塊標題旁有獨立年份選單（選項與其他年度選單相同：有資料的年份、目標開始年與今年，新的一年自動出現）；跑鞋分頁新增「跑鞋輪替時間軸」。資料經 `resourceStore` 快取：跑步異動使趨勢與時間軸失效，目標異動使趨勢失效，跑鞋異動使時間軸失效。
- 窄螢幕上熱力圖可左右捲動，預設捲到最近的週次；沒有新增前端 asset 檔案。

## Security and data isolation

- 兩個查詢都以 `Run.user_id`／`Shoe.user_id` 限制目前使用者；時間軸的 join 同時限制跑步與鞋款屬於同一使用者，已刪除鞋款不列出。
- 不新增寫入、外部請求或秘密；回應只含使用者自己的日期、公里與鞋款 ID，鞋名由前端已載入的使用者鞋款清單對應。

## Migration, rollout, and rollback

- Schema／資料 migration：無；schema 6 不變。
- 上線與 smoke test：Asset 4.1.0／shell v44；部署後執行匿名 `release-check`。
- 回滾方式與資料相容性：只新增唯讀 API 與前端，可直接回滾至 v4.0.3 image。

## Acceptance criteria

- [x] AC-1：Given 同一天有多筆跑步，When 讀取年度趨勢，Then 熱力圖顯示當天合計並以週一起始排列；連續天數在一整天沒跑後歸零；未來日期不著色。
- [x] AC-2：Given 前 4 週平均 20 km，When 某週跑 30 km，Then 該週標示暴增；增加 11% 或前 4 週平均不足 5 km 時不標示；進行中的週次標示為未完成。
- [x] AC-3：Given 年度目標，When 讀取年度趨勢，Then 回傳全年目標線、累計跑量、超前／落後公里與全年推估；未來年份回傳空資料，過去年份涵蓋全年。
- [x] AC-4：Given 現役、退役、已刪除與未穿過的鞋，When 讀取輪替時間軸，Then 只列出有跑步且未刪除的鞋並依首次跑步排序，現役鞋超過 30 天未穿標示閒置。
- [x] AC-5：Given 兩個使用者，When 各自讀取趨勢與時間軸，Then 只看到自己的資料；未登入回 401，年份超出範圍回 422。
- [x] AC-6：Given 前端取得趨勢與時間軸，When 繪製，Then 顯示熱力圖分級、暴增週次顏色、目標進度說明與閒置鞋提醒；格式錯誤的回應不被快取；跑步／跑鞋異動後重新讀取。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_trends.py::test_heatmap_merges_same_day_runs_and_counts_streaks`、`unit_tests/frontend/trends.test.cjs::SPEC-038 trends render a Monday-first heatmap, weekly spikes and the goal pace note` |
| AC-2 | `unit_tests/test_trends.py::test_weekly_load_flags_jump_over_previous_four_week_average` |
| AC-3 | `unit_tests/test_trends.py::test_cumulative_goal_line_and_projection`、`unit_tests/test_trends.py::test_future_year_is_empty_and_past_year_is_complete` |
| AC-4 | `unit_tests/test_trends.py::test_shoe_timeline_orders_rotation_and_flags_idle_active_shoes`、`unit_tests/frontend/trends.test.cjs::SPEC-038 rotation timeline names shoes, greys retired pairs and calls out idle active shoes` |
| AC-5 | `unit_tests/test_trends.py::test_trend_endpoints_are_user_scoped` |
| AC-6 | `unit_tests/frontend/trends.test.cjs::SPEC-038 future years render no charts and malformed trends are not cached`、`unit_tests/frontend/feature-operations.test.cjs::SPEC-038 run changes refresh training trends and the rotation timeline; shoe edits refresh the timeline`、`python3 scripts/task.py frontend-layout` |
