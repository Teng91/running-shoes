# SPEC-019：請求可靠性、年度彙總與可重現發布

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：SPEC-017、SPEC-018、ADR-0002、ADR-0003

## Problem

月份載入失敗後的成功回應不清除錯誤提示；同源雙分頁登出不同步。
普通 JSON 請求沒有統一逾時，新增日誌在提交成功但回應遺失時可能重複建立。
年度圖表仍分頁下載逐筆日誌。部署後資產／PWA smoke 尚未形成固定 task，Playwright 未鎖版。

## Goals

- 修正 1–5，保留既有 UI、工具名稱、API 與 user isolation，發布 v3.4.0。
- GET 可有限重試；寫入不盲目自動重試；同一次新增操作的重送不新增第二筆。
- 年度圖表只讀聚合結果；固定部署 smoke 不使用正式帳號或寫入正式資料。

## Non-goals

- 不新增進階搜尋、備註、刪除復原、帳號 JSON 還原或離線寫入佇列。
- 跨分頁同步不等於登出所有裝置，不改變 JWT 有效期限或授權方式。

## Proposed design

- 月份載入錯誤獨立於全域 aggregate error，成功後只清除自己擁有的提示。
- storage event 發生時立即作廢本頁 session、取消請求及清理畫面；不在事件處理器寫回 localStorage，避免循環；換帳號要求重新驗證。
- JSON transport 使用涵蓋 response body 的 deadline，GET 最多一次暫時性失敗重試；SSE 維持既有取消與串流生命週期，不套用短 deadline。
- 新增日誌的 Idempotency-Key 與 user_id 組成唯一鍵；canonical payload hash 與原始回應在同一 DB transaction 保存。相同鍵／內容重播原始回應，相同鍵／不同內容回 409；無鍵舊客戶端維持相容。
- 前端相同表單的人工重試沿用 key，成功或修改內容／換帳號即重建；不以日期／公里數推斷重複跑步。
- read_models 以 SQL GROUP BY 提供年度每月／每鞋統計與總量；保留被刪鞋款的歷史群組。
- 鎖定 Playwright npm dependency／lockfile，以 npm ci 安裝；失敗保存截圖、trace 與測試輸出。
- 新增 release-check task：健康／API 契約、manifest 版本、所有 shell 資產 hash／MIME、匿名瀏覽器啟動與 Chromium 離線重開；本機 fixture 負面測試防止錯版本或錯資產誤判通過。

## Security and data isolation

- Receipt、年度查詢均強制 user_id；key 不代替認證，不能取得其他帳號回應。
- 跨分頁換帳號不沿用前帳號草稿、cache、待送 key 或晚到回應；session teardown 取消普通請求。
- 發布檢查僅匿名 GET；正式檢查明確指定 origin，不包含 token 或私有資料。CI 使用暫存 DB。

## Migration, rollout, and rollback

- Schema 1 → 2：只新增 run_creation_requests 表與 user/key unique constraint，不改舊表或既有里程。
- 正式部署前下載異地備份、驗證 checksum 與隔離還原；verify-all／Agent eval／CI 全部通過後才部署。
- 部署以 v3.4.0 加 commit SHA 標記 image；部署後執行 release-check。失敗不宣稱發布完成。
- 回滾優先採 forward fix。若回 v3.3.1，必須先停止所有 app writes，另備份 schema 2，再確認只有本規格新增表，將 schema_metadata.schema_version 改回 1（保留 receipt 表與所有業務資料），才部署舊 image；舊版不支援 schema 2 marker，不能直接切 image。重新發布舊程式須新 shell revision；不得用舊備份覆蓋已新增的正式資料。

## Acceptance criteria

- [x] AC-1：月份／頁面載入失敗後成功重試，清掉該提示，不掩蓋其他資料錯誤。
- [x] AC-2：雙分頁登入／登出／換帳號後，其他分頁立即隱藏舊資料，晚到請求不得修改新工作階段。
- [x] AC-3：JSON header／body 卡住會 timeout；GET 最多重試一次，401 不重試，寫入不自動重試，SSE 不被短 deadline 中斷。
- [x] AC-4：同 key 並行／重送只建立一筆日誌及一次里程；內容衝突 409、不同帳號互不干擾，失敗交易可重試。
- [x] AC-5：年度 API 在空資料、跨帳號、刪鞋、跨年下正確；前端不再下載全年度逐筆日誌。
- [x] AC-6：release-check 拒絕版本／hash／MIME／API／boot／離線失敗；不寫入正式帳號；CI 鎖版並提供失敗 artifacts。

## Test traceability

| Acceptance criterion | Test file / command |
| --- | --- |
| AC-1–3 | Node reliability suite、雙引擎瀏覽器與跨分頁測試 |
| AC-4 | run idempotency API／transaction／migration regressions |
| AC-5 | annual summary API／query budget／chart regressions |
| AC-6 | release smoke negative fixtures、task runner tests、release-check |

## Verification record

2026-10-22：`verify-all` 通過，424 Python tests、78 Node tests、94.63% backend branch coverage；
40 組排版、雙引擎 CRUD／session／SPEC-019、實際 ASGI/CORS 的匿名 release-check 與 PWA upgrade/offline 均實際執行，未跳過。
`eval-agent` 10 passed；Ruff、mypy（54 modules）、architecture（37 API method/path pairs）、secret scan、dependency audit、generated assets 與 docs-check 通過。
CI 與正式部署／備份的實際結果記錄於 v3.4.0 GitHub Release；本機驗證不使用正式 DB、帳號、LLM 或搜尋服務。
