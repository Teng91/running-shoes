# Test Design Document（TDD）

本文件的 TDD 指 **Test Design Document**。開發流程仍採小步的 test-first／regression-first：
先定義可觀察行為與風險，再實作，最後由 repository harness 與 CI 驗證。

## 1. 測試目標

- 防止帳號隔離、里程交易、備份安全與 API contract 回歸。
- 讓純重構可以證明「程式位置改變，但使用者行為沒有改變」。
- 外部服務不穩定或無網路時，核心測試仍保持確定性。
- 用較少、較快的測試涵蓋多數邏輯，再用 API 與版面測試保護整合邊界。

## 2. 測試層級

```mermaid
flowchart BT
    Unit[Domain unit tests<br/>計算 / parser / export rows]
    API[FastAPI integration tests<br/>auth / isolation / transactions / contracts]
    Frontend[Node frontend regressions<br/>state / escaping / interaction]
    Layout[Playwright layout matrix<br/>Chromium + WebKit]
    E2E[Playwright functional E2E<br/>real FastAPI + temp SQLite]
    Evals[Deterministic agent evals<br/>tool choice / safety]

    Unit --> API
    API --> Frontend
    Frontend --> Layout
    Frontend --> E2E
    API --> Evals
```

下層測試數量較多、速度較快；上層只保留跨模組或瀏覽器才看得到的風險。

## 3. 需求到測試的追蹤矩陣

| 品質需求 | 主要驗證 | 失敗代表 |
| --- | --- | --- |
| 帳號資料隔離 | API tests + security regressions | query 缺少 user scope 或 authorization |
| 帳號切換非同步隔離 | Node transport tests + Chromium/WebKit session E2E | 舊洞察、AI history/retry 或 401 回填／清除新 session |
| 跑步／鞋款／月跑量一致 | transaction 與 edge-case tests | partial commit、差額或 optimistic lock 錯誤 |
| 匯出與備份安全 | export API tests | 格式、欄位、帳號範圍或 secret 洩漏回歸 |
| AI 工具安全與選擇 | agent evals + mocked stream tests | prompt/tool policy 或 fallback 回歸 |
| 前端互動與 XSS 防護 | Node regression tests + 頁面 CSP 雜湊與 browser 違規檢查（SPEC-054） | state、escaping、分頁或錯誤處理回歸；inline script 未被雜湊或出現 inline handler |
| 文件與程式一致 | `docs-check` 清單檢查（SPEC-053）與 API 一覽檢查（SPEC-058） | 新模組、script、環境變數或 API 端點沒有寫進 README／SDD |
| 刪除與匯入身分 | Strava 匯入 API tests + schema 8 升級／回滾 tests（SPEC-055） | 刪除的 Strava 活動被重新匯入、里程重複累加，或回滾失去資料 |
| 統計口徑一致 | read model tests + Node rendering + 前後端門檻比對（SPEC-055／056） | 年度同期比較、退役預估、換鞋門檻或週目標在不同頁面不一致 |
| AI 統計工具 | tool adapter tests + agent evals（SPEC-057） | 工具重算數字、洩漏其他帳號資料、輸出逐日大陣列或意圖未取得對應工具 |
| 固定跑步日誌首頁 | Node startup/lifecycle + Chromium/WebKit SPEC-015 + PWA offline navigation | 舊 activeTab 還原、重開後 agent-mode 殘留、ARIA／手機標籤不同步，或誤清登入與主題 |
| 響應式版面 | Playwright matrix | 特定引擎、尺寸、主題出現重疊／溢出 |
| 元件對齊契約 | 40 組 Chromium/WebKit 排版設定（SPEC-016）+ Node presentation tests | 日期／數字／選單不同高、混用按鈕密度、模型列錯位、圖表起點或數字表頭邊界不齊；覆蓋六個分頁、三個認證表單、全部彈窗、編輯／停用／錯誤／行內輸入 |
| 瀏覽器核心流程 | Playwright E2E + 暫存 SQLite | UI、HTTP 與 persistence 整合回歸 |
| 購鞋欄位歸屬 | Node rendering + Playwright matrix / E2E（SPEC-011） | 跑鞋／支出表頭錯位、尺寸遺失、編輯或退役後購鞋資訊不同步 |
| 編輯快照與衝突 | Node modal tests + 真實 API browser conflict（SPEC-012） | 重新載入後改錯 ID、用新版本提交舊表單，或舊回應關閉新視窗 |
| 共用 SSE 正確性 | Node chunk/UTF-8/CRLF/cancel tests + Chromium/WebKit mock streams | 中斷當成功、錯誤答案進入歷史、重試重複上下文、月報狀態不一致 |
| 退役預估一致性 | `test_forecasting.py` + DOM regression | 清單／分析使用不同公式、預估跨帳號或 N+1 查詢 |
| 按需呈現 | Node render invalidation + browser request/chart counters | 隱藏分頁建立圖表／讀年度日誌、重複繪製或晚到回應重畫隱藏頁 |
| 登入操作與跑鞋視窗競態 | Node + Chromium/WebKit SPEC-013 | 重複登入、舊成功／錯誤覆蓋新 session，或鞋款 mutation 關閉新草稿 |
| 月報時區一致性 | Python UTC serializer / GET / history + browser local formatting | SQLite 無時區值誤作本地時間，讀取與完成時間相差 8 小時 |
| Strava worker 隔離 | `test_strava_worker_keeps_event_loop_responsive` + 原 transaction tests | parse/service 在 event loop 執行、worker 停頓時 loop 也停頓，或交易／隔離回歸 |
| 前端責任拆分 | Node single-responsibility / HTML / SW order + 全分頁 browser matrix | 匯出、目標或圖表函式漏載，或功能重新混合 |
| 模組依賴方向 | `architecture-check` | circular dependency 或重複 API route |
| App composition 隔離 | app factory tests | lifespan 誤用正式 database globals 或設定漂移 |
| API contract | method/path snapshot | endpoint 被意外新增、刪除或改名 |
| Runtime module boundary | architecture check + frontend asset/order regressions | router/service 或 plain-script dependency 再次混合 |
| 備份可恢復性 | backup/restore tests | checksum、integrity、retention、安全快照、殘留 WAL 還原或 busy 鎖失效 |
| 異地備份與隔離演練 | mocked Fly CLI + temporary SQLite（SPEC-014） | 半份備份被發布、checksum 缺失／錯誤、schema／資料遺失、輸出落在 Git 或洩漏遠端內容 |
| 真正 PWA 升級 | `frontend-pwa` local HTTP fixture / Chromium + WebKit | 舊 worker 線上遷移失敗、新版 HTTP／MIME 失敗污染舊 HTML、離線無法載入已安裝 shell、刪除其他 cache 或快取 API |
| Coverage floor | branch coverage ≥ 92% | 測試保護範圍明顯退化 |
| SPEC-017 統計唯一來源 | `test_statistics_consistency.py` + Node + Chromium/WebKit SPEC-017 | 50 日誌＋100 手動變成 120%、清單／分析／匯出成本不一致或支出跨時區偏月 |
| SPEC-017 輸入與完整分頁 | Node + 真實 API 205 筆／browser fixture | 空白清零、只計目前頁、刪鞋後丟失日誌彙總、day 篩選越界或跨帳號 |
| SPEC-017 同名消歧義及效能 | 0／1／12 鞋 query budget + ID scope tests | 任選第一雙、洩漏候選或 N+1 SELECT |
| SPEC-017 跨日與對話框 | Chromium/WebKit `frontend_consistency.cjs` | 日期 max 停在昨日、草稿被重設、Tab 逃出彈窗、inert 未解除導致焦點遺失 |
| SPEC-017 功能生命週期 | native module Node + session E2E | 舊新增回應污染新帳號、遺漏 feature cleanup、隱藏支出仍保留舊帳號內容 |
| SPEC-017 生成與依賴方向 | `build_frontend.py --check` + transitive import tests | CSS／HTML／worker 清單漂移，service 間接依賴 FastAPI 或月報反向解析工具 JSON |
| SPEC-017 PWA 更新 | 實際 worker message／controllerchange + `.mjs` MIME failure | 新版未通知、未確認即重載、錯誤 module MIME 污染離線 shell |
| Secret hygiene | `security-check` | tracked files 包含明確 credential 特徵 |
| 文件與實作一致 | `docs-check` + document contract negative fixtures | 測試數／命令過期、壞連結／anchor、缺 spec sections／Owner、Implemented 未勾選 AC 或測試路徑不存在 |
| SPEC-020 配額與注入 | `unit_tests/test_transactional_features.py` | 不同 app 共用錯誤配額、thread/process 競態突破上限、Strava 與手動上限不一致、upload 設定外洩 |
| SPEC-020 草稿與 state | `unit_tests/frontend/run-controller.test.cjs` + `unit_tests/frontend_reliability.cjs` | 舊成功清除新草稿／月份、controller reset 失效、編輯／重送 key 污染新 session |
| SPEC-020 聚合邊界與效能 | `unit_tests/test_run_statistics.py` | 閏年／跨年／未來／空資料／user scope 錯誤，或月報 YTD 查詢數隨月份增長 |
| SPEC-020 寫入邊界 | architecture constraints + 既有 CRUD／衝突／rollback tests | router 重新擁有 mutation，或 services 穿透 HTTP |
| SPEC-021 認證競態 | `unit_tests/test_auth_concurrency.py` | 舊改密碼請求覆寫新密碼、憑證未撤銷，或獨立程序突破註冊容量／同名回 500 |
| SPEC-021 發布資產數量 | `unit_tests/test_docs_harness.py` + docs-check | README 舊數字或新增 module 未被偵測 |

## 4. 開發流程

PWA fixture 凍結 v3.2.2 worker 進行線上 migration，再測試完整新版 worker 的失敗升級／離線恢復；
Chromium 使用 browser offline emulation，WebKit 使用 fixture transport 斷線（避免 emulation 同時阻止 cache navigation）。
WebKit 的 API probe 另外在 HTTP headers 後截斷 body，讀取完整 JSON 並檢查 server 請求計數，避免 headers 前 TCP 中斷讓 fetch 不結束；沒有降低 API 不可從 worker cache 讀取的要求。
兩者都要求 API network failure、舊 shell 完整、新版恢復及實際 cache key／HTML revision 正確；不連正式站，亦不取代 iPhone 實機驗證。
SPEC-017 增加 native runtime MIME 失敗，以及 worker 完整啟用後提示更新但保留舊 document／草稿的斷言。
Node suites 位於 `unit_tests/frontend/*.test.cjs`，由原有入口載入；共享 source/extraction helpers 不註冊測試。
docs-check 統計所有 suite 的測試數，而非只計入口或以字串命中代替數值情境。

```mermaid
flowchart LR
    Spec[寫 acceptance criteria<br/>列出不變條件] --> Red[新增或確認會保護行為的測試]
    Red --> Implement[最小範圍實作 / 重構]
    Implement --> Fast[執行受影響的快速測試]
    Fast --> Verify[verify / verify-all]
    Verify --> Review[檢查 diff、文件與部署風險]
    Review -->|發現缺口| Spec
```

純程式碼搬移若已有足夠 API regression，可先確認測試會經過被搬移的 endpoint，再重構；
新功能或修 bug 則必須新增能在舊版本失敗的測試。

## 5. Harness 指令

所有平台都使用同一份 `scripts/task.py`。Unix 以 `python3 scripts/task.py <task>` 呼叫，
Windows 可用 `py -3 scripts/task.py <task>`；本機、Coding Agent 與 CI 不依賴特定 shell，
runner 會自行尋找 Windows 或 Unix 的專案虛擬環境。

| 變更類型 | 最少執行 |
| --- | --- |
| 後端／router | `python3 scripts/task.py test-fast` |
| Agent／tools | `python3 scripts/task.py eval-agent`，再執行 `test-fast` |
| 前端邏輯 | `python3 scripts/task.py frontend-test` |
| 版面 | `python3 scripts/task.py frontend-layout` |
| 真實瀏覽器 CRUD | `python3 scripts/task.py frontend-e2e` |
| 架構邊界 | `python3 scripts/task.py architecture-check` |
| Secret／credential 風險 | `python3 scripts/task.py security-check` |
| 文件／harness | `python3 scripts/task.py docs-check` |
| 跨模組或 release | `python3 scripts/task.py verify`；大改動使用 `verify-all` |

SPEC-020 的明確 traceability 見 `docs/specs/020-transactional-features-and-document-contracts.md`。
並行 quota 測試同時使用獨立 SQLite connections 的 thread 與 spawn process，不能由 Python lock 假裝通過。
原生 controller 的 Node 測試直接 import production module；DOM adapter 與兩引擎延遲 POST 驗證新草稿保留。
新增文件檢查的負面 fixture 覆蓋壞本地連結／anchor、合法 encoded/reference links、缺 sections、未完成 AC 與不存在測試檔。

## 6. Definition of Done

SPEC-019 的 traceability：`test_request_reliability.py` 驗證 transaction／並行相同與衝突 payload、quota replay、user scope、schema 1→2 與年度單一 grouped query；
`frontend/reliability.test.cjs` 驗證 timeout headers/body、GET 有限重試、401／寫入不重試、人工重送 key 與年度 endpoint。
`frontend_reliability.cjs` 在 Chromium／WebKit 的真實 storage event 下驗證跨分頁登出／換帳號與未完成請求取消，另驗證獨立錯誤恢復。
`test_release_check.py` 負面 fixture 拒絕錯版本／hash／MIME／schema／API／匿名授權與失敗 browser subprocess。
`frontend-e2e` 會對自己的真實 ASGI server 執行 `python3 scripts/task.py release-check --base-url ...`；正式部署後再以相同命令唯讀檢查。
Playwright 使用 `npm ci` 鎖版，CI browser job 使用相符的官方 noble container（SPEC-022），不在 job 內重跑 apt；`test_task_runner.py` 檢查映像版本／完整 gates／診斷上傳。失敗保留 `.artifacts/browser/` 的 screenshot／trace／error，CI 明確允許 hidden files，僅上傳 browser 子目錄並保留 7 天，不包含正式帳號內容。

- Acceptance criteria 與不變條件已寫清楚。
- 新行為或 bug 有 regression test；純重構由既有 contract tests 覆蓋。
- 測試不讀寫正式 `shoes.db`，也不呼叫真實 LLM／搜尋服務。
- Ruff、mypy、architecture-check、security-check、92% branch coverage 與相關測試通過。
- setup、command、API 行為或架構邊界變更時同步 README／SDD／TDD。
- 修改 frontend templates／CSS／assets manifest 後，先 `python3 scripts/build_frontend.py --write`，再驗證產物零漂移。
- diff 不包含 secret、資料庫備份或與需求無關的使用者變更。


## 7. SPEC-023 具名追蹤與診斷 roundtrip

[規格及具名案例](specs/023-feature-operations-and-application-boundaries.md#test-traceability) 覆蓋月跑量新草稿、跨帳號 stale completion、鞋款編輯草稿與版本、nickname escaping／export／migration、服務隔離／rollback 及部分刷新交錯。
新 spec 每個 AC 的 `file::test` 必須由 AST 或 Node literal title 找到；改名／刪除、只引用檔案或越界路徑都有負例，歷史 spec 仍可使用檔案路徑。

`diagnostics-generate` 在不連伺服器的合成 Chromium context 產生刻意 assertion failure，使用與 browser gates 相同的 capture helper 保存 PNG／Playwright trace ZIP／錯誤文字及 SHA-256 manifest。
CI browser job 上傳專用 artifact，`diagnostics-roundtrip` job 下載至 `.artifacts/browser/roundtrip/` 再執行 `diagnostics-verify`；檢查檔案身分、路徑、checksum、PNG magic、ZIP integrity、trace 和錯誤中的合成標記。
這個演練不需要帳號、正式網站或 secrets；真正的 browser regression 失敗仍另傳原本 diagnostics，且仍讓 pipeline 失敗。

## 8. SPEC-024 草稿轉移、資源合併與逾時收尾

[具名追蹤](specs/024-draft-rebase-resource-store-and-browser-deadlines.md#test-traceability) 對應下列風險：

| 風險 | 驗證 |
| --- | --- |
| 退役／現役後再次儲存保留草稿撤銷狀態 | Node 直接執行 ShoeModal，雙向狀態轉移、dirty fields／CAS；`frontend_drafts.cjs` Chromium／WebKit 真實 DOM 延遲退役後儲存暱稱 |
| 目標失焦重繪或晚到成功覆蓋草稿 | Node baseline／acknowledge／reset；雙引擎切主題、延遲儲存期間改值及第二次儲存版本 |
| 同資源重複讀取、舊 session／月份回填 | Native resource store coalescing、mutation invalidation、key／session 失效、只接受一次及成功值快取 |
| 某來源失敗阻擋其他資料或錯誤被隱藏 | Native 及 core adapter tests，獨立成功／錯誤與相關 cache hooks |
| screenshot／trace／close 卡住 | Node 注入永不完成的 promises，以短 deadline 驗證原始文字先落檔及 cleanup 仍繼續 |
| browser 子程序完全停頓 | Python 真實合成 sleep 程序，驗證 timeout 回 124、文字診斷、另開 process group 的 child 也收尾 |
| CI 單一 gate 卡住需全跑 | Workflow contract 驗證三個獨立 jobs、各自 gate／watchdog／取消時產物上傳；PWA artifact 下載驗證內容 |

PWA API probe 10 秒、worker update 外層 20 秒（瀏覽器內 statechange timer 15 秒，與 registration.update 一起等待，避免未處理的 timeout）。
Layout 每引擎 300 秒、PWA 每引擎 120 秒，E2E 真實 CRUD 90 秒／各 feature stage 60 秒，release 每引擎 90 秒。
Trace 啟動 10 秒；失敗 capture 的 screenshot／trace 各 5 秒，context／browser close 各 5 秒。
外層 layout／E2E／PWA／release browser watchdog 分別 660／420／300／240 秒；超時本身屬失敗，不可視為通過。
完全卡死時可能只有 watchdog/error 文字；CI 失敗／取消使用 `always()` 嘗試上傳已有產物，不保證取消的 runner 還能生成 trace。
三個 browser jobs 不互相依賴，僅 `diagnostics-roundtrip` 依賴 `frontend-pwa`。

## 9. SPEC-025 匯入交錯、逐資源交付與 SQL 上界

- Node `strava-resources.test.cjs` 鎖定刪鞋選單的空白 sentinel、Strava 視窗／revision／session、重複匯入、歷史失效與先完成來源的交付；鞋款移動前的暱稱／分類草稿在新版本上再次儲存。
- `frontend_strava_ownership.cjs` 在 Chromium／WebKit 使用合成 API 與可控制的延遲：跨日編輯刪鞋日誌、退役前暱稱草稿、舊匯入成功／失敗遇到替換預覽、同視窗改檔避免重複提交、舊 GET 晚於新歷史，以及慢 goal 不遮住已完成 runs。既有 SPEC-024 等待期間草稿測試保留。
- `test_shoe_analytics_sql_is_bounded_and_user_scoped` 比對每鞋 403 筆合成歷史的完整 totals／distinct days／first-last／30-90 天／12 月／recent12 與單鞋／批次相容性。SQL 固定三次、禁止載入 Run entities；外帳號偽 legacy row、刪鞋及空資料隔離皆檢查。AI 摘要仍維持既有 constant query budget，省略不使用的 detail queries。
- `worker_update.cjs` 用可控制的 EventTarget 測試已在 installing 的 candidate 與 update 卡住的診斷。真實 PWA gate 持有 candidate 資產、先啟動安裝再附加 observer，釋放後驗證啟用；HTTP／MIME／宣告長度截斷／版本不符皆必須拒絕候選安裝並保留舊離線 shell。
- Worker installer Node 測試包含未壓縮截斷拒收、完整回應、無長度及壓縮回應，避免把 wire／decoded 長度混用。失敗 trace、截圖與文字仍先落檔並受限時收尾。
- 具名 AC 對應見 SPEC-025；發布前執行 verify-all，不以重跑或跳過瀏覽器代替通過；正式站 release-check 匿名唯讀。

- v3.7.1 PWA gate 每次 offline→online 前明確呼叫 registration.update，要求 10 秒內失敗。WebKit fixture 的 worker script 回 503，API 回截斷 JSON、其他網路請求仍中斷；測試保留真正的快取離線重載與每種失敗升級，避免一個背景 worker HTTP 重試卡住後續候選。

- v3.7.2 的 goal 首次初始化案例固定持有 switchTab 的第一個 animation frame，在填入 180 並失焦後釋放、切換主題，再驗證儲存。Node 另驗證晚到的 goal resource 不覆寫該草稿；覆蓋首次互動界線，不能只等待初次 render 完成後才測草稿。

## 10. SPEC-026 行內 DOM 與生成順序

- `frontend/resource-editing.test.cjs` 驗證新增表單的刪鞋 sentinel、table DOM 延後替換、原版本提交、session 取消 blur、依資源失效、三種衍生讀取合併／失效，以及 Strava 視窗配對鎖。
- `frontend_resource_editing.cjs` 納入 `frontend-e2e`，在 Chromium／WebKit 以合成 HTTP 與固定時鐘驗證鞋款／月跑量輸入 `1` 時釋放背景 goal、主題及同資源刷新仍無 PUT，完成 `180` 並 Enter 才提交；新增跑步刪鞋、配對成功／失敗，以及 annual pending 在重繪時不重發。
- `test_report_generations.py` 使用獨立 session 與暫存 SQLite，mock text stream；覆蓋兩種完成順序、新生成空內容／model error／未知錯誤／取消、保存失敗、user/month 隔離、並行 writer，以及 schema 3→4 重複升級不改寫既有報告。
- 切換分頁後等待實際 DOM 更新（被刪選項消失），再斷言空選擇；不以 `switchTab` 同步返回推論下一 frame 已完成，也不放寬錯誤鞋款斷言。
- 新版資源 dispatch 在 microtask 前失效時不發 HTTP；session／月份 fixture 等候真正發送後再切換，分別驗證發送前取消及 in-flight 晚到回應。
- `architecture-check` 將月報 router 納入禁止交易／mutation 的檢查；services 不依賴 HTTP／LLM adapter。發布依序要求完整本機驗證、main／tag 全 CI、失敗產物 roundtrip、正式備份隔離還原與部署後匿名 release-check。測試不接觸正式資料或模型。

## 11. SPEC-027 可恢復工作區

| 邊界 | 具名驗證 |
| --- | --- |
| 帳號分區、跨重開草稿、原版本 | `unit_tests/frontend/workspace.test.cjs::SPEC-027 drafts and cached resources stay within their account` |
| 佇列與草稿的原子接收 | `unit_tests/frontend/workspace.test.cjs::SPEC-027 queue acceptance consumes only its draft atomically before a crash` |
| 跨分頁、回應遺失、lease 回收 | `unit_tests/frontend/workspace.test.cjs::SPEC-027 durable queue survives lost responses and competing consumers`、`SPEC-027 leases prevent parallel consumers and recover after a crash` |
| 本機配額失敗、登入過期、刪鞋 | `unit_tests/frontend/workspace.test.cjs` 的 failed persistence／expired auth／missing shoes 案例 |
| 匯出讀取快照、還原原子性、去重、預覽失效、增量來源與 tombstone | `unit_tests/test_account_restore.py`；只使用 `workspace_helpers.py` 暫存 SQLite |
| 里程與復原版本／配額、不可重用主鍵 | `unit_tests/test_history.py` |
| 操作回執、跨連線競態、legacy 相容 | `unit_tests/test_operations.py` |
| 真實離線重開、帳號切換、合併 UI、誤刪復原 | `unit_tests/frontend_workspace.cjs`；`frontend-e2e` 中 Chromium／WebKit 均執行，使用暫存 FastAPI 與合成帳號，真實 IndexedDB／service worker |

`frontend-layout` 自動遍歷全部七個彈窗，資料與同步另填入長訊息／blocked 配對控制項，仍跑 40 組引擎／主題／尺寸設定。`verify-all` 包含完整 PWA 升級／離線 shell 驗證；測試不得連正式站、使用真帳號或寫入工作區 shoes.db。發布仍須另外正式備份、隔離還原、匿名 release-check，通過本機測試不等同已部署。

SPEC-029 更新模式的具名測試見 [資料搬移規格](specs/029-account-data-transfer.md)：覆蓋來源 ID／Strava 辨識、跨鞋款／月份更新、額外資料及跑步 tombstone 保留、配額、模式 hash、舊預覽、交易回滾、月報生成撤銷與 user isolation。雙引擎工作區 E2E 由 UI 實際下載 JSON、匯入至另一合成帳號，修改來源後再以 update 匯入，驗證資料及里程；Node 測試另確認模式／視窗所有權、取消更新與下載失敗回饋。

[SPEC-030](specs/030-import-operation-isolation.md) 增加可重現的亂序預覽、原生 controller 視窗／session 與清理、舊清除不影響新帳號、等待期間的新輸入、相同內容匯入的版本／revision／audit 不變，以及 schema 5→6 與回滾腳本的資料保持測試。E2E 在兩引擎延遲舊預覽至新預覽之後才送達，仍可確認新 token；並延遲清除完成、換帳號輸入後才釋放，驗證新草稿不被清空。


SPEC-032：合成資料驗證歷史筆數上限（v4.7.3 起 10,000／10,001）邊界、UTF-8 位元組及含秘密拒絕、明確省略歷史的 HTTP 下載／匯入契約與帳號隔離。差異預覽對照實際版本變動、額外本機跑步及刪除 tombstone；Node 與 Chromium／WebKit 驗證提交成功後讀取失敗只重試讀取、換帳號／視窗不污染新狀態。SPEC-031 回歸確保月曆不顯示次數且保留日期操作。

## SPEC-033 復原與同步組合流程

[規格與具名案例](specs/033-recovery-and-sync-identity.md) 覆蓋同帳號舊檔保留刪除、多次復原後外部及原生別名、跨帳號隔離、匯入歷史不可偽造本機刪除、commit 失敗原子 rollback，以及重新登入接手租約與已提交操作的讀取重試。雙引擎 workspace E2E 在 origin 注入核心 GET 失敗，驗證離線同步與刪除復原的成功提示及純讀取重試。

## SPEC-034 可攜來源與跨分頁同步

[規格與具名案例](specs/034-portable-recovery-and-sync-refresh.md) 驗證來源及接收者連續復原、省略歷史仍攜帶來源鍵、tombstone、別名衝突／全域容量／格式拒絕、v1/v2 指紋相容，以及小數累積與 legacy Float 尾差的 no-op 版本／audit 不變。Node 覆蓋手動空佇列讀取、通知失敗不重排已確認操作、刷新中的新通知及外帳號忽略；雙引擎 workspace E2E 操作 v3 來源復原檔及真實 BroadcastChannel／IndexedDB 多分頁，確認雲端讀取與表單草稿保留。

## SPEC-047 程式審查修正、有界歷史與模組解耦

[規格與具名案例](specs/047-review-hardening-and-decoupling.md)

- **Strava 日期**：參數化驗證中英文 12 小時制 UTC 時間戳轉成台灣日期。API 案例確認重新匯入只修正仍停在舊 UTC 日期的跑步、保留手動日期、月跑量跨月移動且第二次為 no-op。
- **Migration 與保留**：以檔案型 SQLite 驗證過期 trigger 會被重建、每帳號保留上限只刪自己最舊的資料、稽核清理後墓碑仍保護已刪跑步，以及 schema 7 回填墓碑、移除舊回執表與 7 → 6 回滾腳本可往返。
- **限流**：以注入的 settings 調整限額，驗證超限請求整筆回滾不計數、不 commit 請求 session，以及「來源＋帳號」與「帳號」兩層登入鎖定。
- **import 與密鑰**：子行程確認匯入 backend 模組不建立資料庫目錄；正式環境拒絕缺少或過短的密鑰。
- **前端**：Node 確認 markup 與動態列除了樣式表 `onload` 沒有 inline 事件、每個 `data-*` 動作都有唯一註冊、巢狀元素只執行最近的動作。
- **v4.7.1 修訂**：以小上限重現匯入歷史擠掉本機紀錄（修正前失敗）；啟動清除各帳號過期預覽；年目標在 API、資料庫與匯出都是兩位小數；冷卻設定不超過限流紀錄保留時間；歷史復原四個衝突分支與 readiness 三種 503。
- **v4.7.3 修訂**：以真實匯出列形狀放大到帳號配額（5,000 筆跑步、10,000 筆保留歷史、120 份月報），確認仍在 10 MiB 內且可解析；HTTP 驗證預覽的每帳號與全站限流、忙碌時立即回 429 且不解析、不儲存、不計數；預覽在不建立第二份 Python 副本的情況下存下相同內容並可套用。
- **v4.7.2 修訂**：以凍結時間驗證帳號備份檔名使用台灣日期；參數化七種 OpenAI SDK 錯誤，確認使用者訊息不含原始內容、識別碼與網址，而 log 保有細節；架構測試禁止 router 自行查詢，read model 測試確認本人範圍與排序。
- **測試資源**：`conftest.py` 的 `disposing_engines()` 在每個測試結束時關閉它開啟的 engine，有專門測試確認原始連線已關閉；覆蓋率執行不再出現 ResourceWarning。

## SPEC-046 冷啟動加速、購買日前跑步提醒與瀏覽器偵測

[規格與具名案例](specs/046-cold-start-purchase-date-warnings-and-browser-probe.md) 以子行程驗證匯入 `backend.main` 不載入 `openai`、Dockerfile 預先編譯 backend；Python 驗證 Strava 預覽回傳各群組最早日期；Node 驗證跑步表單與 Strava 配對在早於購買日時提醒、當天不提醒且不阻擋儲存；任務執行器與 Stop hook 以假的啟動探測驗證缺系統函式庫時只探測一次並跳過，release-check 仍拒絕。

## SPEC-045 清除舊空表與已刪除鞋款標籤

[規格與具名案例](specs/045-legacy-tables-and-deleted-shoe-labels.md) 以記憶體資料庫驗證 migration 兩次執行後只刪除空的舊表與其索引、仍有資料的舊表保留、schema version 不變；Node 驗證已刪除鞋款合併為單一「已刪除的鞋款」系列、月合計不變且無內部編號，日曆標籤為「已刪除」。發布前另以正式備份的記憶體副本演練：19 → 17 張表，業務資料雜湊不變。

## SPEC-044 月跑量年度目標總覽

[規格與具名案例](specs/044-annual-goal-overview.md) 以暫存資料庫驗證 12 個月只計本人日誌、今天之後的跑步與手動調整不計入、過去／本月／未來與達標標記、今天應達里程與訓練趨勢目標線相同，以及過去、未來、未啟用年份與 API 帳號隔離；Node 驗證沒有月份選單、12 格狀態與年度文字、設定預設收起、取消還原及草稿自動展開；`frontend-layout` 在 40 組設定檢查 12／6 欄月份格與展開後的設定表單，`frontend-e2e` 在展開的設定中驗證草稿與版本流程。

## SPEC-043 支出併入跑鞋分頁

[規格與具名案例](specs/043-spending-in-shoes-tab.md) 以 Node 驗證沒有支出分頁、支出卡片／圖表／明細位於跑鞋分頁、支出資料晚到時只在跑鞋分頁繪製、跑鞋異動只讓相關面板失效；`frontend-layout` 檢查 4 欄底部分頁列與跑鞋分頁 8 張圖，`frontend-e2e` 在跑鞋分頁驗證支出重試與購買明細。

## SPEC-042 移除跑步摘要卡、距離分布配色與 AI 分頁合併

[規格與具名案例](specs/042-run-log-tiles-distance-colors-and-ai-tab.md) 以暫存資料庫驗證首頁摘要只回傳選鞋建議、距離分段在 20 km 邊界的歸屬；Node 驗證跑步日誌沒有摘要卡與個人紀錄、選鞋建議仍可選入、距離分布五色、AI 分頁只有一個按鈕且月報經面板切換開啟；`frontend-layout` 透過切換開啟月報並檢查 5 欄底部分頁列。

## SPEC-040 年度回顧、首頁摘要與手機導覽

[規格與具名案例](specs/040-highlights-review-and-mobile-navigation.md) 以暫存資料庫驗證累計里程碑級距、選鞋建議排序（未穿過優先、快到退役排最後、排除退役）、本週／連續／本月目標與近 30 天成就、年度回顧（前一年比較、排除刪除鞋花費、進行中與未來年份）、距離分桶與跨使用者隔離。Node 驗證摘要卡、成就與名稱 escape、「選這雙」觸發草稿更新、鞋款顏色不受清單順序影響、年度回顧版面與錯誤資料不快取、唯一年份選單重繪所有年度區塊、距離分布與手機底部分頁列；`frontend-layout` 在 40 組版面檢查底部分頁列固定在底部且無溢出。

## SPEC-039 移除月跑量紀錄表

[規格與具名案例](specs/039-compact-monthly-records.md) 以 Node 驗證月跑量分頁沒有紀錄表、新增表單與編輯對話框且不載入 `app-monthly.js`，以及舊版本的月份新增／編輯草稿在恢復本機工作區時被捨棄、其他草稿保留、舊草稿鍵不開啟對話框；月份編輯相關的 Node 與瀏覽器案例隨功能移除，SPEC-023 AC-1 改由共用 operation owner 測試覆蓋。

## SPEC-038 訓練趨勢與跑鞋輪替

[規格與具名案例](specs/038-training-trends-and-shoe-rotation.md) 以暫存資料庫驗證同日合計、週一起始與連續天數、前 4 週平均的暴增門檻與最小基數、進行中週次、年度目標線與推估、未來／過去年份邊界、輪替時間軸排序、排除退役與刪除鞋款、閒置，以及跨使用者隔離與 401／422。Node 驗證熱力圖分級與空白格、暴增週次顏色、目標說明、時間軸鞋名與閒置提醒、格式錯誤不快取，以及跑步／跑鞋異動後重新讀取；`frontend-layout` 檢查 40 組版面沒有水平溢出。

## SPEC-037 本機工作區資料庫自動重新連線

[規格與具名案例](specs/037-reconnecting-local-workspace-store.md) 以 Node 模擬 IndexedDB，驗證連線無 `close` 事件靜默關閉與有 `close` 事件兩種情況都會重新開啟並讀寫成功，應用程式驗證錯誤不重試；雙引擎 workspace E2E 以 `waitForAsync` 真正等待離線重新整理後的帳號、跑鞋與佇列恢復。

## SPEC-036 安全強化與跨平台鎖定檔

[規格與具名案例](specs/036-security-hardening-and-portable-locks.md) 以無 `document` 的 Node context 驗證 Markdown 只經 `DOMParser` 解析並移除可執行標記與非 allowlist 屬性；API 測試確認被 IP／帳號上限拒絕的請求不增加全站 bucket、密碼錯誤只鎖定該帳號、未知帳號仍執行 bcrypt；鎖定檔測試確認 `uvloop` 與 `colorama` 的平台條件。

## SPEC-048 push 到 main 自動部署與發版

[規格與具名案例](specs/048-push-to-main-deploy-and-release.md) 以文字解析 workflow：部署只在 main 且全部測試通過後執行、release-check 與發版依序在後；只有部署 job 取得 `FLY_API_TOKEN` 且不執行專案套件，只有發版 job 可寫入；部署前快照的遠端指令、資料庫路徑與成功訊息和 Dockerfile／`database_backup.py` 一致；實際執行發版腳本內嵌的 CHANGELOG 擷取，比對目前版本段落與缺段落的 commit 備援；main 執行序列化不取消；browser 與部署後檢查重跑一次並警告。實際部署由 main 上的 GitHub Actions 驗證。

## SPEC-049 新版部署提示與主動偵測

[規格與具名案例](specs/049-pwa-update-prompt.md) 以 Node 驗證不同版本只顯示提示、不自動重新載入、稍後與再次提示、確認後只重新載入一次；以假時間與事件驗證前景、焦點、連線恢復與 30 分鐘檢查、60 秒合併、隱藏與離線不檢查及失敗不拋錯。`frontend-pwa` 在 Chromium／WebKit 的舊版 worker 遷移與完整升級中，確認提示出現時仍是舊版，按下更新後才載入新 shell。

## SPEC-059 在安全時自動套用新版

[規格與具名案例](specs/059-automatic-updates-at-safe-moments.md) 以 Node 假時間、假可見度與假 service worker 訊息驗證：剛回到前景未操作、在背景、閒置 5 分鐘時自動重新載入一次；AI 回答、月報、請求、行內編輯、彈窗、AI 輸入框與登入表單的文字都會延後，直到下一次檢查；自動重新載入後仍是舊版時改為只顯示提示。AI 對話以假 sessionStorage 驗證只為同一帳號還原、資料格式錯誤或換帳號時捨棄。`frontend-pwa` 在 Chromium／WebKit 的真實 service worker 升級中，確認使用中的頁面只顯示提示，切到背景後自動換成新版 shell。

## SPEC-061 每次推送都跑 CI 與 main 保護

[規格與具名案例](specs/061-ci-on-every-push-and-protected-main.md) 以文字解析 workflow：觸發條件是不限分支的 push、pull request、每週排程與手動執行，沒有 `paths-ignore`；部署條件仍只有 main 的 push／手動執行；main 以外的 ref 由較新的執行取消舊的，main 不取消。ruleset 由 `.github/rulesets/main.json` 描述，Python 測試確認它要求 PR、必要檢查與 workflow 的 5 個測試 job 完全一致、禁止刪除與 force push，且沒有繞過名單。

## SPEC-062 Strava 匯入辨識手動輸入的跑步

[規格與具名案例](specs/062-strava-import-matches-manual-runs.md) 以純函式測試涵蓋四捨五入的距離、已有時間、配速不合理的時間、同天多筆一對一與無法一對一、距離差太多、當天沒有手動紀錄、已知活動與 CSV 重複列。API 測試以兩個帳號的資料驗證預覽與匯入的筆數一致、只新增沒手動輸入的日子、連結的紀錄補上時間但不覆寫既有時間、跑鞋與月跑量只增加新匯入的距離、另一個帳號的同日紀錄不參與配對，以及再次匯入或刪除後不再新增。Node 以 vm 驗證預覽說明與只有連結時仍可匯入。

## SPEC-060 跑步時間與配速

[規格與具名案例](specs/060-run-duration-and-pace.md) 以 API 測試新增、只更新、清除與拒絕不合理的跑步時間，確認回應的配速；以兩個帳號的資料驗證月份摘要與單雙鞋分析的時間加權平均配速。Strava 測試使用真實繁中匯出的欄位排列（重複的「經過時間」「距離」），驗證移動時間、經過時間備援與時間不可用時照常匯入；重新匯入只補缺少且合理的時間、不覆寫既有時間，也不動另一個帳號的同一活動。備份測試涵蓋 v4 往返、v3 帶時間被拒、合併不清除時間與刪除復原；暫存 SQLite 驗證 9 → 8 回滾腳本的守衛、保留資料與再升級。Node 以 vm 驗證時間輸入格式、即時配速提示、新增／編輯送出的 `duration_seconds`、列表與卡片的配速，以及只補時間的 Strava 匯入仍可執行；Python 測試確保前後端的配速上下限一致。

## SPEC-055 資料正確性修正與 Strava 刪除記憶

[規格與具名案例](specs/055-correctness-fixes-and-strava-deletions.md)：
- API 測試匯入、刪除再匯入同一份 CSV，確認預覽與結果計入刪除筆數、不建立跑步也不加里程，另一個帳號不受影響。
- 以暫存 SQLite 把 tombstone 的活動 ID 清空、marker 改回 7 後重新啟動，確認從稽核紀錄回填；8 → 7 回滾腳本有守衛、保留資料並可再升級。
- read model 測試涵蓋年度同期比較（含 2/29）、已退役鞋的預估，以及 95%／85%／79.9% 在提醒、壽命狀態與前端常數的一致門檻。
- Node 測試以 vm 執行提醒、跑步日誌卡片、單鞋分析與 Strava 預覽文字，並檢查登入欄位的 `autocomplete` 值。

## SPEC-056 週目標、每週最長一次與星期幾分析

[規格與具名案例](specs/056-weekly-goal-long-run-and-weekday-analysis.md) 以 pytest 驗證週目標斜率、同日多跑的最長一次、達標判斷與只計當年的星期分布；Node 以假 Chart 驗證週目標虛線與說明、兩張新圖的資料與文字，以及未來年份不建立圖表。版面矩陣把月跑量分頁的圖表數改為 8，檢查新圖不溢出、不被擠壓。v4.14.1 修訂另驗證進行中的週不畫平均點與 0 km 長跑點、近期平均只用已結束的週、週目標說明的計算依據，以及以跑步次數計算的平均每次距離。

## SPEC-057 AI 助手使用現有統計

[規格與具名案例](specs/057-ai-tools-for-native-statistics.md) 以兩個帳號的資料呼叫 4 個新工具，比對 read model 數字、鞋名與輸出裁剪，確認另一個帳號的資料不出現；`year` 參數的各種不合法值都退回今年。Agent eval 新增目標、暴增、回顧與支出 4 個意圖案例。

## SPEC-058 README API 一覽與版本說明分離

[規格與具名案例](specs/058-readme-api-reference-and-release-notes.md) 以暫存 repo 驗證 `api_reference_errors()` 只接受完整的 `` `METHOD /path` ``（較長路徑不能代替），目前的 README 必須列出 contract 的每個端點；`docs/release-notes.md` 的連結由文件契約一併檢查。

## SPEC-053 文件清單一致性與程式整理

[規格與具名案例](specs/053-documentation-inventory-and-hygiene.md)：
- 以暫存 repo 驗證 `inventory_errors()` 會指出 README 目錄樹漏列的模組、列了但不存在的路徑、SDD 沒提到的應用模組，以及 README 沒寫的 `settings.py` 環境變數；目前的 repo 必須全部通過。
- 方框樹解析器以縮排還原巢狀路徑，並忽略註解。
- 回歸案例確認合併後的 legacy tool-call 掃描、共用 `Password` 型別（三個端點、新舊密碼）與只用注入密鑰的認證，行為都不變。
- 前端 helper 以 LF 讀取來源，Windows 的 CRLF checkout 也能通過。

## SPEC-054 安全標頭與頁面 CSP

[規格與具名案例](specs/054-security-headers-and-page-csp.md)：
- Node 測試解析產生的 `index.html`，用 `node:crypto` 重新計算每段 inline script 的 SHA-256，必須與 CSP 完全相同。
- 確認政策位於第一個 script 之前、沒有 `'unsafe-inline'` 或外部來源，模板、產生的列與離線頁也沒有 inline 事件屬性。
- 以 vm 執行樣式表載入器，驗證 preload 在 script 之前或之後完成時都只套用一次。
- pytest 對 JSON、頁面、SPA fallback、script、401、404、422、413 回應檢查安全標頭，確認跨來源請求沒有 CORS 標頭、`.mjs` 在 `nosniff` 下仍是 `text/javascript`。
- `frontend-e2e`、`frontend-layout` 與部署後 `release-check` 以 `trackCspViolations()` 收集真實 Chromium／WebKit 的 CSP 違規，有任何違規即失敗。

## SPEC-052 主畫面與分頁圖示改版

[規格與具名案例](specs/052-app-icon-refresh.md) 以 Node 讀取 PNG 標頭，確認 manifest 宣告的 192／512 圖示與 180px `apple-touch-icon` 的實際尺寸、manifest 圖示可 maskable；比對向量來源 `app-icon.svg` 與 `favicon.svg` 的標誌路徑和介面品牌標誌完全相同，並計算進度環外緣落在半徑 40% 的 maskable 安全區內。模板測試確認 SVG 分頁圖示優先、PNG 備援，且所有圖示都在 service worker 預先快取清單中；`frontend-pwa` 驗證新 shell 版本的升級流程。

## SPEC-051 運動科技風視覺改版

[規格與具名案例](specs/051-sports-tech-visual-refresh.md) 以 Node 解析產生的 `styles.css`，確認圖表程式讀取的每個 `getThemeColor()` token 在暗色與亮色主題都有定義、舊的靛藍／綠色不再寫死；以 token 名稱 stub 驗證磨耗色階門檻、每週跑量與輪替時間軸的配色，以及月曆輸出 `has-run` 與 `--day-load` 而非 inline 顏色。模板測試確認分頁使用線條 SVG 且標籤仍為最後一個 span、英文小標與描邊字以 `content: … / ""` 排除在無障礙名稱外，手機標題列不使用會改變 fixed 定位的 filter／transform。`frontend-layout` 的 40 組版面確認幾何不變。

## SPEC-050 近 90 天月均里程佔比

[規格與具名案例](specs/050-recent-shoe-share.md) 以 API 測試確認跑鞋清單的 `actual_monthly_km_90_days` 與單鞋分析、批次預估一致，且只計 user-scoped 的近 90 天紀錄；以 Node 執行真實的 `renderCharts()`，確認圓餅圖使用近 90 天月均而非計畫月跑量、中間顯示合計、缺值的鞋沒有扇形；表格測試確認現役表格移除「月跑量」欄與行內編輯，數值欄對齊。`frontend-layout` 與 `frontend-e2e` 驗證 40 組版面與 CRUD 流程的欄數。跑鞋頁在讀取途中收到跑步紀錄／目標資料或離開分頁時的重畫，由 `trends.test.cjs` 以真實 resource store 與 cache hook 驗證。
