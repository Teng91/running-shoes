# SPEC-034：可攜復原來源、小數里程與跨分頁刷新

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-033](033-recovery-and-sync-identity.md)

## Problem

來源網站刪除再復原手動跑步後，搬移到已匯入該來源的資料庫會產生重複跑步。浮點累積讓相同備份被誤判更新。另一分頁消耗共用佇列後，目前分頁的同步不重新讀取雲端。

## Goals

- 復原來源別名隨備份搬移，重複匯入不重建，衝突不自動合併。
- 小數精度內相同資料不改版本，新的里程累積統一兩位精度。
- 手動同步、回到前景及跨分頁提交後刷新雲端，保持草稿與帳號隔離。

## Non-goals

- 不猜測相似跑步、不自動刪除既有重複資料，不建立即時跨裝置同步。

## Proposed design

帳號備份 v3 在每筆跑步加入有界 aliases，只包含匯出帳號自身 source_id 的前身 ID。契約驗證別名唯一、不與任何現有來源 ID 重疊、總量與 UTF-8 容量有界；v1/v2 繼續可讀。預覽與執行共用別名匹配，若多個別名已指向不同接收紀錄則拒絕。接收者刪除 tombstone 保持有效。

里程寫入在 SQL round 至兩位，差異計畫以兩位精度比較，兼容既有浮點尾差。工作區 controller 以注入提交通知區分成功送出；DOM bridge 透過 BroadcastChannel 通知相同帳號分頁刷新，手動／前景同步亦可直接讀取雲端。通知失敗不影響已成功提交。

## Security and data isolation

- 別名只在認證 user_id 和 archive source_id 內匹配，不攜帶 token、user_id 或其他帳號來源。
- 所有寫入由呼叫端交易擁有；跨分頁通知只帶帳號 partition，接收時重新檢查 session，不信任通知資料作寫入。
- 測試只用暫存 DB、合成帳號及注入 transport。

## Migration, rollout, and rollback

- v3.10.4／shell v39，schema 6 不變；新下載為 archive v3，繼續讀取 v1/v2。
- 舊版無法讀取 v3 檔案；回滾應保留 v3 檔案並升回新版匯入，不自行刪掉別名欄位。
- 部署前驗證備份／隔離還原，verify 與 browser／main/tag CI 通過後部署 immutable image；正式站匿名 release-check。
- 可回滾 v3.10.3 image，schema 與既有 DB 來源對應相容，不還原業務快照。

## Acceptance criteria

- [x] AC-1：Given 來源跑步多次復原及接收者已有對應，When v3 搬移／反覆更新，Then 只有一筆且版本、里程及預覽一致。
- [x] AC-2：Given 衝突、重複、超量或跨帳號別名，When 預覽或匯出，Then 安全拒絕不寫入，舊檔仍可讀。
- [x] AC-3：Given 舊浮點尾差或新的小數累積，When 相同備份再匯入，Then 不增加版本及異動，實際兩位變更仍更新。
- [x] AC-4：Given 空佇列或另一分頁完成送出，When 手動／前景／通知同步，Then 讀取雲端、保留輸入且舊帳號通知無效。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_account_restore.py::test_portable_source_recovery_aliases_roundtrip` |
| AC-2 | `unit_tests/test_account_restore.py::test_portable_alias_contract_rejects_ambiguous_graphs` |
| AC-3 | `unit_tests/test_account_restore.py::test_fractional_import_ignores_legacy_noise_and_preserves_real_changes` |
| AC-4 | `unit_tests/frontend/workspace.test.cjs::SPEC-034 manual empty sync refreshes cloud and rejects foreign notifications` |
