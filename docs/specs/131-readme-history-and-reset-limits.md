# SPEC-131：補齊 README 開發歷程，重設密碼次數依帳號比對規則分組

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-085](085-auth-hardening.md)、[SPEC-130](130-review-findings.md)

## Problem

- README 的「開發歷程」停在 v5.0，沒有 v5.1～v5.2 的備份含目標賽事、目標賽事復原、課表排版模組、本機資料依帳號識別碼分區與程式碼檢查修正。
- 重設密碼的嘗試次數限制，對不存在的帳號以 `casefold()` 分組，但帳號查詢只轉 A–Z 小寫（SPEC-093、SPEC-130）。查詢視為不同名稱的 `Ärger` 與 `ärger` 會共用一份次數，和查詢規則不一致。

## Goals

- README 開發歷程包含目前的版本。
- 不存在的名稱依帳號查詢的規則分組（名稱只轉 A–Z 小寫、email 轉小寫），存在的帳號仍以帳號 ID 分組。

## Non-goals

- 不改變次數上限或時間窗；不改變回應內容，仍不透露帳號是否存在。

## Proposed design

- README「開發歷程」新增 v5.1–5.2 一列。
- `email_codes.attempt_key()`：帳號存在時為 `user:<id>`；不存在時，含 `@` 的值轉小寫，其他用 `accounts.username_key()`。

## Security and data isolation

- 只影響限流分組；帳號存在時的分組不變，所以名稱與 email 仍共用同一帳號的上限。

## Migration, rollout, and rollback

- Schema／資料 migration：無；既有限流桶會在時間窗結束後自然過期。
- 上線與 smoke test：忘記密碼照常回應。
- 回滾方式與資料相容性：直接回滾 v5.2.2 image。

## Acceptance criteria

- [x] AC-1：Given 不存在的名稱或 email，When 計算次數限制的分組，Then 名稱只忽略 A–Z 大小寫與頭尾空白，email 忽略大小寫。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_review_findings.py::test_unknown_reset_identifiers_share_a_budget_like_the_lookup` |
