"""SPEC-089: vendored browser libraries stay tracked by the npm lockfile and its audit."""

import json
import re
from pathlib import Path

import pytest

from scripts import task

ROOT = Path(__file__).resolve().parents[1]
VENDORED = {
    # npm package: (vendored file, header pattern, file inside the npm package)
    "chart.js": ("chart.umd.min.js", r"Chart\.js v(\S+)", "dist/chart.umd.js"),
    "marked": ("marked.min.js", r"marked v(\S+) - a markdown parser", "marked.min.js"),
}


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


@pytest.mark.parametrize("package", sorted(VENDORED))
def test_each_vendored_library_is_pinned_at_its_vendored_version(package):
    vendored, pattern, _ = VENDORED[package]
    version = re.search(pattern, _text(ROOT / "frontend" / "vendor" / vendored)).group(1)
    manifest = json.loads(_text(ROOT / "package.json"))
    lock = json.loads(_text(ROOT / "package-lock.json"))
    assert manifest["devDependencies"][package] == version, "update package.json with the vendored file"
    assert lock["packages"][f"node_modules/{package}"]["version"] == version
    assert lock["packages"][f"node_modules/{package}"]["resolved"].startswith("https://registry.npmjs.org/")


@pytest.mark.parametrize("package", sorted(VENDORED))
def test_each_vendored_file_is_the_published_release_when_installed(package):
    vendored, _, published = VENDORED[package]
    installed = ROOT / "node_modules" / package / published
    if not installed.is_file():
        pytest.skip("npm ci has not installed the package")
    text = _text(ROOT / "frontend" / "vendor" / vendored)
    # jsDelivr prepends a "Skipped minification" note before the package's own banner.
    if text.startswith("/**\n * Skipped minification"):
        text = text[text.index("*/\n") + 3:]
    assert text == _text(installed)


def test_dependency_audits_cover_python_and_the_npm_lockfile():
    labels = [command.label for command in task.verification_commands()]
    audits = task.dependency_audit_commands()
    assert [command.label for command in audits] == [
        "Dependency vulnerability audit", "npm dependency vulnerability audit"]
    assert all(command.label in labels for command in audits), "verify runs both audits"
    assert audits[1].arguments[1:] == ("audit", "--package-lock-only", "--audit-level=moderate")
