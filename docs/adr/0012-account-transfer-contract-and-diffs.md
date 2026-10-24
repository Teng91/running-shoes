# ADR-0012：可再匯入的下載與實際差異計畫

- 狀態：Accepted
- 日期：2026-10-24
- 規格：[SPEC-032](../specs/032-trustworthy-account-transfer.md)

## Context

匯出未套用匯入限制，歷史增長會產生無法還原的檔案；preview 的來源對應計數與 executor 的實際比較分離。提交後畫面刷新錯誤也會混淆操作是否完成。

## Decision

- backup_contract 是雙向契約，匯出 cap+1 限制讀取後驗證同一結構與 UTF-8 位元組容量，不靜默截斷。省略歷史需要明確選擇，預設完整且在檔名與畫面揭露。
- 來源快照轉成 query-free 欄位 patch 與最終里程投影，統計與寫入使用同一份計畫。保留本機額外資料及來源刪除，不把匹配筆數當成更新。
- 原生 controller 記錄提交成功及讀取操作身分；bridge 顯示獨立讀取重試。未知提交回應沿用原操作 key，已知成功不能再提交。

## Consequences

新增一個後端純計畫模組、include_history query 與讀取按鈕；schema／檔案版本維持原值。超過全部資料容量時仍需管理員備份，不以提高不可信上傳上限解決。回歸覆蓋容量邊界、分頁／視窗／session 時序及差異與版本一致性。
