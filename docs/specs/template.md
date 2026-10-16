# SPEC-NNN：功能名稱

- 狀態：Draft
- Owner：
- 關聯 issue／ADR：

## Problem

描述使用者問題、目前行為，以及可重現或量測的證據。

## Goals

- 可驗證的目標。

## Non-goals

- 本次刻意不處理的範圍。

## Proposed design

說明 UI、API、domain/service、資料模型和外部依賴。必要時加入 Mermaid 圖。

## Security and data isolation

- 哪些資料屬於使用者？每個 query/mutation 如何限制 `user_id`？
- 是否涉及 secret、備份、外部內容或權限？

## Migration, rollout, and rollback

- Schema／資料 migration：
- 上線與 smoke test：
- 回滾方式與資料相容性：

## Acceptance criteria

- [ ] Given／When／Then 格式的可觀察行為。
- [ ] 錯誤、空資料與並行操作行為。

## Test traceability

| Acceptance criterion | Test file / command |
| --- | --- |
| AC-1 | `unit_tests/...` |

