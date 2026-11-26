# SPEC-133：月報額度、報告清單、支出平均與下載連結的小修正

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-026](026-inline-edit-ownership-and-report-generations.md)、[SPEC-071](071-public-site-hardening.md)、[SPEC-132](132-report-export-plan-module-fixes.md)

## Problem

2026-11-26 對月報、支出、匯出與 PWA 更新的檢查另外找到幾個小問題：

- 月報請求因為月份在未來或模型不允許而被拒絕時，仍先扣了 AI 額度。
- 已存月報的清單沒有請求序號，較舊的回應晚到會蓋掉較新的清單，剛產生的月份暫時不見。
- 支出：購買日期格式不正確的舊鞋款會算進總額，卻不屬於任何月份；每月平均用總額除以月份數，兩者對不起來。
- 匯出下載在點擊後立刻釋放 blob URL，部分 WebKit 版本會取消下載。
- AGENTS.md 寫 `app-lifecycle.js` 第一個載入，實際上 `app-boot.js` 在它之前。

## Goals

- 只有會執行的月報請求才扣 AI 額度；報告清單以最新請求為準。
- 每月平均只除以月份裡的金額；下載連結在瀏覽器開始讀取後才釋放；文件與載入順序一致。

## Non-goals

- 不改變「較新的月報請求失敗時，不恢復舊請求的儲存資格」：SPEC-026 明訂如此，保留之前成功的報告。檢查把它列為問題，這裡維持原設計。
- 不改變帳號備份裡月報與 Strava 匯入時間的格式：改加時區會改變 v6 檔案內容與還原時的比對，現有檔案都以 UTC 解讀並能往返。

## Proposed design

- `routers/reports.generate_monthly_report` 先檢查月份與模型，再呼叫 `enforce_agent_request_limits`。
- `app-reports.loadReportHistory()` 以 `reportHistoryRequestId` 忽略較舊的回應。
- `read_models/spending.average_monthly_paid` 以各月份金額總和除以月份數；總額不變。
- `app-exports` 的兩個下載在 60 秒後才 `revokeObjectURL`。
- AGENTS.md 改為「緊接在 `app-boot.js` 之後載入」。

## Security and data isolation

- 只調整檢查順序與顯示；查詢的 `user_id` 範圍不變。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：月報、支出與匯出照常運作。
- 回滾方式與資料相容性：直接回滾 v5.2.4 image。

## Acceptance criteria

- [x] AC-1：Given 未來月份或不允許的模型，When 產生月報，Then 回 422／400 且不扣 AI 額度。
- [x] AC-2：Given 兩次報告清單請求，When 較舊的回應晚到，Then 清單維持較新的結果。
- [x] AC-3：Given 一雙購買日期格式不正確的鞋，When 計算支出，Then 總額包含它，每月平均不包含。
- [x] AC-4：Given 帳號備份下載，When 點擊下載，Then blob URL 不會立即釋放。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_reports.py::test_refused_report_requests_never_spend_the_ai_quota` |
| AC-2 | `unit_tests/frontend/crud-reports.test.cjs::SPEC-133 an older report history response never replaces a newer one` |
| AC-3 | `unit_tests/test_statistics_consistency.py::test_spending_read_model_uses_calendar_months_and_user_scope` |
| AC-4 | `unit_tests/frontend/workspace.test.cjs::SPEC-029 workspace download reports results and ignores a replaced session` |
