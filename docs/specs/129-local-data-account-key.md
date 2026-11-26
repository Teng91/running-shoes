# SPEC-129：本機資料依帳號識別碼分區

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-027](027-recoverable-account-workspace.md)、[SPEC-087](087-session-binding-and-hardening.md)、[SPEC-093](093-project-review-hardening.md)

## Problem

- 伺服器比對帳號名稱不分 A–Z 大小寫（SPEC-093），但瀏覽器把登入時輸入的名稱直接當作身分：IndexedDB 工作區的分區是 `origin|輸入的名稱`，Strava 日期區間與 AI 對話也用這個名稱。用 `runner` 離線存了跑步，之後打 `Runner` 登入，待送跑步與草稿都讀不到，看起來像資料不見。
- 後端把刪除後重新註冊的同名帳號視為不同帳號（token 的 `aid`，SPEC-087），但瀏覽器分區只有名稱：同一台裝置上新的同名帳號會讀到舊帳號的草稿與待送跑步（待送跑步送出時會因鞋款不屬於新帳號被拒絕，但草稿會出現）。

## Goals

- 本機工作區依帳號永久識別碼（`backup_id`）分區；大小寫不同或重新註冊的同名帳號不再混用。
- 登入後的名稱用伺服器的寫法，讓其他以名稱為 key 的偏好一致。
- 已經用各種大小寫存下的本機資料第一次開啟時併入，不會遺失。

## Non-goals

- 不改變後端 API 或 token 格式；token 已帶 `sub` 與 `aid`。
- 不分辨升級前的舊分區是否來自已刪除的同名帳號（無從得知）。

## Proposed design

- `app-session.js` 新增只在檔內使用的 `authTokenClaims(token)`，解析 token 內容但不驗證簽章（簽章由伺服器驗證）。`startAuthSession` 以 `sub` 作為 `currentUser` 並寫入儲存；`captureAuthSession()` 回傳的物件多了 `account`（`aid`），沒有時為 null。
- `app-workspace.js` 的分區為 `origin|aid:<aid>`；沒有 `aid` 時沿用 `origin|名稱`。啟用時把「同網站、名稱只差 A–Z 大小寫、且不是 `aid:` 分區」的舊分區交給 controller 併入。
- `workspace-controller.attach(account, isLegacy)` 先呼叫 storage 的 `adopt(account, isLegacy)`；`app-local-store.adopt` 在一個 readwrite 交易內把舊紀錄改寫到新分區並刪除舊紀錄，新分區已有同 key 的紀錄時保留新的，lease 欄位隨紀錄移動。

## Security and data isolation

- 只讀取伺服器簽發給目前使用者的 token；解析結果只用於本機分區與顯示，不作為授權依據，伺服器仍以簽章、`token_version` 與 `aid` 驗證每個請求。
- 併入只限同一網站且名稱相同（A–Z 不分大小寫）的分區，其他帳號或其他網站的分區不會被移動。

## Migration, rollout, and rollback

- Schema／資料 migration：無；瀏覽器端在第一次開啟時一次性併入舊分區。
- 上線與 smoke test：以不同大小寫登入同一帳號，草稿與待送跑步仍在。
- 回滾方式與資料相容性：回滾 v5.2.0 後，舊版讀 `origin|名稱` 分區，看不到這版之後存在 `aid:` 分區的資料；資料仍留在 IndexedDB，升回即可看到。

## Acceptance criteria

- [x] AC-1：Given 伺服器簽發的 token，When 登入，Then 名稱是 token 的 `sub`，session 帶出 `aid`；無法解析的 token 保留輸入的名稱、`account` 為 null。
- [x] AC-2：Given 已登入的帳號，When 開啟本機工作區，Then 分區是 `origin|aid:<aid>`，只併入同網站且名稱只差 A–Z 大小寫的舊分區，不併入其他帳號識別碼或其他網站。
- [x] AC-3：Given 舊分區與新分區都有紀錄，When 併入，Then 在一個交易內完成、新分區的紀錄優先、lease 保留，再次併入不移動任何紀錄。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/workspace.test.cjs::SPEC-129 the session takes the server spelling of the name and the permanent account ID from the token` |
| AC-2 | `unit_tests/frontend/workspace.test.cjs::SPEC-129 the workspace partition is the account ID and adopts any spelling of the same name once` |
| AC-3 | `unit_tests/frontend/workspace.test.cjs::SPEC-129 the IndexedDB store adopts legacy partitions in one transaction` |
