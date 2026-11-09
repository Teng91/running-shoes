# Changelog

## [Unreleased]

## [4.4.0] - 2026-11-09

### Changed
- 支出併入跑鞋分頁（SPEC-043）：移除「支出」分頁，支出卡片、年度支出總覽、年度月支出與支出明細移到跑鞋分頁最下方，內容不變；導覽剩 4 個分頁，手機底部分頁列 4 欄。Asset 4.4.0／shell v50。

## [4.3.0] - 2026-11-09

### Changed
- 跑步日誌移除頂端四張摘要卡（本週、連續跑步、本月目標、累計跑量）、里程碑標籤與個人紀錄；保留「今天穿哪雙」。`GET /api/analytics/home` 只回傳選鞋建議（SPEC-042）。
- 每雙鞋的距離分布改為 5 km 一段（<5、5–10、10–15、15–20、≥20 km），依序以紅、黃、綠、藍、紫標示。
- AI 助手與月報合併為一個「AI」分頁，面板上方切換「對話／月報」；手機底部分頁列改為 5 欄。
- Asset 4.3.0／shell v49，schema 6 不變。

## [4.2.0] - 2026-11-09

### Added
- 月跑量分頁「年度回顧」：總跑量與前一年比較、年度目標達成率、跑步次數與天數、平均距離、最長連續、最長一次、最多的一週與月份、最常穿的鞋、買鞋數量與每 km 成本（SPEC-040）。
- 跑步日誌頂端摘要：本週跑量、連續天數、本月目標進度環、累計跑量與下一個里程碑，以及近 30 天的里程碑與個人新紀錄。
- 「今天穿哪雙」：依休息天數建議現役鞋（快到退役里程的鞋排最後），一鍵選入新增跑步表單。
- 跑鞋分頁「每雙鞋的距離分布」與月跑量分頁「年度月跑量對比」。
- API：`GET /api/analytics/home`、`GET /api/analytics/year-review`、`GET /api/analytics/shoe-distance-mix`。

### Changed
- 月跑量分頁只剩頂端一個年份選單，目標、回顧、趨勢與所有年度圖表一起切換。
- 同一雙鞋在所有圖表與表格使用相同顏色。
- 手機版改為固定底部分頁列；標題列「帳號」選單只保留同步、主題與登出。
- Asset 4.2.0／shell v48，schema 6 不變。

### Fixed
- Windows 上瀏覽器 E2E 結束時暫存資料夾偶爾被鎖住而刪除失敗，改為重試。

## [4.1.3] - 2026-11-09

### Changed
- 跑鞋輪替時間軸只列出現役鞋，已退役的鞋不再顯示；`GET /api/analytics/shoe-timeline` 不再回傳退役鞋與 `is_retired` 欄位（SPEC-038 修訂）。Asset 4.1.3／shell v47。

### Fixed
- CI 瀏覽器工作固定在 `ubuntu-24.04`：`ubuntu-latest` 改為 26.04 後，掛進 Playwright noble 容器的 tool-cache Python 缺少 ssl 模組，pip 無法安裝依賴。

## [4.1.2] - 2026-11-07

### Removed
- 月跑量分頁的「月跑量紀錄」表格、新增表單與月份編輯對話框（`app-monthly.js`）。既有月跑量與歷史／手動調整資料保留，圖表、目標、報告、備份與 API 不變；舊裝置上的月份草稿升級後被忽略（SPEC-039）。Asset 4.1.2／shell v46，release asset 50 個。

### Fixed
- Claude Code Stop hook 不再對未變更的工作區重播快取的失敗：回應 hook 回饋時不重複阻擋，之後的停止點重新驗證，避免暫時性網路錯誤（例如 pip-audit 連不到 PyPI）造成無限循環。

## [4.1.1] - 2026-11-06

### Changed
- 月跑量分頁的「月跑量紀錄」表格預設收合，只列出「年度月跑量」選擇的年份（最多 12 列），新增月份後切到該年份（SPEC-039）；Asset 4.1.1／shell v45。

### Fixed
- Claude Code Stop hook 以 UTF-8 讀取事件 JSON，不再因 Windows 主控台字碼頁（cp950）遇到中文或 emoji 時誤判為無效 JSON。

## [4.1.0] - 2026-11-06

### Added
- 月跑量分頁「訓練趨勢」：年度跑步熱力圖與有跑天數／最長／目前連續天數、近 16 週每週跑量與 4 週平均（比前 4 週平均多 30% 以上標示暴增）、年度累計跑量對照目標線與全年推估（SPEC-038）。
- 跑鞋分頁「跑鞋輪替時間軸」：每雙鞋首次到最後一次跑步的期間，標出超過 30 天沒穿的現役鞋（SPEC-038）。
- API：`GET /api/analytics/trends`、`GET /api/analytics/shoe-timeline`；Asset 4.1.0／shell v44，schema 6 不變。

## [4.0.3] - 2026-11-05

### Changed
- 依賴升級：certifi 2026.10.23、python-dotenv 1.2.4、httpx2 2.16.0、ruff 0.17.2、types-openpyxl 3.1.5.20261017；鎖定檔以 `uv pip compile --universal` 重編，保留 Windows 條件（取代 Dependabot #17–#21）。

### Fixed
- 本機工作區 IndexedDB 連線被瀏覽器關閉（iPhone Safari 背景、記憶體壓力或 versionchange）後，下一次讀寫自動重新連線，不再需要重新整理才能存取離線待送跑步與草稿（SPEC-037）。
- 瀏覽器測試的非同步等待改用 `waitForAsync`：Playwright `waitForFunction` 不會等待 async predicate，造成 WebKit 離線佇列測試間歇失敗；新增防回歸檢查。
- PWA 測試：失敗升級後先把 fixture 回復到已安裝版本並等候背景更新與流量結束才模擬斷線；改用 `serviceWorker.ready`；WebKit 偶發（約 1/70）更新佇列永久卡住且未送出請求時，於新瀏覽器重試一次（第二次或已送出未完成仍失敗）。
- Asset 4.0.3／shell v43；schema 6 不變，無資料 migration。

## [4.0.2] - 2026-11-05

### Changed
- 應用時區與「今天」集中於 `backend/clock.py`，取代 8 處各自寫死的 UTC+8；行為不變。
- 統計用四捨五入集中為 `backend/read_models/rounding.py` 的 `round_metric`，取代 4 份重複的 `_round`；輸出數值不變。
- Asset 4.0.1／shell v42 與 schema 6 不變，前端無需更新，無資料 migration。

## [4.0.1] - 2026-11-04

### Security
- AI 回覆與月報的 Markdown 改在 inert document 解析並以屬性 allowlist 清理，修正 `<img onerror>` 可在清理前執行的 XSS（SPEC-036）。
- 已超過自身上限的 IP／帳號不再消耗全站登入與 AI 額度，避免單一來源讓所有人無法登入。
- 新密碼至少 8 字元；同一帳號 15 分鐘內密碼錯誤 10 次後暫停登入與改密碼；不存在的帳號也執行 bcrypt，避免以回應時間推知帳號。
- 非預期的模型錯誤不再把例外原文傳給瀏覽器。

### Fixed
- 鎖定檔改為跨平台編譯：`uvloop` 只在非 Windows 安裝，並鎖定 Windows 需要的 `colorama`；Windows 可直接執行 `task.py setup`。
- Asset 4.0.1／shell v42，schema 6 不變。

## [4.0.0] - 2026-10-25

### Changed
- 資料與同步依狀態顯示操作；草稿、備份、歷史與本機清理區預設收合。
- PWA 偵測到新部署後會自動載入最新版，不再顯示確認更新提示。
- 跑步紀錄及鞋款選單移除使用者無法辨識的資料庫數字編號。
- Asset 4.0.0／shell v41，schema 6 不變。

### Release status
- 目前上線測試的穩定版；預期不再特別調整。

本專案的重要變更依 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.1.0/) 分類，版本號遵循 [Semantic Versioning](https://semver.org/lang/zh-TW/)。完整部署說明另見各版本的 GitHub Release。

## [3.10.4] - 2026-10-25

### Fixed
- 來源網站復原手動跑步後再搬移，保留同一紀錄身分，不再重複計算跑量。
- 相同小數里程備份不因浮點尾差誤判更新；新的累積值保持兩位精度。
- 手動同步、前景與另一分頁提交後重新讀取雲端，保持未送出輸入與帳號隔離。

### Changed
- 帳號下載使用 archive v3，附有界、原生來源的跑步 aliases；仍讀取 v1/v2 並保留舊指紋。舊 App 需更新才能匯入 v3。
- Asset 3.10.4／shell v39，schema 6 不變。

## [3.10.3] - 2026-10-25

### Fixed
- 同帳號備份不再重建已刪除跑步；明確復原後保留所有來源別名，後續匯入可正確更新。
- 離線佇列每次送出使用獨立租約，舊請求不再覆寫重新登入後的同步狀態。
- 同步及誤刪復原區分提交成功與畫面刷新失敗，復原可單獨重試讀取。

### Changed
- 抽出跑步來源身分 service 與共用核心資料刷新驗證，補上組合流程回歸及使用指南。
- Asset 3.10.3／shell v38；schema 6 不變。

## [Unreleased]

## [3.10.2] - 2026-10-24

### Fixed

- 匯入提交與畫面刷新分離；刷新失敗提供只讀重試，舊視窗／帳號的回呼不會改寫新狀態。
- 帳號匯出與匯入共用契約、集合與 20 MiB 限制，超限明確拒絕，不再產生無法匯入的檔案。
- 下載預設包含歷史，可明確取消歷史並於檔名／畫面揭露；不靜默截斷業務資料。
- 匯入計畫包含實際欄位差異及最終里程，預覽與執行共用，區分新增、實際變更、相同及保留刪除。
- 跑步月曆移除鞋款旁的次數文字，保留鞋款、每日里程與日期操作。

### Changed

- 新增 query-free `account_import_changes.py`，executor 只套用計畫 patch；時間比較、里程投影與差異統計集中。
- Asset 3.10.2／shell v37，schema 6 不變、51 個 release assets。

## [3.10.1] - 2026-10-24

### Fixed

- 非同步本機清除綁定 session 與操作，舊成功／失敗不修改新帳號，等待期間新輸入與編輯草稿保留。
- 匯入只更新有差異的欄位與里程，無變更／額外紀錄不增加版本、revision 或異動，避免假衝突。
- 每份預覽使用獨立 token，較早請求晚完成不再覆蓋最新預覽。關窗／過期回收，最多每人 8 份、合計 64 MiB。

### Changed

- 匯入規劃／來源辨識與寫入分離，預覽與套用共用計畫；交易與回執仍由 application service 管理。
- 原生 account restore controller 注入 session、transport 與 key，DOM bridge 只呈現；新增本人預覽 DELETE。
- Asset 3.10.1／shell v36、51 個 release assets；schema 6 僅調整預覽主鍵，保留現有 token。備份、升級與回滾步驟見 README／SPEC-030。

## [3.10.0] - 2026-10-24

### Added

- 帳號資料下載與匯入 UI 明示目前網站／帳號、來源與匯出時間。保留只新增模式，新增 v2「新增並更新同來源資料」，可更新先前匯入的鞋款、跑步、月份調整、目標及月報，保留額外資料與已刪除跑步。
- 繁體中文使用指南，說明雲端下載→本機版登入→選檔與模式→預覽→確認匯入，以及瀏覽器暫存與本機版資料庫的差異。

### Fixed

- 立即同步顯示空清單、離線、未就緒、進行中、完成及待處理結果，舊帳號完成不污染新帳號。
- 帳號資料下載在資料與同步視窗顯示進度／結果／錯誤，不再把失敗訊息放到隱藏的匯出視窗。
- 匯入更新後由後端重新彙總里程，支援跑步換鞋／換月份，並撤銷被更新月報的舊生成資格。

### Changed

- 預覽模式與內容共同綁定 hash、本人 revision 與操作回執；預設 merge 及舊預覽相容，update 僅接受 v2。
- Asset 3.10.0／shell v35，維持 schema 5 與 50 個 release assets；回滾可部署 v3.9.0 image，無須修改資料庫 schema。

## [3.9.0] - 2026-10-24

### Added

- SPEC-027：依帳號保存表單與編輯版本、最近資源快照；側欄「資料與同步」可恢復／捨棄草稿及清除目前帳號的本機資料。
- 新增跑步的 IndexedDB 同步佇列，原子消耗對應草稿、多分頁 lease、相同操作重播、登入過期暫停及明確刪鞋配對；離線重開可保留。
- 帳號備份 v2 及 v1 相容匯入：有界驗證、本人預覽、revision 檢查、來源 mapping、保留既有內容及一次交易合併；同檔／來源重複不重建。
- SQLite 同交易異動事件、本人歷史分頁及防衝突誤刪復原；匯入歷史唯讀，復原同步重算里程與配額。

### Changed

- 原生 workspace controller 注入 storage／session／transport，IndexedDB 與 DOM adapters 分離；移除年度、目標、洞察舊快取鏡像。
- 新 `/api/operations` 統一身分、版本與回執；既有 HTTP adapters 保持相容，錯誤補機器可讀 code。Schema 5 增加 metadata／歷史／mapping，run／month 主鍵不重用。
- README、SPEC-027、ADR-0010、SDD、測試策略與 harness 同步；Asset 3.9.0／shell v34、50 assets；本機驗收 508 Python、124 Node、94.66% 後端分支覆蓋率，包含 40 組版面與雙引擎 E2E／PWA，沒有 browser skip。正式 migration 須先完成備份與隔離還原，部署後執行匿名 release-check。

## [3.8.0] - 2026-10-23

### Fixed

- 新增跑步選定鞋款遭刪除後保留「請重新選擇」，重繪不默默改記其他鞋款。
- 鞋款／月跑量行內編輯保留 DOM、草稿與顯示列快照；背景來源、主題與跨日重繪不自動提交部分數字，明確提交仍檢查原版本。
- 月報以最新開始的生成身分驗證保存，舊請求不能覆蓋新內容與統計；失敗／取消保留之前成功報告。
- Strava 匯入期間停用配對，失敗只解鎖同一視窗；延後資源 dispatch 在發送前拒絕過期 session。

### Changed

- 依來源失效相依分頁；年度彙總、目標進度與洞察讀取由 resource store 合併 pending／快取與拒絕過期結果，格式錯誤可重試。
- 月報 application service、條件持久化、統計、LLM adapter 與 SSE 分離；月報 router 納入交易邊界檢查。
- Schema 4 僅新增 user／月份最新身分表，不改寫既有報告／里程；同步 README、SPEC-025／026、ADR-0009、SDD、測試策略與 rollback。
- Asset 3.8.0／shell v33，45 個 release assets；驗收基線為 475 Python、113 Node，完整 browser／CI 與部署證據見 GitHub Release。

## [3.7.2] - 2026-10-23

### Fixed

- v3.7.1 tag E2E 發現首次月跑量 panel 的延後 render 可能在使用者輸入後才建立 goal baseline，把 180 覆蓋回 125。現在切換分頁時先同步準備表單，再延後繪製圖表。
- Node 回歸與雙引擎 E2E 固定暫停第一個 panel frame，驗證先輸入／失焦、釋放 render 及晚到 server goal 仍保留草稿；不以重跑通過取代修正。
- Asset revision 3.7.2／shell v32，schema 3、44 個 release assets；v3.7.0／v3.7.1 tags 保留原始內容。
- 本機 verify：464 Python、106 Node；雙引擎 E2E／PWA 及匿名 44 資產 release-check 通過。

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
