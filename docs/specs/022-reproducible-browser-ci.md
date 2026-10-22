# SPEC-022：可重現的瀏覽器 CI 與失敗診斷

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：SPEC-019、SPEC-021、ADR-0004

## Problem

v3.5.1 main CI 重跑時，Ubuntu Azure mirror 下載瀏覽器系統依賴超過 15 分鐘，工作被取消且未開始測試。
另一輪 WebKit CacheStorage Internal error 的截圖／trace 位於隱藏 .artifacts 目錄，upload-artifact 預設排除隱藏檔，導致沒有診斷產物。

## Goals

- CI 使用已包含相符瀏覽器與系統依賴的固定版本執行環境，不在每次測試重新下載 apt 套件。
- 保留完整 layout、CRUD、PWA gate 與既有 timeout，不自動重試失敗斷言。
- 失敗時可上傳合成帳號／匿名 browser 的截圖、trace 與錯誤。

## Non-goals

- 不改正式 app image、schema、公開 v3.5.1 tag 或應用程式 PWA 邏輯。
- 不把 WebKit 單次 Internal error 當成已證實的 app 缺陷或增加任意重試。

## Proposed design

- frontend-layout job 使用與 package-lock 相同 Playwright 1.63.0 的官方 noble container，配置 --ipc=host。
- 仍由 npm ci 安裝套件；container 已有 browsers／OS dependencies，移除 install --with-deps。
- container job 不啟用 setup-python 的 pip cache（其 host shebang 在 /__t mount 下失效）；依賴一律以 python -m pip 安裝，host verify job 保留 cache。
- upload-artifact 明確 include-hidden-files，path 縮小至 .artifacts/browser/，保留 7 天。
- regression 檢查 workflow image 與 package／lockfile 版本一致，以及診斷上傳的 scope／hidden 設定。

## Security and data isolation

- CI 僅測試本機 fixture、合成帳號與暫存 SQLite，不使用 production credentials。
- GitHub permissions 維持 contents: read；container 只執行可信的 repository 測試。
- 只上傳 browser diagnostics，避免擴大至其他 artifact 目錄。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：verify、docs-check、實際 GitHub CI 完整 browser gates；正式部署另遵守 SPEC-021。
- 回滾方式與資料相容性：僅回滾 workflow 即可；無正式資料變動。

## Acceptance criteria

- [x] AC-1：Given 固定 Playwright lockfile，When CI 啟動，Then container 版本相符且不用 apt 安裝；layout、CRUD、PWA 皆執行。
- [x] AC-2：Given browser 失敗產物位於隱藏目錄，When upload step 執行，Then scope 僅 browser 且允許 hidden files。

## Test traceability

| Acceptance criterion | Test file / command |
| --- | --- |
| AC-1 / AC-2 | `unit_tests/test_task_runner.py`、`.github/workflows/verify.yml` |
| AC-1 | `python3 scripts/task.py verify` |

## Verification record

2026-10-22：已核對官方 v1.63.0-noble image manifest；本機使用該映像、唯讀 source mount、停用對外網路與 --ipc=host，實跑 Chromium／WebKit PWA 全部通過。
verify 通過：450 Python／81 Node、95.21% backend coverage，含 image／lockfile／完整 gates／hidden diagnostics 契約；實際 GitHub CI 結果記錄於 v3.5.1 Release。
