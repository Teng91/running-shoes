"""Hash-locked dependency files must install on every supported platform."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _requirements(name: str) -> dict[str, str]:
    """Map each pinned package name to its environment marker ("" if none)."""
    entries = {}
    for line in (ROOT / name).read_text(encoding="utf-8").splitlines():
        if "==" not in line or line.startswith((" ", "#")):
            continue
        requirement, _, marker = line.rstrip(" \\").partition(";")
        package = requirement.split("==", 1)[0].split("[", 1)[0].strip().lower()
        entries[package] = marker.strip()
    return entries


@pytest.mark.parametrize("name", ["requirements.txt", "requirements-dev.txt"])
def test_posix_only_wheels_are_excluded_on_windows(name):
    # uvloop has no Windows build; an unconditional pin breaks `task.py setup` there.
    assert "sys_platform != 'win32'" in _requirements(name)["uvloop"]


def test_windows_only_dependencies_are_hash_locked():
    # pytest needs colorama on Windows; --require-hashes rejects unlocked transitive deps.
    assert _requirements("requirements-dev.txt")["colorama"] == "sys_platform == 'win32'"
