# SPEC-063：Strava 繁中匯出的時段用語

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-047](047-review-hardening-and-decoupling.md)、[SPEC-062](062-strava-import-matches-manual-runs.md)

## Problem

- 繁中 Strava 匯出的「活動日期」不是只用「上午／下午」，還會寫「凌晨、清晨、中午、晚上」等時段，例如 `2026年10月31日 晚上11:30:52`（UTC）。
- 解析器只認得上午／下午；其他時段讀不到時間，只取日期，等於直接用 UTC 日期。「晚上」的 UTC 時間換成台灣時間是隔天清晨，這類跑步被記到前一天。
- 2026-11-17 正式站的匯入因此把兩筆清晨的跑步（11/01 07:30、10/17 07:51）記成 10/31、10/16；當天已有手動紀錄，但日期不同，SPEC-062 的配對認不出來，造成重複的 11.51 km。

## Goals

- 認得繁中匯出的所有時段用語，以 UTC 時間換算成台灣日期。
- 沒有時段用語的 24 小時制時間也能解析。

## Non-goals

- 不自動刪除或合併已經重複匯入的跑步；由使用者在網頁上刪除（刪除後不會再匯入）。
- 不改 SPEC-062 的配對規則（仍只比對同一天）。

## Proposed design

- `strava_import._CHINESE_TIME` 接受「午夜、半夜、凌晨、清晨、早上、上午」（12 小時制的上午）、「中午」（11–12 點維持，1–2 點加 12）、「下午、傍晚、晚上」（加 12），以及沒有用語的 24 小時制。
- 換算後的台灣日期與 UTC 日期照舊回傳；已存的紀錄若仍在 UTC 日期，重新匯入時由既有的日期修正（SPEC-047）移到台灣日期。

## Security and data isolation

- 只改 CSV 解析，沒有新的查詢或寫入；不涉及 secret。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：以實際匯出檔確認只有「晚上」的活動改變日期（357 筆中 2 筆）。
- 回滾方式與資料相容性：可直接回滾到 v4.16.0 image。

## Acceptance criteria

- [x] AC-1：Given 繁中匯出含凌晨、清晨、早上、上午、中午、下午、傍晚、晚上或午夜的時間，When 解析，Then 依 UTC 時間換算台灣日期；「晚上11:30」記在台灣的隔天，沒有時段用語的 24 小時制時間也正確。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_strava_import.py::test_strava_utc_timestamps_become_taipei_calendar_dates` |
