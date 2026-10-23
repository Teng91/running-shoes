# SPEC-025：Strava 操作所有權、逐資源呈現與有界鞋款分析

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：ADR-0008

## Problem

跨日重繪會替已刪鞋款的日誌選入另一雙鞋。Strava 舊匯入完成會關閉新預覽，舊歷史回應會覆蓋新歷史。鞋款退役會丟棄操作前的未儲存欄位。整批讀取等待慢來源；鞋款分析載入全部歷史；WebKit worker-update 逾時缺少階段與 worker 狀態證據。

## Goals

- 保護跨日選鞋、替換視窗、同帳號交錯請求與退役前後草稿。
- 原生 Strava controller 管理預覽／匯入生命週期，resource store 管理歷史與逐資源完成。
- SQL 聚合歷史及每雙鞋最多 12 筆最近紀錄，維持既有分析回應。
- Worker 更新觀測既有與新 installing worker，失敗留下階段、註冊及網路診斷。

## Non-goals

- 不更改 CSV 格式、API path、資料 schema 或生產帳號資料。

## Proposed design

新增不依賴 DOM 的 Strava controller，注入 session 與 transport。關閉／重開視窗使 UI operation 失效；已提交匯入仍刷新資料，不能改寫替換視窗。歷史經 resource ticket 合併與失效。refresh 每個資源完成即交付，仍提供全部完成的 Promise。鞋款移動僅 acknowledge 狀態／月跑量，其他草稿依原始基準 rebase。分析 read model 使用 user-scoped 聚合、月份聚合與 partitioned recent window。

## Security and data isolation

- 所有 SQL 限制 user_id，批次入口排除他人／已刪鞋款；controller 與資源完成必須驗證登入 session。
- 瀏覽器測試只使用合成資料；正式站檢查匿名唯讀，備份放 Git 外私有目錄。

## Migration, rollout, and rollback

- Schema／資料 migration：無，schema 3。
- 上線與 smoke test：完整 verify-all、主線與 tag CI；備份並隔離還原驗證，再部署指定 digest，執行匿名 release-check。
- 回滾方式與資料相容性：回到 v3.6.1 image `registry.fly.io/running-shoes@sha256:6c1789d3aa0904058fd9855c60f097938ed7acc709853d687ac60ceffdaf3cf9`；schema 相容，不覆寫正式資料。

## Acceptance criteria

- [x] AC-1：Given 已刪鞋款的編輯日誌，When 跨日重繪，Then 保留請重新選擇，禁止隱性轉移里程。
- [x] AC-2：Given 匯入／預覽未完成，When 替換視窗或登入工作階段，Then 舊成功／失敗不修改新畫面；當前匯入不重複提交。
- [x] AC-3：Given 匯入後的新歷史，When 舊 GET 最後完成，Then 新歷史與日期預設不倒退。
- [x] AC-4：Given 移動前或等待期間的鞋款草稿，When 移動成功再儲存，Then 保留草稿且不撤銷鞋款狀態。
- [x] AC-5：Given 慢來源或個別失敗，When 其他資源完成，Then 立即呈現成功資料並維持獨立錯誤與失效規則。
- [x] AC-6：Given 大量歷史及多帳號，When 單鞋／批次分析，Then 聚合相容且最近紀錄最多每鞋 12 筆，查詢數不隨鞋數增加。
- [x] AC-7：Given 已在 installing 的更新或中斷資產，When PWA 檢查，Then 正確觀測該 worker 並在逾時保存階段與註冊狀態。
- [x] AC-8：Given 未壓縮資產 body 長度不符，When 引擎仍回傳成功，Then installer 拒絕候選 shell；壓縮回應不以解壓大小比對 wire length。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/strava-resources.test.cjs::SPEC-025 deleted shoe selection remains explicit across redraws` |
| AC-2 | `unit_tests/frontend/strava-resources.test.cjs::SPEC-025 Strava ownership protects replacement previews and sessions` |
| AC-3 | `unit_tests/frontend/strava-resources.test.cjs::SPEC-025 Strava history invalidation rejects older reads` |
| AC-4 | `unit_tests/frontend/strava-resources.test.cjs::SPEC-025 retirement preserves edits made before the command` |
| AC-5 | `unit_tests/frontend/strava-resources.test.cjs::SPEC-025 resource completion is delivered before slow peers` |
| AC-6 | `unit_tests/test_analytics.py::test_shoe_analytics_sql_is_bounded_and_user_scoped` |
| AC-7 | `unit_tests/frontend/strava-resources.test.cjs::SPEC-025 worker observer handles an already installing candidate` |
| AC-8 | `unit_tests/frontend/strava-resources.test.cjs::SPEC-025 worker refuses truncated identity bodies without comparing compressed lengths` |

補充雙引擎驗收：`python3 scripts/task.py frontend-e2e`、`python3 scripts/task.py frontend-pwa`。

## Verification evidence

- 本機 `verify-all` 通過：464 Python、95.29% backend branch coverage、40 組版面、雙引擎 CRUD／SPEC-025 與 PWA，無跳過。
- `frontend-test` 最新 105 個具名案例通過；`eval-agent` 10 個合成評估通過；`docs-check` 核對 44 個 release assets 及具名追蹤。
- 發布必須再確認 main／tag CI、備份還原及正式 origin 的匿名 release-check。

## CI follow-up：v3.7.1

v3.7.0 main run 39934466655 的 PWA 失敗 artifact 12492509529 顯示 update timeline 只有 observe／failure、installing 與 waiting 都為 null；trace 的 worker script request status -1。最後的 fixture 請求是在 networkDown 中的 worker script；後續候選尚未抵達 server。相同 SHA 的 tag run 39934467048 PWA 與 diagnostics roundtrip 通過，仍不能作為 main 失敗的替代。

離線 fixture 針對 worker script 回 503 以終止背景更新；每次回到在線前，以 10 秒 deadline 驗證 registration.update 必須失敗，避免舊更新佇列延誤下一個 candidate。這是 AC-7 的實際 browser 驗收，仍保留全部失敗安裝／離線／恢復斷言。v3.7.0 tag 不重寫；正式發布／部署使用 asset 3.7.1／shell v31，schema 維持 3，回滾 image 不變。

v3.7.1 本機 `verify-all` 全數通過：464 Python、105 Node、95.29% backend branch coverage、40 組版面、雙引擎 E2E／PWA 無跳過。離線 update 明確失敗後才恢復在線，避免只用改變 fixture 狀態推論先前 scope job 已結束。
