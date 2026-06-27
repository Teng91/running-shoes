# Running Shoes Dashboard

跑鞋追蹤 Dashboard — 記錄每雙跑鞋的里程、成本、生命週期，支援圖表視覺化。

## 目錄結構

```
running-shoes/
├── backend/           # FastAPI 後端
│   ├── main.py        # API 路由 + 靜態檔案服務
│   ├── database.py    # SQLite 資料庫連線
│   ├── models.py      # 資料表定義
│   ├── schemas.py     # Pydantic schema
│   └── requirements.txt
├── frontend/
│   └── index.html     # Dashboard 前端（Chart.js）
├── Dockerfile         # Docker 部署用
└── .gitignore
```

## 快速開始

### 本機開發

```bash
# 1. 安裝依賴
pip install -r backend/requirements.txt

# 2. 啟動伺服器
python -m backend.run

# 3. 開啟瀏覽器
open http://localhost:8000
```

第一次啟動會自動建立 `shoes.db` 並寫入預設的範例資料。

### Docker 部署

```bash
# 1. Build image
docker build -t running-shoes .

# 2. 啟動 container（資料持久化）
docker run -d -p 8000:8000 -v shoes-data:/data --name running-shoes running-shoes

# 3. 在任何裝置瀏覽器開啟
open http://你的IP:8000
```

## 不同裝置共用資料

只要 Docker container 持續在伺服器上跑，同區域網路內任何裝置都可以連 `http://伺服器IP:8000` 使用，所有資料讀寫都指向同一份資料庫。

## API 文件

啟動後開啟 `http://localhost:8000/docs` 查看 Swagger API 文件。