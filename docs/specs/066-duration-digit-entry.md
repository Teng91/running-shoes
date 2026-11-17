# SPEC-066：手機數字鍵盤輸入時間

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-060](060-run-duration-and-pace.md)、[SPEC-065](065-race-readiness.md)

## Problem

- 跑步時間、比賽目標時間與參考成績時間都用 `inputmode="numeric"`，手機會跳出數字鍵盤；iOS 的數字鍵盤沒有冒號，只能輸入整數分鐘，打不出 `54:21` 或 `1:59:59`。

## Goals

- 只用數字鍵就能輸入 `m:ss` 與 `h:mm:ss`。
- 既有的輸入方式（含冒號、整數分鐘）不變。

## Non-goals

- 不改後端的時間範圍與配速驗證。
- 不改成時、分、秒三個分開的欄位。

## Proposed design

- `app-runs.js` 的 `groupDurationDigits` 在輸入只有數字與冒號時，移除冒號後從右邊每兩位分組：一、兩位不變（整數分鐘），三到四位成 `m:ss`，五到六位成 `h:mm:ss`；超過六位或含其他字元時保留原文，交給既有的驗證訊息。
- `formatDurationInput` 在 `input` 事件時改寫欄位並把游標放到最後；跑步新增／編輯沿用 `run-pace-preview` 動作，比賽目標的兩個欄位用新的 `duration-digits` 動作。
- 範例文字改成「直接打數字，例如 3215 → 32:15」。

## Security and data isolation

- 只改前端輸入格式，沒有新的 API、查詢或資料。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：手機打 `5421`、`15959` 看到 `54:21`、`1:59:59`。
- 回滾方式與資料相容性：可直接回滾到 v4.18.0 image。

## Acceptance criteria

- [x] AC-1：Given 手機數字鍵盤，When 在跑步時間、目標時間或參考成績時間逐字輸入數字，Then 欄位自動補冒號（`5421` → `54:21`、`15959` → `1:59:59`），一、兩位數仍是分鐘，刪除數字會重新分組，貼上的時間不變。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/run-pace.test.cjs::SPEC-066 digits typed on a phone number pad are grouped into a duration` |
