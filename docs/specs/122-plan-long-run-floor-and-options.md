# SPEC-122：課表不砍長跑，並說明怎樣排得到足夠的長距離

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-119](119-race-training-plan.md)、[SPEC-120](120-plan-weeks-and-indexeddb-retry.md)、[SPEC-121](121-plan-zone-counts-and-taper.md)

## Problem

- 長跑每週成長的上限是該距離的預設高峰（10K 14 km、半馬 19 km）。本來每週跑 40 km、週日長跑 20 km 的人排 10K 課表，第一週長跑 20 km，第二週起就被降到 14 km，課表等於要求有底子的人退步。
- 課表的最長一次不到比賽距離 75% 時，提示「放寬目標時間或選較晚的比賽」。但目標時間根本不影響跑量；比較晚的比賽也只有在平常跑量跟著提高時才有幫助。跑者不知道到底要改什麼。

## Goals

- 起點的長跑已經超過該距離的預設高峰時，課表維持這個長跑，不往下砍。
- 最長一次不足時，後端算出「課表拉長到幾週」或「平常週跑量提高到多少」就排得到，前端與 AI 教練依此提示。

## Non-goals

- 不改變週跑量的成長規則（每週最多 10%、最多比起點多 50%）與長跑占週跑量最多一半的上限。
- 不自動改變使用者選的課表週數。

## Proposed design

- `read_models/race_plan._planned_weeks` 的長跑上限改為「距離預設高峰」與「起點長跑」取大者。
- `build_plan` 在 `long_below_threshold` 時，以同一個 `_planned_weeks` 搜尋：
  - `long_weeks_needed`：比目前長、且仍從本週以後開始（不超過 `weeks_until_race` 與 24 週）的最短課表週數；沒有則為 null。已開始的課表不能再往前延，所以一定是 null。
  - `long_base_needed_km`：維持目前週數，平常週跑量（整數 km，最多 150）提高到多少就排得到；長跑依跑者自己起點的長跑占比放大。課表已開始時基準固定，為 null。
- 前端課表說明改為「把課表拉長到 N 週（按「調整比賽」），或先把平常週跑量提高到約 B km，就排得到」；兩者都沒有時建議選較晚的比賽或較短的距離。AI 工具補上兩個欄位的說明。

## Security and data isolation

- 只用目前使用者自己的比賽目標與跑步紀錄，沿用既有的 user-scoped 查詢；搜尋是純計算，不多讀資料。

## Migration, rollout, and rollback

- Schema／資料 migration：無；`plan` 新增兩個可為 null 的欄位。
- 上線與 smoke test：長跑超過預設高峰的跑者，課表的最長一次不再下降；跑量不足的全馬課表顯示需要的週數或週跑量。
- 回滾方式與資料相容性：直接回滾 v5.0.2 image。

## Acceptance criteria

- [x] AC-1：Given 起點長跑 20 km、排 10K 課表，When 取得課表，Then 每個累積週的最長一次都是 20 km，不會降到 14 km。
- [x] AC-2：Given 最長一次不足的課表，When 取得課表，Then 回傳排得到的最短週數與最低週跑量；已開始的課表兩者都是 null。
- [x] AC-3：Given 這些欄位，When 顯示課表說明，Then 列出拉長週數或提高週跑量的建議，都沒有時建議較晚的比賽或較短的距離。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_race_plan.py::test_an_experienced_runner_keeps_a_long_run_above_the_distance_peak` |
| AC-2 | `unit_tests/test_race_plan.py::test_a_short_long_run_says_which_plan_length_or_base_reaches_it` |
| AC-3 | `unit_tests/frontend/pace-analysis.test.cjs::SPEC-119 the weekly plan lays out backend targets, actual distance and status` |
