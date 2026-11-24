# SPEC-103：拆解 AI 對話、資料庫遷移與模型呼叫的複雜函式

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-100](100-architecture-ratchet.md)、[SPEC-102](102-split-account-import.md)

## Problem

SPEC-102 之後，後端還有 12 個函式的 McCabe 複雜度超過 10。最高的四個都在核心流程上：

- `agent.run_agent_stream`（30）：同一個函式處理模型選擇、預先查詢、每輪的串流與工具解析、工具執行、重複／上限阻擋與最後一輪提示。
- `migrations.run_startup_migrations`（24）：從舊版無帳號資料庫到 schema 13 的所有步驟寫在同一個函式。
- `llm.call_llm_stream`（19）與 `llm._fetch_free_models`（19）：串流、tool call 片段合併與參數解析，以及模型目錄、免費判斷與每日排行統計混在一起。

## Goals

- `run_agent_stream` 只負責流程：`_resolve_model`、`_offered_tools`、`_prefetch_plan`，每輪 `_stream_model_turn`（片段由 `_chunk_event` 轉成 SSE）、`_record_assistant_turn`、`_run_tool_calls`（單一工具由 `_tool_output` 執行或阻擋，搜尋結果由 `_note_search_result` 記錄）。一次回答的狀態放在 `_AgentRun`，一輪的結果放在 `_Turn`。
- `run_startup_migrations` 依原順序呼叫 `_migrate_legacy_owner`、`_ensure_account_identity`、`_add_version_columns`、`_add_mileage_baselines`、`_add_run_provenance_and_indexes`、`_migrate_shoe_categories`、各 schema 步驟、`_sync_entity_sequences` 與 `_record_schema_version`。
- `_fetch_free_models` 拆出 `_get_json`、`_is_free`、`_free_tool_models`、`_add_canonical_key`、`_daily_token_totals`；`call_llm_stream` 拆出 `_stream_request`、`_merge_tool_call_deltas`、`_finished_tool_calls`、`_close_quietly`。
- 四個函式都降到 10 以下，`complexity_exemptions` 由 12 降到 8。
- 行為完全相同：SSE 事件順序與內容、工具阻擋規則、錯誤訊息、遷移順序與 SQL 都不變。

## Non-goals

- 其餘 8 個超標函式留待 SPEC-104。
- 不改變 system prompt、工具清單、模型選擇規則或 schema 版本。

## Proposed design

- 子步驟以 generator 的 `yield from` 回傳結果（例如 `_stream_model_turn` 回傳 `_Turn`、`_run_tool_calls` 回傳是否有工具被阻擋，`None` 代表回答必須立即結束），SSE 事件仍由同一個 generator 依序產出。
- 測試替換的模組層級名稱（`_execute_tool`、`_source_summary_event`、`MAX_TURNS`、`WEB_SEARCH_CALL_LIMIT`、`llm.call_llm_stream`）仍在呼叫時才查找，替換方式不變。
- 遷移步驟各自開自己的 `engine.begin()`，與之前的交易切分相同；`_columns()` 只是讀取欄位名稱的共用函式。

## Security and data isolation

- 資料庫工具仍只在有 `db` 與 `user_id` 時執行，缺少時一樣回傳錯誤並結束；外部搜尋結果仍是不可信資料。遷移不讀寫任何帳號之外的資料，SQL 不變。

## Migration, rollout, and rollback

- Schema／資料 migration：無（schema 13 不變，遷移步驟只是重新分組）。
- 上線與 smoke test：部署前自動快照；部署後 `release-check`。前端資產不變，記在 CHANGELOG 的 Unreleased。
- 回滾方式與資料相容性：還原本次 commit 即可。

## Acceptance criteria

- [x] AC-1：Given 既有的 agent 測試與行為評估，Then 串流、思考片段、原生與文字工具呼叫、重複與上限阻擋、缺少資料庫上下文與模型錯誤的結果都不變。
- [x] AC-2：Given 既有的遷移與回滾測試，Then 舊版資料庫升級到 schema 13 的結果不變。
- [x] AC-3：Given 既有的模型目錄與串流測試，Then 免費模型篩選、排行與 tool call 參數正規化不變。
- [x] AC-4：Given `backend/`，Then 四個函式不再需要 `# noqa: C901`，豁免數量等於基準 8。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_agent.py::test_personal_fit_stream_executes_complete_plan_before_model`、`unit_tests/test_agent.py::test_plain_response_streams_tokens_and_uses_default_model`、`python3 scripts/task.py eval-agent` |
| AC-2 | `unit_tests/test_migrations.py::test_lifespan_migrates_old_schema`、`unit_tests/test_migrations.py::test_migration_refuses_a_newer_schema_version`、`unit_tests/test_migrations.py::test_schema_thirteen_defaults_runs_to_road` |
| AC-3 | `unit_tests/test_llm.py::test_fetch_free_models_only_keeps_free_tool_models_in_overall_top_50`、`unit_tests/test_llm.py::test_call_llm_stream_closes_provider_stream_when_consumer_stops_early` |
| AC-4 | `unit_tests/test_architecture_boundaries.py::test_backend_complexity_is_linted_and_exemptions_only_shrink` |
