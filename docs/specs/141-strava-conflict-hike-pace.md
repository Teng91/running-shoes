# SPEC-141：Strava 衝突連結的健行配速上限

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-091](091-strava-conflict-choices.md)、[SPEC-139](139-review-layering-and-hike-pace.md)

## Problem

- SPEC-139 讓健行與步行的配速上限放寬到每公里 120:00，自動連結與補時間都依 Strava 活動的類型檢查。
- 但使用者在「當天已有手動紀錄」的衝突中手動選擇連結時（`strava_import.resolve_conflicts`），衝突資料沒有活動類型，補時間仍用跑步的 60:00 上限：慢速健行連結後不會補上移動時間。

## Goals

- `manual_matches()` 產生的衝突帶上 Strava 活動類型；`resolve_conflicts()` 依該類型的上限決定是否補時間，和自動連結一致。

## Non-goals

- 不改變預覽回應：`manual_conflicts` 只列原本的欄位，活動類型留在伺服器端。
- 不改變里程、日期修正或衝突選擇的規則。

## Proposed design

- `strava_import.manual_matches()` 的衝突加上 `activity_type`（`_row_activity_type(row)`）；`resolve_conflicts()` 的 `is_plausible_duration()` 帶入該值。匯入時衝突由伺服器重新計算，不信任用戶端。

## Security and data isolation

- 不新增資料邊界；衝突仍只列本帳號的手動紀錄。

## Migration, rollout, and rollback

- Schema／資料 migration：無（schema 14）。
- 上線與 smoke test：`release-check`。
- 回滾方式與資料相容性：可直接回滾至 v5.3.6 image。

## Acceptance criteria

- [x] AC-1：Given 一筆每公里約 90:00 的 Strava 健行與當天兩筆手動紀錄，When 使用者在衝突中把它連結到其中一筆，Then 補上移動時間；同樣配速的路跑不補時間。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_strava_manual_match.py::test_a_hike_linked_through_a_conflict_keeps_its_slow_moving_time` |
