# SPEC-032：可靠帳號下載、差異預覽與匯入完成狀態

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-030](030-import-operation-isolation.md)、[SPEC-031](031-calendar-shoe-labels.md)

## Problem

匯入提交後讀取失敗被誤報為可重試的匯入錯誤；匯出全部歷史可能產生超過匯入集合或 20 MiB 限制的檔案；預覽把來源對應數當作實際更新數。

## Goals

- 提交與畫面刷新分離，提交成功後提供可重試的純讀取，不重新匯入。
- 匯出與匯入共用欄位、集合及位元組限制，匯出前驗證可再匯入，不靜默截斷。
- 預設完整下載，可明確選擇不含異動歷史；超限給可操作訊息。
- 匯入計畫包含欄位差異與最終里程，預覽及執行共用差異，列出新增、變更、相同、保留刪除。

## Non-goals

- 不改資料來源身分或非破壞合併政策，不變更資料庫 schema 或提高不可信上傳限制。

## Proposed design

`backup_contract.py` 擁有所有集合限制與匯出驗證；export service 在同一讀取快照中以 cap+1 讀取，超限拒絕並提供不含歷史選項。`include_history=false` 由兩個下載入口的 checkbox 明確指定，預設 true，檔名與狀態揭露省略。

`account_import_changes.py` 根據 user-scoped 計畫產生純欄位 patch 與最終鞋款／月份里程；比較 UTC 時間與巢狀值。executor 只套用這份 patch，summary 以實際變更計數，保留額外本機跑步與刪除 tombstone。

原生 restore controller 擁有已提交、需刷新與刷新操作身分；DOM bridge 提供獨立「重新載入資料」按鈕。刷新失敗保留成功狀態，錯誤／完成均檢查 session、revision 與操作所有權。

## Security and data isolation

- 所有讀取、差異、下載及寫入維持認證 user_id 範圍，清理與回執沿用既有身分。
- 匯出拒絕輸出含 credentials 或不符合匯入契約的資料；錯誤不反射帳號內容。
- 測試僅用合成帳號、暫存 DB、注入 transport，不寫入正式帳號。

## Migration, rollout, and rollback

- v3.10.2／shell v37，schema 6 不變。發布前驗證正式異地備份與隔離還原。
- 本機 verify、版面、CRUD、PWA、main/tag CI 通過後部署 immutable image；完成匿名 release-check。
- 無 schema migration，回滾可部署 v3.10.1 immutable image；不還原業務快照。舊版預覽回執保持可讀。

## Acceptance criteria

- [x] AC-1：Given 匯入提交成功但刷新失敗，When 重試刷新，Then 只重新讀取且保留已提交結果；關窗／換帳號後舊回呼不污染新狀態。
- [x] AC-2：Given 完整歷史超限或資料超過位元組限制，When 下載，Then 明確拒絕且不產生壞檔；明確省略歷史的成功檔案能重新匯入且不含他人資料。
- [x] AC-3：Given 相同、局部變更、額外本機跑步及已刪除來源，When 預覽並套用，Then 新增／變更／相同數符合實際 patch，無變更不改版本。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/workspace.test.cjs::SPEC-032 committed import refresh retries only reads and isolates replaced windows` |
| AC-2 | `unit_tests/test_account_restore.py::test_export_contract_limits_and_explicit_history_omission` |
| AC-3 | `unit_tests/test_account_restore.py::test_import_diff_preview_matches_patches_and_preserves_local_runs` |
