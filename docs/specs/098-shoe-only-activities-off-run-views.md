# SPEC-098：健行與步行不出現在跑步畫面

- 狀態：Implemented（v4.29.1）
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-096](096-activity-types.md)、[SPEC-097](097-strava-walk-hike-opt-in.md)

## Problem

- SPEC-096 讓健行（以及 SPEC-097 的步行）只計入鞋子里程，跑量、目標、熱力圖與配速都已排除；但跑步日誌的月曆、月份的鞋款里程分布圓環圖與「主力鞋」仍來自包含所有活動的 `GET /api/runs/summary`，所以健行會出現在「跑步」月曆上，也會讓主力鞋變成健行鞋。
- 摘要回來之前，前端以已載入的紀錄計算月曆與卡片，同樣沒有排除。
- 跑鞋頁「每雙鞋的距離分布」把健行與步行當成跑步距離。

## Goals

- 跑步日誌的月曆、月份鞋款分布、主力鞋、總里程／次數／天數只算路跑與越野跑（伺服器摘要與前端的暫時計算一致）。
- 「每雙鞋的距離分布」只算路跑與越野跑。
- 健行與步行仍留在跑步紀錄列表（標示類型），才能編輯或刪除；按月曆某天篩選列表時，同一天的健行／步行也會列出。
- 單鞋分析的「最近使用」列出這雙鞋的所有活動並標示類型（健行同樣磨耗鞋子），平均配速仍只看路跑。

## Non-goals

- 不另外做健行／步行專用的月曆或統計頁。
- 穿著次數、鞋子里程、退役預估、輪替時間軸日期與選鞋建議照舊計入所有活動。

## Proposed design

- `read_models/runs.month_run_summary` 以 `run_statistics.TRAINING_RUN` 過濾後再彙總月曆、鞋款分布與總數；`list_runs` 不變。
- `read_models/highlights.shoe_distance_mix` 加上 `TRAINING_RUN`。
- `read_models/shoe_statistics` 的最近 12 筆多回傳 `activity_type`。
- 前端 `renderRunLog` 在摘要尚未回來時以 `RUN_TRAINING_ACTIVITY_TYPES` 篩選已載入的紀錄計算卡片、月曆與鞋款分布；列表仍用全部紀錄。單鞋分析的標題改為「最近使用」並標示類型。

## Security and data isolation

- 只在既有的 `user_id` 條件上多加類型過濾，不改變隔離範圍。

## Migration, rollout, and rollback

- Schema／資料 migration：無（schema 13 不變）。
- 上線與 smoke test：`release-check`；在正式站新增一筆健行，確認月曆與主力鞋不變、列表有標示。
- 回滾方式與資料相容性：可直接回滾至 v4.29.0 image，資料不受影響。

## Acceptance criteria

- [x] AC-1：Given 同月有路跑與健行，When 讀取月份摘要，Then 月曆、鞋款分布與總數只有路跑；When 讀取紀錄列表，Then 健行仍在且標示類型。
- [x] AC-2：Given 一雙鞋有路跑、越野跑、健行與步行，When 讀取距離分布，Then 只算路跑與越野跑；When 讀取單鞋最近使用，Then 四筆都列出並帶類型。
- [x] AC-3：Given 摘要尚未載入，When 跑步日誌以已載入紀錄繪製，Then 月曆、卡片與鞋款分布只算跑步，列表仍列出健行與步行。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_runs_api.py::test_hike_counts_toward_shoe_but_not_monthly_mileage` |
| AC-2 | `unit_tests/test_run_pace.py::test_shoe_views_keep_hikes_and_walks_out_of_running_distances` |
| AC-3 | `unit_tests/frontend/run-pace.test.cjs::SPEC-098 hikes and walks stay listed but off the run calendar and month cards` |
