"""SPEC-024 watchdogs use synthetic child processes and temporary artifacts."""
import os
import sys
import time
from pathlib import Path

import pytest

from scripts.browser_runner import run_browser_command


def test_browser_watchdog_propagates_success_and_failure_without_artifacts(tmp_path):
    assert run_browser_command([sys.executable, '-c', 'pass'], timeout_seconds=5,
                               label='success', artifact_dir=tmp_path) == 0
    assert run_browser_command([sys.executable, '-c', 'raise SystemExit(7)'], timeout_seconds=5,
                               label='failure', artifact_dir=tmp_path) == 7
    assert list(tmp_path.iterdir()) == []


def test_browser_watchdog_records_timeout_and_returns_failure(tmp_path):
    result = run_browser_command([sys.executable, '-c', 'import time; time.sleep(60)'],
                                 timeout_seconds=0.2, label='synthetic hang', artifact_dir=tmp_path)
    assert result == 124
    files = list(tmp_path.glob('watchdog-*.txt'))
    assert len(files) == 1
    assert 'synthetic hang exceeded' in files[0].read_text()


@pytest.mark.skipif(os.name == 'nt', reason='POSIX detached browser ancestry')
def test_browser_watchdog_terminates_detached_descendants(tmp_path):
    pid_file = tmp_path / 'child.pid'
    source = (
        "import subprocess,sys,time; from pathlib import Path; "
        "p=subprocess.Popen([sys.executable,'-c','import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)'], start_new_session=True); "
        f"Path({str(pid_file)!r}).write_text(str(p.pid)); time.sleep(60)"
    )
    assert run_browser_command([sys.executable, '-c', source], timeout_seconds=0.5,
                               label='detached', artifact_dir=tmp_path) == 124
    pid = int(pid_file.read_text())
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            if not Path('/proc').is_dir() or Path(f'/proc/{pid}/stat').read_text().split()[2] != 'Z':
                os.kill(pid, 0)
            else:
                break
        except (FileNotFoundError, ProcessLookupError):
            break
        time.sleep(0.01)
    if Path(f'/proc/{pid}/stat').exists():
        assert Path(f'/proc/{pid}/stat').read_text().split()[2] == 'Z'
    else:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
