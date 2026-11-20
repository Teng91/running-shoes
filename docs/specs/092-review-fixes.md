# SPEC-092：程式碼審查修正：Strava 衝突的鞋款與重複連結、名額錯誤碼、重複登出

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-091](091-strava-conflict-choices.md)、[SPEC-088](088-logout-everywhere.md)、[SPEC-087](087-session-binding-and-hardening.md)

## Problem

對 v4.23.1～v4.26.0 的審查找到：

- 衝突活動選「匯入為新紀錄」時，若它的裝備只出現在衝突活動裡，預覽不會為那個裝備列出鞋款配對，匯入時被算成「未配對」默默略過。
- 兩筆衝突連結到同一筆手動紀錄時回 409「選擇已過期，請重新預覽」，重新預覽也無法解決；前端也沒有擋。
- 選了連結或匯入後，畫面沒有說明已選擇的結果。
- SPEC-087 把所有 403 的 `error.code` 改成 `forbidden`，註冊名額已滿也失去了 `capacity`。
- 「登出所有裝置」連按兩下時，第二個請求帶著已失效的 token，顯示「登出失敗」。
- README 的 API 表沒有提到 `conflicts` 欄位；`scripts/check_docs.py` 的清單多了一行空白。

## Goals

- 每個衝突活動的裝備都有鞋款配對群組，群組標示有幾筆待選擇的重複活動。
- 同一筆手動紀錄被選兩次時，前端停用匯入並說明，後端回 400「同一筆手動紀錄只能連結一個 Strava 活動」。
- 衝突下方即時顯示「已選擇：連結 N 筆、匯入 M 筆新紀錄」。
- 註冊名額已滿回 `error.code = "capacity"`，其他 403 仍是 `forbidden`。
- 「登出所有裝置」在請求進行中不再重複送出。

## Non-goals

- 不改變衝突判斷、候選紀錄與時間補寫規則。

## Proposed design

- `read_models/strava_preview.build_preview`：每筆衝突都確保它的裝備有群組（`count`／`km` 只算可直接匯入的活動），並加上 `conflict_count`。
- `strava_import.DuplicateConflictLinkError`（`ConflictChoiceError` 的子類別）在同一筆 run 被選兩次時丟出；router 對它回 400，其餘不符仍回 409。
- 前端 `stravaConflictProblem` 偵測重複連結、`stravaConflictSummary` 產生摘要，`updateStravaImportButton` 一併更新狀態列與按鈕。
- `routers/errors.CodedHTTPException` 帶自己的 `code`；`service_errors` 把 `CapacityExceeded` 轉成 code `capacity` 的 403，`http_exception_handler` 優先使用例外上的 code。
- `logoutEverywhere` 以 `logoutEverywhereRunning` 防止重入。

## Security and data isolation

- 查詢與 `user_id` 條件不變；新增群組只來自本次 CSV 的裝備名稱，畫面上照常跳脫。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：部署前自動快照；部署後 `release-check`。
- 回滾方式與資料相容性：可直接回滾至 v4.26.0 image。

## Acceptance criteria

- [x] AC-1：Given 只出現在衝突活動裡的裝備，When 預覽，Then 有該裝備的配對群組（`count` 0、`conflict_count` 2）；配對後選擇匯入的活動會被匯入，不算未配對。
- [x] AC-2：Given 兩筆衝突選同一筆手動紀錄，Then 後端回 400 與明確訊息，純函式丟 `DuplicateConflictLinkError`；前端停用匯入並說明，改選後恢復。
- [x] AC-3：Given 衝突選擇，Then 狀態列顯示已選擇的連結與匯入筆數。
- [x] AC-4：Given 註冊名額已滿，Then 回 403 與 `error.code = "capacity"`；一般帳號呼叫管理員 API 仍是 `forbidden`。
- [x] AC-5：Given 「登出所有裝置」進行中，When 再按一次，Then 不再詢問也不送出第二個請求。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_strava_manual_match.py::test_a_conflict_with_its_own_gear_can_be_mapped_and_two_links_to_one_run_are_refused` |
| AC-2 | `unit_tests/test_strava_manual_match.py::test_conflict_choices_skip_import_or_link_a_candidate_and_reject_stale_ones`、`unit_tests/frontend/run-pace.test.cjs::SPEC-092 two conflicts cannot link the same manual run` |
| AC-3 | `unit_tests/frontend/run-pace.test.cjs::SPEC-091 each conflict offers skip, a link to a manual run of that day or a new run, and the choice is sent` |
| AC-4 | `unit_tests/test_api_extra.py::test_registration_capacity_is_enforced`、`unit_tests/test_invites_and_accounts.py::test_only_admins_reach_admin_routes_and_me_says_who_is_admin` |
| AC-5 | `unit_tests/frontend/account.test.cjs::SPEC-092 a second click while logging out everywhere sends nothing` |
