# SPEC-102：拆解帳號匯入的兩個最複雜函式

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-100](100-architecture-ratchet.md)

## Problem

SPEC-100 量到後端 14 個函式超過 McCabe 複雜度 10。最高的是帳號匯入的執行 `services/account_import.execute_import`（32，95 個敘述），第四高的是同一流程的預覽差異 `services/account_import_changes.build_changes`（22）。這兩個函式各自在一個函式裡依序處理鞋款、跑步、月跑量、目標、月報、Strava 匯入紀錄與稽核歷史，合併（merge）與更新（update）兩種模式的分支交錯在一起，要確認某一步在哪種模式下會做什麼，必須讀完整個函式。

## Goals

- `execute_import` 只依原本的順序呼叫各步驟：`_import_shoes`、`_import_runs`（新增跑步由 `_create_run` 建立）、更新模式的 `_apply_month_changes`、`_import_months`、`_import_goal`、`_import_reports`、`_import_strava_history`、`_import_audit_history`。
- `build_changes` 依序呼叫 `_run_changes`（單筆 patch 由 `_run_patch` 計算）、`_projected_totals`、`_shoe_changes`、`_month_changes`，目標與月報的 patch 留在原處。
- 每個函式的複雜度都在 10 以下（拆完最高為 8），移除兩個 `# noqa: C901`，`scripts/architecture_ratchet.json` 的 `complexity_exemptions` 由 14 降到 12。
- 行為完全相同：寫入順序、`flush` 時機、錯誤訊息與交易邊界都不變。

## Non-goals

- 其餘 12 個超標函式（`run_agent_stream`、`run_startup_migrations`、`call_llm_stream` 等）留待後續規格。
- 不改變備份格式、API 或資料。

## Proposed design

- 步驟函式都接收同一個 caller-owned `Session` 與 `ImportPlan`，不自行 commit；`execute_import` 仍由 `services/account_restore.py` 在寫入交易內呼叫。
- `_import_shoes` 回傳來源鞋款 ID 對應到目標 ID，供 `_import_runs` 使用；合併模式在 `_import_runs` 結尾套用新跑步的里程並 `expire_all()`，與之前相同。
- `build_changes` 的中間結果以型別別名 `ShoeKey`、`FinalRun` 描述（新鞋款在執行前以 `('source', 來源 ID)` 表示）。

## Security and data isolation

- 每個查詢仍以 `user_id=uid` 限定，`ImportPlan` 只含目前帳號的資料列；沒有新增查詢。

## Migration, rollout, and rollback

- Schema／資料 migration：無（schema 13 不變）。
- 上線與 smoke test：部署前自動快照；部署後 `release-check`。前端資產不變，因此不升版本，記在 CHANGELOG 的 Unreleased。
- 回滾方式與資料相容性：還原本次 commit 即可，沒有資料相依。

## Acceptance criteria

- [x] AC-1：Given 既有的合併、更新、墓碑、別名、配額與回滾測試，When 拆解後執行，Then 全部通過，結果與拆解前相同。
- [x] AC-2：Given 更新預覽，Then 預覽的 patch 與實際執行寫入的值一致，總里程依最終跑步重新計算。
- [x] AC-3：Given `backend/`，Then 兩個函式不再需要 `# noqa: C901`，豁免數量等於基準 12，ruff 通過。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_account_restore.py::test_restore_roundtrip_is_atomic_and_idempotent`、`unit_tests/test_account_restore.py::test_restore_incremental_source_keeps_existing_edits_and_tombstones`、`unit_tests/test_account_restore.py::test_restore_commit_failure_rolls_back_every_business_and_mapping_row`、`unit_tests/test_account_restore.py::test_restore_import_summary_capacity_never_prunes_existing_history` |
| AC-2 | `unit_tests/test_account_restore.py::test_update_import_refreshes_existing_data_and_recalculates_totals`、`unit_tests/test_account_restore.py::test_import_diff_preview_matches_patches_and_preserves_local_runs`、`unit_tests/test_account_restore.py::test_identical_update_preserves_versions_history_and_unrelated_edits` |
| AC-3 | `unit_tests/test_architecture_boundaries.py::test_backend_complexity_is_linted_and_exemptions_only_shrink`、`python3 scripts/task.py test-fast` |
