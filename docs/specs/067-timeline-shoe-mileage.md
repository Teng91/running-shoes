# SPEC-067：輪替時間軸顯示鞋子里程

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-038](038-training-trends-and-shoe-rotation.md)、[SPEC-060](060-run-duration-and-pace.md)

## Problem

- 輪替時間軸的提示框只顯示跑步紀錄的合計（例如 Wave Rider 29 的 365.2 km），跑鞋清單顯示鞋子總里程（407.2 km），使用者以為資料錯了。
- 差距是記在鞋上、但不在跑步日誌的里程：Strava 的鞋子里程包含「步行」活動（暖身、緩和），匯入只收跑步類型；手動加到鞋子里程的暖身也一樣。
- 跑鞋清單顯示到小數點第二位，和 Strava 的裝備清單（第一位）不同，不好對照。

## Goals

- 時間軸顯示和跑鞋清單一致的鞋子里程，並拆出跑步與步行與暖身。
- 跑鞋里程和 Strava 一樣顯示到小數點第一位。

## Non-goals

- 不匯入 Strava 的步行活動，也不建立校正用的跑步紀錄；訓練分析仍只看跑步。
- 不自動處理早於購買日的跑步。

## Proposed design

- `trends.shoe_timeline` 每雙鞋新增 `shoe_km`（鞋子里程）與 `other_km`（鞋子里程減跑步合計，可能為負）。
- 提示框顯示「鞋子里程 X km」與「跑步 Y km · N 次｜步行與暖身 Z km」；`other_km` 四捨五入到第一位不是正數時只顯示跑步。
- 跑鞋清單的里程以 `formatShoeMileage` 顯示到第一位；行內編輯沿用完整的儲存值。

## Security and data isolation

- 沿用既有的使用者範圍查詢，只多讀同一列鞋子的里程；沒有新的寫入。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：Wave Rider 29 的提示框顯示鞋子里程 407.2 km、跑步 365.2 km · 50 次、步行與暖身 42.0 km。
- 回滾方式與資料相容性：可直接回滾到 v4.18.1 image。

## Acceptance criteria

- [x] AC-1：Given 鞋子里程大於跑步合計，When 讀取時間軸，Then 回傳鞋子里程與差距，提示框顯示鞋子里程、跑步與步行與暖身。
- [x] AC-2：Given 差距為零或負數，When 顯示提示框，Then 只顯示鞋子里程與跑步；跑鞋清單的里程顯示到小數點第一位。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_trends.py::test_shoe_timeline_splits_shoe_mileage_into_runs_and_walking` |
| AC-2 | `unit_tests/frontend/trends.test.cjs::SPEC-067 the rotation tooltip shows the shoe total with runs and walking` |
