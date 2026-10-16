"""Fail when tracked source contains strong indicators of committed credentials."""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "private key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"),
    "OpenRouter key": re.compile(rb"sk-or-v1-[A-Za-z0-9]{20,}"),
}


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    return [ROOT / item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def main() -> None:
    findings: list[str] = []
    for path in tracked_files():
        try:
            content = path.read_bytes()
        except OSError:
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(content):
                findings.append(f"{path.relative_to(ROOT)}: possible {label}")
    if findings:
        print("Secret scan failed:\n" + "\n".join(findings), file=sys.stderr)
        raise SystemExit(1)
    print(f"Secret scan passed: {len(tracked_files())} repository files checked.")


if __name__ == "__main__":
    main()
