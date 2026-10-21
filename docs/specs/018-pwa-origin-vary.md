# SPEC-018：正式站 CORS 與離線原生模組快取

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：SPEC-017、ADR-0003

## Problem

v3.3.0 部署後的唯讀 Chromium smoke 重現：線上啟動正常，但離線重新載入時，
原生 lifecycle module 載入失敗，停在錯誤 loading。正式站靜態回應含 `Vary: Origin`，
預快取請求沒有 Origin，而原生 module 請求帶有 Origin；Cache.match 因而無法命中同一 URL。
原本的本機 PWA fixture 沒有這個正式環境回應標頭。

## Goals

- 已完整安裝的 shell 在有 CORS Vary 標頭時仍可離線啟動 native module。
- 保留版本 query、同源隔離、API 不快取，以及完整安裝後才啟用的契約。
- 保留已發布 v3.3.0 tag，以新版本 v3.3.1／shell v24 修正，不改寫歷史。

## Non-goals

- 不變更 CORS 認證政策、不快取私有 API、不修改資料庫 schema。

## Proposed design

只對本 app 自己的同源、公開靜態 shell cache 查詢忽略 Vary；URL／query 繼續精確比對。
快取只由已知 APP_SHELL 清單填入，fetch handler 仍先排除外站與 `/api/`。
PWA fixture 模擬正式站 `Vary: Origin`，確認 browser native module 確實帶 Origin，
並以原有雙引擎離線／失敗升級／快取隔離流程保護行為。

## Security and data isolation

- 不對任意 HTTP response 或 API 忽略 Vary，不新增任何使用者資料快取。
- 正式站 smoke 只測匿名登入畫面與 shell，不登入或寫入正式帳號。

## Migration, rollout, and rollback

- Schema／資料 migration：無。發布前保留可還原的異地備份。
- 上線與 smoke test：PWA regression、verify-all 通過後發布 v3.3.1；核對資產雜湊與線上離線重開。
- 回滾：保留 v3.2.5 可用映像；若重新發布舊程式，仍需使用新的 shell revision 以免混版。

## Acceptance criteria

- [x] AC-1：Given shell 回應含 Vary: Origin，When 原生模組帶 Origin 且離線重開，Then loading 隱藏且登入畫面可用。
- [x] AC-2：錯誤 MIME／HTTP／斷線／版本不一致仍拒絕升級，舊 shell 與非本 app cache 不受影響。
- [x] AC-3：API 不快取，URL 版本 query 不忽略；v3.3.0 tag 保持原提交。

## Test traceability

| Acceptance criterion | Test file / command |
| --- | --- |
| AC-1 | `unit_tests/frontend_pwa.cjs`：CORS Vary fixture、native Origin 與離線 boot |
| AC-2、AC-3 | `python3 scripts/task.py frontend-pwa`、`verify-all`、公開線上 smoke 與 Git tag 核對 |

## Verification record

2026-10-21：先增加正式站相同 CORS fixture，`frontend-pwa` 在離線登入畫面等待逾時而失敗（red）；
加入公開 shell 專用的 Vary 處理後，相同命令在 Chromium／WebKit 均通過（green），含失敗升級與 API 排除。
WebKit 的離線導航採 fixture transport 中斷，不使用會連 SW cache 導航一起禁止的引擎離線模擬開關。
