# SPEC-117：現役與退役跑鞋表格對齊

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-055](055-correctness-fixes-and-strava-deletions.md)

## Problem

- 現役跑鞋表格有「預估退役」欄，退役跑鞋表格沒有，兩張表欄數不同（11 與 10），上下並排時欄位對不齊。

## Goals

- 退役跑鞋表格也有「預估退役」欄，內容顯示「已退役」；兩張表欄位、順序與欄寬一致。
- 在現役與退役之間移動跑鞋照常運作：移到退役後顯示「已退役」，移回現役後重新顯示預估日期。

## Non-goals

- 不改變退役鞋不預估退役日的規則（SPEC-055），也不改 API 與資料。

## Proposed design

- `app-dashboard.js` 以同一個 `shoeTableRow` 產生兩張表的列；退役表第 9 欄是「已退役」，編輯按鈕仍分別使用 `edit-shoe`／`edit-retired-shoe`。
- 兩張表都加上 `shoe-list-table` 與相同的 `<colgroup>`，欄寬由 `06-shoes.css` 統一設定。

## Security and data isolation

- 只改前端呈現，不碰 API、資料或使用者隔離。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：跑鞋分頁兩張表欄位對齊，退役表「預估退役」顯示「已退役」；把一雙鞋移至退役再移回現役，兩邊各自正確。
- 回滾方式與資料相容性：直接回滾前一版 image。

## Acceptance criteria

- [x] AC-1：Given 現役與退役跑鞋，When 顯示跑鞋分頁，Then 兩張表有相同的 11 個欄位與欄寬，退役鞋的「預估退役」顯示「已退役」。
- [x] AC-2：Given 一雙現役跑鞋，When 移至退役再移回現役，Then 它依序出現在退役表（11 欄、顯示「已退役」）與現役表。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/streams-rendering.test.cjs::shoe purchase columns live only in spending details, with aligned table rows` |
| AC-2 | `unit_tests/frontend_e2e.cjs`（暫存資料庫真實移至退役再移回現役）、`unit_tests/frontend/streams-rendering.test.cjs::shoe purchase columns live only in spending details, with aligned table rows` |
