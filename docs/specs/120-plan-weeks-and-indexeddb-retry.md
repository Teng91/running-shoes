# SPEC-120：可自訂課表週數與 IndexedDB 內部錯誤重試

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-119](119-race-training-plan.md)、[SPEC-114](114-last-long-functions.md)

## Problem

- SPEC-119 的課表週數依距離固定（半馬 12 週、全馬 16 週）。比賽已經很近時，課表的開始日早就過了，前幾週全是「未達」，使用者只能看著一份來不及照著跑的課表。
- CI 的 WebKit E2E 偶發失敗：恢復本機資料時 IndexedDB 回報「An internal error was encountered in the Indexed Database server」（`UnknownError`），畫面顯示「恢復本機資料失敗」。Safari 使用者也可能遇到同一個錯誤。

## Goals

- 使用者在比賽設定選擇課表週數（含比賽週，4～24 週）；留白時以「距離比賽剩下的週數，最多到距離預設」儲存，課表從本週開始。
- 週數存進比賽目標，課表開始日因此固定，已過的週次不會移動。
- 本機資料庫開啟或交易遇到 `UnknownError` 時，換一條新連線重試一次。

## Non-goals

- 不自動改寫既有的比賽目標；舊目標沿用距離預設，畫面提示到「調整比賽」設定。
- 不重試其他 IndexedDB 錯誤，也不重試超過一次。

## Proposed design

- Schema 14：`race_goals.plan_weeks INTEGER NULL`。`PUT /api/race-goal` 接受 `plan_weeks`（嚴格整數 4～24 或 null），回應與 `GET` 都帶上它。
- `read_models/race_plan.build_plan` 以 `plan_weeks`（null 時用距離預設）決定課表長度；回應新增 `weeks_chosen`、`default_weeks` 與 `weeks_until_race`。週數少於預設時，累積週變少、減量與比賽週不變。
- 前端比賽表單新增「課表週數」，提示距離比賽剩幾週與留白會排幾週；留白時送出建議值。課表說明最前面加上本週的建議跑量、最長一次、已跑與還差多少；舊目標加上改週數的提示。
- `app-local-store.js`：開啟失敗或交易以 `UnknownError` 失敗時，關閉壞掉的連線、開新連線重試一次。中止的交易沒有寫入，重試不會重複套用。

## Security and data isolation

- `plan_weeks` 只隨使用者自己的比賽目標讀寫，沿用既有的版本檢查與使用者範圍。

## Migration, rollout, and rollback

- Schema／資料 migration：schema 14 新增可為 null 的欄位，既有資料不變。部署前 CI 會先備份正式資料庫。
- 上線與 smoke test：「調整比賽」看到課表週數與提示，留白儲存後課表從本週開始；本週摘要顯示在課表說明最前面。
- 回滾方式與資料相容性：停止寫入並驗證 schema-14 備份後執行 `scripts/rollback_schema_fourteen.sql`，再部署 v5.0.0 image；欄位保留但 schema-13 程式不讀，再次升級時沿用。

## Acceptance criteria

- [x] AC-1：Given 比賽目標存了課表週數，When 取得比賽準備，Then 課表長度等於該週數並從比賽週往前推算；沒有週數時沿用距離預設並標示。
- [x] AC-2：Given 比賽表單，When 課表週數留白或填入，Then 留白送出「剩餘週數，最多到預設」、填入則照填，4～24 以外或非整數被擋下。
- [x] AC-3：Given schema 13 資料庫，When 升級到 14 再執行回滾腳本，Then 比賽目標保留，再次升級沿用原本的週數。
- [x] AC-4：Given 課表有本週，When 顯示說明，Then 最前面列出本週的建議跑量、最長一次、已跑與還差多少。
- [x] AC-5：Given IndexedDB 開啟或交易回報 `UnknownError`，When 本機資料庫讀寫，Then 換新連線重試一次，寫入只套用一次；再次失敗時回報錯誤。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_race_plan.py::test_the_runner_chooses_how_many_weeks_the_plan_lasts`、`unit_tests/test_race_plan.py::test_plan_weeks_are_saved_with_the_goal` |
| AC-2 | `unit_tests/frontend/pace-analysis.test.cjs::SPEC-065 the race form validates its fields and saves the parsed goal`、`unit_tests/test_race_readiness.py::test_race_goal_is_saved_versioned_validated_and_user_scoped` |
| AC-3 | `unit_tests/test_migrations.py::test_schema_fourteen_adds_plan_weeks_and_rolls_back_keeping_goals` |
| AC-4 | `unit_tests/frontend/pace-analysis.test.cjs::SPEC-119 the weekly plan lays out backend targets, actual distance and status` |
| AC-5 | `unit_tests/frontend/workspace.test.cjs::SPEC-120 the local workspace store retries WebKit internal IndexedDB errors once` |
