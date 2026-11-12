# SPEC-050：近 90 天月均里程佔比

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-011](011-shoe-purchase-details-in-spending.md)、[SPEC-038](038-training-trends-and-shoe-rotation.md)、[SPEC-040](040-highlights-review-and-mobile-navigation.md)

## Problem

跑鞋頁的「月跑量佔比」圓餅圖和現役表格的「月跑量」欄，都顯示使用者手動填的計畫月跑量（例如 40／10／30／30／10 km）。這個數字建立鞋款時填一次，之後不會跟著實際穿著改變，所以圓餅圖看不出最近真正常穿哪雙鞋。

每雙鞋的實際用量其實已經算好了：單鞋分析的「實際月均」和退役預估，都用後端 `forecasting.py` 依近 90 天跑步紀錄算出的月均里程。但跑鞋清單 API 沒有回傳這個值，圖表拿不到。

## Goals

- 圓餅圖改為各現役鞋的近 90 天實際月均里程（與單鞋分析的「實際月均」相同），標題改為「近 90 天月均里程佔比」。
- 圓餅中間顯示「近 90 天月均」與各鞋月均的合計。
- 現役表格移除「月跑量」欄。
- 跑鞋清單與跑鞋 operation 回應帶 `actual_monthly_km_90_days`，由後端計算，前端只負責呈現。

## Non-goals

- 不移除計畫月跑量欄位：編輯表單保留它，近 90 天沒有跑步紀錄的鞋，退役預估仍以它回退。
- 不改退役預估規則、API path 或資料庫 schema。
- 不改退役表格；退役表格本來就沒有月跑量欄。

## Proposed design

- `backend/forecasting.py`：新增 `SHOE_RESPONSE_FIELDS` 與 `shoe_response_fields()`，列出要放進跑鞋回應的預估欄位（`forecast_*` 加上 `actual_monthly_km_90_days`）。`routers/shoes.py` 的清單和 `services/operations.py` 的 operation 回應都改用這個 helper，不再各自以 `forecast_` 前綴篩選。
- `backend/schemas.py`：`ShoeOut` 新增唯讀欄位 `actual_monthly_km_90_days: float = 0`。
- `frontend/app-shoe-charts.js`：圓餅圖資料改為 `actual_monthly_km_90_days`（缺值視為 0，例如舊的離線快取）。中間標籤改為「近 90 天月均」，合計與扇形標籤一樣，整數不帶小數、其他取一位小數。tooltip 顯示「近 90 天月均 N km」。
- `frontend/templates/index.html`、`frontend/app-dashboard.js`：更新標題；移除現役表格的「月跑量」表頭與可雙擊編輯的儲存格。

## Security and data isolation

- `forecasts_for_shoes()` 原本就以 `user_id` 限制跑步查詢，並排除他人或已刪除的鞋；新欄位沿用同一份結果，不增加查詢。
- 不涉及 secret、備份格式或外部內容。

## Migration, rollout, and rollback

- Schema／資料 migration：無；新欄位是由既有資料算出的回應欄位。
- 上線與 smoke test：
  - Asset 4.9.0／shell v59。
  - 部署後，跑鞋頁圓餅圖每雙鞋的數字應與該鞋「分析」裡的「實際月均」相同，中間顯示它們的合計。
- 回滾方式與資料相容性：部署 v4.8.0 image 即恢復舊圖表與欄位。v4.8.0 前端會忽略多出來的回應欄位，資料不受影響。

## Acceptance criteria

- [x] AC-1：Given 現役鞋有近 90 天跑步紀錄，When 跑鞋清單或跑鞋 operation 回應，Then 每雙鞋帶有與單鞋分析相同的 `actual_monthly_km_90_days`；沒有近期紀錄的鞋為 0。
- [x] AC-2：Given 跑鞋頁，When 繪製「近 90 天月均里程佔比」，Then 每雙現役鞋以近 90 天實際月均為扇形大小，不使用計畫月跑量；中間顯示「近 90 天月均」與合計；沒有近期紀錄的鞋沒有扇形。
- [x] AC-3：Given 現役表格，When 顯示，Then 不再有「月跑量」欄與它的行內編輯，其餘欄位與數值欄對齊不變。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_forecasting.py::test_batch_forecast_is_scoped_bounded_and_matches_analysis` |
| AC-2 | `unit_tests/frontend/presentation-shell.test.cjs::SPEC-050 the share doughnut shows each active shoe’s 90-day monthly average and their total`、`python3 scripts/task.py frontend-layout` |
| AC-3 | `unit_tests/frontend/streams-rendering.test.cjs::shoe purchase columns live only in spending details, with aligned table rows`、`unit_tests/frontend/streams-rendering.test.cjs::table numeric headers and shared component geometry have explicit presentation contracts`、`python3 scripts/task.py frontend-e2e` |
