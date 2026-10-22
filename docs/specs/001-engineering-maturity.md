# SPEC-001：工程成熟度與可恢復性

- 狀態：Implemented
- Owner：Repository maintainer
- 關聯 ADR：ADR-0001

## Problem

專案已有測試與初步模組邊界，但正式 SQLite 備份／還原、部署 readiness、feature spec 流程，
以及 shoes/runs 路由邊界仍不足。單靠文件不能防止新 endpoint 回到 `main.py` 或 API contract 漂移。

## Goals

- 提供經 SQLite backup API 建立、具 checksum、integrity check 與保留策略的備份工具。
- 提供明確確認與 pre-restore snapshot 的安全還原流程。
- 提供 liveness、readiness、request ID 與部署後 smoke test。
- 將 shoes、runs 與 mileage transaction 拆成 router/service。
- 讓 CI 檢查依賴方向、API contract、coverage 與規格文件。
- 再拆分前端跑步與鞋款模組，維持功能與 PWA cache 行為。

## Non-goals

- 不自動連線或修改正式 Fly volume。
- 不導入微服務、外部監控 SaaS 或前端框架。
- 不改變既有 API payload、帳號資料或使用方式。

## Proposed design

保留單一 FastAPI／SQLite 部署，抽離 feature routers 與 mileage service；備份與唯讀 smoke 由 operator scripts 執行。

## Security and data isolation

- 備份檔權限設為 owner-only，工具不輸出資料內容。
- readiness 不回傳帳號、路徑或錯誤細節。
- router 和 mileage service 的查詢／更新維持 `user_id` 條件。
- request log 不記錄 body、Authorization header 或 query secret。

## Migration, rollout, and rollback

- 啟動 migration 寫入 schema version；舊的 idempotent migration 行為保留。
- 上線前建立資料庫快照；上線後執行 `scripts/smoke_test.py`。
- 程式可回滾；若要還原資料庫，必須停寫、驗證 backup 並輸入 `RESTORE`，工具會先保存現況。

## Acceptance criteria

- [x] Backup create/verify/retention/restore 具確定性測試。
- [x] `/health/live` 與 `/health/ready` 可供 container/Fly probes 使用。
- [x] 每個 HTTP response 都有安全的 `X-Request-ID`。
- [x] shoes/runs API 路徑與回傳 contract 不變。
- [x] 新 endpoint 不能默默增加到 `backend/main.py`。
- [x] Feature spec、ADR、測試與 PR checklist 可互相追蹤。

## Test traceability

| Acceptance criterion | Test / check |
| --- | --- |
| Backup and restore | `unit_tests/test_database_backup.py` |
| Health and request ID | `unit_tests/test_health.py` |
| User isolation and mileage | `unit_tests/test_api.py`, `test_data_integrity.py` |
| API/module contract | `scripts/check_architecture.py` |
| Frontend behavior | `frontend-test`, `frontend-layout` |

