# Running Shoes Dashboard

跑鞋追蹤 Dashboard — 記錄每雙跑鞋的里程、成本、生命週期，支援每月跑量統計與圖表視覺化，並內建 AI 跑鞋推薦助手。支援多使用者帳號，每人資料獨立隔離。

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

# 2. 建立並啟用虛擬環境
python3 -m venv venv
source venv/bin/activate

# 3. 安裝依賴
python -m pip install -r requirements.txt

# 4. 啟動伺服器
python -m backend.run

# 5. 開啟瀏覽器
open http://localhost:8000
```

第一次啟動會自動建立 `shoes.db`（資料表結構）。預設範例資料只在 `SEED_DATA=true` 時才會寫入（Fly.io 部署預設會 seed，本機開發則不會）。

### 本機使用 AI 助手

在專案根目錄建立 `.env` 檔，填入 OpenRouter API Key：

```bash
OPENROUTER_API_KEY=<你的 OpenRouter API Key>   # 取得: https://openrouter.ai/keys
# 選填：覆寫預設模型；未設定時使用 openrouter/free
OR_MODEL=openrouter/free
```

`.env` 會被自動載入，不需要手動 `export`。沒設定也不影響 Dashboard 的其他功能，只是 AI 助手無法使用。

## 功能特色

- **跑鞋全生命週期追蹤**：記錄品牌、鞋款、用途類別 (Daily / Speed / Tempo / Race / Trail / Walk，可多選)、購買日期、尺寸、價格、里程、預期壽命、月跑量
- **鞋櫃類別覆蓋分析**：判斷某雙鞋退役後其所有用途是否仍有其他現役鞋覆蓋，避免不必要地補鞋 (支援多用途鞋款)
- **智慧試算**：自動計算每 km 成本、折數、生命進度、預估退役日期
- **圖表視覺化**：生命進度條、每 km 成本比較、退役時間軸、月跑量佔比（Chart.js）
- **每月跑量統計**：獨立管理月跑量資料，支援年度趨勢圖
- **跑鞋資料匯出**：一鍵匯出 **XLSX / CSV**，支援 **現役 / 退役 / 全部** 三種範圍，欄位完整含品牌、鞋款、日期、尺寸、價格、里程、成本、生命進度、月跑量
- **AI 跑鞋推薦助手**：依你的實際資料給換鞋與選鞋建議（需設定 OpenRouter API Key），預設使用 `openrouter/free` 自動路由免費模型，也可手動指定其他模型
- **多使用者隔離**：每人資料完全獨立，支援註冊/登入/改密碼

## AI 跑鞋推薦助手

內建的 AI 助手會依你的**實際資料**給換鞋與選鞋建議：

- 讀取你的跑鞋清單、剩餘壽命、每月跑量趨勢（只看你自己的資料）
- 找出接近預期壽命、該準備替換的鞋
- 上網搜尋市售鞋款、規格、評價、價格，並附上來源連結
- 以繁體中文對話，過程逐步顯示推理與工具呼叫（SSE 串流）
- 使用 OpenRouter / OpenAI 原生 function calling；模型清單只顯示免費且宣告支援 `tools` 的模型
- 資料庫工具回傳具名 JSON；里程、剩餘壽命、百分比、成本與跑量統計由後端計算，LLM 只負責文字分析

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

需要設定 `OPENROUTER_API_KEY`（見上方）。預設模型為 `openrouter/free`：OpenRouter
會依請求需求，從當下可用的免費模型中自動選擇。免費模型的速率限制、延遲與可用性
可能波動，因此較適合個人使用、展示與低流量情境，不保證每次請求都成功。

前端下拉選單會顯示 OpenRouter 目前提供且支援工具呼叫的免費模型，點擊 🔄 可強制刷新；若要固定
其他預設模型，可設定 `OR_MODEL=<model-id>`。由於 Agent 使用原生工具呼叫，固定模型也必須
支援 OpenRouter 的 `tools` 參數。

## 測試

請使用專案虛擬環境執行，避免誤用系統 Python 而找不到 `ddgs` 等套件：

```bash
# 一般測試
venv/bin/pytest -q

# 同時檢查行覆蓋率與分支覆蓋率
venv/bin/pytest -q --cov=backend --cov-branch --cov-report=term-missing
```

目前測試基準為 **139 passed**，`backend` 的行覆蓋率與分支覆蓋率皆為 **100%**。

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
# 必要：管理員帳號的初始密碼（沒設會啟動失敗）
fly secrets set MIGRATION_PASSWORD=<你想設的密碼>

# 必要：JWT 簽章密鑰，請使用足夠長度的隨機字串
fly secrets set SECRET_KEY=<隨機安全字串>

# 必要：AI 助手功能需要 OpenRouter API 金鑰
# 取得: https://openrouter.ai/keys
fly secrets set OPENROUTER_API_KEY=<你的 OpenRouter API Key>
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
#    Ctrl+C 結束 python -m backend.run

# 2. 備份本地（建議，覆蓋前留個底）
cp shoes.db shoes.db.local.bak

# 3. 從 Fly.io 抓最新的 shoes.db
fly ssh sftp get /data/shoes.db ./shoes.db

# 4. 重新啟動本地 server
python -m backend.run
```

**注意**：
- 本地 server 必須先停，否則 SQLite 鎖住會抓不下來
- 雲端是 source of truth — 本地被覆蓋後，本地的未同步更動會被洗掉
- 免費方案機器會自動休眠，若 `fly ssh sftp get` 報「no started VMs」先跑 `fly machine start <id>` 叫醒（ID 從 `fly status` 查到）

反向同步（local → 雲端）目前沒有自動化流程，直接對雲端 UI 操作即可。

## 多使用者

任何人都可以在登入頁面註冊帳號，每個使用者的跑鞋資料完全隔離，互看不到。

## API 文件

啟動後開啟 `http://localhost:8000/docs` 查看 Swagger API 文件。
