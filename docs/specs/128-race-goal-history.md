# SPEC-128：目標賽事的異動歷史與誤刪復原

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-065](065-race-readiness.md)、[SPEC-126](126-backup-race-goal.md)

## Problem

- 鞋款、跑步、月跑量與跑量目標都有同交易的稽核紀錄，刪除的跑步、鞋款與月份可以在「異動歷史與誤刪復原」找回。目標賽事（SPEC-065）沒有稽核 trigger：修改不會出現在歷史，誤刪後只能從備份還原，或重新填一次比賽、目標時間、參考成績與課表週數。

## Goals

- 新增、修改與刪除目標賽事都出現在異動歷史，內容是不含 `user_id` 的前後快照。
- 刪除的目標賽事可以復原，含課表週數；已經設定新的目標賽事時不覆蓋它。
- 備份格式維持 v6：目標賽事的歷史不放進備份，舊版仍能匯入新下載的備份。

## Non-goals

- 不提供「修改」的回溯；和跑量目標一樣，只有刪除可以復原。
- 不把目標賽事的歷史放進 JSON 備份（需要新的備份版本，留待之後）。

## Proposed design

- `audit_schema.AUDITED` 加入 `race_goals`；trigger 每次啟動依模型欄位重建，事件的 `reason` 沿用 `write_transaction` 的 `race_goal.update`／`race_goal.delete`。
- `history.can_restore` 允許 `race_goals` 的刪除事件；`_restore_race_goal` 在帳號沒有目標賽事時以快照的 `RACE_GOAL_FIELDS` 重建，版本為快照版本加 1；已有目標賽事時回 409「已經有新的目標賽事」。
- `services/exports.py` 的歷史只匯出 `ARCHIVED_HISTORY_ENTITIES`（鞋款、跑步、月跑量、跑量目標）。
- 前端 `app-history.js` 顯示「目標賽事」，復原後讓 `race-readiness` 與 `pace-analysis` 失效再重新讀取。

## Security and data isolation

- trigger 以 `NEW`／`OLD.user_id` 寫入事件，快照不含 `user_id`；歷史查詢與復原都以 `user_id` 篩選，其他帳號的事件回 404。
- 目標賽事不含憑證或密碼。

## Migration, rollout, and rollback

- Schema／資料 migration：無；啟動時建立三個新的 trigger。
- 上線與 smoke test：修改目標賽事後，異動歷史出現「目標賽事 … 更新」。
- 回滾方式與資料相容性：回滾 v5.1.1 image 後，舊版不會刪除新 trigger，而舊版備份不認得 `race_goals` 歷史。回滾後先備份，再執行 release notes 列出的 `DROP TRIGGER` 與 `DELETE FROM audit_events WHERE entity = 'race_goals'`。

## Acceptance criteria

- [x] AC-1：Given 新增、修改與刪除目標賽事，When 讀取異動歷史，Then 依序有三筆 `race_goals` 事件與前後快照，只有刪除可以復原。
- [x] AC-2：Given 刪除事件，When 復原，Then 目標賽事回到刪除前的內容、版本加 1，同一事件不能再復原。
- [x] AC-3：Given 已經設定新的目標賽事，When 復原舊的刪除，Then 回 409 且新目標不變；其他帳號看不到也不能復原這筆事件。
- [x] AC-4：Given 有目標賽事歷史的帳號，When 下載備份，Then 歷史不含 `race_goals` 事件，`race_goal` 仍是目前內容。
- [x] AC-5：Given 歷史裡的目標賽事刪除，When 顯示並復原，Then 標示「目標賽事」並讓比賽準備重新讀取。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_race_goal_history.py::test_race_goal_changes_are_audited_and_a_deleted_goal_is_recovered` |
| AC-2 | `unit_tests/test_race_goal_history.py::test_race_goal_changes_are_audited_and_a_deleted_goal_is_recovered` |
| AC-3 | `unit_tests/test_race_goal_history.py::test_recovery_keeps_a_newer_goal_and_another_account_cannot_recover` |
| AC-4 | `unit_tests/test_race_goal_history.py::test_backups_leave_race_goal_history_out` |
| AC-5 | `unit_tests/frontend/workspace.test.cjs::SPEC-128 a recovered race goal is labelled and refreshes race preparation` |
