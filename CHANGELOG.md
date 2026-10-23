# Changelog

本專案的重要變更依 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.1.0/) 分類，版本號遵循 [Semantic Versioning](https://semver.org/lang/zh-TW/)。完整部署說明另見各版本的 GitHub Release。

## [Unreleased]

## [3.7.1] - 2026-10-23

### Fixed

- v3.7.0 main PWA CI 在 WebKit 的 worker script request 逾時，尚未建立 installing candidate。離線 fixture 改以 HTTP 503 結束背景 register/update，避免 TCP drop 後的重試阻塞 scope job queue。
- 每次恢復在線前驗證 offline registration.update 在 10 秒內失敗，再驗證後續候選更新；保留完整離線 shell、API exclusion、failed upgrades 與 recovery 測試，沒有放寬 deadline 或定向重跑取代修正。
- Asset revision 3.7.1／shell v31；schema 3、44 個 release assets。原 v3.7.0 tag 不改寫。
- verify-all 全數通過：464 Python、105 Node、95.29% backend branch coverage、40 組版面、雙引擎 E2E／PWA 無跳過。

## [3.7.0] - 2026-10-23

### Fixed

- 編輯已刪鞋款日誌跨日刷新仍要求重新選鞋，避免隱性轉移里程。
- Strava 舊匯入成功／失敗不修改替換視窗或新預覽，歷史舊 GET 不覆蓋新匯入結果；同視窗新預覽也不會重複提交。
- 鞋款現役／退役保留操作前與等待期間的未儲存暱稱等欄位，再儲存使用新版本且不撤銷狀態。
- PWA installer 拒絕長度不符的未壓縮 body，防止 WebKit 將截斷資產當作成功並啟用不完整 shell。

### Changed

- 原生 Strava controller 管理視窗、預覽／匯入 operation 與注入 transport/session，歷史納入 resource store。
- 各來源完成即套用並呈現，慢來源不再阻擋可用資料；獨立錯誤、session／request ownership 與精準失效保留。
- 單鞋／批次分析改 SQL 聚合與每鞋 recent12，固定三次 detail queries；AI 摘要只讀 aggregate，不載入完整 Run history。
- PWA observer 涵蓋已在 installing 的 candidate，update／終態共用 deadline，失敗附 worker timeline、fixture 階段與最近 HTTP 請求。
- 同步 README、SPEC-024／025、SDD 主圖、ADR-0008 與測試策略；asset revision 3.7.0／shell v30，schema 仍為 3。
- 本機 verify-all、最新 frontend-test 及 Agent eval 通過：464 Python、105 Node、95.29% backend branch coverage；40 組版面、雙引擎 E2E／PWA 無跳過，10 個 Agent evals 通過。

## [3.6.1] - 2026-10-23

### Fixed

- 鞋款移至退役／現役成功且保留新草稿時，同步模式、月跑量與版本；再次儲存只提交 dirty fields，避免撤銷狀態轉移。
- 目標以草稿 baseline 保護失焦、主題重繪及儲存期間的新修改，換帳號重設。

### Changed

- 原生 resource store 管理 session／request ownership、同資源讀取合併、獨立錯誤與快取失效；core 僅組合 readers、套用結果及呈現。
- WebKit PWA 離線 API probe 在 headers 後截斷 HTTP body，完整讀取 JSON 並檢查 server 計數；probe／worker update 各有期限，避免 fixture TCP 中斷後裸 fetch 長期 pending。
- Layout／CRUD／PWA 拆成獨立 CI jobs，加入階段 deadline、先落檔的原始錯誤、限時 trace／screenshot／close 與外層程序 watchdog。
- 新增 SPEC-024／ADR-0007、雙引擎草稿操作與卡住的 diagnostics／子程序回歸；同步 README module map、SPEC-023 狀態轉移追蹤與測試策略。
- 發布資產 revision 3.6.1／shell v29；schema 維持 3，沒有資料 migration。
- 本機 verify-all：462 Python、95 Node、95.26% backend branch coverage；40 組版面、雙引擎 E2E／PWA 無跳過，10 個 Agent evals 與合成 diagnostics 驗證通過。

## [3.6.0] - 2026-10-23

### Fixed

- 月跑量新增比對完整年月／里程草稿與操作身分；舊回應不清除新草稿或解鎖替換操作。
- 跑步／月跑量／鞋款編輯保留等待期間的新草稿，成功後更新可重用的 CAS 版本。
- 同款鞋選單改用暱稱、購買日期及 ID 辨識；暱稱持久化、輸出 escaping，CSV／XLSX 及帳號備份保留。

### Changed

- 原生 form operations 共用 session、epoch、ownership 與快照；依 mutation 精準重讀資源、清除相關快取並拒絕過期結果。
- 認證與目標寫入移入 services，純 credentials primitives 不依賴 HTTP；architecture gate 納入 auth／goals routers。
- 新增 schema 3 nickname additive migration；使用 asset revision 3.6.0／shell v28。
- 新增 SPEC-023／ADR-0006、具名測試追蹤、CI 合成 diagnostics 產生→上傳→下載驗證，README／SDD／測試策略同步。
- 本機 verify-all：458 Python、88 Node、95.26% backend branch coverage；40 組版面及雙引擎 E2E／PWA 無跳過，Agent evals 10 個通過。

### CI

- Browser job 使用與 lockfile 相符的 Playwright noble container，避免 Ubuntu mirror 下載拖過 job timeout；完整 layout／CRUD／PWA gates 保留。
- 失敗診斷明確包含 hidden files，上傳範圍限制在 .artifacts/browser/。
- 新增 SPEC-022、CI runtime／診斷契約回歸；保留既有 v3.5.1 image 與 tag 不變。

## [3.5.1] - 2026-10-22

### Fixed

- 改密碼以原 hash／登入版本作條件原子更新，過期並行請求回 409，避免覆寫新密碼與漏撤銷憑證。
- 註冊改以 SQLite writer reservation 保護同名／容量檢查與新增，空資料庫及跨程序均適用。
- README 的 shell／worker 資產數量更新為 40；docs-check 以 manifest 推導數量，阻擋後續漂移。

### Documentation and testing

- 新增 SPEC-021 並更新 SDD／ADR／TDD；新增重疊改密碼、spawn process 註冊容量／同名及文件數量負例。
- 核心修正 verify-all 通過：449 Python、81 Node、95.21% backend coverage；40 組版面及雙引擎 E2E／PWA 無跳過。
- 修補版使用 asset revision 3.5.1／shell v27，schema 維持 2。

## [3.5.0] - 2026-10-22

### Fixed

- 延遲的新增跑步成功回應保留等待期間的新日期、里程、鞋款與查看月份；同內容失敗重試沿用 key。
- 鞋款／日誌配額在 SQLite writer reservation 後驗證，跨 thread／process 並行不再突破上限。
- App factory 的 CRUD／註冊／Strava 配額與 upload guard 使用注入設定，不再由 router import-time 常數決定。

### Changed

- 跑步、鞋款、月跑量的 transaction／quota／version／mileage 移入 application services；HTTP adapter 統一轉換 domain errors。
- 原生 run controller 收斂明細、分頁、年度 cache、editor 與新增操作 state，明確注入 transport／session／key factory，boot 與 PWA manifest 整合。
- 日期區間統計共用 read model；月報月份、上月同期、YTD 一次 SQL conditional aggregate，重用於目標進度。
- Schema 維持 2；PWA shell v26／asset revision 3.5.0，與 v3.4.0 資料相容。

### Security

- Docker context 排除 SQLite WAL／SHM、DB 備份與 backups 目錄，防止遠端建置帶入工作區資料。

### Documentation and testing

- README 更正年度彙總說明，新增 SPEC-020／ADR-0005，更新 SDD／TDD／harness map。
- docs-check 驗證本地連結／anchor、spec sections／Owner／狀態、Implemented AC completion 與 traceability 測試檔；補齊早期規格章節並修正不存在的測試引用。
- 新增 thread／spawn process quota、app settings isolation、共享統計 query budget、native controller／DOM 草稿及雙引擎延遲 POST 回歸。
- 本機 verify-all／最終 verify：444 Python、81 Node、95.14% backend coverage；Agent eval 10 passed，40 組版面、雙引擎整合／PWA 均實際執行。

## [3.4.0] - 2026-10-22

### Fixed

- 跑步月份／分頁載入失敗後成功重試會清除自己的錯誤，不掩蓋全域資料載入失敗。
- 同源跨分頁登入／登出／換帳號立即清理舊資料與 pending JSON requests，不刪除其他分頁的新憑證。

### Added

- JSON CRUD／登入 deadline 與 GET 一次有限重試；新增日誌 Idempotency-Key 使用持久化、user-scoped transaction receipt，人工重試／並行重送只累計一次里程，內容衝突回 409。
- 年度每月／每鞋彙總 API，年度圖表不再分頁下載逐筆日誌。
- `release-check --base-url` 固定檢查完整 API、schema、39 個資產 hash／MIME、匿名雙引擎 boot/runtime/cache 與 Chromium 離線重開；E2E 先在真實 ASGI/CORS／暫存 SQLite 執行。

### Changed

- Schema 2 只新增 run_creation_requests，附備份與舊版 rollback marker 相容步驟；舊 API 無 key 仍相容。
- Playwright 1.63.0／npm lockfile 與 npm ci；失敗截圖、trace、錯誤輸出由 CI 保存；Docker context 排除本機 secrets／診斷／npm dependencies。
- PWA shell v25／asset revision 3.4.0；更新 SPEC-019、ADR-0004、SDD、TDD、README 及 harness。

### Testing

- 424 Python／78 Node／10 Agent eval、94.63% branch coverage；40 組排版、兩引擎 CRUD／session／跨分頁／PWA 與真實 ASGI/CORS release gate 通過，沒有跳過瀏覽器。
- 並行相同／衝突 key、quota replay、失敗 transaction、user isolation、schema 1→2，以及錯版本／hash／MIME／schema／API／匿名授權／browser failure 負面測試。

## [3.3.1] - 2026-10-21

### Fixed

- 修正正式站 CORS 的 `Vary: Origin` 造成原生模組離線載入失敗：僅公開同源 shell cache 查詢忽略 Vary，仍精確比對 URL／版本且排除 API。
- 發布 PWA shell v24／asset revision 3.3.1，保留已發布 v3.3.0 tag，不重用有問題的舊快取名稱。

### Testing

- 先以正式站同樣的 CORS response headers 重現離線啟動失敗，再由 Chromium／WebKit PWA regression 驗證修正；新增 SPEC-018，保留失敗升級、版本隔離及 API 不快取測試。

## [3.3.0] - 2026-10-21

### Security

- 發布稽核發現 CA bundle 漏洞，鎖定 certifi 2026.10.19 並重新生成正式／開發依賴雜湊，修補 [PYSEC-2026-4320／GHSA-6q48-6c7w-9gw2](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2)。

### Fixed

- 月跑量空白不再覆寫成零，目標頁與首頁／月報統一只計日誌；跨日更新日期限制且保留目前草稿。
- 刪鞋後年度堆疊圖保留歷史日誌；同名鞋款須消歧義並可用 user-scoped ID 選定。
- 平均月支出改由後端日曆年月計算，不受瀏覽器時區影響；新增跑步晚到回應不污染新帳號。
- 彈窗補齊焦點、Tab／Shift+Tab、Escape 與 aria 語義，修正背景 inert 導致無法返回焦點。

### Changed

- 共用 read models 與 shoe metrics 統一 API／工具／月報／匯出規則；批次鞋款分析消除 N+1。
- 新增日誌整月 summary、目標 progress、支出 summary API；明細每頁 200 筆，月曆／統計完整不截斷。
- 支出按需載入及局部重試；Strava 解析領域錯誤由 router 映射 HTTP，月報不再解析 AI 工具 JSON。
- 各功能註冊生命週期清理，原生 ES module runtime 由相容橋接載入；CSS、彈窗模板、模型、Markdown、工具 schema／parser 與 Node tests 依責任拆分。
- HTML／單一 CSS／PWA 清單由 assets manifest 生成並由 harness 驗證；shell v23 包含 native module MIME 檢查與非強制更新提示。

### Testing

- SPEC-017／ADR-0003 與架構／測試圖更新，新增統計不變量、身份歧義、query budget、跨日、完整分頁及兩引擎鍵盤流程。
- 架構檢查追蹤 transitive／relative imports，防止 service/read models 間接依賴 HTTP 或 AI adapters。

## [3.2.5] - 2026-10-20

### Fixed

- 全前端表單、日期／月份欄位、模型工具列與操作按鈕共用尺寸及行高；修正 WebKit 長選單溢出。
- 彈窗次要／主要操作明確分組，桌面等高對齊、手機換行不留下 spacer；保留新增、現役／退役編輯與停用行為。
- 表格數字與表頭統一右對齊及等寬數字，修正可編輯格的邊界；圖表標題與繪圖區起點、卡片文字節奏一致，跑鞋／支出六張摘要採平衡的三欄或兩欄排列。
- 補齊欄位 label 對應，修正跑鞋分析／Strava 彈窗被通用寬度覆蓋；PWA revision 3.2.5／shell v22。
- 月報狀態與產生按鈕保留間距，已儲存訊息不再顯示錯誤紅色，真正失敗仍有明確錯誤樣式。

### Testing

- 排版矩陣擴為 40 組（雙引擎、亮暗及 10 組尺寸），遍歷六個功能分頁、三個認證表單、全部彈窗及新增／編輯／錯誤／停用／行內輸入。
- 新增控制項、按鈕、工具列、圖表與數字欄位幾何斷言；啟動畫面測試改用明確 gate，避免固定延遲的競態。更新 SPEC-016、SDD、README 與測試矩陣。

## [3.2.4] - 2026-10-20

### Fixed

- 跑步日誌固定為首頁：重新整理、重新開啟與瀏覽器快取還原不再回到上次的 AI 助手或其他分頁。
- 移除分頁持久保存，保留本次使用的正常切換、登入狀態與主題偏好；一般前景／背景切換不強制切頁。
- 更新 PWA asset revision 3.2.4／shell v21，新增啟動、手機標籤／ARIA、重開及 PWA 離線導航回歸測試與 SPEC-015。

## [3.2.3] - 2026-10-20

### Added

- Fly 外部備份 CLI：下載一致 SQLite 快照與 checksum，private staging 驗證及隔離還原通過後才發布完整備份與 manifest；拒絕 Git 目錄，不自動刪除本地備份。
- `database_backup.py drill`：隨機 OS 暫存目的地，比對完整 schema、ordered row digest、各表筆數與 schema version，不接受正式還原目的地。
- `frontend-pwa`：以真正 Chromium／WebKit Service Worker 測試舊版線上 migration、HTTP／MIME 失敗更新、已安裝 shell 離線啟動、恢復更新、API 排除與 scoped cleanup，納入 verify-all／CI。

### Fixed

- PWA navigation 不再將新 HTML 寫入舊版 cache；完整資產安裝成功才接管，失敗保留舊 shell，僅清理本 app cache。
- PWA 安裝逐一讀完資源 response body，避免有限連線池被未消耗的串流佔滿；驗證資源 MIME 與 HTML revision。
- PWA asset revision `3.2.3`、shell v20，確保新版 HTML 與資產一起更新。

## [3.2.2] - 2026-10-20

### Fixed

- 登入／註冊／更改密碼加入共用操作鎖、取消與過期回應隔離；舊請求不能覆蓋新帳號或 loading 狀態。
- 跑鞋新增、編輯、刪除與移動以視窗 context 保存版本及 session，防止重送和晚到回應關閉新草稿。
- 月報 GET／歷史／串流統一輸出帶時區 UTC，讀取與生成都使用同一本地時間格式。

### Changed

- Strava 上傳後的 CSV／filter／DB service 工作移入 worker thread，保留原交易與帳號隔離。
- 拆出匯出、目標設定、跑鞋圖表與月跑量圖表，保留 plain-script 契約與原版面。
- PWA shell v19、asset revision 3.2.2 納入四個新增 modules。
- 新增 SPEC-013，更新 SDD、harness module 清單與 Node／Python／雙引擎回歸測試。

## [3.2.1] - 2026-10-20

### Fixed

- 跑步／月跑量編輯保存原始 ID、版本及 session，避免資料重新載入後修改錯筆或覆蓋較新內容；提交鎖與回應更新以視窗為單位。
- AI 串流只有成功 done 才保存完整對話；錯誤、提前 EOF 或連線中斷保留可見內容並提供重試，不污染歷史。
- 清單、退役時間軸與單鞋分析共用後端預估及來源，批次查詢不產生逐鞋 N+1。

### Changed

- 抽出 `app-streams.js`，共用認證 SSE 檢查、解碼、取消及 terminal state。
- 圖表按 active panel 載入、快取及失效，資料／主題更新不重畫隱藏分頁；年度跑步資料按需載入。
- PWA cache v18、asset revision `3.2.1` 納入新 module，避免混用舊版 shell。
- 新增 SPEC-012、模組圖、回歸追蹤矩陣與 deterministic Node／SQLite／雙引擎 browser 測試。

## [3.2.0] - 2026-10-19

### Changed

- 現役與退役跑鞋清單移除尺寸、買價、原價、折數四欄，保留使用指標與分析／編輯操作。
- 支出明細新增尺寸，集中呈現購鞋資訊；既有資料、編輯表單、匯出及成本計算保持不變。
- 無尺寸或無原價時以「—」呈現，不再顯示無意義的「—%」。
- 靜態資產版本更新為 3.2.0，PWA app shell cache 更新為 v17。

### Documentation

- 新增 SPEC-011，更新呈現責任說明、README、測試矩陣及欄位／資料持續性回歸測試。

## [3.1.0] - 2026-10-19

### Fixed

- SQLite 還原改用獨占鎖與 backup API，避免殘留 WAL 重播舊資料；拒絕忙碌目標、保留安全快照並驗證還原結果。
- 洞察快取綁定登入 session，登出清空快取與畫面，拒絕上一帳號的延遲分析回應。
- 登出中止 AI 串流、清除對話與重試內容並解鎖輸入，防止舊串流污染下一帳號。
- 統一認證回應與 body 的 session 檢查，舊請求 401 不再清除新登入；目前 session 過期仍正常登出。

### Changed

- 靜態資產版本更新為 3.1.0，Service Worker app shell 更新為 v16。
- 新增 WAL crash／busy restore、HTTP 競態與 Chromium/WebKit 帳號切換回歸測試。

### Documentation

- 新增 SPEC-010、session 隔離時序圖，更新備份操作、測試追蹤矩陣與驗證基線。

## [2.14.0] - 2026-10-19

### Changed

- 將前端啟動、state、API、認證、跑步洞察與 Strava UI 拆成獨立 module，保持 plain-script 載入與既有互動相容。
- 將 Strava upload router、匯入 transaction 與 run CRUD 分離。
- 將 analytics、exports、spending HTTP routes 分離，CSV／XLSX／帳號備份生成移入 framework-independent service。
- 將 Agent query planner、tool dispatcher、SSE protocol 與 runner 分離。
- Service Worker app shell 升級為 v11，納入所有新增前端 module。

### Documentation

- 新增 SPEC-006、前端 module 圖、PWA／Fly runtime 圖與集中式 changelog。
- 補齊 v2.13.0 的 app factory／typed settings release history。

## [2.13.1] - 2026-10-19

### Fixed

- 讓 PWA 啟動畫面在舊快取與冷啟動時更早出現。
- 登出與重新登入時清除帳密欄位，避免不同帳號共用裝置時殘留表單內容。

## [2.13.0] - 2026-10-19

### Added

- 新增 PWA 冷啟動 loading、逾時與重試狀態。

### Changed

- 導入可注入的 FastAPI app factory、typed settings 與最小 ASGI entry point。
- 將所有 HTTP endpoints 收斂至 feature routers，`backend/main.py` route budget 降為零。

## [2.12.0] - 2026-10-18

### Changed

- 強化資料載入、API 邊界、工程 harness 與架構驗證。

[3.4.0]: https://github.com/Teng91/running-shoes/releases/tag/v3.4.0
[3.3.1]: https://github.com/Teng91/running-shoes/releases/tag/v3.3.1
[3.3.0]: https://github.com/Teng91/running-shoes/releases/tag/v3.3.0
[3.2.5]: https://github.com/Teng91/running-shoes/releases/tag/v3.2.5
[3.2.4]: https://github.com/Teng91/running-shoes/releases/tag/v3.2.4
[3.2.3]: https://github.com/Teng91/running-shoes/releases/tag/v3.2.3
[3.2.2]: https://github.com/Teng91/running-shoes/releases/tag/v3.2.2
[3.2.1]: https://github.com/Teng91/running-shoes/releases/tag/v3.2.1
[3.2.0]: https://github.com/Teng91/running-shoes/releases/tag/v3.2.0
[3.1.0]: https://github.com/Teng91/running-shoes/releases/tag/v3.1.0
[2.14.0]: https://github.com/Teng91/running-shoes/releases/tag/v2.14.0
[2.13.1]: https://github.com/Teng91/running-shoes/releases/tag/v2.13.1
[2.13.0]: https://github.com/Teng91/running-shoes/releases/tag/v2.13.0
[2.12.0]: https://github.com/Teng91/running-shoes/releases/tag/v2.12.0

[3.5.0]: https://github.com/Teng91/running-shoes/releases/tag/v3.5.0
