# SPEC-012：編輯快照、共用串流與按需呈現

- 狀態：Implemented（v3.2.1）
- Owner：Running Shoes
- 關聯 issue／ADR：專案檢查的三項 bug、一項一致性問題及兩項優化；ADR-0001

## Problem

月跑量以陣列 index 保存編輯對象，重新載入後可能改到另一筆；跑步編輯使用重新載入後的 version，可能繞過衝突檢查。
AI 未確認 done 就保存半截回答；AI 與月報重複實作串流解析。清單與單鞋分析退役預估來源不同。
全域 render 會建立隱藏分頁的圖表並讀取年度日誌。

## Goals

- 編輯時固定 ID、version、session；資料更新、刪除或重新排序不改變編輯對象，過期提交回應不影響新視窗。
- 共用 SSE HTTP／解碼／取消／完成狀態；只有成功 done 的 AI 回覆可以進入歷史，錯誤或中斷保留可見部分及重試提示。
- 退役日期由同一後端函式計算，優先近 90 天實際使用、無紀錄時回退計畫月跑量，清單與分析顯示相同依據。
- 只呈現目前分頁；資料或主題更新使分頁失效，切換到該頁才更新圖表／載入年度日誌。

## Non-goals

- 不修改正式業務資料、schema、權限或既有 API path。
- 不引入前端框架，不改變跑鞋購買資訊的欄位歸屬。

## Proposed design

- Run／monthly modal 使用獨立物件快照與提交鎖，成功／失敗更新需符合原視窗與 session；登出重設快照。
- 新增 `app-streams.js`，在 API／auth 後、feature modules 前載入，提供 JSON SSE reader；feature 只處理事件與呈現，沿用 request ID 與 session guard。
- 新增純後端 forecast helper，清單以 user-scoped grouped query 批次取得 90 天跑量；ShoeOut 加入唯讀 forecast 欄位，分析使用相同 helper。無需逐鞋 API 請求。
- Core 管理分頁呈現版本，dashboard dispatcher 只繪製 active panel，年度圖表完成前再次確認 active panel 與 request ID。
- 更新 PWA asset revision 至 3.2.1，確保新增共用 module 與舊 shell 不混用。

## Security and data isolation

快照包含原 session，登出失效；串流取消後不得更新其他帳號。forecast query 同時限制 user_id 與鞋 ID，測試使用暫存 SQLite、mock SSE／fetch，不呼叫外部模型。

## Migration, rollout, and rollback

- Schema／資料 migration：無；ShoeOut 僅新增 response 欄位。
- 本地驗證 `eval-agent`、`verify-all`，保留既有 CRUD、帳號隔離及響應式矩陣。
- 使用者已授權 commit、push、tag、release 與 Fly 部署；部署前建立並驗證正式資料庫快照，部署後執行公開端點 smoke test 與靜態資產版本檢查。
- 回滾程式可部署 v3.2.0 對應映像，資料格式相容，不需還原業務資料。

## Acceptance criteria

- [x] 月跑量重新排序／刪除、跑步版本更新後，提交保留原 ID／version，衝突顯示錯誤且不覆蓋新資料。
- [x] modal 在提交中關閉／切換、登出後，晚到回應不關閉或修改新視窗；重複提交不產生多次寫入。
- [x] AI done／error／無 done EOF／網路中斷、重試及取消都有回歸，只有完整成功回答進入 history。
- [x] 共用 reader 正確處理 chunk、UTF-8、CRLF、多行 data、格式錯誤及取消；月報成功／中斷語意維持。
- [x] 清單、時間軸與分析使用同一 forecast；實際／回退／零跑量／壽命已到／大數值／帳號隔離皆驗證。
- [x] 初始跑步頁不建構隱藏圖表或讀年度日誌；分頁切換可重用，資料／主題改變後正確失效，過期非同步結果不重畫隱藏頁。

## Test traceability

| Acceptance criterion | Test file / command |
| --- | --- |
| AC-1、AC-2 | Frontend Node、browser regression + 暫存 SQLite CRUD |
| AC-3、AC-4 | 共用 SSE Node tests + Chromium/WebKit streaming regression |
| AC-5 | Backend forecast／analytics tests + frontend DOM regression |
| AC-6 | Node render tests + browser layout／request counters |
| 全部 | `python3 scripts/task.py verify-all` |

## Verification record

- 2026-10-20：`python3 scripts/task.py verify-all` 完整通過，未跳過 browser checks。
- Python 360 項、frontend Node 48 項、28 組排版，以及 Chromium CRUD／Chromium 和 WebKit session 與 SPEC-012 browser regression 全數通過。
- Ruff、mypy、架構邊界、secret scan、依賴安全與文件一致性檢查通過。
- 本地驗證使用暫存 SQLite 與 mock 外部回應，不修改正式資料；發布與部署為驗證完成後、使用者另外授權的操作。
