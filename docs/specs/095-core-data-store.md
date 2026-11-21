# SPEC-095：核心資料搬進 native store，讀取改走唯讀 view（全域狀態拆分第二階段）

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-094](094-core-data-single-writer.md)

## Problem

SPEC-094 讓核心資料只有一個寫入點，但資料本身仍是 `app-state.js` 的 7 個全域變數（`shoes`、`retiredShoes`、`monthlyMileages`、`runningGoal`、`stravaImports`、`spendingSummary`、`monthlySpending`）：

- 12 個 script 以裸名稱讀取，看不出哪些名稱是共享資料、哪些是區域變數。
- 狀態不在 native module 裡，無法在 Node 單獨測試，也擋不住讀取端就地修改陣列（只能靠靜態掃描）。
- 測試只能用 `let shoes = …` 這類全域宣告準備資料，和正式程式的資料流不同。

## Goals

- 狀態由 `runtime/core-data.mjs` 的 `createCoreDataStore()` 擁有；script 透過唯讀 view `coreData` 讀取（`coreData.shoes` 等），7 個全域變數移除。
- view 的屬性不能指定，陣列是凍結的複本：讀取端改寫或就地排序在執行時就丟 `TypeError`，呼叫端自己的回應陣列不受影響。
- `app-resources.js` 是唯一建立與更新 store 的地方（`useCoreDataStore()`、`applyCoreResource()`、登出重設）。
- `architecture-check` 拒絕替換 `coreData`、寫入它的欄位、就地修改陣列、重新宣告舊名稱，以及讀取已移除的全域變數。
- 前端測試以真正的 store 準備資料（`seedCoreData`），不再宣告全域變數。

## Non-goals

- 年份選擇（`selectedYear`、`selectedSpendingYear`）、主題、各功能的請求序號仍是 UI 狀態，留在原處。
- 不提供變更訂閱；畫面仍由既有的 `render(resource)`／`invalidatePanels()` 更新。
- 畫面與 API 行為不變。

## Proposed design

- `createCoreDataStore(initial)`：`initial` 只接受 `CORE_DATA_FIELDS`（未知欄位丟錯）；`view` 以 getter 暴露欄位並 `Object.freeze`；`apply(resource, value, options)` 以 `coreDataPatch()` 計算，只替換該資源的欄位（其他欄位保持同一個陣列）並凍結其複本；`reset()` 回到 `coreDataDefaults()`。
- `app-state.js` 宣告 `let coreData`，初始為與 `coreDataDefaults()` 相同的凍結佔位物件；`initializeDataResources()` 在任何資料到達前以 `useCoreDataStore(createCoreDataStore())` 換成 store 的 view。
- 12 個 script 的讀取改為 `coreData.<field>`（機械式改寫，不動物件 key、字串與註解）。
- `check_architecture.core_data_violations()` 取代 `core_data_writers()`：除了寫入規則，也找出沒有在該檔宣告為區域變數或參數、卻以裸名稱讀取舊全域變數的行。
- 測試 helper：`featureContext` 把 `{ shoes: [...] }` 這類 fixture 放進真正的 store，`context.seedCoreData(fields)` 合併替換欄位。

## Security and data isolation

- 只改前端狀態的保存方式；登出與帳號切換仍經 lifecycle 重設 store，資料只來自目前帳號的回應。

## Migration, rollout, and rollback

- Schema／資料 migration：無（schema 12 不變）。
- 上線與 smoke test：部署前自動快照；部署後 `release-check`。資產數量不變。
- 回滾方式與資料相容性：可直接回滾至 v4.27.1 image。

## Acceptance criteria

- [x] AC-1：Given 實際載入的 `app-lifecycle.js`、`app-state.js`、`app-resources.js`，Then 佔位 view 等於 `coreDataDefaults()`，7 個舊全域名稱都不存在；安裝 store 後 `applyCoreResource()` 只改該資源的欄位，登出重設回到預設值與未選年份。
- [x] AC-2：Given store 的 view，Then 指定欄位、`push`、排序都丟 `TypeError`，未知的初始欄位被拒絕；套用其他資源時保留原本的陣列；呼叫端的回應陣列不會被凍結；`reset()` 回到預設值。
- [x] AC-3：Given 目前的前端，Then 沒有違規；Given 替換 view、寫入欄位、就地排序、重新宣告舊名稱與讀取已移除的全域變數，Then architecture-check 逐行指出，區域變數、參數、物件 key 與註解不算。
- [x] AC-4：Given 既有的前端回歸測試，Then 全部以真正的 store 準備資料並通過。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/core-data.test.cjs::SPEC-095 scripts read core data through the store view, which only the bridge changes` |
| AC-2 | `unit_tests/frontend/core-data.test.cjs::SPEC-095 the store view is read-only and its shared arrays cannot change in place` |
| AC-3 | `unit_tests/test_architecture_boundaries.py::test_core_data_is_read_through_the_view_and_written_only_by_the_bridge`、`python3 scripts/task.py architecture-check` |
| AC-4 | `unit_tests/frontend/onboarding.test.cjs::SPEC-084 a new account sees the three steps only after its data loaded and they tick off in order`、`unit_tests/frontend/feature-operations.test.cjs::SPEC-023 overlapping full and mutation reloads reject stale resources and retain unrelated results`、`python3 scripts/task.py frontend-test` |
