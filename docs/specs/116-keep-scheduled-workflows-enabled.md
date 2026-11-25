# SPEC-116：排程 workflow 每天續命

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-078](078-daily-encrypted-offsite-backup.md)、[SPEC-061](061-ci-on-every-push-and-protected-main.md)

## Problem

- 公開 repo 連續 60 天沒有 commit，GitHub 會自動停用所有 `schedule` 觸發的 workflow；排程自己跑不算活動。
- 停用時不會失敗也不會報錯，只是安靜地不再執行。受影響的是每天的 `offsite-backup.yml`（停了就悄悄沒有異地備份）與 `verify.yml` 每週一的相依套件漏洞檢查。

## Goals

- 每天以 GitHub API 重新啟用兩個排程 workflow，不產生假 commit。
- 只有續命的 job 有 `actions: write`；碰到正式資料庫的備份 job 維持 `contents: read`。
- 續命失敗只發警告，不讓備份失敗，也不擋住備份。

## Non-goals

- 不建立外部 cron 或定期空 commit。
- 不改變備份或 CI 本身的內容與時間。

## Proposed design

- `offsite-backup.yml` 新增獨立的 `keep-schedules-enabled` job，與 `backup` 平行執行（沒有 `needs`），job 層級權限只有 `actions: write`，不 checkout、不用任何 secret。
- 它以 `GITHUB_TOKEN` 對 `offsite-backup.yml` 與 `verify.yml` 各呼叫一次 `PUT /repos/{repo}/actions/workflows/{file}/enable`；成功印出 `Re-enabled the schedule of <file>`，失敗只印 `::warning::`。
- 測試確認 repo 裡每個有 `schedule` 的 workflow 都在續命清單中，新增排程 workflow 時不會漏掉。

尚未證實：GitHub 沒有文件保證呼叫 enable 會重設 60 天的計時，目前只確認 API 會成功。若之後仍收到 GitHub 的「scheduled workflows disabled」通知信，改用 repo 以外的 cron（例如另一個持續有 commit 的 repo，或外部排程服務）呼叫 `workflow_dispatch`。

## Security and data isolation

- 不碰使用者資料。`actions: write` 只給續命 job，它不 checkout、不接觸 `FLY_API_TOKEN` 或 `BACKUP_PASSPHRASE`；備份 job 的權限不變。
- log 只印 workflow 檔名。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：合併後在 Actions 頁手動觸發一次 `offsite-backup`，確認 `keep-schedules-enabled` 的 log 有兩行 `Re-enabled the schedule of …`，備份 artifact 照常產生。
- 回滾方式與資料相容性：移除這個 job 即可，不影響正式站與備份。

## Acceptance criteria

- [x] AC-1：Given `offsite-backup.yml`，When 每天排程或手動執行，Then 獨立的續命 job 以 `GITHUB_TOKEN` 重新啟用 repo 裡所有排程 workflow（`offsite-backup.yml`、`verify.yml`）。
- [x] AC-2：Given 續命 job，When 檢查權限與失敗行為，Then 只有它有 `actions: write`、不依賴備份 job、不使用 secret，失敗只發警告。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_deploy_workflow.py::test_offsite_backup_keeps_every_scheduled_workflow_enabled` |
| AC-2 | `unit_tests/test_deploy_workflow.py::test_offsite_backup_keeps_every_scheduled_workflow_enabled` |
