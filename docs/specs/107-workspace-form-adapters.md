# SPEC-107：鞋款編輯、目標表單與帳號設定向工作區登記自己的草稿

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-106](106-resource-cache-hooks.md)

## Problem

工作區（`app-workspace.js`）負責保存與還原草稿，但它直接操作其他功能的表單與視窗，和那些功能互相使用：

- `app-shoes.js` ↔ 工作區：工作區直接讀寫 `shoeModal` 與鞋款分類，鞋款又呼叫工作區保存草稿。
- `app-goals.js` ↔ 工作區：工作區以 `goalFormValues()`、`prepareGoalForm()`、`setGoalField()` 判斷與還原目標表單，目標又呼叫工作區保存草稿。
- `app-account.js` ↔ 工作區：工作區打開帳號設定時直接呼叫 `renderEmailSection()`，帳號又關閉工作區視窗。

## Goals

- 工作區提供三個登記函式：
  - `registerWorkspaceForm(name, ids, { isDraft, restore, reset })`：目標表單登記欄位、何時算草稿（與已儲存的目標不同）、如何還原與清除。
  - `registerWorkspaceEditor(kind, { capture, resume })`：鞋款編輯登記如何擷取開啟中的表單與重新打開；草稿值仍由工作區在重新打開後填回。
  - `onWorkspaceModalOpen(view)`：帳號設定在每次打開時顯示 Email 區塊。
- 工作區不再提到 `shoeModal`、`goalFormValues`、`prepareGoalForm`、`setGoalField`、`renderEmailSection` 或 `getSelectedCategories`。
- 互相使用的 script 由 10 對降到 7 對，跨 script 名稱由 244 降到 241；行為不變。

## Non-goals

- 跑步表單、跑步編輯與離線佇列仍由工作區直接處理（`app-runs.js` ↔ 工作區），登入相關的 6 對也留待後續規格。
- 不改 API、草稿格式或畫面。

## Proposed design

- 三個登記函式定義在 `app-workspace.js`，使用者（帳號、鞋款、目標）都在它之後載入，符合 SPEC-106 的載入順序規則。
- 表單依登記順序處理：跑步表單內建在前，目標表單登記在後，與之前的欄位順序相同；擷取編輯時先問已登記的編輯器（鞋款），再處理跑步與表格內編輯，順序與之前相同。
- 已存的草稿格式不變（`forms.goal`、`editors['shoe:<id>']`），舊版存下的草稿照常還原。

## Security and data isolation

- 草稿仍只存在這個網站、這個帳號的本機儲存，不含任何憑證；只調整 script 之間的呼叫方式。

## Migration, rollout, and rollback

- Schema／資料 migration：無（schema 13 不變，本機草稿格式不變）。
- 上線與 smoke test：Asset 4.29.5／shell v111；部署前自動快照，部署後 `release-check`。
- 回滾方式與資料相容性：可直接回滾至 v4.29.4 image。

## Acceptance criteria

- [x] AC-1：Given 目標表單與已儲存的目標相同，Then 不存成草稿；不同時存成草稿，並經目標自己的登記還原與清除。
- [x] AC-2：Given 開啟中的鞋款表單，Then 存成 `shoe:<id>` 草稿（含分類），繼續編輯時由鞋款登記重新打開，草稿值再填回；打開帳號設定時顯示 Email 區塊。
- [x] AC-3：Given 既有的草稿、清除與舊版草稿測試，Then 全部通過；architecture-check 的基準為 241 個名稱、7 對。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/workspace.test.cjs::SPEC-107 the goal form, shoe editor and account view register their workspace drafts` |
| AC-2 | `unit_tests/frontend/workspace.test.cjs::SPEC-107 the goal form, shoe editor and account view register their workspace drafts` |
| AC-3 | `unit_tests/frontend/workspace.test.cjs::SPEC-030 local clearing preserves replacement sessions and newer input`、`unit_tests/frontend/monthly-records.test.cjs::SPEC-039 drafts saved by older versions drop monthly editors and forms`、`unit_tests/test_architecture_boundaries.py::test_frontend_coupling_matches_the_recorded_ratchet`、`python3 scripts/task.py frontend-e2e` |
