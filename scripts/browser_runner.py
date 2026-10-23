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
        if process.poll() is None:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           check=False, capture_output=True, timeout=10)
    else:
        # Playwright browsers may start their own process group. Follow ancestry,
        # rather than assuming every descendant shares Node's group.
        snapshot = process_snapshot()
        owned = {process.pid: snapshot.get(process.pid)}
        while True:
            children = {pid: identity for pid, identity in snapshot.items()
                        if identity[0] in owned and pid not in owned}
            if not children:
                break
            owned.update(children)
        for pid in reversed(owned):
            if owned[pid] is not None:
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        try:
            process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            pass
        current = process_snapshot()
        for pid, identity in owned.items():
            # Do not signal an unrelated process if a PID was reused.
            observed = current.get(pid)
            if identity is not None and observed is not None and observed[1] == identity[1]:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=10)


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
