## Spec and scope

- Feature spec／issue：
- ADR（若有重大架構取捨）：
- 本次 non-goals：

## Safety checklist

- [ ] 所有 user-owned query/mutation 都限制目前 `user_id`
- [ ] 沒有加入 secret、正式資料庫或備份檔
- [ ] Schema 變更包含 migration、備份與 rollback 說明
- [ ] API／使用者行為變更已更新 README／spec
- [ ] 新功能或 bug fix 已加入 regression test

## Verification

- [ ] `python3 scripts/task.py architecture-check`
- [ ] `python3 scripts/task.py verify`
- [ ] 若修改版面：`python3 scripts/task.py frontend-layout`
- [ ] 若準備部署：已建立備份並執行 post-deploy smoke test
