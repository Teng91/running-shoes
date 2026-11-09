# ADR-0013：復原來源身分與提交後讀取

- 狀態：Accepted（本機刪除證據改由 `run_tombstones` 提供，見 [ADR-0015](0015-bounded-history-and-injected-runtime.md)）
- 日期：2026-10-25
- 規格：[SPEC-033](../specs/033-recovery-and-sync-identity.md)

## Context

刪除與復原配置新 ID，但匯入來源別名仍指向已刪 ID。同帳號未曾匯入的紀錄缺少刪除 mapping。前端 loadData 漸進交付且不因單一資源失敗 reject，不能直接視為刷新成功。

## Decision

- run_identity service 辨識本機非匯入的刪除事件；復原在呼叫端持有的交易內重定向全部本人來源別名並記錄原生舊 ID。
- 保留單調遞增 ID，不讓舊編輯表單誤改復原紀錄。Imported audit 永遠只供呈現。
- queue 租約每次 claim 分配身分，與穩定的業務 idempotency key 分離。
- resource bridge 統一核心刷新成功判定；已成功提交的復原只重試讀取。

## Consequences

不變更 schema 或 archive format。測試需覆蓋連續復原、不同來源、帳號隔離與交易失敗，以及過期請求／登入切換。新增 service 不引入 HTTP 或 commit 依賴。
