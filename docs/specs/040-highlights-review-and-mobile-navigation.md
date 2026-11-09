# SPEC-040：年度回顧、跑步首頁摘要與手機導覽

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-015](015-run-log-home.md)、[SPEC-038](038-training-trends-and-shoe-rotation.md)、[SPEC-039](039-compact-monthly-records.md)

## Problem

使用者想在年底回顧一整年的跑步，並在每次記錄跑步時就看到本週進度、連續天數、目標與里程碑；選鞋時也需要提醒哪雙現役鞋休息最久。
月跑量分頁有三個獨立的年份選單（訓練趨勢、年度月跑量、跑鞋堆疊圖），切換其中一個時其他區塊不跟著變，造成困惑。
同一雙鞋在不同圖表的顏色不同；手機版必須先展開選單才能切換分頁。

## Goals

- 年度回顧：總跑量（與前一年比較、年度目標達成率）、跑步次數與天數、平均距離、最長連續天數、最長一次、最多的一週與月份、最常穿的鞋、買鞋數量、花費與每 km 成本。
- 今天穿哪雙：依休息天數排序現役鞋，快到退役里程（≥90%）的鞋排在最後；一鍵選入新增跑步表單。
- 里程碑與個人紀錄：累計跑量里程碑（100／250／500／1000 km，之後每 1000 km）、現役鞋突破 100／300／500／800 km、近 30 天的新最長距離與單週新高。
- 每雙現役鞋的距離分布（<5、5–10、10–15、15–21、≥21 km）。
- 年度月跑量對比：每年一條線，選定年份加粗。
- 月跑量分頁只保留一個年份選單，所有年度區塊一起切換。
- 跑步日誌頂端摘要：本週跑量、連續天數、本月目標進度環、累計跑量與下一個里程碑。
- 同一雙鞋在所有圖表與表格使用相同顏色。
- 手機版改為固定底部分頁列，標題列選單只保留帳號操作。

## Non-goals

- 不新增資料欄位或 schema；不提供可調整的里程碑或分桶門檻。
- 年度回顧與里程碑只計入跑步日誌，不含已移除介面的月份手動調整（與目標進度一致）。

## Proposed design

- `backend/read_models/highlights.py`：`home_summary`、`shoe_suggestion`、`year_review`、`shoe_distance_mix`，全部以 `user_id` 篩選，計算在後端；連續天數沿用 `trends.run_streaks`，每雙鞋的剩餘里程沿用 `shoe_metrics`。
- API：`GET /api/analytics/home`、`GET /api/analytics/year-review?year=YYYY`、`GET /api/analytics/shoe-distance-mix`，皆需登入。
- 前端：跑步日誌新增摘要區與選鞋建議（`app-run-insights.js`）；月跑量分頁頂端的單一 `#year-select` 驅動目標卡、年度回顧、訓練趨勢、年度月跑量、跑鞋堆疊圖與年度對比（`app-monthly-charts.js`）；跑鞋分頁新增距離分布（`app-shoe-charts.js`）；`shoeColor()`／`shoeName()` 依鞋款 ID 決定顏色與名稱（`app-dashboard.js`）。
- 資料經 `resourceStore` 快取；跑步、鞋款或目標異動觸發的 `dashboard` 快取掛鉤使三個新資源失效；首頁摘要以當地日期為快取鍵，跨日自動重新讀取。
- 手機版（≤800px）分頁列以 `position: fixed` 固定在底部並保留安全區域，內容底部預留空間；`.tabs` 移出可收合的 `#sidebar-navigation`，選單按鈕改名「帳號」。

## Security and data isolation

- 每個查詢都以 `Run.user_id`／`Shoe.user_id` 限制；距離分布的 join 同時限制鞋款屬於同一使用者。
- 回應只含使用者自己的日期、公里、價格與鞋款 ID；鞋名由前端已載入的清單對應並經過 escape。無新寫入、外部請求或秘密。

## Migration, rollout, and rollback

- Schema／資料 migration：無；schema 6 不變。
- 上線與 smoke test：Asset 4.2.0／shell v48；部署後執行匿名 `release-check`。
- 回滾方式與資料相容性：只新增唯讀 API 與前端，可直接回滾至 v4.1.3 image。

## Acceptance criteria

- [x] AC-1：Given 過去、進行中與未來的年份，When 讀取年度回顧，Then 過去年份涵蓋全年並與前一年比較，進行中年份統計到今天，未來年份回傳無資料；已刪除鞋款不計入買鞋花費。
- [x] AC-2：Given 現役、退役、未穿過與快到退役里程的鞋，When 讀取首頁摘要，Then 建議依休息天數排序、未穿過的鞋優先、快到退役的鞋排最後，退役鞋不列入；按「選這雙」會選入表單並觸發草稿更新。
- [x] AC-3：Given 跑步紀錄，When 讀取首頁摘要，Then 回傳本週跑量、連續天數、本月目標百分比、累計里程碑與個人紀錄，並列出近 30 天內達成的里程碑與新紀錄。
- [x] AC-4：Given 多雙鞋的跑步，When 讀取距離分布，Then 只列現役鞋並依距離分桶計數；兩個使用者只看到自己的資料，未登入回 401，年份超出範圍回 422。
- [x] AC-5：Given 月跑量分頁，When 切換唯一的年份選單，Then 目標、年度回顧、訓練趨勢、年度月跑量、跑鞋堆疊圖與年度對比一起更新；格式錯誤的回應不被快取。
- [x] AC-6：Given 任意順序的鞋款清單，When 繪製圖表與表格，Then 同一雙鞋顏色相同；手機版底部分頁列永遠可見，選單只顯示帳號操作。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_highlights.py::test_year_review_summarizes_a_past_year_and_compares_the_previous_one`、`unit_tests/frontend/highlights.test.cjs::SPEC-040 year review lays out the backend summary for the shared year` |
| AC-2 | `unit_tests/test_highlights.py::test_suggestion_prefers_the_longest_rested_pair_and_demotes_worn_out_shoes`、`unit_tests/frontend/highlights.test.cjs::SPEC-040 run log summary shows week, streak, goal ring, milestones and the next shoe` |
| AC-3 | `unit_tests/test_highlights.py::test_home_summary_reports_week_streak_goal_records_and_recent_achievements`、`unit_tests/test_highlights.py::test_total_milestones_step_through_the_list_then_every_thousand_km` |
| AC-4 | `unit_tests/test_highlights.py::test_distance_mix_buckets_runs_for_active_shoes_only`、`unit_tests/test_highlights.py::test_highlight_endpoints_are_user_scoped`、`unit_tests/frontend/highlights.test.cjs::SPEC-040 distance mix stacks bucket counts per active shoe and names the long-run pair` |
| AC-5 | `unit_tests/frontend/highlights.test.cjs::SPEC-040 the shared year selector redraws every year view and the comparison chart`、`unit_tests/frontend/highlights.test.cjs::SPEC-040 year review explains ongoing, empty and future years and rejects malformed data` |
| AC-6 | `unit_tests/frontend/highlights.test.cjs::SPEC-040 shoes keep one color in every chart regardless of list order`、`unit_tests/frontend/highlights.test.cjs::SPEC-040 phones use a fixed bottom tab bar while the header menu keeps account actions`、`python3 scripts/task.py frontend-layout` |
