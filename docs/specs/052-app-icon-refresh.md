# SPEC-052：主畫面與分頁圖示改版

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-051](051-sports-tech-visual-refresh.md)

## Problem

SPEC-051 把介面改成碳黑底配螢光黃綠（volt），但刻意沒有換圖示：

- PWA 主畫面圖示與 iOS `apple-touch-icon` 仍是靛藍色跑鞋配綠色進度環。
- 瀏覽器分頁的 `favicon.svg` 仍是紫色「R」字。

所以打開 App 後是新風格，主畫面與分頁上卻還是舊的品牌樣子。

## Goals

- 主畫面圖示、iOS 圖示與分頁圖示都改用介面內同一個「速度線＋箭頭」標誌，配色與 SPEC-051 一致：碳黑底、volt 標誌、青色「目前」標記。
- 主畫面圖示保留「磨耗進度環」的概念：暗色軌道、volt 進度與一小段青色。
- Android maskable 裁切（最小為半徑 40% 的圓）不會切到進度環或標誌；iOS 圖示為不透明的滿版方形。
- 圖示有可維護的向量來源，PNG 可以從來源重新產生。

## Non-goals

- 不改 App 名稱、manifest 顏色或任何介面樣式。
- 不為已加入 iOS 主畫面的捷徑自動換圖示：iOS 只在「加入主畫面」時取得圖示，要刪除捷徑再加入一次。

## Proposed design

- **向量來源** `frontend/icons/app-icon.svg`（512×512）：
  - 背景：滿版碳黑 `#07090c`，加上細格線與兩處柔光（左上 volt、右下青色）。
  - 進度環：半徑 182、線寬 18，外緣 191px，落在 maskable 安全區（204.8px）內。
  - 中央標誌：與 `index.html` 側欄品牌標誌相同的四條路徑，放大 9.5 倍並帶 volt 光暈。
- **產生 PNG**：`node scripts/render_icons.cjs [輸出目錄]` 以 Playwright Chromium 在各尺寸直接繪製向量，輸出 `icon-512.png`、`icon-192.png`、`apple-touch-icon.png`（180）。舊的 `app-icon-source.png`（靛藍點陣稿）移除。
- **分頁圖示**：`favicon.svg` 改為碳黑圓角方形配 volt 標誌。模板先宣告 `<link rel="icon" type="image/svg+xml" href="/favicon.svg">`，再以 `sizes="192x192"` 的 PNG 當不支援 SVG 圖示的瀏覽器的備援。
- **快取**：圖示屬於 app shell 預先快取的靜態檔，所以 asset 升到 4.11.0／shell v61，讓已安裝的 PWA 透過 SPEC-049 的更新提示取得新檔。

## Security and data isolation

- 只換靜態圖片與模板中的固定 `<link>`，不涉及使用者資料、query、API、secret 或外部資源。
- `render_icons.cjs` 是本機開發工具，只讀取 repo 內的 SVG，不在 CI 或正式環境執行。

## Migration, rollout, and rollback

- Schema／資料 migration：無，schema 7 不變。
- 上線與 smoke test：
  - Asset 4.11.0／shell v61。
  - 部署後確認正式站的 `/favicon.svg` 與 `/icons/icon-192.png` 是新圖示。
  - Android 的主畫面圖示會在 Chrome 下次檢查 manifest 時更新（可能需要數天）；iOS 需刪除捷徑後重新「加入主畫面」。
- 回滾方式與資料相容性：部署 v4.10.0 image 即恢復舊圖示；沒有資料或 API 變更。

## Acceptance criteria

- [x] AC-1：Given PWA manifest 與 iOS 圖示，When 讀取宣告的每個圖示，Then 檔案是對應宣告尺寸的 PNG（192、512、180），manifest 圖示可做 maskable 裁切，來源 SVG 的標誌路徑與介面品牌標誌相同，且整個進度環落在半徑 40% 的安全區內。
- [x] AC-2：Given 瀏覽器分頁，When 載入頁面，Then 優先使用 volt 標誌的 `favicon.svg`，並有 192px PNG 備援；新圖示都在 app shell 預先快取清單中。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/visual-theme.test.cjs::SPEC-052 home-screen icons are rendered at their declared sizes from the volt mark source` |
| AC-2 | `unit_tests/frontend/visual-theme.test.cjs::SPEC-052 the browser tab uses the volt SVG mark with a PNG fallback`、`python3 scripts/task.py frontend-pwa` |
