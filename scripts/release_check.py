"""Read-only, fail-closed release verification; never authenticates or deploys."""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_frontend import FRONTEND, ROOT, shell_asset_paths


def validate_origin(value: str) -> str:
    url = urlparse(value)
    if (url.username or url.password or url.query or url.fragment or url.path not in ("", "/")
            or not url.hostname or url.scheme not in ("http", "https")):
        raise ValueError("base URL must be an origin without credentials, path, query or fragment")
    if url.scheme != "https" and url.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("HTTPS is required except for a loopback fixture")
    return value.rstrip("/")


def fetch_public(origin: str, path: str) -> tuple[int, dict, bytes]:
    request = Request(origin + path, headers={
        "Cache-Control": "no-cache", "User-Agent": "running-shoes-release-check/1",
    })
    try:
        with urlopen(request, timeout=45) as response:
            if validate_origin(f"{urlparse(response.url).scheme}://{urlparse(response.url).netloc}") != origin:
                raise ValueError("release check refused a cross-origin redirect")
            return response.status, dict(response.headers), response.read()
    except HTTPError as error:
        return error.code, dict(error.headers), b""


def check_release(fetcher, *, frontend: Path = FRONTEND) -> dict:
    manifest = json.loads((frontend / "assets.json").read_text(encoding="utf-8"))
    version = manifest["version"]

    def read_json(path: str) -> dict:
        status, _, body = fetcher(path)
        if status != 200:
            raise ValueError(f"{path}: expected HTTP 200, got {status}")
        result = json.loads(body)
        if not isinstance(result, dict):
            raise ValueError(f"{path}: invalid JSON object")
        return result

    live, ready = read_json("/health/live"), read_json("/health/ready")
    expected_schema = int(re.search(
        r"CURRENT_SCHEMA_VERSION = (\d+)", (ROOT / "backend/migrations.py").read_text(encoding="utf-8")
    )[1])
    if live.get("status") != "ok" or ready.get("status") != "ok" or ready.get("schema_version") != expected_schema:
        raise ValueError("health/readiness or database schema version mismatch")
    contract = read_json("/openapi.json").get("paths", {})
    for entry in json.loads((ROOT / "unit_tests/api_contract.json").read_text(encoding="utf-8")):
        method, path = entry.split(" ", 1)
        if method.lower() not in contract.get(path, {}):
            raise ValueError(f"API contract missing: {entry}")

    assets = [*shell_asset_paths(manifest), ("/service-worker.js", "service-worker.js")]

    def check_asset(item):
        url, name = item
        status, headers, body = fetcher(url)
        if status != 200:
            raise ValueError(f"asset unavailable: {name} (HTTP {status})")
        kind = {key.lower(): value for key, value in headers.items()}.get("content-type", "")
        types = {(".js", ".mjs"): "javascript", (".css",): "text/css",
                 (".html",): "text/html", (".png",): "image/png", (".svg",): "image/svg+xml",
                 (".webmanifest",): "application/manifest+json"}
        if any(name.endswith(suffixes) and expected not in kind for suffixes, expected in types.items()):
            raise ValueError(f"asset MIME mismatch: {name}")
        if hashlib.sha256(body).digest() != hashlib.sha256((frontend / name).read_bytes()).digest():
            raise ValueError(f"asset content/version mismatch: {name}")

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(check_asset, assets))
    for path in ("/api/runs/summary?year=2026&month=1", "/api/runs/year-summary?year=2026",
                 "/api/running-goal/progress?year=2026&month=1", "/api/spending/summary"):
        if fetcher(path)[0] != 401:
            raise ValueError(f"anonymous API isolation failed: {path.split('?')[0]}")
    return {"version": version, "cache": manifest["cache_name"], "assets": len(assets)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    try:
        origin = validate_origin(args.base_url)
        report = check_release(lambda path: fetch_public(origin, path))
        print(f"Release assets passed: v{report['version']}, {report['assets']} matching hashes/MIMEs, schema and API isolation.", flush=True)
        subprocess.run([
            sys.executable, str(ROOT / "scripts/browser_runner.py"), "--timeout", "240",
            "--label", "release-browser", "--", "node",
            str(ROOT / "scripts/release_browser.cjs"), origin, report["version"], report["cache"],
        ], cwd=ROOT, check=True, timeout=270)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Release check failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
