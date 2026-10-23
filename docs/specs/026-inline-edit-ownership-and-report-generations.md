# SPEC-026：行內編輯保護與月報生成順序

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：ADR-0009

## Problem

刪除新增跑步草稿所選鞋款後，選單會默默換鞋。背景資料完成會移除行內輸入框，造成部分數字被自動儲存或草稿遺失。同月份舊月報生成可覆蓋新生成。Strava 匯入中的配對仍可編輯但不會送出。同年度 pending 查詢在整體重繪時重複發送。

## Goals

- 保留明確的鞋款選擇、行內輸入 DOM、草稿與原始版本。
- 依資源更新畫面，合併年度、目標與洞察讀取。
- 以跨 session／process 有效的資料庫生成身分保護月報，分離 application service、LLM adapter、SSE。
- 匯入期間鎖定配對，舊操作不能改動新視窗。

## Non-goals

- 不更換前端框架、不改變後端統計口徑，不新增 LLM 工具。

## Proposed design

表格各自擁有行內編輯期間的 DOM；背景刷新延後該表格重繪，結束編輯後呈現最新資料。提交使用開始編輯時的 id／version，發生衝突由既有 API 拒絕。資源完成只失效依賴它的 panel；衍生讀取由 resource store 合併 pending、快取與失效身分。

月報 service 開始時在短交易中寫入 `(user_id, year, month)` 最新 UUID；統計及 LLM 等待不持有寫鎖。成功持久化前於同一寫交易驗證 UUID，僅最新開始的請求可更新完整內容與統計。較新請求失敗也不恢復舊請求資格，保留之前成功的報告；reservation 不出現在歷史清單。SSE adapter 僅序列化 service events。

## Security and data isolation

- reservation 與報告查詢／寫入均限制 user_id、year、month；UUID 不是認證。
- 測試只用暫存 SQLite、合成瀏覽器資料、mock LLM。正式備份存放 Git 外，禁止在測試中使用正式資料。

## Migration, rollout, and rollback

- Schema 4：新增 `report_generations`，不改寫既有報告、里程或版本。
- 部署前執行 offsite-backup 並驗證隔離還原；CI、雙引擎 CRUD／PWA／版面、部署後匿名 release-check 必須通過。
- 回滾：停止寫入並先備份 schema 4；schema 3 舊映像拒絕較新 marker。新增表可保留，但須在確認沒有 v3.8 實例後將 schema_metadata marker 設回 3，再部署已驗證的 v3.7.2 映像；或還原部署前備份（會遺失備份後寫入）。禁止混跑兩版生成服務。

## Acceptance criteria

- [x] AC-1：Given 草稿選鞋 A，When A 被刪除且重繪，Then 保留「請重新選擇」，明確選 B 前不能新增。
- [x] AC-2：Given 鞋款／月跑量行內輸入，When 背景刷新或主題重繪，Then DOM 與草稿保留，沒有自動 PUT；明確提交才使用原版本。
- [x] AC-3：Given 同月份交錯生成，When 舊請求較晚完成，Then 不覆蓋新內容／統計；失敗、取消、不同使用者及月份均隔離。
- [x] AC-4：Given 同 key 衍生讀取並行，Then 共用 pending，失效後舊回應不能呈現，失敗可重試。
- [x] AC-5：Given Strava 匯入 pending，Then 配對停用；完成／失敗只解鎖同一視窗。
- [x] AC-6：Given schema 3 資料，When 升級兩次，Then 保留既有內容且 schema 4 生成表可用。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/resource-editing.test.cjs::SPEC-026 new run keeps a removed shoe unselected until explicit replacement` |
| AC-2 | `unit_tests/frontend/resource-editing.test.cjs::SPEC-026 inline editors defer table replacement and retain the original version` |
| AC-3 | `unit_tests/test_report_generations.py::test_latest_generation_owns_report_content_and_stats` |
| AC-4 | `unit_tests/frontend/resource-editing.test.cjs::SPEC-026 derived reads coalesce and reject invalidated responses` |
| AC-5 | `unit_tests/frontend/resource-editing.test.cjs::SPEC-026 Strava mapping lock follows the current import window` |
| AC-6 | `unit_tests/test_report_generations.py::test_schema_four_upgrade_preserves_existing_reports` |

補充真實 DOM 驗收：`unit_tests/frontend_resource_editing.cjs` 由 `frontend-e2e` 在 Chromium／WebKit 執行，測試不寫入正式資料或呼叫外部模型。

## Verification evidence

- 本機 `verify-all` 通過：475 Python、113 Node、95.63% backend branch coverage、40 組版面、雙引擎 CRUD／PWA，無跳過；10 個 Agent evals 通過。
- 年度圖表 layout fixture 改由 API 提供完整矩陣後，獨立 `frontend-layout` 40 組再驗證通過。
- WebKit 刪鞋案例的首次整批失敗 trace 顯示斷言早於下一 frame；fixture 改為等待被刪選項消失，再斷言空選擇。未放寬錯鞋與無寫入斷言。
- main／tag CI、diagnostics roundtrip、正式備份還原及部署後匿名檢查的最終證據記錄於 v3.8.0 GitHub Release。
