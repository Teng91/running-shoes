# ADR-0003：共用 read models、功能生命週期與靜態來源生成

- 狀態：Accepted
- 日期：2026-10-20
- 規格：SPEC-017

## Context

單純拆檔未消除統計規則重複與全域狀態耦合：目標曾把手動調整算入、月報解析 AI 工具 JSON，
新增功能還必須修改 auth 的清理清單。維持個人服務的單一部署與低依賴，同時需要可檢查的依賴方向。

## Decision

- `read_models` 產生 user-scoped native dict；HTTP／AI tool adapters 各自序列化，月報直接使用 read models。
- `shoe_metrics` 是清單、單鞋分析、比較工具與匯出的共同算術來源。
- CSV 純解析拋領域錯誤，router 才映射 HTTP；架構檢查遞迴追蹤直接、relative 與 transitive imports。
- 每個前端功能註冊自己的 reset；auth 只使 session 失效並通知 registry。原生 ES module runtime 不引用 DOM／storage／transport。
- 漸進遷移而非一次重寫：既有 classic handlers 與共享資料仍保留，由 bridge 接上 native lifecycle。
- CSS／HTML partials 是人工維護來源；標準函式庫 generator 產生單一 CSS、完整 HTML 與原子 PWA shell。
  `assets.json` 固定順序；不在 runtime 載入 HTML partials 或多份 CSS，不引入 npm build pipeline。
- 明細分頁獨立於後端完整月彙總；支出按需讀取，不讓支出服務失敗阻擋首頁。

## Consequences

- 無 schema migration；新 API 及 ShoeOut 計算欄位為相容性新增。舊列表 API 仍可使用。
- 新功能只需在自身 module 註冊清理，不需要 auth 知道 feature DOM。舊請求仍須 session／identity guard。
- 來源及 generated outputs 都進 Git，CI 驗證產物零漂移；部署仍可直接服務靜態檔。
- 原生 `.mjs` 必須與 classic scripts 一起 precache／驗證 MIME；初始化失敗使用原有 loading/retry。
- 關閉對話框或取消畫面不保證撤回已提交的 HTTP 交易；版本衝突與後端交易仍是資料保護邊界。
- 保留單體；不用微服務、前端框架或只依行數硬切的方式增加維護負擔。

## Verification

SPEC-017 對應 Node 行為、Chromium/WebKit DOM、PWA native-module MIME、query budget、API 隔離與
統計一致性測試；`verify-all` 檢查生成產物、架構、lint/type、依賴安全、文件與所有瀏覽器流程。
