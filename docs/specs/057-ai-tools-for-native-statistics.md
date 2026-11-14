# SPEC-057：AI 助手使用現有統計

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-044](044-annual-goal-overview.md)、[SPEC-040](040-highlights-review-and-mobile-navigation.md)、[SPEC-056](056-weekly-goal-long-run-and-weekday-analysis.md)

## Problem

- AI 助手只有 7 個資料庫工具（跑鞋清單、總覽、月跑量、壽命、比較、類別、使用分析），看不到目標進度、訓練趨勢、年度回顧與支出。
- 問「今年目標達成多少？」「最近每週跑量有沒有暴增？」「買鞋花了多少？」時，模型只能從月跑量自己推算，容易和首頁、月跑量分頁的數字不一致，也違反「計算留在後端」的規則。
- 這些數字後端都已經算好（`goals.year_goal_overview`、`trends.training_trends`、`highlights.year_review`、`spending.spending_summary`），只是沒有接成工具。

## Goals

- 新增 4 個工具：`running_goal_progress`、`training_trends`、`year_review`、`spending_summary`，直接重用現有 read model，不重算。
- 前三個接受選填 `year`（1900–2100），省略或不合法時用今年。
- 意圖偵測對目標、趨勢、回顧與支出的私人問題預先取得對應工具；system prompt 說明這些欄位已由後端算好。
- 控制輸出大小：不把逐日陣列與 365 天累計曲線送給模型。

## Non-goals

- 不新增 HTTP 端點；工具與畫面共用同一份 read model。
- 不讓模型修改目標或任何資料，工具全部唯讀。

## Proposed design

- **`tools/tool_definitions.py`**：4 個 schema，`year` 為 integer 並有上下限，`additionalProperties: false`。
- **`tools/db_tools.py`**（薄 adapter）：
  - `running_goal_progress`：`goals.year_goal_overview(year, as_of=today)`，附 `field_definitions`。
  - `training_trends`：保留 streaks、16 週、週目標、星期分布（加上「週一」等名稱）與累計摘要；移除 `daily`、`actual_km`、`goal_km` 等逐日陣列，改回傳 `run_days`。
  - `year_review`：附上 `longest_run`／`top_shoe` 的鞋款名稱（已刪除標示「（已刪除）」），說明 `previous_year_km` 是同期。
  - `spending_summary`：總額與折數，月份明細只保留最近 12 個有買鞋的月份。
- **`agent_tools.execute_tool`**：只接受非 bool 的 int `year` 且在範圍內，其餘一律傳 `None`。
- **`agent_planner`**：
  - 新增目標、趨勢、回顧、支出的關鍵字組。
  - 個人標記加入「今年／本週／這週」。
  - 這些詞也會讓模型取得工具。
- **System prompt**：工具清單加上目標、趨勢、回顧與支出，說明達標、暴增、週目標、同期比較與折數直接引用。

## Security and data isolation

- 每個 adapter 只把 `user_id` 傳給既有的 user-scoped read model；鞋名查詢也以 `Shoe.user_id` 限定。
- 具名測試建立另一個帳號的鞋與跑步，確認不出現在任何工具輸出。
- `year` 在進入 read model 前驗證，不會把任意值帶進 SQL。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：與 SPEC-055 同版；`eval-agent` 涵蓋新意圖。README 的 Agent 工具數由 8 改為 12，`docs-check` 驗證。
- 回滾方式與資料相容性：回滾 image 即移除新工具；對話歷史不保存工具結果。

## Acceptance criteria

- [x] AC-1：Given 兩個帳號的鞋與跑步，When 呼叫 4 個新工具，Then 數字與 read model 相同（年度累計、16 週、星期分布、同期比較、平均折數、最近月份），鞋名正確，另一個帳號的資料不出現，逐日陣列被移除。
- [x] AC-2：Given 字串、布林、超出範圍或缺少的 `year`，When 執行工具，Then 一律改用今年；合法年份照用。
- [x] AC-3：Given「今年目標達成多少？」「我最近每週跑量有沒有暴增？」「幫我回顧我今年跑得怎麼樣」「我買鞋總共花了多少錢？」，When 建立查詢計畫，Then 分別預先取得對應工具，既有意圖不變。
- [x] AC-4：Given 工具 registry，When 執行 docs-check，Then README 記載的 Agent 工具數等於實際的 12 個。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_tools.py::test_native_statistics_tools_reuse_read_models_and_stay_user_scoped` |
| AC-2 | `unit_tests/test_tools.py::test_native_statistics_tools_validate_the_year_argument` |
| AC-3 | `unit_tests/test_agent_evals.py::test_agent_query_plan_contract`、`python3 scripts/task.py eval-agent` |
| AC-4 | `unit_tests/test_docs_harness.py::test_docs_harness_reads_agent_tool_count`、`python3 scripts/task.py docs-check` |
