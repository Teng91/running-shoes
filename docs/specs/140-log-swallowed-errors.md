# SPEC-140：記錄被吞掉的例外與模組私有函式

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-139](139-review-layering-and-hike-pace.md)

## Problem

- 月報產生（`services/reports.py`）在準備資料、模型串流與儲存三處用 `except Exception` 回給使用者中性訊息，但伺服器沒有任何紀錄；正式環境月報失敗時無從得知原因。
- AI 工具執行失敗（`agent._execute_tool_safely`）只回 `ok: false`，同樣沒有紀錄，工具的程式錯誤會被默默吃掉。
- `read_models/strava_preview.py` 匯入 `strava_import._normalize_gear`，`strava_import.py` 呼叫 `schemas._validate_completed_run_date`：底線開頭的私有函式被其他模組使用。

## Goals

- 上述四處以 `logger.exception` 記錄原因（含 traceback）：月報記錄年月，工具記錄工具名稱；使用者看到的訊息不變。
- `ReportModelError`（模型轉接層提供的安全訊息）照舊直接顯示，不記為錯誤。
- 兩個函式改為公開名稱 `normalize_gear`、`validate_completed_run_date`；`architecture-check` 新增規則：`backend/` 內不得匯入或呼叫其他專案模組的底線名稱。

## Non-goals

- 不改變 API、SSE 事件或使用者看到的文字；不改變 `observability.py` 的 HTTP 紀錄。

## Proposed design

- `services/reports.py` 使用 `logging.getLogger("running_shoes.reports")`，訊息只有固定文字與年月。
- `agent._execute_tool_safely` 使用既有的 `backend.agent` logger，只記工具名稱；模型產生的參數可能引用使用者文字，因此不記錄。
- `scripts/check_architecture.py` 的 `private_import_violations()` 以 AST 檢查 `from backend… import _x` 與 `module._x`（module 為專案模組）。

## Security and data isolation

- 紀錄不包含月報內容、工具參數、token 或密碼（AGENTS「never log bodies, tokens or passwords」）；具名測試確認月報內文與工具參數不出現在紀錄中。

## Migration, rollout, and rollback

- Schema／資料 migration：無（schema 14）。
- 上線與 smoke test：`release-check`；`fly logs` 在月報或工具失敗時可看到 `running_shoes.reports`／`backend.agent` 的 traceback。
- 回滾方式與資料相容性：可直接回滾至 v5.3.5 image。

## Acceptance criteria

- [x] AC-1：Given 月報準備、模型串流或儲存發生非預期例外，When 產生月報，Then 使用者收到原本的中性訊息，伺服器紀錄有該階段與年月的 traceback，且不含月報內容；`ReportModelError` 不記錄。
- [x] AC-2：Given AI 工具丟出例外，When 執行工具，Then 回傳 `tool_execution_failed`，紀錄有工具名稱與 traceback，不含工具參數。
- [x] AC-3：Given 後端模組，When 執行 `architecture-check`，Then 沒有跨模組使用底線名稱，違規會被具名回報。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_report_generations.py::test_unexpected_report_failures_reach_the_server_log_not_the_user`、`unit_tests/test_report_generations.py::test_safe_model_errors_are_not_logged_as_failures` |
| AC-2 | `unit_tests/test_agent.py::test_execute_tool_safely_logs_the_cause_without_arguments`、`unit_tests/test_agent.py::test_execute_tool_safely_contains_failures_and_rolls_back` |
| AC-3 | `unit_tests/test_architecture_boundaries.py::test_private_helpers_stay_in_their_module`、`python3 scripts/task.py architecture-check` |
