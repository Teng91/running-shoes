# SPEC-088：登出所有裝置與註冊不洩漏帳號名稱

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-075](075-invites-and-account-controls.md)、[SPEC-087](087-session-binding-and-hardening.md)

## Problem

- 手機遺失或懷疑別人登入過時，唯一能讓其他裝置失效的方法是更改密碼；不想換密碼的人沒有辦法。
- 邀請制下，註冊先檢查名稱，再檢查邀請碼。沒有邀請碼的人送出任意邀請碼，就能從「Username already registered」與「Invalid invite code」的差別試出哪些名稱已經有人用。

## Goals

- 「資料與同步」可以登出所有裝置（包括這一台），密碼不變。
- 邀請制下，沒有有效邀請碼時，不論名稱是否被使用都回 `Invalid invite code`。

## Non-goals

- 不提供只登出某一台裝置或列出登入中的裝置；token 沒有逐一記錄。
- open 模式本來就能註冊，仍會回答名稱已被使用。

## Proposed design

- `services/accounts.logout_everywhere(db, user)`：在帳號的寫入交易裡把 `token_version` 加 1，回 `{"ok": true}`；`POST /api/auth/logout-all` 需要登入。所有舊 token 在下一次請求回 401 `Session expired; please log in again`，和改密碼後相同。
- 前端在「資料與同步」新增「登出所有裝置」區塊：確認後呼叫 API，成功才清除這台的登入並回到登入頁，顯示「已登出所有裝置，請重新登入。」；失敗時留在原畫面並顯示原因。
- `services/accounts.register`：邀請制下先在同一個寫入交易裡兌換邀請碼，再檢查名稱、管理員名稱與名額；任何一項被拒都會回滾，邀請碼不會被用掉。

## Security and data isolation

- 只修改登入者自己的 `token_version`；不新增欄位、不讀其他帳號。
- 有效邀請碼的持有者仍能知道名稱是否被使用，這是註冊本身必須告訴他的事。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：部署前自動快照；部署後 `release-check`，確認 `/api/auth/logout-all` 未登入時回 401。
- 回滾方式與資料相容性：可直接回滾至 v4.24.2 image；舊版沒有這個 API，前端的按鈕會顯示失敗訊息，不影響登入。

## Acceptance criteria

- [x] AC-1：Given 兩台裝置登入同一帳號，When 其中一台登出所有裝置，Then 兩台的 token 都回 401，原密碼可以重新登入；未登入時呼叫回 401。
- [x] AC-2：Given 前端，When 取消確認，Then 不送請求；請求失敗時保留登入並顯示原因；成功後關閉視窗、清除登入、回到登入頁並說明。
- [x] AC-3：Given 邀請制，When 用無效邀請碼註冊已存在或不存在的名稱，Then 都回 `Invalid invite code`；有效邀請碼註冊已存在的名稱回 `Username already registered` 且邀請碼未被使用。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_invites_and_accounts.py::test_logging_out_everywhere_ends_every_session_and_keeps_the_password` |
| AC-2 | `unit_tests/frontend/account.test.cjs::SPEC-088 logging out everywhere asks first and signs this device out only after the server confirms` |
| AC-3 | `unit_tests/test_invites_and_accounts.py::test_without_a_valid_invite_sign_up_does_not_reveal_taken_names` |
