# Running Shoes Dashboard

跑鞋追蹤 Dashboard — 記錄每雙跑鞋的里程、成本、生命週期，支援每月跑量統計與圖表視覺化，並內建 AI 跑鞋推薦助手。支援多使用者帳號，每人資料獨立隔離。

## 使用方式

### 直接使用線上服務

開啟部署好的網址，註冊帳號即可開始使用，每個人的跑鞋資料完全隔離。

> 所有使用者共用同一個 Fly.io 免費容器（256MB RAM），人數或資料量過多可能影響效能。

### 自己部署

開源專案，歡迎 clone 下來自己跑：

```bash
# 1. Clone
git clone https://github.com/你的帳號/running-shoes.git
cd running-shoes

# 2. 安裝依賴
pip install -r requirements.txt

# 3. 啟動伺服器
python -m backend.run

# 4. 開啟瀏覽器
open http://localhost:8000
```

也可以部署到自己的 Fly.io 帳號或其他平台，完全獨立運作。

## 目錄結構

```
running-shoes/
├── backend/              # FastAPI 後端
│   ├── main.py           # API 路由 + 靜態檔案服務
│   ├── auth.py           # JWT 認證 + 密碼雜湊
│   ├── database.py       # SQLite 資料庫連線
│   ├── models.py         # 資料表定義
│   ├── schemas.py        # Pydantic schema
│   ├── agent.py          # AI 助手 agent loop（工具呼叫 + SSE 串流）
│   ├── llm.py            # LLM 抽象層（OpenRouter）
│   ├── tools/            # AI 助手工具
│   │   ├── db_tools.py   # 讀取使用者跑鞋 / 跑量資料
│   │   └── search_tool.py# 上網搜尋市售鞋款（DuckDuckGo）
│   └── run.py            # 本機開發啟動入口
├── frontend/
│   ├── index.html        # Dashboard 前端（Chart.js）
│   └── favicon.svg
├── unit_tests/           # Pytest 測試
├── requirements.txt      # Python 依賴
├── Dockerfile            # Docker 部署用
├── fly.toml              # Fly.io 部署設定
└── .gitignore
```

## 快速開始（本機開發）

```bash
# 1. 安裝依賴
pip install -r requirements.txt

# 2. 啟動伺服器
python -m backend.run

# 3. 開啟瀏覽器
open http://localhost:8000
```

第一次啟動會自動建立 `shoes.db`（資料表結構）。預設範例資料只在 `SEED_DATA=true` 時才會寫入（Fly.io 部署預設會 seed，本機開發則不會）。

想在本機使用 AI 跑鞋推薦助手，需在專案根目錄的 `.env` 設定 OpenRouter API 金鑰：

```bash
OPENROUTER_API_KEY=<你的 OpenRouter API Key>   # 取得: https://openrouter.ai/keys
```

沒設定也不影響 Dashboard 的其他功能，只是 AI 助手無法使用。

## AI 跑鞋推薦助手

內建的 AI 助手會依你的**實際資料**給換鞋與選鞋建議：

- 讀取你的跑鞋清單、剩餘壽命、每月跑量趨勢（只看你自己的資料）
- 找出接近預期壽命、該準備替換的鞋
- 上網搜尋市售鞋款、規格、評價、價格，並附上來源連結
- 以繁體中文對話，過程逐步顯示推理與工具呼叫（SSE 串流）

需要設定 `OPENROUTER_API_KEY`（見上方）。模型使用 OpenRouter 上的免費/低成本模型，可透過 `OR_MODEL` 環境變數指定預設模型。

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