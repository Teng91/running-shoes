# SPEC-058：README API 一覽與版本說明分離

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-053](053-documentation-inventory-and-hygiene.md)

## Problem

- README 只在功能段落列了部分 API：48 個端點中有 21 個在 README 完全沒出現（登入註冊、跑鞋與月跑量 CRUD、AI、目標修改、支出月份、異動歷史、批次操作、還原套用），只在最後一行指向 `/docs`。`docs-check` 也不檢查這件事。
- 「## 測試」一節約 500 行，將近整份 README 的 40%：
  - 裡面是 v3.5～v4.12 約 40 個版本的更新說明，順序混亂（v3 遞增、v4 倒序，最後又回到 v3.10.5）。
  - 測試指令夾在「統計與操作規則」小節裡，內容和 CHANGELOG 重複。

## Goals

- README 新增「API 一覽」，列出 API contract 的每一個端點與用途；`docs-check` 會擋下漏列的端點。
- 版本說明原文搬到 `docs/release-notes.md`，依版本由新到舊排列；README 只描述目前的功能與操作方式。
- 把「## 測試」重新整理為「開發與測試」（產物、測試指令、AI 開發規範）與「統計與操作規則」兩節。

## Non-goals

- 不改寫或刪減既有版本說明的內容，只搬移並修正相對連結。
- 不合併到 CHANGELOG：CHANGELOG 維持簡短摘要並用於 GitHub Release。

## Proposed design

- **`document_contracts.api_reference_errors(root)`**
  - 讀 `unit_tests/api_contract.json`（架構檢查也以它為準），要求 README 出現每一個 `` `METHOD /path` `` code span。
  - 必須以反引號或 `?` 結束，`GET /api/runs/summary` 不能代替 `GET /api/runs`。
  - `check_docs.main()` 與 `document_errors`、`inventory_errors` 一起執行。
- **README**：
  - 「API 一覽」依帳號、跑鞋、跑步日誌、Strava、月跑量、目標、分析、支出、AI、月報、匯出與備份、工作區分類。
  - 表格內避免 `|`，以免 GFM 拆格。
- **搬移**：以腳本把標題含版本號（以及附屬的「Schema 2 上線與回滾」）的小節移到 `docs/release-notes.md`，相對連結加上 `../`。README 留下「版本紀錄」一節指向 CHANGELOG 與版本說明。
- CHANGELOG 中段多餘的 `## [Unreleased]` 一併移除。

## Security and data isolation

- 只改文件與靜態檢查，不涉及資料或權限。API 一覽註明除了 health 與登入註冊外都需要 Bearer token，且只讀寫目前帳號。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：`docs-check` 通過，`docs/release-notes.md` 的連結由 `document_errors` 驗證。
- 回滾方式與資料相容性：純文件，回滾 commit 即可。

## Acceptance criteria

- [x] AC-1：Given API contract 與 README，When 執行 docs-check，Then 每個端點都要以自己的 `` `METHOD /path` `` 出現；只出現較長路徑或缺少時列出錯誤；目前的 README 全部通過。
- [x] AC-2：Given 重新整理後的文件，When 驗證連結與結構，Then README 不再含版本說明小節，`docs/release-notes.md` 由新到舊保留原文且連結有效。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_docs_harness.py::test_api_reference_requires_every_contract_route_exactly`、`unit_tests/test_docs_harness.py::test_current_readme_documents_every_api_route` |
| AC-2 | `unit_tests/test_docs_harness.py::test_current_document_contracts_are_valid`、`python3 scripts/task.py docs-check` |
