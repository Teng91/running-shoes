# SPEC-061：每次推送都跑 CI 與 main 保護

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-048](048-push-to-main-deploy-and-release.md)

## Problem

- 為了節省私人 repo 的 GitHub Actions 分鐘數，CI 只在 push 到 `main` 與 pull request 時執行，只改 Markdown 或 `docs/` 時完全不跑。
- 推到功能分支後沒有任何結果，要開 PR 才知道測試是否通過；只改文件的變更不會跑 `docs-check`。
- `main` 沒有保護：可以直接 push、force push，也可以在 CI 失敗時合併 PR，而合併到 `main` 就會部署到正式站。
- 2026-11-17 repo 改為公開，標準 runner 不再計分鐘數，省分鐘數的理由已不存在。

## Goals

- 任何分支的 push、每個 pull request（測試合併後的結果）都跑完整測試，包括只改文件的變更。
- 每週排程在 `main` 跑一次，依賴弱點掃描能抓到新公布的 CVE。
- `main` 只能透過 PR 合併；5 個測試 job 全部通過、分支跟上 `main` 才能合併；禁止直接 push、force push 與刪除，沒有繞過名單。
- 保護規則存在 repo 裡並由測試確認與 workflow 一致。

## Non-goals

- 不要求 code review 核准（單人維護，核准數為 0）。
- 不改部署、快照、release-check 與發版流程（SPEC-048）。
- 不新增測試 job，也不改 browser job 的重跑一次策略。

## Proposed design

- **`.github/workflows/verify.yml`**
  - 觸發：不限分支的 `push`、`pull_request`、`schedule`（每週一 01:00 UTC）與 `workflow_dispatch`；移除 `paths-ignore`。
  - 同一個分支的 push 與它的 PR 各跑一次：push 測分支本身，PR 測合併進目前 `main` 的結果。
  - concurrency：main 的 push／排程／手動執行仍用 `production` 群組且不取消；其他 ref 以 `ci-<event>-<ref>` 分組，較新的執行取消舊的。
  - 部署條件不變，只有 main 的 push 或手動執行會部署；排程與分支執行不部署。
- **`.github/rulesets/main.json`**：以 GitHub ruleset API 套用到預設分支。
  - `deletion`、`non_fast_forward`、`pull_request`（核准數 0）。
  - `required_status_checks`：`verify`、`frontend-layout`、`frontend-e2e`、`frontend-pwa`、`diagnostics-roundtrip`，來源限定 GitHub Actions（integration 15368），並要求分支跟上 `main`。
  - `bypass_actors` 為空，管理員也必須走 PR。
- **流程文件**：README 的部署章節與 AGENTS.md 改為「在分支開發、推送即跑 CI、透過 PR 合併」。

## Security and data isolation

- 不涉及使用者資料。workflow 權限不變：測試 job 沒有 secret，只有部署 job 取得 `FLY_API_TOKEN`。
- 來自 fork 的 PR 走 `pull_request` 事件，拿不到 secret；部署條件排除所有 PR 與排程。
- 保護規則防止未經測試的程式碼或被改寫的歷史進入會部署的 `main`。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：推送功能分支後確認 push 與 PR 兩個執行都出現；套用 ruleset 後確認直接 push 到 `main` 被拒、CI 未通過時 PR 無法合併。
- 回滾方式與資料相容性：GitHub → Settings → Rules → Rulesets 停用或刪除「Protect main」，並 revert workflow 的觸發條件。沒有資料相容性問題。

## Acceptance criteria

- [x] AC-1：Given 任何分支的 push、PR、每週排程或手動執行，When 觸發 workflow，Then 完整測試都會執行，只改文件也不跳過；只有 main 的 push／手動執行會部署。
- [x] AC-2：Given main 以外的 ref 有較新的執行，When 新的開始，Then 舊的被取消；main 的執行仍逐一進行且不取消。
- [x] AC-3：Given repo 裡的 ruleset，When 檢查內容，Then 它要求 PR、禁止刪除與 force push、必要檢查與 workflow 的 5 個測試 job 完全一致且要求分支最新，沒有繞過名單。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_deploy_workflow.py::test_ci_tests_every_push_pull_request_and_weekly_schedule_including_docs`、`unit_tests/test_deploy_workflow.py::test_deploy_runs_only_for_main_after_every_test_job` |
| AC-2 | `unit_tests/test_deploy_workflow.py::test_production_runs_are_serialized_without_cancelling` |
| AC-3 | `unit_tests/test_deploy_workflow.py::test_main_ruleset_requires_a_green_pull_request_without_bypass` |
