# SPEC-054：安全標頭與頁面 Content-Security-Policy

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[ADR-0016](../adr/0016-build-time-hashed-page-csp.md)、[SPEC-047](047-review-hardening-and-decoupling.md)、[SPEC-053](053-documentation-inventory-and-hygiene.md)

## Problem

- 登入 token 存在 `localStorage`，頁面又會呈現 LLM 與網路搜尋產生的 Markdown。`app-markdown.js` 的 allowlist 是唯一的防線：只要有一個 XSS 漏洞，就能執行任意 script 並讀走 token。
- 所有回應都沒有任何瀏覽器安全標頭：沒有 CSP、`X-Content-Type-Options`，也沒有禁止被 iframe 嵌入（可被 clickjacking）。
- `create_app` 安裝了 `CORSMiddleware(allow_origins=["*"])`。前端與 API 同源，根本不需要 CORS。目前因為認證用 Bearer token 而不用 cookie，所以不能被利用，但這是多開的一扇門。
- 頁面還留著 inline JavaScript：`index.html` 樣式表上的 `onload` 屬性（SPEC-047 測試明文列為例外），以及離線頁的 `onclick`。嚴格的 CSP 會擋下它們。

## Goals

- 頁面以 CSP 限制 script：只允許同源檔案，以及建置時以 SHA-256 雜湊放行的 inline script。inline 事件屬性、`eval`、外部 script、`object` 與 `<base>` 都被擋下。
- 每個 HTTP 回應帶上 `X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`frame-ancestors 'none'`、`Referrer-Policy`、`Cross-Origin-Opener-Policy` 與 `Permissions-Policy`。
- 移除 CORS，API 只接受同源呼叫。
- 頁面啟動行為不變：開機畫面立即顯示、樣式表不阻塞、啟動失敗時仍可按「重新載入」。
- 真實瀏覽器（CRUD E2E、40 組版面、部署後 release-check）只要出現 CSP 違規就失敗。

## Non-goals

- 不限制 inline style（`style-src` 保留 `'unsafe-inline'`）。產生的表格列與 SVG 大量使用 style 屬性，CSS 注入的風險也遠低於 script。
- 不設 HSTS：`fly.dev` 屬於整個 HSTS preload 的 `.dev` 頂級網域，Fly 也已強制 HTTPS。
- 不改 token 的儲存方式，仍存在 `localStorage`。CSP 是在 Markdown allowlist 之外的第二道防線。
- 不加 CSP 回報端點（`report-to`）。

## Proposed design

- **頁面 CSP（`<meta>`）**：
  - `scripts/build_frontend.py` 在完成其他替換之後，計算 `index.html` 中每段無屬性 `<script>` 的 SHA-256，填進模板最前面的 `<meta http-equiv="Content-Security-Policy">`。
  - 帶屬性又沒有 `src` 的 inline script 會讓建置失敗，因為它的雜湊無法可靠地維護。
  - 政策內容：`default-src 'self'; script-src 'self' <hashes>; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; worker-src 'self'; manifest-src 'self'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'self'`。
  - 因為 HTML 與政策一起產生，`--check` 會擋下兩者漂移；Service Worker 快取的舊 shell 也帶著自己的政策。
- **樣式表載入**：
  - 原本的 `onload` 屬性改成緊接在 `<link id="app-styles" rel="preload">` 後面的 inline script。它在 load 時把 `rel` 改成 `stylesheet`、設定 `data-ready` 並送出 `appstylesready`，與原本的行為相同。
  - 如果 parser 在 link 與 script 之間讓出執行權，preload 可能已經完成、load 事件已經觸發。這時以 `performance.getEntriesByName()` 判斷已完成，立即套用；以旗標保證只套用一次。
  - Script 內容不含版號，所以 PWA 測試改寫版號時雜湊不會改變。
- **離線頁**：`offline.html` 改成不需要 script 的 `<a class="retry" href="">`（空 href 會重新載入同一網址），並帶 `default-src 'none'` 的 CSP。
- **標頭**：
  - `backend.middleware.SecurityHeadersMiddleware` 是純 ASGI middleware，在 `http.response.start` 補上 `SECURITY_HEADERS`，回應已經設定的同名標頭不覆蓋。
  - Header CSP 只放 `<meta>` 無法表達的 `frame-ancestors 'none'`，以及 `base-uri 'none'`、`object-src 'none'`、`form-action 'self'`。不放 `script-src`，以免影響 `/docs` 的 Swagger UI。
- **MIME**：回應都帶 `nosniff`，所以 `create_app` 把 `.js`／`.mjs` 固定為 `text/javascript`、`.css` 為 `text/css`、`.webmanifest` 為 `application/manifest+json`，避免主機的 MIME 登錄（例如 Windows）把 script 變成 `text/plain`。
- **CORS**：移除 `CORSMiddleware`。PWA 測試模擬舊版 `Vary: Origin` 的部分保留，作為 Service Worker 忽略 `Vary` 的回歸測試。
- **瀏覽器驗證**：`scripts/browser_artifacts.cjs::trackCspViolations()` 以 `exposeBinding` 與 init script 收集每次導覽的 `securitypolicyviolation`。`frontend_e2e.cjs`、`frontend_layout.cjs` 與 `release_browser.cjs` 在結束時斷言沒有違規。

## Security and data isolation

- 不改任何 query、帳號範圍或資料。CSP 限制已載入頁面能執行的程式；`frame-ancestors` 防止被其他網站嵌入。
- 移除 CORS 後，其他網站的頁面即使取得 token 也無法讀取 API 回應；同源的前端不受影響。
- Release 檢查仍是匿名、唯讀，CSP 違規訊息只含指令名稱、被擋的網址與行號，不含使用者資料。

## Migration, rollout, and rollback

- Schema／資料 migration：無，schema 7 不變。
- 上線與 smoke test：
  - Asset 4.12.0／shell v62：`index.html` 與 `offline.html` 改變，已安裝的 PWA 透過 SPEC-049 的提示更新。
  - 實作時，公司代理擋下了 Playwright 的下載，所以先以本機 headless Edge（Chromium）手動驗證：
    - 對照頁中沒有雜湊的 inline script 與外部樣式表會被擋下並回報違規。
    - 正式頁面匿名載入、登入、切換四個分頁（含圖表）、開啟跑鞋視窗、切換主題、呈現 Markdown、Service Worker 接管，以及離線頁，全程沒有 CSP 違規或頁面例外。
    - 分支 CI（GitHub Actions run 43420497443）在 Chromium／WebKit 通過 `frontend-e2e`、40 組 `frontend-layout` 與 `frontend-pwa`，沒有 CSP 違規。
  - CI 的 `frontend-e2e` 與 `frontend-layout` 在 Chromium／WebKit 確認沒有 CSP 違規。
  - 部署後 `release-check` 在正式站再確認一次。
- 回滾方式與資料相容性：部署 v4.11.0 image 即恢復舊的 CORS 與無安全標頭。舊 shell 不含 CSP，與新後端相容。

## Acceptance criteria

- [x] AC-1：Given 產生的 `index.html`，When 讀取頁面 CSP，Then 它位於第一個 script 之前；`script-src` 只有 `'self'` 與每段 inline script 實際內容的 SHA-256，沒有 `'unsafe-inline'`、`'unsafe-eval'` 或外部來源；帶屬性的 inline script 會讓建置失敗。
- [x] AC-2：Given 模板、產生的列與離線頁，When 掃描 markup，Then 沒有任何 inline 事件屬性或 `javascript:` 網址；離線頁不含 script，以空 href 連結重新載入。
- [x] AC-3：Given 非阻塞樣式表載入，When preload 在 script 執行前或後完成，Then 都只套用一次：`rel` 變成 `stylesheet`、`data-ready` 為 `true`，`appstylesready` 只送出一次。
- [x] AC-4：Given JSON、頁面、SPA fallback、靜態 script、401、404、422 與 413 回應，When 回應送出，Then 都帶齊安全標頭；回應自己設定的同名標頭不被覆蓋。
- [x] AC-5：Given 其他網站的 Origin 發出簡單請求或 preflight，When 呼叫 API，Then 回應沒有任何 `Access-Control-Allow-*` 標頭。
- [x] AC-6：Given `nosniff`，When 提供 `.js`、`.mjs` 與 `.css`，Then Content-Type 固定為 `text/javascript` 與 `text/css`。
- [x] AC-7：Given 真實的 Chromium／WebKit，When 執行 CRUD E2E、40 組版面與部署後 release-check，Then 只要出現 CSP 違規，檢查就失敗。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/security-policy.test.cjs::SPEC-054 the shell CSP allows inline scripts only by the hash of their exact text`、`unit_tests/test_security_headers.py::test_generated_shell_policy_hashes_exactly_its_inline_scripts`、`unit_tests/test_security_headers.py::test_inline_scripts_with_attributes_are_rejected_instead_of_silently_unhashed` |
| AC-2 | `unit_tests/frontend/security-policy.test.cjs::SPEC-054 markup, generated rows and the offline page carry no inline handlers or javascript: URLs`、`unit_tests/frontend/presentation-shell.test.cjs::SPEC-047 markup declares UI actions instead of inline JavaScript handlers` |
| AC-3 | `unit_tests/frontend/security-policy.test.cjs::SPEC-054 the stylesheet loader applies the preload exactly once, even if its load event already fired` |
| AC-4 | `unit_tests/test_security_headers.py::test_every_response_kind_carries_the_hardening_headers`、`unit_tests/test_security_headers.py::test_security_headers_do_not_override_a_response_that_sets_its_own` |
| AC-5 | `unit_tests/test_security_headers.py::test_the_api_is_same_origin_only` |
| AC-6 | `unit_tests/test_security_headers.py::test_scripts_and_modules_keep_javascript_media_types_under_nosniff` |
| AC-7 | `unit_tests/frontend/security-policy.test.cjs::SPEC-054 every real-browser check fails on a Content-Security-Policy violation`、`python3 scripts/task.py frontend-e2e`、`python3 scripts/task.py frontend-layout` |
