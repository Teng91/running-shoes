# Changelog

本專案的重要變更依 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.1.0/) 分類，版本號遵循 [Semantic Versioning](https://semver.org/lang/zh-TW/)。完整部署說明另見各版本的 GitHub Release。

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

[2.14.0]: https://github.com/Teng91/running-shoes/releases/tag/v2.14.0
[2.13.1]: https://github.com/Teng91/running-shoes/releases/tag/v2.13.1
[2.13.0]: https://github.com/Teng91/running-shoes/releases/tag/v2.13.0
[2.12.0]: https://github.com/Teng91/running-shoes/releases/tag/v2.12.0
