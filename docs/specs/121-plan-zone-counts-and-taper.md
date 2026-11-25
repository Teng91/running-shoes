# SPEC-121：課表的每週強度次數與減量修正

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-119](119-race-training-plan.md)、[SPEC-120](120-plan-weeks-and-indexeddb-retry.md)

## Problem

- 課表的「比賽配速段」只顯示一個數字（例如 6），看不出是公里、次數還是分鐘，也無法對照自己實際跑了什麼強度。
- 週數較短的課表，減量週反而比高峰週多：4 週半馬課表從每週 33 km 起算，高峰週 36 km，減量週卻是 37 km。減量與比賽週是用理論上限（起點 × 1.5）計算，而短課表根本加不到那個量。

## Goals

- 每週改列實際跑步落在各強度區間的次數（輕鬆、穩定、比賽配速、更快），區間與下方「強度分布」圖相同。
- 減量週與比賽週改以課表實際排到的最高週跑量計算，減量週永遠低於高峰週。

## Non-goals

- 不排每週建議的強度次數或課表內容。
- 不改變強度區間的定義。

## Proposed design

- `read_models/race_plan.build_plan` 每週新增 `zone_runs`：該週（到今天為止）有填時間的路跑，依目標配速以 `race_readiness.zone_for` 分到四個區間的次數；越野跑仍算進跑量但不算強度（同 SPEC-096）。移除 `race_pace_km`。
- `_planned_weeks` 的減量週為「最後的累積週跑量 × 減量比例」，比賽週為「最後的累積週跑量 × 30% + 比賽距離」。
- 前端課表的「比賽配速段」欄改成「強度（次）」，放在實際跑量後面，以強度分布圖的顏色標示，次數為 0 的區間不顯示，尚未開始或沒有計時的週顯示「—」。AI 工具的欄位說明同步改為 `zone_runs`。

## Security and data isolation

- 只讀目前使用者自己的跑步紀錄，沿用既有的 user-scoped 查詢。

## Migration, rollout, and rollback

- Schema／資料 migration：無；API 移除 `race_pace_km`、新增 `zone_runs`，只有本專案前端與 AI 工具使用。
- 上線與 smoke test：課表的強度欄顯示「輕鬆 2、穩定 1」這類次數，減量週低於高峰週。
- 回滾方式與資料相容性：直接回滾 v5.0.1 image。

## Acceptance criteria

- [x] AC-1：Given 一份 4 週的課表，When 排出減量週，Then 減量週低於高峰週，比賽週以實際高峰計算。
- [x] AC-2：Given 已開始的週有計時的路跑，When 取得課表，Then 每週列出各強度區間的次數，越野跑與今天之後的紀錄不計入。
- [x] AC-3：Given 課表資料，When 顯示課表，Then 強度欄以區間名稱與次數呈現、略過 0 次，未開始或沒有計時的週顯示「—」。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_race_plan.py::test_a_short_plan_never_tapers_above_its_own_peak_and_counts_zones` |
| AC-2 | `unit_tests/test_race_plan.py::test_a_short_plan_never_tapers_above_its_own_peak_and_counts_zones`、`unit_tests/test_race_plan.py::test_race_analytics_include_a_user_scoped_plan_that_ignores_hikes` |
| AC-3 | `unit_tests/frontend/pace-analysis.test.cjs::SPEC-119 the weekly plan lays out backend targets, actual distance and status` |
