# Changelog

本專案的重要變更依 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.1.0/) 分類，版本號遵循 [Semantic Versioning](https://semver.org/lang/zh-TW/)。完整部署說明另見各版本的 GitHub Release。

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

[3.2.0]: https://github.com/Teng91/running-shoes/releases/tag/v3.2.0
[3.1.0]: https://github.com/Teng91/running-shoes/releases/tag/v3.1.0
[2.14.0]: https://github.com/Teng91/running-shoes/releases/tag/v2.14.0
[2.13.1]: https://github.com/Teng91/running-shoes/releases/tag/v2.13.1
[2.13.0]: https://github.com/Teng91/running-shoes/releases/tag/v2.13.0
[2.12.0]: https://github.com/Teng91/running-shoes/releases/tag/v2.12.0
