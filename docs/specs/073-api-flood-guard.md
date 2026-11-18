# SPEC-073：被大量請求灌爆時的防護

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-071](071-public-site-hardening.md)、[SPEC-054](054-security-headers-and-page-csp.md)

## Problem

- 只有登入、註冊、AI 與備份預覽有頻率限制。其他 API 沒有每個位址的上限；未登入的請求雖然很快回 401，大量灌入仍會吃掉唯一一台 256 MB 機器的 CPU。
- `fly.toml` 沒有同時請求上限，湧入的請求會全部送進機器，可能把記憶體用完。

## Goals

- 每個 `/api/` 請求在驗證、資料庫與路由之前先檢查每個位址每分鐘的上限（預設 600，`API_RATE_LIMIT_PER_MINUTE`）。
- Fly 代理層限制同時請求數，超過時由 Fly 排隊或拒絕。

## Non-goals

- 不防大規模分散式 DDoS（需要前置 CDN 與自有網域）。
- 不限制靜態檔、首頁與健康檢查。
- 不改既有 SQLite 限流視窗。

## Proposed design

- `middleware.ApiRequestLimiter`：記憶體內每位址 60 秒固定視窗，最多追蹤 10,000 個位址，超過時先丟掉最舊的；不寫 SQLite，避免灌爆時每個請求都佔用唯一的 writer。正式站只有一個 Uvicorn 程序，重新啟動就是新的一分鐘。
- `middleware.ApiRateLimitMiddleware` 掛在安全標頭與 request ID 內側、上傳大小限制外側；超過上限回 429、`Retry-After` 與 `error.code = "rate_limited"`。位址判斷和 SQLite 限流共用 `client_address`（只在 Fly 上信任 `Fly-Client-IP`）。
- `fly.toml` 的 `[http_service.concurrency]`：`type = "requests"`、`soft_limit = 25`、`hard_limit = 50`。

## Security and data isolation

- 被拒絕的請求不讀取任何帳號資料，也不碰資料庫。
- 偽造大量來源位址只會讓最舊的視窗被丟掉，記憶體有上限。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：`release-check` 通過；正常使用不會碰到 429。
- 回滾方式與資料相容性：可直接回滾到 v4.19.2 image；`fly.toml` 的 concurrency 隨部署更新。

## Acceptance criteria

- [x] AC-1：Given 每位址上限 3，When 同一位址第 4 次呼叫任一 API（即使帶有效 token），Then 回 429 與安全標頭；其他位址與健康檢查不受影響。
- [x] AC-2：Given 記憶體限流器，When 視窗過了 60 秒或追蹤的位址超過上限，Then 視窗重新計算、最舊的位址先被丟掉。
- [x] AC-3：Given `fly.toml`，When 部署，Then 設有以請求計算的同時上限。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_api_extra.py::test_every_api_route_has_a_per_address_budget_before_any_work` |
| AC-2 | `unit_tests/test_security_config.py::test_api_request_limiter_resets_each_minute_and_stays_bounded` |
| AC-3 | `unit_tests/test_security_config.py::test_fly_caps_concurrent_requests_on_the_single_small_machine` |
