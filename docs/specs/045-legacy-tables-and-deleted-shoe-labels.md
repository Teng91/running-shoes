# SPEC-045：清除舊空表與已刪除鞋款標籤

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-017](017-consistent-statistics-and-feature-lifecycles.md)、[SPEC-044](044-annual-goal-overview.md)

## Problem

正式資料庫有 19 張表，其中 `operation_history`（已移除的復原操作）與 `app_settings` 是早期功能留下的空表，現行 model 與查詢都不使用。
年度堆疊圖遇到已刪除鞋款時顯示「歷史鞋款 已刪除 #15」，把內部主鍵露給使用者，看起來像每位使用者有自己的鞋款編號。

## Goals

- 啟動時刪除上述兩張舊表（連同索引），但只刪空表；舊安裝若仍有資料就保留，不丟資料。
- 年度堆疊圖把所有已刪除鞋款的里程合成一個灰色「已刪除的鞋款」系列，月合計不變，不顯示任何內部編號；日曆標籤改稱「已刪除」。

## Non-goals

- 不改主鍵分配：鞋款、跑步、月份仍是全域穩定編號，刪除不回收、不重排。主鍵被跑步、異動歷史、備份對應、離線佇列與開啟中的表單引用，重排會讓舊參照指到錯的鞋款。
- 不合併其他 17 張表；實測年度彙總 0.09 ms、當月跑步 0.01 ms（`idx_runs_user_date`），表數量不影響查詢速度。
- 不調整 Fly 自動停機設定。

## Proposed design

- `backend/migrations.py`：`LEGACY_TABLES` 與 `_drop_empty_legacy_tables()` 在 audit trigger 安裝後執行，可重複執行；不屬於 schema 契約，schema version 維持 6。
- `frontend/app-monthly-charts.js`：鞋櫃中的鞋（現役與退役）各自一個系列，找不到的鞋款里程合併為「已刪除的鞋款」。
- `frontend/app-run-insights.js`：日曆中已刪除鞋款標籤由「歷史鞋款」改為「已刪除」。

## Security and data isolation

- 只刪除沒有任何資料列的舊表；不讀取或輸出其他帳號資料。圖表仍只使用本人 `/api/runs/year-summary` 的彙總。

## Migration, rollout, and rollback

- Schema／資料 migration：刪除空的 `operation_history`、`app_settings`；以正式備份在記憶體副本演練，19 → 17 張表，業務資料雜湊不變、`integrity_check` 與外鍵檢查通過。
- 上線與 smoke test：部署前照常建立並驗證異地備份；Asset 4.5.1／shell v52；部署後匿名 `release-check`。
- 回滾方式與資料相容性：v4.5.0 不使用這兩張表，可直接回滾 image；schema version 不變。

## Acceptance criteria

- [x] AC-1：Given 含空的 `operation_history` 與有資料的 `app_settings` 的資料庫，When 啟動 migration 兩次，Then 空表與其索引被刪除、有資料的表保留，schema version 仍為 6。
- [x] AC-2：Given 年度彙總含兩雙已刪除鞋款，When 繪製堆疊圖，Then 它們合併為一個「已刪除的鞋款」系列，月合計不變且不顯示 `#` 編號；日曆標籤為「已刪除」。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_migrations.py::test_startup_drops_only_empty_legacy_tables` |
| AC-2 | `unit_tests/frontend/statistics-lifecycle.test.cjs::SPEC-017 deleted shoes remain in annual stacked mileage totals`、`unit_tests/frontend/statistics-lifecycle.test.cjs::SPEC-031 calendar shows shoe names and distance without run counts` |
