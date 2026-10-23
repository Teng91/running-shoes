# ADR-0007：草稿重新基準化、原生資源模組與瀏覽器期限

- 狀態：Accepted
- 日期：2026-10-23
- 規格：[SPEC-024](../specs/024-draft-rebase-resource-store-and-browser-deadlines.md)
- 延伸：[ADR-0006](0006-form-operations-and-account-services.md)

## Context

只更新 CAS 版本不足以保護保留的鞋款草稿：狀態轉移成功後，舊 mode／月跑量仍可能被下次儲存送回。
目標只保護聚焦欄位也不足以辨識未儲存內容。Core 同時管理來源請求、錯誤與快取，難以合併讀取或獨立接受成功結果。
v3.6.0 tag 的一次 WebKit PWA 工作卡到 job timeout；原本 trace／close 沒有 deadline，可能連診斷都無法留下。

## Decision

- 鞋款編輯保存表單 baseline。寫入成功後先套用 server snapshot、mode 與 UI，再還原等待期間的新欄位／分類修改；下一次只送 dirty fields 與最新版本。
  保留的新建草稿仍屬新建操作。Goal 使用 native draft 的 reconcile／acknowledge，以值與 baseline 判斷修改，不依賴 focus。
- `runtime/resource-store.mjs` 注入 session 與 cache invalidation hooks，擁有來源 ticket、epoch、pending／成功值、獨立錯誤與 mutation policy。
  同資源／key 共用 pending promise；不同 key、mutation 或 session 拒絕舊結果。接受結果最多一次，避免重複 apply／失效。
- `app-resources.js` 註冊既有 feature cache adapters；`app-core.js` 組合 readers、套用有效結果、選擇月份並 render。
  保留 classic handlers 與 run controller；不引入 framework、global fetch 或另一份帳號狀態。
- 每個 browser engine／操作階段有 deadline。共用 capture 先同步保存 error，再分別限時 screenshot／trace；context 和 browser close 各自限時並依序嘗試。
  外層 Python watchdog 超時先落檔、再終止自己的子程序樹並回 124；POSIX 以程序 ancestry／身分辨識涵蓋另開 process group 的 browser。
- WebKit PWA 的離線 shell 保留 fixture transport 中斷；API probe 在 HTTP headers 後截斷 body，完整讀取 JSON 並檢查 server 請求計數，避免裸 fetch 在 headers 前 TCP 中斷後長期 pending。
  API probe／worker update 各有獨立 deadline，worker update 同時等待 update request 與 statechange，讓 timeout 直接成為測試失敗。
- Layout／CRUD／PWA CI jobs 共用鎖版 composite setup，但各自執行、失敗上傳及重跑。合成 artifact roundtrip 依賴 PWA，繼續驗證真實 trace 內容。

## Consequences

- Native runtime 可直接測試，且維持 DOM／transport 獨立；Classic bridge 仍需註冊功能快取，尚未將所有 state 移入 native modules。
- 來源讀取錯誤不再阻止其他成功來源套用；整批載入仍等待各來源有期限的 transport 結果後 render，並保留未恢復的獨立錯誤。
- Deadline 不會取消底層 Playwright promise；bounded close 與外層 process watchdog 負責最後收尾。完全卡死時可能只有文字診斷，不保證 trace／PNG。
- 分開 CI jobs 增加初始化次數，換取獨立重跑與更明確的失敗來源。所有診斷僅使用合成或匿名 context。
- Schema 維持 3，HTTP contract 不變；新 native module 與 bridge 仍列入 manifest，使用新 shell revision 3.6.1／v29。
