# SPEC-137：前端 review 修正：主題 token、死碼、跑鞋表單、共用標記與模組預先載入

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-051](051-sports-tech-visual-refresh.md)、[SPEC-054](054-security-headers-and-page-csp.md)、[SPEC-135](135-feature-registries.md)

## Problem

2026-11-27 的前端 review 找到四類問題，逐條核對後確認以下屬實：

- **死碼**：
  - 沒有元素使用 `.inline-add`、`.metric-source`、`.agent-config input[type="text"]` 這三組 CSS 規則。
  - `--cyan`、`--green`、`--yellow`、`--radius-sm`、`--boot-card` 這幾個 token 定義了但沒有地方用。
  - 產品程式沒有呼叫 `fetchRunPages()`。
  - `.sidebar-actions` 的兩欄 grid 只剩一顆按鈕。
- **淺色主題**：
  - 新手引導「目前步驟」用螢光色 `--accent`，對淺色卡片的對比只有 1.1:1。
  - `--warning` 從未定義，所以永遠退回 `#ffb020`，對白底的對比是 1.8:1。
  - 其他橘色警示字的對比是 2.4:1；Strava 徽章寫死 `#ff7a3d`，對比是 2.2:1。
  - 錯誤文字用 `--red`，沒有用淺色主題準備好的 `--danger-text`。
- **CSS 重複**：
  - 已經有一條全域 `[hidden] { display: none !important; }`，各檔仍另外寫了 14 條同樣的規則。
  - Strava 摘要與下拉選單的規則重複宣告，後一條還蓋掉前一條的 `max-width`。
  - 啟動畫面的 CSS 幾乎整段重複 inline critical style。
- **介面與標記**：
  - **跑鞋視窗的排版**：第一列兩欄放了三個欄位，「鞋款」單獨掉到下一列。
  - **跑鞋視窗的寫法**：
    - 視窗不是 `<form>`，所以按 Enter 不會儲存。
    - 按鈕綁 `.onclick`。
    - 點背景關閉靠自己的監聽，和 SPEC-135 的登記表不一致：登記寫不會關，實際上會關。
  - **過時文案**：新手引導還寫「跑量與目標」頁；AI 對話寫「今日」免費模型，月報寫「本日」。
  - **重複標記**：
    - 隱私說明在登入與註冊頁各寫一次。
    - 品牌 logo 的 SVG 重複 4 次。
    - 樣板裡有 19 處 inline `style`。
- **啟動**：9 個原生模組都在啟動時以 `import()` 依序載入，兩個 initializer 內又各自連續 await 兩個獨立模組。

## Goals

- 移除上述死碼與重複規則，CSS 使用的每個 token 都有定義、定義的都有使用。
- 淺色主題的警示、錯誤、Strava 與新手引導文字對比至少 4.5:1；深色主題外觀不變（錯誤字改用既有的 `--danger-text`）。
- 跑鞋視窗改成 `<form>`：按 Enter 儲存，按鈕與關閉都走 `registerUiActions`／`registerDialog`；暱稱獨立一列，品牌與鞋款並排。
- 樣板沒有 inline style；隱私說明與 logo 各只有一份來源。
- 每個原生模組在 `<head>` 預先載入，URL 與 `import()` 完全相同；同一個 initializer 裡獨立的模組一起載入。

## Non-goals

- **不收斂響應式斷點**（380／700／760／800／900／1100 px）：
  - 斷點一改，中間寬度的版面就會變，版面測試也有依寬度判斷的斷言。
  - 換到的只是維護上的整齊，使用者看不到差別。
- **不延後載入 Chart.js 與 marked、不合併 app-*.js**：
  - 登入後預設的「跑步日誌」就要畫圖，延後載入只對登入頁有幫助。
  - 延後載入還要處理「圖表函式庫還沒到就先重繪」的情況。
  - 合併檔案會改動 Service Worker 清單、release check 與直接讀原始檔的測試。
- `cross_script_names`（153）是持續收斂的方向，這次不處理。
- 不改 `app.js` 裡 initializer 的先後順序：它們有初始化時的相依；模組預先載入後，依序 await 只剩查表的成本。

## Proposed design

- **CSS**：
  - 刪除死規則與未使用的 token。
  - 新增 `--warning-text`（深色 `#ff8a1f`，淺色 `#a35200`）與 `--strava-text`（深色 `#ff7a3d`，淺色 `#b93d00`）。
  - 警示字、Strava 徽章、錯誤字與新手引導改用 token；寫死的 `#0b1015` 改用 `--accent-ink`。
  - 只保留全域的 `[hidden]` 規則。
  - `01-foundation.css` 的啟動畫面只留 safe-area padding 與主題色，版面與動畫只寫在 inline critical style。
- **跑鞋視窗**：
  - `shoe-modal.html` 外層改成 `<form class="modal" data-submit="save-shoe" novalidate>`，由 app 自己驗證，維持原本不經瀏覽器驗證的行為。
  - 按鈕加上 `type` 與 `data-click`，刪除與移動按鈕以 `hidden` 切換。
  - `app-shoes.js` 不再綁 `.onclick`。對話框改登記 `registerDialog('modal', { close, backdrop: true })`，維持原本點背景會關的行為。
- **樣板**：
  - 隱私說明移到 `templates/auth-privacy.html`，登入與註冊頁用 `<!-- include:auth-privacy.html -->` 引入。
  - logo 改成一個 `<symbol id="brand-mark">`，四處以 `<use>` 引用。
  - inline style 改成 class：`.btn-block`、`.auth-submit`、`.auth-switch`、`.modal.export-dialog`、`.modal.run-dialog`、`.strava-intro`。
  - 登入畫面、主畫面與註冊、重設密碼表單改用 `hidden` 屬性，`app-auth.js`、`app-account.js` 跟著改。
- **文案**：新手引導改成「訓練分析」頁，AI 對話與月報都叫「今日免費模型」。
- **死碼**：刪除 `fetchRunPages()` 與只測它的測試；`fetchRunPage()` 原本就有測試。
- **啟動**：
  - `build_frontend.py` 依 `assets.json` 的 `modules` 產生 `<link rel="modulepreload" href="/runtime/x.mjs?v=版本">`，放在樣式載入 script 之後。版本以 `encodeURIComponent` 相同的規則編碼。
  - `initializeFeatureLifecycle`、`initializeDataResources` 以 `Promise.all` 一起載入兩個模組。
- `cross_script_names` 維持 153。

## Security and data isolation

- 沒有 API、資料或權限變更。CSP 不變：modulepreload 是同源 script，`style-src` 原本就允許。這次移除 inline style，以後要收緊時少一個障礙。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：`release-check`；登入頁、跑鞋表單（Enter 儲存、點背景關閉）、淺色主題的新手引導與 Strava 衝突提示。
- 回滾方式與資料相容性：直接回滾 v5.3.1 image，沒有保存格式變更。

## Acceptance criteria

- [x] AC-1：Given 樣式與樣板，When 檢查 token，Then CSS 用到的每個 token 都有定義（或由 script 在執行時設定），定義的都有用到，review 列出的未使用 token 不存在。
- [x] AC-2：Given 淺色主題，When 計算對比，Then 警示、錯誤、`--accent-light` 文字對卡片至少 4.5:1，Strava 徽章對自己的底色至少 4.5:1；樣式不再寫死 `#0b1015`、`#ff7a3d` 或引用未定義的 `--warning`。
- [x] AC-3：Given 死碼與重複規則，When 檢查，Then `.inline-add`、`.metric-source`、文字輸入框規則、`fetchRunPages` 不存在，`[hidden]` 只宣告一次，啟動畫面的版面只寫在 inline style。
- [x] AC-4：Given 跑鞋視窗，When 在欄位按 Enter、按刪除／移動／取消或點背景，Then 經 `data-submit`／`data-click`／對話框登記處理，`app-shoes.js` 沒有 `.onclick` 或 `style.display`；暱稱獨立一列，品牌與鞋款同列。
- [x] AC-5：Given 樣板，When 產生頁面，Then 沒有 inline style，隱私說明與 logo 各一份來源，登入／主畫面以 `hidden` 切換，文案是「訓練分析」與「今日免費模型」。
- [x] AC-6：Given 頁面，When 載入，Then 每個原生模組以與 `import()` 相同的 URL 預先載入，且樣式載入 script 仍最先執行。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/review-cleanup.test.cjs::SPEC-137 every color token the styles use is defined, and every defined one is used` |
| AC-2 | `unit_tests/frontend/review-cleanup.test.cjs::SPEC-137 light-theme text that used fixed or volt colors is readable` |
| AC-3 | `unit_tests/frontend/review-cleanup.test.cjs::SPEC-137 unused rules and functions are gone and [hidden] is declared once` |
| AC-4 | `unit_tests/frontend/review-cleanup.test.cjs::SPEC-137 the shoe form saves with Enter and closes only through the registries`、`unit_tests/frontend/registries.test.cjs::SPEC-135 every dialog registers how it closes; Escape and backdrop clicks go through the registry` |
| AC-5 | `unit_tests/frontend/review-cleanup.test.cjs::SPEC-137 templates carry no inline styles, and the sign-in screens share one notice and one mark`、`python3 scripts/task.py frontend-layout`（登入、註冊、重設密碼表單在每種寬度的版面） |
| AC-6 | `unit_tests/frontend/review-cleanup.test.cjs::SPEC-137 every native module is preloaded at the URL its import builds`、`python3 scripts/task.py frontend-pwa` |
