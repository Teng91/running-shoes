# ADR-0006：共用表單操作與認證／目標服務

- 狀態：Accepted
- 日期：2026-10-23
- 規格：[SPEC-023](../specs/023-feature-operations-and-application-boundaries.md)

## Context

月跑量缺少快照保護，鞋款編輯只檢查視窗身分，等待期間的新草稿仍可能被成功回應關閉。
認證與目標 router 仍管理交易，前端每次 mutation 都重讀六個主要資源並清除所有快取。

## Decision

- `runtime/form-operations.mjs` 注入 session，管理 epoch、操作身分、pending ownership 和獨立草稿快照。
  Run controller 與 monthly／shoe adapters 共用，DOM 值比較留在 bridge。Reset 後舊 finally 無權解鎖新操作。
- 只有表單與送出快照相同才清理或關閉；保留編輯草稿時，更新成功回應的版本供下次 CAS 儲存。
- 每個資料來源有自己的 request ticket 與 session；完整讀取和部分刷新交錯時，只接受仍擁有該來源的回應。各來源保留自己的載入錯誤，其他來源成功不能掩蓋未恢復的錯誤。
  跑步異動重讀鞋款、月跑量及日誌；手動月跑量只重讀月份；鞋款異動只重讀鞋款；Strava 另讀歷史。
  支出只因鞋款異動失效，目標與年度統計只因逐筆日誌異動失效；完整讀取保留全部刷新語義。
- `credentials.py` 只依賴 bcrypt／JWT，不依賴 HTTP、runtime settings；`auth.py` 保留 HTTP 認證與舊呼叫相容 exports。
  Accounts／goals services 管理配額、CAS、commit／rollback；router 管理 rate limits、Depends、request configuration 和 domain error 轉換。
- Schema 3 為 shoe 新增有 server default 的 `nickname`；不改品牌／型號分組，不改既有 ID／里程／版本。
- SPEC-023 起驗證具名 Python nodes／Node literal test titles，舊 spec 保留檔案層級追蹤。
  CI 使用獨立合成 context 捕捉真實失敗，產物上傳後由另一 job 下載，驗證 checksum／PNG／trace ZIP／錯誤標記。

## Consequences

- 保留 classic DOM handler 相容性，原生模組與其 transitive import 共同使用 shell revision，避免離線 cache miss。
- 月跑量 mutation 從六個主要請求降至一個；鞋款兩個；日誌五個；只有完整／匯入刷新讀 Strava 歷史。
- 新增 schema 需要 migration；上線前必須另做備份及隔離還原驗證。舊 schema 2 image 不接受 marker 3，回滾需停寫並保留新欄位後調整 marker。
- 靜態具名追蹤可以偵測刪除／更名，不能代替行為測試。CI roundtrip 需要 artifact service，但只保存合成資料。
