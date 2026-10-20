# SPEC-015：跑步日誌固定首頁

- 狀態：Implemented（v3.2.4）
- Owner：Running Shoes
- 關聯 issue／ADR：使用者要求每次重新開啟都進入跑步日誌

## Problem

目前 init 讀取 localStorage.activeTab，在保留登入狀態時還原上次分頁。
因此離開 AI 助手後重新開啟會回到 AI 助手，與預設首頁的期待不符。

## Goals

- 登入、重新整理及新視窗／PWA 冷啟動一律以跑步日誌為首頁。
- 忽略舊版保存的分頁；同次使用可正常切換，不影響登入與主題偏好。
- 瀏覽器以 back-forward cache 還原文件時亦回首頁，不額外請求或更動資料。

## Non-goals

- 不改動版面、API、資料庫或 AI 對話保存方式。
- 不在一般切換 App／瀏覽器分頁的 visibilitychange 上重設，避免打斷尚未完成的操作。

## Proposed design

- app.js 的 init 在驗證登入之前使用既有 resetAppLayout，移除 stored tab 還原。
- app-core.js 的 switchTab 僅更新當前文件，不再保存 activeTab；舊 key 不讀取也不影響啟動。
- pageshow.persisted 重新套用首頁並呈現 active panel；新文件沿用 init。
- PWA asset revision 3.2.4 與 shell cache v21 一起更新，避免既有安裝保留舊邏輯。

## Security and data isolation

- 無 DB query／mutation，不修改 token、username 或 theme；回歸測試只用 synthetic session 與暫存 DB。
- 回首頁不觸發 AI 請求，也不清空使用者資料或送出草稿。

## Migration, rollout, and rollback

- Schema／資料 migration：無；既有 activeTab 僅被忽略，不清除整個 localStorage。
- 上線與 smoke test：完整 runner、Chromium／WebKit 重開與 PWA 測試、線上健康及資產版本檢查。
- 回滾方式與資料相容性：重新部署 v3.2.3；不需還原資料庫，PWA 更新需連網。

## Acceptance criteria

- [x] AC-1：Given 已保存 AI／月報等分頁與登入，When 重新整理或新開文件，Then 唯一 active panel 是 runs，手機標籤與 ARIA 同步，agent-mode 關閉。
- [x] AC-2：Given 未登入或登入驗證網路失敗，When 啟動，Then 預設 layout 仍是 runs，登入／主題機制不變。
- [x] AC-3：When 使用者切換分頁，Then 正常切換但不再寫入 activeTab；主題仍可保存。
- [x] AC-4：When persisted pageshow 還原，Then 回跑步日誌；一般 visibilitychange 不切頁。
- [x] AC-5：已安裝 PWA 重新導航／離線重開時仍以跑步日誌為首頁，新 shell 更新測試通過。

## Test traceability

| Acceptance criterion | Test file / command |
| --- | --- |
| AC-1～AC-4 | frontend_regressions.cjs、frontend_safety.cjs／frontend-test、frontend-e2e |
| AC-5 | frontend_pwa.cjs／frontend-pwa |

## Verification record

- 2026-10-20：frontend-test（55 個）、frontend-e2e 與 frontend-pwa 通過；Chromium／WebKit 均驗證舊 key、重開／重新整理、persisted pageshow handler、手機標題與 ARIA，以及離線快取導航。
- `python3 scripts/task.py verify-all` 完整通過（382 Python、55 Node、28 組排版及雙引擎 E2E／PWA），未跳過瀏覽器檢查。部署前 Fly 快照下載至本機 Git 外備份目錄，checksum 與隔離還原演練通過。
- pageshow 以真實 DOM 的 PageTransitionEvent 驗證 handler；PWA 是瀏覽器引擎測試，非 iPhone 實機測試。背景保留的活文件不視為重新啟動。
