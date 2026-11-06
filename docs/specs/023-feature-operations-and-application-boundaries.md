# SPEC-023：表單操作保護、鞋款辨識與應用服務邊界

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：SPEC-020、SPEC-021、SPEC-022、ADR-0006

## Problem

新增月跑量的舊成功回應會清掉新月份／里程草稿，部分表單操作沒有一致的 session／identity 保護。
同款鞋在跑步選單名稱相同，無法辨識個別鞋款。認證與目標寫入仍位於 router；每次 mutation
重讀所有資料並使不相關快取失效。文件追蹤只驗證檔案路徑，失敗診斷未演練完整 artifact round trip。

## Goals

- 共用 DOM-independent operation owner，保護跑步、月跑量與鞋款的晚到成功／錯誤及 session reset。
- 鞋款持久化可選暱稱；以名稱、購買日期與 ID 清楚區分每雙鞋。
- 認證與目標的配額、密碼衝突及交易由 application services 擁有，密碼／token primitive 不依賴 HTTP。
- 按 mutation 種類重讀資料及使相關快取失效，保留 session／request-generation 保護。
- 演練 browser 診斷的產生、上傳與下載驗證，並驗證 spec 的具名 Python／Node 測試引用。

## Non-goals

- 不新增日誌備註、搜尋、目標歷史或帳號還原。
- 不改公開 API method/path、不使用正式帳號進行測試、不在驗證流程中部署 schema migration；正式上線依明確授權執行。

## Proposed design

- 原生 form-operations module 擁有 session／operation identity／snapshot；classic bridge 注入依賴，run controller 與 monthly／shoe adapters 共用。
- nickname 為有長度限制、可空字串的鞋款欄位；schema 3 只新增欄位，舊值為空。新增／編輯表單、ShoeOut 與帳號備份保留暱稱；共用鞋款標籤顯示購買日期／ID。
- credentials module 管理 bcrypt／JWT primitives；accounts／goals services 管理 use cases／domain errors，router 僅認證、輸入與 HTTP 轉換。
- loadData 接收 mutation kind，使用明確 resource／cache invalidation policy；首次登入與手動重試仍完整讀取。
- docs-check 從 AST／Node test titles 驗證新 spec 的 file::test_name，保留舊 spec 相容。
- CI 在合成 browser context 故意產生並捕捉錯誤，驗證 screenshot／trace／error 後 upload，獨立 job download 並核對內容。

## Security and data isolation

- 所有 services 仍以認證帳號 ID 限定資料，保留配額、CAS、rate limits 與 rollback。
- Nickname 為不可信文字，輸出 HTML 必須 escaping，匯出遵守 formula injection 防護。
- CI artifacts 僅包含合成資料；download job 維持 contents: read，不使用正式帳號或 secrets。

## Migration, rollout, and rollback

- Schema／資料 migration：schema 3 新增 shoes.nickname，預設空字串，不更改既有 ID／里程／版本。
- 上線與 smoke test：verify-all、eval-agent、architecture/security/docs gates 與 CI artifact round trip；使用者於 2026-10-23 明確授權發布 v3.6.0；正式 migration 前完成異地備份與隔離還原演練，部署後執行匿名唯讀 release-check。
- 回滾方式與資料相容性：正式 migration 前先建立並驗證異地備份；回滾 schema 2 image 需依既有 marker 相容流程，保留 nickname 欄位與新資料，不以舊快照覆蓋正式業務資料。

## Acceptance criteria

- [x] AC-1：Given 延遲新增月跑量，When 表單改填或 session 切換，Then 舊回應不清除新草稿、不顯示舊錯誤或解鎖新操作。（[SPEC-039](039-compact-monthly-records.md) 已移除月跑量新增表單；同一 operation owner 保證由下列共用測試持續覆蓋。）
- [x] AC-2：Given 跑步／鞋款／月跑量寫入，When 重送、modal 替換或 session reset，Then 共用 operation owner 正確保護草稿與控制項。
- [x] AC-3：Given 同款同日鞋或惡意暱稱，When 新增、編輯、選鞋或備份，Then 暱稱持久化、標籤可辨識且安全 escaping，其他帳號不可修改。
- [x] AC-4：Given schema 2 資料庫，When 升級 schema 3 及重複啟動，Then 原資料／里程不變且 nickname 預設空字串。
- [x] AC-5：Given 註冊、改密碼或目標並行更新，When 經 HTTP 或直接 service 呼叫，Then 配額、CAS、revocation、隔離與 rollback 保持正確，services 不依賴 HTTP。
- [x] AC-6：Given run／monthly／shoe／Strava mutation，When 更新資料，Then 只讀相關資源，不重讀無關目標／匯入歷史或清除無關支出快取；晚到請求不覆寫較新資料。
- [x] AC-7：Given 有效或不存在的具名測試引用，When docs-check 執行，Then 有效引用通過，錯誤引用顯示檔案與測試名稱。
- [x] AC-8：Given 合成 browser 失敗，When CI upload／download diagnostics，Then screenshot、trace 與錯誤可驗證，無真實帳號內容。

## Test traceability

| AC | Named regression / gate |
| --- | --- |
| AC-1 | `unit_tests/frontend/feature-operations.test.cjs::SPEC-023 operation owners preserve identity after reset and isolate independent features`；`unit_tests/frontend/monthly-records.test.cjs::SPEC-039 the monthly tab has no records table, add form or edit dialog` |
| AC-2 | `unit_tests/frontend/feature-operations.test.cjs::SPEC-023 operation owners preserve identity after reset and isolate independent features`；`unit_tests/frontend/feature-operations.test.cjs::SPEC-023 shoe save preserves an edited draft and rebases its optimistic version`；`unit_tests/frontend/draft-resources.test.cjs::SPEC-024 shoe transitions preserve only new edits and retain the server state`；`unit_tests/frontend/auth-editors.test.cjs::all shoe mutations lock their snapshot and leave replacement drafts and sessions untouched` |
| AC-3 | `unit_tests/frontend/feature-operations.test.cjs::SPEC-023 shoe selectors distinguish duplicate models and escape nicknames`；`unit_tests/test_feature_boundaries.py::test_nickname_persists_is_scoped_and_survives_account_and_safe_csv_exports` |
| AC-4 | `unit_tests/test_feature_boundaries.py::test_schema_three_nickname_upgrade_preserves_ids_mileage_versions_and_is_idempotent` |
| AC-5 | `unit_tests/test_feature_boundaries.py::test_account_services_enforce_capacity_credentials_and_revocation`；`unit_tests/test_feature_boundaries.py::test_goal_service_is_user_scoped_rejects_stale_versions_and_rolls_back`；`unit_tests/test_auth_concurrency.py::test_overlapping_password_changes_reject_stale_snapshot_and_revoke_tokens`；`python3 scripts/task.py architecture-check` |
| AC-6 | `unit_tests/frontend/feature-operations.test.cjs::SPEC-023 mutation refresh limits requests and preserves unrelated caches`；`unit_tests/frontend/feature-operations.test.cjs::SPEC-023 overlapping full and mutation reloads reject stale resources and retain unrelated results` |
| AC-7 | `unit_tests/test_docs_harness.py::test_named_traceability_resolves_python_classes_parameters_and_node_titles`；`unit_tests/test_docs_harness.py::test_new_spec_traceability_rejects_file_only_and_missing_named_cases` |
| AC-8 | `unit_tests/test_task_runner.py::test_diagnostics_roundtrip_requires_capture_upload_download_and_content_verification`；`unit_tests/test_task_runner.py::test_downloaded_diagnostics_validate_checksums_trace_contents_and_safe_paths`；`python3 scripts/task.py diagnostics-generate`；`python3 scripts/task.py diagnostics-verify`；CI diagnostics-roundtrip job |

本機驗證：`python3 scripts/task.py verify-all` 全通過，458 Python／88 Node／95.26% backend branch coverage，40 組版面及雙引擎 E2E／PWA 無跳過；Agent evals 10 個通過。合成 diagnostics 已透過實際 Chromium 產生並驗證，CI 獨立 job 負責上傳後的下載驗證。

SPEC-024 補足退役／現役成功後再次儲存保留草稿的狀態轉移追蹤；新案例同時於 Chromium／WebKit 的 `unit_tests/frontend_drafts.cjs` 操作真實 DOM。上述 458／88 為 v3.6.0 發布時的歷史基線。
