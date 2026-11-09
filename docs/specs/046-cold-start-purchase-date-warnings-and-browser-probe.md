# SPEC-046：冷啟動加速、購買日前跑步提醒與瀏覽器偵測

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-022](022-reproducible-browser-ci.md)、[SPEC-045](045-legacy-tables-and-deleted-shoe-labels.md)

## Problem

- Fly 機器閒置後自動停機，下一次開啟要等 2.5～3 秒。後端載入約 0.6 秒，其中 OpenAI SDK 約 0.2 秒，只有 AI 對話／月報才需要；image 裡的 `backend/` 沒有預先編譯，執行使用者又無法寫入 `__pycache__`，每次冷啟動都重新編譯。
- 正式資料有 11 筆跑步早於所配對鞋款的購買日，全部來自 Strava 匯入；新增或匯入時沒有任何提醒。
- 本機已下載 Playwright 瀏覽器但缺 Linux 系統函式庫時，Stop hook 與 `verify-all` 只檢查執行檔存在，就去跑版面測試而失敗。

## Goals

- 後端啟動不載入 OpenAI SDK；Docker image 預先編譯 `backend/`。
- 新增／編輯跑步的日期早於所選鞋款購買日時顯示提醒，仍可儲存；Strava 匯入預覽每個鞋款群組回傳最早可匯入日期，配對的鞋款購買日較晚時提醒。
- 瀏覽器檢查以實際啟動 Chromium 與 WebKit 為準；啟動不了時，選用檢查與 Stop hook 跳過並說明原因與修正指令。

## Non-goals

- 不調整 Fly `min_machines_running`（會增加費用），不改啟動 migration（實測正式資料副本 3～5 ms）。
- 提醒不阻擋儲存或匯入，不自動改寫既有資料。

## Proposed design

- `backend/llm.py`：`_build_client()` 才 `from openai import OpenAI`；型別只在 `TYPE_CHECKING` 匯入。
- `Dockerfile`：`COPY backend` 後 `RUN python -m compileall -q backend`。
- `backend/read_models/strava_preview.py`：每個 gear group 加 `first_date`。
- `frontend/app-runs.js`：`prePurchaseWarning()`／`updateRunDateWarning()`，日期或鞋款變更、選單重繪時更新；`frontend/app-strava.js`：`updateStravaDateWarning()`。
- `scripts/browser_probe.cjs`：依序啟動並關閉 Chromium、WebKit，最後一行 stderr 說明失敗原因；`scripts/task.py`（每次執行快取一次結果）與 `scripts/claude_stop_hook.py` 共用。

## Security and data isolation

- Strava 預覽只多回傳本人上傳 CSV 中的日期；鞋款購買日來自本人已載入的鞋櫃。瀏覽器偵測只在本機執行，不連線外部服務。

## Migration, rollout, and rollback

- Schema／資料 migration：無；schema 6 不變。
- 上線與 smoke test：部署前照常建立並驗證異地備份；Asset 4.6.0／shell v53；部署前後各量測一次閒置停機後的第一個請求時間。
- 回滾方式與資料相容性：可直接回滾至 v4.5.1 image；預覽多出的 `first_date` 欄位舊前端會忽略。

## Acceptance criteria

- [x] AC-1：Given 後端模組，When 匯入 `backend.main`，Then 不會載入 `openai`；建立 AI client 時才載入，且 Docker image 在複製 `backend/` 後預先編譯。
- [x] AC-2：Given 跑步日期早於所選鞋款購買日，When 新增或編輯跑步，Then 顯示含購買日的提醒且仍可儲存；購買當天或之後不提醒。
- [x] AC-3：Given Strava 預覽，When 某鞋款群組最早活動早於配對鞋款的購買日，Then 預覽回傳 `first_date` 並在該群組顯示提醒；不匯入或日期較晚時不顯示。
- [x] AC-4：Given 已下載但無法啟動的 Playwright 瀏覽器，When 執行 `verify-all` 或 Stop hook，Then 偵測只呼叫一次啟動探測、跳過瀏覽器檢查並提示 `install-deps`；release-check 仍拒絕執行。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_import_paths.py::test_backend_import_does_not_load_the_openai_sdk`、`unit_tests/test_llm.py::test_build_client_requires_key_and_uses_openrouter_endpoint`、`unit_tests/test_security_config.py::test_docker_enables_production_secret_checks` |
| AC-2 | `unit_tests/frontend/feature-operations.test.cjs::SPEC-046 runs dated before the shoe purchase show a non-blocking reminder` |
| AC-3 | `unit_tests/test_strava_import.py::test_strava_preview_reports_each_gear_groups_earliest_importable_date`、`unit_tests/frontend/feature-operations.test.cjs::SPEC-046 Strava mapping flags gear whose first activity predates the chosen shoe` |
| AC-4 | `unit_tests/test_task_runner.py::test_browser_checks_require_browsers_that_launch`、`unit_tests/test_claude_stop_hook.py::test_layout_check_is_skipped_when_browsers_cannot_launch`、`unit_tests/test_release_check.py::test_release_task_requires_explicit_origin_and_never_skips_browsers` |
