# SPEC-144：CI 重跑保留診斷、部署後檢查失敗自動回滾

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-048](048-push-to-main-deploy-and-release.md)、[SPEC-061](061-ci-on-every-push-and-protected-main.md)

## Problem

- 瀏覽器 job 失敗會自動重跑一次。重跑通過時只剩一行警告，第一次失敗的截圖與 trace 被第二次覆蓋，且只有整個 job 失敗才上傳，偶發失敗無從追查。
- `release-check` 在部署之後才執行；失敗時新版已經上線，只能手動回滾。

## Goals

- 重跑時：警告、在 run summary 寫一行，並把第一次的 `.artifacts/browser/` 移到 `.artifacts/browser-first-attempt/` 上傳為 `<job>-first-attempt` artifact（保留 7 天）。
- 部署前記錄所有機器執行的映像與 `/health/ready` 的 schema 版本。`release-check` 失敗時，新的 `rollback` job 在「這次 commit 的 `CURRENT_SCHEMA_VERSION` 與部署前相同」時以 `flyctl deploy --image <上一版> --rollback` 回到上一版；schema 改變或上一版不明時不動作，以錯誤標示改用文件化的回滾腳本。整個 run 仍為失敗，不會打 tag。

## Non-goals

- 不取消重跑（WebKit 在 CI 偶爾內部錯誤）；不自動執行 schema 回滾 SQL；不改部署策略。

## Proposed design

- `verify.yml` 的瀏覽器步驟與 release-check 步驟改為多行腳本：第一次成功即結束，失敗時輸出 `retried=true` 並重跑；`Save the first attempt of a retried run` 依 `steps.attempt.outputs.retried` 上傳。
- `deploy` job 的 `Record the running release for a rollback` 以 `flyctl machine list --json` 的 `config.image`（全部機器相同時）與 `/health/ready` 的 `schema_version` 產生 job outputs。
- `rollback` job：`needs: [deploy, release-check]`，`if: always() && needs.deploy.result == 'success' && needs.release-check.result == 'failure'`；只有 checkout 與 flyctl，不執行專案套件。

## Security and data isolation

- `FLY_API_TOKEN` 只給 `deploy` 與 `rollback`，兩者都不安裝或執行專案程式；測試 job 仍沒有 secret。
- 第一次嘗試的 artifact 與原本的失敗診斷相同，只含合成帳號或匿名畫面。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：下一次 push 的 CI；回滾 job 只在 release-check 失敗時出現。
- 回滾方式與資料相容性：還原 `verify.yml` 即可；不影響正式資料。

## Acceptance criteria

- [x] AC-1：Given 瀏覽器 job 第一次失敗，When 重跑，Then 留下警告、summary 一行與第一次的診斷 artifact；verify job 從不重跑。
- [x] AC-2：Given release-check 失敗，When 部署前後 schema 相同且上一版映像已知，Then rollback job 重新部署上一版；schema 改變或資訊不明時以錯誤結束而不部署。
- [x] AC-3：Given workflow，When 檢查 secret 使用，Then 只有 deploy 與 rollback 取得 `FLY_API_TOKEN`，且都不執行專案套件。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_deploy_workflow.py::test_browser_jobs_retry_once_with_a_visible_warning`、`unit_tests/test_task_runner.py::test_browser_jobs_are_independent_and_keep_timeout_diagnostics` |
| AC-2 | `unit_tests/test_deploy_workflow.py::test_a_failed_release_check_rolls_back_only_when_the_schema_did_not_move`、`unit_tests/test_deploy_workflow.py::test_deploy_runs_only_for_main_after_every_test_job` |
| AC-3 | `unit_tests/test_deploy_workflow.py::test_only_the_deploy_and_rollback_jobs_receive_the_fly_token` |
