# SPEC-059：在安全時自動套用新版

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-049](049-pwa-update-prompt.md)、[SPEC-027](027-recoverable-account-workspace.md)、[SPEC-048](048-push-to-main-deploy-and-release.md)

## Problem

- SPEC-049 起，新版裝好後只顯示「有新版本」提示，必須按「立即更新」才重新載入。
- 維護者電腦上的分頁好幾天沒關，2026-11-16 發現仍停在 v4.11.0，中間錯過 v4.12.0 與 v4.13.0。每次部署都要在每台裝置各按一次。
- 當初不自動重新載入，是因為重新整理會清掉記憶體裡的 AI 對話，也可能打斷正在進行的操作。

## Goals

- 新 shell 啟用後，在使用者不會失去任何東西的時候自動重新載入：
  - App 在背景。
  - 回到前景後還沒有任何點擊或按鍵。
  - 已閒置 5 分鐘。
- 以下情況先不重新載入，每分鐘再檢查一次：AI 正在回答、月報產生中、有彈窗或行內編輯開著、有請求還沒完成、AI 輸入框或顯示中的登入表單還有文字。
- 使用中的畫面照常顯示提示，可按「立即更新」馬上換。
- 完成的 AI 對話在重新載入後保留，只限同一分頁、同一帳號。
- 自動重新載入後若仍不是新版，不反覆重整。

## Non-goals

- 不改 service worker 的安裝、驗證與啟用流程（SPEC-018／049）。
- 不保存串流到一半或失敗的 AI 回答、來源卡片與工具狀態；只保存完成的問答文字。
- 不跨分頁或跨裝置同步 AI 對話。
- 已在使用舊版的裝置無法被遠端強制更新：第一次升到這一版仍需手動更新。

## Proposed design

- **`frontend/app-updates.js`**
  - `initializeAppUpdates()` 記錄最後一次 `pointerdown`／`keydown` 時間，以及頁面變為可見的時間（`visibilitychange`、bfcache `pageshow`）。
  - 收到不同版本時記下 `pendingVersion`、顯示提示，並呼叫 `tryApplyUpdate()`：
    - 頁面隱藏、可見後沒有輸入，或最後輸入已滿 5 分鐘，而且 `appUpdateBusy()` 為 false 時，寫入 `sessionStorage['app-update-attempt']` 後重新載入。
    - 否則 60 秒後再試；可見度改變時也再試。
  - 同一分頁已為同一版本嘗試過時不再自動重新載入（只留提示）；載入到該版本時清除紀錄。
  - `appUpdateBusy()` 讀取 `agentController`、`reportGenerationController`、`activeHttpRequests`、`inlineEditors`、`.modal-overlay.active`、`#agent-input` 與顯示中的 `#auth-view` 輸入框。
  - 可見度、焦點與連線的檢查時機（SPEC-049）不變，`visibilitychange` 同時負責檢查與套用。
- **`frontend/app-agent.js`**：
  - `saveAgentChat()` 在回答完成與重設對話時，把最近 20 輪存成 `sessionStorage['agent-chat']`（`{user, history}`）。
  - `restoreAgentChat()` 只在帳號相同時還原：問題以文字、回答以既有的安全 Markdown renderer 顯示；格式錯誤或帳號不同就刪除。
- **`frontend/app.js`**：已登入啟動時在 `showAppView()` 之後呼叫 `restoreAgentChat()`。登入、登出與換帳號會經由 `resetAgentChat()` 清除。
- 提示文字改為「App 閒置或切到背景時會自動更新；表單草稿與 AI 對話都會保留」。

## Security and data isolation

- AI 對話只存在目前分頁的 `sessionStorage`：關閉分頁即消失，不寫入 `localStorage` 或 IndexedDB，其他分頁讀不到。
- 還原時比對 `currentUser`，登出或換帳號時清除，不會把前一位使用者的對話顯示給下一位。
- 回答內容仍經過 `renderMarkdown()` 的 allowlist，問題以 `textContent` 顯示，不新增 XSS 面；頁面 CSP 不變。
- 不新增任何網路請求或 API。

## Migration, rollout, and rollback

- Schema／資料 migration：無，schema 8 不變。
- 上線與 smoke test：
  - Asset 4.14.0／shell v64。
  - 舊版頁面仍依 SPEC-049 只顯示提示，所以第一次升到這一版要手動更新；之後的部署會自動套用。
  - 上線後保持 App 開著、切到背景再回來，下一次部署應自動換成新版。
- 回滾方式與資料相容性：部署 v4.13.0 image 即回到只提示；分頁裡的 `agent-chat` 會被舊版忽略。

## Acceptance criteria

- [x] AC-1：Given 已啟用的新 shell，When 頁面可見但沒有任何輸入、頁面切到背景，或最後輸入已滿 5 分鐘，Then 自動重新載入一次並記錄嘗試的版本；使用中的可見頁面只顯示提示。
- [x] AC-2：Given AI 正在回答、月報產生中、請求未完成、行內編輯或彈窗開著、AI 輸入框或登入表單有文字，When 頁面切到背景，Then 不重新載入；工作結束後的下一次檢查才重新載入。
- [x] AC-3：Given 同一分頁已為某版本自動重新載入過卻仍是舊版，When 再收到該版本，Then 只顯示提示不自動重整，手動「立即更新」仍可用；載入到該版本時清除紀錄。
- [x] AC-4：Given 完成的 AI 問答，When 重新載入同一分頁，Then 同一帳號看到相同的對話並可接續；帳號不同、資料格式錯誤或重設對話時不還原並清除。
- [x] AC-5：Given 真實 Chromium／WebKit 的 service worker 升級，When 使用者剛操作過頁面，Then 先顯示提示且維持舊版；頁面切到背景後自動換成新版 shell。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/updates.test.cjs::SPEC-059 an untouched, backgrounded or idle app switches to the new version by itself` |
| AC-2 | `unit_tests/frontend/updates.test.cjs::SPEC-059 work in progress postpones the automatic update until it is safe` |
| AC-3 | `unit_tests/frontend/updates.test.cjs::SPEC-059 an automatic reload that missed the new version falls back to the prompt` |
| AC-4 | `unit_tests/frontend/updates.test.cjs::SPEC-059 completed AI turns survive a reload for the same account only` |
| AC-5 | `unit_tests/frontend/statistics-lifecycle.test.cjs::SPEC-049 a newer shell shows an update prompt and reloads only after confirmation`、`python3 scripts/task.py frontend-pwa` |
