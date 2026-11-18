# SPEC-078：每日加密異地備份

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-014](014-offsite-backup-and-pwa-upgrades.md)、[SPEC-048](048-push-to-main-deploy-and-release.md)

## Problem

- 自動備份只有部署前的快照，而且放在正式資料所在的同一個 Fly volume；volume 遺失或超過 Fly 快照保留天數時救不回來。
- `offsite_backup.py` 可以下載到別處，但需要有人手動執行。

## Goals

- 每天自動把正式資料庫的快照下載到 Fly 以外、驗證並做隔離還原演練。
- 只上傳以 `BACKUP_PASSPHRASE` 加密的檔案到 GitHub artifact，保留 30 天。
- 不需要新的雲端帳號或費用。

## Non-goals

- 不自動還原正式站。
- 不另開私人 repo 或外部儲存服務。

## Proposed design

- `.github/workflows/offsite-backup.yml`：每天 03:30（台北）與手動觸發。第一步檢查 `BACKUP_PASSPHRASE`（至少 20 字元）與 `FLY_API_TOKEN`，缺少就失敗，不會產生任何備份。
- 以既有的 `scripts/offsite_backup.py` 把快照下載到 `$RUNNER_TEMP`（checkout 之外），驗證 checksum、完整性並做隔離還原演練。
- 把快照目錄（`.db`、`.sha256`、`manifest.json`）打包後以 `openssl enc -aes-256-cbc -pbkdf2 -iter 600000` 加密，刪除明文；上傳前先解密一次確認內容完整，只上傳 `.tar.gz.enc`，`retention-days: 30`。
- 還原：下載 artifact，`openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -in <檔案> | tar -xzf -`，再用 `database_backup.py verify`／`drill`。

## Security and data isolation

- repo 公開，artifact 與 log 任何登入 GitHub 的人都看得到；所以只上傳加密檔，log 只印檔名與大小，不印帳號、筆數或資料。
- 加密密碼只存在 GitHub secret（log 自動遮蔽），站長需另外保存；遺失就無法解密。
- workflow 權限只有 `contents: read`，checkout 不保留憑證。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：設好 `BACKUP_PASSPHRASE` 後手動觸發一次，確認 artifact 只有 `.tar.gz.enc` 且能解密。
- 回滾方式與資料相容性：刪除或停用這個 workflow 即可，不影響正式站。

## Acceptance criteria

- [x] AC-1：Given workflow，When 檢查設定，Then 每天排程、可手動觸發、只有讀取權限，第一步缺少密碼就失敗。
- [x] AC-2：Given 快照，When 上傳前，Then 已加密、明文已刪除、先解密驗證過，只上傳 `.tar.gz.enc` 並保留 30 天，log 不印資料。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_deploy_workflow.py::test_daily_offsite_backup_uploads_only_an_encrypted_archive` |
| AC-2 | `unit_tests/test_deploy_workflow.py::test_daily_offsite_backup_uploads_only_an_encrypted_archive` |
