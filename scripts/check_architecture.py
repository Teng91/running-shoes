"""Executable architecture constraints for the modular backend."""

import ast
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTERS = ROOT / "backend" / "routers"
sys.path.insert(0, str(ROOT))


def fail(message: str) -> None:
    print(f"Architecture check failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def imports_backend_main(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == "backend.main" for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.module == "backend" and any(alias.name == "main" for alias in node.names):
                return True
            if node.module == "backend.main":
                return True
    return False


def iter_routes(routes):
    """Flatten FastAPI's deferred included-router entries."""
    for route in routes:
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            yield from iter_routes(original_router.routes)
        else:
            yield route


def main() -> None:
    router_files = sorted(ROUTERS.glob("*.py"))
    if len(router_files) < 2:
        fail("backend/routers must contain a package and at least one route module")
    for path in router_files:
        if imports_backend_main(path):
            fail(f"{path.relative_to(ROOT)} must not import backend.main")

    from backend.main import app

    routes = list(iter_routes(app.routes))
    route_keys = [
        (method, route.path)
        for route in routes
        for method in getattr(route, "methods", set())
        if route.path.startswith("/api/")
    ]
    duplicates = sorted(key for key, count in Counter(route_keys).items() if count > 1)
    if duplicates:
        rendered = ", ".join(f"{method} {path}" for method, path in duplicates)
        fail(f"duplicate API routes found: {rendered}")

    api_paths = {
        route.path
        for route in routes
        if getattr(route, "path", "").startswith("/api/")
    }
    required = {
        "/api/analytics/dashboard",
        "/api/shoes/{shoe_id}/analytics",
        "/api/export",
        "/api/export/account",
        "/api/spending/monthly",
    }
    if not required.issubset(api_paths):
        fail("the insights router is not fully registered on the FastAPI app")

    print(
        "Architecture constraints passed: "
        f"{len(router_files) - 1} router module, {len(route_keys)} API method/path pairs."
    )


if __name__ == "__main__":
    main()
