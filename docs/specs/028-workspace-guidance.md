# SPEC-028：資料與同步操作說明與結果回饋

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-027](027-recoverable-account-workspace.md)

## Problem

「立即同步」沒有空佇列或離線提示，看起來像按鈕失效。現有 README 偏重工程規格，使用者無法判斷備份合併及清除本機資料的影響。

## Goals

- 同步按鈕顯示處理中、無待同步資料、完成、待處理或不可同步的原因。
- 頁面與使用指南明確說明伺服器資料、本機草稿、待同步紀錄及備份的差異。

## Non-goals

- 不變更同步、備份合併或資料清除的後端規則，不執行部署。

## Proposed design

在既有 DOM bridge 加入同步狀態區與按鈕忙碌狀態；自動與手動同步共用進行中的工作。保留 session guard，舊帳號完成時不更新新帳號介面。頁面加入各功能的用途及操作前提，README 連到繁體中文使用指南。

## Security and data isolation

- 不新增資料查詢或傳送認證資訊；本機記錄沿用帳號分區，測試使用合成資料。
- 指南說明 JSON 只包含目前帳號的伺服器資料，不包含尚未同步紀錄或草稿。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：先完成前端回歸、版面及文件檢查；本次僅修改工作區檔案。
- 回滾方式與資料相容性：回復前端來源並重新生成資產，資料格式不變。

## Acceptance criteria

- [x] AC-1：Given 空佇列／離線／未就緒，When 按立即同步，Then 顯示明確原因；同步中停用按鈕，完成顯示成功及剩餘筆數。
- [x] AC-2：Given 錯誤／待處理資料／帳號切換，When 同步完成，Then 不誤報全部完成且舊帳號不污染新介面。
- [x] AC-3：Given 資料與同步頁面，When 閱讀功能說明，Then 可確認備份僅合併目前帳號且本機清除會丟失未同步資料；README 提供操作指南入口。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/workspace.test.cjs::SPEC-028 manual sync explains empty offline and unavailable states`、`unit_tests/frontend/workspace.test.cjs::SPEC-028 sync shares pending work and reports uploaded runs` |
| AC-2 | `unit_tests/frontend/workspace.test.cjs::SPEC-028 sync reports blocked pending and storage failures`、`unit_tests/frontend/workspace.test.cjs::SPEC-028 stale sync cannot change the next account feedback` |
| AC-3 | `unit_tests/frontend/workspace.test.cjs::SPEC-028 workspace guidance distinguishes server backup and local data`、`python3 scripts/task.py docs-check` |

## Verification evidence

- `frontend-test`：129 項通過。
- `frontend-e2e`：Chromium／WebKit 通過，包含實際點擊空佇列與離線同步按鈕、原有工作區合併還原及本機匿名 release-check。
- `frontend-layout`：40 組引擎／主題／尺寸通過，包含資料與同步彈窗。
- `docs-check`：生成資產、連結、測試數量與規格追溯通過。所有操作測試只使用本機合成帳號與暫存資料庫，未部署。
