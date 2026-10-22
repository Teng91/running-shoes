# SPEC-021：認證競態與發布資產數量契約

- 狀態：Implemented
- Owner：Running Shoes maintainers
- 關聯 issue／ADR：SPEC-020、ADR-0005

## Problem

同帳號並行改密碼會以舊 ORM 快照覆寫相同 token_version，中途發出的憑證可能繼續有效。
註冊以程序內 Lock 包住 count／insert，跨程序仍可突破容量或使同名請求出現 unique 錯誤。
README 的 release-check 資產數量仍為 39，manifest 實際已達 40，docs-check 未涵蓋此數字。

## Goals

- 過期改密碼請求不得覆寫新密碼；成功更新原子遞增登入版本，撤銷先前憑證。
- 第一個帳號在內的註冊容量及同名檢查，皆由跨程序有效的資料庫交易保護。
- 文件中的 shell／worker 資產數量與發布檢查使用相同 manifest 來源。

## Non-goals

- 不新增 endpoint、密碼政策、資料表或部署拓撲。
- 不修改已發布 v3.5.0 tag，亦不把測試通過宣稱為零缺陷保證。

## Proposed design

- 改密碼在驗證後保存舊 hash／版本，以條件 UPDATE 原子增加版本；失敗回 409 並要求重新登入，交易失敗 rollback。
- 註冊在鎖外計算 hash，再由 write_transaction 的無 user 模式取得 SQLite writer reservation；以不可能命中的 User primary key NULL predicate 做 no-op UPDATE，空資料庫也能先鎖後讀。
- 移除 registration process Lock；鎖內檢查 username／容量並新增，維持同名 400、容量 403。
- docs-check 依 shell_asset_paths(manifest) 加 worker 取得數量，檢查 README 明確的資產數字，並以錯誤數量／新增 module 的負例驗證。

## Security and data isolation

- 改密碼依已驗證帳號 id、原 hash 及 token_version 限制更新；不回傳密碼或 hash。
- writer reservation 不改變任何帳號欄位，不重設 token_version；全域容量保護僅適用註冊。
- 測試限合成帳號、暫存 SQLite 及獨立程序；不使用 shoes.db 或正式帳號。

## Migration, rollout, and rollback

- Schema／資料 migration：無，維持 schema 2。
- 上線與 smoke test：核心修正 verify-all 通過，v3.5.1／shell v27 發布產物另執行 verify 與 CI browser gates；部署前驗證異地備份，部署後執行匿名 release-check。
- 回滾方式與資料相容性：程式可回滾；已增加的 token_version 仍保留，不還原舊憑證。

## Acceptance criteria

- [x] AC-1：Given 兩次改密碼都驗證同一舊密碼，When 第一個成功且中途登入後第二個完成，Then 第二個回 409、不覆寫密碼或降低登入版本；後續合法改密碼再次撤銷中途憑證。
- [x] AC-2：Given 空暫存資料庫與註冊容量 1，When 獨立程序同時註冊不同帳號，Then 只有一個 200，另一個 403，最後僅一個帳號。
- [x] AC-3：Given 獨立程序同時註冊同名帳號且容量足夠，When 交易完成，Then 一個 200、一個 400，沒有 500；失敗交易可 rollback。
- [x] AC-4：Given README 數量錯誤或 manifest 新增 module，When docs-check 執行，Then 拒絕過期數字；正確數字通過。

## Test traceability

| Acceptance criterion | Test file / command |
| --- | --- |
| AC-1 | `unit_tests/test_auth_concurrency.py` |
| AC-2 / AC-3 | `unit_tests/test_auth_concurrency.py` |
| AC-4 | `unit_tests/test_docs_harness.py`、`python3 scripts/task.py docs-check` |

## Verification record

2026-10-22：三個新增認證競態案例在 v3.5.0 archive 上均失敗（改密碼 200 取代 409、
容量 1 卻出現兩個 200、同名註冊出現 500），修正後全部通過。
核心修正 `verify-all` 完整通過：449 Python／81 Node、95.21% backend branch coverage、
40 組版面與雙引擎 E2E／PWA，無瀏覽器依賴跳過。
v3.5.1 發布產物的 `verify` 通過；文件負例另直接執行 docs-check entry point，拒絕過期數量。
正式部署前異地快照 checksum／隔離還原演練通過；CI、image 與部署後匿名 release-check 結果記錄於 v3.5.1 GitHub Release。
