# Running Shoes Dashboard

跑鞋追蹤 Dashboard — 記錄每雙跑鞋的里程、成本與生命週期，並以跑步日誌追蹤每次跑步的日期、公里數及穿著鞋款。支援每月跑量與鞋款里程圖表，並內建 AI 跑鞋推薦助手。支援多使用者帳號，每人資料獨立隔離，也可在手機上安裝為 PWA。

版本演進與相容性說明集中於 [`CHANGELOG.md`](CHANGELOG.md)，設計與測試規格位於 `docs/`。

## 使用方式

完整操作說明見 [使用指南：日常記錄、資料與同步、備份及清理本機資料](docs/user-guide.md)。

要把雲端資料帶到本機版：在雲端「資料與同步」按「下載目前帳號資料 JSON」，再於電腦執行的本機版登入、選檔、預覽並確認匯入。「只新增」保留既有內容；「新增並更新同來源資料（v2/v3）」可更新先前匯入的鞋款與跑步、檔案內月份調整、目標和月報，並保留額外資料及已刪除跑步。預覽會顯示接收網站／帳號與新增／更新筆數；不會覆寫整個資料庫，也不會刪除檔案未包含的資料。

一般連線時，跑步新增成功就直接存到雲端，不用按同步。「資料與同步」會依狀態顯示「同步待送跑步」或「更新雲端資料」；草稿、備份、歷史等低頻操作可按標題展開。JSON 不含草稿與待同步紀錄，請先確認沒有待送跑步再下載。「清除此帳號的本機資料」清理的是瀏覽器暫存，不是本機版資料庫；不刪除伺服器資料，但會丟失此裝置尚未同步的紀錄。

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
│   ├── actions/browser-setup/ # 三個 browser jobs 共用的鎖版環境
│   └── workflows/
│       └── verify.yml    # Push／PR 自動執行完整 harness 驗證
├── .claude/
│   └── settings.json     # Claude Code 完成回覆前執行確定性驗證的 Stop hook
├── backend/              # FastAPI 後端
│   ├── main.py           # 最小 ASGI 入口
│   ├── app_factory.py    # 可注入的 FastAPI 組裝、lifecycle 與 SPA fallback
│   ├── settings.py       # Immutable typed runtime configuration
│   ├── dependencies.py   # Request-scoped app settings dependency
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
│   │   ├── workspace.py  # 操作回執、歷史與帳號還原 adapters
│   │   ├── runs.py       # 跑步日誌 CRUD routes
│   │   └── shoes.py      # 跑鞋 CRUD HTTP routes
│   ├── services/
│   │   ├── account_restore.py # 預覽、來源 mapping 與原子合併還原
│   │   ├── operations.py  # 操作身分、版本及回執的統一寫入入口
│   │   ├── history.py     # User-scoped 歷史與防衝突誤刪復原
│   │   ├── identifiers.py # 單調遞增 run／month 主鍵配置
│   │   ├── accounts.py    # 註冊容量、密碼 CAS 與 token revocation 交易
│   │   ├── goals.py       # 個人目標 upsert、版本與 rollback
│   │   ├── reports.py     # 月報生成身分、事件及成功保存流程
│   │   ├── report_storage.py # 月報最新生成回執與條件寫入交易
│   │   ├── run_requests.py # User-scoped 日誌建立回執
│   │   ├── transactions.py # SQLite writer reservation 與交易生命週期
│   │   ├── runs.py       # 日誌寫入、重送、版本與里程交易
│   │   ├── shoes.py      # 鞋款配額、編輯與刪除交易
│   │   ├── monthly.py    # 月跑量與歷史調整交易
│   │   ├── exports.py    # Framework-independent 匯出內容生成
│   │   ├── strava_imports.py # Strava 匯入 transaction 與配對驗證
│   │   └── mileage.py    # 跑步、鞋款、月份彙總的交易式里程同步
│   ├── audit_schema.py   # 同交易異動事件及資料 revision triggers
│   ├── backup_contract.py # 有界 v1／v2／v3 備份格式與參照驗證
│   ├── migrations.py     # 有版本的 SQLite schema upgrade
│   ├── observability.py  # Request ID 與不含敏感內容的結構化 HTTP log
│   ├── rate_limits.py    # Auth／AI process 與 SQLite shared rate limits
│   ├── auth.py           # HTTP JWT 認證 adapter
│   ├── credentials.py    # 不依賴 HTTP 的 bcrypt／JWT primitives
│   ├── database.py       # SQLite 資料庫連線
│   ├── models.py         # 資料表定義
│   ├── schemas.py        # Pydantic schema
│   ├── agent.py          # AI 助手 runner 與公開 orchestration entry point
│   ├── agent_planner.py  # Deterministic intent 與最小查詢計畫
│   ├── agent_tools.py    # 受信任工具 dispatch
│   ├── agent_protocol.py # SSE 與搜尋來源摘要 contract
│   ├── reports.py        # 月報唯讀統計快照與提示詞
│   ├── report_llm.py     # One-shot LLM adapter
│   ├── report_protocol.py # 月報 domain events 的 SSE 序列化
│   ├── goals.py          # 個人月／年跑量目標與達成率計算
│   ├── forecasting.py    # 共用退役預估與 user-scoped 批次查詢
│   ├── shoe_metrics.py   # 共用折數、成本與壽命算術
│   ├── read_models/      # API／月報／AI 共用的 user-scoped native statistics
│   │   └── shoe_statistics.py # SQL 聚合與每雙鞋 12 筆 recent window
│   ├── analytics.py      # 首頁洞察與單鞋使用分析
│   ├── strava_import.py  # 純 Strava CSV 解析、篩選與領域錯誤
│   ├── exporting.py      # CSV／XLSX 安全匯出列與檔名
│   ├── llm.py            # LLM 抽象層（OpenRouter）
│   ├── tools/            # AI 助手工具
│   │   ├── db_tools.py   # JSON adapters 與受信任工具 registry
│   │   ├── tool_definitions.py # 工具 schema，與查詢／派發分離
│   │   ├── legacy_calls.py # 舊模型文字 tool calls 相容解析
│   │   └── search_tool.py# 上網搜尋市售鞋款（DuckDuckGo）
│   └── run.py            # 本機開發啟動入口
├── frontend/
│   ├── index.html        # 由 templates/ 產生的完整 Dashboard HTML
│   ├── assets.json       # Script 順序、CSS 來源與 PWA revision 的單一清單
│   ├── templates/        # Shell、七個彈窗與 worker 的可編輯來源
│   ├── css/              # 依責任拆分的樣式來源，產生單一 styles.css
│   ├── runtime/
│   │   ├── feature-lifecycle.mjs # 功能生命週期
│   │   ├── form-operations.mjs # 操作身分、草稿快照與成功回應合併
│   │   ├── resource-store.mjs # 請求合併、ownership、錯誤與快取失效策略
│   │   ├── workspace-controller.mjs # 注入帳號 storage／session 的草稿與同步佇列
│   │   ├── run-controller.mjs # 注入 transport/session 的跑步 state
│   │   └── strava-controller.mjs # 預覽、匯入與視窗操作所有權
│   ├── app-lifecycle.js  # Legacy handler 與原生 runtime 的過渡橋接
│   ├── app-inline-editors.js # 表格輸入 DOM、列快照與 session 清理
│   ├── app-dates.js      # 日曆日期與跨日限制／恢復
│   ├── app-dialogs.js    # 共用焦點、Tab、Escape 與彈窗語義
│   ├── app-updates.js    # 版本資訊與不強制重載的 PWA 更新提示
│   ├── app.js            # Dashboard 初始化與全域 dialog wiring
│   ├── app-boot.js       # 啟動 loading、逾時與 stylesheet readiness
│   ├── app-state.js      # 共用記憶體 state 與 presentation constants
│   ├── app-api.js        # HTTP／upload helpers
│   ├── app-auth.js       # 登入、註冊、登出與帳號切換
│   ├── app-streams.js    # 共用 SSE 解碼、取消與完成狀態
│   ├── app-resources.js  # 原生資源模組、session 與功能快取的過渡橋接
│   ├── app-local-store.js # IndexedDB 原子交易 adapter
│   ├── app-workspace.js  # 草稿、資源快照及同步 DOM adapter
│   ├── app-account-restore.js # 還原預覽與視窗操作身分
│   ├── app-history.js    # 異動分頁與誤刪復原 UI
│   ├── app-core.js       # Shell、主題、分頁與聚合資料載入
│   ├── app-dashboard.js  # 首頁卡片、提醒與跑鞋表格
│   ├── app-monthly.js    # 月跑量 CRUD、inline 表單與編輯快照
│   ├── app-exports.js    # 跑鞋匯出與帳號備份下載
│   ├── app-goals.js      # 跑步目標設定與期間進度
│   ├── app-charts.js     # 共用圖表 registry 與 label utilities
│   ├── app-shoe-charts.js # 跑鞋生命週期、成本、時間軸與分配
│   ├── app-monthly-charts.js # 月份／年度選擇與跑量圖表
│   ├── app-spending.js   # 支出摘要、圖表與表格
│   ├── app-agent.js      # AI 助手對話與串流呈現
│   ├── app-models.js     # AI／月報共用模型選單
│   ├── app-markdown.js   # 不可信 Markdown 的安全呈現
│   ├── app-reports.js    # 月報讀取、產生與串流顯示
│   ├── app-runs.js       # 跑步 CRUD、分頁與鞋款選擇
│   ├── app-strava.js     # Strava 預覽、配對與匯入 UI
│   ├── app-run-insights.js # 跑步月曆、洞察與單鞋分析 UI
│   ├── app-shoes.js      # 跑鞋編輯與 modal 互動
│   ├── styles.css        # 自動產生的單一樣式資產，請修改 css/ 來源
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
│   ├── build_frontend.py # 產生／驗證 HTML、CSS、PWA 清單，無 Node build 依賴
│   ├── claude_stop_hook.py # Claude Code 本機驗證與失敗回饋
│   ├── claude_stop_hook_launcher.cjs # 跨 Windows／Unix 尋找專案 Python
│   ├── check_architecture.py # 阻止反向依賴與重複 API route
│   ├── check_secrets.py  # 掃描 tracked files 的明確 credential 特徵
│   ├── check_docs.py     # 核對 README 數字、命令與文件契約
│   ├── document_contracts.py # 本地連結、spec 結構、AC 狀態與測試路徑
│   ├── database_backup.py # SQLite backup／checksum／retention／restore
│   ├── offsite_backup.py # Fly 外部下載、private staging 與隔離還原演練
│   ├── browser_runner.py # Browser 程序 deadline、錯誤落檔與子程序收尾
│   ├── browser_artifacts.cjs # 先存 error、限時 screenshot／trace／close
│   ├── smoke_test.py     # 部署後 health 與 OpenAPI smoke check
│   └── task.py           # 跨平台 setup、測試、eval 與完整驗證入口
├── unit_tests/           # Pytest、Agent eval、前端邏輯與版面回歸測試
│   ├── agent_eval_cases.json # Agent 工具選擇與安全行為案例
│   ├── frontend_regressions.cjs # Node 回歸測試單一入口
│   ├── frontend/         # 依責任拆分的 Node suite 與共享 helpers
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
- 1 日到月底的完整互動月曆；顯示每日里程與鞋款名稱，不顯示次數。空白日期可帶入新增表單，鞋款活動可篩選當日明細再編輯
- 跑步明細每頁 200 筆，月曆、總里程、跑步次數與鞋款分布不受目前明細頁影響
- 依鞋款匯總的里程分布圓環圖，以及各鞋實際里程與使用比例明細
- 每筆紀錄的來源標籤（手動或 Strava）
- 當月截至今天與上月同期、前 7 天的趨勢比較，以及月目標與鞋款壽命提醒；已結束月份維持整月比較，未來月份不會混入前一月資料
- 依目前節奏預測月底總里程，並顯示達標所需的每日里程
- 每雙鞋在所選月份的里程、穿著次數及占比

跑步紀錄儲存在 SQLite `runs` 資料表，每筆資料都會綁定帳號與該帳號擁有的鞋款。後端會驗證鞋款擁有權，並啟用 SQLite 外鍵約束，避免無效或跨帳號的鞋款關聯。編輯時會檢查紀錄版本；同一筆紀錄若已在其他分頁被修改，較舊的畫面會收到衝突提示，避免重複套用里程差額。刪除已有跑步紀錄的鞋款時，鞋款會從鞋櫃與未來選項中移除，但歷史跑步紀錄與月跑量仍會保留。每個帳號預設最多儲存 5,000 筆跑步紀錄，可用 `MAX_RUNS_PER_USER` 調整。前端只分頁載入目前查看月份；鞋款年度堆疊圖切換年份時才按需載入該年的後端彙總矩陣，避免每次操作都下載完整歷史。

| API | 用途 |
| --- | --- |
| `GET /api/runs` | 取得目前帳號的跑步紀錄；可用 `year`、`month`、`limit`（最多 500）與 `offset` 篩選／分頁，不帶參數時維持完整列表相容性 |
| `GET /api/runs/summary` | 指定 `year`、`month` 的完整月曆與鞋款／日誌彙總，不受明細分頁影響 |
| `GET /api/runs/year-summary` | 指定 `year` 的完整年度每月／每鞋里程矩陣；一次聚合查詢，不下載逐筆日誌 |
| `GET /api/running-goal/progress` | 指定 `year`、`month` 的日誌目標進度，與首頁／月報共用後端規則 |
| `GET /api/spending/summary` | 後端計算的總支出、折數、平均月支出與月份明細 |
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

### 前端來源與產物

編輯 `frontend/templates/`、`frontend/css/` 或 `frontend/assets.json` 後執行：

```bash
python3 scripts/build_frontend.py --write
python3 scripts/build_frontend.py --check
```

產物是 `index.html`、`styles.css` 與 `service-worker.js`，一併納入 Git；不是手動維護的第二份來源。
`verify` 與 `docs-check` 都會檢查來源／產物一致。CSS 保留原始 cascade 順序，瀏覽器仍只下載單一樣式檔。
原生 `.mjs` runtime 也包含在 PWA 原子 shell，並檢查 JavaScript MIME。
公開同源 shell cache 的查詢忽略 CORS `Vary: Origin`，避免預快取與原生模組的 Origin 差異
讓離線啟動失敗；URL／版本仍須完整匹配，`/api/` 一律不快取（SPEC-018）。

### 統計與操作規則（SPEC-017）

- 月跑量空白或無效不會送出；清零必須明確輸入 `0`。歷史／手動調整與日誌里程分開保留。
- 月跑量頁、首頁、月報目標皆只計逐筆日誌；鞋款成本／壽命指標由 `shoe_metrics.py` 統一計算。
- 刪鞋不移除日誌或年度堆疊里程；圖表保留「歷史鞋款／已刪除」群組。
- AI 遇到同名鞋回傳含購買日期及狀態的候選，必須詢問後以 ID 選定；批次使用分析不逐鞋查詢。
- 支出平均依後端日曆月份計算，不受瀏覽器時區影響；按需載入，失敗可在該區重試，不阻擋首頁。
- PWA 回到前景或跨日時更新日期上限，不改目前分頁／月份／草稿。登入換帳號則清除前帳號狀態與草稿。
- 彈窗支援 Tab、Shift+Tab、Escape 及返回原按鈕；關閉不等於撤回已送出的交易。
- 畫面顯示版本；新版完整安裝後提示更新，需使用者確認才重新載入，避免自動丟失尚未儲存內容。

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

# 部署後唯讀檢查（也可指定本機 fixture origin；缺瀏覽器會失敗，不跳過）
python3 scripts/task.py release-check --base-url https://running-shoes.fly.dev
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
npm ci
npx playwright install chromium webkit
python3 scripts/task.py frontend-layout

# Chromium 真實 CRUD（暫存 SQLite）＋ Chromium/WebKit mock 帳號切換與串流競態
python3 scripts/task.py frontend-e2e

# 真正 Service Worker：舊版升級、資產 HTTP/MIME 失敗、離線與恢復
python3 scripts/task.py frontend-pwa
```

可設定 `LAYOUT_SCREENSHOT_DIR` 保存手機版截圖供人工檢查；Windows 若使用已安裝的 Edge，可設定 `PLAYWRIGHT_CHROMIUM_CHANNEL=msedge`。WebKit 模擬檢查不等同於 iPhone 實機驗證。

Playwright 版本由 `package.json`／`package-lock.json` 鎖定，使用 `npm ci` 重現本機與 CI 的套件版本，
瀏覽器 harness 使用 Node.js 22+（CI 固定 Node 22），
本機由該版 Playwright 安裝匹配的 Chromium／WebKit；CI 使用同版本官方 noble container，已包含瀏覽器與系統依賴，避免每次下載 apt 套件。映像版本必須和 lockfile 同步（[官方容器說明](https://playwright.dev/docs/docker)）。瀏覽器失敗時在 `.artifacts/browser/` 保存截圖、trace 與錯誤輸出，
CI 明確允許上傳這個隱藏目錄並保留 7 天，範圍只限 browser diagnostics；可用 `npx playwright show-trace /path/to/trace.zip` 開啟。Artifacts 可能包含測試畫面，只記錄合成帳號或匿名 smoke，不對真實登入工作階段錄製。

Layout／CRUD／PWA 在 CI 分成 `frontend-layout`、`frontend-e2e`、`frontend-pwa`，共用鎖版初始化，不互相依賴。
引擎／操作階段使用明確 deadline；trace 啟動最多 10 秒，失敗時先保存原始錯誤文字，再讓 screenshot／trace 各最多 5 秒，context／browser close 也分別限時 5 秒。
外層 `browser_runner.py` 為 layout／E2E／PWA 設定 660／420／300 秒程序期限；超時先寫 watchdog 診斷，再終止該 runner 的子程序，回傳 124。
CI 失敗／取消時嘗試上傳已有產物；引擎完全卡死時可能只有錯誤文字，不能保證產生 trace。這些期限不改變產品的 API timeout 或重試策略。

診斷演練使用 `python3 scripts/task.py diagnostics-generate` 產生刻意失敗的合成 browser screenshot／trace／error，並驗證 checksum 與內容；
`python3 scripts/task.py diagnostics-verify` 可在只有 Python 標準函式庫的環境驗證 `.artifacts/browser/roundtrip/`。
CI 的 `frontend-pwa` job 上傳獨立 `browser-diagnostics-roundtrip` artifact，另一個 job 下載並驗證 PNG、trace ZIP 與合成錯誤標記，缺檔／損毀會讓 pipeline 失敗。

`frontend-e2e` 會對真實 FastAPI／CORS 與暫存 SQLite 執行同一個 `release-check`：檢查 readiness／schema、
完整 API contract、manifest 對應的 51 個 shell／worker 資產雜湊與 MIME、四個統計 API 的匿名拒絕存取，
再驗證 Chromium／WebKit 匿名手機啟動與 native runtime cache，以及 Chromium 離線重開。
WebKit 離線 shell 由 `frontend-pwa` 的 fixture transport 中斷驗證；API probe 在 HTTP headers 後截斷 response body，完整讀取 JSON 並檢查 server 請求計數，避免 headers 前 TCP 中斷讓裸 fetch 一直 pending。這些不取代引擎之外的實機驗證。
這個 task 不登入、不送出資料、不發布或回滾；正式 origin 必須是 HTTPS，HTTP 只允許 loopback。

### 請求、重試與跨分頁（SPEC-019）

- 月份／分頁載入錯誤有自己的提示，重試成功不掩蓋其他區塊的載入錯誤。
- 同源其他分頁登入、登出或換帳號時，本頁立即清理舊資料及取消未完成普通請求，回登入畫面；不刪除其他分頁的新憑證。這不是登出所有裝置。
- JSON CRUD／登入讀取有 20 秒 deadline（涵蓋 headers 與 body）；CSV upload 為 90 秒。GET 在 timeout／network／502–504 最多重試一次；寫入不自動重試。SSE 維持原串流取消流程，不套用 JSON deadline。
- `POST /api/runs` 支援可選 `Idempotency-Key`（16–128 字元，英數及 `._:-`），同帳號、同 key／內容會重播原始回應，不重複寫入日誌及里程；內容不一致回 409。無 key 的舊客戶端維持相容。
- 前端保留失敗新增表單的 key；原表單人工重試沿用，修改內容、成功或換帳號即建立新操作。同日同距離的兩次真實跑步不會被誤判重複。刪除後重播舊 key 不會復活日誌。

### 交易與草稿安全（SPEC-020，v3.5.0）

- 新增日誌等待回應期間，可繼續修改下一筆草稿；成功只清除仍符合送出快照的輸入，不覆蓋新日期、里程、鞋款或查看月份。
- 跑步、鞋款與月跑量的寫入由 application services 統一管理；取得 SQLite writer reservation 後才讀取配額與業務版本。並行新增不會突破鞋款／日誌上限，里程與重送回執維持同一交易。
- `create_app(config=...)` 的鞋款、日誌、註冊、Strava 配額及上傳限制由該 app instance 注入；測試不必改 router 全域常數。
- `runtime/run-controller.mjs` 擁有跑步明細／分頁／年度 cache、編輯快照與新增操作，明確注入 transport、session 與 key factory。DOM bridge 保留既有 handler，帳號切換統一清理 controller。
- 首頁、目標與月報共用日期區間邊界；月報的月份／上月同期／年度累積以一次 SQL 聚合取得，不再每月各查一次，仍不把手動歷史調整算成逐筆日誌目標。
- v3.5.0 維持 schema 2，不需資料 migration。回滾至 v3.4.0 image 可讀寫相同資料；重新發布舊來源仍需新 shell revision，不以舊備份覆蓋正式資料。

### 表單保護、暱稱與部分刷新（SPEC-023，v3.6.0）

- 月跑量新增成功只清除與送出時相同的年月及里程草稿；舊回應不會解鎖新操作、覆蓋新帳號錯誤或關閉重開的視窗。
- 跑步、月跑量與鞋款共用原生表單操作模組。等待期間改過的編輯草稿會保留，成功回應的版本用於下一次儲存。
- 新增／編輯鞋款可設定最多 80 字的暱稱（留空表示沒有暱稱）。跑步與 Strava 選單顯示暱稱、品牌型號、購買日期和 #ID，區分同款鞋；鞋款表、CSV／XLSX 與帳號備份保留暱稱。
- 月跑量異動只重讀月跑量；鞋款異動重讀現役與退役清單；跑步異動重讀鞋款、月跑量、明細與摘要。首次登入及手動重試仍完整讀取，匯入另更新 Strava 歷史。
- 購鞋支出快取只因鞋款異動失效；逐筆目標與年度統計因日誌異動失效。不同資源分別檢查請求身分及登入 session，舊完整讀取不會蓋掉新的部分刷新，其他來源成功也不會掩蓋尚未恢復的載入錯誤。
- 認證與目標寫入位於 `backend/services/accounts.py`／`goals.py`，密碼與 token primitives 位於 `backend/credentials.py`；router 保留輸入、rate limits 及 HTTP 轉換。
- v3.6.0 使用 asset revision 3.6.0／shell v28。Schema 3 新增 `shoes.nickname`，舊鞋預設空字串，保留原始里程與版本；新舊資料庫均提供 server default。

Schema 3 正式上線前，必須執行異地備份、checksum 與隔離還原演練。優先 forward fix；若要回滾 v3.5.1，先停止所有 writes、另做 schema 3 備份並確認只有新增 nickname 欄位，
再於停止的資料庫執行 `UPDATE schema_metadata SET value='2' WHERE key='schema_version' AND value='3';`，保留 nickname 欄位和新業務資料，部署已驗證的 schema 2 image。
不要以舊快照覆蓋新資料。重新發布舊來源仍須新 shell revision。

### 草稿狀態轉移與資源模組（SPEC-024，v3.6.1）

- 鞋款移至退役／現役成功後，保留的新草稿會同步最新模式、月跑量與版本；再次儲存只提交實際修改的欄位，避免撤銷剛完成的狀態轉移。
- 目標以 server baseline 比較草稿，失焦、主題切換與背景重繪皆保留未儲存內容；儲存期間的新修改也會保留，帳號切換會清理。
- `runtime/resource-store.mjs` 不依賴 DOM 或 HTTP，注入 session 與快取 hooks；同資源／key 的並行讀取共用 pending request，成功與錯誤各自管理，失效或換帳號後拒絕舊結果。
- `app-resources.js` 註冊既有快取 adapters；`app-core.js` 負責 reader 組合、套用結果與 render。某個來源失敗仍能更新其他成功來源，完整／部分刷新沿用 SPEC-023 的異動範圍。
- v3.6.1 使用 asset revision 3.6.1／shell v29；schema 仍為 3，沒有資料 migration，API method/path 不變。

### 匯入所有權與逐資源呈現（SPEC-025，v3.7.0）

- 編輯原鞋款已刪除的日誌，跨日／背景刷新仍保留「請重新選擇」；明確選取替代鞋款後才能儲存，避免自動轉移里程。
- Strava 預覽、匯入與視窗操作由 `runtime/strava-controller.mjs` 管理。取消／重開後，舊成功或失敗不關閉新視窗、不清除新預覽，也不解鎖其他提交；已完成的匯入仍刷新資料。
- Strava 歷史納入 resource store；匯入成功使舊讀取失效，新歷史及下次預設日期不會被晚到的舊回應覆蓋。
- 鞋款移至現役／退役保留點擊前和等待期間的其他未儲存欄位；再次儲存只更新這些欄位並使用新版本。狀態操作本身仍更新月跑量。
- 各資源完成即套用及呈現，慢來源不再阻擋已完成資料或持續蓋住啟動畫面；整批 Promise 仍可等待全部完成，失敗按來源保留。
- 單鞋及批次分析共用 SQL read model：三次查詢取得全歷史統計、12 個月聚合及每雙鞋最多 12 筆最近紀錄，不載入全部 Run entities；統計欄位及日期政策維持相容。
- PWA worker observer 同時觀測既有與新 installing candidate，deadline 涵蓋 update 呼叫與終態；失敗文字附註冊狀態時間線、目前階段及最近合成 HTTP 請求。中斷資產 fixture 在 headers 後截斷宣告的 body，避免 WebKit TCP 重試使錯誤掛起；worker 拒絕長度不符的未壓縮回應，避免截斷內容仍被當成成功。
- Asset revision 3.7.0／shell v30；schema 維持 3。部署前做異地備份及隔離還原演練，回滾可直接部署相容 schema 3 的 v3.6.1 image；不以舊資料覆寫正式站。

### 離線 worker 更新與佇列驗證（v3.7.1）

- v3.7.0 main CI 的 trace 顯示 worker update 卡在尚無 installing candidate 的 script request；相同 tag 的 PWA 已通過，不能以此略過 main 失敗。
- WebKit 離線 fixture 對 worker script 回 503，避免背景 register/update 在 TCP drop 後持續重試。每次恢復連線前，明確驗證離線 `registration.update()` 在 10 秒內失敗，然後驗證下一個在線候選正常處理；離線 shell／API exclusion 與 failed-upgrade gates 保留。
- v3.7.1 使用 asset revision 3.7.1／shell v31，仍是 44 個資產、schema 3。v3.7.0 tag 保留原始內容；正式發布及部署使用後續通過檢查的修正版。

### 首次顯示目標表單的草稿保護（v3.7.2）

- 切換月跑量時，在欄位可操作前同步初始化目標草稿 baseline；圖表仍於下一個 animation frame 繪製。即使在第一個 frame 前輸入並失焦，後續重繪及晚到的目標回應也不覆蓋草稿。
- 雙引擎 E2E 明確暫停首次 panel frame，先輸入再釋放，以固定重現原先的時序缺口。正式版本為 asset revision 3.7.2／shell v32，44 個資產、schema 3。

### 行內草稿、衍生資源與月報生成（SPEC-026，v3.8.0）

- 新增跑步草稿所選鞋款被刪除後，保留「請重新選擇」，直到明確選擇替代鞋款；重繪或跨日不默默換鞋。
- 資源完成只失效依賴它的分頁。鞋款／月跑量行內編輯保留輸入 DOM 與表格列快照；背景刷新、主題或跨日重繪不觸發部分數字儲存。Enter／使用者離開欄位才提交原始 id／version，Escape 取消，換帳號清理。
- 年度彙總、目標進度與首頁洞察透過 resource store 合併同 key 的 pending 與成功結果；失效後拒絕舊回應，失敗可重試。完整刷新導致的有效日誌失效可以啟動新讀取，單純重繪不增加請求。
- Strava 匯入期間停用配對選單；失敗可在同一視窗重新調整。舊操作不解鎖替換視窗。
- 月報採「最新開始的生成」：同帳號同月份的新請求開始後，舊請求即使較晚完成也不保存，串流回傳錯誤而非成功。新請求失敗／取消時保留先前成功報告，不讓舊請求重新取得資格。不同帳號／月份互不撤銷；LLM 等待不持有資料庫交易。
- Schema 4 僅新增 `report_generations`，每帳號／月份一筆最新身分，不產生可見的空月報；既有報告、里程與版本不改寫。Asset 3.8.0／shell v33，共 45 個資產。

Schema 4 上線前，執行異地備份、checksum 與隔離還原驗證。回滾優先 forward fix；若需回 v3.7.2，先停止所有實例與寫入、另備份 schema 4，確認新增表是唯一 schema 差異，
再對停止寫入的資料庫執行 `UPDATE schema_metadata SET value='3' WHERE key='schema_version' AND value='4';`，保留新增表與業務資料，部署已驗證的 v3.7.2 image。禁止混跑兩版月報生成服務；回滾後失去生成順序保護。還原部署前快照會遺失後續寫入，僅作災難復原選項。

### 可恢復的帳號工作區（SPEC-027，v3.9.0）

側欄「資料與同步」提供草稿、同步佇列、備份合併還原及異動歷史。Asset 3.9.0／shell v34，共 50 個資產；發布流程包含正式備份、隔離還原驗證、CI 與部署後匿名 release-check。

- 跑步、月跑量與目標表單自動存入 IndexedDB；鞋款、跑步、月份的彈窗／行內編輯保留原 ID、version 與輸入，可在工作區選擇恢復或捨棄。重開仍使用原版本，伺服器有新異動會回報衝突。資料按 origin／帳號分區，登出保留本機資料，另一帳號不可顯示或同步；共用裝置可按「清除此帳號的本機資料」。
- 僅新增跑步支援離線寫入。先以同一 IndexedDB 交易持久化 payload／operation ID 並消耗對應草稿，成功才清除仍相同的表單；等待時的新輸入保留。尚未同步不計入統計。連線且開啟 App、回到前景或按同步按鈕時重試；不承諾關閉 App 後背景同步。
- 多分頁以 120 秒原子 lease 避免同時發送，失聯重播同 operation ID，由伺服器交易回執防止重複。401 暫停等待重新登入；刪鞋、版本／配額或格式錯誤會列為「需要處理」，必須明確重新配對或移除，絕不默默換鞋。移除／清除會失去尚未同步紀錄，介面會先確認。瀏覽器儲存不可用時保留輸入並提示，連線可使用一般新增。
- 最近鞋款、月跑量、目標及目前月份跑步另存本機快照；它們可能過期，不作為伺服器權威。Service worker 只快取公開 shell，IndexedDB 不存 token／密碼。瀏覽器回收空間或使用者清除網站資料會移除本機草稿／佇列，請定期同步、下載備份；本機資料不是加密保險箱。
- 完整備份以同一資料庫讀取快照匯出，並行新增不會產生跨集合不一致。備份 JSON v2 包含穩定來源身分、鞋款基礎里程、月份歷史調整與異動歷史。選檔後先驗證／預覽，確認才在一個交易合併，保留既有暱稱、月份調整、目標與月報；不按同品牌型號合併鞋款。相同來源 ID／Strava ID 不重建，mapping 保留已刪紀錄的身分，重複匯入不撤銷後續刪除。新跑步正常累加里程。Strava 匯入摘要保留既有項目，剩餘容量內按新到舊合併，超額略過並在預覽列出，不清除既有摘要。舊 v1 格式仍接受，只保證完全相同檔案重複匯入不重建。
- 預覽僅限本人、有效 20 分鐘；預覽後資料異動須重新預覽。上限 20 MB、5,000 雙鞋、50,000 筆跑步／歷史、2,412 個月份／月報及 1,000 筆匯入歷史，並受目標帳號配額限制；拒絕非有限數值、無效參照、未知欄位與認證內容，失敗整筆回滾。超過還原限制的大型完整匯出不會截斷，需另行規劃資料搬移；不會靜默部分還原。
- Schema 5 起，鞋款、跑步、月跑量、目標每次寫入都在同一交易記錄前後值、原因及操作身分；升級前的歷史無法回溯產生。歷史分頁僅限本人；可復原刪除的跑步／鞋款及清除的月份，仍檢查原鞋款、目前版本、配額與 Strava 重複。復原會重新計算里程，原事件只可復原一次；備份帶入的歷史明確標為唯讀。
- `/api/operations` 統一 operation ID、更新／刪除 expected_version、成功回執與錯誤 `{detail, error: {code, message}}`。既有 CRUD 保留相容性，新增／帶版本的異動可附 `Idempotency-Key`；未提供版本的舊式刪除不取得新契約的重播保護。年度、目標與洞察已移除相容鏡像 Map，統一由 resource store 擁有請求與快取。

Schema 5 增加 user metadata、回執、預覽、mapping、異動、context 與主鍵配置表；既有業務資料／里程不改寫。Run／month ID 不因刪除而重用，避免恢復草稿寫到新紀錄；allocator 僅讀全域最大主鍵與 sequence 這類配置 metadata，不讀取其他帳號的業務值。上線前必須建立、校驗正式備份並完成隔離還原演練。若回滾至 v3.8.0，先停止所有寫入、另備份 schema 5，保留新增表／欄位／triggers，將 `schema_metadata` marker 降至 4，再切回舊映像及通過 readiness／匿名 release-check；舊版不再保證離線操作回執與主鍵不重用，不能混跑新舊寫入。重新升級需保留本機 queue 並使用新 shell revision。

### 雲端下載與本機匯入更新（SPEC-028／029，v3.10.0）

v3.10.0 使用 Asset 3.10.0／shell v35、schema 5、50 個資產。詳見 [使用指南](docs/user-guide.md) 與 [資料搬移規格](docs/specs/029-account-data-transfer.md)。

- `POST /api/account-restore/preview?mode=merge|update` 預設只新增；update 僅接受 v2，明確更新同來源鞋款與跑步、檔案內月份調整、目標及月報。模式與資料一起綁定本人預覽 hash／revision，apply 不接受切換模式。
- 更新保留接收端額外資料、已刪除跑步及不存在於檔案的內容；不是整個帳號的鏡像取代。鞋款刪除狀態依檔案更新，不按同品牌型號合併。所有總里程於後端重算，月報匯入會撤銷同月份舊生成的保存資格。
- 同步按鈕與下載在目前視窗顯示明確結果；接收網站／帳號、來源與更新筆數在確認前可見。使用者確認匯入才修改目前網站的資料，部署驗證不執行正式帳號匯入。
- 無 schema migration；回滾可直接部署 v3.9.0 image，維持 schema 5。新版已成功匯入的資料仍為既有格式；未完成的新預覽需重新預覽。部署前照常建立、校驗正式備份並完成隔離還原演練。

### Schema 2 上線與回滾

v3.4.0 只新增 `run_creation_requests` 表與 user/key 唯一約束，沒有改寫既有鞋款、日誌或里程。
部署前必須用下方異地備份工具下載快照並完成 checksum 與隔離還原演練；舊 v3.3.1 不接受 schema 2 marker，不能直接切回舊 image。
優先 forward fix。若確實回滾，停止所有 app writes、另做 schema 2 備份，確認 schema 2 只有新增 receipt 表後，
在停止的資料庫上執行 `UPDATE schema_metadata SET value='1' WHERE key='schema_version' AND value='2';`，保留 receipt 表與業務資料，再部署已驗證的 v3.3.1 image。
重新發布舊程式仍須新的 shell revision。不要以舊快照覆蓋已新增的正式資料；完整還原只用於確認可接受資料回溯的災難復原。

### 匯入操作隔離（SPEC-030，v3.10.1）

v3.10.1 使用 Asset 3.10.1／shell v36、schema 6、51 個 release assets。
[SPEC-030](docs/specs/030-import-operation-isolation.md) 修正跨帳號清除、無變更匯入的假衝突及預覽完成順序問題。
每份預覽獨立有效 20 分鐘，同帳號最多 8 份、合計 64 MiB；關閉／換檔會以本人
`DELETE /api/account-restore/preview/{token}` 捨棄不用的 token，失敗由到期清理回收。其他分頁與晚到請求不會撤銷仍有效的預覽；業務資料變更仍需重新預覽。
相同內容的更新不增加版本或異動紀錄，額外資料的編輯仍可正常儲存。

Schema 5→6 只以交易重建 `restore_previews` 的 `(user_id, token)` 主鍵並保留現有預覽，不修改業務表。
部署前建立異地備份、校驗與隔離還原，並在私有副本重複升級驗證資料不變。
回滾優先 forward fix；確需回 v3.10.0，先進入維護環境停止所有 HTTP／背景寫入、另做 schema 6 備份，
以 Python `sqlite3.Connection.executescript` 在掛載的資料庫執行
[`scripts/rollback_preview_schema.sql`](scripts/rollback_preview_schema.sql)，再部署先前 v3.10.0 immutable image
`registry.fly.io/running-shoes@sha256:a6281907140cc065db385eb68769ed86fc2cbbb4757678c48d04755d361bbb78`。
此程序只捨棄暫存預覽、恢復 schema 5 預覽主鍵及 marker，不以舊快照覆蓋跑步資料；不得混跑兩版。
重新上線後需重新預覽並執行匿名 release-check。

### 可靠帳號資料搬移（SPEC-032，v3.10.2）

v3.10.2 使用 Asset 3.10.2／shell v37、schema 6、51 個 release assets。
[SPEC-032](docs/specs/032-trustworthy-account-transfer.md) 將提交成功與畫面載入分開：若匯入已完成但讀取失敗，
按「重新載入資料」只重新讀取，不會再次匯入；提交回應不確定時仍沿用原操作重試。
預覽分別顯示新增、實際變更與內容相同，並保留已刪除跑步及額外本機資料。

`GET /api/export/account?include_history=true` 預設包含全部異動歷史；兩個下載入口均可明確取消「包含異動歷史」，
產生檔名以 `_without_history.json` 結尾的資料檔，業務資料不會省略。匯出與匯入共用集合、格式、秘密檢查及 20 MiB 上限，
下載前驗證可重新匯入；超限會顯示原因，不產生檔案、不靜默截斷。每份最多 5,000 雙鞋、50,000 筆跑步、
2,412 個月份／月報、1,000 筆 Strava 摘要及 50,000 筆異動歷史。取消歷史後仍超限時，需使用下方管理員完整資料庫備份流程。

本版無 schema migration。部署前完成異地備份及隔離還原；若需回滾可直接使用 v3.10.1 immutable image
`registry.fly.io/running-shoes@sha256:ba35ff3051b2c627ebf3b59fdb091747e93db2c0fc3a91c14320ca8411bde804`，
schema 6 保持相容，不還原舊業務快照。

### 復原與同步身分（SPEC-033，v3.10.3）

v3.10.3 使用 Asset 3.10.3／shell v38、schema 6、51 個 release assets。
[SPEC-033](docs/specs/033-recovery-and-sync-identity.md) 補足刪除、復原與再次匯入的組合操作：
同帳號舊備份不重建已刪跑步；明確復原後，原來源及舊 ID 的對應會跟隨復原紀錄，後續更新匯入仍可修改該筆資料。
每次離線送出使用獨立租約，重新登入接手後不受舊請求的延遲結果影響。
同步已送出而畫面讀取失敗時會明確提示重新整理；誤刪復原已成功而讀取失敗時，按「重新載入資料」只重試讀取。
核心刷新驗證由 resource bridge 共用；跑步來源復原別名由 `backend/services/run_identity.py` 管理，服務仍由呼叫端持有交易。

本版無 schema migration，回滾可使用 v3.10.2 immutable image
`registry.fly.io/running-shoes@sha256:bac44457f12adfde6473e9d9a973b330e1bf69eac7e44feb3fb6ed1f5a55429a`，
不還原業務資料快照。發布驗證涵蓋 verify、40 組版面、雙引擎 CRUD／PWA、main/tag CI 及正式站匿名 release-check。

### 資料與同步操作簡化（SPEC-035，v3.10.5）

目前前端使用 Asset 3.10.5／shell v40、schema 6。同步區依待送跑步及網路狀態顯示動作；草稿、備份／匯入、歷史和本機清理預設收合。

### 來源復原搬移與跨分頁同步（SPEC-034，v3.10.4）

v3.10.4 使用 Asset 3.10.4／shell v39、schema 6、51 個 release assets。
[SPEC-034](docs/specs/034-portable-recovery-and-sync-refresh.md) 修正來源網站復原後再次搬移的重複跑步、浮點尾差造成的假更新，以及其他分頁送出後畫面未刷新的問題。

新下載使用 **備份 JSON v3**，每筆跑步的 `aliases` 保留同一來源復原前的 ID；省略異動歷史仍保留這項來源身分。
單檔最多 50,000 個別名，共用 20 MiB 限制，超限拒絕下載，不靜默裁切。別名須唯一且不能指向不同跑步；若既有對應已衝突，預覽會拒絕，不會自動刪除或合併資料。
新版仍接受 v1/v2；v1 指紋沿用舊算法，避免升版後重建舊檔。舊 App 不接受 v3，請先更新接收端再匯入，不能手動刪除別名或改版本以繞過檢查。

里程累積與比較統一兩位精度，既有儲存浮點尾差不會觸發無意義的版本更新。
「更新雲端資料」即使沒有待送出紀錄也會讀取雲端；回到前景或同帳號另一分頁成功送出時同樣刷新，保留未送出的輸入。
支援 BroadcastChannel 的瀏覽器會接收跨分頁提交通知；通知不可用時，回到前景或按「更新雲端資料」仍可刷新。通知期間又收到提交會補做一次讀取，舊帳號通知不影響目前帳號。

無 schema migration。部署前驗證正式異地備份及隔離還原；回滾可部署 v3.10.3 image
`registry.fly.io/running-shoes@sha256:5def65ac422062ac5a7e4c932d5d8dd4c76c5e1a184e46d11759d9781e4af690`。
回滾後 v3 檔案需保留至接收端重新升級才能匯入，DB 對應仍相容，不還原舊業務快照。

### AI 開發規範與自動驗證

`AGENTS.md` 是 Codex 等 Coding Agent 共用的專案規範；`CLAUDE.md` 會把同一份規範匯入
Claude Code，避免兩份規則日後分歧。Claude Code 的專案 Stop hook 只要發現工作樹有變更，
就會在完成回覆前執行 Ruff、mypy、架構／secret／文件一致性、Python coverage 與前端回歸測試；版面檔案有變更且
Playwright／Chromium／WebKit 齊全時，也會執行版面測試。

驗證失敗會把指令輸出送回 Claude 繼續修正。同一個 session 的同一份 diff 會重用本機快取，
避免每次停止都重跑。Hook 不會呼叫其他模型、外部 API，或傳送提示、diff、原始碼與測試輸出。
GitHub Actions 仍會在 push／pull request 執行 `verify`，並以三個可獨立重跑的 browser jobs 執行完整版面矩陣、真實 CRUD E2E 與 PWA 升級／離線測試；Dependabot 每週檢查 Python 與 GitHub Actions 更新。

本次驗證基線為 Python **541 passed**、前端回歸測試 **146 passed**；測試數量會隨功能與修正持續增加，實際結果以 `python3 scripts/task.py verify` 與 CI 當次輸出為準。
版面檢查涵蓋 WebKit／Chromium、亮／暗模式與 10 組直橫向尺寸，共 40 組設定，檢查六個功能分頁、三個認證表單、圖表、全部彈窗、行內編輯、停用／錯誤及空資料狀態。

主要表單、工具列與彈窗操作統一為 44px 控制項；桌面表格內的緊湊操作為 36px，手機至少 44px。
日期／月份欄位與一般輸入框等高，模型工具列及彈窗按鈕依可用空間換行；表格數字與表頭統一右對齊。
`frontend-layout` 同時驗證幾何對齊、同列邊界、圖表起點與無溢出，設定 `LAYOUT_SCREENSHOT_DIR` 可保存桌面／手機、認證及彈窗截圖人工覆核。

`docs-check` 會從 pytest collection、前端測試檔、Agent tool registry、Playwright 測試矩陣與實際檔案系統核對上述數字及 harness 路徑；release-check 的 shell／worker 資產數量也由同一 manifest 推導。新增測試、工具、版面設定或 native module 卻忘記同步 README 時，`verify` 和 GitHub Actions 會直接失敗。另檢查 Markdown 本地連結／標題 anchor、spec 必要章節／Owner／狀態、Implemented 規格的 AC 勾選及 traceability 測試檔路徑；SPEC-020 起每個 AC 都要連結明確測試路徑或 repository command。SPEC-023 起每個 AC 必須引用實際存在的 `unit_tests/file.py::test_name` 或 `unit_tests/frontend/feature.test.cjs::test title`；Python 支援 class 與參數化節點，Node 使用具名 literal test title。這些是靜態檢查，行為正確性仍由回歸測試與 review 確認。

專案的規格不是只存在對話裡：[`docs/architecture.md`](docs/architecture.md) 是目前的
Software Design Description（含 Mermaid 架構圖與拆分順序），
[`docs/testing-strategy.md`](docs/testing-strategy.md) 是 Test Design Document（含需求追蹤矩陣），
重大取捨則記錄在 [`docs/adr/`](docs/adr/)。`architecture-check` 會把其中最重要的依賴規則
變成 CI 可執行的限制，避免文件和程式逐漸分歧。

新功能、資料模型、部署流程或架構變更先從 [`docs/specs/template.md`](docs/specs/template.md)
建立 feature spec，寫清楚 goals、non-goals、帳號隔離、migration、rollback、acceptance criteria
與測試追蹤；PR template 會要求連結 spec／ADR 與實際驗證結果。

鞋款、跑步日誌、月跑量與跑量目標的更新都會使用版本檢查，舊畫面遇到衝突時請重新載入後再操作。跑步日誌造成的鞋款與月跑量增減會在同一交易中處理；同月份彙總與首次建立目標使用 SQLite 原子 upsert，搭配交易與版本條件處理並行寫入。月報另以 user／月份的最新生成身分，在同一寫交易中驗證並保存，舊生成不會覆蓋新內容或統計快照。SQLite 連線啟用 foreign keys、30 秒 busy timeout 與 WAL，降低讀取分析和一般寫入互相鎖住的機率。已有逐筆日誌的月份不能直接改年月，必須先調整日誌日期；純手動月份仍可移動。改密碼後既有登入會失效，需重新登入。

並行改密碼使用原密碼與登入版本的條件更新；過期請求回 409，請重新登入後再試，避免覆寫較新的密碼或保留應撤銷憑證。註冊在資料庫寫入保留後才檢查同名與容量，空資料庫與多 worker 皆適用；同名維持回 400、容量不足回 403（SPEC-021）。
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

Docker build context 排除 SQLite 主檔、WAL／SHM、DB 備份、backups 目錄與 `.env`；正式資料只保留在掛載 volume。

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
# 先建立異地快照，驗證 checksum 與隔離還原；備份目錄必須位於 Git 外
python3 scripts/offsite_backup.py --app running-shoes \
  --output-dir /home/joy-teng/.local/share/running-shoes/backups

fly deploy

# 部署後匿名唯讀檢查 schema、API、資產 hash/MIME、boot 與離線 shell
python3 scripts/task.py release-check --base-url https://running-shoes.fly.dev
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
首次安裝必須連網；完成安裝且此帳號已載入鞋款後，可離線查看最近快照、恢復草稿與新增跑步至本機佇列；伺服器統計須連線同步。首次從舊 worker 遷移時亦應保持連線，
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
