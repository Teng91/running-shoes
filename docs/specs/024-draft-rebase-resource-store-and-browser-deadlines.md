# SPEC-024：草稿狀態重整、資料資源模組與瀏覽器期限

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：SPEC-023、ADR-0007

## Problem

鞋款移至退役的回應若保留新草稿，只更新 shoe snapshot 而未同步 mode／月跑量，下一次儲存會撤銷退役。
目標表單只保護目前 focus 的欄位，重繪會清掉已失焦的新內容。資料讀取身分、錯誤、快取失效仍混在 DOM adapter，
同資源重複讀取沒有合併，任一來源失敗會阻擋其他來源。PWA WebKit 卡住時可耗盡整個 browser job，診斷與 close 本身也缺少期限。

## Goals

- 鞋款成功回應重新建立 server baseline、mode 與 UI，只保留等待期間真正修改的欄位；後續儲存只傳 dirty fields。
- 目標草稿在重繪、失焦、背景讀取、等待儲存期間維持正確，換帳號清理。
- 原生資源模組統一 request ownership、session reset、同資源請求合併、成功快取、錯誤與 cache invalidation policy。
- 各資料來源獨立成功／失敗，不讓舊回應或別的來源成功掩蓋新資料／未恢復的錯誤。
- 瀏覽器引擎／階段、diagnostics、teardown 有期限；CI layout／CRUD／PWA 分開，可獨立重跑。
- 同步 README module map、SDD／ADR／測試策略與 SPEC-023 具名狀態轉移案例。

## Non-goals

- 不新增 AI 暱稱查詢、日誌標籤／搜尋、目標歷史或新 API。
- 不改 schema 3；驗證不修改正式資料，正式發布依使用者明確授權執行。

## Proposed design

- Shoe modal 保存已確認的 form baseline；成功時先套用 server 值與 mode，再還原操作期間 dirty fields／categories。
- form-operations native module 提供可重設的 draft baseline/reconcile/acknowledge；goal bridge 管理 DOM 與 session operation。
- resource-store native module 注入 session 和 cache invalidation hooks；以 resource + read key 合併 pending reads，mutation 使舊來源失效。
  每個結果含 ownership，可只接受一次；錯誤獨立保留。Classic resource bridge 註冊 cache hooks，core 僅組合 readers、apply 與 render。
- Browser harness 共用 deadline、engine watchdog、failure capture 與 bounded cleanup。錯誤文字先寫入，trace／screenshot 分別限時。
  外層 watchdog 在必要時終止整個 synthetic runner，避免無法結束的 browser 子程序拖到 job timeout。
- WebKit 離線 shell 保留 transport 中斷；API probe 在 headers 後截斷 HTTP body，完整讀取 JSON 並驗證 server 請求計數，使用 10 秒 deadline。Worker update 同時等待 update request／statechange，另有 20 秒外層期限。
- CI 三個 browser jobs 共用初始化步驟；diagnostic roundtrip 依賴 PWA job，失敗／取消也嘗試上傳已有診斷。

## Security and data isolation

- 每個 resource/cache 結果維持 session/epoch 檢查，reset 後舊請求不能回填另一帳號。
- 測試只用暫存 DB 與合成 browser context；diagnostics 不錄正式帳號或 credentials。
- 不以重試寫入處理 timeout；保留既有 CAS／idempotency／HTTP contract。

## Migration, rollout, and rollback

- Schema／資料 migration：無，維持 schema 3。
- 上線與 smoke test：frontend regressions、verify-all、architecture/security/docs、synthetic failure/deadline tests 與拆分後 CI；使用者於 2026-10-23 明確授權發布 v3.6.1。部署前依 README 建立異地備份並驗證 checksum／隔離還原；部署後執行匿名唯讀 release-check。
- 回滾方式與資料相容性：原 API 與 schema 3 相容，可部署已驗證的 v3.6.0 image（`registry.fly.io/running-shoes:v3.6.0-07b509f`）回滾，不回復舊 DB 快照。重新發布舊 frontend 來源仍須新 shell revision；驗證實際 image／schema／readiness 與匿名唯讀 smoke。

## Acceptance criteria

- [x] AC-1：Given 鞋款狀態移動成功且有新草稿，When 再儲存，Then 僅送出 dirty fields，狀態／月跑量與成功版本不被舊欄位撤銷。
- [x] AC-2：Given 目標新草稿或儲存中的新修改，When 重繪、成功或 session reset，Then 保留 dirty values、更新 baseline 並隔離舊操作。
- [x] AC-3：Given 同資源／key 並行讀取，When 無 mutation，Then 共用 pending read；mutation、key 或 session 改變時拒絕舊結果。
- [x] AC-4：Given 部分來源失敗，When 其他來源成功或重試，Then 正常資料仍套用、錯誤獨立保留，cache 只因相關異動失效。
- [x] AC-5：Given browser／trace／close 永不完成，When deadline 到期，Then 先保存 error，限時結束並回傳失敗，runner 不假通過。
- [x] AC-6：Given CI browser gate，When 某一 gate 失敗，Then 該工作可獨立重跑且保留已有診斷；合成 artifact roundtrip 仍驗證內容。
- [x] AC-7：Given 最新模組與具名 regression，When docs-check，Then README／SPEC／SDD／ADR／測試策略與實作一致。

## Test traceability

| AC | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/draft-resources.test.cjs::SPEC-024 shoe transitions preserve only new edits and retain the server state` |
| AC-2 | `unit_tests/frontend/draft-resources.test.cjs::SPEC-024 goal drafts survive redraw and save acknowledgements` |
| AC-3 | `unit_tests/frontend/draft-resources.test.cjs::SPEC-024 resources coalesce reads and reject superseded sessions and keys` |
| AC-4 | `unit_tests/frontend/draft-resources.test.cjs::SPEC-024 independent resource failures preserve successful data and relevant caches` |
| AC-5 | `unit_tests/frontend/browser-deadlines.test.cjs::SPEC-024 stuck capture and cleanup preserve the error and finish within deadlines`；`unit_tests/test_browser_runner.py::test_browser_watchdog_terminates_detached_descendants` |
| AC-6 | `unit_tests/test_task_runner.py::test_browser_jobs_are_independent_and_keep_timeout_diagnostics` |
| AC-7 | `unit_tests/test_docs_harness.py::test_current_document_contracts_are_valid` |

雙引擎整合：`python3 scripts/task.py frontend-e2e` 於 `unit_tests/frontend_drafts.cjs` 以合成 API／真實 DOM 驗證退役→保留暱稱→再儲存、目標失焦→切主題及等待儲存→修改→再儲存。

本機驗證：`python3 scripts/task.py verify-all` 通過，462 Python／95 Node／95.26% backend branch coverage，40 組版面、Chromium／WebKit E2E 及 PWA 無跳過；10 個 Agent evals 通過，合成 diagnostics 產生與內容驗證通過。拆分後 CI 的實際執行結果以該 commit 的 Actions run 為準。

遠端診斷驗證：首次拆分後的 CI 在 WebKit 離線 API probe 卡住時，以 120 秒 engine deadline 失敗並成功上傳 screenshot／trace／error；下載 trace 後定位裸 fetch，改為 headers 後截斷 body、完整讀取 JSON 與 server 計數斷言；Chromium／WebKit 本機回歸通過。
