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
    for trigger in ("push:", "pull_request:", "schedule:", "workflow_dispatch:"):
        assert re.search(rf"^  {trigger}$", WORKFLOW, re.M)
    deploy = workflow_jobs["deploy"]
    assert ("    if: github.ref == 'refs/heads/main' && (github.event_name == 'push' "
            "|| github.event_name == 'workflow_dispatch')") in deploy
    assert needs(deploy) == TEST_JOBS
    assert needs(workflow_jobs["release-check"]) == {"deploy"}
    assert needs(workflow_jobs["release"]) == {"release-check"}


def test_ci_tests_every_push_pull_request_and_weekly_schedule_including_docs():
    """SPEC-061: every branch push, PR merge result and a weekly run get the full harness;
    documentation-only changes are no longer skipped, so docs-check always guards them."""
    triggers = WORKFLOW.split("\non:\n", 1)[1].split("\n\n", 1)[0]
    assert triggers == ('  push:\n  pull_request:\n  schedule:\n    - cron: "0 1 * * 1"\n'
                        "  workflow_dispatch:")
    assert "paths-ignore" not in WORKFLOW and "branches:" not in triggers
    # A scheduled or branch run never deploys: only push/dispatch on main does.
    assert "github.event_name == 'schedule'" not in jobs()["deploy"]


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
    production = "github.event_name != 'pull_request' && github.ref == 'refs/heads/main'"
    assert (f"  group: ${{{{ {production} && 'production' "
            "|| format('ci-{0}-{1}', github.event_name, github.ref) }}") in WORKFLOW
    # Main never cancels a running deploy; a newer push on another ref supersedes the older run.
    assert f"  cancel-in-progress: ${{{{ !({production}) }}}}" in WORKFLOW


def test_browser_jobs_retry_once_with_a_visible_warning():
    workflow_jobs = jobs()
    for job, command in (("frontend-layout", "frontend-layout"), ("frontend-e2e", "frontend-e2e"),
                         ("frontend-pwa", "frontend-pwa"),
                         ("release-check", "release-check --base-url https://running-shoes.fly.dev")):
        task = command.split()[0]
        assert (f'python scripts/task.py {command} || {{ echo "::warning::{task} failed once; retrying"; '
                f"python scripts/task.py {command}; }}") in workflow_jobs[job], job
    assert "||" not in workflow_jobs["verify"], "unit, lint and docs checks are deterministic and never retried"


def test_main_ruleset_requires_a_green_pull_request_without_bypass():
    """SPEC-061: the versioned ruleset applied to main matches the workflow's test jobs."""
    ruleset = json.loads((ROOT / ".github" / "rulesets" / "main.json").read_text(encoding="utf-8"))
    assert ruleset["enforcement"] == "active" and ruleset["bypass_actors"] == []
    assert ruleset["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"]
    rules = {rule["type"]: rule.get("parameters", {}) for rule in ruleset["rules"]}
    assert {"deletion", "non_fast_forward", "pull_request", "required_status_checks"} <= set(rules)
    checks = rules["required_status_checks"]
    assert checks["strict_required_status_checks_policy"] is True
    assert {check["context"] for check in checks["required_status_checks"]} == TEST_JOBS
    assert {check["integration_id"] for check in checks["required_status_checks"]} == {15368}


OFFSITE = (ROOT / ".github" / "workflows" / "offsite-backup.yml").read_text(encoding="utf-8").replace("\r\n", "\n")


def test_daily_offsite_backup_uploads_only_an_encrypted_archive():
    """SPEC-078: the public repository's artifacts must never hold the plain database."""
    code = "\n".join(line for line in OFFSITE.splitlines() if not line.lstrip().startswith("#"))
    assert re.search(r'^  schedule:\n    - cron: "30 19 \* \* \*"', code, re.M)
    assert "workflow_dispatch:" in code
    assert re.search(r"^permissions:\n  contents: read$", code, re.M) and "contents: write" not in code
    steps = code.split("    steps:\n", 1)[1]
    # The passphrase check is the first step, before any data leaves Fly.
    assert steps.index("BACKUP_PASSPHRASE}\" -lt 20") < steps.index("offsite_backup.py")
    assert "exit 1" in steps.split("- uses: actions/checkout", 1)[0]
    assert "openssl enc -aes-256-cbc -salt -pbkdf2 -iter 600000 -pass env:BACKUP_PASSPHRASE" in steps
    assert 'rm -rf "$RUNNER_TEMP/offsite"' in steps
    upload = steps.split("actions/upload-artifact", 1)[1]
    assert "path: ${{ runner.temp }}/upload/*.tar.gz.enc" in upload
    assert "retention-days: 30" in upload and "if-no-files-found: error" in upload
    assert steps.index("openssl enc -d") < steps.index("actions/upload-artifact"), "decrypt check before upload"
    assert '--output-dir "$RUNNER_TEMP/offsite"' in steps, "plain snapshots stay outside the checkout"
    assert "persist-credentials: false" in steps
    # SPEC-078 (v4.20.4): grep -q must not close tar's pipe early under pipefail.
    assert "tar -tzf - | grep -Eq" not in steps and 'listing=$(openssl enc -d' in steps
    for part in (r"\.db$", r"manifest\.json$"):
        assert part in steps, part
    for leak in ("cat ", "sqlite3", "row_counts", "set -x"):
        assert leak not in steps, leak


def test_offsite_backup_keeps_every_scheduled_workflow_enabled():
    """SPEC-116: GitHub disables schedules after 60 days without a commit; re-enable them daily."""
    code = "\n".join(line for line in OFFSITE.splitlines() if not line.lstrip().startswith("#"))
    backup, keepalive = code.split("\n  keep-schedules-enabled:\n", 1)
    assert "actions: write" not in backup, "the job that touches production keeps read-only permissions"
    assert re.search(r"^    permissions:\n      actions: write$", keepalive, re.M)
    assert "needs:" not in keepalive, "the re-enable runs even when the backup fails"
    assert "GH_TOKEN: ${{ github.token }}" in keepalive and "secrets." not in keepalive
    assert 'gh api -X PUT "repos/$GITHUB_REPOSITORY/actions/workflows/$workflow/enable"' in keepalive
    assert "::warning::" in keepalive and "exit 1" not in keepalive, "a failed re-enable only warns"
    enabled = set(re.search(r"for workflow in ([^;]+);", keepalive).group(1).split())
    scheduled = {
        path.name
        for path in (ROOT / ".github" / "workflows").glob("*.yml")
        if re.search(r"^  schedule:$", path.read_text(encoding="utf-8"), re.M)
    }
    assert scheduled == enabled == {"offsite-backup.yml", "verify.yml"}


def test_every_action_from_another_repository_is_pinned_to_a_commit():
    """SPEC-087: a moved tag must not change what runs next to FLY_API_TOKEN or BACKUP_PASSPHRASE.

    Dependabot (``.github/dependabot.yml``) updates the commit and its release comment together.
    """
    remote = []
    for path in sorted((ROOT / ".github").rglob("*.yml")):
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^\s*(?:- )?uses: (\S+)(.*)$", line)
            if match and not match.group(1).startswith("./"):
                remote.append((path.name, match.group(1), match.group(2)))
    assert len(remote) > 10, remote
    for name, action, comment in remote:
        assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", action), f"{name}: {action} is not pinned to a commit"
        assert re.fullmatch(r" # v?\d+(?:[.]\d+)*", comment), f"{name}: {action} must name its release"
