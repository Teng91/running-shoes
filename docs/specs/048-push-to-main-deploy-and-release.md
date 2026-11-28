# SPEC-048：push 到 main 自動部署與發版

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-019](019-reliable-requests-and-release-gates.md)、[SPEC-047](047-review-hardening-and-decoupling.md)

## Problem

部署與發版全靠手動：在裝好 Fly CLI、`gh`、Python venv 與 Node 的電腦上，依 README 執行異地備份、`fly deploy`、release-check，再手動打 tag 和發 GitHub Release。

v4.7.3 發布時，維護者的 Windows 電腦缺少 Fly CLI 與 `gh`，venv 指向已刪除的 Python，Node 也不在 PATH 上。結果 commit 已推到 main，卻無法部署或發版，CI 的 WebKit 偶發錯誤也只能手動重跑。

## Goals

- push 到 `main`（或在 main 手動執行 workflow）時，全部測試通過才依序：在 Fly 主機上建立並驗證資料庫快照 → `flyctl deploy` → 匿名 release-check → 版號是新的才打 tag 並發 GitHub Release。
- 本機不需要任何部署工具。
- 權限最小化：只有部署 job 拿得到 `FLY_API_TOKEN`，且不執行專案套件；只有發版 job 能寫入 repo；測試與部署後檢查沒有 secret。
- main 的執行一次一個，正在進行的部署不被取消。
- Release 內容沿用既有慣例，取 `CHANGELOG.md` 對應版本的段落。
- browser 測試遇到 CI WebKit 偶發錯誤時自動重跑一次，並留下警告。

## Non-goals

- 不把正式資料庫下載到 GitHub（不做 artifact 備份）；異地備份仍用 `scripts/offsite_backup.py` 手動執行。
- 不加 `/version` API 或前端新版提示；既有 shell 版本診斷與 release-check 已涵蓋。
- 失敗時不自動回滾；回滾仍依各版 README／spec 的步驟手動進行。
- 不改變 pull request、其他分支與 tag 的測試行為（它們只測試、不部署）。

## Proposed design

- `.github/workflows/verify.yml`（名稱改為 Verify and deploy）新增 `workflow_dispatch` 觸發，以及三個只在 main 執行的 job：
  - `deploy`：`needs` 全部五個測試 job。步驟依序為：確認 secret 存在、以 `/health/ready` 喚醒可能被自動停機的機器、`flyctl ssh console` 執行 `scripts/database_backup.py create --source /data/shoes.db --output-dir /data/backups/predeploy --keep 10`（輸出必須含 `Backup created and verified:`）、`flyctl deploy --remote-only --ha=false`。checkout 不保留 GitHub 憑證，不安裝 Python／Node 套件。
  - `release-check`：在 Playwright 容器以 `python scripts/task.py release-check --base-url https://running-shoes.fly.dev` 檢查正式站；沒有 secret。
  - `release`：唯一有 `contents: write` 的 job。`package.json` 與 `frontend/assets.json` 版號不一致就失敗；tag 已存在就只記錄「只部署」；否則以 `CHANGELOG.md` 段落（沒有就列出最近 commit 並警告）打 annotated tag、push，並 `gh release create --verify-tag`。以 `GITHUB_TOKEN` push 的 tag 不會再觸發 workflow。
- workflow 層級 concurrency：main 的 push／手動執行共用 `production` group、`cancel-in-progress: false`；其他 ref 各自一個 group。
- `frontend-layout`、`frontend-e2e`、`frontend-pwa` 與 `release-check` 失敗時重跑一次並輸出 `::warning::`；`verify`（單元、lint、文件）不重跑。

## Security and data isolation

- 不新增或改變任何 user-scoped query；正式資料只在 Fly volume 上複製，不離開 Fly。
- `FLY_API_TOKEN` 是只限 `running-shoes` 的 deploy token，只在部署 job 的三個步驟以環境變數提供；該 job 不執行 npm／pip 安裝腳本或專案測試程式。
- 測試 job 會執行第三方套件，所以拿不到任何 secret，`GITHUB_TOKEN` 也只有讀取權限；寫入權限只給發版 job。
- token 一年到期，README 記載重新產生與覆蓋 secret 的步驟。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：
  1. 依 README 建立 `FLY_API_TOKEN` repository secret。
  2. push 本變更到 main；第一次執行會部署 v4.7.3，並因 `v4.7.3` tag 尚不存在而自動發版。
  3. 確認 Actions 中五個測試 job、deploy、release-check、release 都成功，GitHub Releases 出現 v4.7.3，`/data/backups/predeploy` 有一份快照。
- 回滾方式與資料相容性：刪除 `deploy`／`release-check`／`release` job 即回到只測試的 CI；正式站版本回滾仍用 `fly deploy --image <先前 image>`。快照可依 README「資料庫備份、驗證與還原」離線驗證與還原。

## Acceptance criteria

- [x] AC-1：Given push 到 main 或在 main 手動執行，When 全部測試 job 成功，Then 才會部署；pull request、其他分支與 tag 不會部署，部署之後才做 release-check，release-check 之後才發版。
- [x] AC-2：Given workflow 內的各個 job，When 檢查 secret 與權限，Then 只有部署 job 取得 `FLY_API_TOKEN` 且不安裝或執行專案套件，只有發版 job 有 `contents: write`，其他 job 只能讀取。
- [x] AC-3：Given 部署 job，When 執行，Then 先在 Fly volume 建立並驗證資料庫快照，快照失敗就不部署；遠端指令、資料庫路徑與成功訊息和 image 內容一致。
- [x] AC-4：Given 發版 job，When `package.json` 的版號還沒有 tag，Then 以 `CHANGELOG.md` 對應段落打 tag 並發 Release；tag 已存在只部署不發版；版號與 `frontend/assets.json` 不一致時失敗；缺少段落時改列 commit 並警告。
- [x] AC-5：Given main 上連續 push，When workflow 排隊，Then 一次只跑一個，正在進行的部署不被取消。
- [x] AC-6：Given browser 測試或部署後檢查遇到偶發失敗，When 執行，Then 重跑一次並留下警告；`verify` 不重跑。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_deploy_workflow.py::test_deploy_runs_only_for_main_after_every_test_job` |
| AC-2 | `unit_tests/test_deploy_workflow.py::test_only_the_deploy_and_rollback_jobs_receive_the_fly_token` |
| AC-3 | `unit_tests/test_deploy_workflow.py::test_deploy_takes_a_verified_database_snapshot_before_deploying` |
| AC-4 | `unit_tests/test_deploy_workflow.py::test_release_tags_only_new_versions_after_the_release_check` |
| AC-5 | `unit_tests/test_deploy_workflow.py::test_production_runs_are_serialized_without_cancelling` |
| AC-6 | `unit_tests/test_deploy_workflow.py::test_browser_jobs_retry_once_with_a_visible_warning` |
