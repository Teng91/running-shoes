# ADR-0010：可恢復帳號工作區與交易式異動

- 狀態：Accepted
- 日期：2026-10-24
- 規格：[SPEC-027](../specs/027-recoverable-account-workspace.md)

## Context

記憶體草稿與單向備份無法涵蓋離線、重開及誤刪。新增跑步已有重播回執，但其他寫入沒有統一操作身分；快取鏡像也增加狀態所有權負擔。

## Decision

- 原生 workspace controller 注入 storage／session／clock／transport，IndexedDB adapter 與 DOM bridge 分離。持久化紀錄按 origin／帳號分區，不包含 token、密碼或 session。既有表單保留 handler，儲存原始 ID／version，恢復時仍需後端 CAS。
- 只新增跑步進入持久佇列。IndexedDB 在同一 readwrite transaction 建立操作與消耗對應草稿；新的草稿身分不受影響。跨分頁以原子 lease claim，逾時重播相同 operation ID，由伺服器 receipt 保證效果一次。401 暫停，資料錯誤 blocked，明確配對才建立新操作身分。
- SQLite writer reservation 在讀取配額／版本／回執之前取得；外層 application transaction 擁有 commit，巢狀 service 不自行提交。成功回應與 mutation receipt 同交易，更新／刪除由新 operations contract 強制版本。既有沒有版本的 HTTP adapters 保留舊語義。
- Schema 5 triggers 在原交易建立鞋款、跑步、月份、目標 before／after 事件及資料 revision。WriteContext 只在交易內存在，記錄操作原因與身分；legacy 無 context 時安全使用 legacy.write。禁止 audit users／認證資料，報告與匯入歷史只增加 revision。
- Run／month 使用單調配置主鍵，刪除 trigger 同時推進序號；allocator 僅讀全域 PK floor 及 sequence metadata，所有業務讀寫仍 user-scoped。避免舊草稿的 ID 在刪除重建後指向不同內容。
- 備份匯出以 SQLite 實體讀取快照保持所有集合一致；並行寫入不可產生鞋款／日誌里程互相矛盾的檔案。
- 備份 v2 以穩定來源 ID＋entity/source key 建立 user-scoped mapping，不以鞋名猜測同一雙鞋。v1 以完整檔案 digest 命名空間去重。預覽有效 20 分鐘，apply 驗證本人、hash、revision、配額後一次合併；保留既有內容，mapping tombstone 防止重複匯入復活後續刪除。來源歷史保留唯讀；Strava 匯入摘要保留既有項目，僅於剩餘容量新增並預覽略過數，不清除既有摘要。
- 誤刪復原只建立新的業務操作，不刪改原事件內容；要求目前狀態、原鞋款、版本、配額仍有效，正確累計里程且原事件只復原一次。
- 年度、目標與洞察移除舊鏡像 Map，resource store 成為唯一讀取／pending／快取 owner。

## Consequences

- IndexedDB 可能被瀏覽器回收，不能取代同步及下載備份；無法使用時顯示錯誤並保留輸入，連線 CRUD 仍可用。關閉 App 不承諾背景同步。登出保留帳號本機內容，另有明確清除入口。
- 僅新增可離線；更新／刪除需要連線版本驗證。尚未同步不計入統計，衝突不自動換鞋。
- 還原有 body／集合／深度上限，超限整筆拒絕，不截斷完整匯出。大量歷史使匯出超過 20 MB 時需另行資料搬移。
- 歷史、回執與 mapping 隨使用成長；不能為省空間任意清理，否則失去跨離線重送的保護。後續容量規劃需有保留／壓縮協議。
- 正式 migration 前必須備份及隔離還原。回滾停寫、備份後保留新增結構與 triggers、降 marker 至 4 才可切回 v3.8.0；不混跑寫入，舊版失去新回執／主鍵保證。發布必須通過 CI、前置備份／隔離還原及部署後匿名 release-check。
