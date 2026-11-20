# SPEC-089：內建前端函式庫納入稽核與跑鞋索引

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-054](054-security-headers-and-page-csp.md)

## Problem

- `frontend/vendor/` 內建 Chart.js 4.4.7 與 marked 15.0.12 的檔案，沒有出現在任何套件清單裡。`pip-audit` 與 GitHub 的相依套件警示都看不到它們，有安全公告時不會有人知道。
- `shoes` 沒有以 `user_id` 開頭的索引；每個跑鞋查詢都以擁有者篩選，資料變多後只能整表掃描。其他帳號資料表都已有對應索引或唯一鍵。

## Goals

- 兩個內建函式庫以相同版本列為 npm devDependencies，鎖定檔讓 `npm audit` 與 GitHub 警示涵蓋；`verify` 與 `audit-deps` 同時稽核 Python 與 npm 鎖定檔。
- 測試確認內建檔案的版本與 `package.json`、鎖定檔一致；裝了 npm 套件時，內容與 npm 發布的檔案相同。
- 新舊資料庫都有 `idx_shoes_user_id`。

## Non-goals

- 不升級 Chart.js 或 marked，也不改由打包工具產生前端檔案；瀏覽器仍載入 `frontend/vendor/` 的檔案。
- 不提高 schema 版本：索引只加速讀取，舊版程式照常運作。

## Proposed design

- `package.json` devDependencies 加入 `chart.js 4.4.7`、`marked 15.0.12`（精確版本），`package-lock.json` 由 registry.npmjs.org 解析。CI 的瀏覽器 job 原本就 `npm ci`，多裝兩個小套件。
- `scripts/task.py` 新增 `dependency_audit_commands()`：`pip_audit` 與 `npm audit --package-lock-only --audit-level=moderate`（只讀鎖定檔，不需安裝）；`verify` 與 `audit-deps` 共用。
- `migrations._ensure_lookup_indexes` 在啟動時 `CREATE INDEX IF NOT EXISTS idx_shoes_user_id ON shoes (user_id)`；`models.Shoe` 宣告同名索引，讓新建的資料庫一開始就有。

## Security and data isolation

- 不改變任何查詢條件或資料；npm 套件只用於稽核與測試比對，不會被部署或載入。
- `npm audit` 只把鎖定檔送到 npm registry 做比對，鎖定檔本來就公開在 repo 裡。

## Migration, rollout, and rollback

- Schema／資料 migration：啟動時建立索引（目前資料量下瞬間完成），schema 維持 12。
- 上線與 smoke test：部署前自動快照；部署後 `/health/ready` 200 與 `release-check`。
- 回滾方式與資料相容性：可直接回滾至 v4.25.0 image；舊版不認識這個索引也不受影響，不需要回滾 SQL。

## Acceptance criteria

- [x] AC-1：Given 內建的 Chart.js 與 marked，Then 檔案標頭的版本等於 `package.json` devDependencies 與鎖定檔的版本，且鎖定檔來源是 registry.npmjs.org。
- [x] AC-2：Given 已 `npm ci`，Then 內建檔案（去掉 jsDelivr 加的說明）與 npm 套件發布的檔案逐字相同。
- [x] AC-3：Given `verify` 與 `audit-deps`，Then 都執行 pip 與 npm 鎖定檔的漏洞稽核。
- [x] AC-4：Given 沒有索引的舊資料庫，When 啟動 migration，Then 建立 `idx_shoes_user_id`，以擁有者查詢跑鞋時使用它；重複執行不出錯。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_vendored_libraries.py::test_each_vendored_library_is_pinned_at_its_vendored_version` |
| AC-2 | `unit_tests/test_vendored_libraries.py::test_each_vendored_file_is_the_published_release_when_installed` |
| AC-3 | `unit_tests/test_vendored_libraries.py::test_dependency_audits_cover_python_and_the_npm_lockfile` |
| AC-4 | `unit_tests/test_migrations.py::test_startup_adds_the_shoe_owner_index_to_older_databases` |
