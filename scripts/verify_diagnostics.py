"""Validate downloaded synthetic diagnostics using only the standard library."""
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

DIRECTORY = Path('.artifacts/browser/roundtrip')
MARKER = 'SPEC023_SYNTHETIC_DIAGNOSTIC'


def verify(directory: Path) -> list[str]:
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('format') != 'synthetic-browser-diagnostics-v1' or manifest.get('marker') != MARKER:
        raise ValueError('not a synthetic diagnostics manifest')
    entries = manifest.get('files', [])
    if len(entries) != 3 or {Path(item['name']).suffix for item in entries} != {'.png', '.zip', '.txt'}:
        raise ValueError('diagnostics require screenshot, trace and error')
    return [_verify_entry(directory, entry) for entry in entries]


def _verify_entry(directory: Path, entry: dict) -> str:
    """One listed file: a safe plain name, the recorded checksum and the content its type requires."""
    name = entry['name']
    if Path(name).name != name or '/' in name or '\\' in name:
        raise ValueError('unsafe diagnostics path')
    target = directory / name
    if target.is_symlink() or not target.is_file():
        raise ValueError('missing or unsafe diagnostics file')
    content = target.read_bytes()
    if hashlib.sha256(content).hexdigest() != entry['sha256']:
        raise ValueError(f'diagnostics checksum mismatch: {name}')
    if target.suffix == '.png' and not content.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('invalid screenshot')
    if target.suffix == '.txt' and MARKER not in content.decode('utf-8'):
        raise ValueError('missing synthetic failure text')
    if target.suffix == '.zip':
        with ZipFile(target) as archive:
            traces = [name for name in archive.namelist() if name.endswith('.trace')]
            if archive.testzip() is not None or not any(
                MARKER.encode() in archive.read(trace) for trace in traces
            ):
                raise ValueError('trace is unreadable or missing the synthetic page')
    return name


if __name__ == '__main__':
    print('Verified downloaded screenshot, Playwright trace and failure text:', ', '.join(verify(DIRECTORY)))
