# SPEC-027：可離線、恢復與追溯的跑步工作區

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[ADR-0010](../adr/0010-recoverable-account-workspace.md)

## Problem

目前草稿只存在記憶體；帳號備份僅可匯出；離線不能新增跑步；刪除與里程變更缺少可供使用者查看、復原的歷史。既有交易回執與 controller 可作為可靠同步基礎。

## Goals

- 依帳號保存草稿、最近資料與持久化新增跑步佇列，重開仍可恢復。
- 提供驗證、預覽、重複辨識、保留現有內容的帳號合併還原。
- 提供 user-scoped 異動歷史與防衝突誤刪復原。
- 以 application service、原生 controller、DOM adapter 明確分工；統一操作回執與錯誤格式。

## Non-goals

- 不在 service worker 快取認證 API；不支援離線更新／刪除、不自動覆蓋衝突，不備份認證憑證。
- 不移除既有相容 HTTP endpoints。

## Proposed design

IndexedDB adapter 以 account/kind/id 分區；native workspace controller 注入 storage、session、clock、transport。草稿與快照不包含 token。離線新增先持久化 operation ID／payload，再發送；跨分頁以原子 lease 防止同時消費，逾時沿用同 key 重播，401 暫停，資料錯誤進入 blocked 清單等待明確配對／重試／移除。關閉 App 或登出不偷偷刪除尚未同步內容，另一帳號不可呈現或提交它們。

Schema 5 新增使用者 backup identity／資料 revision、操作回執、還原預覽、來源 ID mapping、異動事件與寫入 context。SQLite triggers 在原交易記錄鞋款、跑步、月跑量、目標的 before/after 及原因；不記錄 users 密碼或 token。復原僅允許被刪除／清除的業務內容且目前狀態仍符合事件快照，重新計算里程與配額，同一事件不重複復原。

匯出以實體 read snapshot 固定各集合，並行寫入不產生混合備份。備份 v2 帶穩定來源 identity，v1 仍可匯入。預覽不改動業務資料；apply 驗證 user-bound token、payload hash 及資料 revision，全部新增／mapping／回執一次 commit。預設跳過已有 mapping、Strava ID、月份／報告／目標，不覆寫；鞋款不按品牌型號誤合併。Strava 匯入摘要先保留既有，剩餘容量按新到舊加入，預覽顯示新增／略過數，不清除既有摘要。v1 只能保證完全相同檔案重複不重建，預覽清楚說明。

新 `/api/operations` 契約要求 operation ID，更新／刪除要求 expected_version；既有 CRUD adapters 保留相容性，有 key 時走相同 transactional receipt。統一錯誤保留 detail 並提供 machine-readable code。新增功能各自持有 controller/state，逐步移除舊快取鏡像。

## Security and data isolation

- DB query、receipt、preview、mapping、history 全部限制 user_id；來源檔案中的 user_id／username 不可決定寫入帳號。
- 還原限制 body／筆數／字串／巢狀深度、日期、有限數值與參照完整性；未知敏感欄位拒絕，無外部請求。
- 瀏覽器以帳號 partition 與 session guards 隔離資料；IndexedDB 不取代伺服器認證。登出中止發送，本機可明確清除帳號資料。
- 測試只用暫存 SQLite、合成 IndexedDB／瀏覽器資料與 mock 外部服務。

## Migration, rollout, and rollback

- Schema 5 為新增表及 user metadata，不改寫既有業務總量；現有 backup v1／API 保持讀取相容。
- 上線前必須另做正式備份並驗證隔離還原；v3.9.0 發布流程須通過 CI 並於部署後執行匿名 release-check。
- 回滾需先停寫、備份 schema 5；保留新增表／欄位並將 marker 降回 4 後，才可使用相容舊映像。舊版寫入不產生 context 時，triggers 必須仍能安全記錄；不可遺失待同步 queue，重新發布需新 shell revision。

## Acceptance criteria

- [x] AC-1：草稿重開可恢復且 A/B 帳號隔離，儲存失敗不假裝成功；原始編輯版本保留。
- [x] AC-2：離線新增持久化、重開／多分頁／回應遺失不重複寫入；過期登入暫停，刪鞋衝突需明確處理。
- [x] AC-3：還原預覽驗證完整參照及限制；重複匯入不重建，資料變動拒絕舊預覽，失敗完整 rollback。
- [x] AC-4：異動歷史與誤刪復原限本人，里程一致、拒絕衝突且重試不重複復原。
- [x] AC-5：新寫入契約驗證 version／operation ID 並重播成功回應，legacy endpoints 相容。
- [x] AC-6：schema 4→5 可重複升級、保留資料；既有匯出及 PWA 升級／離線 shell 保持有效。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/workspace.test.cjs::SPEC-027 drafts and cached resources stay within their account` |
| AC-2 | `unit_tests/frontend/workspace.test.cjs::SPEC-027 durable queue survives lost responses and competing consumers` |
| AC-3 | `unit_tests/test_account_restore.py::test_restore_roundtrip_is_atomic_and_idempotent`、`unit_tests/test_account_restore.py::test_export_uses_one_read_snapshot_while_another_connection_writes`、`unit_tests/frontend/workspace.test.cjs::SPEC-027 restore windows reject repreview during apply and stale completion` |
| AC-4 | `unit_tests/test_history.py::test_deleted_run_restore_preserves_mileage_and_rejects_replay` |
| AC-5 | `unit_tests/test_operations.py::test_operation_receipt_replays_and_rejects_changed_payload` |
| AC-6 | `unit_tests/test_history.py::test_schema_five_upgrade_preserves_existing_business_data` |

## Verification evidence

- `verify-all` 完整通過：40 組 Chromium／WebKit 版面、雙引擎 E2E／工作區及 PWA 升級／離線，沒有 browser skip；E2E 另對暫存 FastAPI 執行匿名 50 資產 release-check。
- 工作區雙引擎驗證真實 IndexedDB 草稿重開／帳號隔離、離線佇列重開、同步恰一次、里程、誤刪復原、合併還原及重複預覽；Chromium 原生 offline emulation，WebKit 以本機 origin transport 斷線 fixture，均檢查 API 不從 shell cache 提供。
- 後續新增的匯出快照與還原視窗回歸納入 `verify`；數量以 README 與當次輸出為準。所有測試使用合成資料／暫存 SQLite；正式 migration 以前置備份及隔離還原為發布門檻，正式站另跑匿名 release-check。
