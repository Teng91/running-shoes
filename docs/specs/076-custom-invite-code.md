# SPEC-076：自訂邀請碼

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-075](075-invites-and-account-controls.md)

## Problem

- 註冊表單的邀請碼欄位提示寫著「例如 K7QM-3XPA」，看起來像一組真的邀請碼。
- 邀請碼只能自動產生 8 碼亂數，管理員想用好記的邀請碼（例如 `Teng91`）口頭告訴朋友。

## Goals

- 註冊表單提示改為「向管理員索取」，不顯示任何像邀請碼的字串。
- 管理員產生邀請碼時可以自訂 4～20 個英文字母或數字；留空仍自動產生。

## Non-goals

- 不改邀請碼的使用次數、天數上限與只存雜湊的做法。

## Proposed design

- `InviteCreate.code` 選填；`invites.create_invite` 正規化（去掉空白與符號、轉大寫）後檢查長度與 ASCII，重複時回 409。
- `redeem_invite` 接受 4～20 碼，自動產生的 8 碼與自訂碼共用同一個雜湊比對。
- 「資料與同步」的管理員面板新增「自訂邀請碼（選填）」欄位，並提醒自訂碼比較好猜。

## Security and data isolation

- 自訂碼同樣只存 SHA-256；比較好猜，所以面板提醒設定使用次數與天數。註冊仍受每個 IP 每分鐘 20 次的限制（SPEC-074）。

## Migration, rollout, and rollback

- Schema／資料 migration：無，schema 11 不變。
- 上線與 smoke test：註冊頁提示為「向管理員索取」；管理員可建立自訂邀請碼並用它註冊。
- 回滾方式與資料相容性：可直接回滾到 v4.20.0 image；已建立的自訂碼在舊版無法使用（舊版只接受 8 碼）。

## Acceptance criteria

- [x] AC-1：Given 管理員，When 建立 `Teng91`，Then 回傳 `TENG91`，不分大小寫與空白都能註冊，達到使用次數後拒絕；重複或格式不符時拒絕。
- [x] AC-2：Given 註冊表單，When 顯示邀請碼欄位，Then 不出現像真的邀請碼的提示；管理員面板送出修剪過的自訂碼並在成功後清空。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_invites_and_accounts.py::test_admin_can_choose_a_memorable_invite_code` |
| AC-2 | `unit_tests/frontend/account.test.cjs::SPEC-075 the sign-up form asks for an invite only when the server requires one`、`unit_tests/frontend/account.test.cjs::SPEC-075 only admins see the invite panel; codes are escaped and spent ones cannot be revoked` |
