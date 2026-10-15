# ADR-0001：採用模組化單體拆分後端

- 狀態：Accepted
- 日期：2026-10-15

## Context

專案目前部署為單一 FastAPI container、單一 SQLite volume。`backend/main.py` 同時負責 app
組裝、lifecycle 與多組 route，造成檔案偏大；但目前流量、資料庫與維運需求都不需要分散式系統。

## Decision

保留單一部署單元，依功能建立 `backend/routers/`，並讓 domain/service 模組承擔可重用邏輯。
`backend/main.py` 作為 composition root，只能由外往內組裝；router 不可反向 import main。
拆分採垂直切片逐步進行，第一個切片為 analytics／exports／spending。

## Consequences

- API path 與部署方式不變，重構風險較低。
- 模組可以獨立測試，且 circular import 可由 architecture check 阻止。
- 在所有 routes 搬完前，`main.py` 仍會同時包含舊路由與 composition code；SDD 必須如實反映。
- 若未來確實需要獨立 scaling 或不同資料儲存，再以量測結果新增 ADR 評估服務拆分。

## Rejected alternatives

- **立刻拆微服務**：會增加網路錯誤、認證傳遞、部署與資料一致性成本，沒有目前需求支持。
- **只依檔案行數任意切割**：行數會下降，但責任與依賴方向不會因此清楚。
- **一次重寫所有 routes**：review 範圍過大，難以證明行為沒有改變。

