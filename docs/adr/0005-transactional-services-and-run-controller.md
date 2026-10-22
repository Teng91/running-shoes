# ADR-0005：SQLite 寫入服務與可注入的跑步控制器

- 狀態：Accepted
- 日期：2026-10-22
- 規格：SPEC-020

## Context

先 count 再 insert 無法跨請求保護配額；HTTP router 擁有交易使並行、錯誤與配置難以重用。
classic scripts 分檔後仍共享操作狀態，晚到成功回應會清除新草稿。月報重複執行逐月加總。

## Decision

- 維持 modular monolith、SQLite 與既有 API。寫入由 application services 擁有，domain error 由 HTTP adapter 轉換。
- 以同使用者的 no-op User UPDATE 取得 SQLite writer reservation，於鎖內重新讀取資料並驗證配額／版本／里程。
  token_version 值不變；SQLite 本來就一次只有一個 writer，這個順序讓 validation 與 persistence 共享同一交易。
  不使用 process-local mutex 保護資料一致性，不新增鎖表、migration 或另一個持久化來源。
- CRUD、註冊／匯入配額與 upload guard 從 app.state.settings 注入；服務只接收需要的 scalar limits。
- 原生 run controller 接收 session、transport、key factory；DOM bridge 僅讀寫表單與呈現結果。
  操作 identity、編輯快照與重送 key 由 controller 擁有，成功清理必須符合送出時的表單快照。
- run statistics read model 共用日期範圍與 SQL aggregates；不把手動歷史調整混入逐筆日誌目標。
- docs-check 驗證可機械判定的連結、spec sections、AC completion、test paths；語義仍由 regression 與 review 驗證。

## Consequences

- 交易包含額外一個廉價 UPDATE，取得 writer 後才讀取業務狀態；外部 LLM／搜尋不進入交易。
- Services 可直接測試 rollback／並行與 user isolation，router 不再擁有 commit／rollback。
- 前端仍保留相容 DOM handler 名稱，逐步將功能 state 移入 native modules，PWA manifest 明列新 module。
- schema 2 與 v3.4.0 相容，回滾不需修改 marker；發布仍需新 asset revision 與正式資料備份。
