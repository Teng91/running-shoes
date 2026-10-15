# Software Design Description（SDD）

本文件描述 Running Shoes 的目前架構、模組邊界與下一步拆分方向。它不是理想化的完成圖；
圖中明確保留 `backend/main.py` 尚未拆出的核心路由，讓文件和程式碼維持一致。

## 1. 設計目標

- 維持單一 FastAPI／SQLite 部署，優先符合目前 Fly.io 資源與維運規模。
- 依功能邊界拆成模組化單體（modular monolith），避免為了「看起來有架構」提早引入微服務。
- HTTP router 只處理驗證、參數與 response；計算與資料轉換放在 domain/service 模組。
- 所有資料查詢與修改都必須帶入 `current_user.id`，不可跨帳號存取。
- 外部 LLM 與搜尋是可失敗的 adapter，不可成為跑鞋、跑量和支出計算的資料來源。
- 架構規則、測試與文件可由 CI 重複驗證。

## 2. 系統脈絡

```mermaid
flowchart LR
    User[使用者瀏覽器] -->|HTTPS / JSON / SSE| App[Running Shoes FastAPI]
    App -->|SQLAlchemy| DB[(SQLite / Fly Volume)]
    App -->|模型與工具呼叫| OpenRouter[OpenRouter API]
    App -->|鞋款公開資料搜尋| Search[DuckDuckGo]
    App -->|HTML / JS / CSS / PWA| User
```

## 3. 目前後端元件

```mermaid
flowchart TB
    Browser[frontend modules] --> Main[backend/main.py<br/>composition root + lifecycle]

    Main --> Core[尚待拆分的 core routes<br/>auth / shoes / runs / goals]
    Main --> Insights[routers/insights.py<br/>analytics / exports / spending]
    Main --> AI[agent + report routes]

    Insights --> Auth[auth.py]
    Insights --> Analytics[analytics.py]
    Insights --> Exporting[exporting.py]
    Core --> Goals[goals.py]
    Core --> Strava[strava_import.py]
    AI --> Agent[agent.py]
    AI --> Reports[reports.py]
    Agent --> Tools[tools/]

    Auth --> Models[models.py]
    Analytics --> Models
    Exporting --> Models
    Goals --> Models
    Strava --> Models
    Reports --> Models
    Tools --> Models
    Models --> Database[database.py / SQLite]
```

`backend/main.py` 是 composition root：建立 FastAPI、掛載 middleware／router，並暫時保留
尚未拆出的 routes 與啟動 migration。`backend/routers/insights.py` 是第一個完成的後端垂直切片；
它不能反向 import `backend.main`，因此可以獨立測試，也不會形成 circular import。

## 4. 模組責任與依賴方向

| 模組 | 責任 | 可以依賴 | 不應依賴 |
| --- | --- | --- | --- |
| `backend/main.py` | app 組裝、middleware、lifecycle、舊路由相容層 | routers、domain、database | frontend 實作細節 |
| `backend/routers/` | HTTP 參數、認證 dependency、response | auth、domain/service、models | `backend.main` |
| `backend/analytics.py`、`goals.py`、`reports.py` | 可重用的業務計算與 use case | models、LLM adapter（僅 AI use case） | FastAPI app、frontend |
| `backend/exporting.py`、`strava_import.py` | 輸入／輸出轉換 | models 或純資料 | FastAPI app |
| `backend/tools/` | Agent 可使用的受信任工具 | database、models | route 與 UI state |
| `backend/database.py`、`models.py` | persistence 與 schema | SQLAlchemy | router、frontend |

依賴方向由入口往內：`main → router → domain/service → persistence/adapters`。CI 的
`architecture-check` 會阻止 router 反向 import `backend.main`，並檢查 API method/path 是否重複。

## 5. 關鍵流程：跑鞋匯出

```mermaid
sequenceDiagram
    actor U as 使用者
    participant R as insights router
    participant A as auth dependency
    participant D as SQLite
    participant E as exporting service

    U->>R: GET /api/export?format=xlsx&mode=active
    R->>A: 驗證 JWT
    A-->>R: current_user
    R->>D: 只查 current_user.id 的未刪除鞋款
    D-->>R: shoes
    R->>E: 產生安全欄位與檔名
    E-->>R: rows / filename
    R-->>U: StreamingResponse
```

## 6. 不可破壞的品質屬性

- **帳號隔離**：任何 user-owned table 查詢都必須包含 `user_id`。
- **交易一致性**：跑步日誌與鞋款／月跑量的里程差額在同一交易內完成。
- **向後相容**：外部 API path、payload 與下載格式在純重構時不得改變。
- **資料安全**：帳號備份不得包含密碼 hash、JWT secret、API key 或其他帳號資料。
- **確定性測試**：測試使用暫存／記憶體資料庫，LLM 與搜尋必須 mock。
- **可部署性**：維持單一 container 與 SQLite volume；拆分模組不等於拆分服務。

## 7. 演進順序

1. **已完成**：前端依 dashboard、AI assistant、月報拆分；後端建立 insights router。
2. **下一階段**：抽出 shoes 與 runs routers，並把共用里程交易整理成 service。
3. **再下一階段**：抽出 auth／rate-limit 與 agent／reports routers。
4. **最後**：將 startup migration 移到獨立 migration 模組；`main.py` 只保留 app factory 與組裝。

每一階段都先以既有 API regression tests 鎖住行為，再移動程式碼；不在同一個 commit 同時
改變 endpoint contract 與模組邊界。

