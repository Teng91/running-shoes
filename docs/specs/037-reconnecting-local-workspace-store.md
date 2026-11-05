# SPEC-037：本機工作區資料庫自動重新連線

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-027](027-recoverable-account-workspace.md)、[SPEC-034](034-portable-recovery-and-sync-refresh.md)

## Problem

`frontend/app-local-store.js` 只在啟動時開一次 IndexedDB 連線。瀏覽器可能主動關閉仍在使用的連線
（WebKit／iOS Safari 在背景、記憶體壓力下，或收到 `versionchange`）；之後每次建立 transaction 都丟出
`InvalidStateError: The database connection is closing.`，離線待送跑步與草稿無法讀寫，直到重新整理頁面。

證據：修正 `waitForFunction` 不等待 async predicate 後，雙引擎 workspace E2E 真正檢查離線重啟恢復，
WebKit 於 main CI（run 41964533305）在離線重新整理後讀取佇列失敗，診斷輸出即為上述錯誤；
測試不會刪除資料庫或升級版本，連線由瀏覽器關閉。

## Goals

- 連線被關閉（含沒有 `close` 事件的情況）後，下一次本機讀寫自動重新開啟並成功。
- 只在 transaction 尚未建立、沒有任何資料動作時重試一次；應用程式驗證錯誤不重試。

## Non-goals

- 不重試 transaction 執行中途中止的讀寫；IndexedDB transaction 為原子操作，錯誤照舊回報。
- 不改資料庫名稱、版本、record 格式或佇列語義。

## Proposed design

- `openLocalWorkspaceStore()` 保存目前連線與進行中的 open promise；`close`／`versionchange` 事件只清除對應連線。
- `transaction()` 使用目前連線，若沒有則重新開啟；建立 transaction 時遇到 `InvalidStateError` 時丟棄該連線並重開、重試一次。
- 對外介面（`list`、`update`、`enqueue`、`move`、`clear`）不變；呼叫端不需修改。

## Security and data isolation

- 只影響瀏覽器內的本機資料庫連線；record 仍依帳號 partition，不含 token 或密碼。
- 不新增網路請求，也不讀取其他帳號資料。

## Migration, rollout, and rollback

- Schema／資料 migration：無；IndexedDB 版本維持 1，伺服器 schema 6 不變。
- 上線與 smoke test：前端 asset 4.0.3／shell v43；部署後執行匿名 `release-check`。
- 回滾方式與資料相容性：可回滾至 v4.0.2 image；本機 record 格式未變，舊版可直接讀取。

## Acceptance criteria

- [x] AC-1：Given 本機佇列已有待送跑步，When 瀏覽器關閉連線且沒有發出 `close` 事件，Then 下一次讀取自動重新開啟並讀到同一筆資料。
- [x] AC-2：Given 瀏覽器關閉連線並發出 `close` 事件，When 寫入，Then 先重新開啟再提交；應用程式驗證錯誤不觸發重新開啟或重試。
- [x] AC-3：Given 已安裝 PWA 離線重新整理，When 恢復本機工作區，Then 雙引擎 E2E 以真正 await 的 `waitForAsync` 等到帳號、跑鞋快取與待送佇列可讀取；瀏覽器測試不得把 async predicate 交給 `waitForFunction`。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/workspace.test.cjs::local workspace store reopens a connection the browser closed` |
| AC-2 | `unit_tests/frontend/workspace.test.cjs::local workspace store reopens a connection the browser closed` |
| AC-3 | `unit_tests/test_browser_harness.py::test_browser_waits_never_pass_async_predicates_to_wait_for_function`、`python3 scripts/task.py frontend-e2e` |
