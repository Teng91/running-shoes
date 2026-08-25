# Eval-driven bug-fixing loop

## Targets

- All tests pass.
- Overall line coverage >= 90%.
- Overall branch coverage >= 85%.
- `backend/agent.py`, `backend/llm.py`, and `backend/tools/db_tools.py` coverage >= 95%.
- Ruff and mypy pass.
- The full test suite passes three consecutive times.
- No known reproducible bug remains unfixed.

## Baseline

- Tests: 144 passed.
- Overall line coverage: 100%.
- Overall branch coverage: 100%.
- Core module coverage: 100% for all three target modules.
- Ruff: 89 findings.
- mypy: 11 findings after resolving package discovery with `--explicit-package-bases`.

## Iteration 1 — missing database context in agent tool calls

- Failure: a database tool call with `db=None` or `user_id=None` raised an uncaught
  `AttributeError` and terminated the SSE generator.
- Regression test: `test_database_tool_without_request_context_reports_stream_error`.
- Pre-fix evidence: failed with `AttributeError: 'NoneType' object has no attribute 'query'`.
- Fix: emit a user-facing SSE `error` followed by `done` before dispatching a database tool
  without request context.
- Focused result: 15 Agent tests passed.

## Iteration 2 — reproducible lint and type-check configuration

- Added explicit Ruff, mypy, and pytest configuration in `pyproject.toml`.
- Ruff and mypy target Python 3.11 to match the production Docker image.
- Added reproducible development-only dependencies in `requirements-dev.txt`.
- `B008` is excluded because FastAPI dependency injection intentionally uses calls in
  parameter defaults; all other selected rules remain enforced.
- Normalized imports and modern Python 3.12 annotations.
- Replaced ambiguous exception handling where a specific exception is available and
  documented the two intentional third-party exception boundaries.
- Added timezone awareness to generated export timestamps.
- Replaced the root logger with a module logger.
- Separated CSV `StringIO` and XLSX `BytesIO` variables and narrowed the worksheet type.
- Ruff result: passed with no findings.
- mypy result: passed for all 10 backend source files.
- Full suite result: 145 passed.

## Final coverage

- Overall line coverage: 956/958 = 99.79%.
- Overall branch coverage: 264/266 = 99.25%.
- `backend/agent.py`: 121/122 lines and 47/48 branches covered (98.82% combined).
- `backend/llm.py`: 133/133 lines and 40/40 branches covered (100%).
- `backend/tools/db_tools.py`: 130/130 lines and 40/40 branches covered (100%).

The two uncovered defensive paths are the direct `_execute_tool` missing-context fallback
(the public stream path is covered) and the impossible-by-default openpyxl state where a new
workbook has no active worksheet. Both target-module coverage requirements remain above 95%.

## Final verification

- `python -m pytest --cov=backend --cov-branch --cov-report=term-missing`: 145 passed.
- `python -m pytest -q`, three consecutive runs: 145 passed each time.
- `python -m ruff check backend unit_tests`: passed.
- `python -m mypy backend`: passed, 10 source files checked.
- `python -m pip check`: no broken requirements.
- `python -m compileall -q backend unit_tests`: passed.
- `git diff --check`: passed.

## Remaining risks

- Development mode intentionally emits a warning and uses a fallback JWT secret when
  `SECRET_KEY` is absent. Production-like environments still fail fast without the variable.
- Automated tests cannot prove the absence of every possible defect; no known reproducible
  defect remains after this loop.
