# SPEC-139：全面檢查修正：讀取模型分層與健行／步行配速上限

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-060](060-run-duration-and-pace.md)、[SPEC-096](096-activity-types.md)、[SPEC-097](097-strava-walk-hike-opt-in.md)

## Problem

- `read_models/strava_preview.py` 從 `services/run_identity.py` 匯入 `deleted_strava_ids`，讀取模型反過來依賴應用服務；其他地方的方向都是 services → read_models。
- `tools/db_tools.py` 的 `_shoe_names` 自己組資料庫查詢，違反「AI 工具只是讀取模型的薄轉接層」。
- 跑步時間的合理配速上限（每公里 60:00）同時套用在健行與步行：陡坡健行每公里超過一小時是真實紀錄，卻被拒絕；Strava 匯入的慢速健行也會丟掉移動時間。
- README 有三段還停在 SPEC-097 之前：說 Strava 匯入只收跑步、鞋子里程的紀錄合計沒有步行、鞋子里程下限只算跑步。

## Goals

- `deleted_strava_ids` 移到唯一的呼叫端 `read_models/strava_preview.py`；鞋名對照移到 `read_models/shoes.shoe_names()`，`db_tools` 不再匯入 `models`。
- `architecture-check` 新增兩條規則：讀取模型（含遞移依賴）不得依賴 `backend.services`；`backend/tools/` 不得呼叫 `.query(...)`。
- 路跑與越野跑維持每公里 1:00–60:00；健行與步行放寬到 1:00–120:00（`MAX_SHOE_ONLY_PACE_SECONDS_PER_KM = 7200`），後端新增、編輯、Strava 匯入與補時間，以及前端即時提示與送出檢查都用同一條規則；錯誤訊息顯示該類型的範圍。
- 修正 README 三段過期描述。

## Non-goals

- 不改變配速統計範圍：健行與步行仍不進入配速趨勢、平均配速與比賽準備（SPEC-096）。
- 不改變 API 路由、schema（14）或備份格式。

## Proposed design

- `backend/run_metrics.py`：`max_pace_seconds_per_km(activity_type)`、`pace_range_text(activity_type)`；`is_plausible_duration(duration, km, activity_type=None)`，未知或未提供的類型以跑步上限檢查。
- `backend/schemas.py`：`RunBase` 依送出的類型檢查；`RunUpdate` 沒有送類型時先用最寬的上限，由 `services/runs._check_effective_pace()` 依「編輯後的距離、時間與類型」檢查，涵蓋只改時間、只改距離與只改類型（把慢速健行改成路跑會被拒絕並提示一併修改或清除時間）。
- `backend/strava_import.py`：解析移動時間、既有紀錄補時間與手動紀錄連結時帶入活動類型。
- `frontend/app-state.js`：鏡像常數 `RUN_SHOE_ONLY_PACE_MAX_SECONDS` 與 `runPaceMaxSeconds`／`runPaceRangeText`／`plausibleRunPace`（和常數放在一起，跨腳本名稱數不變）；`app-runs.js` 的配速提示與送出檢查讀表單的運動類型，切換類型時更新提示。

## Security and data isolation

- 不新增授權或資料邊界；移動的查詢保留原本的 `user_id` 過濾。

## Migration, rollout, and rollback

- Schema／資料 migration：無（schema 14）。
- 上線與 smoke test：`release-check`；新增一筆 4 km、6 小時的健行可儲存，同樣的路跑顯示「每公里 1:00–60:00」。
- 回滾方式與資料相容性：可直接回滾至 v5.3.4 image；回滾後已儲存的慢速健行照常顯示，只是編輯其時間時會再套用 60:00 上限。

## Acceptance criteria

- [x] AC-1：Given 讀取模型與 AI 工具，When 執行 `architecture-check`，Then 讀取模型不依賴 `backend.services`，工具模組沒有 `.query(...)`，違規會被具名回報。
- [x] AC-2：Given 一筆每公里 90:00 的紀錄，When 以健行／步行新增或編輯，Then 儲存成功；以路跑或越野跑新增、或把它改成路跑，Then 回 422／400 並顯示對應的配速範圍。
- [x] AC-3：Given Strava 的慢速健行，When 解析移動時間，Then 依健行上限保留時間；同樣的路跑不保留。
- [x] AC-4：Given 跑步表單，When 選擇健行或步行並輸入慢速時間，Then 即時提示與送出檢查採用 1:00–120:00，路跑採用 1:00–60:00。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_architecture_boundaries.py::test_read_models_never_depend_on_application_services`、`unit_tests/test_architecture_boundaries.py::test_tool_adapters_never_build_queries`、`python3 scripts/task.py architecture-check` |
| AC-2 | `unit_tests/test_run_pace.py::test_hikes_and_walks_accept_a_slower_pace_than_runs` |
| AC-3 | `unit_tests/test_run_pace.py::test_strava_hike_moving_time_uses_the_hike_pace_bound` |
| AC-4 | `unit_tests/frontend/run-pace.test.cjs::SPEC-139 hikes and walks accept a slower pace; running types keep 60:00 per km`、`unit_tests/test_run_pace.py::test_frontend_pace_bounds_mirror_the_backend` |
