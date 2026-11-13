# SPEC-051：運動科技風視覺改版

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-007](007-sidebar-workspace-layout.md)、[SPEC-016](016-frontend-alignment.md)、[SPEC-042](042-run-log-tiles-distance-colors-and-ai-tab.md)

## Problem

介面用的是通用的靛藍色深色儀表板樣式：同一種卡片、emoji 分頁圖示（🏃👟📊✨）、系統字體的數字、到處都是同一個 `#6366f1`。使用者覺得「很陽春」，看不出是一個跑步與裝備的工具。

顏色也分散在程式裡：圖表把 `#6366f1`、`#22c55e`、`rgba(99,102,241,.45)` 等色碼直接寫在 JS，亮色主題只能沿用暗色的顏色。例如跑鞋表格「生命進度」的淺綠文字（`#4ade80`）在白底上幾乎看不見。

## Goals

- 一套可辨識的運動科技視覺：碳黑底加細格線，螢光黃綠（volt `#c8ff3c`）做主色與「距離／行動」，青色做「金額／目前／次要數列」，DIN 風格的數字字體，斜線「速度條」當共用標記。
- 暗色與亮色主題都由 CSS token 定義，圖表、跑鞋磨耗色階、熱力圖與日曆都讀同一組 token，亮色主題不再出現看不清楚的螢光文字。
- 分頁、品牌與開機畫面改用線條 SVG，取代 emoji。
- 不改任何版面幾何：44／36px 控制項、248px 側欄、手機底部分頁列、卡片欄數與對齊規則全部維持，`frontend-layout` 的 40 組版面照常通過。

## Non-goals

- 不改資料、API、計算或任何功能流程。
- 不換 PWA 主畫面圖示（`frontend/icons/*.png` 是既有美術稿）。
- 不引入外部字型或 CDN；數字字體使用平台內建（iOS／macOS 的 DIN Alternate、Windows 的 Bahnschrift），沒有時回退系統字體。
- SPEC-042 的距離分布五色（紅、黃、綠、藍、紫）與各品牌色不變。

## Proposed design

- **Token**（`frontend/css/01-foundation.css`）：`:root` 是暗色，`body.light-theme` 覆寫同一組名稱。除了既有的 `--bg`、`--card`、`--text` 等，新增：
  - `--accent-ink`（volt 底上的深色字）、`--accent-line`（線條與框，亮色主題改深綠）、`--accent-light`（強調文字，亮色主題 `#4a7400`）。
  - 圖表：`--chart-1`（距離）、`--chart-1-soft`、`--chart-1-fill`、`--chart-2`（金額與「目前」）、`--chart-warn`、`--chart-line`（平均線）、`--chart-muted`、`--chart-track`。
  - 磨耗色階 `--wear-1`…`--wear-5`、熱力圖 `--heat-0`…`--heat-4` 與 `--heat-rgb`、字體 `--font-num`／`--font-mono`。
- **圖表**：所有原本寫死的顏色改成 `getThemeColor(token, 暗色預設值)`；`progressColor()` 回傳磨耗色階 token。`app-charts.js` 設定 Chart.js 的全域數字字體與碳黑 tooltip（兩個主題都可讀）。年度對比圖的強調年份改用 `--chart-1`。切換主題時沿用既有的 `invalidatePanels()` 重畫。
- **日曆**：每天的格子改帶 `style="--day-load:N"` 與 `has-run` class，由 CSS 畫出依距離增高的 volt 漸層與底線，不再在 JS 寫入 `rgba(34,197,94,…)`。
- **HTML**（`frontend/templates/index.html`）：分頁圖示改成 24px 線條 SVG，標籤 `<span>` 仍是按鈕最後一個子元素（手機標題沿用它）。品牌、登入與開機畫面使用同一個「速度線＋箭頭」標誌。區塊標題加上 `data-eyebrow` 英文小標（例如 `ANNUAL GOAL`），跑步日誌與月報的 hero 以 `data-mark` 放大描邊字。這兩種裝飾以 CSS `content: … / ""` 排除在無障礙名稱外。
- **安全的裝飾**：分頁淡入只用 opacity；手機標題列不使用 `backdrop-filter`／`transform`，因為固定在底部的分頁列是它的子元素，這類屬性會讓 `position: fixed` 改以標題列定位。
- 主題按鈕與「刷新模型列表」改用單色符號（☀︎／☾／↻），`theme-color`、manifest 與離線頁同步改成碳黑。

## Security and data isolation

- 純前端呈現，不新增查詢、mutation、API 欄位或外部資源；不涉及 secret 或使用者資料。
- `data-eyebrow`／`data-mark` 都是模板中的固定文字，不放任何使用者輸入。

## Migration, rollout, and rollback

- Schema／資料 migration：無，schema 7 不變。
- 上線與 smoke test：
  - Asset 4.10.0／shell v60；PWA 透過 SPEC-049 的更新提示載入新樣式。
  - 部署後在手機與桌面各切換一次亮／暗主題，確認四個分頁、跑鞋彈窗與 AI 對話的配色，以及圖表在切換後重畫。
- 回滾方式與資料相容性：部署 v4.9.0 image 即恢復舊樣式；沒有資料或 API 變更。

## Acceptance criteria

- [x] AC-1：Given 暗色或亮色主題，When 繪製任何圖表或跑鞋磨耗色，Then 顏色來自該主題定義的 token；兩個主題都定義了圖表讀取的每個 token，程式中不再寫死舊的靛藍／綠色。
- [x] AC-2：Given 跑步月曆，When 某天有跑步，Then 格子以 `has-run` 與 `--day-load` 呈現距離強度，不寫入 inline 顏色；今天仍有獨立標示。
- [x] AC-3：Given 側欄與手機分頁列，When 顯示，Then 四個分頁使用線條 SVG 圖示且標籤仍是最後一個 span；品牌與開機畫面使用 SVG 標誌；英文小標與描邊字不進入無障礙名稱。
- [x] AC-4：Given 新的裝飾樣式，When 在 10 種尺寸、亮／暗主題下檢查四個分頁、彈窗與控制項，Then 版面幾何與改版前相同：沒有溢出、44／36px 控制項、手機分頁列固定在底部。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/visual-theme.test.cjs::SPEC-051 every theme token the charts read is defined for dark and light themes`、`unit_tests/frontend/visual-theme.test.cjs::SPEC-051 shoe wear colors follow the theme ramp`、`unit_tests/frontend/trends.test.cjs::SPEC-038 trends render a Monday-first heatmap, weekly spikes and the goal pace note` |
| AC-2 | `unit_tests/frontend/visual-theme.test.cjs::SPEC-051 calendar days carry their distance load instead of an inline color` |
| AC-3 | `unit_tests/frontend/visual-theme.test.cjs::SPEC-051 navigation and brand use line icons, and English eyebrows stay decorative` |
| AC-4 | `unit_tests/frontend/visual-theme.test.cjs::SPEC-051 decoration never re-anchors the fixed phone tab bar or shifts measured layout`、`python3 scripts/task.py frontend-layout` |
