# SPEC-030：匯入操作隔離與最小資料更新

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-029](029-account-data-transfer.md)、[ADR-0010](../adr/0010-recoverable-account-workspace.md)、[ADR-0011](../adr/0011-independent-import-operations.md)

## Problem

已重現三項問題：A 帳號的非同步本機清除會清空切換後 B 的草稿；更新匯入對未變更／額外紀錄增加版本及異動；每人只有一個預覽，使晚到的舊請求撤銷新預覽。

## Goals

- 本機清除的成功與錯誤只影響原 session，保留等待期間的新輸入。
- 相同內容匯入不改版本、里程、revision 或新增業務異動，真正變更仍使舊編輯失效。
- 多個預覽可各自確認，晚到、關窗及多分頁不互相撤銷；以 TTL、筆數與容量限制保護儲存。
- 共用匯入計畫供預覽與套用；前端 controller 擁有操作狀態，DOM bridge 只處理呈現。

## Non-goals

- 不改既有 merge／update 的資料保留策略，不做整庫覆蓋或正式帳號試匯入。

## Proposed design

`account_import_plan.py` 擁有本人資料快照、來源／Strava 辨識、限制與預覽；`account_import.py` 套用計畫，`account_restore.py` 保留預覽／回執及交易邊界。里程對帳移至 `services/mileage.py`，只寫入確有改變的值。既有欄位更新也先比較值。

Schema 6 將 `restore_previews` 主鍵改為 `(user_id, token)`，保留既有有效預覽。每人最多 8 份未過期預覽、總 payload 上限 64 MiB、有效 20 分鐘；建立前只清理過期項目，超限拒絕新預覽而不撤銷仍有效的 token。新增本人預覽 DELETE 供 controller 捨棄失效／關窗的 token，失敗以 TTL 回收。

`runtime/account-restore-controller.mjs` 注入 session／transport／key，管理視窗、revision、preview、apply 及清理，狀態不依賴 DOM。清除本機資料使用既有 form operation 所有權並比對輸入快照，只重設尚未被使用者改動的欄位。

## Security and data isolation

- 所有計畫、預覽、清理、回執、更新以認證 user_id 限定；token 不取代登入。
- TTL／容量檢查在 SQLite writer reservation 後執行；保留 hash／revision、配額與一次交易回滾。
- 測試只使用合成資料、暫存 DB 與 mock 服務。

## Migration, rollout, and rollback

- v3.10.1／shell v36／schema 6；發布前建立並驗證正式異地備份及隔離還原。
- migration 在同一 SQLite 交易重建預覽表並複製資料，其他業務表不改寫；重跑安全。
- 回滾優先 forward fix。需回 v3.10.0 時先停止寫入、另備份 schema 6，捨棄暫存預覽並以 schema 5 主鍵重新建立預覽表，再將 marker 改回 5、部署先前 immutable image。不得還原舊業務快照或混跑兩版；具體步驟記於 README。
- 本機完整驗證與 main／tag CI 通過後部署，最後執行正式站匿名 release-check。

## Acceptance criteria

- [x] AC-1：Given A 的清除等待中，When 切換 B 或修改輸入，Then 舊成功／失敗不污染 B 且新輸入保留。
- [x] AC-2：Given 重複檔案與額外資料，When 更新匯入，Then 未變更項目的版本／異動維持原值；真正變更正確重算。
- [x] AC-3：Given 舊預覽晚到或不同分頁，When 確認新預覽，Then token 仍可用；過期、超限、不同帳號清理仍受限。
- [x] AC-4：Given schema 5 有效預覽，When 重複升級到 6，Then 保留預覽、資料及主鍵契約。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/workspace.test.cjs::SPEC-030 local clearing preserves replacement sessions and newer input` |
| AC-2 | `unit_tests/test_account_restore.py::test_identical_update_preserves_versions_history_and_unrelated_edits` |
| AC-3 | `unit_tests/test_account_restore.py::test_late_preview_cannot_revoke_newer_token`、`unit_tests/frontend/workspace.test.cjs::SPEC-030 restore controller isolates windows and releases stale previews` |
| AC-4 | `unit_tests/test_account_restore.py::test_schema_six_preserves_existing_preview_and_is_idempotent` |
