# SPEC-080：移除登入頁的更改密碼

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-079](079-email-recovery.md)、[SPEC-075](075-invites-and-account-controls.md)

## Problem

- 登入頁仍有「更改密碼」表單（輸入帳號、舊密碼、新密碼），和新的「忘記密碼？」並排，容易混淆；忘記密碼已改由 email 驗證碼處理。
- 管理員的臨時密碼流程仍需要「登入後換掉密碼」的地方。
- 公開的 README 範例路徑含站長的本機帳號名稱。

## Goals

- 登入頁只留登入、註冊與「忘記密碼？」。
- 知道目前密碼時，在登入後的「資料與同步」→「更改密碼」更改；更改後所有裝置重新登入。
- README 範例路徑改成通用的 `~/.local/share/...`。

## Non-goals

- 不改 `POST /api/auth/change-password` 的 API 與規則。

## Proposed design

- 移除 `templates/index.html` 的 `change-form` 與連結，`app-auth.js` 的 `showChangeForm`／`handleChangePassword`，以及相關 data action。
- `workspace-modal.html` 新增「更改密碼」區塊；`app-account.changePassword()` 以目前帳號呼叫既有 API（不帶 token，打錯目前密碼的 401 不會被當成登入過期）。成功後關閉視窗、登出並提示用新密碼登入。
- 管理員臨時密碼的說明指向新位置；版面測試改為檢查「忘記密碼」表單。

## Security and data isolation

- API 仍要求帳號與目前密碼，失敗次數計入登入鎖定；只能改自己的帳號（前端帶入目前登入的帳號）。

## Migration, rollout, and rollback

- Schema／資料 migration：無，schema 12 不變。
- 上線與 smoke test：登入頁沒有「更改密碼」；「資料與同步」可更改密碼。
- 回滾方式與資料相容性：可直接回滾到 v4.21.0 image。

## Acceptance criteria

- [x] AC-1：Given 登入頁，When 顯示，Then 沒有更改密碼表單；「資料與同步」有更改密碼區塊。
- [x] AC-2：Given 登入後更改密碼，When 目前密碼錯誤，Then 顯示錯誤且不登出；正確時清空欄位、關閉視窗並登出提示重新登入。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/account-email.test.cjs::SPEC-080 the login page has no change-password form; signed-in users change it in「資料與同步」` |
| AC-2 | `unit_tests/frontend/account-email.test.cjs::SPEC-080 the login page has no change-password form; signed-in users change it in「資料與同步」` |
