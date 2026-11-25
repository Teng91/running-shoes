# SPEC-119：比賽訓練課表

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-065](065-race-readiness.md)、[SPEC-096](096-activity-types.md)

## Problem

- 比賽準備只告訴使用者「長距離偏少」「輕鬆跑太少」，沒有說接下來每週該跑多少，也無法對照自己有沒有照計畫跑。

## Goals

- 設定目標賽事後，依比賽距離與使用者自己的跑量排出每週課表：建議週跑量、最長一次、比賽配速段。
- 每週對照實際跑量與最長一次，標示達成、部分完成、未達。
- 課表由後端決定，相同資料永遠得到相同課表，已過的週次不會移動；AI 教練只負責解說。

## Non-goals

- 不排每天的課表或間歇內容，也不儲存或讓使用者手動編輯課表。
- 不讓 LLM 產生或修改課表數字。

## Proposed design

- `backend/read_models/race_plan.py` 的 `build_plan` 是純函式：
  - 週數依距離：5K 8 週、10K 10 週、半馬 12 週、全馬 16 週，最後一週是比賽週。
  - 起點是課表開始前 4 週的平均週跑量（課表未開始時用本週前 4 週），最低以 15 km 起算；課表開始後起點固定。
  - 累積週每週最多加 10%，高峰最多比起點多 50%（且不超過距離上限 30／40／50／65 km，起點已較高則維持）；每 4 週一次恢復週（8 成），高峰後減量 1～2 週。
  - 最長一次從起點期間的最長一次開始，每週最多加 10%（至少 1 km）、不超過當週一半，上限 10／14／19／32 km；比賽週的最長一次就是比賽。
  - 從第 3 週起的累積週與減量週排比賽配速段（當週 15%，上限為比賽距離的一半）。
  - 已過的週以路跑與越野跑對照：跑量與最長一次都達 9 成算達成，跑量達 6 成算部分完成，否則未達；本週標為進行中。
  - 課表最長一次仍不到比賽距離 75% 時，回傳 `long_below_threshold` 讓畫面提醒。
- `race_preparation` 把課表加進 race readiness，`GET /api/analytics/race` 回應新增 `plan`（沒有目標或比賽結束後為 null）。
- AI 工具 `race_training_plan` 回傳同一份資料與欄位說明；planner 遇到「比賽、課表、半馬、全馬、馬拉松、備賽、賽前、減量」與個人用語時呼叫它。
- 前端 `app-pace-charts.js` 在比賽準備卡片下方畫課表與說明，只排版後端數字。

## Security and data isolation

- 課表只查詢目前使用者的跑步紀錄；AI 工具與 HTTP 共用同一個 user-scoped read model。

## Migration, rollout, and rollback

- Schema／資料 migration：無；API 只新增欄位。
- 上線與 smoke test：設定目標賽事後，訓練分析分頁的比賽準備出現課表，本週列以底色標示；AI 教練問「我的半馬課表這週要跑多少」會呼叫 `race_training_plan`。
- 回滾方式與資料相容性：直接回滾 v4.29.14 image。

## Acceptance criteria

- [x] AC-1：Given 目標賽事與近期跑量，When 取得比賽準備，Then 課表依距離排出累積、恢復、高峰、減量與比賽週，每週成長不超過 10%、最長一次不超過當週一半。
- [x] AC-2：Given 跑量很少的新手，When 排課表，Then 以 15 km 起算，且課表最長一次不到比賽距離 75% 時標示提醒。
- [x] AC-3：Given 課表已開始，When 之後的日期再取得，Then 已過週次的建議數字不變，並以實際跑量標示達成、部分完成、未達與本週。
- [x] AC-4：Given 比賽已結束或另一個帳號，When 取得比賽準備，Then 沒有課表，且課表只計算自己的路跑與越野跑。
- [x] AC-5：Given 課表資料，When 顯示比賽準備，Then 前端只排版後端數字並在每種寬度正常顯示。
- [x] AC-6：Given 使用者問備賽課表，When AI 教練規劃查詢與呼叫工具，Then 呼叫 `race_training_plan` 並取得與畫面相同的課表。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_race_plan.py::test_plan_builds_from_the_baseline_with_recovery_taper_and_race_week` |
| AC-2 | `unit_tests/test_race_plan.py::test_a_beginner_gets_a_floor_and_a_warning_that_long_runs_stay_short` |
| AC-3 | `unit_tests/test_race_plan.py::test_started_weeks_compare_actual_distance_and_past_weeks_never_move` |
| AC-4 | `unit_tests/test_race_plan.py::test_no_plan_after_the_race`、`unit_tests/test_race_plan.py::test_race_analytics_include_a_user_scoped_plan_that_ignores_hikes` |
| AC-5 | `unit_tests/frontend/pace-analysis.test.cjs::SPEC-119 the weekly plan lays out backend targets, actual distance and status`、`unit_tests/frontend_layout.cjs`（每種寬度載入 12 週課表） |
| AC-6 | `unit_tests/test_race_plan.py::test_race_training_plan_tool_reads_the_same_plan`、`unit_tests/agent_eval_cases.json`（`race-training-plan`） |
