# SPEC-020：交易式功能邊界、草稿保護與文件契約

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：SPEC-004、SPEC-017、SPEC-019、ADR-0005

## Problem

新增跑步的晚到成功回應會清除等待期間輸入的新草稿。鞋款 count/check/insert
在並行請求下可突破配額；router 的 import-time 配額忽略 app factory 注入設定。
跑步、鞋款與月份的交易仍位於 HTTP router，跑步操作狀態依賴 classic globals。
月報 YTD 每月各查一次；README 年度圖表說明過期，文件檢查沒有驗證連結與規格結構。

## Goals

- 保留等待期間修改的日期、里程、鞋款及查看月份，維持同內容人工重試的 operation key。
- 配額、版本、日誌與里程在 framework-independent application services 中原子處理。
- app instance 的 CRUD／匯入／註冊配額與 upload guard 使用注入設定。
- 跑步以 native module 管理操作 state，透過明確注入 transport/session/key factory 與 DOM bridge 整合。
- 共用 user-scoped 日期區間統計，月報 YTD 一次聚合；首頁與目標採相同日期邊界。
- 驗證 Markdown 本地連結、feature spec 必要結構、AC 與實際測試路徑。

## Non-goals

- 不新增搜尋、備註、目標歷史、垃圾桶、帳號還原或離線寫入。
- 不改 API method/path、既有 payload、schema version、部署拓撲或改用前端框架。
- 不把靜態文件檢查宣稱為已證明每個 acceptance criterion 的語義正確。

## Proposed design

- `services/transactions.py` 以 user-scoped no-op UPDATE 取得 SQLite writer reservation，先取得鎖再讀取業務快照／配額；同一 transaction commit 或 rollback，不依賴 Python process lock。
- `services/runs.py`、`shoes.py`、`monthly.py` 擁有寫入與 domain errors；router 只處理輸入、認證與錯誤的 HTTP mapping。Strava 使用相同 writer reservation。
- `runtime/run-controller.mjs` 擁有新增／編輯操作、request identity 與重試 key；DOM adapter 在成功後比對原始表單快照，並以 session identity 阻擋晚到回應。
- `read_models/run_statistics.py` 統一 calendar bounds、日期區間加總與月份比較；以參數保留 current／past／future 語義。
- `docs-check` 遞迴解析本地 Markdown links（排除 fenced code）、檢查 spec sections、Implemented AC completion 與 traceability file existence；歷史 spec 保留原始決策。

## Security and data isolation

- Services/read models 全部以 scalar user_id 限制每個查詢／mutation；HTTP 認證仍是必要條件。
- Writer reservation 不更改 token_version，不建立新 schema，不將 operation key 當成認證。
- Native controller reset 取消舊操作 identity，舊成功／失敗不清空新帳號或新草稿。
- Docker build context 排除 SQLite 主檔、WAL／SHM、DB 備份與備份目錄，不將工作區資料傳給遠端 builder。
- 回歸測試僅使用暫存／記憶體 SQLite、合成 browser 帳號及 mocked LLM/search。

## Migration, rollout, and rollback

- Schema／資料 migration：無，維持 schema 2。
- 上線與 smoke test：`verify-all`、`eval-agent`、CI；正式部署前完成異地備份及隔離還原演練，發布 v3.5.0、shell v26，部署後執行匿名 `release-check`。
- 回滾方式與資料相容性：schema 2 與 v3.4.0 相容，可回滾該 image；重新發布舊來源時仍使用新 shell revision，不還原或覆蓋新業務資料。

## Acceptance criteria

- [x] AC-1：Given 新增請求未完成，When 使用者修改表單或查看月份後收到成功，Then 新草稿保留；未修改表單照常清除，失敗重試與換帳號安全。
- [x] AC-2：Given 同帳號只剩一個鞋款配額，When 不同 session／process 同時新增，Then 只有一筆成功，其他回 409；失敗交易不消耗配額。
- [x] AC-3：Given 不同 app instance 的配額／upload 設定，When 註冊、CRUD 或匯入，Then 各自使用注入值且不互相污染。
- [x] AC-4：Given 既有版本衝突、帳號隔離、刪鞋歷史、重送及里程案例，When 寫入移到 services，Then API 與交易不變；services 無 HTTP dependency。
- [x] AC-5：Given 月底／閏年／跨年／空資料／跨帳號，When 首頁、目標或月報加總，Then 共用邊界正確且月報 YTD 僅一次區間聚合。
- [x] AC-6：Given 本地連結、規格結構或追蹤路徑錯誤，When docs-check 執行，Then 顯示檔案與可修正原因；有效歷史規格通過。
- [x] AC-7：Given v3.5.0 產物，When 完整 browser/PWA 與發布檢查執行，Then module 載入、session cleanup、離線與 API contract 全部通過。

- [x] AC-8：Given 工作區有 SQLite 主檔、sidecars 與備份，When 遠端建置發布，Then Docker context 排除這些資料。

## Test traceability

| Acceptance criterion | Test file / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/run-controller.test.cjs`、`unit_tests/frontend_reliability.cjs` |
| AC-2 / AC-3 | `unit_tests/test_transactional_features.py` |
| AC-4 | `unit_tests/test_runs_api.py`、`unit_tests/test_statistics_consistency.py`、`unit_tests/test_request_reliability.py`、`python3 scripts/task.py architecture-check` |
| AC-5 | `unit_tests/test_run_statistics.py`、`unit_tests/test_reports.py`、`unit_tests/test_goals.py` |
| AC-6 | `unit_tests/test_docs_harness.py`、`python3 scripts/task.py docs-check` |
| AC-8 | `unit_tests/test_security_config.py` |
| AC-7 | `python3 scripts/task.py verify-all`、`python3 scripts/task.py release-check --base-url https://running-shoes.fly.dev` |

## Verification record

2026-10-22：`verify-all` 與最終 `verify` 通過。最終來源為 444 Python tests、81 Node tests、
95.14% backend branch coverage；`eval-agent` 10 passed，Ruff、mypy（62 modules）、architecture（37 API method/path pairs）、
secret scan、dependency audit、generated assets 與 docs-check 全部通過。
40 組版面、雙引擎 CRUD／session／SPEC-020 延遲儲存草稿、真實 ASGI/CORS 匿名 release-check、
雙引擎 PWA migration／失敗更新／離線恢復均實際執行，未跳過。
Docker context 的 SQLite sidecar／backup exclusion 另有安全回歸，正式異地快照 checksum 與隔離還原已通過。
CI、tag、image 與正式部署後唯讀檢查的實際結果記錄於 v3.5.0 GitHub Release；備份與帳號內容不公開。
