# SPEC-125：留白的課表週數由後端決定，並補齊過時的文件

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-119](119-race-training-plan.md)、[SPEC-120](120-plan-weeks-and-indexeddb-retry.md)

## Problem

- 課表週數留白時，網頁會存「距離比賽剩下的週數，最多到距離預設」（`app-race-goal.js` 的 `suggestedPlanWeeks`），但後端收到 `plan_weeks: null` 時直接存 null，課表改用距離預設週數。直接呼叫 `PUT /api/race-goal` 的用戶端在比賽只剩 6 週時建立半馬目標，課表會從 12 週前開始，起點跑量取的是 4 個月前的資料，和網頁建立的結果不同。
- README 的開發歷程停在 v4.26.1，沒有運動類型、解耦與 v5.0 訓練課表；資料流程裡的課表說明沒有 SPEC-122～124 的行為。
- 備份「新增並更新」模式支援 v2 以後的備份（目前到 v5），但 README 寫「v2～v4」，還原視窗與使用指南寫「v2/v3」。

## Goals

- `plan_weeks` 留白時，後端存入和網頁相同的建議週數，任何用戶端結果一致，存檔後課表起點固定。
- README、還原視窗與使用指南描述目前的行為。

## Non-goals

- 不改寫 SPEC-120 以前已存成 null 的目標；它們仍用距離預設週數，起點本來就固定。
- 不改變課表的排法與網頁的建議規則。

## Proposed design

- `read_models/race_plan.suggested_plan_weeks(distance_km, race_day, today)`：比賽週與本週相差的週數加 1，最多是距離預設週數，至少 4 週，與 `suggestedPlanWeeks` 相同。
- `services/race_goals.save_race_goal` 多收 `today`；`plan_weeks` 為 null 時存入建議週數。router 以 `clock.local_today()` 傳入，service 不讀時鐘。
- README 開發歷程補上 v4.27～v5.0，資料流程補上 SPEC-122～124；還原模式文字改為「v2 以後」。

## Security and data isolation

- 只寫目前使用者自己的 `race_goals` 列，沿用既有 user-scoped upsert 與樂觀鎖；沒有新的查詢。

## Migration, rollout, and rollback

- Schema／資料 migration：無；既有資料不變。
- 上線與 smoke test：以 API 建立不帶 `plan_weeks` 的目標，回應的 `plan_weeks` 等於網頁的建議週數。
- 回滾方式與資料相容性：直接回滾 v5.0.5 image；新存的 `plan_weeks` 是一般整數，舊版照常讀取。

## Acceptance criteria

- [x] AC-1：Given 比賽距離、比賽日與今天，When 計算建議週數，Then 結果與網頁規則相同（剩下週數、最多距離預設、至少 4 週）。
- [x] AC-2：Given 不帶 `plan_weeks` 的 `PUT /api/race-goal`，When 存檔，Then 回應與資料庫存入建議週數，一週後課表的週數與起點不變。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_race_plan.py::test_suggested_plan_weeks_follow_the_race_goal_form_rule` |
| AC-2 | `unit_tests/test_race_plan.py::test_the_api_stores_suggested_plan_weeks_so_the_plan_start_stays_put` |
