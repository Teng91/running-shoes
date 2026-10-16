"""Post-deploy smoke check for public, non-mutating service endpoints."""

import argparse
import json
import urllib.error
import urllib.request


def fetch_json(base_url: str, path: str, timeout: float) -> dict:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        headers={"User-Agent": "running-shoes-smoke-test/1"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"{path} returned HTTP {response.status}")
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path} did not return a JSON object")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url", help="Deployed origin, for example https://app.fly.dev")
    parser.add_argument("--timeout", type=float, default=15)
    args = parser.parse_args()

    try:
        live = fetch_json(args.base_url, "/health/live", args.timeout)
        ready = fetch_json(args.base_url, "/health/ready", args.timeout)
        openapi = fetch_json(args.base_url, "/openapi.json", args.timeout)
    except (OSError, RuntimeError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Smoke test failed: {exc}") from exc

    if live.get("status") != "ok" or ready.get("status") != "ok":
        raise SystemExit("Smoke test failed: health endpoint is not ready")
    if "/api/auth/me" not in openapi.get("paths", {}):
        raise SystemExit("Smoke test failed: expected API contract is missing")
    print(
        "Smoke test passed: live, ready, and OpenAPI contract are available "
        f"(schema {ready.get('schema_version')})."
    )


if __name__ == "__main__":
    main()
