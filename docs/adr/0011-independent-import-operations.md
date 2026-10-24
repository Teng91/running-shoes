# ADR-0011：獨立預覽、共用匯入計畫與最小寫入

- 狀態：Accepted
- 日期：2026-10-24
- 規格：[SPEC-030](../specs/030-import-operation-isolation.md)

## Context

前端 revision 無法阻止舊 HTTP 請求在伺服器晚完成後撤銷新預覽；每人單一預覽 token 讓不同分頁互相干擾。匯入內混合來源辨識與寫入，預覽重算與執行易分歧。無條件更新版本及未檢查 session 的清除會破壞使用者未完成的編輯。

## Decision

- Schema 6 預覽以 user_id／token 複合主鍵儲存，沿用本人 hash／revision／receipt；8 份、64 MiB、20 分鐘限制在 writer reservation 後判定。清理只刪除本人指定 token 或已過期項目，超限拒絕新請求，不撤銷其他有效 token。
- 預覽與套用共用 user-scoped `ImportPlan`，固定來源與 Strava 對應；寫入 executor 與交易／回執 orchestrator 分離，僅 orchestrator commit。禁止以 ORM session 的隱藏 info cache 傳遞來源狀態。
- ORM 欄位與派生總量只於實際變更時寫入，UTC 日期按相同時間比較。無變更匯入不增加版本與業務異動。
- 前端原生 controller 注入 transport／session／key，DOM bridge 不自行擁有操作狀態。過期結果只清理自己的 token；關窗不撤銷已送出的 apply，舊回呼不能改動新操作。
- 本機清除沿用既有 form operation epoch 與輸入快照，舊 session 的成功／失敗不更新新帳號，等待中的新輸入保留。

## Consequences

新增一個原生模組及 preview DELETE 契約；發布資產數為 51。預覽表需交易 migration，保留舊有效 token；回滾腳本只捨棄暫存預覽並恢復 schema 5，不覆寫業務資料。因斷線未清理的 token 由 TTL 回收；嚴格上限可能要求等待過期或關閉其他預覽。回歸涵蓋多分頁／亂序、相同內容、舊 session、新輸入、升級與回滾。
