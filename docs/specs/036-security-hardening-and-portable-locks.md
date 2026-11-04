# SPEC-036：安全強化與跨平台鎖定檔

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-021](021-auth-concurrency-and-release-asset-count.md)、[SPEC-002](002-cross-platform-task-runner.md)

## Problem

全專案檢查發現五個問題：

1. AI 回覆與月報的 Markdown 清理器先把未信任 HTML 指派給 live document 的元素 `innerHTML` 再清理；瀏覽器在清理前就會載入 `<img>`，`onerror` 因而可執行。模型輸出會受網路搜尋內容影響，token 又存於 `localStorage`，可導致帳號被接管。
2. 驗證與 AI 限流先扣全站額度才檢查單一 IP／帳號；已超過自身上限的單一來源仍持續消耗全站額度，可讓所有人無法登入或使用 AI。
3. 密碼最短 4 字元、同 IP 每分鐘可嘗試 120 次，且不存在的帳號不執行 bcrypt，回應時間可推知帳號是否存在。
4. 非預期的模型例外訊息原文傳給瀏覽器。
5. `requirements*.txt` 只在 Linux 編譯，`uvloop` 缺少平台條件、pytest 在 Windows 需要的 `colorama` 未鎖定，Windows 執行 `task.py setup` 失敗。

## Goals

- 未信任 Markdown 只在 inert document 解析，標籤與屬性皆使用 allowlist。
- 被自身上限拒絕的請求不消耗全站共享額度。
- 新密碼至少 8 字元；同一帳號 15 分鐘內密碼錯誤 10 次後暫停該帳號的登入與改密碼；不存在帳號也執行一次 bcrypt。
- 模型例外只記錄於伺服器 log，串流只顯示通用訊息。
- 鎖定檔以 universal 模式編譯，Windows／macOS／Linux 皆可 `--require-hashes` 安裝。

## Non-goals

- 不強制既有短密碼帳號改密碼；只限制新註冊與改密碼。
- 不改 Strava 活動日期的時區解讀；需先以真實匯出檔確認時區後另案處理。
- 不加入 Content-Security-Policy；現有 inline handler 需先移除。

## Proposed design

- `frontend/app-markdown.js` 以 `DOMParser` 解析，移除非 allowlist 標籤與 `href`、`title`、`colspan`、`rowspan`、`align`、`start` 以外的屬性；連結僅允許 http(s) 並加上 `rel="noopener noreferrer"`。
- `backend/rate_limits.py` 新增唯讀檢查，先確認 IP／帳號視窗未滿，再依原順序扣全站與個別額度；全站飽和時仍不建立新的 IP bucket。
- 新增共享 `auth-user-failure` bucket：登入或改密碼回 401 才記錄；達上限時回 429 與 `Retry-After`。
- `backend/services/accounts.py` 以 `MIN_PASSWORD_LENGTH = 8` 檢查，未知帳號比對快取的假 hash。
- 鎖定檔改以 `uv pip compile --universal --generate-hashes` 產生，版本不變，只新增平台條件與 Windows 專用依賴。

## Security and data isolation

- 失敗計數以使用者名稱為 key，不讀取或回傳其他帳號資料；回應不區分帳號是否存在。
- 帳號暫停可能被他人觸發 15 分鐘；這是限制線上猜密碼的取捨，不影響其他帳號。
- 模型例外細節只寫入伺服器 log，不進入 SSE。

## Migration, rollout, and rollback

- Schema／資料 migration：無；沿用既有 `rate_limit_buckets`，schema 6 不變。
- 上線與 smoke test：部署後執行匿名 `release-check`；確認 asset 4.0.1／shell v42。
- 回滾方式與資料相容性：可回滾至 v4.0.0 image；新增的 `auth-user-failure` bucket 會被舊版忽略並由既有清理移除。

## Acceptance criteria

- [x] AC-1：Given Markdown 含 `<img onerror>`、`<svg><script>`、`javascript:` 連結與 `id`／`class`／`style`，When 渲染，Then 解析不經過 live document，輸出不含任何可執行標記或非 allowlist 屬性，http(s) 連結保留。
- [x] AC-2：Given 單一 IP 或帳號已達自身上限，When 持續送出驗證或 AI 請求，Then 回 429 且全站計數不增加，其他來源仍可使用。
- [x] AC-3：Given 同一帳號連續密碼錯誤達上限，When 以正確密碼登入或改密碼，Then 回 429 與大於 60 秒的 `Retry-After`，其他帳號不受影響；未知帳號仍執行一次密碼比對；少於 8 字元的新密碼回 400。
- [x] AC-4：Given 模型串流丟出非預期例外，When 回傳錯誤事件，Then 不含例外原文。
- [x] AC-5：Given Windows 或 POSIX 平台，When 以 `--require-hashes` 安裝鎖定檔，Then `uvloop` 只在非 Windows 安裝且 `colorama` 已鎖定於 Windows。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/streams-rendering.test.cjs::markdown sanitizer parses untrusted HTML in an inert document and allowlists attributes` |
| AC-2 | `unit_tests/test_api_extra.py::test_throttled_client_does_not_consume_global_auth_budget`、`unit_tests/test_api_extra.py::test_throttled_account_does_not_consume_global_agent_budget` |
| AC-3 | `unit_tests/test_api_extra.py::test_repeated_password_failures_lock_only_that_account`、`unit_tests/test_api_extra.py::test_unknown_username_still_runs_a_password_hash_check`、`unit_tests/test_api.py::test_register_requires_eight_character_passwords` |
| AC-4 | `unit_tests/test_agent.py::test_model_errors_are_reported_and_stream_finishes` |
| AC-5 | `unit_tests/test_lockfiles.py::test_posix_only_wheels_are_excluded_on_windows`、`unit_tests/test_lockfiles.py::test_windows_only_dependencies_are_hash_locked` |
