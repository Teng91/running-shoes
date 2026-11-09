# ADR-0004：持久化新增操作回執與唯讀發布檢查

- 狀態：Accepted（`run_creation_requests` 決策由 [ADR-0015](0015-bounded-history-and-injected-runtime.md) 取代）
- 日期：2026-10-22
- 規格：SPEC-019

## Context

前端按鈕鎖只能阻擋同一頁重複點擊，不能辨識「提交成功、回應遺失」的人工重試。
年度圖表只需要彙總，逐筆分頁傳輸使成本隨日誌數量增加。PWA 的正式 CORS 邊界曾未被純 fixture 涵蓋。

## Decision

- `run_creation_requests` 是 schema 2 的獨立、user-scoped receipt 表；唯一鍵 reservation、run、里程與原始回應同一 transaction commit。
- Key 不是認證、不是日期／距離指紋，也不是 Strava ID；同日同距離的真實跑步仍可分開新增。相同 key 的原始回應在編輯／刪除後也不變，重播不復活資料。
- Router 處理 Header／HTTP status；service 負責 canonical fingerprint 與 owned receipt lookup，SQL unique constraint 裁決跨程序並行，不依賴 process lock。
- 一般 JSON helper／登入採 bounded deadline，GET 只有一次暫時性失敗重試；寫入不自動重試，串流不套用整體 JSON deadline。
- storage event 作廢本分頁的 session 並清理功能狀態，不寫回 storage，不隱式登入其他帳號。
- 年度 read model SQL 分組，前端只組合圖表；feature cache 仍由既有 session／revision 清理。
- 發布檢查是 task runner 的唯讀子命令，不包含 commit、deploy 或 rollback；對正式 origin 只做匿名 GET。E2E 在暫存 DB 與真實 ASGI/CORS 上執行相同命令，再到正式站核對。
- 瀏覽器版本以 lockfile 重現，失敗 trace／截圖只錄製合成帳號或匿名頁，保留於 Git 之外。

## Consequences

- 新增 receipt 儲存空間與 schema upgrade；必須在正式 migration 前完成備份／隔離還原，不能直接回滾至不接受 schema 2 的舊 image。
- 既有不傳 key 的客戶端維持相容，不承諾無 key 請求的去重。前端失敗 key 只存本頁記憶體，不是跨重開的離線佇列。
- 跨分頁清理不是全裝置 token 撤銷；不更改 token_version 或 JWT 有效期。
- WebKit 的已安裝離線由 fixture transport 失敗測試；正式站只宣稱實際執行的匿名啟動／快取檢查，不將模擬當成 iPhone 實機結果。
