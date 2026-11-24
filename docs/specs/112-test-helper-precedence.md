# SPEC-112：前端測試傳入的替身優先於共用輔助函式

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-101](101-panel-registry.md)、[SPEC-107](107-workspace-form-adapters.md)、[SPEC-108](108-session-module-and-run-drafts.md)

## Problem

前端 Node 測試以 `featureContext()` 建立執行環境：先放入測試傳入的全域值，再載入一組共用的真實函式（`readForm`、`prepareGoalForm`、`setGoalField`、`updateRunActivityHint`、`formatRunDuration`、`getFormDraft` 等）。測試傳入的替身因此被真實函式蓋掉，SPEC-101、SPEC-107、SPEC-108 的三個測試都必須在建立後再覆寫一次，否則會默默測到真實函式；SPEC-108 的測試還自己寫了一份從原始碼擷取函式的程式，與共用的 `extract()` 重複。

## Goals

- `featureContext()` 在安裝完共用函式後，把測試傳入的值放回去：測試傳入的替身一律優先，沒有傳入的仍是真實的共用函式。
- 移除三個測試的事後覆寫，替身直接寫在建立參數裡；SPEC-108 測試改用共用的 `extract()`。
- 新增測試確認優先順序。

## Non-goals

- 不改任何產品程式碼；不改測試涵蓋的行為。

## Proposed design

- 比對每個傳入的名稱，若被共用安裝換掉就放回原值；以函式宣告建立的全域綁定在 vm context 裡可以直接替換，呼叫端會解析到替身。

## Security and data isolation

- 只影響測試輔助程式。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：只改測試，正式站不變；記在 CHANGELOG 的 Unreleased。
- 回滾方式與資料相容性：還原本次 commit 即可。

## Acceptance criteria

- [x] AC-1：Given 測試傳入 `prepareGoalForm`、`updateRunActivityHint`、`getFormDraft`、`readForm` 替身，Then 環境裡就是這些替身；沒有傳入的共用函式仍是真實的。
- [x] AC-2：Given 移除事後覆寫的三個測試，Then 全部通過。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/streams-rendering.test.cjs::SPEC-112 what a test passes in wins over the shared helpers the feature context installs` |
| AC-2 | `unit_tests/frontend/workspace.test.cjs::SPEC-107 the goal form, shoe editor and account view register their workspace drafts`、`unit_tests/frontend/workspace.test.cjs::SPEC-108 runs and sign-in hooks reach the workspace only through registrations`、`unit_tests/frontend/streams-rendering.test.cjs::SPEC-101 features register their panels and data in script order; the shell names none of them` |
