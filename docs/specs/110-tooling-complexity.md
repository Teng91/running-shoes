# SPEC-110：開發工具與測試也套用複雜度上限

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-100](100-architecture-ratchet.md)、[SPEC-104](104-remaining-complexity.md)

## Problem

SPEC-100 只對 `backend/` 啟用 ruff 的 C901，`scripts/` 與 `unit_tests/` 以 per-file-ignores 排除。後端歸零後，排除的資料夾仍有 9 個函式超過複雜度 10：`task.run_task`（21）、`document_contracts.spec_errors`（20）、`check_architecture.check_feature_boundaries`（17）與 `main`（12）、`browser_runner.stop_process_tree`（14）、`release_check.check_release`（13）、`verify_diagnostics.verify`（11），以及兩個測試。這些工具決定 CI 是否放行，難讀就容易改錯。

## Goals

- 移除 per-file-ignores，C901（上限 10）套用到 `backend/`、`scripts/`、`unit_tests/` 全部。
- 拆法：
  - `run_task` 改為任務表 `_TASK_RUNNERS`，每個任務一個小函式（名稱在呼叫時才查找，測試可替換）。
  - `spec_errors` 拆成 `_spec_header_errors`、`_traceability_file_errors`、`_traced_criteria_errors`、`_named_test_errors`。
  - `check_feature_boundaries` 拆成 `_check_router_mutations`、`_check_domain_dependencies`、`_check_frontend_ownership`、`_check_frontend_state`；`main` 拆成 `_check_entry_points`、`_check_main_module`、`_check_api_routes`。
  - `stop_process_tree` 拆出 `_owned_processes`、`_signal_owned`、`_kill_survivors`；`check_release` 拆出 `_read_json`、`_check_health_and_contract`、`_check_asset`；`verify` 拆出 `_verify_entry`。
  - 兩個測試把資料準備與逐鞋斷言、失敗回應的組法抽成輔助函式。
- 行為完全相同：任務、錯誤訊息、檢查順序與 release-check 的判斷不變。

## Non-goals

- 不改任何任務的命令、CI workflow 或檢查規則本身。

## Proposed design

- 純粹抽出函式，不新增模組；任務表的鍵與 `PUBLIC_TASKS` 完全一致，由測試確認。

## Security and data isolation

- release-check 仍匿名、唯讀，仍要求未登入的 API 一律被拒；瀏覽器程序清理仍不會對已被重用的 PID 送出 SIGKILL。

## Migration, rollout, and rollback

- Schema／資料 migration：無（schema 13 不變）。
- 上線與 smoke test：只改開發工具與測試，正式站行為不變；記在 CHANGELOG 的 Unreleased。
- 回滾方式與資料相容性：還原本次 commit 即可。

## Acceptance criteria

- [x] AC-1：Given `pyproject.toml`，Then C901 上限 10 且沒有任何資料夾被排除，`backend/`、`scripts/`、`unit_tests/` 全部通過 ruff。
- [x] AC-2：Given 每個公開任務，Then 任務表恰好涵蓋它們並都能呼叫；既有的任務、文件契約、架構、release-check、診斷與瀏覽器程序清理測試全部通過。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_architecture_boundaries.py::test_backend_complexity_is_linted_and_exemptions_only_shrink`、`python3 scripts/task.py test-fast` |
| AC-2 | `unit_tests/test_task_runner.py::test_every_public_task_has_exactly_one_runner`、`unit_tests/test_release_check.py::test_release_check_fails_closed_on_broken_deployments`、`unit_tests/test_analytics.py::test_shoe_analytics_sql_is_bounded_and_user_scoped`、`python3 scripts/task.py docs-check` |
