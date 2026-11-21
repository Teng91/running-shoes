# SPEC-087：登入綁定帳號、Actions 釘選與瀏覽器儲存

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-075](075-invites-and-account-controls.md)、[SPEC-085](085-auth-hardening.md)、[SPEC-048](048-push-to-main-deploy-and-release.md)

## Problem

公開 repo 的檢查還留下兩個低風險資安問題與兩個小 bug：

- 登入 token 只記帳號名稱與 `token_version`。帳號刪除後，若有人用同一個名稱重新註冊，新帳號的 `token_version` 也從 0 開始；`users.id` 沒有 AUTOINCREMENT，最新的帳號被刪掉後連 id 都會沿用。被刪帳號的裝置上還沒過期的 token（最長 7 天）因此能直接進入新帳號。
- GitHub Actions 以版本標籤引用，包括第三方的 `superfly/flyctl-actions/setup-flyctl@1.5`。標籤可以被移動，被改掉的 action 會在拿得到 `FLY_API_TOKEN`、`BACKUP_PASSPHRASE` 的 job 裡執行。
- 瀏覽器封鎖網站資料時，任何 `localStorage` 存取都會丟出例外。`app-state.js` 與 `app-auth.js` 在最上層直接讀取，整個 script 中斷，頁面打不開。
- 所有 403 回應的 `error.code` 都是 `capacity`，連「Admin only」也是。畫面顯示的是 `detail`，前端沒有讀 `error.code`，使用者看不出差別。

## Goals

- 被刪帳號的 token 不能進入之後同名註冊的新帳號；現有登入不需要重新登入。
- 另一個 repository 的 action 一律釘選到 commit SHA，並註明版本。
- 瀏覽器封鎖網站資料時 app 仍能啟動，登入只保存在這個頁面的記憶體裡。
- 403 的 `error.code` 改為 `forbidden`。

## Non-goals

- 不新增資料表或欄位，不改 token 有效期。
- 不處理註冊時可以試出帳號名稱是否存在，也不新增「登出所有裝置」（另案）。
- 不改已經各自以 try/catch 保護的 `localStorage` 存取（主題、新帳號引導、Strava 日期範圍的讀取）。

## Proposed design

- `services/accounts.login` 的 token 多帶 `aid`＝`users.backup_id`。`backup_id` 在建立帳號時隨機產生、之後不會改變，也不會被別的帳號沿用。
- `auth.get_current_user` 在 `token_version` 檢查之後比對 `aid`：有 `aid` 但與帳號的 `backup_id` 不同時回 401 `Session expired; please log in again`。v4.24.2 以前簽發的 token 沒有 `aid`，照舊接受；它們最遲 7 天後到期，之後所有有效 token 都帶 `aid`。
- `.github/workflows/*.yml` 與 `.github/actions/browser-setup/action.yml` 的 `uses:` 改為 `owner/repo@<40 位 commit SHA> # vX.Y.Z`。釘選的就是原本主版本標籤目前指向的 commit，執行內容不變。既有的 Dependabot github-actions 設定會一併更新 SHA 與註解。
- `app-state.js` 新增 `readStoredValue`、`writeStoredValue`、`removeStoredValue`、`isLocalStorageEvent`，各自以 try/catch 包住。`app-auth.js` 的登入狀態、`app-state.js` 的主題偏好與 `app-strava.js` 寫入日期範圍改用這些函式。封鎖時讀到 `null`、寫入無效，登入保存在記憶體，重新整理後要再登入一次。
- `app_factory.http_exception_handler` 把 403 對應到 `forbidden`。註冊名額已滿同樣是 403，`error.code` 也從 `capacity` 變成 `forbidden`；`detail` 不變。

## Security and data isolation

- `aid` 是帳號自己的識別碼，只有持有 token 的本人看得到，帳號備份裡也有同一個值；不含其他帳號的資料，也不是秘密。token 仍以 app 的金鑰簽章，`aid` 不能被竄改。
- `aid` 不吻合時的回應和 `token_version` 不吻合時相同，不透露帳號曾被刪除。
- localStorage 被封鎖時，token 只存在頁面記憶體，不會改存到其他地方。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：部署前自動快照。部署後確認 `/health/ready`、shell v96，並用 `release-check` 匿名檢查；現有登入應維持有效。
- 回滾方式與資料相容性：可直接回滾至 v4.24.1 image；舊版會忽略 token 裡的 `aid`，新簽發的 token 照樣可用。

## Acceptance criteria

- [x] AC-1：Given 帳號被刪除後有人以同一名稱重新註冊（取得相同的 id 與 `token_version`），When 用被刪帳號的舊 token 呼叫 API，Then 回 401 `Session expired; please log in again`；新帳號重新登入後正常使用。
- [x] AC-2：Given 登入，Then token 的 `aid` 等於帳號的 `backup_id`；沒有 `aid` 的舊 token 仍然有效，`aid` 屬於其他帳號的 token 回 401。
- [x] AC-3：Given `.github` 下的 workflow 與 composite action，Then 每個來自其他 repository 的 action 都釘選到 40 位 commit SHA，並以註解標示版本。
- [x] AC-4：Given 瀏覽器在每次存取 `localStorage` 時丟出例外，When 載入 `app-lifecycle.js`、`app-state.js`、`app-auth.js`，Then 不中斷、尚未登入、主題跟隨系統；登入後 token 保存在記憶體，登出可清除；所有 script 裡的 `localStorage` 存取都包在 try 裡。
- [x] AC-5：Given 一般帳號呼叫管理員 API，Then 回 403，`error` 為 `{"code": "forbidden", "message": "Admin only"}`。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_invites_and_accounts.py::test_a_deleted_accounts_token_never_opens_a_new_account_with_the_same_name` |
| AC-2 | `unit_tests/test_invites_and_accounts.py::test_a_token_names_its_account_and_one_without_it_is_refused` |
| AC-3 | `unit_tests/test_deploy_workflow.py::test_every_action_from_another_repository_is_pinned_to_a_commit` |
| AC-4 | `unit_tests/frontend/reliability.test.cjs::SPEC-087 a browser that blocks site storage still starts and keeps the login in memory` |
| AC-5 | `unit_tests/test_invites_and_accounts.py::test_only_admins_reach_admin_routes_and_me_says_who_is_admin` |
