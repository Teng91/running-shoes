# SPEC-011：購鞋欄位集中到支出明細

- 狀態：Implemented
- Owner：Running Shoes
- 關聯 issue／ADR：使用者要求簡化跑鞋清單；延續模組化單體架構

## Problem

現役／退役跑鞋表格混合使用狀態與購鞋資訊，尺寸、買價、原價、折數讓清單過寬。
支出明細已有價格與折數，但缺少尺寸；同一資訊重複出現在兩個功能頁。

## Goals

- 現役與退役跑鞋清單移除尺寸、買價、原價、折數四欄。
- 支出明細統一呈現日期、品牌、鞋款、尺寸、買價、原價、折數、類別、狀態。
- 保留既有資料、新增／編輯表單、每 km 成本及壽命計算。

## Non-goals

- 不刪除資料欄位，不變更 API、資料庫 schema、匯出格式或計算規則。
- 不重設價格或尺寸，不新增獨立的購鞋資料模型。

## Proposed design

只調整 `index.html` 的三組表頭，以及 `app-dashboard.js`、`app-spending.js` 的 row rendering。
支出明細仍合併現役與退役鞋並按購買日期排序；尺寸做 HTML escaping，空值顯示「—」。
新增／編輯跑鞋的共用 modal 保留尺寸與價格欄位，儲存後支出明細反映更新；無原價時折數顯示「—」。
桌面與手機沿用既有 table-wrap 橫向捲動，不使整頁溢出。

## Security and data isolation

- 沿用 user-scoped `/api/shoes` 資料，不新增查詢或權限。
- 所有文字以既有 escaping 處理；測試只使用合成資料及暫存 SQLite。

## Migration, rollout, and rollback

- Schema／資料 migration：無，正式資料不搬移或刪除。
- 發布 v3.2.0、同步靜態資產版本與 PWA cache；部署後檢查健康狀態及正式站 mock 版面。
- 回滾可重新部署 v3.1.0，API 與資料格式相容。

## Acceptance criteria

- [x] 現役／退役鞋表格不含四個購鞋欄位，表頭與資料列數一致，分析／編輯仍可用。
- [x] 支出明細同時顯示現役及退役鞋的尺寸、價格、折數，排序及狀態維持原行為；空尺寸／無原價顯示「—」。
- [x] 編輯尺寸／價格後重新載入仍保留，支出明細同步反映，跑鞋里程不變。
- [x] Chromium/WebKit 亮暗模式、手機及桌面矩陣通過，表格可左右捲動且不造成整頁溢出。

## Test traceability

| Acceptance criterion | Test file / command |
| --- | --- |
| AC-1、AC-2 | `unit_tests/frontend_regressions.cjs`、`unit_tests/frontend_layout.cjs` |
| AC-3 | `unit_tests/frontend_e2e.cjs`（暫存資料庫真實 CRUD） |
| AC-4 | `python3 scripts/task.py frontend-layout` |
| 全部 | `python3 scripts/task.py verify-all` |
