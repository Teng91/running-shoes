# SPEC-104：拆完後端其餘的複雜函式

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-100](100-architecture-ratchet.md)、[SPEC-103](103-split-agent-migrations-llm.md)

## Problem

SPEC-103 之後還有 8 個函式的 McCabe 複雜度超過 10，仍以 `# noqa: C901` 豁免：備份圖驗證 `AccountBackup.validate_graph`（17）、查詢規劃 `build_query_plan`（15）、刪除復原 `restore_deleted`（14）、首頁統計 `dashboard_analytics`（14）、匯入計畫 `build_import_plan`（13），以及 `web_search`、`parse_csv` 與上傳大小限制 `UploadLimitMiddleware.__call__`（各 11）。

## Goals

- 每個函式都降到 10 以下，後端不再有任何 `# noqa: C901`，`complexity_exemptions` 由 8 降到 0；之後任何超標函式都直接讓 ruff 失敗。
- 拆法：
  - `validate_graph` 依原順序呼叫 `_check_unique_keys`、`_check_run_features`、`_check_run_aliases`、`_check_run_references`、`_logged_totals`、`_reconcile_shoes`、`_reconcile_months`。
  - `build_query_plan` 改為表格 `_PERSONAL_TOOL_TERMS`（工具順序不變，使用分析取代單純的鞋款清單），肯定回覆的上下文由 `_effective_message` 處理。
  - `restore_deleted` 依資料種類分派到 `_restore_run`、`_restore_shoe`、`_restore_month`。
  - `dashboard_analytics` 拆出 `_month_shoe_usage`、`_seven_day_end`、`_recent_seven_days`、`_lifecycle_alerts`、`_month_forecast`。
  - `build_import_plan` 拆出 `_map_own_archive`、`_run_targets`、`_claim_update_target`。
  - `web_search` 拆出 `_cached_result`、`_search_with_retry`、`_remember_result`；`parse_csv` 拆出單列的 `_activity_row`；上傳限制拆出 `_declared_size`、`_read_limited_body`、`_too_large`。
- 行為完全相同：錯誤訊息與檢查順序、回傳格式、SQL 條件與交易邊界都不變。

## Non-goals

- 不改變 API、備份格式、工具清單或快取規則；`scripts/` 與 `unit_tests/` 仍不套用 C901。

## Proposed design

- 純粹抽出函式，不新增模組；每個輔助函式只接收它需要的值。`dashboard_analytics` 的唯讀查詢順序略有調整（目標進度先算），結果相同。
- 上傳限制仍在讀到超過上限的那一刻回應 413，讀完後只保留一份 body 交給應用程式。

## Security and data isolation

- 每個查詢仍以 `user_id` 限定；備份驗證仍在合併前拒絕不一致的檔案；搜尋結果仍是不可信資料；上傳大小限制在讀取 body 時就生效。

## Migration, rollout, and rollback

- Schema／資料 migration：無（schema 13 不變）。
- 上線與 smoke test：部署前自動快照；部署後 `release-check`。前端資產不變，記在 CHANGELOG 的 Unreleased。
- 回滾方式與資料相容性：還原本次 commit 即可。

## Acceptance criteria

- [x] AC-1：Given 既有的備份、還原、刪除復原與 Strava 匯入測試，Then 驗證、計畫、復原與 CSV 解析的結果與錯誤訊息不變。
- [x] AC-2：Given 既有的 agent 規劃、首頁統計、搜尋快取與上傳大小限制測試，Then 結果不變。
- [x] AC-3：Given `backend/`，Then 沒有任何 `# noqa: C901`，豁免數量等於基準 0，ruff 通過。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_account_restore.py::test_restore_incremental_source_keeps_existing_edits_and_tombstones`、`unit_tests/test_history.py::test_restore_monthly_adjustment_and_reject_later_changes`、`unit_tests/test_history.py::test_restore_run_requires_original_shoe_and_quota`、`unit_tests/test_strava_import.py::test_strava_parser_rejects_future_activities` |
| AC-2 | `unit_tests/test_agent.py::test_personal_fit_query_plan_prefetches_web_and_personal_data`、`unit_tests/test_analytics.py::test_dashboard_reports_lifecycle_alert_and_goal_progress`、`unit_tests/test_search.py::test_cache_prunes_expired_and_oldest_entries`、`unit_tests/test_strava_import.py::test_strava_upload_size_limit_is_bounded_before_full_read` |
| AC-3 | `unit_tests/test_architecture_boundaries.py::test_backend_complexity_is_linted_and_exemptions_only_shrink`、`python3 scripts/task.py test-fast` |
