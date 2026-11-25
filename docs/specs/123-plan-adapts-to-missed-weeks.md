# SPEC-123：課表依實際執行調整之後的週

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-119](119-race-training-plan.md)、[SPEC-122](122-plan-long-run-floor-and-options.md)

## Problem

- 課表開始後基準固定（SPEC-119），之後每週照原本的規則加 10%。生病、受傷或出差停了兩三週，回來那週課表還是要求停跑前的量再往上加，容易受傷，跑者也只能自己猜要跑多少。

## Goals

- 累積期的週，前兩週實際跑量明顯不足時，從實際跑量重新累積，減量週與比賽週跟著調整。
- 已開始的週目標不變，課表仍是資料的確定函數。
- 課表標示哪一週被調降，說明原因。

## Non-goals

- 不因為跑得比建議多而往上加量（安全優先）。
- 不調整減量週與比賽週的規則本身，也不改基準的計算。

## Proposed design

- `read_models/race_plan.build_plan` 先算出每週的實際跑量與最長一次，已結束的週（週日早於今天）交給 `_planned_weeks`。
- `_planned_weeks` 在每個累積週（含恢復週）的週一判斷：前兩週合計實際跑量不到兩週建議合計的 60%（同「部分完成」門檻）時，週跑量改為前兩週平均（至少 15 km、不高於原本），最長一次改為前兩週最長（至少 5 km、不超過週跑量一半、不高於原本），這週不再加 10%，下一週起照常成長。調降後的兩週都依新目標評估，所以同一段缺跑只調降一次。
- 判斷只用那一週開始前已結束的週，所以已開始的週不會再變；尚未開始的週以「之後照計畫執行」推算。
- 每週新增 `adjusted`；前端在階段後面標「已調降」，說明文字指出從第幾週起重新累積。AI 工具補上欄位說明。

## Security and data isolation

- 只讀目前使用者自己的跑步紀錄，沿用既有的 user-scoped 查詢，不新增查詢。

## Migration, rollout, and rollback

- Schema／資料 migration：無；`plan.weeks` 新增 `adjusted`。
- 上線與 smoke test：有缺跑的課表在之後的週顯示「已調降」，減量週低於原本。
- 回滾方式與資料相容性：直接回滾 v5.0.3 image。

## Acceptance criteria

- [x] AC-1：Given 前兩週實際跑量不到建議的 6 成，When 到了下一個累積週，Then 這週從實際跑量重新累積並標示調降，減量與比賽週跟著降低。
- [x] AC-2：Given 跑者照調降後的目標跑完，When 之後取得課表，Then 不會再次調降，已開始的週目標與當時相同。
- [x] AC-3：Given 有調降的週，When 顯示課表，Then 該週階段標示「已調降」，說明文字指出從第幾週起重新累積。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_race_plan.py::test_weeks_ahead_restart_from_what_was_run_after_a_shortfall`、`unit_tests/test_race_plan.py::test_started_weeks_compare_actual_distance_and_past_weeks_never_move` |
| AC-2 | `unit_tests/test_race_plan.py::test_weeks_ahead_restart_from_what_was_run_after_a_shortfall` |
| AC-3 | `unit_tests/frontend/pace-analysis.test.cjs::SPEC-119 the weekly plan lays out backend targets, actual distance and status` |
