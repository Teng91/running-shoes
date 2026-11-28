# SPEC-142：請求大小上限、新鞋退役預估與其他 review 強化

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-073](073-api-flood-guard.md)、[SPEC-069](069-idle-shoe-forecast.md)、[SPEC-138](138-drop-shoe-monthly-km.md)、[SPEC-093](093-project-review-hardening.md)

## Problem

- `UploadLimitMiddleware` 只保護 Strava 與備份上傳三個路徑。實測不登入對 `/api/auth/login` 送 30 MB JSON，伺服器整包讀入並解析後才回 422，單一請求記憶體峰值約 95 MB；正式環境只有一台 256 MB 機器，幾個同時的請求就能讓它記憶體不足。
- 退役預估固定以「近 90 天里程 ÷ 90 天」換算月均。剛開穿 10 天跑了 100 km 的鞋（實際約 300 km／月）被算成 33.8 km／月，預估晚了一年半；SPEC-138 移除計畫月跑量後，每雙新鞋都會遇到。
- `llm.current_config()` 沒有注入設定時會自己讀環境，和 AGENTS「模組不讀環境」不符。
- SPA fallback 會提供 `frontend/` 底下任何檔案，包括 `templates/`、`css/` 原始檔與 `assets.json`。
- 過期的還原預覽（每份最多 64 MiB）只在啟動時、或同一帳號再次預覽時清除。
- `services/runs.create_run` 留著只為 mock 而寫的 `isinstance` 判斷；`account_import_changes` 與 `account_import_plan` 在型別檢查時互相匯入。

## Goals

- 每個 `/api/` 的 POST／PUT／PATCH／DELETE 請求內容在解析前限制為 `Settings.max_api_body_bytes`（1 MiB），超過回 413 `too_large`；Strava（11 MB）與備份（64 MiB）上傳維持各自的上限。限制不會拒絕任何 schema 接受的請求（最大的 AI 對話約 0.4 MB）。
- 讀完內容後，後續 `receive()` 交回原連線，串流回應（AI 對話、月報）仍收得到真正的中斷。
- 第一筆跑步落在近 90 天內的鞋，月均改以「第一筆跑步到今天的天數」計算，至少 14 天、最多 90 天；跑鞋清單、單鞋分析與 AI 工具使用同一個數字。
- `llm.current_config()` 未注入時回傳沒有金鑰的 `LLMConfig()`，不讀環境。
- `templates/`、`css/` 與 `assets.json` 不對外提供，請求這些路徑時回 shell。
- 應用程式運作期間每小時清除過期的還原預覽。
- 移除 mock 用判斷；`ImportTargets` Protocol 取代型別檢查時的循環匯入，架構測試確認 backend 沒有互相匯入的模組。
- README 概覽的版本、規格數、端點數與測試數由 `docs-check` 檢查。

## Non-goals

- 不改變 Strava／備份上傳上限、限流數字與退役門檻；不改 API 回應欄位名稱（`actual_monthly_km_90_days` 保留）。
- 不改變 LLM 設定是行程內單一設定的作法（一個行程只服務一個 app）。

## Proposed design

- `middleware.UploadLimitMiddleware._limit()` 依路徑與方法選擇上限；`create_app` 傳入 `max_api_bytes=settings.max_api_body_bytes`。
- `forecasting.rate_window_days(first_run, as_of)`；`forecasts_for_shoes` 的批次查詢多取 `min(Run.date)`，`insights._shoe_analytics` 傳入 `shoe_run_statistics` 已有的 `first`。
- `app_factory.UNSERVED_FRONTEND_ENTRIES` 在 404 fallback 排除建置輸入；`lifespan` 建立 `_sweep_expired_previews` 背景工作，關閉時取消。
- `scripts/check_docs.require_overview()` 檢查 README「規模」表。

## Security and data isolation

- 大小限制在認證與限流之後、任何解析之前執行，只看位元組數，不讀內容。
- 退役預估查詢沿用 `user_id` 條件；預覽清除只刪過期的暫存列，不讀任何帳號資料（與啟動時的清除相同）。
- 不提供的檔案不含機密；改動只縮小公開範圍。

## Migration, rollout, and rollback

- Schema／資料 migration：無（schema 14）。
- 上線與 smoke test：`release-check`；以 2 MB JSON 對 `/api/auth/login` 應得 413。
- 回滾方式與資料相容性：可直接回滾至 v5.3.7 image；退役日期會回到舊算法，沒有儲存的值。

## Acceptance criteria

- [x] AC-1：Given 超過 1 MiB 的 JSON（有或沒有 Content-Length），When 送到任何 `/api/` 寫入路徑，Then 不經解析回 413 `too_large`；上傳路徑維持原上限；讀完內容後路由仍收到真正的中斷；最大的合法 AI 請求小於上限。
- [x] AC-2：Given 第一筆跑步在近 90 天內的鞋，When 讀跑鞋清單或單鞋分析，Then 月均以開穿天數（14～90 天）計算且兩處一致；更早開穿的鞋不變。
- [x] AC-3：Given 沒有注入 LLM 設定，When 使用模型，Then 不讀 `OPENROUTER_API_KEY`／`OR_MODEL` 環境變數並回報未設定金鑰。
- [x] AC-4：Given `templates/`、`css/` 或 `assets.json` 的路徑，When 瀏覽器請求，Then 回 shell 而不是原始檔；其他靜態檔照常提供。
- [x] AC-5：Given 一筆過期與一筆有效的還原預覽，When app 運作中，Then 過期的被清除、有效的保留。
- [x] AC-6：Given backend 原始碼，When 執行架構測試，Then 沒有互相匯入（含型別檢查用匯入）的模組。
- [x] AC-7：Given README 概覽的版本、規格、端點或測試數與 repo 不符，When 執行 `docs-check`，Then 具名失敗。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_transport_hardening.py::test_an_oversized_json_body_is_rejected_before_parsing`、`unit_tests/test_transport_hardening.py::test_reads_and_upload_routes_keep_their_own_rules`、`unit_tests/test_transport_hardening.py::test_a_chunked_json_body_without_content_length_is_counted`、`unit_tests/test_transport_hardening.py::test_after_the_body_the_route_waits_for_the_real_disconnect`、`unit_tests/test_transport_hardening.py::test_the_largest_valid_chat_request_fits_the_default_limit` |
| AC-2 | `unit_tests/test_forecasting.py::test_rate_window_starts_at_the_first_run_inside_90_days`、`unit_tests/test_forecasting.py::test_a_pair_first_worn_inside_the_window_is_averaged_over_its_days_in_use`、`unit_tests/test_forecasting.py::test_batch_forecast_is_scoped_bounded_and_matches_analysis` |
| AC-3 | `unit_tests/test_llm.py::test_an_unconfigured_adapter_never_reads_the_environment` |
| AC-4 | `unit_tests/test_transport_hardening.py::test_frontend_build_inputs_are_not_served` |
| AC-5 | `unit_tests/test_transport_hardening.py::test_expired_restore_previews_are_swept_while_the_app_runs` |
| AC-6 | `unit_tests/test_architecture_boundaries.py::test_backend_modules_have_no_import_cycle_even_for_type_checking` |
| AC-7 | `unit_tests/test_docs_harness.py::test_docs_harness_rejects_a_stale_overview`、`python3 scripts/task.py docs-check` |
