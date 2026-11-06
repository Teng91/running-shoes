# SPEC-039：移除月跑量紀錄表

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-017](017-consistent-statistics-and-feature-lifecycles.md)、[SPEC-023](023-feature-operations-and-application-boundaries.md)、[SPEC-038](038-training-trends-and-shoe-rotation.md)

## Problem

月跑量分頁最底下的「月跑量紀錄」一次列出所有年份的每個月（目前 47 列），頁面要捲很久。
v4.1.1 先把它改成預設收合、只列一個年份，但它只跟「年度月跑量」圖表的年份連動，與頁面上另外兩個年份選單不一致，使用者切換年份時看不到變化。
跑步日誌已自動維護每月里程，上方的圖表也已能依年份查看，使用者不再需要這張表。

## Goals

- 月跑量分頁移除「月跑量紀錄」表格、新增表單與月份編輯對話框，只保留目標、訓練趨勢與圖表。
- 既有月跑量與「歷史／手動調整」資料完整保留，圖表、目標進度、報告、備份與 AI 工具照常使用。
- 舊版本存在裝置上的月份編輯草稿在升級後被忽略，不會打開已移除的對話框。

## Non-goals

- 不刪除 `/api/monthly-mileage` API、資料表或備份格式；不重新計算既有月份。
- 不提供替代的月份手動調整介面。

## Proposed design

- `frontend/templates/index.html`：移除表格區塊與 `monthly-modal.html` include。
- 刪除 `frontend/app-monthly.js`（表格、行內編輯、新增與編輯對話框）並從 `assets.json` 移除；啟動、對話框與面板繪製不再呼叫月份編輯函式。
- `frontend/app-workspace.js`：草稿表單不再包含月份新增表單；恢復草稿時捨棄 `kind: 'monthly'` 的編輯草稿，`resumeWorkspaceEditor()` 對未知種類不做任何事。
- 後端不變；月跑量仍由跑步日誌自動累加。

## Security and data isolation

- 只移除前端寫入入口；API 仍需登入並以 `user_id` 限制，無新查詢、寫入或秘密。

## Migration, rollout, and rollback

- Schema／資料 migration：無；資料不變。
- 上線與 smoke test：Asset 4.1.2／shell v46（release asset 由 51 個減為 50 個）；部署後執行匿名 `release-check`。
- 回滾方式與資料相容性：只改前端，可直接回滾至 v4.1.1 image；回滾後表格與編輯功能恢復。

## Acceptance criteria

- [x] AC-1：Given 月跑量分頁，When 載入，Then 沒有月跑量紀錄表、新增表單或月份編輯對話框，也不載入 `app-monthly.js`；目標、訓練趨勢與年度圖表照常顯示。
- [x] AC-2：Given 舊版本存下的月份新增或編輯草稿，When 升級後恢復本機工作區，Then 月份草稿被捨棄，其他草稿保留，舊草稿鍵不會打開已移除的對話框。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/monthly-records.test.cjs::SPEC-039 the monthly tab has no records table, add form or edit dialog`、`python3 scripts/task.py frontend-layout` |
| AC-2 | `unit_tests/frontend/monthly-records.test.cjs::SPEC-039 drafts saved by older versions drop monthly editors and forms`、`python3 scripts/task.py frontend-e2e` |
