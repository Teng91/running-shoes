# Changelog

本專案的重要變更依 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.1.0/) 分類，版本號遵循 [Semantic Versioning](https://semver.org/lang/zh-TW/)。完整部署說明另見各版本的 GitHub Release。

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

[3.2.3]: https://github.com/Teng91/running-shoes/releases/tag/v3.2.3
[3.2.2]: https://github.com/Teng91/running-shoes/releases/tag/v3.2.2
[3.2.1]: https://github.com/Teng91/running-shoes/releases/tag/v3.2.1
[3.2.0]: https://github.com/Teng91/running-shoes/releases/tag/v3.2.0
[3.1.0]: https://github.com/Teng91/running-shoes/releases/tag/v3.1.0
[2.14.0]: https://github.com/Teng91/running-shoes/releases/tag/v2.14.0
[2.13.1]: https://github.com/Teng91/running-shoes/releases/tag/v2.13.1
[2.13.0]: https://github.com/Teng91/running-shoes/releases/tag/v2.13.0
[2.12.0]: https://github.com/Teng91/running-shoes/releases/tag/v2.12.0
