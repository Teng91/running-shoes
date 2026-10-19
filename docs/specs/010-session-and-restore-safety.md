# SPEC-010：帳號生命週期隔離與 SQLite 安全還原

- 狀態：Implemented
- Owner：Running Shoes
- 關聯 issue／ADR：全專案檢查的四項重現問題；ADR-0002

## Problem

洞察快取未區分帳號、登出未中止 AI 串流、舊請求的 401 會清除新登入。另 SQLite 還原以檔案替換主 DB，殘留 WAL 可重新套用舊資料，造成假成功。

## Goals

- 每次帳號切換建立新的 session generation，所有認證回應與 AI 串流更新先檢查原 session。
- 登出清除洞察快取、使未完成分析失效，清空對話／重試內容並解鎖輸入。
- 目前 session 的 401 照常登出，過期 session 的回應不得改變新帳號。
- 還原由 SQLite API 執行，保留還原前安全快照並驗證還原後資料庫，拒絕忙碌目標。

## Non-goals

- 不變更 API 或資料庫 schema，不進行正式資料還原或 migration。

## Proposed design

前端 auth module 提供 session snapshot／比對函式；HTTP adapter 共用認證 fetch，回應及 JSON 完成後均檢查 session。快取 key 包含 generation，AI 串流另有 AbortController 與 request ID；登出統一使快取、串流及相關 modal 狀態失效。自行 fetch 的月報與 bootstrap 也使用共用 adapter。

SQLite 還原先驗證來源，以 SQLite 取得目標獨占鎖、退出 WAL 模式並保留安全快照，再以 backup API 寫入同一目標連線，避免主檔替換與舊 WAL 不一致；完成後重新驗證目標。遇到連線鎖定立即失敗，要求先停服務。

## Security and data isolation

測試使用合成帳號、mock fetch／SSE 及暫存 SQLite。任何外部模型及正式資料不參與驗證。session generation 與帳號綁定，舊請求的成功、失敗、串流完成均不得寫入新 session。

## Migration, rollout, and rollback

- Schema／資料 migration：無；本次不執行正式還原。
- 發布 v3.1.0，CSS／JS 及 PWA cache 同步更新。
- 驗證四項原始重現情境、新 session 正常 401、AI 取消後重新發問、WAL 非正常結束與使用中目標。
- 回滾：重新部署 v3.0.3；資料格式完全相容，安全快照保留於還原工具指定目的地旁。

## Acceptance criteria

- [x] A 登出後 B 即使載入失敗，也不顯示 A 的洞察；A 的延遲分析不得回填。
- [x] A 的 AI 串流在登出時中止；晚到 token／完成回應不產生 history 或 retry UI，B 可立即發問。
- [x] 舊 session 的 401 不清除新登入，當前 session 的 401 仍正常登出；晚到 JSON 不返回舊資料。
- [x] WAL 殘留時還原後讀到備份內容且安全快照保留舊內容，忙碌目標拒絕還原並保留原資料。

## Test traceability

| Acceptance criterion | Test file / command |
| --- | --- |
| AC-1～AC-3 | `unit_tests/frontend_regressions.cjs`、`unit_tests/frontend_sessions.cjs`（Chromium/WebKit），`frontend-test` / `frontend-e2e` |
| AC-4 | `unit_tests/test_database_backup.py` |
| 全部 | `python3 scripts/task.py verify-all` |
