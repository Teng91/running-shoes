# SPEC-081：公開 repo 的個人資料清理

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-071](071-public-site-hardening.md)、[SPEC-080](080-account-cleanup.md)

## Problem

- repo 公開後，目前版本仍含站長的個人資料：範例資料是真實的鞋款、尺寸、購買日期、價格與 2023 年起的月跑量；管理員畫面與測試用了朋友的真實帳號名稱；舊規格含本機帳號名稱的路徑；文件與測試引用真實的跑步總計與單鞋里程。

## Goals

- 範例資料（`SEED_DATA`）改成虛構的鞋款與月跑量。
- 畫面提示與測試不再出現朋友的帳號名稱。
- 文件、測試與程式註解的真實數字改成性質相同的虛構例子（例如捨去規則仍用「四捨五入會多 0.1」的數字）。

## Non-goals

- 不改寫 git 歷史：`main` 受保護、不允許 force push，而這些資料敏感度低；舊 commit 仍看得到。
- 不改功能、API 或資料庫。

## Proposed design

- `backend/seeding.py`：8 雙虛構鞋（統一 `us10/28cm`、整數價格）與 2024-06～2026-06 依公式產生的虛構月跑量。
- 共用測試資料（`unit_tests/conftest.py`）改成虛構的價格、尺寸與月跑量，相關斷言同步更新。
- 管理員備註提示改為「例如：給跑友」，鞋款尺寸提示改為 `us10/28cm`。
- CHANGELOG、版本說明、規格與 README 的真實總計、單鞋里程與鞋名改成通用例子。

## Security and data isolation

- 只改文字與測試資料；正式站資料不受影響。

## Migration, rollout, and rollback

- Schema／資料 migration：無；只有啟用 `SEED_DATA=true` 的新資料庫會用到新的範例資料。
- 上線與 smoke test：`release-check` 通過；管理員備註提示不含真實帳號。
- 回滾方式與資料相容性：可直接回滾到 v4.21.1 image。

## Acceptance criteria

- [x] AC-1：Given `SEED_DATA=true`，When 建立範例資料，Then 是 8 雙虛構鞋（6 雙現役、2 雙退役）與 25 個月的虛構月跑量。
- [x] AC-2：Given 目前版本的 repo，When 搜尋朋友的帳號、本機帳號路徑與真實總計，Then 找不到；相關測試以虛構數字驗證同樣的規則。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_migrations.py::test_seed_creates_joy_and_default_data` |
| AC-2 | `unit_tests/frontend/trends.test.cjs::SPEC-068 shoe mileage is truncated to one decimal exactly like Strava` |
