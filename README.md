# Running Shoes Dashboard

跑鞋追蹤 Dashboard — 記錄每雙跑鞋的里程、成本、生命週期，支援圖表視覺化。支援多使用者帳號，每人資料獨立隔離。

## 使用方式

### 直接使用線上服務

開啟部署好的網址，註冊帳號即可開始使用，每個人的跑鞋資料完全隔離。

> 所有使用者共用同一個 Fly.io 免費容器（256MB RAM），人數或資料量過多可能影響效能。

### 自己部署

開源專案，歡迎 clone 下來自己跑，也可以部署到自己的 Fly.io 帳號或其他平台，完全獨立運作。

## 目錄結構

```
running-shoes/
├── backend/              # FastAPI 後端
│   ├── main.py           # API 路由 + 靜態檔案服務
│   ├── auth.py           # JWT 認證 + 密碼雜湊
│   ├── database.py       # SQLite 資料庫連線
│   ├── models.py         # 資料表定義
│   ├── schemas.py        # Pydantic schema
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

第一次啟動會自動建立 `shoes.db` 並寫入預設的範例資料。

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

## 多使用者

任何人都可以在登入頁面註冊帳號，每個使用者的跑鞋資料完全隔離，互看不到。

## API 文件

啟動後開啟 `http://localhost:8000/docs` 查看 Swagger API 文件。
