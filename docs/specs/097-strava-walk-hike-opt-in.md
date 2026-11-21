# SPEC-097：步行類型與 Strava 健行／步行選擇匯入

- 狀態：Implemented（v4.29.0）
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-096](096-activity-types.md)、[SPEC-067](067-timeline-shoe-mileage.md)

## Problem

- SPEC-096 之前，Strava 匯入只收跑步，健行與步行一律略過。想讓鞋子里程和 Strava 裝備總里程一致，只能手動把這些里程加在鞋子上（畫面上的「步行與暖身」）。
- SPEC-096 開始匯入 `Hike`／`Walk`。這些活動以前沒匯入過，不算重複，所以重新匯入涵蓋過去的 CSV（預設前 13 個月）時會全部新增，同一段里程會在鞋子上算兩次，壽命提醒因此提早。
- SPEC-096 把 `Walk` 也記成「健行」，通勤或平常走路被標成健行，紀錄看起來不對。

## Goals

- 新增 `walk`（步行）運動類型，和健行一樣只計入鞋子里程；Strava 的 `Walk`／`步行` 記為步行。
- Strava 預覽與匯入預設排除健行與步行，並顯示這段期間有幾筆、幾公里；使用者勾選「也匯入健行與步行」後才納入預覽與匯入。
- 勾選說明直接提醒：如果這些里程已經手動加在鞋子上，勾選會重複計算。
- 匯入結果回報略過的健行／步行筆數。

## Non-goals

- 不自動判斷鞋子上手動加的里程是否已包含某些健行或步行，也不自動扣除。
- 不記住上一次是否勾選；每次打開匯入視窗都預設不勾選。
- 不處理越野賽的比賽準備度（另案）。

## Proposed design

- `run_metrics.ACTIVITY_TYPES` 加入 `walk`；`TRAINING_ACTIVITY_TYPES`／`PACE_ACTIVITY_TYPES` 不變，所以步行和健行一樣只計入鞋子。`schemas.ActivityType` 同步加入；資料庫欄位不變（schema 13）。
- `migrations._migrate_schema_thirteen` 與 `scripts/rollback_schema_thirteen.sql` 改以「不是 road／trail」判斷要移動的里程，涵蓋健行與步行。
- `strava_import.STRAVA_ACTIVITY_TYPES`：`Walk`／`步行` → `walk`。新的 `split_shoe_only(rows, include)` 回傳要處理的列與健行／步行的筆數、公里數。
- `POST /api/runs/import/strava/preview` 與 `POST /api/runs/import/strava` 新增表單欄位 `include_walks_hikes`（布林，預設 `false`），在日期篩選之後套用。預覽多回傳 `walk_hike_count`、`walk_hike_km`、`walk_hike_included`；匯入多回傳 `skipped_walk_hike`。路由清單不變。
- 前端：紀錄表單多一個「步行」選項；Strava 視窗在有健行／步行時顯示勾選框與說明，勾選後重新預覽。預覽鍵（`stravaInputKey`）包含勾選狀態，所以勾選後一定要等新預覽完成才能匯入。

## Security and data isolation

- 只改變 CSV 列是否進入既有的使用者範圍匯入流程；所有查詢與寫入仍限制目前 `user_id`。
- 新欄位由 FastAPI 解析為布林，不合法的值回 422。

## Migration, rollout, and rollback

- Schema／資料 migration：無；`activity_type` 本來就是文字欄位，schema 仍是 13。
- 上線與 smoke test：`release-check`；在正式站開啟 Strava 匯入，確認含健行的 CSV 預設不匯入並顯示筆數。
- 回滾方式與資料相容性：回到 v4.28.0 前要先把步行改成健行（`UPDATE runs SET activity_type = 'hike' WHERE activity_type = 'walk';`），因為 v4.28.0 不認得 `walk`；兩者的統計規則相同，里程不受影響。

## Acceptance criteria

- [x] AC-1：Given 含跑步、健行與步行的 CSV，When 不勾選就預覽與匯入，Then 只匯入跑步，預覽回報健行／步行的筆數與公里數，匯入回報略過筆數，鞋子里程不重複增加。
- [x] AC-2：Given 同一份 CSV，When 勾選後預覽與匯入，Then 健行記為 `hike`、步行記為 `walk`，只增加鞋子里程，月跑量不變；不合法的勾選值回 422。
- [x] AC-3：Given 一筆步行紀錄，When 新增或改成路跑，Then 步行只計入鞋子，改成路跑後才計入月跑量。
- [x] AC-4：Given schema 13 資料庫有步行與健行，When 執行回滾腳本再升級，Then 兩者的里程都先加回月份、再扣除。
- [x] AC-5：Given Strava 視窗，When 預覽有健行／步行，Then 顯示勾選框與重複計算提醒；勾選狀態改變預覽鍵與送出的欄位。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_strava_import.py::test_strava_walks_and_hikes_are_opt_in` |
| AC-2 | `unit_tests/test_strava_import.py::test_strava_walks_and_hikes_are_opt_in`、`unit_tests/test_strava_import.py::test_strava_activity_types_map_to_run_types` |
| AC-3 | `unit_tests/test_runs_api.py::test_walk_counts_only_toward_the_shoe` |
| AC-4 | `unit_tests/test_migrations.py::test_rollback_schema_thirteen_restores_walk_mileage` |
| AC-5 | `unit_tests/frontend/strava-resources.test.cjs::Strava keeps hikes and walks out until the box is ticked` |
