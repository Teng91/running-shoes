# SPEC-062：Strava 匯入辨識手動輸入的跑步

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-060](060-run-duration-and-pace.md)、[SPEC-055](055-correctness-fixes-and-strava-deletions.md)

## Problem

- Strava 匯入只用 Strava 活動 ID 判斷重複。手動輸入的跑步沒有活動 ID，用涵蓋同一期間的 CSV 匯入時，同一次跑步會再新增一筆，跑鞋里程與月跑量變成雙倍。
- SPEC-060 的補時間只針對先前從 Strava 匯入的紀錄；大多數紀錄是手動輸入的使用者，無法用 Strava 匯出補上時間與配速。

## Goals

- 匯入時，Strava 活動若和同一天的手動紀錄是同一次跑步，就不新增，而是把活動 ID 連結到那筆紀錄，並在它沒有時間時補上移動時間。
- 無法確定是同一次時，一律不匯入，在預覽列出筆數與例子，絕不重複計算里程。
- 連結後的紀錄在之後的匯入被當成已匯入；刪除後沿用 SPEC-055 的刪除紀錄，不會再被匯回來。

## Non-goals

- 不修改手動紀錄的距離、日期或鞋款，也不用 Strava 的距離覆寫手動輸入。
- 不處理跨日期（例如手動填錯日期）的配對，也不提供手動指定配對的介面。
- 不改 schema、備份格式或匯入歷史的欄位。

## Proposed design

- **`strava_import.manual_matches(rows, manual_runs, known_ids)`**：純函式。只看還沒匯入、也沒被刪除過的活動，依在地日期分組。
  - 距離容許差 `max(0.3 km, 5%)`（`MANUAL_MATCH_MIN_KM`、`MANUAL_MATCH_RATIO`），手動輸入常四捨五入。
  - 活動在當天只有一筆距離接近的手動紀錄，且那筆手動紀錄也只有這一個距離接近的活動 → **連結**。手動紀錄沒有時間且 Strava 時間換算的配速合理（依手動距離）時帶上時間。
  - 當天有手動紀錄但不符合上面條件（距離差太多、同天多筆無法一對一）→ **衝突**，不匯入也不連結。
  - 當天沒有手動紀錄 → 照常匯入。
- **`read_models/strava_preview.stored_runs()`**：一次讀出使用者的 Strava 紀錄、手動紀錄與刪除過的活動 ID，預覽與匯入共用，確保兩者結果一致。
- **預覽**新增 `manual_link_count`、`manual_link_duration_count`、`manual_conflict_count`、`manual_conflict_samples`（前 5 筆日期與距離）；`importable_count`／`importable_km` 不含連結與衝突的活動。
- **匯入**在同一個寫入交易中以 `_link_manual_runs` 更新 `strava_id`（條件 `user_id` 相符且 `strava_id IS NULL`）、版本 +1、必要時補時間；結果新增 `linked_manual`、`skipped_manual_conflict`。里程不變，因為距離與鞋款沒動。匯入歷史的「重複」筆數包含連結與衝突的活動。
- **前端** `app-strava.js` 的預覽說明連結與略過的筆數與例子；只需連結時也可以按匯入。

## Security and data isolation

- 手動紀錄的查詢與連結更新都限定 `user_id`，另一個帳號同一天的紀錄不參與配對。
- 不涉及 secret 或外部服務；CSV 仍只在請求中解析，不保存。

## Migration, rollout, and rollback

- Schema／資料 migration：無（schema 9 不變）。
- 上線與 smoke test：上線後先用完整歷史的 CSV 開預覽（預覽不寫入），確認「可匯入」只剩沒手動輸入的日子、連結筆數合理，再匯入。
- 回滾方式與資料相容性：可直接回滾到 v4.15.0 image。已連結的紀錄多了 `strava_id`，舊版會把它們當成已匯入的 Strava 紀錄，不會重複。

## Acceptance criteria

- [x] AC-1：Given 同一天只有一筆距離接近的手動紀錄，When 預覽或匯入，Then 活動不會新增，而是連結到該紀錄並補上缺少且合理的時間，已有的時間不覆寫，跑鞋與月跑量不變。
- [x] AC-2：Given 同一天有手動紀錄但距離差太多或無法一對一，When 匯入，Then 活動不匯入也不連結，預覽列出筆數與例子；當天沒有手動紀錄的活動照常匯入。
- [x] AC-3：Given 已連結的紀錄，When 再次匯入或刪除後再匯入，Then 它被當成重複或已刪除，不會再新增；另一個帳號的手動紀錄不參與配對。
- [x] AC-4：Given 預覽有連結或略過的手動紀錄，When 顯示摘要，Then 說明筆數與例子，只有連結時也能按匯入。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_strava_manual_match.py::test_manual_matches_link_only_unambiguous_same_day_runs`、`unit_tests/test_strava_manual_match.py::test_import_links_hand_entered_runs_without_doubling_mileage` |
| AC-2 | `unit_tests/test_strava_manual_match.py::test_manual_matches_link_only_unambiguous_same_day_runs`、`unit_tests/test_strava_manual_match.py::test_import_links_hand_entered_runs_without_doubling_mileage` |
| AC-3 | `unit_tests/test_strava_manual_match.py::test_import_links_hand_entered_runs_without_doubling_mileage`、`unit_tests/test_strava_manual_match.py::test_a_deleted_linked_run_is_not_imported_again` |
| AC-4 | `unit_tests/frontend/run-pace.test.cjs::SPEC-062 the Strava preview explains linked and skipped hand-entered runs` |
