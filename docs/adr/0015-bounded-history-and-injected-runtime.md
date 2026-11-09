# ADR-0015：有界帳號歷史、單一回執與注入式執行環境

- 狀態：Accepted
- 日期：2026-11-09
- 規格：[SPEC-047](../specs/047-review-hardening-and-decoupling.md)

## Context

稽核紀錄同時負責「顯示歷史」與「本機刪除身分」，因此無法清理；任何註冊帳號都能讓 `audit_events` 與回執持續成長。
建立跑步同時寫入 `run_creation_requests` 與 `mutation_receipts`，內層回放永遠不會先命中。
`auth`、`rate_limits`、`database` 在 import 時讀取全域設定、建立 engine 或結束程序，`create_app(config)` 的注入對它們無效；
限流在記憶體與 SQLite 各算一次，還會 commit 請求的 session。稽核 trigger 以 `IF NOT EXISTS` 建立，欄位清單不會跟著 schema 更新。

## Decision

- **墓碑**：本機刪除的跑步身分存在 `run_tombstones (user_id, run_id)`，由 `services/runs.delete_run` 在同一交易寫入。匯入計畫只讀這張表，稽核紀錄只負責顯示與復原。
- **保留上限**：`services/retention.py` 在 `write_transaction` commit 前，只清理該帳號超出上限的最舊資料：稽核 5,000、回執 1,000（依 `recorded_at`）、墓碑 50,000。上限是程式常數，不是部署設定。
- **單一回執**：`mutation_receipts` 是唯一的鍵控回執；`run_creation_requests` 在 schema 7 移除，ADR-0004 的對應決策由本 ADR 取代。`payload_hash` 移到 `services/fingerprints.py`。
- **組合根**：`create_app()` 是唯一驗證密鑰（`settings.runtime_settings`）與建立預設 engine 的地方。`database.py` 不在 import 時做 I/O；`dependencies.get_db` 從 `app.state.session_factory` 建立 session。正式環境的 SECRET_KEY 至少 32 bytes。
- **限流**：只用 SQLite 固定視窗，限額讀取 `request.app.state.settings`，在 `app.state.db_engine` 的獨立交易中消耗；任一視窗已滿就整筆回滾。登入失敗依「來源＋帳號」與「帳號」兩個視窗計算。
- **稽核 trigger**：每次啟動在同一交易中依目前 model 欄位重建全部 trigger。
- **前端事件**：markup 以 `data-click` 等屬性宣告動作，`app-actions.js` 是唯一把動作名稱對應到全域函式的地方。

## Consequences

- 超過上限的舊歷史無法再顯示或復原；需要長期留存時，改用管理員完整資料庫備份。從備份匯入的大量歷史也會被裁到上限。
- 回滾到 schema 6 必須先執行 `scripts/rollback_schema_seven.sql`，重建空的舊回執表。
- 限流每個請求多一個短交易，換來與請求交易隔離且只有一套計數；部署在多個 worker 時仍共用同一份限額。
- 測試改用 `app.state.settings` 調整限額，不再 monkeypatch 模組常數，也不必清理記憶體桶。
- 前端新增 `app-actions.js` 資產；新增 inline `on*=` 事件會被回歸測試拒絕，唯一例外是必須先於 app script 執行的樣式表 `onload`。
