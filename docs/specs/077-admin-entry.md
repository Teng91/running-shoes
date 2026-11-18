# SPEC-077：側邊欄的邀請碼管理入口

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-075](075-invites-and-account-controls.md)、[SPEC-076](076-custom-invite-code.md)

## Problem

- 管理員面板藏在「資料與同步」視窗最下面的摺疊區塊，管理員找不到邀請碼要在哪裡管理。

## Goals

- 側邊欄「資料與同步」旁邊新增「邀請碼管理」按鈕，只有管理員看得到。
- 點按後開啟獨立的「邀請碼管理」視窗：產生（含自訂邀請碼）、清單與停用、幫忙重設密碼。

## Non-goals

- 不改邀請碼與臨時密碼的 API 或規則。

## Proposed design

- `templates/admin-modal.html`：原本在 `workspace-modal.html` 的管理員內容移到這個視窗。
- `app-account.refreshAdminEntry()` 在 `showAppView` 時讀 `/auth/me`，先隱藏按鈕，只有 `is_admin` 才顯示；換帳號時重新判斷。
- `openAdminModal()` 開啟視窗並載入清單；`closeAdminModal()` 關閉時清掉畫面上的邀請碼與臨時密碼。Esc／焦點由 `app-dialogs.js` 管理。

## Security and data isolation

- 按鈕只是入口，權限仍由後端 `require_admin` 判斷；非管理員就算打開視窗也無法讀寫。
- 一次性的邀請碼與臨時密碼在關閉視窗時清除。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：管理員帳號的側邊欄出現「邀請碼管理」，一般帳號沒有。
- 回滾方式與資料相容性：可直接回滾到 v4.20.1 image。

## Acceptance criteria

- [x] AC-1：Given 一般帳號，When 進入 App，Then 側邊欄沒有「邀請碼管理」；Given 管理員，Then 顯示並可開啟視窗載入清單。
- [x] AC-2：Given 視窗顯示過邀請碼或臨時密碼，When 關閉，Then 畫面上的這些內容被清除。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/account.test.cjs::SPEC-075 only admins see the invite panel; codes are escaped and spent ones cannot be revoked` |
| AC-2 | `unit_tests/frontend/account.test.cjs::SPEC-075 only admins see the invite panel; codes are escaped and spent ones cannot be revoked` |
