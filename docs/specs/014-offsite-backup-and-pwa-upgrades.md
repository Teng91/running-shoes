# SPEC-014：異地備份演練與 PWA 升級驗證

- 狀態：Implemented（v3.2.3）
- Owner：Running Shoes
- 關聯 issue／ADR：資料可靠性改善 1、2；ADR-0002

## Problem

Fly Volume 內快照與正式資料位於同一基礎設施；目前需手動下載後自行驗證，沒有一鍵隔離還原演練。
PWA 測試尚未覆蓋已安裝舊版、更新資產失敗與離線恢復。舊 worker 的 navigation refresh
可將新版 HTML 寫入舊版 cache，讓 shell 與靜態資產版本不同步。

## Goals

- 以既有 Fly CLI 建立交易一致快照，下載 DB／checksum 到指定的 Fly 外部位置，驗證後才發布為完成的本地備份。
- 每次拉取都在 OS 暫存目錄還原演練，驗證資料表、各表筆數、內容摘要與 schema version，不碰正式或開發 DB。
- 提供獨立 drill 命令與機器可讀 manifest；任何失敗非零結束，不保留看似成功的半份備份。
- PWA shell 只在完整安裝成功時換版；導覽不得把新版 HTML 塞入舊 cache。僅管理本應用程式的快取。
- 使用本機 HTTP fixture 與真正 service worker，覆蓋 Chromium／WebKit 舊版升級、失敗更新、離線啟動與恢復。

## Non-goals

- 不新增付費雲端帳號、不把完整資料庫上傳 GitHub artifacts／Git、不自動刪除異地備份。
- 不變更業務資料／schema、不實作離線寫入佇列。未指定時間／目的地前不啟用排程。
- 使用者已選擇這台電腦的專用資料夾（Git 外 private storage）；不新增自動備份排程。

## Proposed design

- scripts/offsite_backup.py 以參數陣列執行 Fly CLI；只讀正式 DB，遠端建立獨立快照，下載至 private staging directory。
- 驗證 remote checksum 後調用 database_backup 的隔離 restore drill，manifest 不包含帳號、密碼 hash 或業務列內容。
- drill 使用隨機暫存目的地，沒有 production destination 參數；僅清理自己建立的暫存資料。
- SW 安裝先 fetch 並檢查資源 MIME／HTML asset revision，再填入本版 cache；失敗不得接管舊版。
- 導覽只使用本版 precached HTML；升級透過 service worker install／activate 完成，不透過 navigation 覆寫 HTML。
- frontend-pwa 納入 task runner、verify-all 與 CI；測試 server 動態切換 release，外部網路與正式 API 不參與。

## Security and data isolation

完整 SQLite 包含所有使用者及密碼 hash，只保存於使用者指定的受控位置；目錄 0700、檔案 0600
（Windows 仍需管理 ACL）。不列印資料內容或 token，不把認證參數寫入 manifest。演練僅對副本讀取／寫入。
PWA 不快取 API／驗證回應；測試保留其他 cache，避免刪除同 origin 不相關資料。

## Migration, rollout, and rollback

- Schema／資料 migration：無。先完成 synthetic verification，再拉取至 `~/.local/share/running-shoes/backups`，不覆蓋開發 DB。
- v3.2.3 使用 asset revision 3.2.3／shell v20；依使用者授權完成 commit、push、tag、release 與 Fly deploy，部署前重新拉取並驗證備份。舊 worker migration 的首次更新需網路可用。
- 回滾可重新部署 v3.2.2 tag，無 schema 相容性變更，不還原業務 DB；異地備份只增加副本，無自動覆蓋正式還原流程。PWA 用戶需連線以取得回滾 worker。

## Acceptance criteria

- [x] AC-1：成功拉取產生完整 DB、checksum、manifest，且已完成隔離 drill；不是正式 DB 檔案複製。
- [x] AC-2：下載失敗、checksum 缺失／錯誤、非法 app／遠端路徑、還原不一致均拒絕成功；既有備份不變，機密內容不進 log。
- [x] AC-3：drill 對暫存副本驗證完整內容與 schema，不接受可指定的正式目的地。
- [x] AC-4：v3.2.2 舊 worker 線上遷移成功；完整安全版 worker 安裝後，後續 HTTP／MIME／傳輸中斷／HTML revision 失敗不污染既有 shell，離線仍可啟動，恢復網路後可更新。
- [x] AC-5：SW 不刪其他 cache、不快取 API、拒絕 HTML 偽裝 JS；首次離線／成功升級都有明確可驗證結果。
- [x] AC-6：frontend-pwa 由跨平台 runner 和 CI 執行；README、SDD、測試矩陣保持一致。

## Test traceability

| Acceptance criterion | Test file / command |
| --- | --- |
| AC-1～AC-3 | Python temporary SQLite / mocked CLI tests；test-fast |
| AC-4、AC-5 | 真正 service worker / local HTTP server；frontend-pwa |
| AC-6 | task runner tests、docs-check、verify-all |

## Verification record

- 2026-10-20：`python3 scripts/task.py verify-all` 完整通過（382 Python、53 frontend Node、28 組排版、CRUD／session 及 Chromium／WebKit PWA），browser checks 未跳過。
- PWA 實測包含真實 v3.2.2 worker 線上 migration、首次離線、HTTP／MIME／傳輸中斷／HTML revision 失敗更新、既有 shell 離線啟動與重新連線成功換版。
- synthetic checks 完成後，依使用者選擇實際將 Fly 一致快照拉取至 Git 外的本機 private storage；checksum、schema version 1 與隔離 restore drill 通過，未覆蓋開發或正式 DB。
- 使用者後續授權發布 v3.2.3；CI workflow 已加入 frontend-pwa，發布時確認遠端 CI 與部署結果。不啟用備份排程。
