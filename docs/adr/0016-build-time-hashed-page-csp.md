# ADR-0016：建置時雜湊的頁面 CSP 與統一安全標頭

- 狀態：Accepted
- 日期：2026-11-13
- 規格：[SPEC-054](../specs/054-security-headers-and-page-csp.md)

## Context

頁面把登入 token 放在 `localStorage`，並呈現不可信的 LLM／搜尋 Markdown，卻沒有任何 Content-Security-Policy。
App shell 有三段必須先於 app bundle 執行的 inline script：首屏主題、非阻塞樣式表、開機逾時與重試。重試必須在
bundle 載入失敗時仍然可用，所以不能搬到外部檔案。
Shell 由 `build_frontend.py` 產生，並由 Service Worker 原子快取；離線啟動時，瀏覽器拿到的是快取裡的舊回應。

可行的作法有：

1. 後端在啟動時解析 `index.html` 算雜湊，放進 HTTP 標頭：執行期多一份 HTML 解析，測試用的前端目錄也要有對應檔案。
2. 每個請求產生 nonce：靜態 shell 被 Service Worker 快取，nonce 無法每次不同。
3. 允許 `'unsafe-inline'`：等於沒有限制 script。
4. 建置時計算雜湊，寫進 HTML 的 `<meta>` CSP：政策和它保護的 HTML 同時產生、同時被快取。

## Decision

- 採用方案 4。`build_frontend.py` 在其他替換完成後，對每段無屬性的 inline `<script>` 計算 SHA-256，填入模板最前面的
  `<meta http-equiv="Content-Security-Policy">`。帶屬性又沒有 `src` 的 inline script 會讓建置失敗；`--check` 擋下 HTML 與政策的漂移。
- Inline script 內容不得包含版號等會被改寫的值，所以樣式表載入器直接讀取 `<link>` 的 `href`。
- `<meta>` 無法表達的指令（`frame-ancestors`），以及 `nosniff`、`X-Frame-Options`、`Referrer-Policy`、
  `Cross-Origin-Opener-Policy`、`Permissions-Policy`，由 `SecurityHeadersMiddleware` 加在每個回應上。
  Header CSP 不放 `script-src`，以免影響 `/docs`。
- 前端與 API 同源，所以移除 CORS middleware。

## Consequences

- 修改模板中的 inline script 後必須執行 `build_frontend.py --write`，否則瀏覽器會擋下那段 script，`--check` 也會失敗。
- Inline 事件屬性不再有任何例外：SPEC-047 對樣式表 `onload` 的例外由本 ADR 取代。
- `style-src` 仍允許 `'unsafe-inline'`，因為產生的表格列與 SVG 使用 style 屬性；收緊它需要先移除這些屬性。
- 瀏覽器測試與部署後的 release-check 會收集 `securitypolicyviolation`，有任何違規就失敗。
- 其他網站的頁面無法再讀取 API 回應。日後若需要跨來源用戶端，必須以明確的來源 allowlist 重新設計，不能恢復 `*`。
