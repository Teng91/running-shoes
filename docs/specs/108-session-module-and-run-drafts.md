# SPEC-108：登入身分獨立成 `app-session.js`，跑步草稿向工作區登記，前端不再有互相引用

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-106](106-resource-cache-hooks.md)、[SPEC-107](107-workspace-form-adapters.md)

## Problem

SPEC-107 之後前端還有 7 對互相使用的 script：

- 6 對都繞著 `app-auth.js`：登入身分（`authToken`、`currentUser`、世代與 `captureAuthSession()` 等）定義在 auth 裡，transport、生命週期、殼層、AI 對話、工作區與帳號都依賴它；auth 又反過來呼叫它們（401 時 `app-api.js` 直接呼叫 `clearAuth()`／`showLoginView()`，auth 直接呼叫工作區的 `persistWorkspaceDrafts()`／`activateLocalWorkspace()` 與帳號的 `refreshAdminEntry()`／`loadRegistrationMode()`）。
- `app-runs.js` ↔ `app-workspace.js`：工作區直接讀寫 `runController`、所選月份、跑鞋清單與跑步編輯表單。

## Goals

- 新 script `app-session.js`（緊接在 `app-state.js` 之後載入）擁有登入身分：`authToken`、`currentUser`、`authGeneration`、`captureAuthSession()`、`isCurrentAuthSession()`、`requireAuthSession()`。`app-auth.js` 只負責登入表單與帳號切換。
- 401 時 `app-api.js` 發出 window 事件 `auth-session-expired`，由 `app-auth.js` 監聽並登出；兩邊都不呼叫對方的函式。
- `app-auth.js` 提供 `onAuthView({ sessionEnding, appShown, registerShown })`：工作區在 session 結束前保存草稿、在畫面打開時連上本機工作區；帳號在畫面打開時更新管理入口、在註冊表單打開時讀取註冊模式。
- 工作區提供 `registerWorkspaceRuns({ month, applyCachedPage, shoes, formRestored })`；跑步編輯以 SPEC-107 的 `registerWorkspaceEditor('run', { capture, resume, restored })` 登記。工作區不再提到任何跑步函式。
- 互相使用的 script 由 7 對降到 0 對，跨 script 名稱由 241 降到 240；行為不變。

## Non-goals

- 不改 API、登入流程、草稿格式或離線佇列的行為。

## Proposed design

- 載入順序符合 SPEC-106：`app-session.js` 在所有使用者之前；`onAuthView` 定義在 `app-auth.js`（第 6 個載入），工作區與帳號在它之後才登記；`registerWorkspaceRuns` 定義在工作區，跑步在它之後登記。
- `auth-session-expired` 以同步的 `dispatchEvent` 送出，監聽者在回傳前就完成登出，與之前直接呼叫的時序相同；401 錯誤之後照常拋出。
- 同一事件的 hook 依登記順序執行：工作區先於帳號，與之前 `showAppView()` 內的呼叫順序相同。擷取編輯草稿時先問跑步、再問鞋款（兩個視窗不會同時開著）。

## Security and data isolation

- 身分只搬家，不改內容：token 仍只存在這個網站的 storage 與記憶體，每次登入／登出都推進世代，舊 session 的工作仍會被拒絕；401 仍會立即登出並清除草稿以外的帳號狀態。

## Migration, rollout, and rollback

- Schema／資料 migration：無（schema 13 不變，本機草稿格式不變）。
- 上線與 smoke test：Asset 4.29.6／shell v112（新 script 加入預先快取）；部署前自動快照，部署後 `release-check`。
- 回滾方式與資料相容性：可直接回滾至 v4.29.5 image。

## Acceptance criteria

- [x] AC-1：Given 已登入的請求收到 401，Then 透過 `auth-session-expired` 登出並顯示登入畫面，錯誤訊息照常拋出；同 token 的新 session 不受舊回應影響。
- [x] AC-2：Given 開啟中的跑步編輯，Then 存成 `run:<id>` 草稿，繼續編輯時由跑步登記重新打開、填回草稿值並更新運動類型提示；快取的跑步頁面只套用到目前顯示的月份。
- [x] AC-3：Given session 結束、畫面打開與註冊表單打開，Then 依序保存草稿、連上工作區、更新管理入口、讀取註冊模式；auth、工作區與 transport 的原始碼不再提到彼此的函式。
- [x] AC-4：Given 目前的前端，Then architecture-check 的基準為 240 個名稱、0 對，載入順序檢查通過；封鎖 storage 的瀏覽器仍能啟動並在記憶體保留登入。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/goals-transport.test.cjs::current 401 expires login, but an identical token from a new session is protected`、`unit_tests/frontend/reliability.test.cjs::SPEC-019 transient GETs retry once but writes and 401 never retry` |
| AC-2 | `unit_tests/frontend/workspace.test.cjs::SPEC-108 runs and sign-in hooks reach the workspace only through registrations` |
| AC-3 | `unit_tests/frontend/workspace.test.cjs::SPEC-108 runs and sign-in hooks reach the workspace only through registrations` |
| AC-4 | `unit_tests/test_architecture_boundaries.py::test_frontend_coupling_matches_the_recorded_ratchet`、`unit_tests/frontend/reliability.test.cjs::SPEC-087 a browser that blocks site storage still starts and keeps the login in memory`、`python3 scripts/task.py frontend-e2e` |
