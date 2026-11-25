# SPEC-126：帳號備份包含目標賽事（備份 v6）

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-065](065-race-readiness.md)、[SPEC-096](096-activity-types.md)、[SPEC-120](120-plan-weeks-and-indexeddb-retry.md)

## Problem

- README 說 JSON 帳號備份是「完整」的，但 `backup_contract.py` 只有鞋款、跑步、月跑量、跑量目標、月報、Strava 匯入摘要與異動歷史。目標賽事（SPEC-065）與它的課表週數（SPEC-120）不在裡面。
- 把雲端帳號搬到本機版，或從備份重建帳號後，目標賽事會消失，比賽準備與訓練課表都要重新設定。

## Goals

- 備份格式升為 v6，帶入 `race_goal`（比賽名稱、日期、距離、目標時間、參考成績與氣溫、課表週數）。
- 還原時和跑量目標相同：「只新增」只在接收帳號沒有目標賽事時加入；「新增並更新」覆寫為檔案的內容；預覽顯示會新增、更新或內容相同。
- v1～v5 備份照常匯入，指紋不變。

## Non-goals

- 不為目標賽事加稽核 trigger 或刪除復原；目標賽事仍不出現在異動歷史。
- 不改變 `GET`／`PUT /api/race-goal` 與預覽 API 的路徑。

## Proposed design

- `backup_contract.BackupRaceGoal` 繼承 `schemas.RaceGoalUpdate`，沿用同樣的日期、配速與 `plan_weeks`（4～24 或 null）驗證，`expected_version` 只能是 null 且不輸出；`AccountBackup.version` 接受 6，`race_goal` 只能出現在 v6。v6 以前的指紋去掉 `race_goal`，維持原值。
- `services/exports.py` 輸出 v6，`race_goal` 只含 `RACE_GOAL_FIELDS`，不含 id、`user_id` 與版本。
- `account_import_plan` 讀接收帳號自己的目標賽事；`account_import_changes` 在更新模式算出欄位差異；`account_import._import_race_goal` 沒有時新增（版本 1），更新模式套用差異並加版本。預覽 summary 新增 `new_race_goal`、`updated_race_goal`、`unchanged_race_goal`。
- 前端預覽以 `restoreGoalText()` 寫出「及跑量目標與目標賽事」。

## Security and data isolation

- 匯出只讀目前使用者的 `race_goals` 列；匯入只讀寫接收帳號（`user_id` 由登入身分決定，備份裡出現 `user_id` 仍會被 `_check_json` 拒絕）。
- 目標賽事不含憑證；備份大小上限不變。

## Migration, rollout, and rollback

- Schema／資料 migration：無；schema 14 不變。
- 上線與 smoke test：下載帳號 JSON，`version` 為 6 且含 `race_goal`；在另一個帳號預覽顯示會新增目標賽事。
- 回滾方式與資料相容性：可直接回滾 v5.0.6 image，但舊版不接受 v6 檔案；回滾後請重新下載備份（v5），或把 v6 檔案的 `version` 改成 5 並刪除 `race_goal`。

## Acceptance criteria

- [x] AC-1：Given 有目標賽事的帳號，When 下載 JSON 備份，Then 檔案是 v6 且 `race_goal` 含課表週數，不含版本或識別碼。
- [x] AC-2：Given v6 備份，When 以「只新增」匯入沒有目標賽事的帳號，Then 新增目標賽事；接收帳號已有時保留它；When 以「新增並更新」匯入，Then 覆寫為檔案內容，再次匯入時預覽顯示內容相同。
- [x] AC-3：Given v5 以前的備份，When 匯入，Then 照常接受且指紋不變；v5 備份帶 `race_goal`、或目標賽事不符 API 驗證時拒絕。
- [x] AC-4：Given 預覽結果，When 顯示，Then 列出會新增、更新或內容相同的目標賽事。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_account_restore.py::test_backup_v6_round_trips_the_race_goal` |
| AC-2 | `unit_tests/test_account_restore.py::test_backup_v6_round_trips_the_race_goal` |
| AC-3 | `unit_tests/test_account_restore.py::test_only_v6_archives_carry_a_valid_race_goal`、`unit_tests/test_account_restore.py::test_legacy_archive_fingerprint_excludes_v3_defaults` |
| AC-4 | `unit_tests/frontend/workspace.test.cjs::SPEC-029 import modes own their previews and confirmation` |
