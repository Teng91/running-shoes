# SPEC-115：只有一個使用者的宣告搬到使用者身邊

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-109](109-session-single-writer.md)、[SPEC-113](113-ui-action-registry.md)

## Problem

SPEC-113 之後前端還有 170 個跨 script 名稱。逐一檢查只有一個使用者、而且擁有者自己沒有用到的名稱後，大多數是刻意的：各功能提供給 `app.js` 的初始化函式、`app-api.js`／`app-session.js` 這類模組的 API，以及刻意集中在 `app-state.js`、由 Python 測試比對後端數值的鏡像常數（活動類型、配速範圍、壽命門檻）。真正放錯位置的有 4 個：

- `BRAND_COLORS`（`app-state.js`）只有 dashboard 的鞋款顏色使用。
- `byDate`（`app-state.js`）與 `fmtMoney`（`app-dashboard.js`）只有支出使用。
- `monthRuns`（`app-runs.js`）只有跑步紀錄畫面（`app-run-insights.js`）使用。

## Goals

- 把這 4 個宣告搬到唯一的使用者，跨 script 名稱由 170 降到 166；行為不變。
- `fmtMoney` 改為多行寫法，與其他函式一致（測試以「宣告到行首 `}`」擷取函式）。

## Non-goals

- 不搬模組 API、初始化函式、儲存工具與鏡像常數；它們的位置是刻意的。
- 不做 ES modules 遷移：那需要改寫所有 script 的載入方式與以原始碼擷取函式的前端測試架構，另立規格評估。

## Proposed design

- 純粹搬移宣告；新位置都在使用前載入或只在執行時使用，符合載入順序規則。

## Security and data isolation

- 只搬移前端的常數與輔助函式。

## Migration, rollout, and rollback

- Schema／資料 migration：無（schema 13 不變）。
- 上線與 smoke test：Asset 4.29.11／shell v117；部署前自動快照，部署後 `release-check`。
- 回滾方式與資料相容性：可直接回滾至 v4.29.10 image。

## Acceptance criteria

- [x] AC-1：Given 目前的前端，Then architecture-check 的基準為 166 個名稱、0 對，載入順序檢查通過。
- [x] AC-2：Given 支出卡片與表格、鞋款顏色與跑步紀錄的既有測試，Then 全部通過。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_architecture_boundaries.py::test_frontend_coupling_matches_the_recorded_ratchet`、`python3 scripts/task.py architecture-check` |
| AC-2 | `unit_tests/frontend/streams-rendering.test.cjs::spending details retain active and retired purchases, escape sizes and handle missing values`、`unit_tests/frontend/statistics-lifecycle.test.cjs::SPEC-017 spending renders server calendar months without UTC Date parsing`、`python3 scripts/task.py frontend-test` |
