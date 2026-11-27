# SPEC-138：移除跑鞋「月跑量」欄位

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-050](050-recent-shoe-share.md)、[SPEC-069](069-idle-shoe-forecast.md)

## Problem

- 跑鞋的新增／編輯表單還有一個人工填寫的「月跑量 (km)」欄位（`monthly_km`，預設 60），移至退役時會清成 0、移回現役時又用其他現役鞋的平均補回去。
- 早在 SPEC-050 跑鞋表格與「近 90 天月均里程佔比」圓餅圖就已改用近 90 天實際里程；SPEC-069 也把穿過但近 90 天沒穿的鞋改為不預估。這個欄位只剩三個地方用到：表單輸入、從來沒跑過的新鞋退役預估、AI 工具 `list_my_shoes` 與 CSV／XLSX 匯出。
- 對新鞋來說，依「預設 60 km／月」推算一個假的退役日期沒有依據，反而容易誤導。

## Goals

- 新增／編輯跑鞋表單移除「月跑量」欄位，移至退役或現役時也不再傳送或自動補平均值。
- 從來沒跑過的新鞋不再依計畫月跑量預估退役日期：`forecast_source` 回傳 `"no_runs"`、日期為 `null`、金額速率為 `0.0`，單鞋分析顯示「—」與「還沒有跑步紀錄，不預估」；有近 90 天跑步紀錄後改依實際月均預估。
- AI 教練的 `list_my_shoes`、`agent.py` 系統提示詞與 `tool_definitions.py` 移除 `assigned_monthly_km` 欄位與說明。
- 跑鞋 CSV／XLSX 匯出（`exporting.generate_shoe_rows`）移除「月跑量(km)」欄。

## Non-goals

- 不移除資料庫 `shoes.monthly_km` 欄位，也不變動 API `ShoeCreate`／`ShoeUpdate`／`ShoeOut` 或 v1–v6 帳號備份契約，維持既有資料、舊版用戶端與備份完全相容。
- 不變動整體跑量目標（`running_goals.monthly_km`）與月份跑量統計（`monthly_mileages`）。

## Proposed design

- **前端表單與工作區**（`templates/shoe-modal.html`、`app-shoes.js`、`app-workspace.js`）：
  - 移除 `#f-monthly` 輸入列與 `ShoeModal.formIds.monthly`／`monthlyRow`／`_payload().monthly_km`。
  - `ShoeModal.move()` 只送 `{ is_retired, expected_version }`，不再把退役鞋的 `monthly_km` 清為 0 或在移回現役時補算平均；`resumeWorkspaceEditor()` 的行內欄位對應表移除 `monthly_km`。
- **退役預估**（`backend/forecasting.py`、`backend/schemas.py`）：
  - `ShoeForecast.forecast_source` 與 `ShoeOut.forecast_source` 的 Literal 由 `"planned_monthly_km"` 改為 `"no_runs"`。
  - `retirement_forecast()` 在未退役且 `actual_rate == 0` 時直接回傳 `forecast_retirement_date: None`、`forecast_monthly_km: 0.0`，並依 `has_runs` 區分 `"idle_90_days"` 與 `"no_runs"`。
- **前端顯示**（`app-dashboard.js`、`app-run-insights.js`）：
  - `forecastSourceText('no_runs')` 回傳「還沒有跑步紀錄，不預估」；`renderShoeAnalytics()` 將 `'no_runs'` 與 `'idle_90_days'` 同樣視為無可用速率，主數值顯示「—」、副標顯示來源提示。
- **AI 工具與匯出**（`read_models/shoes.py`、`tools/tool_definitions.py`、`agent.py`、`exporting.py`）：
  - `_shoe_data` 與 `list_my_shoes` 的 `field_definitions` 移除 `assigned_monthly_km`；更新 `tool_definitions.py` 與 `agent.py` 提示詞。
  - `generate_shoe_rows` 移除 `"月跑量(km)"` 欄。

## Security and data isolation

- 不新增或改變授權、使用者範圍過濾或機密資料邊界；`forecasts_for_shoes`、AI 工具與匯出皆沿用原本的 `user_id` 過濾。

## Migration, rollout, and rollback

- Schema／資料 migration：無（維持 schema 14 與既有 `shoes.monthly_km` 欄位）。
- 上線與 smoke test：`release-check`；確認新增／編輯跑鞋視窗沒有月跑量欄位，新鞋的單鞋分析顯示「還沒有跑步紀錄，不預估」，匯出 CSV／XLSX 不含「月跑量(km)」。
- 回滾方式與資料相容性：可直接回滾至 v5.3.2 image，資料庫與 v6 備份格式皆無變更；回滾後新鞋仍保留資料庫預設 `monthly_km = 60`。

## Acceptance criteria

- [x] AC-1：Given 未退役且從無跑步紀錄或近 90 天實測月均為 0 的跑鞋，When 計算退役預估，Then `forecast_source` 為 `"no_runs"`（或有舊紀錄時為 `"idle_90_days"`）、`forecast_retirement_date` 為 `None`、`forecast_monthly_km` 為 `0.0`。
- [x] AC-2：Given 跑鞋表單與狀態切換，When 新增／編輯或移至退役／現役，Then 畫面沒有 `#f-monthly` 欄位，送出與移動 payload 皆不帶 `monthly_km`。
- [x] AC-3：Given `forecast_source === 'no_runs'`，When 顯示清單提示與單鞋分析，Then 顯示「—」與「還沒有跑步紀錄，不預估」。
- [x] AC-4：Given AI `list_my_shoes` 與跑鞋匯出，When 取得鞋款清單或 CSV／XLSX 匯出列，Then 不包含 `assigned_monthly_km` 與「月跑量(km)」。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_forecasting.py::test_retirement_forecast_policy`、`unit_tests/test_forecasting.py::test_a_pair_idle_for_90_days_gets_no_forecast_but_a_new_pair_uses_the_plan` |
| AC-2 | `unit_tests/frontend/corrections.test.cjs::SPEC-138 shoe form drops monthly_km and never-run shoes show no forecast`、`unit_tests/frontend/draft-resources.test.cjs::SPEC-024 shoe transitions preserve only new edits and retain the server state` |
| AC-3 | `unit_tests/frontend/corrections.test.cjs::SPEC-138 shoe form drops monthly_km and never-run shoes show no forecast` |
| AC-4 | `unit_tests/test_tools.py::test_list_my_shoes_includes_all`、`unit_tests/test_api_extra.py::test_export_csv_all_contains_calculated_fields`、`unit_tests/test_api_extra.py::test_export_xlsx_active_has_styled_sheet` |
