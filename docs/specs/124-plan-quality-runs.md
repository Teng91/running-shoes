# SPEC-124：課表每週建議強度次數

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-119](119-race-training-plan.md)、[SPEC-121](121-plan-zone-counts-and-taper.md)、[SPEC-123](123-plan-adapts-to-missed-weeks.md)

## Problem

- 課表只排週跑量與最長一次。強度欄（SPEC-121）只列出實際跑在各區間幾次，沒有說應該跑幾次，跑者不知道一週要不要、要幾次比賽配速或更快的跑步，也看不出自己做得夠不夠。

## Goals

- 每週建議在各強度區間跑幾次，區間與配速範圍沿用強度分布（SPEC-065）。
- 已開始的週把實際次數和建議並列，未開始的週顯示建議。
- 本週說明列出建議次數與配速範圍。

## Non-goals

- 不排每天的課表內容（哪一天、幾組間歇、暖身緩和）。
- 不改變強度區間的定義，也不把強度算進「達成」狀態；狀態仍只看跑量與最長一次。
- 每次跑步只有總距離與總時間，間歇課的平均配速可能落在較慢的區間；本次不處理分段資料。

## Proposed design

- `read_models/race_plan` 每週新增 `quality_runs`（四個區間的建議次數，`easy` 為 0，代表其餘輕鬆跑）：
  - 比賽週：全部 0，比賽本身就是強度。
  - 其他週：比賽配速 1 次；累積與高峰週、且建議週跑量至少 25 km 時，再加 1 次 `Profile.second_quality`：5K、10K 為更快（`fast`），半馬、全馬為穩定（`steady`）。
- 建議次數依該週（可能已依 SPEC-123 調降的）建議跑量計算。
- 前端「強度（實際／建議）」欄：已開始與未開始的週都統一顯示「實際/建議」（如 `輕鬆 1/0`、`穩定 1/1`、`比賽配速 0/1`），達到建議的區間加粗；都沒有次數與建議時顯示「—」（v5.3.4 起統一格式；v5.0.5～v5.3.3 在沒有建議的區間與未開始的週省略斜線）。本週說明加上「強度建議：比賽配速 1 次（5:31–5:56），其餘輕鬆跑」。AI 工具補上欄位說明。

## Security and data isolation

- 建議是比賽目標與建議跑量的純計算；實際次數沿用既有的 user-scoped 查詢。

## Migration, rollout, and rollback

- Schema／資料 migration：無；`plan.weeks` 新增 `quality_runs`。
- 上線與 smoke test：課表強度欄顯示「實際／建議」，本週說明列出建議配速。
- 回滾方式與資料相容性：直接回滾 v5.0.4 image；舊前端忽略新欄位。

## Acceptance criteria

- [x] AC-1：Given 一份課表，When 取得課表，Then 比賽週沒有建議，其他週有 1 次比賽配速，累積期 25 km 以上的週再加 1 次更快（5K、10K）或穩定（半馬、全馬）。
- [x] AC-2：Given 已開始與未開始的週，When 顯示課表，Then 所有有紀錄或有建議的區間都統一並列實際／建議（含建議為 0 的區間與未開始的週）並把達成的區間加粗，本週說明列出建議次數與配速範圍。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_race_plan.py::test_every_week_suggests_runs_per_intensity_zone` |
| AC-2 | `unit_tests/frontend/pace-analysis.test.cjs::SPEC-124 the plan compares actual runs per zone with the suggested quality runs` |
