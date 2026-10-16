# ADR-0002：版本化 SQLite migration 與可驗證備份

- 狀態：Accepted
- 日期：2026-10-16

## Context

正式資料位於單一 Fly volume。舊做法在 app startup 直接執行多段 idempotent `ALTER TABLE`，
備份則依賴人工複製命令，無 schema version、checksum、restore safety snapshot 或 readiness gate。

## Decision

- 保留 SQLite 與單一 volume，但 migration 集中於 `backend/migrations.py` 並寫入 schema version。
- readiness 必須確認資料庫可查詢且 schema version 等於程式預期版本。
- 正式 migration 前使用 SQLite backup API 建立快照，並執行 checksum、integrity 與必要資料表驗證。
- restore 必須停寫、明確確認，並先保存 pre-restore snapshot。
- volume 內 retention 只處理快速回滾，重要備份仍需下載到不同故障域。

## Consequences

- 啟動與部署失敗可以由 health check 立即識別。
- 備份具可驗證結果，還原不會直接抹掉當前資料庫。
- 現有 legacy migration 仍保留 idempotent 行為；未來 schema 變更必須提高版本並加入 regression test。
- 本專案不內建外部物件儲存憑證；off-volume 備份仍由維運者執行。
