# Running Shoes Dashboard

跑鞋追蹤 Dashboard — 記錄每雙跑鞋的里程、成本與生命週期，並以跑步日誌追蹤每次跑步的日期、公里數及穿著鞋款。支援每月跑量與鞋款里程圖表，並內建 AI 跑鞋推薦助手。支援多使用者帳號，每人資料獨立隔離。

## 使用方式

### 直接使用線上服務

開啟部署好的網址，註冊帳號即可開始使用，每個人的跑鞋資料完全隔離。

> 所有使用者共用同一個 Fly.io 免費容器（256MB RAM），人數或資料量過多可能影響效能。

### 自己部署

開源專案，可依照下方「快速開始」在本機執行，也可以部署到自己的
Fly.io 帳號或其他支援 Docker 的平台。

## 目錄結構

```
running-shoes/
├── backend/              # FastAPI 後端
│   ├── main.py           # API 路由 + 靜態檔案服務
│   ├── auth.py           # JWT 認證 + 密碼雜湊
│   ├── database.py       # SQLite 資料庫連線
│   ├── models.py         # 資料表定義
│   ├── schemas.py        # Pydantic schema
│   ├── agent.py          # AI 助手 agent loop（工具呼叫 + SSE 串流，僅保留 streaming 版）
│   ├── llm.py            # LLM 抽象層（OpenRouter）
│   ├── tools/            # AI 助手工具
│   │   ├── db_tools.py   # 讀取使用者跑鞋 / 跑量資料
│   │   └── search_tool.py# 上網搜尋市售鞋款（DuckDuckGo）
│   └── run.py            # 本機開發啟動入口
├── frontend/
│   ├── index.html        # Dashboard 前端（Chart.js）
│   └── favicon.svg
├── unit_tests/           # Pytest 測試（API、Agent、LLM、migration 與邊界案例）
├── requirements.txt      # Python 依賴
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
venv/bin/python -m pip install -r requirements-dev.txt

# 4. 使用虛擬環境啟動伺服器
venv/bin/python -m backend.run

# 5. 開啟瀏覽器
open http://localhost:8000
```

建議直接使用 `venv/bin/python`，因為指令本身就明確指定虛擬環境，不會因為換了
Terminal、忘記 activate，或 IDE 使用另一個 shell 而誤用系統 Python。

專案保留兩份依賴清單是刻意的：

- `requirements.txt`：正式執行需要的套件，Docker／Fly.io 部署使用這份。
- `requirements-dev.txt`：先引用 `requirements.txt`，再加入 pytest、coverage、Ruff、mypy 與型別 stub，供本機開發及 CI 使用。

如果只想執行服務、不需要跑測試或程式碼檢查，也可以只安裝
`requirements.txt`。

若偏好先啟用虛擬環境，也可以使用以下等效方式：

```bash
source venv/bin/activate
python -m pip install -r requirements-dev.txt
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

第一次啟動會自動建立 `shoes.db`（資料表結構）。預設範例資料只在 `SEED_DATA=true` 時才會寫入（Fly.io 部署預設會 seed，本機開發則不會）。

### 本機使用 AI 助手

在專案根目錄建立 `.env` 檔，填入 OpenRouter API Key：

```bash
OPENROUTER_API_KEY=<你的 OpenRouter API Key>   # 取得: https://openrouter.ai/keys
# 選填：固定某個免費且支援 tools 的模型
OR_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free
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
```

`.env` 會被自動載入，不需要手動 `export`。沒設定也不影響 Dashboard 的其他功能，只是 AI 助手無法使用。

## 功能特色

- **跑鞋全生命週期追蹤**：記錄品牌、鞋款、用途類別 (Daily / Speed / Tempo / Race / Trail / Walk，可多選)、購買日期、尺寸、價格、里程、預期壽命、月跑量
- **鞋櫃類別覆蓋分析**：判斷某雙鞋退役後其所有用途是否仍有其他現役鞋覆蓋，避免不必要地補鞋 (支援多用途鞋款)
- **智慧試算**：自動計算每 km 成本、折數、生命進度、預估退役日期
- **圖表視覺化**：生命進度條、每 km 成本比較、退役時間軸、月跑量佔比（Chart.js）
- **每月跑量統計**：獨立管理月跑量資料，支援年度趨勢圖
- **跑步日誌**：記錄每次跑步的日期、公里數與鞋款，並以每日里程及鞋款佔比圖表統計當月跑量
- **跑鞋資料匯出**：一鍵匯出 **XLSX / CSV**，支援 **現役 / 退役 / 全部** 三種範圍，欄位完整含品牌、鞋款、日期、尺寸、價格、里程、成本、生命進度、月跑量
- **AI 跑鞋推薦助手**：依你的實際資料給換鞋與選鞋建議（需設定 OpenRouter API Key），可從目前免費且支援工具呼叫的模型中選擇
- **多使用者隔離**：每人資料完全獨立，支援註冊/登入/改密碼

## 跑步日誌

登入後切換到「跑步日誌」頁籤，即可為每次跑步選擇日期、公里數與穿著的鞋款。日誌支援新增、編輯與刪除，也可使用月份選擇器查看過去紀錄。現役與已退役鞋款都可用於日誌。

每個月份會即時計算：

- 總里程、跑步次數與跑步天數
- 平均每個跑步日的里程
- 當月使用里程最高的主力鞋
- 1 日到月底的每日里程長條圖（沒有跑步的日期以 0 顯示）
- 依鞋款匯總的里程分布圓環圖

跑步紀錄儲存在 SQLite `runs` 資料表，每筆資料都會綁定帳號與該帳號擁有的鞋款。後端會驗證鞋款擁有權，並啟用 SQLite 外鍵約束，避免無效或跨帳號的鞋款關聯。已被跑步紀錄使用的鞋款不能直接刪除，可改為移至退役，避免破壞歷史紀錄。每個帳號預設最多儲存 5,000 筆跑步紀錄，可用 `MAX_RUNS_PER_USER` 調整。

| API | 用途 |
| --- | --- |
| `GET /api/runs` | 取得目前帳號的跑步紀錄，依日期由新到舊排序 |
| `POST /api/runs` | 新增日期、公里數與鞋款 |
| `PUT /api/runs/{run_id}` | 編輯指定跑步紀錄 |
| `DELETE /api/runs/{run_id}` | 刪除指定跑步紀錄 |

## AI 跑鞋推薦助手

內建的 AI 助手會依你的**實際資料**給換鞋與選鞋建議：

- 讀取你的跑鞋清單、剩餘壽命、每月跑量趨勢（只看你自己的資料）
- 找出接近預期壽命、該準備替換的鞋
- 上網搜尋市售鞋款、規格、評價、價格；網址由後端驗證後顯示為安全來源卡片
- 以繁體中文對話，過程逐步顯示推理與工具呼叫（SSE 串流）
- 使用 OpenRouter / OpenAI 原生 function calling；模型清單只顯示免費且宣告支援 `tools` 的模型
- 資料庫工具回傳具名 JSON；里程、剩餘壽命、百分比、成本與跑量統計由後端計算，LLM 只負責文字分析
- 詢問市價、最新評價、上市資訊或具體市售鞋款規格時，後端會先用「官方規格」與「台灣價格／評價」查詢；搜尋失敗時禁止模型憑記憶補造資料
- 詢問「某雙鞋適合我嗎」時，後端會在同一輪先取得外部資料、鞋櫃與跑量，再交給模型綜合判斷，不必先問一次再等使用者確認
- 搜尋結果會過濾不安全網址、去除重複項目，並優先排列官方與可信評測來源；成功結果快取 15 分鐘，價格類查詢快取 5 分鐘
- 搜尋標題與摘要會限制長度，並以不可信的原生 tool 結果傳給模型，避免網頁文字偽裝成使用者或系統指令
- 「我最新的月跑量／跑鞋里程」等私人資料問題會優先查後端資料庫；「最新市售跑鞋」才會查網路
- 每則回答下方會由後端標示「即時搜尋」、「近期搜尋快取」、「不需要搜尋」或「搜尋失敗」，並列出可點擊的來源卡片與實際搜尋關鍵字

目前提供 7 個 Agent 工具：

| Tool | 用途 |
| --- | --- |
| `list_my_shoes` | 列出所有跑鞋，明確區分累積里程、預期壽命、剩餘里程、已使用百分比與分配月跑量 |
| `shoe_summary` | 統計鞋款數量、總里程、現役鞋花費及各鞋生命週期 |
| `monthly_mileage_stats` | 由後端計算總跑量、月均、近期趨勢及最近六個有跑量月份明細 |
| `nearing_end_of_life` | 找出達提醒門檻的現役鞋，並判斷同類別是否已有替代鞋 |
| `compare_shoes` | 比較兩雙鞋的用途、里程、壽命與每公里成本 |
| `shoe_category_status` | 分析 Daily / Speed / Tempo / Race / Trail / Walk 覆蓋及補鞋需求 |
| `web_search` | 搜尋市售鞋款、規格、評價與價格來源 |

需要設定 `OPENROUTER_API_KEY`（見上方）。前端預設選取 OpenRouter 最近 7 天 token
使用量最高的免費工具模型。免費模型的速率限制、延遲與可用性可能波動，因此較適合
個人使用、展示與低流量情境，不保證每次請求都成功。

前端下拉選單會顯示 OpenRouter 目前提供且支援工具呼叫的免費模型，並依最近 7 天 token
使用量由高到低排列；點擊 🔄 可強制刷新。若要固定其他預設模型，可設定
`OR_MODEL=<model-id>`。由於 Agent 使用原生工具呼叫，固定模型也必須支援 OpenRouter 的
`tools` 參數。

後端會再次驗證請求模型必須位於目前的免費工具模型清單，前端傳入任意模型 ID
不會直接使用伺服器的 OpenRouter API Key 呼叫。Agent API 同時限制單則訊息長度、
history 筆數，並套用每帳號、每 IP 與全站請求上限。公開驗證端點、註冊帳號總數、
每人跑鞋筆數、跑步紀錄筆數及模型列表刷新頻率也都有可透過環境變數調整的防濫用限制。

## 測試

請使用專案虛擬環境執行，避免誤用系統 Python 而找不到 `ddgs` 等套件：

```bash
# 不依賴 shell 是否已 activate；推薦用法
# 一般測試
venv/bin/pytest -q

# 同時檢查行覆蓋率與分支覆蓋率
venv/bin/pytest -q --cov=backend --cov-branch --cov-report=term-missing
```

目前測試基準為 **231 passed**；`backend` 敘述覆蓋率為 **98.70%**（四捨五入為 99%）、分支覆蓋率為 **95.96%**，含分支的整體覆蓋率為 **98.09%**（四捨五入為 98%）。

## Docker 部署

```bash
# 1. Build image
docker build -t running-shoes .

# 2. 啟動 container（資料持久化）
docker run -d -p 8000:8000 -v shoes-data:/data --name running-shoes running-shoes

# 3. 在任何裝置瀏覽器開啟
open http://你的IP:8000
```

## Fly.io 部署流程

第一次部署需要設定以下 secrets：

```bash
# 必要：管理員帳號的初始密碼（輸入時不會顯示；沒設會啟動失敗）
read -rsp 'MIGRATION_PASSWORD: ' MIGRATION_PASSWORD_VALUE && echo
fly secrets set MIGRATION_PASSWORD="$MIGRATION_PASSWORD_VALUE"
unset MIGRATION_PASSWORD_VALUE

# 必要：自動產生 256-bit JWT 簽章密鑰
fly secrets set SECRET_KEY="$(openssl rand -hex 32)"

# 必要：AI 助手功能需要 OpenRouter API 金鑰
# 取得: https://openrouter.ai/keys
read -rsp 'OPENROUTER_API_KEY: ' OPENROUTER_KEY_VALUE && echo
fly secrets set OPENROUTER_API_KEY="$OPENROUTER_KEY_VALUE"
unset OPENROUTER_KEY_VALUE
```

之後每次部署只要：

```bash
fly deploy
```

部署架構：

```
git push (local) ──→ GitHub ──→ fly deploy ──→ Fly.io Builder
                                                    │
                                              Dockerfile 建置
                                                    │
                                         ┌──────────┴──────────┐
                                         │                     │
                              requirements.txt            COPY backend/
                              pip install                 COPY frontend/
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
