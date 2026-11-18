# SPEC-068：跑鞋里程與 Strava 相同的捨去規則

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-067](067-timeline-shoe-mileage.md)

## Problem

- 以實際 `activities.csv` 對照 Strava「我的鞋履」：Strava 的鞋子里程是公尺欄位的合計，畫面**無條件捨去**到小數點第一位（Wave Sky 7 合計 673.352 km，顯示 673.3）。
- SPEC-067 讓 App 四捨五入到小數點第一位，小數點第二位為 5～9 時會比 Strava 多 0.1；App 的主要資料來源是 Strava 匯入，數字應該一模一樣。

## Goals

- 跑鞋里程在所有畫面都用和 Strava 相同的捨去規則。
- README 說明里程如何與 Strava 對帳。

## Non-goals

- 不改儲存值、API 或匯入換算（匯入已讀公尺欄位並四捨五入到 0.01 km）。
- 不改剩餘里程、月跑量等其他數字的格式。

## Proposed design

- `app-dashboard.js` 的 `floorShoeKm` 以 `Math.floor(km × 10 + 1e-6) / 10` 捨去，`1e-6` 避免二進位浮點數（例如 4.35 × 10 = 43.4999…）多捨一位；`formatShoeMileage` 固定顯示一位小數。
- 套用到現役／退役清單、首頁總里程卡、單鞋分析的總里程、壽命圖提示，以及輪替時間軸的鞋子里程、跑步與步行與暖身。

## Security and data isolation

- 只改前端顯示，沒有新的 API、查詢或寫入。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：跑鞋清單的數字和 Strava「我的鞋履」逐雙相同。
- 回滾方式與資料相容性：可直接回滾到 v4.18.2 image。

## Acceptance criteria

- [x] AC-1：Given 跑鞋里程，When 顯示在任何畫面，Then 無條件捨去到小數點第一位（673.352 → 673.3、0.29 → 0.2），且 401.7、4.35、1.1 這類值不會因浮點誤差少 0.1。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/trends.test.cjs::SPEC-068 shoe mileage is truncated to one decimal exactly like Strava` |
