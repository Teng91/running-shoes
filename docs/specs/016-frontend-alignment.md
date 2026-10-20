# SPEC-016：全前端元件對齊

- 狀態：Implemented（v3.2.5）
- Owner：Running Shoes
- 關聯 issue／ADR：使用者回報日期／距離、彈窗按鈕及 AI 模型列未對齊

## Problem

原生日期控制項有 44px 最小高度，其他桌面欄位則由字級與內距決定高度；
危險操作混用 btn-sm，AI 工具列自行定義字級與內距。既有排版測試檢查溢出，
但沒有檢查同列控制項、圖表標題列或數字欄位的幾何對齊。

## Goals

- 逐一覆蓋六個功能分頁、三個認證表單及所有彈窗，統一表單、工具列、按鈕與表頭的對齊規則。
- 表單主控制項 44px，桌面表格緊湊操作 36px；同一操作列保持等高，手機操作至少 44px。
- 同列欄位等寬／上下邊界對齊；數字欄位與表頭一致右對齊，卡片及圖表標題保持一致節奏。
- 長文字、空資料、錯誤、disabled 與手機換行不造成溢出或重疊。

## Non-goals

- 不重新設計導覽、改變商業計算、API、資料庫或帳號行為。
- 不將所有不同語意的元件強制同尺寸：checkbox、日曆內按鈕、文字區仍保有適當的密度／高度。

## Proposed design

- styles.css 定義控制項尺寸與行高 token，集中處理 native date/month、一般欄位與按鈕。
- 工具列、彈窗操作、圖表標題及響應式規則以明確 class 管理，消除同組內混用尺寸。
- 欄位 label 對應 input，表格數字使用語意 class；動態列與靜態表頭保持相同契約。
- 擴充 frontend-layout：雙引擎／亮暗／手機到桌面，驗證實際幾何並保存截圖供人工覆核。
- PWA revision／cache 隨 v3.2.5 更新，文件及測試矩陣同步。

## Security and data isolation

- 純呈現變更，不新增 query／mutation；測試使用合成資料及暫存 DB，不使用正式帳號或 shoes.db。
- 不修改既有欄位 ID、驗證、事件處理與資料計算；備份保存於 Git 外。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：verify-all、截圖覆核、部署前備份／隔離還原、線上資產及雙引擎啟動。
- 回滾方式與資料相容性：重新部署 v3.2.4；不還原 DB，PWA 首次更新需連網。

## Acceptance criteria

- [x] AC-1：Given 六個功能分頁，When 切換所有尺寸／主題，Then 同列控制項等高、圖表標題與 canvas 起點對齊，無頁面溢出。
- [x] AC-2：Given 新增／編輯跑步、跑鞋及其他彈窗，Then 欄位邊界一致、同列按鈕等高，手機換行不留下 spacer 空洞。
- [x] AC-3：Given AI 模型列，Then label／select／refresh 垂直對齊，手機有明確換行且文字不裁切；輸入區底部對齊。
- [x] AC-4：Given 表格與卡片，Then 數值／表頭對齊、操作按鈕等高，長內容可閱讀並維持原資料。
- [x] AC-5：Given 認證、錯誤、空資料、disabled 與 PWA，Then 功能及 responsive／離線升級回歸通過，文件一致。

## Test traceability

| Acceptance criterion | Test file / command |
| --- | --- |
| AC-1～AC-4 | frontend_layout.cjs／frontend-layout，截圖人工覆核 |
| AC-2、AC-4、AC-5 | frontend_regressions.cjs、frontend_e2e.cjs／frontend-test、frontend-e2e |
| AC-5 | frontend_pwa.cjs、verify-all、docs-check |

## Component audit inventory

| 區域 | 覆核範圍 |
| --- | --- |
| Shell／認證 | Sidebar、手機選單、帳號／主題操作、loading；登入、註冊、更改密碼的欄位與提交按鈕 |
| 跑步日誌 | 月份篩選、日期／距離／鞋款、六個指標、月曆、圖例、Strava 操作與日誌表格 |
| 跑鞋 | 六個摘要、類別與提醒、四個圖表、現役／退役表格及行內編輯 |
| 月跑量 | 目標列、目標卡片、年度圖表、月份新增、表格與行內編輯 |
| 支出 | 六個摘要、年度圖表與支出明細，金額／折數表頭與內容邊界 |
| AI 助手 | 模型／刷新列、輸入與送出、使用者／助手氣泡、Markdown、思考／工具狀態、來源與重試 |
| 月報 | 月份、歷史、模型、產生按鈕、狀態與 Markdown 報告 |
| 六個彈窗 | 跑鞋新增／現役與退役編輯、跑步編輯、Strava 檔案／日期／鞋款配對、月份編輯、匯出、單鞋分析 |

40 組設定 = Chromium／WebKit × 亮／暗 × 320、375、390、430、844 橫向、768、800、1024、1280、1440 寬度。
每組包含認證表單與全部彈窗的正常／錯誤／disabled 狀態；以合成資料測試，不連正式 API。
AI 與月報使用合成 Markdown／來源，不執行外部模型或搜尋；WebKit 並不等同 iPhone 實機。

## Verification record

- 2026-10-20：`python3 scripts/task.py verify-all` 完整通過：382 Python、58 Node、40 組排版及雙引擎 E2E／PWA，未跳過瀏覽器檢查；Ruff、mypy、架構、機密／依賴與文件檢查皆通過。
- 最終 CSS 另執行 `frontend-layout`，40 組全部通過；保留桌面／手機／亮暗截圖並人工覆核日期與數字欄位、AI 模型／工具／來源、Markdown 月報、認證、現役／退役編輯、Strava、匯出與分析。
- 月報已儲存與錯誤狀態分開呈現，不改內容或儲存流程；Node 測試驗證舊錯誤樣式清除。原生 select 僅統一外觀，保留選值、鍵盤與事件。
- 部署前 Fly 一致快照已下載至 Git 外本機專用目錄，checksum 及隔離 restore drill 通過；無 schema migration 或正式 DB 還原。
