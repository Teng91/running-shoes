"""Fail when README harness facts drift from the repository."""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
sys.path.insert(0, str(ROOT))


def fail(message: str) -> None:
    print(f"README consistency error: {message}", file=sys.stderr)
    raise SystemExit(1)


def collected_pytest_count() -> int:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = result.stdout + result.stderr
    if result.returncode:
        fail(f"pytest collection failed:\n{output}")
    match = re.search(r"(\d+) tests collected", output)
    if not match:
        fail("could not read the pytest collection count")
    return int(match.group(1))


def documented_counts() -> tuple[int, int]:
    match = re.search(
        r"Python \*\*(\d+) passed\*\*、前端回歸測試 \*\*(\d+) passed\*\*",
        README,
    )
    if not match:
        fail("the Python/frontend verification baseline is missing")
    return int(match.group(1)), int(match.group(2))


def frontend_test_count() -> int:
    sources = (ROOT / "unit_tests" / "frontend").glob("*.test.cjs")
    return sum(len(re.findall(r"(?m)^test\(", path.read_text(encoding="utf-8"))) for path in sources)


def agent_tool_count() -> int:
    from backend.tools.db_tools import REGISTRY

    # Database tools live in REGISTRY; web_search is dispatched separately.
    return len(REGISTRY) + 1


def layout_matrix_count() -> int:
    source = (ROOT / "unit_tests" / "frontend_layout.cjs").read_text(encoding="utf-8")
    theme_match = re.search(r"for \(const theme of \[([^]]+)]\)", source)
    dimension_match = re.search(
        r"for \(const \[width, height] of \[(.*?)]\) \{", source,
    )
    if not theme_match or not dimension_match:
        fail("could not read the frontend layout matrix")
    themes = len(re.findall(r"['\"][^'\"]+['\"]", theme_match.group(1)))
    dimensions = len(re.findall(r"\[\d+,\s*\d+]", dimension_match.group(1)))
    engines = len(re.findall(r"await run\([^,]+,\s*['\"][^'\"]+['\"]\)", source))
    return themes * dimensions * engines


def require_readme_number(pattern: str, actual: int, label: str) -> None:
    match = re.search(pattern, README)
    if not match:
        fail(f"the documented {label} count is missing")
    documented = int(match.group(1))
    if documented != actual:
        fail(f"{label} says {documented}, but the repository has {actual}")


def release_asset_count(manifest: dict | None = None) -> int:
    from scripts.build_frontend import shell_asset_paths

    if manifest is None:
        manifest = json.loads((ROOT / "frontend" / "assets.json").read_text(encoding="utf-8"))
    # release-check verifies the generated worker as well as the shell.
    return len(shell_asset_paths(manifest)) + 1


def main() -> None:
    from scripts.document_contracts import document_errors

    errors = document_errors(ROOT)
    if errors:
        fail("\n" + "\n".join(errors))

    required_paths = (
        "docs/specs/019-reliable-requests-and-release-gates.md",
        "docs/adr/0004-request-reliability-and-release-gates.md",
        "scripts/release_check.py",
        "scripts/release_browser.cjs",
        "scripts/browser_artifacts.cjs",
        "package.json",
        "package-lock.json",
        "backend/services/run_requests.py",
        "unit_tests/frontend_reliability.cjs",
        "docs/specs/017-consistent-statistics-and-feature-lifecycles.md",
        "docs/adr/0003-shared-read-models-and-feature-lifecycles.md",
        "scripts/build_frontend.py",
        "frontend/assets.json",
        "frontend/runtime/feature-lifecycle.mjs",
        "frontend/app-lifecycle.js",
        "frontend/app-dialogs.js",
        "frontend/app-dates.js",
        "frontend/app-updates.js",
        "frontend/app-models.js",
        "frontend/app-markdown.js",
        "backend/read_models/shoes.py",
        "backend/read_models/spending.py",
        "backend/read_models/runs.py",
        "backend/shoe_metrics.py",
        "unit_tests/frontend_consistency.cjs",
        ".github/workflows/verify.yml",
        ".github/pull_request_template.md",
        ".claude/settings.json",
        "AGENTS.md",
        "CLAUDE.md",
        "docs/adr/0001-modular-monolith.md",
        "docs/adr/0002-versioned-sqlite-operations.md",
        "docs/architecture.md",
        "CHANGELOG.md",
        "docs/specs/template.md",
        "docs/specs/001-engineering-maturity.md",
        "docs/specs/002-cross-platform-task-runner.md",
        "docs/specs/003-modular-boundaries-and-browser-e2e.md",
        "docs/specs/004-app-factory-and-settings.md",
        "docs/specs/005-startup-loading-screen.md",
        "docs/specs/006-runtime-boundary-refactor.md",
        "docs/specs/012-edit-stream-and-render-safety.md",
        "docs/specs/013-auth-modal-and-module-boundaries.md",
        "docs/specs/014-offsite-backup-and-pwa-upgrades.md",
        "docs/specs/015-run-log-home.md",
        "docs/specs/016-frontend-alignment.md",
        "docs/testing-strategy.md",
        "backend/agent.py",
        "backend/agent_planner.py",
        "backend/agent_protocol.py",
        "backend/agent_tools.py",
        "backend/app_factory.py",
        "backend/exporting.py",
        "backend/main.py",
        "backend/middleware.py",
        "backend/migrations.py",
        "backend/observability.py",
        "backend/rate_limits.py",
        "backend/seeding.py",
        "backend/settings.py",
        "backend/forecasting.py",
        "backend/routers/agent.py",
        "backend/routers/auth.py",
        "backend/routers/goals.py",
        "backend/routers/health.py",
        "backend/routers/analytics.py",
        "backend/routers/exports.py",
        "backend/routers/monthly.py",
        "backend/routers/reports.py",
        "backend/routers/runs.py",
        "backend/routers/shoes.py",
        "backend/routers/spending.py",
        "backend/routers/strava.py",
        "backend/services/exports.py",
        "backend/services/mileage.py",
        "backend/services/strava_imports.py",
        "backend/strava_import.py",
        "backend/tools",
        "frontend/app.js",
        "frontend/app-boot.js",
        "frontend/app-state.js",
        "frontend/app-api.js",
        "frontend/app-auth.js",
        "frontend/app-streams.js",
        "frontend/app-core.js",
        "frontend/app-dashboard.js",
        "frontend/app-exports.js",
        "frontend/app-goals.js",
        "frontend/app-charts.js",
        "frontend/app-shoe-charts.js",
        "frontend/app-monthly-charts.js",
        "frontend/app-spending.js",
        "frontend/app-agent.js",
        "frontend/app-reports.js",
        "frontend/app-runs.js",
        "frontend/app-strava.js",
        "frontend/app-run-insights.js",
        "frontend/app-shoes.js",
        "frontend/index.html",
        "frontend/styles.css",
        "pyproject.toml",
        "requirements-dev.txt",
        "requirements-dev.in",
        "requirements.txt",
        "requirements.in",
        "scripts/claude_stop_hook.py",
        "scripts/claude_stop_hook_launcher.cjs",
        "scripts/check_docs.py",
        "scripts/check_architecture.py",
        "scripts/check_secrets.py",
        "scripts/database_backup.py",
        "scripts/offsite_backup.py",
        "scripts/smoke_test.py",
        "scripts/task.py",
        "unit_tests/test_task_runner.py",
        "unit_tests/test_app_factory.py",
        "unit_tests/agent_eval_cases.json",
        "unit_tests/api_contract.json",
        "unit_tests/frontend_layout.cjs",
        "unit_tests/frontend_e2e.cjs",
        "unit_tests/frontend_pwa.cjs",
        "unit_tests/fixtures/service-worker-v3.2.2.js",
        "unit_tests/test_offsite_backup.py",
        "unit_tests/frontend_regressions.cjs",
        "unit_tests/frontend_safety.cjs",
        "unit_tests/test_forecasting.py",
    )
    for relative_path in required_paths:
        if not (ROOT / relative_path).exists():
            fail(f"documented harness path does not exist: {relative_path}")

    required_tasks = (
        "setup",
        "test-fast",
        "frontend-test",
        "frontend-layout",
        "frontend-e2e",
        "frontend-pwa",
        "eval-agent",
        "audit-deps",
        "architecture-check",
        "security-check",
        "docs-check",
        "verify",
        "verify-all",
        "release-check",
    )
    for task in required_tasks:
        command = f"python3 scripts/task.py {task}"
        if command not in README:
            fail(f"README does not mention public harness command: {command}")

    legacy_terms = ("task.ps1", "pwsh", "PowerShell")
    checked_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            ROOT / "README.md",
            ROOT / "AGENTS.md",
            ROOT / "docs" / "testing-strategy.md",
            ROOT / ".github" / "pull_request_template.md",
            ROOT / ".github" / "workflows" / "verify.yml",
        )
    )
    for term in legacy_terms:
        if term in checked_text:
            fail(f"deprecated platform-specific runner reference remains: {term}")

    documented_python, documented_frontend = documented_counts()
    actual_python = collected_pytest_count()
    actual_frontend = frontend_test_count()
    if documented_python != actual_python:
        fail(f"Python test baseline says {documented_python}, but pytest collects {actual_python}")
    if documented_frontend != actual_frontend:
        fail(
            f"frontend test baseline says {documented_frontend}, "
            f"but frontend feature suites define {actual_frontend}"
        )

    require_readme_number(r"目前提供 (\d+) 個 Agent 工具", agent_tool_count(), "Agent tool")
    require_readme_number(r"共 (\d+) 組設定", layout_matrix_count(), "layout matrix")
    require_readme_number(
        r"manifest 對應的 (\d+) 個 shell／worker 資產", release_asset_count(), "release asset"
    )
    print(
        "README consistency passed: "
        f"{actual_python} Python tests, {actual_frontend} frontend tests, "
        f"{agent_tool_count()} Agent tools, {layout_matrix_count()} layout configurations, "
        f"{release_asset_count()} release assets."
    )


if __name__ == "__main__":
    main()
