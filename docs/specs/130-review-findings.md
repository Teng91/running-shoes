# SPEC-130：程式碼檢查找到的 AI 教練、搜尋、管理員名稱、邀請碼與 Strava 預覽修正

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-075](075-invites-and-account-controls.md)、[SPEC-093](093-project-review-hardening.md)、[SPEC-097](097-strava-walk-hike-opt-in.md)

## Problem

2026-11-26 對 AI 教練、Strava 匯入、離線佇列與登入權限的逐行檢查找到下列問題（離線佇列的分區問題由 SPEC-129 處理）：

- 模型用文字寫出多個工具呼叫時只執行第一個，但對話紀錄保留全部；用裸 JSON 呼叫時，模型在呼叫後自己編的文字也留在紀錄裡。模型之後可能引用它沒拿到的數字。
- 串流的原生工具呼叫，如果供應商在每個片段都重複完整名稱，名稱會被接成 `list_my_shoeslist_my_shoes`，變成未知工具。
- 網路搜尋第一次失敗、第二次只是沒有結果時，仍回報 `request_failed`；失敗時供應商的原始錯誤文字（可能含代理或內部網址）會傳給模型與瀏覽器。
- 管理員名稱用 Python 的 `casefold()` 比對，帳號名稱只轉 A–Z 小寫（SPEC-093），兩個不同帳號（例如 `Straße` 與 `strasse`）可能都符合同一個管理員名稱。
- 邀請碼留白自動產生時，若隨機碼恰好和既有邀請碼相同，直接回「已經存在」，不重抽。
- Strava 預覽沒勾健行與步行時，`total_rows` 少算被排除的筆數。

## Goals

- 對話紀錄只留下實際執行的那一個呼叫；串流名稱不論分段或重複都正確。
- 搜尋「沒有結果」與「失敗」分清楚，原始錯誤只留在伺服器 log。
- 管理員名稱與帳號名稱用同一個比對規則。
- 自動產生的邀請碼撞到時重抽；預覽筆數包含被排除的健行與步行。

## Non-goals

- 不處理檢查提到的「晚上12:15 解析為中午」：Strava 的 zh-TW 時間依 ICU 時段，00:00–05:00 寫作「凌晨」或「午夜」，「晚上」只涵蓋 19–24 點，不會出現「晚上12」，現有解析正確。
- 不改變 API 路徑或回應欄位。

## Proposed design

- `tools/legacy_calls.first_call_end()` 回傳第一個被辨識的呼叫結束位置；`agent._record_assistant_turn` 把紀錄截到那裡。
- `llm._merged_name()`：新片段以目前名稱開頭時取代，否則接上。
- `search_tool._search_with_retry` 在任何一次成功回應後清除錯誤；`request_failed` 的 `error` 改為固定的 `SEARCH_UNAVAILABLE`，原文寫入伺服器 log。
- `settings.account_name_key()`（去頭尾空白、只轉 A–Z 小寫）同時用於 `ADMIN_USERNAMES`、`is_admin` 與 `accounts.username_key`。
- `invites._unused_generated_code()` 最多抽 5 次；自訂邀請碼撞到仍回衝突。
- `routers/strava._preview_upload` 在沒勾健行與步行時，`total_rows` 加上被排除的筆數。

## Security and data isolation

- 搜尋錯誤不再把供應商原文送到瀏覽器；管理員判斷不會因字母折疊規則把另一個帳號當成管理員。
- 其餘修正不改變任何查詢的 `user_id` 範圍。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：AI 教練一般問答、管理員頁面與 Strava 預覽照常運作。
- 回滾方式與資料相容性：直接回滾 v5.2.1 image。若 `ADMIN_USERNAMES` 含非 ASCII 字母，回滾後恢復 `casefold()` 比對。

## Acceptance criteria

- [x] AC-1：Given 模型寫出兩個文字工具呼叫或呼叫後接著自編文字，When 記錄這一輪，Then 只執行並記錄第一個呼叫，紀錄截在它結束的位置。
- [x] AC-2：Given 串流片段重複完整名稱或分段送出名稱，When 合併，Then 名稱都是 `list_my_shoes`。
- [x] AC-3：Given 第一次搜尋失敗、第二次沒有結果，When 搜尋，Then 回 `no_results`；全部失敗時 `error` 是固定訊息，不含原文。
- [x] AC-4：Given `ADMIN_USERNAMES=Strasse`，When 判斷 `STRASSE` 與 `Straße`，Then 只有前者是管理員。
- [x] AC-5：Given 自動產生的邀請碼撞到既有邀請碼，When 建立邀請，Then 重抽並成功。
- [x] AC-6：Given 沒勾健行與步行的 Strava 預覽，When 計算筆數，Then `total_rows` 包含被排除的健行與步行。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_review_findings.py::test_a_text_tool_turn_keeps_only_the_call_that_runs` |
| AC-2 | `unit_tests/test_review_findings.py::test_streamed_tool_names_merge_whether_split_or_repeated` |
| AC-3 | `unit_tests/test_search.py::test_a_failed_attempt_then_an_empty_answer_is_no_results`、`unit_tests/test_search.py::test_web_search_handles_exception_gracefully` |
| AC-4 | `unit_tests/test_review_findings.py::test_admin_names_fold_like_account_names` |
| AC-5 | `unit_tests/test_review_findings.py::test_a_generated_invite_code_that_collides_is_drawn_again` |
| AC-6 | `unit_tests/test_strava_import.py::test_strava_walks_and_hikes_are_opt_in` |
