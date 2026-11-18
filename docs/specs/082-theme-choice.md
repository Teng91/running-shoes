# SPEC-082：淺色／深色／跟隨系統

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-051](051-sports-tech-visual-refresh.md)

## Problem

- 主題只有一顆在亮色與暗色之間切換的按鈕，預設暗色，無法跟隨裝置的淺色／深色設定。

## Goals

- 側邊欄與登入／註冊頁都提供「淺色／深色／跟隨系統」三選一，目前選擇有標示；預設跟隨系統。
- 跟隨系統時，裝置切換淺色／深色會即時更新畫面與圖表。
- 開啟 App 的第一個畫面（啟動畫面）就依偏好顯示，不會閃一下另一種顏色。

## Non-goals

- 不改任何主題配色或圖表 token。
- 偏好只存在這台裝置（`localStorage`），不同步到帳號。

## Proposed design

- `app-state.js`：`themePreference`（`light`／`dark`／`system`，無效值視為 `system`）與實際顯示的 `currentTheme`。
- `app-core.js`：`resolveTheme` 依偏好與 `prefers-color-scheme` 決定顯示；`applyTheme` 存偏好、切換 `body.light-theme`、更新 `meta[name="theme-color"]` 與按鈕的 `aria-pressed`；`setThemePreference` 只在顯示的主題改變時重畫圖表；監聽 `matchMedia` 的 change 事件。`toggleTheme` 保留給瀏覽器測試強制重畫。
- 啟動 inline script 依同樣規則加上 `boot-light`（CSP hash 由 `build_frontend.py` 重新產生）。
- 側邊欄的 `.theme-choice` 分段按鈕取代原本的切換按鈕；手機版獨占一列。

## Security and data isolation

- 只存在瀏覽器的 `localStorage`，不送到伺服器；頁面 CSP 不變（仍只允許有 hash 的 inline script）。

## Migration, rollout, and rollback

- Schema／資料 migration：無。原本存 `light`／`dark` 的裝置維持原選擇；沒存過的裝置改為跟隨系統（原本預設暗色）。
- 上線與 smoke test：側邊欄有三個選項，切換後畫面與圖表跟著變。
- 回滾方式與資料相容性：可直接回滾到 v4.21.3 image；存成 `system` 的裝置在舊版會顯示暗色。

## Acceptance criteria

- [x] AC-1：Given 偏好為跟隨系統且裝置為淺色，When 套用，Then 顯示淺色、`theme-color` 與按鈕狀態正確並記住 `system`；選深色後重畫一次、重選同一個不重畫；無效值視為跟隨系統。
- [x] AC-2：Given 啟動畫面，When 沒有存過偏好或存了 `system`，Then 依裝置設定決定淺色；頁面有三個選項且舊的切換按鈕已移除。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/visual-theme.test.cjs::SPEC-082 the theme follows the system by default and remembers light, dark or system` |
| AC-2 | `unit_tests/frontend/visual-theme.test.cjs::SPEC-082 the theme follows the system by default and remembers light, dark or system` |
