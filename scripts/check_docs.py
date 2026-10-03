"""Fail when README harness facts drift from the repository."""

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
    source = (ROOT / "unit_tests" / "frontend_regressions.cjs").read_text(encoding="utf-8")
    return len(re.findall(r"(?m)^test\(", source))


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


def main() -> None:
    required_paths = (
        ".github/workflows/verify.yml",
        ".claude/settings.json",
        "AGENTS.md",
        "CLAUDE.md",
        "backend/agent.py",
        "backend/main.py",
        "backend/tools",
        "frontend/index.html",
        "pyproject.toml",
        "requirements-dev.txt",
        "requirements.txt",
        "scripts/claude_stop_hook.py",
        "scripts/claude_stop_hook_launcher.cjs",
        "scripts/check_docs.py",
        "scripts/task.ps1",
        "unit_tests/agent_eval_cases.json",
        "unit_tests/frontend_layout.cjs",
        "unit_tests/frontend_regressions.cjs",
    )
    for relative_path in required_paths:
        if not (ROOT / relative_path).exists():
            fail(f"documented harness path does not exist: {relative_path}")

    required_tasks = (
        "setup",
        "test-fast",
        "frontend-test",
        "frontend-layout",
        "eval-agent",
        "docs-check",
        "verify",
        "verify-all",
    )
    for task in required_tasks:
        command = f"./scripts/task.ps1 {task}"
        if command not in README:
            fail(f"README does not mention public harness command: {command}")

    documented_python, documented_frontend = documented_counts()
    actual_python = collected_pytest_count()
    actual_frontend = frontend_test_count()
    if documented_python != actual_python:
        fail(f"Python test baseline says {documented_python}, but pytest collects {actual_python}")
    if documented_frontend != actual_frontend:
        fail(
            f"frontend test baseline says {documented_frontend}, "
            f"but frontend_regressions.cjs defines {actual_frontend}"
        )

    require_readme_number(r"目前提供 (\d+) 個 Agent 工具", agent_tool_count(), "Agent tool")
    require_readme_number(r"共 (\d+) 組設定", layout_matrix_count(), "layout matrix")
    print(
        "README consistency passed: "
        f"{actual_python} Python tests, {actual_frontend} frontend tests, "
        f"{agent_tool_count()} Agent tools, {layout_matrix_count()} layout configurations."
    )


if __name__ == "__main__":
    main()
