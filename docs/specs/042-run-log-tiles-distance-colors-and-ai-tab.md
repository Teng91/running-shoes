# SPEC-042：移除跑步摘要卡、距離分布配色與 AI 分頁合併

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-040](040-highlights-review-and-mobile-navigation.md)

## Problem

使用者逐項檢視 v4.2.0 後提出三點：

- 跑步日誌頂端的四張摘要卡（本週、連續跑步、本月目標、累計跑量）與「個人紀錄」一行用不到。
- 每雙鞋的距離分布用同一色系的五種深淺，分段看不清楚。
- AI 助手與月報是兩個分頁，可以合併。

## Goals

- 跑步日誌移除四張摘要卡、里程碑標籤與個人紀錄；保留「今天穿哪雙」建議。
- 距離分布改為 5 km 一段：<5 紅色、5–10 黃色、10–15 綠色、15–20 藍色、≥20 紫色。
- 導覽只留一個「AI」分頁，對話與月報面板上方各有「對話／月報」切換。

## Non-goals

- 不變更其他分頁、圖表或資料；不改 schema。

## Proposed design

- `backend/read_models/highlights.py`：`home_summary` 只回傳 `as_of` 與 `suggestion`，移除本週、連續、目標、累計、紀錄與成就計算；`DISTANCE_BUCKETS` 改為 15–20／≥20。
- `frontend/app-run-insights.js`：`renderHomeSummary()` 只繪製選鞋建議；刪除摘要卡、進度環與成就文字函式。
- `frontend/app-shoe-charts.js`：`DISTANCE_COLORS` 改為紅、黃、綠、藍、紫。
- `frontend/templates/index.html`、`app-core.js`：移除月報導覽按鈕，AI 面板加入切換；`switchTab('report')` 讓 AI 分頁維持選取。手機底部分頁列改為 5 欄。

## Security and data isolation

- 只縮減唯讀回應與前端呈現；查詢仍以 `user_id` 篩選，無新寫入或秘密。

## Migration, rollout, and rollback

- Schema／資料 migration：無；schema 6 不變。
- 上線與 smoke test：Asset 4.3.0／shell v49；部署後執行匿名 `release-check`。
- 回滾方式與資料相容性：可直接回滾至 v4.2.0 image。

## Acceptance criteria

- [x] AC-1：Given 跑步日誌，When 載入，Then 沒有摘要卡與個人紀錄，首頁摘要 API 只回傳選鞋建議，建議仍可一鍵選入。
- [x] AC-2：Given 跑步距離，When 讀取與繪製距離分布，Then 分段為 <5／5–10／10–15／15–20／≥20 km，依序為紅、黃、綠、藍、紫。
- [x] AC-3：Given 導覽列，When 開啟 AI，Then 只有一個 AI 分頁，可在面板內切換對話與月報，月報時 AI 分頁保持選取。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_highlights.py::test_home_summary_only_carries_the_next_shoe_suggestion`、`unit_tests/frontend/highlights.test.cjs::SPEC-040 run log suggests the next shoe without summary tiles` |
| AC-2 | `unit_tests/test_highlights.py::test_distance_mix_buckets_runs_for_active_shoes_only`、`unit_tests/frontend/highlights.test.cjs::SPEC-040 distance mix stacks bucket counts per active shoe and names the long-run pair` |
| AC-3 | `unit_tests/frontend/crud-reports.test.cjs::the report tab wires its panel and only loads data after login`、`python3 scripts/task.py frontend-layout` |
