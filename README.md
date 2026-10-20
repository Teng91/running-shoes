# Running Shoes Dashboard

跑鞋追蹤 Dashboard — 記錄每雙跑鞋的里程、成本與生命週期，並以跑步日誌追蹤每次跑步的日期、公里數及穿著鞋款。支援每月跑量與鞋款里程圖表，並內建 AI 跑鞋推薦助手。支援多使用者帳號，每人資料獨立隔離，也可在手機上安裝為 PWA。

版本演進與相容性說明集中於 [`CHANGELOG.md`](CHANGELOG.md)，設計與測試規格位於 `docs/`。

## 使用方式

### 直接使用線上服務

開啟 [running-shoes.fly.dev](https://running-shoes.fly.dev/)，註冊帳號即可開始使用，每個人的跑鞋資料完全隔離。

#### 安裝到 iPhone 主畫面

1. 使用 Safari 開啟線上服務。
2. 點選 Safari 的「分享」按鈕。
3. 選擇「加入主畫面」，再按「新增」。

之後可從主畫面以獨立 App 視窗開啟，並使用跑鞋搭配里程進度環的專屬圖示。PWA 本身免費，不需要 TestFlight 或 Apple Developer 帳號。圖表與 Markdown 套件使用專案內固定版本並包含在離線 app shell；application CSS／JavaScript 會以同一版號快取，避免更新後混用新舊介面資產。登入、資料同步與 AI 功能仍需要網路連線。離線時會保留登入狀態，待重新連線後繼續使用。

如果主畫面仍顯示舊圖示，請先刪除原本的主畫面捷徑，再從 Safari 重新執行「加入主畫面」，讓 iOS 重新取得圖示。

> 所有使用者共用同一個 Fly.io 免費容器（256MB RAM），人數或資料量過多可能影響效能。

### 自己部署

開源專案，可依照下方「快速開始」在本機執行，也可以部署到自己的
Fly.io 帳號或其他支援 Docker 的平台。

## 目錄結構

```
running-shoes/
├── .github/
│   └── workflows/
│       └── verify.yml    # Push／PR 自動執行完整 harness 驗證
├── .claude/
│   └── settings.json     # Claude Code 完成回覆前執行確定性驗證的 Stop hook
├── backend/              # FastAPI 後端
│   ├── main.py           # 最小 ASGI 入口
│   ├── app_factory.py    # 可注入的 FastAPI 組裝、lifecycle 與 SPA fallback
│   ├── settings.py       # Immutable typed runtime configuration
│   ├── seeding.py        # 使用注入 session factory 的可選預設資料
│   ├── middleware.py     # Strava request body transport guard
│   ├── routers/
│   │   ├── auth.py       # 註冊、登入與密碼管理 routes
│   │   ├── goals.py      # 跑量目標 routes
│   │   ├── monthly.py    # 月跑量 routes
│   │   ├── agent.py      # AI provider 與對話 routes
│   │   ├── reports.py    # AI 月報 routes
│   │   ├── health.py     # Liveness／readiness probes
│   │   ├── analytics.py  # Dashboard 與單鞋分析 routes
│   │   ├── exports.py    # 帳號備份與跑鞋匯出 routes
│   │   ├── spending.py   # 支出統計 routes
│   │   ├── strava.py     # Strava upload／import routes
│   │   ├── runs.py       # 跑步日誌 CRUD routes
│   │   └── shoes.py      # 跑鞋 CRUD HTTP routes
│   ├── services/
│   │   ├── exports.py    # Framework-independent 匯出內容生成
│   │   ├── strava_imports.py # Strava 匯入 transaction 與配對驗證
│   │   └── mileage.py    # 跑步、鞋款、月份彙總的交易式里程同步
│   ├── migrations.py     # 有版本的 SQLite schema upgrade
│   ├── observability.py  # Request ID 與不含敏感內容的結構化 HTTP log
│   ├── rate_limits.py    # Auth／AI process 與 SQLite shared rate limits
│   ├── auth.py           # JWT 認證 + 密碼雜湊
│   ├── database.py       # SQLite 資料庫連線
│   ├── models.py         # 資料表定義
│   ├── schemas.py        # Pydantic schema
│   ├── agent.py          # AI 助手 runner 與公開 orchestration entry point
│   ├── agent_planner.py  # Deterministic intent 與最小查詢計畫
│   ├── agent_tools.py    # 受信任工具 dispatch
│   ├── agent_protocol.py # SSE 與搜尋來源摘要 contract
│   ├── reports.py        # AI 月度跑步報告（後端算統計 + one-shot LLM 串流 + 報告留存）
│   ├── goals.py          # 個人月／年跑量目標與達成率計算
│   ├── forecasting.py    # 共用退役預估與 user-scoped 批次查詢
│   ├── analytics.py      # 首頁洞察與單鞋使用分析
│   ├── strava_import.py  # Strava CSV 解析、篩選、去重與預覽統計
│   ├── exporting.py      # CSV／XLSX 安全匯出列與檔名
│   ├── llm.py            # LLM 抽象層（OpenRouter）
│   ├── tools/            # AI 助手工具
│   │   ├── db_tools.py   # 讀取使用者跑鞋 / 跑量資料
│   │   └── search_tool.py# 上網搜尋市售鞋款（DuckDuckGo）
│   └── run.py            # 本機開發啟動入口
├── frontend/
│   ├── index.html        # Dashboard HTML 結構
│   ├── app.js            # Dashboard 初始化與全域 dialog wiring
│   ├── app-boot.js       # 啟動 loading、逾時與 stylesheet readiness
│   ├── app-state.js      # 共用記憶體 state 與 presentation constants
│   ├── app-api.js        # HTTP／upload helpers
│   ├── app-auth.js       # 登入、註冊、登出與帳號切換
│   ├── app-streams.js    # 共用 SSE 解碼、取消與完成狀態
│   ├── app-core.js       # Shell、主題、分頁與聚合資料載入
│   ├── app-dashboard.js  # 首頁卡片、提醒與跑鞋表格
│   ├── app-monthly.js    # 月跑量 CRUD、inline 表單與編輯快照
│   ├── app-exports.js    # 跑鞋匯出與帳號備份下載
│   ├── app-goals.js      # 跑步目標設定與期間進度
│   ├── app-charts.js     # 共用圖表 registry 與 label utilities
│   ├── app-shoe-charts.js # 跑鞋生命週期、成本、時間軸與分配
│   ├── app-monthly-charts.js # 月份／年度選擇與跑量圖表
│   ├── app-spending.js   # 支出摘要、圖表與表格
│   ├── app-agent.js      # AI 助手對話、模型清單與安全 Markdown 顯示
│   ├── app-reports.js    # 月報讀取、產生與串流顯示
│   ├── app-runs.js       # 跑步 CRUD、分頁與鞋款選擇
│   ├── app-strava.js     # Strava 預覽、配對與匯入 UI
│   ├── app-run-insights.js # 跑步月曆、洞察與單鞋分析 UI
│   ├── app-shoes.js      # 跑鞋編輯與 modal 互動
│   ├── styles.css        # Dashboard 亮／暗色與響應式版面
│   ├── manifest.webmanifest # PWA 名稱、顏色與圖示設定
│   ├── service-worker.js # App shell 快取與離線 fallback
│   ├── offline.html      # 無快取頁面可用時的離線提示
│   ├── icons/            # PWA、iOS 主畫面圖示與高解析度來源檔
│   ├── vendor/           # 固定版本的 Chart.js 與 marked.js 離線資源
│   └── favicon.svg
├── docs/
│   ├── architecture.md   # SDD：現況架構圖、模組邊界與演進順序
│   ├── testing-strategy.md # TDD：測試層級、追蹤矩陣與完成條件
│   ├── specs/            # Feature spec 範本與 acceptance criteria
│   └── adr/              # 重要架構決策與取捨紀錄
├── scripts/
│   ├── claude_stop_hook.py # Claude Code 本機驗證與失敗回饋
│   ├── claude_stop_hook_launcher.cjs # 跨 Windows／Unix 尋找專案 Python
│   ├── check_architecture.py # 阻止反向依賴與重複 API route
│   ├── check_secrets.py  # 掃描 tracked files 的明確 credential 特徵
│   ├── check_docs.py     # 核對 README 測試數、工具數、版面矩陣與 harness 路徑
│   ├── database_backup.py # SQLite backup／checksum／retention／restore
│   ├── offsite_backup.py # Fly 外部下載、private staging 與隔離還原演練
│   ├── smoke_test.py     # 部署後 health 與 OpenAPI smoke check
│   └── task.py           # 跨平台 setup、測試、eval 與完整驗證入口
├── unit_tests/           # Pytest、Agent eval、前端邏輯與版面回歸測試
│   ├── agent_eval_cases.json # Agent 工具選擇與安全行為案例
│   ├── frontend_regressions.cjs # Node.js 前端邏輯回歸測試
│   ├── frontend_layout.cjs # Playwright 跨瀏覽器版面測試
│   └── frontend_e2e.cjs  # 真實 FastAPI + 暫存 SQLite 的瀏覽器 CRUD
├── AGENTS.md             # Coding Agent 專案規則與完成條件
├── CLAUDE.md             # 讓 Claude Code 匯入共用的 AGENTS.md
├── CHANGELOG.md          # 版本演進與 release 摘要
├── pyproject.toml        # pytest、Ruff 與 mypy 設定
├── requirements.in       # 正式環境直接依賴與核准版本
├── requirements.txt      # 含雜湊的完整正式環境鎖定檔
├── requirements-dev.in   # 測試、lint、型別與安全掃描直接依賴
├── requirements-dev.txt  # 含雜湊的完整開發／CI 鎖定檔
├── Dockerfile            # Docker 部署用
├── fly.toml              # Fly.io 部署設定
└── .gitignore
```

## 快速開始（本機開發）

```bash
# 1. Clone
git clone https://github.com/Teng91/running-shoes.git
cd running-shoes

# 2. 建立虛擬環境
python3 -m venv venv

# 3. 使用虛擬環境安裝開發依賴（包含正式執行、測試與程式碼檢查套件）
venv/bin/python -m pip install --require-hashes -r requirements-dev.txt

# 4. 使用虛擬環境啟動伺服器
venv/bin/python -m backend.run

# 5. 開啟瀏覽器
open http://localhost:8000
```

建議直接使用 `venv/bin/python`，因為指令本身就明確指定虛擬環境，不會因為換了
Terminal、忘記 activate，或 IDE 使用另一個 shell 而誤用系統 Python。

專案將直接依賴與可安裝鎖定檔分開：

- `requirements.in`／`requirements-dev.in`：人工維護的直接依賴與核准版本。
- `requirements.txt`／`requirements-dev.txt`：完整鎖定所有間接依賴並附下載雜湊；Docker、Fly.io 與 CI 都使用 `--require-hashes` 安裝，避免不同時間解析出不同套件。

如果只想執行服務、不需要跑測試或程式碼檢查，也可以只安裝
`requirements.txt`。更新 `.in` 後，使用 `pip-tools` 重新編譯兩份鎖定檔，不要直接手改鎖定內容。

若偏好先啟用虛擬環境，也可以使用以下等效方式：

```bash
source venv/bin/activate
python -m pip install --require-hashes -r requirements-dev.txt
python -m backend.run

# 使用完畢可離開虛擬環境
deactivate
```

`source venv/bin/activate` 不會另外「載入」套件；它會修改**目前這個 shell** 的
`PATH`，讓 `python` 和 `pip` 優先指向 `venv/bin/`。開啟新的 Terminal、從其他
IDE Task 啟動，或關閉目前 shell 後，都需要重新 activate。可用以下指令確認：

```bash
# 應顯示專案內的 venv/bin/python
which python

# 顯示實際執行器、虛擬環境位置，並確認搜尋套件可匯入
venv/bin/python -c "import sys; from ddgs import DDGS; print(sys.executable); print(sys.prefix); print(DDGS)"
```

第一次啟動會自動建立 `shoes.db`（資料表結構）。本機與 Fly.io 都預設建立空資料庫；只有明確設定 `SEED_DATA=true` 時才會寫入範例資料，且此時必須同時設定 `MIGRATION_PASSWORD`。

### 本機使用 AI 助手

在專案根目錄建立 `.env` 檔，填入 OpenRouter API Key：

```bash
OPENROUTER_API_KEY=<你的 OpenRouter API Key>   # 取得: https://openrouter.ai/keys
# 選填：固定某個免費且支援 tools 的模型
# 選填：每個帳號每分鐘最多 AI 請求數（預設 20）
AGENT_RATE_LIMIT_PER_MINUTE=20
# 選填：同一 IP／全站每分鐘 AI 請求上限（預設 30／120）
AGENT_IP_RATE_LIMIT_PER_MINUTE=30
AGENT_GLOBAL_RATE_LIMIT_PER_MINUTE=120
# 選填：同一 IP／全站每分鐘登入、註冊、改密碼請求上限（預設 120／300）
AUTH_RATE_LIMIT_PER_MINUTE=120
AUTH_GLOBAL_RATE_LIMIT_PER_MINUTE=300
# 選填：帳號總數、每人跑鞋／跑步紀錄筆數及模型列表刷新冷卻秒數
MAX_REGISTERED_USERS=100
MAX_SHOES_PER_USER=500
MAX_RUNS_PER_USER=5000
MODEL_REFRESH_COOLDOWN_SECONDS=60
# 選填：全站每分鐘最多強制刷新模型清單次數（預設 10）
MODEL_REFRESH_GLOBAL_PER_MINUTE=10
# 選填：每次 LLM 回覆最多輸出 token 數（預設 4096，最低 256）
LLM_MAX_OUTPUT_TOKENS=4096
```

`.env` 會被自動載入，不需要手動 `export`。沒設定也不影響 Dashboard 的其他功能，只是 AI 助手無法使用。

## 功能特色

- **側欄工作區**：桌面版以固定左側導覽切換六個功能，右側完整呈現目前工作內容；手機版只保留品牌、目前頁面與「選單」按鈕，點開後可切換功能、主題或登出，選取功能後自動收起
- **跑鞋全生命週期追蹤**：記錄品牌、鞋款、用途類別 (Daily / Speed / Tempo / Race，可多選)、購買日期、尺寸、價格、里程、預期壽命、月跑量
- **購鞋資訊集中管理**：現役／退役跑鞋清單聚焦使用狀態；尺寸、買價、原價、折數統一在「支出 → 支出明細」查看。新增／編輯跑鞋仍保留原有尺寸與價格欄位，不刪除既有資料
- **鞋櫃類別覆蓋分析**：判斷某雙鞋退役後其所有用途是否仍有其他現役鞋覆蓋，避免不必要地補鞋 (支援多用途鞋款)
- **智慧試算**：自動計算每 km／每次穿著成本、折數、生命進度，並依近 90 天實際使用預估退役日期
- **一致的退役預估**：跑鞋清單、時間軸及單鞋分析共用後端預估；有近 90 天紀錄時使用實際月均，否則回退計畫月跑量。清單日期提示及分析卡片會標示依據；無法預估或已達壽命時不虛構日期
- **圖表視覺化**：生命進度條、每 km 成本比較、退役時間軸、月跑量佔比（圓餅圖直接標示公里數與百分比，Chart.js）
- **亮色 / 暗色主題切換**：右上角一鍵切換，全域 UI 元素與所有 Chart.js 圖表（網格線、刻度文字、數據標籤）皆自動對應色調，偏好透過 `localStorage` 自動記憶
- **安全的里程統計**：跑鞋與月跑量都明確區分「逐筆跑步日誌」與「歷史／手動調整」，手動總數不能低於日誌合計；所有新輸入的里程與金額統一保存至小數點後兩位
- **跑步日誌**：預設首頁，可記錄日期、公里數與鞋款並同步里程；完成日期不得晚於今天
- **跑步洞察首頁**：當月會以相同天數比較上月同期，並顯示近 7 天趨勢、月目標、月底里程預測及鞋款壽命提醒
- **手機跑步摘要**：六張摘要卡片統一以兩欄三列排列，同列等高；分析載入／失敗訊息與鞋款提醒維持全寬
- **單鞋分析**：可檢視穿著次數、30／90 天里程、最後使用日期、壽命進度、預估退役、近 12 月趨勢與最近跑步
- **Strava 歷史匯入**：從 Strava 匯出的 `activities.csv` 預覽並批次匯入跑步活動，依活動 ID 去重，支援匯入前逐鞋款配對；CSV 與資料庫工作在 worker thread 順序執行，HTTP 仍等待交易完成，不是背景佇列
- **資料匯出與備份**：跑鞋可匯出 **XLSX / CSV**，並可下載不含密碼或 token 的完整 JSON 帳號備份（跑鞋、日誌、月跑量、目標、月報與 Strava 匯入摘要）
- **AI 跑鞋推薦助手**：依你的實際資料給換鞋與選鞋建議（需設定 OpenRouter API Key），可從本日熱門、免費且支援工具呼叫的模型中選擇
- **AI 月度跑步報告**：可自行選擇本日免費模型，一鍵產生指定月份的跑步報告（跑量趨勢、鞋款狀態、退役提醒與下月建議），報告自動保存、可隨時回看，不需重打 LLM；更新時間以帶 offset UTC 傳輸，生成與重新讀取皆顯示裝置本地時間
- **安全的編輯與串流**：跑步／月跑量／跑鞋視窗保存開啟時的 ID、版本與 session；重新載入後仍由後端檢查衝突。跑鞋儲存、刪除與移動防止重送，晚到回應不關閉新草稿。AI／月報共用串流處理，AI 中斷會保留可見內容、提示重試，不把半截答案放進歷史
- **按需圖表**：只建立或更新目前分頁的圖表；未變更的分頁可重用，資料或主題更新後在切入時重繪，年度跑步資料只在月跑量分頁需要時載入
- **個人跑量目標**：預設自 2026 年起每月 125 km，年度目標自動以月目標 × 12 計算；目標、首頁與 AI 月報統一以逐筆跑步日誌計算，可切換月份查看達成率與「截至所選月份」年度進度
- **多使用者隔離**：每人資料完全獨立，支援註冊/登入/改密碼；認證表單防重送，切換表單／session 使舊操作失效。切換帳號會清除洞察快取並取消 AI 串流，過期回應不覆蓋新登入或 UI 狀態

## 跑步日誌

登入後切換到「跑步日誌」頁籤，即可為每次跑步選擇日期、公里數與穿著的鞋款。日誌支援新增、編輯與刪除，現役與已退役鞋款都可使用。

「跑步日誌」位於第一個分頁，也是固定首頁。每次登入、重新整理、重新開啟網站／PWA，或由瀏覽器 back-forward cache 還原文件時，都會回到此頁，不再記憶上次停留的分頁；登入狀態與主題偏好照常保留。單純切換 App／瀏覽器分頁後回到原畫面不會強制切頁。從此處新增的距離會同步累加到所選跑鞋的總里程，以及該年月的「月跑量紀錄」；如果該月份尚無紀錄，系統會自動建立。編輯距離、日期或鞋款時只套用前後差額，刪除時則同步扣回。既有歷史資料不會在升級時重新計算。

跑步日誌會即時計算：

- 總里程、跑步次數與跑步天數
- 平均每個跑步日的里程
- 當月使用里程最高的主力鞋
- 1 日到月底的互動月曆；空白日期可帶入新增表單，既有活動可直接開啟編輯
- 依鞋款匯總的里程分布圓環圖，以及各鞋實際里程與使用比例明細
- 每筆紀錄的來源標籤（手動或 Strava）
- 當月截至今天與上月同期、前 7 天的趨勢比較，以及月目標與鞋款壽命提醒；已結束月份維持整月比較，未來月份不會混入前一月資料
- 依目前節奏預測月底總里程，並顯示達標所需的每日里程
- 每雙鞋在所選月份的里程、穿著次數及占比

跑步紀錄儲存在 SQLite `runs` 資料表，每筆資料都會綁定帳號與該帳號擁有的鞋款。後端會驗證鞋款擁有權，並啟用 SQLite 外鍵約束，避免無效或跨帳號的鞋款關聯。編輯時會檢查紀錄版本；同一筆紀錄若已在其他分頁被修改，較舊的畫面會收到衝突提示，避免重複套用里程差額。刪除已有跑步紀錄的鞋款時，鞋款會從鞋櫃與未來選項中移除，但歷史跑步紀錄與月跑量仍會保留。每個帳號預設最多儲存 5,000 筆跑步紀錄，可用 `MAX_RUNS_PER_USER` 調整。前端只分頁載入目前查看月份；鞋款年度堆疊圖切換年份時才按需載入該年紀錄，避免每次操作都下載完整歷史。

| API | 用途 |
| --- | --- |
| `GET /api/runs` | 取得目前帳號的跑步紀錄；可用 `year`、`month`、`limit`（最多 500）與 `offset` 篩選／分頁，不帶參數時維持完整列表相容性 |
| `POST /api/runs` | 新增日期、公里數與鞋款 |
| `PUT /api/runs/{run_id}` | 編輯指定跑步紀錄 |
| `DELETE /api/runs/{run_id}` | 刪除指定跑步紀錄 |
| `GET /api/runs/import/strava/history` | 取得最近 10 次 Strava 匯入摘要 |
| `POST /api/runs/import/strava/preview` | 預覽 Strava CSV 中的跑步活動與鞋款配對 |
| `POST /api/runs/import/strava` | 依鞋款配對批次匯入 Strava 跑步活動 |
| `GET /api/analytics/dashboard` | 取得指定月份的趨勢、目標、月底預測與壽命洞察 |
| `GET /api/shoes/{shoe_id}/analytics` | 取得單雙鞋的使用、成本與退役預測 |
| `GET /api/export/account` | 下載不含驗證秘密的完整 JSON 帳號備份 |

### Strava 歷史資料匯入

在「跑步日誌」右上角按「匯入 Strava」，選擇 Strava 匯出資料夾中的 `activities.csv`（Strava 官方匯出方式請參考[說明](https://support.strava.com/hc/en-us/articles/216918437-Exporting-your-Data-and-Bulk-Export)）。系統支援繁體中文與英文 Strava 匯出欄位及日期格式，只會保留活動類型為跑步且落在所選起訖日期內的資料（包含開始與結束當天），將 Strava 的公尺距離轉換為公里，並先顯示真正待匯入的鞋款筆數與里程；已存在或同檔重複的活動會另外計數，不會混入鞋款配對合計。日期預設為前 13 個完整月份、不包含本月，調整後會依登入帳號保存在目前瀏覽器。

匯入前可逐組選擇現有鞋款；名稱只有一個相符候選時會自動配對，也可以把多個 Strava 裝備配到同一雙 Dashboard 跑鞋。如果同品牌型號有多雙，系統不會猜測，請依購買日期手動選擇。沒有鞋款或無法辨識的裝備可以選擇略過。

Strava 匯入後會自動同步跑鞋總里程與對應月份的月跑量，只有本次真正新增的活動會計入。每筆匯入資料會保留 Strava 活動 ID，因此重複選擇同一份 CSV 不會重複建立紀錄或再次增加里程。匯入仍受 `MAX_RUNS_PER_USER` 上限限制，CSV 最大為 10 MB、最多 50,000 筆資料列；後端會逐列解析，並在 multipart 解析前限制整體上傳請求為 11 MB。切換檔案或日期時，舊的預覽請求會被取消且結果不會覆蓋最新選擇。

系統另保存成功匯入的摘要（不保存 CSV 內容），每個帳號保留最近 50 次並提供最近 10 次結果，包含時間、日期區間、新增里程與新增／重複／未配對／格式略過筆數。跑步日誌會顯示最近一次結果，下次開啟匯入視窗時則以最近匯入結束日的隔天作為起始日、今天作為結束日；若紀錄已到今天或未來，起始日會安全地停在今天。

## AI 跑鞋推薦助手

內建的 AI 助手會依你的**實際資料**給換鞋與選鞋建議：

- 讀取你的跑鞋清單、剩餘壽命、每月跑量趨勢（只看你自己的資料）
- 找出接近預期壽命、該準備替換的鞋
- 上網搜尋市售鞋款、規格、評價、價格；網址由後端驗證後顯示為安全來源卡片
- 以繁體中文對話，過程逐步顯示推理與工具呼叫（SSE 串流）
- 使用 OpenRouter / OpenAI 原生 function calling；模型清單只顯示本日總使用量前 50 名中，免費且宣告支援 `tools` 的模型
- 資料庫工具回傳具名 JSON；里程、剩餘壽命、百分比、成本與跑量統計由後端計算，LLM 只負責文字分析
- 詢問市價、最新評價、上市資訊或具體市售鞋款規格時，後端會先用「官方規格」與「台灣價格／評價」查詢；搜尋失敗時禁止模型憑記憶補造資料
- 詢問「某雙鞋適合我嗎」時，後端會在同一輪先取得外部資料、鞋櫃與跑量，再交給模型綜合判斷，不必先問一次再等使用者確認
- 搜尋結果會過濾不安全網址、去除重複項目，並優先排列官方與可信評測來源；成功結果快取 15 分鐘，價格類查詢快取 5 分鐘
- 搜尋標題與摘要會限制長度，並以不可信的原生 tool 結果傳給模型，避免網頁文字偽裝成使用者或系統指令
- 「我最新的月跑量／跑鞋里程」等私人資料問題會優先查後端資料庫；「最新市售跑鞋」才會查網路
- 每則回答下方會由後端標示「即時搜尋」、「近期搜尋快取」、「不需要搜尋」或「搜尋失敗」，並列出可點擊的來源卡片與實際搜尋關鍵字

目前提供 8 個 Agent 工具：

| Tool | 用途 |
| --- | --- |
| `list_my_shoes` | 列出所有跑鞋，明確區分累積里程、預期壽命、剩餘里程、已使用百分比與分配月跑量 |
| `shoe_summary` | 統計鞋款數量、總里程、現役鞋花費及各鞋生命週期 |
| `monthly_mileage_stats` | 由後端計算總跑量、月均、近期趨勢及最近六個有跑量月份明細 |
| `nearing_end_of_life` | 找出達提醒門檻的現役鞋，並判斷同類別是否已有替代鞋 |
| `compare_shoes` | 比較兩雙鞋的用途、里程、壽命與每公里成本 |
| `shoe_category_status` | 分析 Daily / Speed / Tempo / Race 覆蓋及補鞋需求 |
| `shoe_usage_analytics` | 分析穿著次數、近期里程與實際退役預測 |
| `web_search` | 搜尋市售鞋款、規格、評價與價格來源 |

需要設定 `OPENROUTER_API_KEY`（見上方）。前端預設選取 OpenRouter 本日總使用量前 50 名中，
符合免費且支援工具呼叫條件的最高排名模型。免費模型的速率限制、延遲與可用性可能波動，因此較適合
個人使用、展示與低流量情境，不保證每次請求都成功。

登入後，前端下拉選單會先依當日 token 使用量排列所有模型、取前 50 名，再顯示其中免費且
支援工具呼叫的模型；點擊 🔄 可強制刷新。清單不會補入前 50 名以外的免費模型，也不使用固定
過期名單；更新失敗時最多短暫沿用一小時內曾驗證過的免費清單，超過後會停止 AI 呼叫，避免舊模型轉為付費仍被使用。所有模型都必須支援
OpenRouter 的 `tools` 參數。

後端會再次驗證請求模型必須位於目前的免費工具模型清單，前端傳入任意模型 ID
不會直接使用伺服器的 OpenRouter API Key 呼叫。Agent API 同時限制單則訊息長度、
history 筆數與整段對話總字數，並套用每帳號、每 IP 與全站請求上限。公開驗證端點、註冊帳號總數、
每人跑鞋筆數、跑步紀錄筆數，以及模型列表的每帳號冷卻與全站刷新頻率，也都有可透過環境變數調整的防濫用限制。驗證與 AI 請求的限流同時使用程序內滑動視窗和 SQLite 共享計數，因此多個伺服器 worker 會共用上限。LLM 請求另有連線與整體逾時，外部服務卡住時不會無限等待。

## AI 月度跑步報告

「月報」分頁可為指定月份一鍵產生 AI 訓練報告，固定包含一句話摘要、關鍵指標表格，以及「本月總覽、趨勢解讀、鞋款壽命與退役提醒、下月建議」四個章節。產生期間會逐步套用 Markdown 文件排版，不必等串流結束才看到格式化結果。

- 統計數字全部由後端計算：當月里程、跑步次數與跑步天數、逐鞋里程與主力鞋、上月差額、年度累計、整體月跑量趨勢及接近壽命的鞋款；不產生輪替或購鞋建議
- 本月報告比較上月同期，已結束月份比較完整月份；目標達成率與首頁統一以逐筆跑步日誌為準
- 產生過程以 SSE 串流顯示；模型只負責把後端算好的數字寫成文字，不得自行計算或杜撰
- 報告成功產生後存入資料庫（一人一月一版），同月重新產生會覆蓋舊版；之後從「歷史報告」或月份選擇器讀取，不會重打 LLM
- 月報提供獨立的「本日免費模型」選單，選項與 AI 助手共用同一份後端核准清單，但不會偷偷沿用 AI 助手分頁目前選取的模型
- 套用與 AI 助手相同的每帳號／每 IP／全站請求上限，未來月份不可產生
- 需設定 `OPENROUTER_API_KEY`（見上方），免費模型的可用性可能波動；產生失敗時不會寫入任何資料

| API | 用途 |
| --- | --- |
| `POST /api/reports/generate` | 串流產生指定月份的跑步報告，成功後自動保存 |
| `GET /api/reports` | 列出目前帳號所有已儲存的報告（不含內文） |
| `GET /api/reports/{year}/{month}` | 取得指定月份的完整報告內容 |

## 測試

專案提供跨平台工程 harness，會自動選用 Windows `venv/Scripts/python.exe`、
Unix `venv/bin/python` 或目前的 Python。Windows、macOS、Linux、Coding Agent 與 CI
都使用相同的 `scripts/task.py`，不依賴特定 shell。以下使用 Unix 的 `python3`；Windows
把 launcher 換成 `py -3` 即可，後面的 script 與 task 名稱完全相同：

```bash
# 安裝開發依賴
python3 scripts/task.py setup

# 完整檢查：Ruff、mypy、架構邊界、依賴漏洞、pytest、前端 Node 回歸測試
python3 scripts/task.py verify

# 一次跑完 verify、frontend-layout、frontend-e2e 與 frontend-pwa（缺 Playwright 時警告並跳過瀏覽器檢查）
python3 scripts/task.py verify-all

# 日常後端檢查，或只執行 Agent 行為 eval
python3 scripts/task.py test-fast
python3 scripts/task.py eval-agent

# 只掃描鎖定的正式環境依賴是否有已知漏洞
python3 scripts/task.py audit-deps

# 檢查 router 依賴方向與重複 API route
python3 scripts/task.py architecture-check

# 掃描 tracked files 是否出現 private key 或常見平台 token
python3 scripts/task.py security-check

# 核對 README 與實際測試數、工具數、版面矩陣及 harness 路徑
python3 scripts/task.py docs-check
```

Agent eval 案例位於 `unit_tests/agent_eval_cases.json`，用來固定私人資料、即時搜尋、
工具選擇和一般對話等行為。後端測試涵蓋 API、帳號隔離、資料庫升級與邊界案例。
`test-fast` 與 `verify` 會量測 branch coverage，低於 92% 直接失敗。若只想單獨查看：

```bash
python3 -m pytest -q --cov=backend --cov-branch --cov-report=term-missing
```

前端流程回歸測試使用 Node.js 內建測試工具，不需要安裝 npm 套件：

```bash
python3 scripts/task.py frontend-test
```

手機版面回歸檢查另外使用 Playwright（WebKit 與 Chromium），包含亮暗模式、長鞋名、多筆資料、空資料、表單欄位重疊、分頁完整顯示、圖表繪圖區及彈出視窗：

```bash
npm install --no-save --package-lock=false playwright
npx playwright install chromium webkit
python3 scripts/task.py frontend-layout

# Chromium 真實 CRUD（暫存 SQLite）＋ Chromium/WebKit mock 帳號切換與串流競態
python3 scripts/task.py frontend-e2e

# 真正 Service Worker：舊版升級、資產 HTTP/MIME 失敗、離線與恢復
python3 scripts/task.py frontend-pwa
```

可設定 `LAYOUT_SCREENSHOT_DIR` 保存手機版截圖供人工檢查；Windows 若使用已安裝的 Edge，可設定 `PLAYWRIGHT_CHROMIUM_CHANNEL=msedge`。WebKit 模擬檢查不等同於 iPhone 實機驗證。

### AI 開發規範與自動驗證

`AGENTS.md` 是 Codex 等 Coding Agent 共用的專案規範；`CLAUDE.md` 會把同一份規範匯入
Claude Code，避免兩份規則日後分歧。Claude Code 的專案 Stop hook 只要發現工作樹有變更，
就會在完成回覆前執行 Ruff、mypy、架構／secret／文件一致性、Python coverage 與前端回歸測試；版面檔案有變更且
Playwright／Chromium／WebKit 齊全時，也會執行版面測試。

驗證失敗會把指令輸出送回 Claude 繼續修正。同一個 session 的同一份 diff 會重用本機快取，
避免每次停止都重跑。Hook 不會呼叫其他模型、外部 API，或傳送提示、diff、原始碼與測試輸出。
GitHub Actions 仍會在 push／pull request 執行 `verify`，並在獨立工作中安裝 Chromium／WebKit、跑完完整版面矩陣、真實 CRUD E2E 與 PWA 升級／離線測試；Dependabot 每週檢查 Python 與 GitHub Actions 更新。

本次驗證基線為 Python **382 passed**、前端回歸測試 **58 passed**；測試數量會隨功能與修正持續增加，實際結果以 `python3 scripts/task.py verify` 與 CI 當次輸出為準。
版面檢查涵蓋 WebKit／Chromium、亮／暗模式與 10 組直橫向尺寸，共 40 組設定，檢查六個功能分頁、三個認證表單、圖表、全部彈窗、行內編輯、停用／錯誤及空資料狀態。

主要表單、工具列與彈窗操作統一為 44px 控制項；桌面表格內的緊湊操作為 36px，手機至少 44px。
日期／月份欄位與一般輸入框等高，模型工具列及彈窗按鈕依可用空間換行；表格數字與表頭統一右對齊。
`frontend-layout` 同時驗證幾何對齊、同列邊界、圖表起點與無溢出，設定 `LAYOUT_SCREENSHOT_DIR` 可保存桌面／手機、認證及彈窗截圖人工覆核。

`docs-check` 會從 pytest collection、前端測試檔、Agent tool registry、Playwright 測試矩陣與實際檔案系統核對上述數字及 harness 路徑。新增測試、工具或版面設定卻忘記同步 README 時，`verify` 和 GitHub Actions 會直接失敗。

專案的規格不是只存在對話裡：[`docs/architecture.md`](docs/architecture.md) 是目前的
Software Design Description（含 Mermaid 架構圖與拆分順序），
[`docs/testing-strategy.md`](docs/testing-strategy.md) 是 Test Design Document（含需求追蹤矩陣），
重大取捨則記錄在 [`docs/adr/`](docs/adr/)。`architecture-check` 會把其中最重要的依賴規則
變成 CI 可執行的限制，避免文件和程式逐漸分歧。

新功能、資料模型、部署流程或架構變更先從 [`docs/specs/template.md`](docs/specs/template.md)
建立 feature spec，寫清楚 goals、non-goals、帳號隔離、migration、rollback、acceptance criteria
與測試追蹤；PR template 會要求連結 spec／ADR 與實際驗證結果。

鞋款、跑步日誌、月跑量與跑量目標的更新都會使用版本檢查，舊畫面遇到衝突時請重新載入後再操作。跑步日誌造成的鞋款與月跑量增減會在同一交易中處理；同月份彙總、首次建立目標及月報保存皆使用 SQLite 原子 upsert，避免同時寫入發生 500 或遺失更新。SQLite 連線啟用 foreign keys、30 秒 busy timeout 與 WAL，降低讀取分析和一般寫入互相鎖住的機率。已有逐筆日誌的月份不能直接改年月，必須先調整日誌日期；純手動月份仍可移動。改密碼後既有登入會失效，需重新登入。
啟動時會自動為既有資料庫補上鞋款、跑步日誌、月跑量、跑量目標與登入版本欄位，並依當前顯示總里程建立歷史調整基準；升級前後的顯示總里程不會改變。

現役與退役鞋皆只使用 Daily、Speed、Tempo、Race 四種用途分類。啟動時會移除既有資料中的 Trail、Walk 與舊 Other 標記，保留其他類別、里程及退役狀態；清理後沒有用途的鞋會顯示「未分類」，不會自動改成 Daily。清理會更新受影響鞋款的版本，重複啟動不會再次修改已清理資料。
新增跑鞋預設勾選 Daily，也可以取消所有類別；編輯未分類鞋款會保留空分類。換鞋提醒會檢查每個用途是否都有現役替代鞋，未分類鞋款則提示先分類。

## AI 開發萬用指示

在 Codex 或其他 Coding Agent 中開啟本專案後，可以複製以下內容，再把中間的需求換成這次要開發的功能或要修正的問題：

```text
請先閱讀 AGENTS.md，依照現有架構直接完成以下需求：

[在這裡描述新功能、Bug 的操作方式、目前結果與預期結果]

完成條件：
- 找出並處理根因，不要只隱藏表面症狀
- 保留既有行為、使用者資料隔離與安全限制
- 補上必要的回歸測試
- 不修改正式 shoes.db
- 執行 python3 scripts/task.py verify
- 如果有修改畫面版面，再執行 python3 scripts/task.py frontend-layout
- 最後列出修改內容、測試結果與仍存在的限制
```

如果目前只想討論方案、不希望 AI 修改檔案，請在開頭加上：

```text
先不要修改程式。請分析需求會影響哪些檔案、資料表和測試，並列出風險與建議方案。
```

## Docker 部署

```bash
# 1. Build image
docker build -t running-shoes .

# 2. 啟動 container（資料持久化）
docker run -d -p 8000:8000 -v shoes-data:/data \
  -e SECRET_KEY="$(openssl rand -hex 32)" --name running-shoes running-shoes

# 3. 在任何裝置瀏覽器開啟
open http://你的IP:8000
```

## Fly.io 部署流程

第一次部署至少需要設定 JWT 簽章密鑰；AI 功能另需 OpenRouter 金鑰：

```bash
# 必要：自動產生 256-bit JWT 簽章密鑰
fly secrets set SECRET_KEY="$(openssl rand -hex 32)"

# 必要：AI 助手功能需要 OpenRouter API 金鑰
# 取得: https://openrouter.ai/keys
read -rsp 'OPENROUTER_API_KEY: ' OPENROUTER_KEY_VALUE && echo
fly secrets set OPENROUTER_API_KEY="$OPENROUTER_KEY_VALUE"
unset OPENROUTER_KEY_VALUE
```

全新空資料庫不需要 `MIGRATION_PASSWORD`。只有升級尚未綁定使用者的舊版資料庫，或明確啟用 `SEED_DATA=true` 範例資料時才需要設定：

```bash
read -rsp 'MIGRATION_PASSWORD: ' MIGRATION_PASSWORD_VALUE && echo
fly secrets set MIGRATION_PASSWORD="$MIGRATION_PASSWORD_VALUE"
unset MIGRATION_PASSWORD_VALUE
```

之後每次部署只要：

```bash
# 先對正式資料建立並驗證快照；指令會保留最近 14 份
fly ssh console -a running-shoes -C \
  "python scripts/database_backup.py create --source /data/shoes.db --output-dir /data/backups --keep 14"

fly deploy

# 部署完成後確認 process、資料庫 schema 與公開 API contract
venv/bin/python scripts/smoke_test.py https://running-shoes.fly.dev
```

Fly 與 Docker 會呼叫 `/health/ready`；只有 SQLite 可讀且 schema version 正確才會回 200。
所有 HTTP response 也會附上 `X-Request-ID`，server log 只記錄 method、path、status、耗時與
request ID，不會記錄 Authorization、request body 或使用者資料。

部署架構：

```
git push (local) ──→ GitHub ──→ fly deploy ──→ Fly.io Builder
                                                    │
                                              Dockerfile 建置
                                                    │
                                         ┌──────────┴──────────┐
                                         │                     │
                         requirements.txt（鎖版+雜湊）     COPY backend/
                         pip --require-hashes             COPY frontend/
                                         │                     │
                                         └──────────┬──────────┘
                                                    │
                                            Python 3.11 容器
                                            uvicorn 啟動
                                                    │
                                        ┌───────────┴───────────┐
                                        │                       │
                              HTTP 請求 (port 8000)      SQLite 持久卷
                              HTTPS (自動)               /data/shoes.db
                                        │                       │
                                        └───────────┬───────────┘
                                                    │
                                              使用者瀏覽器
                                         https://你的app.fly.dev
```

### 資料庫備份、驗證與還原

本機或已下載的 SQLite 都使用同一個工具；它透過 SQLite backup API 取得交易一致快照、
建立 SHA-256 checksum、執行 `PRAGMA quick_check`，並確認必要資料表存在：

```bash
# 建立備份並只保留最近 14 份 managed snapshots
venv/bin/python scripts/database_backup.py create \
  --source shoes.db --output-dir backups --keep 14

# 下載或移動後再次驗證 checksum 與 SQLite integrity
venv/bin/python scripts/database_backup.py verify \
  --backup backups/shoes-YYYYMMDDTHHMMSSffffffZ.db
```

還原會覆蓋目標資料庫，因此必須先停止所有連線到該資料庫的 server／worker。工具要求明確輸入
`RESTORE`，取得 SQLite 獨占鎖，而且在覆蓋前會自動建立 `pre-restore` 安全快照；目標忙碌時會拒絕還原。
還原透過 SQLite backup API 處理，不直接替換主檔或手動刪除 WAL／SHM，避免殘留 WAL 蓋回舊資料；完成後再驗證目標：

```bash
venv/bin/python scripts/database_backup.py restore \
  --backup backups/shoes-YYYYMMDDTHHMMSSffffffZ.db \
  --destination shoes.db --confirm RESTORE
```

Fly volume 裡的 `/data/backups` 仍和正式資料位於同一個基礎設施，不能當成唯一備份；重要版本
應使用 `fly ssh sftp get` 下載到另一個裝置或受控儲存空間，下載後再執行 `verify`。未經停寫與
還原演練，不要直接替換運行中的 `/data/shoes.db`。

### Fly 外部備份與隔離還原演練

已有 Fly CLI 登入且 Machine 啟動時，可用同一支跨平台 Python 工具建立一致快照、下載 DB／checksum、
驗證並執行隔離還原演練；不覆蓋本機開發 DB，也不會對正式站進行還原：

```bash
python3 scripts/offsite_backup.py --app running-shoes \
  --output-dir /home/joy-teng/.local/share/running-shoes/backups

# 對既有快照重新演練，目的地只能是工具建立的 OS 暫存目錄
python3 scripts/database_backup.py drill --backup /absolute/path/to/snapshot.db
```

Windows 使用 `py -3` 與自己的專用儲存路徑即可。多台 Fly Machine 時可加 `--machine <id>`；
Machine 若已停止，先用 `fly machine start <id> -a running-shoes` 啟動。工具只使用既有的 Fly CLI
認證，不要求把 token 加入命令、程式或備份 manifest。

完成的備份目錄包含 `.db`、`.db.sha256` 與 `manifest.json`。只有 checksum、完整 SQLite integrity、
資料表筆數／內容摘要、schema（含 index/view/trigger）與 schema version 都通過隔離還原比較，才發布完成目錄；
下載或演練失敗只清理本次 private staging，既有本地備份不刪除。遠端 `/data/backups/offsite` 保留最近 14 份 managed snapshots。

完整 SQLite **包含所有帳號與密碼 hash**，不同於帳號匯出 JSON。不得提交 Git 或上傳公開 artifacts；
工具拒絕 Git 目錄，備份目錄 0700、檔案 0600，Windows 另需管理 ACL。建議啟用磁碟加密。
本機副本可應付 Fly Volume 故障，但不能同時抵抗本機遺失；未另外設定排程／第二儲存位置前，不宣稱有自動或多地備援。

### PWA 升級與離線邊界

每次發布須一併更新 HTML 的 `app-asset-version`、資產 query revision 與 SW cache 名稱。
安裝先檢查所有資源及 HTML revision，成功後才啟用；導覽不將新 HTML 塞入舊 cache。
新版資產下載失敗時保留完整舊 shell，恢復網路後重新更新；清理只限本 app 的 cache，不快取 API。
首次安裝必須連網；離線 app shell 不代表能離線查詢或寫入跑步資料。首次從舊 worker 遷移時亦應保持連線，
讓新 worker 完整安裝後再重新開啟。`frontend-pwa` 使用本機 fixture、不連正式站，也不等同 iPhone 實機驗證。

### 同步雲端資料到本地

雲端是 source of truth。本地開發想用最新資料時：

```bash
# 1. 停掉本地 server（避免 SQLite 檔案被鎖）
#    Ctrl+C 結束 venv/bin/python -m backend.run

# 2. 備份本地（建議，覆蓋前留個底）
cp shoes.db "shoes.db.local-$(date +%Y%m%d-%H%M%S).bak"

# 3. 查看 Fly Machine ID 與狀態
fly status -a running-shoes

# 4. 把下方 ID 換成上一步顯示的 Machine ID；若 STATE 是 stopped，再啟動它
FLY_MACHINE_ID=d8917edb352038
fly machine start "$FLY_MACHINE_ID" -a running-shoes

# 5. 使用 SQLite backup API 在雲端建立交易一致的暫存快照
fly ssh console --machine "$FLY_MACHINE_ID" -a running-shoes -C \
  "python -c \"import sqlite3; src=sqlite3.connect('/data/shoes.db'); dst=sqlite3.connect('/data/shoes.snapshot.db'); src.backup(dst); dst.close(); src.close()\""

# 6. 下載快照並覆蓋本機 shoes.db
fly ssh sftp get /data/shoes.snapshot.db ./shoes.db \
  --machine "$FLY_MACHINE_ID" \
  -a running-shoes

# 7. 刪除雲端暫存快照（不會刪到正式的 /data/shoes.db）
fly ssh console --machine "$FLY_MACHINE_ID" -a running-shoes -C \
  "rm -f /data/shoes.snapshot.db"

# 8. 重新啟動本地 server
venv/bin/python -m backend.run
```

**注意**：
- 本地 server 必須先停，否則 SQLite 鎖住會抓不下來
- 雲端是 source of truth — 本地被覆蓋後，本地的未同步更動會被洗掉
- `FLY_MACHINE_ID` 要換成當次 `fly status` 顯示的 ID；重新部署後 Machine ID 可能改變
- 專案設定了 `auto_stop_machines = "stop"`，閒置後自動停止是正常行為；若 SFTP 顯示 `no started VMs`，重新執行步驟 3～5 即可
- 新版 Fly CLI 的啟動指令是 `fly machine start`，不是 `fly start` 或 `flyctl start`
- 不要在服務運行時直接複製 `/data/shoes.db`；先用 SQLite backup API 建立快照，才能避免下載途中遇到寫入交易而取得不一致的檔案

反向同步（local → 雲端）目前沒有自動化流程，直接對雲端 UI 操作即可。

## 多使用者

任何人都可以在登入頁面註冊帳號，每個使用者的跑鞋資料完全隔離，互看不到。

## API 文件

啟動後開啟 `http://localhost:8000/docs` 查看 Swagger API 文件。
