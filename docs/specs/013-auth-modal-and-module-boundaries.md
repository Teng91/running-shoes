# SPEC-013：登入競態、跑鞋視窗與責任拆分

- 狀態：Implemented（v3.2.2）
- Owner：Running Shoes
- 關聯 issue／ADR：專案檢查五項改善；ADR-0001

## Problem

登入舊回應能覆蓋新 session；跑鞋視窗的舊提交能關閉新草稿。月報讀取時間未帶 UTC offset，
且顯示未沿用串流完成時的本地格式。Strava async route 直接執行 CSV 與同步 DB 操作。
月跑量 module 混合匯出與目標設定，圖表 module 混合共用工具、跑鞋與月跑量圖。

## Goals

- 登入／註冊／密碼更改共享認證操作生命週期；防重送、取消與 generation 檢查隔離舊回應。
- 跑鞋新增／編輯／刪除／移動使用單一視窗快照、原始 version/session 與提交鎖。
- 報告 JSON 時間統一為帶 offset 的 UTC；讀取與生成顯示同一本地時間。
- 上傳 byte limit 維持原樣，CSV 與 DB 工作在 worker thread 執行，交易與使用者隔離維持。
- 依責任拆成 exports、goals、共用 chart utilities、shoe charts、monthly charts，行為不變。

## Non-goals

- 不改 UI 版面、API path、資料庫 schema、密碼政策或引入工作佇列／bundler。
- 不搬移正式業務資料；自動測試不得連線正式服務或外部模型。

## Proposed design

- 認證操作使用物件 identity、AbortController 與 auth generation；表單轉換與 clearAuth 失效舊操作。
- ShoeModal 將 mode、shoe、session 保存於每次開啟的 context；只有相同 context 可關閉、顯示錯誤及解鎖。
- schemas 提供 UTC timestamp serializer helper；report JSON 與 SSE completion 共用，frontend 共用 formatLocalTimestamp。
- Strava route await upload 後，以一次 run_in_threadpool 呼叫執行 parse/filter/service；傳入 scalar user ID，現有 request session 只在該次 worker 內順序使用。
- 原函式名稱與 plain-script 契約保留；index、SW、harness 清單與 module dependency 圖同步更新。

## Security and data isolation

過期登入、錯誤及操作 callback 不得重設或改寫另一 session。跑鞋寫入仍帶 expected_version。
所有 DB query 與 transaction 保留 user_id 篩選；取消 HTTP 不宣稱可撤銷已提交的 transaction。

## Migration, rollout, and rollback

- Schema／資料 migration：無；時間字串增補 offset，舊 client 仍可讀取。
- 發布 v3.2.2，更新 PWA shell／資產版本；執行 verify-all、部署前 SQLite 快照與 checksum 驗證。
- 使用者授權 add／commit／push／tag／release／Fly deploy；上線後檢查 readiness、OpenAPI 與靜態資產一致性。
- 回滾為 v3.2.1 映像；資料格式相容，無需還原業務資料。

## Acceptance criteria

- [x] AC-1：重複登入只有一個請求；表單／session 切換後晚到成功與失敗都不改變新帳號或 loading。
- [x] AC-2：跑鞋所有 mutation 防重送；A 視窗請求完成或失敗不關閉、不改寫 B 草稿，登出後不操作新 session。
- [x] AC-3：SQLite 讀回的無時區 UTC 與帶時區 timestamp 都序列化含 offset；已儲存與串流報告本地時間相同。
- [x] AC-4：Strava parse、preview、import service 均不在 event-loop thread；慢 worker 期間其他 coroutine 能繼續執行，既有匯入／回滾／隔離測試保持通過。
- [x] AC-5：新增 modules 在 HTML 與 SW 依序完整載入；CRUD、匯出、目標、所有圖表及雙引擎排版維持通過。

## Test traceability

| Acceptance criterion | Test file / command |
| --- | --- |
| AC-1、AC-2、AC-3 | Node regressions + Chromium/WebKit browser safety |
| AC-3、AC-4 | Python report timestamp／Strava worker regression |
| AC-5 | frontend-test、frontend-e2e、frontend-layout、architecture-check、docs-check |
| 全部 | `python3 scripts/task.py verify-all` |

## Verification record

- 2026-10-20：`verify-all` 完整通過，browser checks 未跳過。
- Python 366 項、frontend Node 53 項、28 組排版，以及 Chromium CRUD／雙引擎 session 與 SPEC-012／013 回歸通過；branch coverage 94.15%。
- `eval-agent` 10 項通過；Ruff、mypy、架構、secret scan、依賴安全與文件一致性皆通過。
- 驗證使用 in-memory／暫存 SQLite 與 mock I/O，未更動正式業務資料。
