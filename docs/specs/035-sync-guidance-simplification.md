# SPEC-035：同步操作依狀態顯示

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-028](028-workspace-guidance.md)

## Problem

資料與同步頁把離線注意事項、一般雲端儲存行為和兩種不同操作塞在一起。「立即同步」同時代表送出離線跑步與重新讀取雲端，使用者難以判斷是否需要操作及按下後會發生什麼事。

## Goals

- 清單空時清楚說明新增成功的跑步已直接存到雲端，按鈕用「更新雲端資料」描述實際行為。
- 有待送紀錄時顯示裝置端待送筆數與「同步待送跑步」按鈕。
- 離線時停用按鈕並明確顯示等候網路；詳細離線限制預設收合。
- 草稿、備份／匯入、異動歷史及清理本機資料等低頻操作預設收合，標題仍可直接辨識用途。

## Non-goals

- 不改變同步時機、佇列格式、備份或伺服器資料。
- 不增加背景同步或其他離線 CRUD。

## Proposed design

工作區視圖依佇列數量及 `navigator.onLine` 更新狀態、同步按鈕文字與可用性。同步結果仍顯示於既有 live status。把離線風險說明移入原生 `<details>`，並精簡常駐說明。

## Security and data isolation

- 不新增查詢、mutation、credential 或持久化資料。
- 既有帳號分區及 session guard 保持不變。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：執行 frontend-test、frontend-layout、docs-check。
- 回滾方式與資料相容性：回復前端來源並重新生成資產；資料格式不變。

## Acceptance criteria

- [x] AC-1：Given 線上且沒有待送紀錄，When 顯示資料與同步頁，Then 說明紀錄直接存雲端且動作標示為更新雲端資料。
- [x] AC-2：Given 存在待送紀錄或裝置離線，When 顯示同步控制，Then 顯示待送筆數及同步動作，或停用按鈕並顯示等待連線。
- [x] AC-3：Given 使用者尚未查看離線說明，When 開啟資料與同步頁，Then 詳細限制收合，主要操作仍清楚可見。
- [x] AC-4：Given 使用者尚未操作低頻功能，When 開啟資料與同步頁，Then 草稿、備份／匯入、歷史及清理區域預設收合且用途可辨識。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/frontend/workspace.test.cjs::SPEC-035 sync controls name the action for the current connection and queue state` |
| AC-2 | `unit_tests/frontend/workspace.test.cjs::SPEC-035 sync controls name the action for the current connection and queue state` |
| AC-3、AC-4 | `unit_tests/frontend/workspace.test.cjs::SPEC-035 workspace hides detailed offline caveats behind a disclosure` |
