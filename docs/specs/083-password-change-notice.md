# SPEC-083：密碼變更通知信

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：[SPEC-079](079-email-recovery.md)、[SPEC-080](080-account-cleanup.md)

## Problem

- 密碼被更改或重設時，帳號主人不會收到任何通知；帳號被盜時可能很久之後才發現。

## Goals

- 三種情況都寄信到綁定的 email：登入後更改密碼、用 email 驗證碼重設、管理員產生臨時密碼。
- 信裡寫明帳號、時間（台灣時間）、方式，以及不是本人操作時該怎麼做。

## Non-goals

- 沒有綁定 email 的帳號不寄。
- 不做登入通知或其他事件通知。

## Proposed design

- `services/email_codes.notify_password_changed(db, identifier, how, send, when)`：以帳號或 email 找到使用者，有 email 才寄；`how` 為 `changed`／`email_reset`／`admin_reset`。
- `mailer.deliver_later(mailer, schedule)`：把寄信排在回應之後（BackgroundTasks），寄信失敗只記 log，不影響已完成的密碼變更；忘記密碼的驗證碼也改用它。
- `routers/auth.change_password`、`confirm_password_reset` 與 `routers/admin.reset_password` 在服務成功後呼叫 `routers/auth.notify_password_changed`；沒有設定 SMTP 時不寄。

## Security and data isolation

- 只寄到該帳號自己綁定且驗證過的 email；內容不含新密碼或驗證碼。
- 失敗的更改（密碼錯誤等）不寄信。

## Migration, rollout, and rollback

- Schema／資料 migration：無。
- 上線與 smoke test：綁定 email 的帳號更改密碼後收到通知信。
- 回滾方式與資料相容性：可直接回滾到 v4.22.0 image。

## Acceptance criteria

- [x] AC-1：Given 已綁定 email 的帳號，When 更改密碼、用 email 驗證碼重設或管理員產生臨時密碼，Then 各寄一封通知信，內容含帳號、台灣時間、方式與處理方式。
- [x] AC-2：Given 沒有 email 的帳號或寄信失敗，When 更改密碼，Then 不寄或寄失敗，但更改照常成功；密碼錯誤的請求不寄信。

## Test traceability

| Acceptance criterion | Named test / command |
| --- | --- |
| AC-1 | `unit_tests/test_email_recovery.py::test_every_password_change_notifies_the_bound_email` |
| AC-2 | `unit_tests/test_email_recovery.py::test_no_notice_without_an_email_and_mail_failures_do_not_block_the_change` |
