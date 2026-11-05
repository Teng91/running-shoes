"""Browser test harness invariants that keep E2E waits meaningful."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASYNC_WAIT = re.compile(r"waitForFunction\(\s*async\b")


def test_browser_waits_never_pass_async_predicates_to_wait_for_function():
    # Playwright treats the Promise returned by an async predicate as truthy and resolves
    # immediately, which let offline-queue checks race their IndexedDB writes (flaky WebKit CI).
    offenders = [
        f"{path.relative_to(ROOT)}:{number}"
        for folder in ("unit_tests", "scripts")
        for path in sorted((ROOT / folder).glob("*.cjs"))
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if ASYNC_WAIT.search(line)
    ]
    assert offenders == [], "use waitForAsync from unit_tests/browser_waits.cjs: " + ", ".join(offenders)
