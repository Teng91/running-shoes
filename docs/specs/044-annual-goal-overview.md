# SPEC-044：月跑量年度目標總覽

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-017](017-consistent-statistics-and-feature-lifecycles.md)、[SPEC-040](040-highlights-review-and-mobile-navigation.md)

## Problem

月跑量分頁頂端把三件不同的事放在同一列：「目標開始年份」與「每月目標」是設定，「查看月份」是檢視條件，再加上上方已經有一個年份選單。
使用者每次都看到設定欄位；兩個年份欄位並排容易誤會；年度目標只能一次看一個月份，看不出全年哪幾個月達標。

## Goals

- 頁面只保留一個檢視條件：上方的年份。移除「查看月份」選單，改為一張年度目標卡，同時顯示 12 個月對每月目標的達成狀態（達標、未達標、本月進行中、尚未開始）。
- 年度卡片顯示累計／全年目標、達成率、今天應有的進度標記、超前或落後、年底前還差多少與平均每週需要的里程；目前年份另列本月進度。
- 目標設定收進「調整目標」：預設收起，展開後可改每月目標與「從哪一年開始計算」（改為年份選單並說明用途），可取消。
- 數字與既有規則一致：只計逐筆跑步日誌，今天應有的進度與「年度累計跑量與目標」圖表同一條目標線。

## Non-goals

- 不改目標資料模型、`PUT /api/running-goal`、備份格式；不移除 `GET /api/running-goal/progress`（首頁、月報與 release-check 仍使用）。
- 不調整月跑量分頁的其他圖表與年度回顧。

## Proposed design

- `backend/read_models/run_statistics.py`：`monthly_run_distances()` 以一次 group-by 取得指定年份 12 個月的日誌里程，不讀今天之後的日期。
- `backend/goals.py`：`year_goal_overview()` 組合目標月份（今年取本月、過去取 12 月、未來取 1 月）的 `goal_progress`、12 個月狀態、達標月份數、依日數比例的應達里程（`yearly_goal_to_date()`，訓練趨勢的目標線共用）與平均每週需求；未啟用年份不標記達標。
- `backend/routers/goals.py`：新增 `GET /api/running-goal/year?year=`，需登入，只讀自己的資料。
- `frontend/templates/index.html`、`frontend/app-goals.js`：年度目標區塊（標題列顯示目前目標與「調整目標」按鈕、可收合的設定表單、總覽卡）；表單沿用原有草稿／版本流程，有未儲存草稿時自動展開，取消會還原為已儲存的目標，儲存成功後收起。
- `frontend/css/03-dashboard.css`：12 格月份在寬畫面 1 列；手機（≤760px）及側欄仍在但版面較窄（801–940px）時改為 6 欄 2 列。

## Security and data isolation

- 新端點使用 `get_current_user`，所有查詢以 `user_id` 過濾；回應只有里程與目標數字，不含其他帳號或憑證資料。

## Migration, rollout, and rollback

- Schema／資料 migration：無；schema 6 不變。
- 上線與 smoke test：Asset 4.5.0／shell v51；部署後執行匿名 `release-check`。
- 回滾方式與資料相容性：可直接回滾至 v4.4.0 image；新端點為唯讀新增。

## Acceptance criteria

- [x] AC-1：Given 某年份有日誌與手動歷史調整，When 讀取年度目標，Then 12 個月只以本人的逐筆日誌計算，並正確標記過去／本月／未來與是否達標，今天應達里程與訓練趨勢目標線相同；其他帳號與今天之後的跑步不計入。
- [x] AC-2：Given 過去、未來與早於開始年份的年份，When 讀取年度目標，Then 分別回傳整年結算、尚未開始與未啟用（不標記達標）。
- [x] AC-3：Given 月跑量分頁，When 載入，Then 沒有「查看月份」選單，年度卡片顯示 12 個月狀態、年度進度與本月進度；過去、未來與未啟用年份有對應說明。
- [x] AC-4：Given 目標設定，When 未展開，Then 不顯示設定欄位；展開可改每月目標與開始年份，取消還原已儲存值，有未儲存草稿時重繪會自動展開，儲存成功後收起。
- [x] AC-5：Given 手機與桌面寬度、亮暗主題，When 顯示月跑量分頁並展開設定，Then 窄版面月份格為 6 欄、寬版面 12 欄，月份數字不溢出，控制項維持 44px 且沒有版面溢出。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_goals.py::test_year_goal_overview_marks_every_month_against_the_monthly_target`、`unit_tests/test_goals.py::test_year_goal_api_is_user_scoped` |
| AC-2 | `unit_tests/test_goals.py::test_year_goal_overview_handles_past_future_and_untracked_years` |
| AC-3 | `unit_tests/frontend/goals-transport.test.cjs::SPEC-044 the annual goal shows twelve month cells instead of a month picker`、`unit_tests/frontend/goals-transport.test.cjs::SPEC-044 past, future and not-yet-tracked years explain their goal state` |
| AC-4 | `unit_tests/frontend/goals-transport.test.cjs::SPEC-044 the goal editor offers known years and cancel restores the saved goal`、`unit_tests/frontend/draft-resources.test.cjs::SPEC-024 goal drafts survive redraw and save acknowledgements`、`python3 scripts/task.py frontend-e2e` |
| AC-5 | `unit_tests/frontend/goals-transport.test.cjs::SPEC-044 month cells use twelve columns on desktop and two rows of six when narrow`、`python3 scripts/task.py frontend-layout` |
