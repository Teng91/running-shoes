# SPEC-094：前端核心資料只有一個寫入點（全域狀態拆分第一階段）

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-093](093-project-review-hardening.md)、[SPEC-090](090-module-decoupling.md)

## Problem

前端 38 個傳統 script 共用 `app-state.js` 宣告的全域變數。鞋款、退役鞋、月跑量、目標、Strava 匯入紀錄與支出這些核心資料，有 17 處分散在 7 個檔案直接寫入：

- `app-core.js` 與 `app-workspace.js` 各自寫一份「資源載入後怎麼放進 state」的規則，本機快取的月跑量不會像伺服器資料一樣挑選顯示年份。
- `app-dashboard.js` 每次 render 都就地排序 `shoes`，讀取端偷偷改了共享資料。
- 支出格式檢查、Strava 歷史、目標儲存各自直接指定全域變數；登出時的重設預設值寫在另一處，與宣告重複。

任何檔案都能改這些資料，出錯時很難追到是誰改的，也沒有測試能約束。

## Goals

- 新的 native module `frontend/runtime/core-data.mjs`（不碰 DOM、storage 或 HTTP）定義每種資源變成哪些 state 欄位：鞋款依購買日期排序成新陣列、月跑量挑選顯示年份、目標、Strava 匯入紀錄與支出摘要的格式檢查，以及重設預設值。
- `app-resources.js` 的 `applyCoreResource()`／`resetCoreData()` 是這些全域變數唯一的寫入點，只寫入規則傳回的欄位。
- `architecture-check` 拒絕其他 script 指定、解構指定、寫入屬性或就地修改（`sort`、`push` 等）這些全域變數。

## Non-goals

- 讀取端維持讀全域變數；改成注入式讀取與把狀態搬進 module 本身是後續階段。
- 年份選單（`selectedYear`、`selectedSpendingYear`）仍由各圖表模組管理，只有「月跑量載入時挑選年份」移入規則。
- 跑步紀錄（`runController`）、AI、月報等已有自己 controller 的狀態不在範圍內。
- 畫面與 API 行為不變。

## Proposed design

- `core-data.mjs` 匯出 `CORE_DATA_FIELDS`、`coreDataDefaults()`、`chooseMileageYear()` 與 `coreDataPatch(resource, value, options)`；資源為 `shoes`、`monthly`、`goal`、`strava-history`、`spending`（`null` 代表重新載入前清空），未知資源丟錯。
- `initializeDataResources()` 在任何資料到達前載入規則；`applyCoreResource()` 只對 `monthly` 傳入目前選擇的年份與服務日曆的年份。
- `app-core.loadData`、`app-workspace.applyLocalResource`、`app-goals.saveRunningGoal`、`app-spending`、`app-strava.loadStravaHistory` 與支出快取 hook 改呼叫 `applyCoreResource()`；`render()` 不再排序。
- `registerFeatureReset('dashboard-data')` 移到 `app-resources.js` 並使用 `coreDataDefaults()`；年份選擇的重設是 `app-state.js` 的 `dashboard-selection`。
- `scripts/check_architecture.core_data_writers()` 逐行掃描 `assets.json` 的 script（略過 `app-resources.js` 與 `app-state.js` 的宣告、註解與區域宣告）。

## Security and data isolation

- 只改前端狀態的寫入路徑；帳號切換時仍由 lifecycle 重設，資料仍只來自目前登入帳號的回應。格式不正確的支出或 Strava 紀錄不會寫入 state。

## Migration, rollout, and rollback

- Schema／資料 migration：無（schema 12 不變）。
- 上線與 smoke test：部署前自動快照；部署後 `release-check`。shell 多一個 native module 資產。
- 回滾方式與資料相容性：可直接回滾至 v4.27.0 image。

## Acceptance criteria

- [x] AC-1：Given 鞋款與月跑量資料，Then 規則傳回依日期排序的新陣列（不改原陣列），月跑量保留有效的年份、否則選最新年份、沒有資料時選今年。
- [x] AC-2：Given 各種資源，Then 規則只傳回該資源擁有的欄位，格式錯誤與未知資源被拒絕。
- [x] AC-3：Given 實際載入的 `app-lifecycle.js`、`app-state.js`、`app-resources.js`，Then 初始值等於 `coreDataDefaults()`，`applyCoreResource()` 只改傳回的欄位，登出重設回到預設值與未選年份。
- [x] AC-4：Given 目前的前端，Then 除了 `app-resources.js` 沒有 script 寫入核心資料；Given 指定、解構、屬性寫入與就地排序，Then architecture-check 逐行指出，讀取、比較、物件屬性、註解與區域宣告不算。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/core-data.test.cjs::SPEC-094 shoes arrive as sorted copies and monthly history keeps or picks the shown year` |
| AC-2 | `unit_tests/frontend/core-data.test.cjs::SPEC-094 each resource owns its fields and malformed payloads are refused` |
| AC-3 | `unit_tests/frontend/core-data.test.cjs::SPEC-095 scripts read core data through the store view, which only the bridge changes`（SPEC-095 起資料在 store 裡，改由這個測試涵蓋） |
| AC-4 | `unit_tests/test_architecture_boundaries.py::test_core_data_is_read_through_the_view_and_written_only_by_the_bridge`、`python3 scripts/task.py architecture-check` |
