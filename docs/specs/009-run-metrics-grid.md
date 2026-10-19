# SPEC-009：手機跑步摘要兩欄三列

- 狀態：Implemented
- Owner：Running Shoes
- 關聯 issue／ADR：SPEC-008

## Problem

跑步日誌六張摘要分屬 run-stats 與 dashboard-insights，手機 CSS 分別使用單欄與雙欄，造成三張全寬卡片接上兩張加一張的排列。既有版面測試沒有注入 dashboard analytics 資料，未涵蓋六張卡片同時出現的情境。

## Goals

- 手機以同一個兩欄網格呈現六張卡片，依序排成三列。
- 同列卡片的上下緣、左右欄寬與間距一致，長鞋名與較長說明正常換行。
- 分析載入中、失敗訊息與鞋款提醒占滿整列；桌面保留原有三欄配置。

## Non-goals

- 不改變摘要數值、API、資料模型或其他分頁的卡片。

## Proposed design

以 run-metrics 容器包住既有兩個資料區塊。800px 以下使用兩欄 CSS Grid，內部資料包裝層使用 display: contents，讓六張卡片參與同一個網格且維持原有 DOM 順序。提醒與載入／失敗訊息明確跨兩欄。資料仍由既有同步與非同步 rendering 更新。

## Security and data isolation

只修改呈現與測試資料，不新增 query 或 mutation，維持既有使用者隔離。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：手機實際六張卡片的欄位位置、同列等高與錯誤訊息全寬。
- PWA CSS／JS 資產版本同步更新。
- 回滾：回滾前端版本，不影響資料。

## Acceptance criteria

- [x] Given 手機顯示六張卡片，Then 排列為總里程／天數、主力鞋／上月比較、近七天／月目標，共兩欄三列。
- [x] Given 長鞋名與長目標說明，Then 卡片不溢出且每一列兩張卡片等高、兩欄對齊。
- [x] Given 分析載入或失敗，Then 訊息獨占整列；成功後恢復六張卡片，鞋款提醒仍在整個網格下方跨兩欄。
- [x] Given 桌面寬度，Then 原有三欄、兩組摘要的呈現不變。

## Test traceability

| Acceptance criterion | Test file / command |
| --- | --- |
| AC-1～AC-4 | `python3 scripts/task.py frontend-layout`（注入實際六卡分析資料、檢查幾何位置） |
| rendering 回歸 | `python3 scripts/task.py frontend-test` |
