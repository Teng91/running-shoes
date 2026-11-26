# SPEC-127：訓練課表排版移到 native module

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-100](100-architecture-ratchet.md)、[SPEC-119](119-race-training-plan.md)

## Problem

- `frontend/app-pace-charts.js` 有 406 行，同時負責比賽準備摘要卡、長距離與強度圖、配速趨勢，以及訓練課表的表格和說明文字。課表在 SPEC-119～124 每一版都在改，改它就得碰整個比賽準備的 script。
- 把課表拆成另一個 classic script 會讓 `paceClock`、`zoneColor`、`zoneRangeText` 變成跨 script 共用的全域名稱，違反 SPEC-100 只准變少的基準。

## Goals

- 課表的表格列與說明文字由一個不碰 DOM 的 native module 產生，可以直接匯入測試。
- 畫面與文字完全不變；classic script 共用名稱與互相依賴的組合都不增加。

## Non-goals

- 不改課表的內容、排法或後端回應。
- 不搬移比賽準備的其他圖表。

## Proposed design

- 新的 `frontend/runtime/race-plan-view.mjs` 匯出 `racePlanView(race, format)`，回傳 `{ rows, note }`；沒有課表時回傳 null。`format` 提供 `esc`、`paceClock`、`zoneColor`、`zoneRangeText`、`raceShortDate`、`raceDistanceName`，模組本身不讀全域。
- `app-pace-charts.js` 的 `renderRacePlan(race, requestId)` 第一次需要時以 `import()` 載入模組（帶 asset 版本），若期間有更新的請求就不寫入；`renderPaceAnalysis` 不等它就先畫圖，最後再等它完成。
- 模組列入 `assets.json` 的 `modules`，由 service worker 預先快取，離線也能顯示。

## Security and data isolation

- 只排版後端已經依使用者範圍算好的課表；文字欄位一律經注入的 `esc` 轉義，不新增資料來源。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：訓練分析分頁的課表表格與說明和 v5.1.0 相同。
- 回滾方式與資料相容性：直接回滾 v5.1.0 image。

## Acceptance criteria

- [x] AC-1：Given 有課表的比賽準備資料，When 顯示訓練分析，Then 表格與說明文字和拆分前相同。
- [x] AC-2：Given 模組，When 直接呼叫 `racePlanView`，Then 不需要 DOM；沒有課表時回傳 null，格式由注入的函式決定。
- [x] AC-3：Given 載入模組期間已有更新的請求，When 舊的請求完成，Then 不寫入課表。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/pace-analysis.test.cjs::SPEC-119 the weekly plan lays out backend targets, actual distance and status` |
| AC-2 | `unit_tests/frontend/pace-analysis.test.cjs::SPEC-127 the plan view module lays out a plan without the DOM and a stale render writes nothing` |
| AC-3 | `unit_tests/frontend/pace-analysis.test.cjs::SPEC-127 the plan view module lays out a plan without the DOM and a stale render writes nothing` |
