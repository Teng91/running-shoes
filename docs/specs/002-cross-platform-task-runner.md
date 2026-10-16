# SPEC-002：跨平台工程 Task Runner

- 狀態：Implemented
- Owner：Repository maintainer
- 關聯文件：`docs/testing-strategy.md`

## Problem

原本的 repository harness 由特定 shell 腳本實作，Linux、macOS 或未安裝該 shell 的環境
無法直接執行。CI、Coding Agent hook 與本機指令也各自維護部分驗證步驟，容易產生漂移。

## Goals

- 以 Python 3.11+ 提供 Windows、macOS、Linux 共用的 task runner。
- 本機、Coding Agent 與 GitHub Actions 使用相同的 `scripts/task.py` 實作。
- 保留既有 task 名稱、coverage 門檻及 Playwright optional/required 行為。
- 自動尋找 Windows `venv/Scripts/python.exe`、Unix `venv/bin/python`，否則使用目前 Python。
- 文件檢查阻止已淘汰的 runner 名稱重新出現在公開開發流程。

## Non-goals

- 不取代 pytest、Ruff、mypy、pip-audit、Node 或 Playwright。
- 不將正式部署或資料庫操作加入一般 verification task。
- 不要求使用者啟用 virtual environment 才能呼叫 runner。

## Acceptance criteria

- [x] `python3 scripts/task.py verify-all` 可在 Unix 環境完整執行，Windows 使用相同腳本。
- [x] CI 不指定平台專屬 shell，直接呼叫 Python runner。
- [x] Coding Agent hook 的一般驗證委派給同一個 Python runner。
- [x] `frontend-layout` 缺少 Playwright 時明確失敗；`verify-all` 則警告並跳過。
- [x] README、AGENTS、PR template 與測試策略只公開跨平台指令。
- [x] Runner 的 task 清單、虛擬環境選擇及 verify-all 組合有回歸測試。

## Test traceability

| Acceptance criterion | Test / check |
| --- | --- |
| Task 清單與 verify-all 組合 | `unit_tests/test_task_runner.py` |
| Windows／Unix venv 選擇 | `unit_tests/test_task_runner.py` |
| CI 與文件不再依賴平台 shell | `test_task_runner.py`, `scripts/check_docs.py` |
| 實際端到端 runner | `python3 scripts/task.py verify-all` |
