"""SPEC-048: pushes to main deploy, check and release in a safe, least-privilege order."""

import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github" / "workflows" / "verify.yml").read_text(encoding="utf-8").replace("\r\n", "\n")
TEST_JOBS = {"verify", "frontend-layout", "frontend-e2e", "frontend-pwa", "diagnostics-roundtrip"}


def jobs() -> dict[str, str]:
    """Each job's lines without YAML comments (comments may name secrets they explain)."""
    body = WORKFLOW.split("\njobs:\n", 1)[1]
    parts = re.split(r"^  ([a-z][a-z0-9-]*):\n", body, flags=re.M)
    return {
        name: "\n".join(line for line in block.splitlines() if not line.lstrip().startswith("#"))
        for name, block in zip(parts[1::2], parts[2::2], strict=True)
    }


def needs(block: str) -> set[str]:
    match = re.search(r"^    needs: (?:\[(.*)\]|(\S+))$", block, re.M)
    assert match, block
    return {item.strip() for item in (match.group(1) or match.group(2)).split(",")}


def test_deploy_runs_only_for_main_after_every_test_job():
    workflow_jobs = jobs()
    assert set(workflow_jobs) == TEST_JOBS | {"deploy", "release-check", "release"}
    for trigger in ("push:", "pull_request:", "workflow_dispatch:"):
        assert re.search(rf"^  {trigger}$", WORKFLOW, re.M)
    deploy = workflow_jobs["deploy"]
    assert ("    if: github.ref == 'refs/heads/main' && (github.event_name == 'push' "
            "|| github.event_name == 'workflow_dispatch')") in deploy
    assert needs(deploy) == TEST_JOBS
    assert needs(workflow_jobs["release-check"]) == {"deploy"}
    assert needs(workflow_jobs["release"]) == {"release-check"}


def test_only_the_deploy_job_receives_the_fly_token():
    workflow_jobs = jobs()
    for name, block in workflow_jobs.items():
        if name != "deploy":
            assert "secrets." not in block, name
    deploy = workflow_jobs["deploy"]
    assert deploy.count("FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}") == 3
    for forbidden in ("npm ", "pip install", "scripts/task.py", "browser-setup", "setup-python", "setup-node"):
        assert forbidden not in deploy, forbidden
    assert "persist-credentials: false" in deploy
    assert "persist-credentials: false" in workflow_jobs["release-check"]
    assert re.search(r"^permissions:\n  contents: read$", WORKFLOW, re.M)
    assert WORKFLOW.count("contents: write") == 1 and "contents: write" in workflow_jobs["release"]


def test_deploy_takes_a_verified_database_snapshot_before_deploying():
    deploy = jobs()["deploy"]
    snapshot = deploy.index("python scripts/database_backup.py create --source /data/shoes.db")
    assert deploy.index("Require the deploy token") < snapshot < deploy.index("flyctl deploy --remote-only --ha=false")
    assert 'grep -q "Backup created and verified: " snapshot.log' in deploy
    # The remote command, path and success line match what the image actually ships.
    assert 'print(f"Backup created and verified: {path}")' in (ROOT / "scripts" / "database_backup.py").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^COPY scripts/database_backup\.py .*scripts/$", dockerfile, re.M)
    assert "ENV DB_DIR=/data" in dockerfile
    assert 'app = "running-shoes"' in (ROOT / "fly.toml").read_text(encoding="utf-8")
    assert "FLY_APP: running-shoes" in deploy


def test_release_tags_only_new_versions_after_the_release_check():
    release = jobs()["release"]
    assert release.index('git rev-parse -q --verify "refs/tags/$TAG"') < release.index('git tag -a "$TAG"')
    assert 'gh release create "$TAG" --title "$TAG" --notes-file release-notes.md --verify-tag' in release
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    assets = json.loads((ROOT / "frontend" / "assets.json").read_text(encoding="utf-8"))["version"]
    assert package == assets, "the release job refuses to tag disagreeing versions"

    script = textwrap.dedent(WORKFLOW.split("<<'PY'\n", 1)[1].split("\n          PY\n", 1)[0])

    def notes(version: str) -> subprocess.CompletedProcess:
        # The release job runs on a UTF-8 Linux runner; match it on Windows code pages too.
        return subprocess.run([sys.executable, "-c", script, version], cwd=ROOT, capture_output=True,
                              text=True, encoding="utf-8", check=True,
                              env={**os.environ, "PYTHONIOENCODING": "utf-8"})

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    start = changelog.index(f"## [{package}]")
    body = changelog[changelog.index("\n", start) + 1:changelog.index("\n## [", start + 1)]
    assert notes(package).stdout == "\n" + body.strip() + "\n\n"
    missing = notes("0.0.0-unreleased")
    assert missing.stdout.startswith("## Changes\n\n- ") and "no section for 0.0.0-unreleased" in missing.stderr


def test_production_runs_are_serialized_without_cancelling():
    assert ("  group: ${{ github.event_name != 'pull_request' && github.ref == 'refs/heads/main' "
            "&& 'production' || format('ci-{0}', github.run_id) }}") in WORKFLOW
    assert re.search(r"^concurrency:\n  group: .*\n  cancel-in-progress: false$", WORKFLOW, re.M)


def test_browser_jobs_retry_once_with_a_visible_warning():
    workflow_jobs = jobs()
    for job, command in (("frontend-layout", "frontend-layout"), ("frontend-e2e", "frontend-e2e"),
                         ("frontend-pwa", "frontend-pwa"),
                         ("release-check", "release-check --base-url https://running-shoes.fly.dev")):
        task = command.split()[0]
        assert (f'python scripts/task.py {command} || {{ echo "::warning::{task} failed once; retrying"; '
                f"python scripts/task.py {command}; }}") in workflow_jobs[job], job
    assert "||" not in workflow_jobs["verify"], "unit, lint and docs checks are deterministic and never retried"
