# SPEC-084：新帳號引導

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-075](075-invites-and-account-controls.md)

## Problem

- 用邀請碼註冊的新帳號登入後是一片空白，只有各個圖表自己的「還沒有紀錄」提示，不知道第一步要做什麼；也不知道要先有鞋子才能記錄跑步。

## Goals

- 跑步頁最上方顯示「開始使用：三個步驟」：① 新增第一雙鞋 ② 記錄跑步或匯入 Strava ③ 設定月目標；每步有直接開啟對應表單的按鈕。
- 完成的步驟打勾，下一步加上強調；第 2 步在有鞋子之前停用並提示先完成第 1 步。
- 三步都完成或按「略過引導」後不再顯示；略過只記在這台裝置、依帳號分開。
- 既有帳號（已經三步都完成）看不到，資料載入完成前也不會閃一下。

## Non-goals

- 不新增 API 或資料欄位；完成狀態完全由現有資料推導。
- 不做導覽動畫或多頁教學。

## Proposed design

- `frontend/app-onboarding.js`：`onboardingSteps()` 由已載入的 `shoes`／`retiredShoes`（有鞋）、`monthlyMileages`（有任何月份大於 0 km）與 `runningGoal.version > 0`（儲存過目標）推導三步狀態。
- `app-dashboard.render(resource)` 呼叫 `noteOnboardingData(resource)`，`shoes`、`monthly`、`goal` 三個資源都至少到過一次才可能顯示；登出或切換帳號時由 `registerFeatureReset` 清空。跑步頁重畫時也呼叫 `renderOnboarding()`。
- 「略過引導」寫入 `localStorage` 的 `onboarding-dismissed:<小寫帳號>`，讀寫失敗時視為沒略過。
- 按鈕沿用既有動作（`add-shoe`、`open-strava`），另外新增 `onboarding-log-run`（聚焦距離欄位）與 `onboarding-set-goal`（切到「跑量與目標」並打開目標設定）。

## Security and data isolation

- 只讀目前帳號已載入的資料；`localStorage` 只存一個略過旗標，不含任何紀錄或憑證。頁面 CSP 不變（沒有 inline handler）。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：新帳號登入後跑步頁顯示三步驟；新增鞋子後第 1 步打勾。
- 回滾方式與資料相容性：可直接回滾到 v4.22.1 image；略過旗標在舊版被忽略。

## Acceptance criteria

- [x] AC-1：Given 新帳號，When 鞋子、月跑量與目標都載入後，Then 顯示三步驟與「已完成 0 / 3」，第 2 步在有鞋子前停用；依序完成後逐步打勾，三步都完成時卡片消失；登出後重新等待下一個帳號的資料。
- [x] AC-2：Given 已有鞋子、跑量與目標的帳號，When 載入，Then 不顯示；按「略過引導」後這個帳號不再顯示，其他帳號不受影響。
- [x] AC-3：Given 引導卡，When 按各步驟的按鈕，Then 分別開啟新增跑鞋、聚焦跑步表單、開啟 Strava 匯入與目標設定。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/onboarding.test.cjs::SPEC-084 a new account sees the three steps only after its data loaded and they tick off in order` |
| AC-2 | `unit_tests/frontend/onboarding.test.cjs::SPEC-084 an established account never sees the card and skipping is remembered per account` |
| AC-3 | `unit_tests/frontend/onboarding.test.cjs::SPEC-084 the step buttons open the shoe form, the run form, Strava and the goal settings` |
