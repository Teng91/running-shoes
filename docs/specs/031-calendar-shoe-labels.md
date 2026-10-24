# SPEC-031：跑步月曆移除次數標示

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-017](017-consistent-statistics-and-feature-lifecycles.md)

## Problem

跑步月曆的鞋款按鈕顯示「鞋款 · N 次」，使用者要求移除次數。

## Goals

- 月曆只呈現日期、每日里程及鞋款名稱。
- 保留鞋款按鈕的當日明細篩選與既有空白日期操作。

## Non-goals

- 不調整月統計卡、鞋款分析或後端次數統計。

## Proposed design

移除 `renderRunCalendar` 彙總鞋款按鈕文字的次數後綴，沿用既有轉義、日期及點擊事件。

## Security and data isolation

- 純顯示調整，不新增查詢、寫入、權限或外部依賴。

## Migration, rollout, and rollback

- 無資料 migration；以 frontend-test、frontend-layout 及 docs-check 驗證。
- 使用既有 frontend build 產生靜態輸出；回滾可還原顯示變更，不涉及資料。

## Acceptance criteria

- [x] AC-1：Given 同日鞋款彙總，When 渲染月曆，Then 顯示鞋款與每日里程，不顯示次數，且保留當日篩選。
- [x] AC-2：Given 無跑步資料的月份，When 渲染月曆，Then 保留完整日期與新增日期操作，不出現鞋款按鈕。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/statistics-lifecycle.test.cjs::SPEC-031 calendar shows shoe names and distance without run counts` |
| AC-2 | `unit_tests/frontend/statistics-lifecycle.test.cjs::SPEC-031 calendar shows shoe names and distance without run counts` |
