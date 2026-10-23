# ADR-0009：行內 DOM 所有權與月報生成順序

- 狀態：Accepted
- 日期：2026-10-23
- 規格：[SPEC-026](../specs/026-inline-edit-ownership-and-report-generations.md)

## Context

逐來源完成後全體 render 會移除輸入框，Chromium 的 blur 可提交部分數字，WebKit 可能遺失草稿。資料排序後表格索引也可能指向新資料。原子 upsert 只保證單筆月報寫入完整，無法判斷兩次生成的開始順序。

## Decision

- 維持現有 DOM adapters，依 resource 只失效依賴它的 panels。各 tbody 擁有 live editor 與顯示列快照；編輯結束前 renderer 不替換該表格。提交使用原始 id／version，後端 CAS 保護外部異動；session teardown 先撤銷 blur。
- 年度、目標進度與洞察透過 resource store 管理 pending、成功快取與失效；鏡像 Map 僅保留相容診斷用途。延後 loader dispatch 也必須驗證 owner，不能把新帳號的 token 借給舊操作。
- Schema 4 新增 `report_generations`，複合主鍵為 user/year/month，token 為 server UUID。生成開始先在短交易保留最新身分，保存前以 writer reservation 驗證同一 token，再於同一交易 upsert 報告；不靠 process lock，也不在 LLM 等待期間持有交易。
- 選擇最新開始的請求，而非最後完成的請求；較新失敗／取消不恢復舊 token，也不刪除先前成功內容。獨立 reservation 避免首次生成在清單中出現空報告。
- Service 只輸出 domain events，統計、LLM adapter、持久化與 SSE 各自負責清楚邊界，router 不管理交易。

## Consequences

- 表格背景資料更新會延後到使用者完成該行內操作；CAS 衝突須重新載入，不能默默套用新版本。
- 同 key 的重繪共用 pending，但日誌成功失效後可啟動新讀取。不同年度切換採最後 key 的 cache，不新增無上限前端快取。
- Schema 4 為 additive；每 user/month 一筆 receipt，不隨重試成長。新舊生成服務不可混跑。備份、隔離還原及 schema 3 marker 回滾步驟見 README；回滾會失去生成順序保護。
- 瀏覽器雙引擎驗證真實 DOM／blur，Python 暫存資料庫驗證交錯完成及連線隔離，不能只靠 source pattern 或同 process mutex。
