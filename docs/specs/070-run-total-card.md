# SPEC-070：跑步里程與跑鞋里程分開顯示

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-067](067-timeline-shoe-mileage.md)、[SPEC-068](068-strava-mileage-truncation.md)

## Problem

- 跑鞋分頁的「總里程」是所有跑鞋里程的合計，包含記在鞋上的步行與健行（2,827.4 km），使用者想看的是和 Strava 個人頁一樣的跑步總計（2,280.6 km、358 次）。
- 「需補鞋類別」卡在下方的類別摘要已經有，重複且少用。

## Goals

- 新增「跑步里程」卡：所有跑步紀錄的合計與筆數，口徑和 Strava 的跑步總計相同。
- 「總里程」改名「跑鞋里程」，註明含步行、健行；摘要維持六張卡。

## Non-goals

- 不改跑鞋里程、每 km 成本或壽命的計算。
- 不匯入 Strava 的步行與健行活動。

## Proposed design

- `read_models/runs.run_totals`：使用者範圍的 `COUNT`／`SUM`，包含已刪除鞋款上的跑步（刪鞋不刪跑步）；`GET /api/runs/totals` 回傳 `run_count`、`total_km`。
- `renderCards` 的六張卡：現役跑鞋、跑步里程、跑鞋里程、總花費、平均每 km 成本、換鞋提醒。跑步里程以 `resourceStore` 的 `run-totals` 讀取，跑步與 Strava 匯入的快取失效時一併重讀；兩個里程都用 `floorShoeKm` 無條件捨去到小數點第一位。

## Security and data isolation

- 新端點需要登入，只查 `Run.user_id == current_user.id`。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：跑步里程顯示 2,280.6 km · 358 次跑步，跑鞋里程 2,827.4 km。
- 回滾方式與資料相容性：可直接回滾到 v4.18.4 image。

## Acceptance criteria

- [x] AC-1：Given 帳號有跑步（含已刪除鞋款上的跑步）與其他帳號的跑步，When 讀取 `GET /api/runs/totals`，Then 只回傳自己所有跑步的筆數與合計，未登入回 401。
- [x] AC-2：Given 跑鞋分頁，When 顯示摘要卡，Then 依序是現役跑鞋、跑步里程、跑鞋里程（含步行、健行）、總花費、平均每 km 成本、換鞋提醒，跑步里程照 Strava 捨去並顯示筆數。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_runs_api.py::test_run_totals_count_every_run_like_strava_and_stay_user_scoped` |
| AC-2 | `unit_tests/frontend/corrections.test.cjs::SPEC-070 the summary shows the Strava running total next to the shoe total with walks` |
