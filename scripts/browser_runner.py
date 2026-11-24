"""Bound synthetic/anonymous browser runners and their child process trees."""
import argparse
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path


def process_snapshot() -> dict[int, tuple[int, str]]:
    output = subprocess.run(['ps', '-eo', 'pid=,ppid=,lstart='], check=True,
                            capture_output=True, text=True, timeout=5).stdout
    return {int(parts[0]): (int(parts[1]), parts[2]) for line in output.splitlines()
            if len(parts := line.split(maxsplit=2)) == 3}


def stop_process_tree(process: subprocess.Popen, *, grace_seconds: float = 3) -> None:
    if process.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       check=False, capture_output=True, timeout=10)
    else:
        owned = _owned_processes(process.pid)
        _signal_owned(owned, signal.SIGTERM)
        try:
            process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            pass
        _kill_survivors(owned)
    if process.poll() is None:
        process.kill()
    process.wait(timeout=10)


def _owned_processes(root_pid: int) -> dict:
    """The process and every descendant, followed by ancestry: Playwright browsers may start their
    own process group, so a shared group cannot be assumed."""
    snapshot = process_snapshot()
    owned = {root_pid: snapshot.get(root_pid)}
    while True:
        children = {pid: identity for pid, identity in snapshot.items()
                    if identity[0] in owned and pid not in owned}
        if not children:
            return owned
        owned.update(children)


def _signal_owned(owned: dict, signum: int) -> None:
    for pid in reversed(owned):
        if owned[pid] is not None:
            try:
                os.kill(pid, signum)
            except ProcessLookupError:
                pass


def _kill_survivors(owned: dict) -> None:
    """SIGKILL what is still running, but never an unrelated process that reused a PID."""
    current = process_snapshot()
    for pid, identity in owned.items():
        observed = current.get(pid)
        if identity is not None and observed is not None and observed[1] == identity[1]:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def run_browser_command(arguments: list[str], *, timeout_seconds: float, label: str,
                        artifact_dir: Path = Path('.artifacts/browser')) -> int:
    if timeout_seconds <= 0:
        raise ValueError('browser timeout must be positive')
    options = {'start_new_session': True} if os.name != 'nt' else {
        'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP,
    }
    process = subprocess.Popen(arguments, **options)
    try:
        return process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        safe_label = re.sub(r'[^a-zA-Z0-9_-]', '-', label)
        output = artifact_dir / f'watchdog-{safe_label}-{time.time_ns()}.txt'
        output.write_text(f'{label} exceeded {timeout_seconds:g} seconds; browser process tree terminated.\n', encoding='utf-8')
        print(f'Browser watchdog failed: {output}', file=sys.stderr, flush=True)
        return 124
    finally:
        stop_process_tree(process)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout', type=float, required=True)
    parser.add_argument('--label', required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('a browser command is required')
    return run_browser_command(command, timeout_seconds=args.timeout, label=args.label)


if __name__ == '__main__':
    raise SystemExit(main())
