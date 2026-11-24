# SPEC-100：前端跨檔耦合與後端複雜度只准變少（architecture ratchet）

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-090](090-module-decoupling.md)、[SPEC-095](095-core-data-store.md)

## Problem

現有的 `architecture-check` 守住後端依賴方向，但兩種技術債沒有任何檢查，只會越積越多：

- 38 個 classic script 共用同一個全域範圍，依賴只是裸名稱。量測時有 255 個頂層名稱被其他 script 使用，25 對 script 互相使用（例如 `app-core.js` 呼叫各功能的 render，功能又回呼 `loadData`、`renderActivePanel`）。新增一個跨檔名稱不會被任何檢查發現。
- ruff 沒有開複雜度規則。後端有 14 個函式的 McCabe 複雜度超過 10，最高是 `execute_import`（32）與 `run_agent_stream`（30），新的超標函式同樣不會被發現。

## Goals

- `architecture-check` 量測前端跨檔名稱數與互相使用的 script 對，和 `scripts/architecture_ratchet.json` 比對：增加或出現新的一對就失敗；減少但基準沒有更新也失敗，基準因此永遠等於現況。
- ruff 對 `backend/` 啟用 C901（上限 10）。既有的 14 個超標函式標上 `# noqa: C901`，`architecture-check` 限制這類標記的數量只能減少。
- 失敗訊息說明怎麼修（傳入參數、搬進 runtime module、拆函式，或降低基準）。

## Non-goals

- 本次不拆任何函式、不改任何 script；拆解由後續規格處理，每次拆完降低基準。
- `scripts/` 與 `unit_tests/` 不套用 C901。
- 不改變任何 API、畫面或資料。

## Proposed design

- `check_architecture.frontend_script_dependencies()`：去掉註解後，收集每個 script 的頂層宣告（`function`、`let`、`const`、`var`、`class`）作為擁有者；另一個 script 使用該名稱、而且自己沒有在任何層級宣告同名綁定時，記為一條依賴。
- `frontend_coupling()` 回傳 `cross_script_names`（被其他 script 使用的頂層名稱數）與 `mutual_pairs`（雙向依賴的 script 對）；`coupling_violations()` 與基準比對。
- `complexity_exemptions()` 找出 `backend/` 中含 `# noqa: C901` 的行；`complexity_exemption_violations()` 與基準的 `complexity_exemptions` 比對。
- `pyproject.toml` 的 ruff `select` 加入 `C901`、`[tool.ruff.lint.mccabe] max-complexity = 10`，`scripts/**` 與 `unit_tests/**` 以 per-file-ignores 排除。

## Security and data isolation

- 只新增靜態檢查，不讀寫資料庫、不碰 secret 或使用者資料。

## Migration, rollout, and rollback

- Schema／資料 migration：無（schema 13 不變）。
- 上線與 smoke test：CI 的 architecture-check 與 Ruff 步驟會執行新檢查；正式站行為不變。
- 回滾方式與資料相容性：還原本次 commit 即可，沒有資料相依。

## Acceptance criteria

- [x] AC-1：Given 目前的前端，Then 量測結果與 `scripts/architecture_ratchet.json` 完全相同，architecture-check 通過。
- [x] AC-2：Given 新增跨檔名稱或新的互相使用 script 對，Then 檢查失敗並指出；Given 數量減少或某一對消失但基準未更新，Then 檢查也失敗並要求降低基準；註解中的名稱與自己宣告的同名綁定不算依賴。
- [x] AC-3：Given `pyproject.toml`，Then backend 啟用 C901 且上限為 10、沒有 backend 的排除；`# noqa: C901` 的數量等於基準，多一個或少一個都失敗。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_architecture_boundaries.py::test_frontend_coupling_matches_the_recorded_ratchet`、`python3 scripts/task.py architecture-check` |
| AC-2 | `unit_tests/test_architecture_boundaries.py::test_coupling_ratchet_rejects_growth_and_unrecorded_improvement` |
| AC-3 | `unit_tests/test_architecture_boundaries.py::test_backend_complexity_is_linted_and_exemptions_only_shrink`、`python3 scripts/task.py test-fast` |
