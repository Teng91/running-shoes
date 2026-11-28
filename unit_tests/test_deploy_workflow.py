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
    assert set(workflow_jobs) == TEST_JOBS | {"deploy", "release-check", "rollback", "release"}
    for trigger in ("push:", "pull_request:", "schedule:", "workflow_dispatch:"):
        assert re.search(rf"^  {trigger}$", WORKFLOW, re.M)
    deploy = workflow_jobs["deploy"]
    assert ("    if: github.ref == 'refs/heads/main' && (github.event_name == 'push' "
            "|| github.event_name == 'workflow_dispatch')") in deploy
    assert needs(deploy) == TEST_JOBS
    assert needs(workflow_jobs["release-check"]) == {"deploy"}
    assert needs(workflow_jobs["release"]) == {"release-check"}
    assert needs(workflow_jobs["rollback"]) == {"deploy", "release-check"}


def test_ci_tests_every_push_pull_request_and_weekly_schedule_including_docs():
    """SPEC-061: every branch push, PR merge result and a weekly run get the full harness;
    documentation-only changes are no longer skipped, so docs-check always guards them."""
    triggers = WORKFLOW.split("\non:\n", 1)[1].split("\n\n", 1)[0]
    assert triggers == ('  push:\n  pull_request:\n  schedule:\n    - cron: "0 1 * * 1"\n'
                        "  workflow_dispatch:")
    assert "paths-ignore" not in WORKFLOW and "branches:" not in triggers
    # A scheduled or branch run never deploys: only push/dispatch on main does.
    assert "github.event_name == 'schedule'" not in jobs()["deploy"]


def test_only_the_deploy_and_rollback_jobs_receive_the_fly_token():
    workflow_jobs = jobs()
    for name, block in workflow_jobs.items():
        if name not in {"deploy", "rollback"}:
            assert "secrets." not in block, name
    deploy, rollback = workflow_jobs["deploy"], workflow_jobs["rollback"]
    assert deploy.count("FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}") == 4
    assert rollback.count("secrets.") == rollback.count("FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}") == 1
    for block in (deploy, rollback):
        for forbidden in ("npm ", "pip install", "scripts/task.py", "browser-setup", "setup-python", "setup-node"):
            assert forbidden not in block, forbidden
        assert "persist-credentials: false" in block
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
    """SPEC-144: a passing retry still leaves a warning, a summary line and the first attempt."""
    workflow_jobs = jobs()
    for job, command in (("frontend-layout", "frontend-layout"), ("frontend-e2e", "frontend-e2e"),
                         ("frontend-pwa", "frontend-pwa"),
                         ("release-check", "release-check --base-url https://running-shoes.fly.dev")):
        task = command.split()[0]
        block = workflow_jobs[job]
        script = "\n".join((
            f"python scripts/task.py {command} && exit 0",
            f'          echo "::warning::{task} failed once; retrying"',
            '          echo "retried=true" >> "$GITHUB_OUTPUT"',
            f'          echo "{task} failed its first attempt and was retried." >> "$GITHUB_STEP_SUMMARY"',
        ))
        assert script in block, job
        assert block.rstrip().count(f"python scripts/task.py {command}") == 2, job
        if job != "release-check":
            move = "mv .artifacts/browser .artifacts/browser-first-attempt"
            assert block.index(move) < block.rindex(f"python scripts/task.py {command}"), job
            upload = block.split("Save the first attempt of a retried run", 1)[1]
            assert "if: always() && steps.attempt.outputs.retried == 'true'" in upload
            assert f"name: {task}-first-attempt" in upload and "path: .artifacts/browser-first-attempt/" in upload
    assert "||" not in workflow_jobs["verify"], "unit, lint and docs checks are deterministic and never retried"


def test_a_failed_release_check_rolls_back_only_when_the_schema_did_not_move():
    """SPEC-144: the previous image comes back automatically; a migration needs the manual script."""
    workflow_jobs = jobs()
    deploy, rollback = workflow_jobs["deploy"], workflow_jobs["rollback"]
    record = deploy.index("Record the running release for a rollback")
    assert deploy.index("Wake the production machine") < record < deploy.index("flyctl deploy --remote-only")
    assert "flyctl machine list -a \"$FLY_APP\" --json | jq -r '[.[].config.image] | unique" in deploy
    assert "jq -r '.schema_version // \"\"'" in deploy
    assert "previous_image: ${{ steps.previous.outputs.image }}" in deploy
    assert ("    if: always() && needs.deploy.result == 'success' && needs.release-check.result == 'failure'"
            in rollback)
    script = rollback.split("run: |", 1)[1]
    schema_check = script.index('if [ "$schema" != "$PREVIOUS_SCHEMA" ]; then')
    assert script.index('if [ -z "$PREVIOUS_IMAGE" ] || [ -z "$PREVIOUS_SCHEMA" ]; then') < schema_check
    assert schema_check < script.index('flyctl deploy --image "$PREVIOUS_IMAGE" --rollback --ha=false')
    assert script.count("exit 1") == 2
    # The schema this commit would migrate to is read from the source it deployed.
    command = "grep -oE '^CURRENT_SCHEMA_VERSION = [0-9]+$' backend/migrations.py | grep -oE '[0-9]+$'"
    assert command in script
    from backend import migrations
    source = (ROOT / "backend" / "migrations.py").read_text(encoding="utf-8")
    assert re.findall(r"^CURRENT_SCHEMA_VERSION = ([0-9]+)$", source, re.M) == [str(migrations.CURRENT_SCHEMA_VERSION)]


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


def test_image_ships_every_rollback_script_and_pins_its_base_by_digest():
    """SPEC-134: a production rollback needs no file transfer, and every build gets the same base."""
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    copy = re.search(r"^COPY scripts/database_backup\.py (.*) scripts/$", dockerfile, re.M)
    assert copy is not None and "scripts/*.sql" in copy.group(1).split()
    documented = set(re.findall(r"scripts/(rollback_[a-z_]+\.sql)", (ROOT / "AGENTS.md").read_text(encoding="utf-8")))
    shipped = {path.name for path in (ROOT / "scripts").glob("*.sql")}
    assert documented and documented <= shipped
    assert not any(pattern.strip() in {"scripts/", "scripts/*.sql", "*.sql"}
                   for pattern in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines())
    base = re.search(r"^FROM (\S+)$", dockerfile, re.M)
    assert base is not None and re.fullmatch(r"python:3\.11-slim@sha256:[0-9a-f]{64}", base.group(1))
    dependabot = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    assert re.search(r"- package-ecosystem: docker\n\s+directory: \"/\"", dependabot)
