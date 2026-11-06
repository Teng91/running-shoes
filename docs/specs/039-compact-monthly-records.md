# SPEC-039：精簡月跑量紀錄表

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-017](017-consistent-statistics-and-feature-lifecycles.md)、[SPEC-038](038-training-trends-and-shoe-rotation.md)

## Problem

月跑量分頁最底下的「月跑量紀錄」一次列出所有年份的每個月（目前 47 列），頁面要捲很久。
年份圖表已經有年份選單，表格卻沒有跟著篩選。
這張表仍是補登月份與修正「歷史／手動調整」的唯一入口，因此不能直接移除。

## Goals

- 表格只列出「年度月跑量」圖表選擇的年份（最多 12 列），標題顯示目前年份。
- 表格預設收合，展開後才顯示新增表單與表格。
- 新增某一年的月份後，表格切換到該年份。

## Non-goals

- 不改 API、資料庫或月跑量計算；不新增獨立的表格年份選單。

## Proposed design

- `frontend/templates/index.html`：表格區塊改為 `<details id="monthly-records">`，摘要列顯示「月跑量紀錄 · 年份」與用途說明。
- `frontend/app-monthly.js`：`renderMonthlyTable()` 以 `selectedYear`（未設定時為資料中最新年份）篩選列，按鈕與行內編輯仍使用完整清單的索引，因此既有編輯／刪除快照不變；新增成功後設定 `selectedYear`。
- `frontend/app-monthly-charts.js`：切換年份時重繪表格；`renderActivePanel()` 先繪製圖表（決定年份）再繪製表格。

## Security and data isolation

- 只改前端呈現，資料仍來自既有使用者範圍的 `/api/monthly-mileage`；無新查詢、寫入或秘密。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：Asset 4.1.1／shell v45；部署後執行匿名 `release-check`。
- 回滾方式與資料相容性：只改前端，可直接回滾至 v4.1.0 image。

## Acceptance criteria

- [x] AC-1：Given 多個年份的月跑量，When 選擇年份，Then 表格只列出該年份，編輯／刪除仍對應正確紀錄；未選年份時顯示最新年份。
- [x] AC-2：Given 選擇的年份沒有紀錄或完全沒有紀錄，When 繪製表格，Then 顯示對應的空狀態；表格區塊預設收合。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/monthly-records.test.cjs::SPEC-039 monthly records list only the selected year and keep full-list row indexes`、`python3 scripts/task.py frontend-e2e` |
| AC-2 | `unit_tests/frontend/monthly-records.test.cjs::SPEC-039 monthly records explain empty years and start collapsed`、`python3 scripts/task.py frontend-layout` |
