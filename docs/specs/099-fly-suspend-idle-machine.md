# SPEC-099：閒置機器改用 suspend，喚醒更快

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-073](073-api-flood-guard.md)

## Problem

- `fly.toml` 設定 `auto_stop_machines = "stop"`：沒人使用時機器完全停止，下一個請求要冷啟動（啟動 VM、Uvicorn、載入 app），使用者打開網站要多等好幾秒。

## Goals

- 閒置時改為 suspend：Fly 保留記憶體快照，下一個請求只要幾百毫秒就恢復。
- 費用不變：suspended 和 stopped 一樣只收儲存費，不收 CPU 與記憶體。
- 有請求時照常自動啟動，沒人使用時仍不保留任何執行中的機器。

## Non-goals

- 不改機器規格、同時請求上限或健康檢查。
- 不改備份流程：每日備份本來就先以 HTTP 請求喚醒機器，從 suspend 恢復一樣有效。

## Proposed design

- `fly.toml` 的 `[http_service]` 改為 `auto_stop_machines = "suspend"`，`auto_start_machines = true`、`min_machines_running = 0` 不變。
- 符合 Fly suspend 的條件：記憶體 ≤ 2 GB（目前 256 MB）、沒有 swap、沒有 schedule。
- SQLite 在 volume 上；Fly 文件說明 volume 與其資料不受 suspend／resume 影響，快照也不存在 volume 上。程序沒有連外的資料庫連線池，恢復後不需要重新連線。
- 快照不保證保留：部署新版本、主機搬移或平台維護後的第一個請求仍是冷啟動，行為與目前相同。

## Security and data isolation

- 不涉及使用者資料、query 或 secret；只改 Fly 代理層的閒置策略。
- 記憶體快照由 Fly 保管，與目前停機時保存的 rootfs 屬同一信任範圍。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：合併後自動部署；`release-check` 通過；閒置數分鐘後 `fly machine list` 顯示 `suspended`，再次開啟網站可正常使用。
- 回滾方式與資料相容性：把 `auto_stop_machines` 改回 `"stop"` 再部署即可，資料不受影響。

## Acceptance criteria

- [x] AC-1：Given `fly.toml`，When 部署，Then 閒置時以 suspend 停止、有請求時自動啟動、最少執行台數為 0，且機器符合 suspend 的記憶體、swap 與 schedule 條件。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_security_config.py::test_fly_suspends_the_idle_machine_within_suspend_requirements` |
