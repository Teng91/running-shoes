# SPEC-069：近 90 天沒穿的鞋不預估退役日

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-050](050-recent-shoe-share.md)、[SPEC-055](055-correctness-fixes-and-strava-deletions.md)

## Problem

- 退役預估在近 90 天沒有紀錄時一律改用計畫月跑量（新增鞋款預設 60 km／月）。
- 偶爾才穿的鞋（健行鞋、比賽鞋）近 90 天常是 0 km：例如一雙越野鞋一年只穿 3 次，卻被預估「依計畫月跑量 60 km／月，2027/09/08 退役」，完全不合理。

## Goals

- 穿過但近 90 天沒穿的鞋不給退役日，並說明原因。
- 還沒穿過的新鞋仍用計畫月跑量，讓剛買的鞋有參考日期。

## Non-goals

- 不改計畫月跑量的預設值或輸入方式。
- 不用更長期的平均推算偶爾穿的鞋（使用頻率太不規律，推出來的日期沒有意義）。

## Proposed design

- `forecasting.retirement_forecast(..., has_runs=...)`：未退役、近 90 天 0 km、但有逐筆紀錄 → `forecast_source: "idle_90_days"`、`forecast_retirement_date: null`、`forecast_monthly_km: 0`。
- `forecasts_for_shoes` 用一次查詢同時算近 90 天里程（`CASE`）與到今天為止的紀錄筆數；`analytics._shoe_analytics` 用既有的紀錄筆數。清單、單鞋分析與 AI 工具共用同一結果。
- 前端 `forecastSourceText`：清單提示「近 90 天沒穿，不預估」，單鞋分析顯示「—」與「近 90 天沒穿，偶爾穿的鞋不預估」。
- 只看 90 天，不看 30 天：一個月沒穿的比賽鞋仍有近 90 天的實際月均。

## Security and data isolation

- 沿用使用者範圍的批次查詢（`Run.user_id`），沒有新的寫入或 API。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：近 90 天沒穿的越野鞋預估退役顯示「—」，常穿的鞋仍依近 90 天實際使用。
- 回滾方式與資料相容性：可直接回滾到 v4.18.3 image；舊前端把 `idle_90_days` 顯示成「依計畫月跑量／無法預估」。

## Acceptance criteria

- [x] AC-1：Given 未退役、有逐筆紀錄但近 90 天 0 km 的鞋，When 計算退役預估，Then 不給日期且來源為 `idle_90_days`；沒有任何紀錄的新鞋仍依計畫月跑量。
- [x] AC-2：Given `idle_90_days`，When 顯示單鞋分析與跑鞋清單，Then 預估退役顯示「—」並說明近 90 天沒穿。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_forecasting.py::test_a_pair_idle_for_90_days_gets_no_forecast_but_a_new_pair_uses_the_plan` |
| AC-2 | `unit_tests/frontend/corrections.test.cjs::SPEC-055 a retired shoe analysis says retired instead of forecasting a date` |
