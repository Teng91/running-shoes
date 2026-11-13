# SPEC-053：文件清單一致性與程式整理

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-047](047-review-hardening-and-decoupling.md)、[SPEC-054](054-security-headers-and-page-csp.md)

## Problem

2026-11-13 的全專案審查發現，文件已經和程式分歧，而 `docs-check` 抓不到：

- README「目錄結構」漏列 28 個檔案：`backend/clock.py`、12 支 read model 中的 11 支、`routers/errors.py`、`services/account_import*.py`、`run_identity.py`、`errors.py`、`frontend/runtime/account-restore-controller.mjs`，以及 `release_check.py`、`release_browser.cjs` 等 9 支 script。部分說明也過時：`middleware.py` 寫成「只擋 Strava 上傳」，`rate_limits.py` 寫成「只限 Auth／AI」。
- README 的 AI 設定範例中，「固定某個免費且支援 tools 的模型」註解下方是空的：`OR_MODEL=` 在 `35febeb` 被刪掉，但功能仍在（`settings.py`）。`ENVIRONMENT`、`DB_DIR`、`DATABASE_URL`、`FRONTEND_DIR`、`FLY_APP_NAME` 完全沒有文件，其中 `ENVIRONMENT` 決定正式環境缺 `SECRET_KEY` 時是否拒絕啟動。
- SDD（`docs/architecture.md`）的模組責任表漏了 SPEC-038／040 的 `trends.py`、`highlights.py`、`saved_reports.py`，以及 `observability.py`、`services/accounts.py`、`fingerprints.py`、`retention.py`、`app-history.js`、`app-workspace.js` 等 18 個模組。每次發版只在文末加版本註記，表格本體沒有更新。
- AGENTS.md 列了所有 native runtime 模組，唯獨漏了 `strava-controller.mjs`。
- `docs-check` 只核對數字，以及「README 提到的路徑存不存在」，不檢查有沒有漏列。
- 程式冗餘：
  - `tools/legacy_calls.py` 在兩個函式各寫一份 bare-JSON 掃描迴圈，`json` 也重複 import。
  - `read_models/mileage.py` 兩個函式各寫一次同樣的查詢。
  - `schemas.py` 的密碼驗證器與「禁止 null」驗證器各複製了三次。
  - `services/goals.py` 把年度目標算了兩次。
  - `backend/auth.py` 保留只有測試在用的 `create_access_token` 等轉出；沒傳密鑰時會退回環境的預設 key，可能和 app 注入的 key 不同。
- 在 Windows（cp950 語系、專案指定的 Python 3.11）上，有 5 個測試失敗，CI 跑 Linux 所以沒有發現：
  - 前端回歸測試 1 個：Git 以 CRLF checkout，但 SPEC-052 的斷言寫死換行字元。
  - Python 測試 4 個：`test_task_runner.py` 讀 workflow 時沒有指定 encoding；`test_deploy_workflow.py` 的子程序以系統 code page 輸出中文 release notes。
- SPEC-041 這個編號從未使用，沒有任何地方說明。

## Goals

- README 目錄樹列出每個後端模組、前端 `app*.js`／runtime `.mjs` 與 `scripts/` 檔案；SDD 安排每個應用模組；`settings.py` 讀的每個環境變數都寫在 README。三者都由 `docs-check` 強制檢查。
- 合併上述冗餘，對外行為不變。
- 正式的 HTTP 認證只用 app 注入的密鑰；測試的簽章 helper 移到 `unit_tests/`。
- 完整的 `verify` 在 Windows（CRLF checkout、cp950、Python 3.11）也通過。

## Non-goals

- 不把 `backend/llm.py` 改成注入式設定。API key 本來就直接讀環境變數，模型目錄也是程序共用的快取；改為逐 app 注入只會讓快取鍵與大量測試 mock 變複雜，所以改為在 SDD 寫清楚這是程序層級的 adapter。
- 不重新命名 `backend/goals.py`／`services/goals.py` 這類讀寫分離的同名模組，只在 AGENTS.md 與 SDD 說明分工。
- AGENTS.md 是重點地圖，不強制逐檔列出。

## Proposed design

- **清單檢查**（`scripts/document_contracts.py::inventory_errors`，由 `check_docs.py` 呼叫）：
  - 解析 README「目錄結構」的方框樹，依縮排還原完整路徑。
  - 每個符合 `backend/**/*.py`（不含 `__init__.py`）、`frontend/app*.js`、`frontend/runtime/*.mjs`、`scripts/*.{py,cjs,sql}` 的檔案都必須出現在樹中；樹中列出但不存在的路徑也算錯誤。
  - SDD 必須提到每個後端與前端應用模組的檔名。
  - 以 regex 取出 `backend/settings.py` 讀取的環境變數，每個都必須以 `` `NAME` `` 或 `NAME=` 出現在 README。
- **文件**：
  - README 補齊目錄樹，`OR_MODEL` 改為註解範例，新增「執行環境與部署設定」表。
  - SDD 模組表補上 read models、middleware／observability、services、tools 與 `schemas.py` 的列，前端圖補上 workspace／history；並說明 `llm.py` 是程序層級的 adapter。
  - AGENTS.md 補上漏列的模組與兩條規則：新模組要寫進 README 樹與 SDD；CSP 規則。
  - 規格 README 說明 SPEC-041 未使用。
- **程式**：
  - `legacy_calls.py` 抽出共用的 `_bare_json_calls()`：strip 移除每個允許的 tool 物件，parse 只接受 object 參數，兩者的規則不變。
  - `monthly_mileage_stats()` 改用 `list_monthly_mileages()`。
  - `schemas.Password` 共用型別取代三個密碼驗證器，`_reject_explicit_nulls()` 取代三份重複的 null 檢查，錯誤訊息不變。
  - `auth.decode_access_token()` 改為必須傳入 `secret_key`，並移除 `create_access_token` 與 credential 轉出；測試改用 `unit_tests/token_helpers.py` 與 `backend.credentials`。
- **測試 helper**：
  - `unit_tests/frontend/helpers.cjs` 以 `readText()` 讀取來源，並把 CRLF 正規化為 LF。
  - Python 測試讀 repo 文字檔一律指定 `encoding="utf-8"`；release notes 子程序以 `PYTHONIOENCODING=utf-8` 執行，和 Linux runner 一致。

## Security and data isolation

- 認證只會用 app 注入的密鑰驗證 token。過去預設 key 的退回路徑只有測試在用，現在正式程式碼中已不存在。
- 文件清單檢查只讀 repo 內的檔案，不涉及使用者資料、secret 或網路。

## Migration, rollout, and rollback

- Schema／資料 migration：無，schema 7 不變。
- 上線與 smoke test：與 SPEC-054 一起發布為 v4.12.0；`verify` 包含新的 docs-check。
- 回滾方式與資料相容性：部署 v4.11.0 image 即可；API、token 格式與資料都不變。

## Acceptance criteria

- [x] AC-1：Given 一個沒有列在 README 目錄樹的模組、樹中列了不存在的檔案、SDD 沒提到的應用模組，或 README 沒寫的 `settings.py` 環境變數，When 執行 `docs-check`，Then 失敗並指出路徑或變數名稱；目前的 repo 全部通過。
- [x] AC-2：Given 正式的 HTTP 認證模組，When 驗證 token，Then 一定要傳入 app 注入的密鑰，且模組沒有預設 key 的簽章 helper；用其他 key 簽的 token 會得到 401。
- [x] AC-3：Given 合併後的 legacy tool-call 掃描與共用的 schema 型別，When 解析與驗證輸入，Then 行為和合併前相同：strip 移除每個允許的 tool 物件，parse 只接受 object 參數；註冊、登入、改密碼的新舊密碼超過 72 bytes 都回 422。
- [x] AC-4：Given Windows 的 CRLF checkout、cp950 語系與 Python 3.11，When 執行前端回歸測試與 workflow 測試，Then 來源一律以 LF／UTF-8 讀取，全部通過。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_docs_harness.py::test_inventory_rejects_unlisted_modules_stale_entries_and_unplaced_sdd_modules`、`unit_tests/test_docs_harness.py::test_readme_tree_parser_builds_nested_paths_and_ignores_comments`、`unit_tests/test_docs_harness.py::test_current_readme_tree_and_sdd_place_every_module`、`python3 scripts/task.py docs-check` |
| AC-2 | `unit_tests/test_auth.py::test_http_auth_never_signs_or_decodes_with_an_implicit_key` |
| AC-3 | `unit_tests/test_tools.py::test_legacy_markers_strip_every_allowed_call_but_parse_only_object_arguments`、`unit_tests/test_api.py::test_auth_rejects_passwords_over_bcrypt_byte_limit` |
| AC-4 | `unit_tests/frontend/security-policy.test.cjs::SPEC-053 shared test sources are read with LF line endings on every platform`、`unit_tests/test_deploy_workflow.py::test_release_tags_only_new_versions_after_the_release_check`、`unit_tests/test_task_runner.py::test_browser_jobs_are_independent_and_keep_timeout_diagnostics` |
