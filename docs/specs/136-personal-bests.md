# SPEC-136：個人最佳（5K、10K、15K、半馬）

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-060](060-run-duration-and-pace.md)、[SPEC-065](065-race-readiness.md)、[SPEC-096](096-activity-types.md)

## Problem

跑步紀錄有距離與移動時間，但沒有地方看自己最快的 5K、10K、15K 或半馬；設定比賽時，參考成績也要自己翻紀錄、手打距離和時間。

每筆紀錄只存總距離與總時間（SPEC-060），沒有分段或 GPS 軌跡，所以算不出「一場跑步裡最快的一段」。

## Goals

- 「訓練分析」分頁在「比賽準備」上方列出 5K、10K、15K、半馬的個人最佳，每個距離前 3 名。
- 比較長的跑步也算較短距離：以那次的平均配速換算成該距離，所以一場半馬也能是 5K 最佳。
- 個人最佳可以一鍵帶入「設定比賽」的參考成績。

## Non-goals

- 不算一場跑步中最快的分段：資料沒有分段或軌跡。匯入 Strava 的 FIT／GPX 檔會是另一份 spec。
- 不加全馬、1K、1 英里等其他距離；不加 AI 工具。
- 不改資料模型、匯入或備份格式。

## Proposed design

- 新的 `backend/read_models/personal_bests.py` 只讀有時間的路跑（`PACE_RUN`，SPEC-096），不含今天之後的紀錄。比 5K 短 1% 以上的跑步不會讀進來。
- 一次跑步只要不短於該距離的 99%，就算該距離的候選。GPS 常把比賽量短一點，所以留 1% 的寬容。成績是 `duration_seconds × 距離 ÷ 跑步距離`，也就是以那次的平均配速跑完該距離。
- 每個距離取最快 3 筆（`heapq.nsmallest`）。同秒數時，日期較早的排前面。每筆回傳名次、秒數、配速、日期、跑步距離、`from_longer_run`（跑步距離超過該距離 1%）和鞋款名稱（含暱稱）。
- `GET /api/analytics/personal-bests`（`routers/analytics.py`）只轉交 read model。
- 前端 `app-pace-charts.js` 的 `renderPersonalBests()` 在「訓練分析」分頁顯示時讀取並排版，不需要 Chart.js。每個距離一張卡：
  - 最佳時間、配速、日期與那次跑步的距離、鞋款。
  - 第 2、3 名，同樣標出日期與跑步距離。v5.3.1 起每一筆都標距離；v5.3.0 只在取自較長跑步時才標，同一張卡有的有、有的沒有。
  - 「設為比賽參考成績」按鈕。

  快取 `personal-bests` 跟著 `dashboard` 一起失效，所以跑步或鞋款資料重新載入後會重讀。
- `app-race-goal.js` 的 `usePersonalBest()` 處理按鈕（`data-click="use-personal-best"`）：
  - 表單關著就先打開。
  - 填入參考距離與時間，清掉舊參考成績的氣溫。
  - 提示要按「儲存」，此時不送出。
  - 表單開著時只改參考成績，使用者打的其他欄位保留。
- `cross_script_names` 維持 153。新程式只用既有的跨 script 名稱，按鈕的值放在 `data-*` 屬性。

## Security and data isolation

- 查詢以 `Run.user_id` 限制，join 鞋款時也要求 `Shoe.user_id` 相同，另一個帳號的跑步與鞋款名稱不會出現。
- 唯讀，不涉及 secret、備份或外部內容。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：`release-check`。登入後打開「訓練分析」看個人最佳卡片，按「設為比賽參考成績」確認表單帶入。
- 回滾方式與資料相容性：直接回滾 v5.2.7 image。新 API 是唯讀，沒有保存格式變更。

## Acceptance criteria

- [x] AC-1：Given 不同長度、有時間的路跑，When 讀個人最佳，Then 每個距離以平均配速換算、取最快 3 筆。較長的跑步也算，量短 1% 以內仍算，更短的不算；同秒數時日期早的在前。
- [x] AC-2：Given 沒有時間、越野、步行、未來日期或另一個帳號的跑步，When 讀個人最佳，Then 都不算。API 需要登入，回傳 5K、10K、15K、半馬四個距離。
- [x] AC-3：Given 個人最佳，When「訓練分析」分頁顯示，Then 每個距離一張卡：最佳時間、配速、鞋款（跳脫 HTML）與第 2、3 名，每一筆都以同樣格式標出日期與那次跑步的距離。沒有紀錄的距離顯示提示、沒有按鈕。跑步或鞋款重新載入後會重讀。
- [x] AC-4：Given 一張個人最佳卡，When 按「設為比賽參考成績」，Then 比賽表單帶入參考距離與時間並清掉氣溫，其他欄位不變，按「儲存」前不送出。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_personal_bests.py::test_a_longer_run_holds_a_shorter_best_at_its_average_pace` |
| AC-1 | `unit_tests/test_personal_bests.py::test_a_tie_goes_to_the_run_that_set_it_first_and_only_three_are_kept` |
| AC-2 | `unit_tests/test_personal_bests.py::test_only_timed_past_road_runs_of_this_account_count` |
| AC-3 | `unit_tests/frontend/pace-analysis.test.cjs::SPEC-136 personal bests lay out the backend ranking, the runners-up and the source run` |
| AC-3 | `unit_tests/frontend/streams-rendering.test.cjs::panel rendering is lazy, reused, and invalidated by data or theme changes`、`python3 scripts/task.py frontend-layout`（每種寬度排版卡片，按鈕帶入比賽表單） |
| AC-4 | `unit_tests/frontend/pace-analysis.test.cjs::SPEC-136 a personal best fills the race form reference result and saves nothing` |
