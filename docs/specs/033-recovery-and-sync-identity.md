# SPEC-033：復原來源身分與同步完成狀態

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-032](032-trustworthy-account-transfer.md)

## Problem

同帳號下載後刪除跑步，再匯入舊檔會重建已刪紀錄；誤刪復原配置新 ID 後，來源對應仍指向舊 ID，後續更新匯入會略過復原紀錄。離線佇列跨登入重試重用租約身分，舊請求可能覆蓋新請求狀態。同步成功後核心讀取失敗仍顯示完成。

## Goals

- 保留刪除與復原的來源身分，預覽與執行一致。
- 每次佇列送出獨立租約；延遲完成不能覆寫接手者。
- 共享核心讀取驗證，區分成功提交與畫面刷新失敗。

## Non-goals

- 不新增業務功能、不變更 schema、不對正式資料進行測試寫入。

## Proposed design

將原生刪除來源辨識與復原對應轉移集中到 framework-independent service。匯入計畫在同來源時補上本機非匯入的刪除 tombstone，明確復原時將所有本帳號來源別名轉到新紀錄。佇列每次 claim 配置新租約。核心資料刷新驗證集中於 resource bridge，匯入、同步與刪除復原共用；復原提交後只能重試讀取。

## Security and data isolation

- 對應與異動查詢均限制 user_id，匯入歷史不作為本機刪除證據。
- 回歸案例使用暫存資料庫與合成佇列，無 credentials 或正式帳號。

## Migration, rollout, and rollback

- v3.10.3／shell v38，schema 6 不變。
- verify-all、main/tag CI 與匿名 release-check 通過後完成發布。
- 可回滾 v3.10.2 immutable image；來源對應仍相容，不回復業務快照。

## Acceptance criteria

- [x] AC-1：Given 同帳號備份後刪除，When 匯入，Then 保留刪除且不重建跑步。
- [x] AC-2：Given 已對應跑步刪除後復原，When 更新匯入，Then 更新復原紀錄且不重複，其他帳號對應不變。
- [x] AC-3：Given 舊租約過期且重新登入接手，When 舊請求延遲失敗，Then 不改新租約或阻擋新請求。
- [x] AC-4：Given 同步提交成功而核心讀取失敗，When 顯示結果，Then 明確說明已送出及需要重新整理。

- [x] AC-5：Given 誤刪復原已提交而讀取失敗，When 點擊重新載入資料，Then 只讀取，不再次提交復原。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_account_restore.py::test_own_archive_preserves_deleted_runs` |
| AC-2 | `unit_tests/test_account_restore.py::test_recovered_run_retains_all_source_aliases` |
| AC-3 | `unit_tests/frontend/workspace.test.cjs::SPEC-033 expired send cannot release a replacement lease after reattach` |
| AC-4 | `unit_tests/frontend/workspace.test.cjs::SPEC-033 sync reports committed writes when core refresh fails` |
| AC-5 | `unit_tests/frontend/workspace.test.cjs::SPEC-033 deletion recovery retries reads after a committed write` |
