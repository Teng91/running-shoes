# SPEC-090：模組解耦：唯讀統計移入 read models、router 不互相依賴、拆分前端圖表檔

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-053](053-documentation-inventory-and-hygiene.md)、[SPEC-065](065-race-readiness.md)

## Problem

公開 repo 的檢查找到幾個模組邊界問題，都不影響功能，但讓修改的影響範圍不清楚：

- `routers/admin.py` 從 `routers/auth.py` import `notify_password_changed`，兩個 route module 互相依賴；架構檢查沒有擋。
- `backend/analytics.py`、`goals.py`、`reports.py` 是唯讀統計，卻放在 `backend/` 根目錄，不受 read models「不可依賴 HTTP、routers、tools」的檢查保護；月報另有一條只為它寫的規則。
- `frontend/app-monthly-charts.js` 有 773 行，月份圖表與訓練趨勢（熱力圖、每週、長距離、星期、累計）混在一起；`app-pace-charts.js` 同時負責目標賽事表單與準備度圖表。

## Goals

- `notify_password_changed` 移到不定義 router 的共用 helper `routers/password_notices.py`；架構檢查禁止 route module 互相 import。
- 三個唯讀模組移入 `read_models/`：`insights.py`（首頁洞察與單鞋分析）、`goal_progress.py`（目標進度）、`report_snapshot.py`（月報統計快照與提示詞），由既有的 read models 規則涵蓋。
- 訓練趨勢移到 `app-trend-charts.js`，目標賽事表單移到 `app-race-goal.js`；所有函式名稱、DOM 與行為不變。

## Non-goals

- 不改任何 API、計算結果或畫面。
- `llm.py` 的模型清單快取與設定維持 process-wide。免費模型清單本來就是整個 process 共用的外部狀態，API key 也是環境層級的 secret；改成由 `create_app` 注入要更動 Agent、月報與大量 mock，換來的隔離有限，風險不成比例。

## Proposed design

- `backend/routers/password_notices.py`：只有 `notify_password_changed`（和 `errors.py` 一樣不定義 router），`auth.py` 與 `admin.py` 都從這裡 import。
- `scripts/check_architecture.router_cross_imports()`：找出定義 `router = APIRouter(` 的 module，任何 router 檔案 import 其中之一即失敗。
- `git mv` 三個檔案；呼叫端改為 `from backend.read_models import insights／goal_progress／report_snapshot`。原本專門檢查 `backend/reports.py` 的規則，改由 read models 的共同規則涵蓋。
- `frontend/assets.json` 在原檔之後載入新檔（classic script 共用全域，函式在呼叫時才解析）。目標賽事的共用狀態與 `race-prep` reset 仍在 `app-pace-charts.js`。

## Security and data isolation

- 純搬移，所有查詢與 `user_id` 條件不變。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：部署前自動快照；部署後 `release-check`（資產數量隨新檔增加）。
- 回滾方式與資料相容性：可直接回滾至 v4.25.1 image。

## Acceptance criteria

- [x] AC-1：Given `backend/routers/`，Then 沒有 route module import 另一個 route module；共用 helper 可以被 import，而 route module 互相 import 會被架構檢查找出。
- [x] AC-2：Given 移入 `read_models/` 的三個模組，Then read models 規則確認它們不依賴 HTTP framework、routers 或 tools，月報快照不依賴 tool 序列化。
- [x] AC-3：Given 拆分後的前端，Then 目標賽事表單與準備度圖表的既有行為測試照常通過（載入兩個檔案），所有前端回歸測試不變。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_architecture_boundaries.py::test_route_modules_never_import_each_other` |
| AC-2 | `unit_tests/test_architecture_boundaries.py::test_reports_depend_on_read_models_not_tool_serialization`、`unit_tests/test_architecture_boundaries.py::test_domain_service_graph_has_no_http_or_ai_adapter_dependencies` |
| AC-3 | `unit_tests/frontend/pace-analysis.test.cjs::SPEC-065 the race form validates its fields and saves the parsed goal`、`python3 scripts/task.py frontend-test` |
