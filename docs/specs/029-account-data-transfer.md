# SPEC-029：雲端下載與本機帳號資料更新

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-027](027-recoverable-account-workspace.md)、[ADR-0010](../adr/0010-recoverable-account-workspace.md)

## Problem

使用者需要在雲端 UI 下載帳號資料，再於本機版 UI 匯入；目前合併只新增，第二次匯入無法更新先前帶入的鞋款、跑步、月份調整、目標與月報。下載失敗訊息顯示於另一個隱藏視窗，操作目標也不夠清楚。

## Goals

- 提供只新增與新增並更新兩種匯入模式，後者依 v2 穩定來源辨識既有資料。
- 預覽顯示來源、接收網站／帳號及新增／更新筆數，確認後一次交易提交。
- 更新跨鞋款／月份跑步後，在後端重算總量，保留接收帳號額外資料。

## Non-goals

- 不下載含所有帳號與憑證的整個 SQLite 檔案，不自動刪除檔案中缺少的接收端紀錄。
- 不執行正式帳號匯入、不改動正式業務資料；僅部署功能。

## Proposed design

既有 preview endpoint 增加 `mode=merge|update`，預設 merge。模式與備份一起綁定預覽 payload hash；apply 只接受 token，不能切換已預覽的模式。舊預覽仍以 merge 解讀。update 僅接受 v2，鞋款及跑步依來源 mapping／同來源 ID，跑步另外沿用 Strava 去重；月份與月報以年月、目標以帳號辨識。已刪除的接收端跑步維持略過，不偷偷復原。更新既有鞋款不改本機額外日誌，總里程由 baseline／adjustment 加完整帳號日誌重算。報告匯入撤銷該月份尚未完成的生成，防止舊串流蓋回。原有 merge 保持相容。

UI 提供模式選單、接收網站 origin 與帳號、來源及時間預覽；模式變更使舊預覽失效，匯入期間鎖定選單，更新模式確認會提醒覆寫同來源欄位。下載提供目前視窗可見的進度／成功／失敗。

## Security and data isolation

- 所有查詢、更新、mapping、預覽與回執以認證 user_id 限定；來源名稱不能決定接收帳號。
- 保持 20 MB、資料格式／參照／配額與 revision 檢查；更新配額按照匯入後現役鞋款數判定。
- 不輸出秘密或正式資料；測試採合成帳號、暫存 SQLite 及 mock 外部服務。

## Migration, rollout, and rollback

- Schema／資料 migration：無，維持 schema 5；預覽 payload 使用相容 envelope，未完成的新格式預覽由舊版處理時會拒絕，重新預覽即可。
- 發布 v3.10.0／shell v35。先備份正式 DB、checksum 與隔離還原驗證，再於完整本機測試及 CI 通過後部署；部署後執行匿名 release-check。
- 回滾可部署 v3.9.0 image，不降 schema、不以備份覆蓋正式資料；新模式已成功寫入的資料保持標準業務格式。

## Acceptance criteria

- [x] AC-1：Given 先前匯入的 v2 資料，When 以 update 匯入新版，Then 更新鞋款／跑步／月份調整／目標／月報，總量一致且保留額外資料；merge 不覆寫。
- [x] AC-2：Given 不同帳號、舊版檔案、超額、過期／遭修改預覽或提交失敗，When 匯入，Then 拒絕不安全操作、完整回滾並可重播成功回執。
- [x] AC-3：Given 雲端匯出與接收端 UI，When 選模式／檔案並確認，Then 顯示正確來源／目標、新增更新筆數與下載結果，舊操作不污染新視窗／帳號。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_account_restore.py::test_update_import_refreshes_existing_data_and_recalculates_totals` |
| AC-2 | `unit_tests/test_account_restore.py::test_update_preview_binds_mode_rejects_legacy_and_rolls_back` |
| AC-3 | `unit_tests/frontend/workspace.test.cjs::SPEC-029 import modes own their previews and confirmation`、`python3 scripts/task.py frontend-e2e` |
