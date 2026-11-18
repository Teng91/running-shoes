# SPEC-071：公開站台的 AI 每日額度與防護補強

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-047](047-review-hardening-and-decoupling.md)、[SPEC-054](054-security-headers-and-page-csp.md)

## Problem

- 註冊是開放的（上限 100 個帳號）。AI 對話與月報只有每分鐘限額（每帳號 20、全站 120），沒有每日上限。任何人註冊後都能整天呼叫，消耗站長的 OpenRouter 額度。
- 正式站公開 Swagger UI（`/docs`）與 ReDoc（`/redoc`），提供可直接操作的 API 主控台。
- 回應沒有 `Strict-Transport-Security`，瀏覽器第一次仍可能先走 HTTP。

## Goals

- AI 請求（對話、月報產生）加上每帳號與全站的每日額度，可用環境變數調整。
- 正式站關閉 `/docs`、`/redoc`；開發環境保留。
- 每個回應都帶 HSTS。

## Non-goals

- 不關閉公開註冊、不改密碼規則（註冊與改密碼已要求至少 8 碼，登入失敗已有鎖定）。
- 不移除 `/openapi.json`：`release-check` 與 `smoke_test` 以它確認部署後的路由契約，而程式碼本來就公開。
- 不改 JWT 效期。

## Proposed design

- `rate_limits.enforce_agent_request_limits` 在既有的每分鐘視窗之外，同一交易再消耗 `agent-user-daily`（`AGENT_DAILY_LIMIT_PER_USER`，預設 50）與 `agent-global-daily`（`AGENT_GLOBAL_DAILY_LIMIT`，預設 200）兩個 24 小時固定視窗；任一視窗滿了整筆回滾、回 429 與 `Retry-After`。
- `RATE_LIMIT_BUCKET_RETENTION_SECONDS` 改為 24 小時，過期桶清理不會提早刪掉每日視窗；模型刷新冷卻上限另以 `MAX_MODEL_REFRESH_COOLDOWN_SECONDS`（3600）維持原本的上限。
- `create_app` 在 `settings.is_production` 時設定 `docs_url=None`、`redoc_url=None`；這些路徑回 JSON 404，不會落到 SPA。
- `SECURITY_HEADERS` 新增 `strict-transport-security: max-age=31536000; includeSubDomains`。

## Security and data isolation

- 每日額度以 user id 與全站為鍵，不讀其他帳號的資料；被拒絕的請求不會消耗任何視窗。
- HSTS 只在 HTTPS 下生效；Fly 已將 HTTP 301 轉到 HTTPS。

## Migration, rollout, and rollback

- Schema／資料 migration：無，沿用 `rate_limit_buckets`。
- 上線與 smoke test：`/docs`、`/redoc` 回 404，`/openapi.json` 仍可讀，回應帶 HSTS。
- 回滾方式與資料相容性：可直接回滾到 v4.19.0 image；舊版會在一小時後清掉每日桶。HSTS 已被瀏覽器記住一年，回滾不影響（站台本來就只走 HTTPS）。

## Acceptance criteria

- [x] AC-1：Given 每帳號每日額度 2，When 同一帳號第 3 次呼叫 AI，Then 回 429 且不呼叫模型；Given 全站每日額度已用完，When 任一帳號呼叫，Then 回 429 與超過一小時的 `Retry-After`。
- [x] AC-2：Given 每日視窗與模型刷新冷卻，When 清理過期限流桶，Then 每日視窗不會被提早刪除，冷卻上限仍是 3600 秒。
- [x] AC-3：Given 正式環境，When 讀取 `/docs` 或 `/redoc`，Then 回 JSON 404，`/openapi.json` 仍列出路由；開發環境仍可開啟。
- [x] AC-4：Given 任何回應，When 檢查標頭，Then 帶有 `Strict-Transport-Security`。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_api_extra.py::test_agent_daily_budget_caps_each_account_and_the_whole_site` |
| AC-2 | `unit_tests/test_security_config.py::test_rate_limit_windows_never_outlive_bucket_retention` |
| AC-3 | `unit_tests/test_app_factory.py::test_production_hides_the_interactive_api_console_but_keeps_the_contract` |
| AC-4 | `unit_tests/test_security_headers.py::test_every_response_kind_carries_the_hardening_headers` |
