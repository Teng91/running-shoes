# SPEC-091：Strava 與手動紀錄衝突時讓使用者選擇

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-062](062-strava-import-matches-manual-runs.md)

## Problem

SPEC-062 只在「同一天只有一筆距離接近的手動紀錄」時自動連結。當天有手動紀錄但距離差太多，或同一天有多筆、無法一對一時，活動一律不匯入；預覽只列出筆數與前 5 個例子，使用者沒有辦法說「這筆就是那次」或「這是另一次跑步，請匯入」，只能刪掉手動紀錄再匯入，或乾脆放棄。

## Goals

- 預覽列出每一筆衝突的日期、距離、時間、裝備，以及當天可以連結的手動紀錄（距離、時間、鞋款）。
- 每筆衝突可選擇略過（預設，與原本行為相同）、連結到其中一筆手動紀錄，或匯入為新紀錄。
- 後端重新驗證每個選擇；不屬於本次衝突、不是候選、同一筆手動紀錄被選兩次，或格式錯誤，都不套用任何變更。

## Non-goals

- 不改變自動連結的規則與容許誤差。
- 不提供把 Strava 的距離寫回手動紀錄；連結時距離、日期與鞋款維持手動輸入的值。

## Proposed design

- `strava_import.manual_matches` 的每筆衝突多帶 `duration_seconds`、`gear` 與 `candidate_run_ids`：當天的手動紀錄，扣除本次會自動連結的。
- `strava_import.resolve_conflicts(conflicts, choices, manual_runs)` 是純函式：choice 為 `"skip"`、`"import"` 或候選 run id；連結時只有在距離接近（SPEC-062 的容許範圍）且配速合理、手動紀錄沒有時間時才補上時間，避免把另一個距離的時間寫進去。不合規則時丟 `ConflictChoiceError`。
- `read_models.strava_preview.build_preview` 新增 `manual_conflicts`（每筆衝突與候選紀錄的距離、時間、鞋名，只查本帳號）；`manual_conflict_samples` 維持原格式給舊前端。
- `POST /api/runs/import/strava` 新增選填 form 欄位 `conflicts`（JSON 物件，預設 `{}`）。`services.strava_imports.import_runs(conflict_choices=…)` 在同一個寫入交易中把選擇的連結併入自動連結，選擇匯入的活動照一般規則匯入（仍需鞋款配對）。格式錯誤回 400，選擇與目前資料不符回 409「重複活動的選擇已過期，請重新預覽」。
- 前端在鞋款配對下方列出衝突，每筆一個下拉選單；只要有任何非略過的選擇，「匯入」按鈕就可以按。

## Security and data isolation

- 候選紀錄只來自本帳號、`strava_id` 為空的跑步；連結的 UPDATE 仍以 `user_id` 與 `strava_id IS NULL` 為條件。別的帳號的 run id 不會是候選，會回 409。
- 選擇只影響本次匯入，不保存。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：部署前自動快照；部署後 `release-check`。
- 回滾方式與資料相容性：可直接回滾至 v4.25.2 image；舊版忽略 `conflicts` 欄位，衝突照舊略過。

## Acceptance criteria

- [x] AC-1：Given 同一天另有手動紀錄，When 預覽，Then 每筆衝突列出可連結的手動紀錄，不含本次會自動連結的，也不含其他帳號的紀錄。
- [x] AC-2：Given 衝突選擇，Then 略過、匯入與連結候選會照選擇套用；連結時只在距離接近時補上時間；不屬於衝突、不是候選、重複選同一筆、格式錯誤都會被拒。
- [x] AC-3：Given 匯入時一筆選連結、一筆選匯入，Then 連結的紀錄保留手動的距離且里程不變，匯入的活動新增紀錄並計入里程；之後重新預覽不再出現衝突。格式錯誤回 400；選了其他帳號的紀錄回 409，且不改動任何資料。
- [x] AC-4：Given 前端預覽，Then 每筆衝突有略過、連結到手動紀錄、匯入為新紀錄的選項（名稱經過跳脫），選擇會送到後端；全部略過時不能按匯入。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_strava_manual_match.py::test_conflicts_offer_every_same_day_manual_run_not_linked_automatically` |
| AC-2 | `unit_tests/test_strava_manual_match.py::test_conflict_choices_skip_import_or_link_a_candidate_and_reject_stale_ones` |
| AC-3 | `unit_tests/test_strava_manual_match.py::test_the_user_links_or_imports_a_conflict_and_mileage_follows_the_choice` |
| AC-4 | `unit_tests/frontend/run-pace.test.cjs::SPEC-091 each conflict offers skip, a link to a manual run of that day or a new run, and the choice is sent` |
