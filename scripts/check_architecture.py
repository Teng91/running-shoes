"""Executable architecture constraints for the modular backend."""

import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTERS = ROOT / "backend" / "routers"
SERVICES = ROOT / "backend" / "services"
API_CONTRACT = ROOT / "unit_tests" / "api_contract.json"
MAIN_ROUTE_BUDGET = 0
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


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


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
    for path in sorted(SERVICES.glob("*.py")):
        forbidden = {
            module
            for module in imported_modules(path)
            if module in {"fastapi", "backend.main"}
            or module.startswith(("fastapi.", "backend.routers"))
        }
        if forbidden:
            fail(
                f"{path.relative_to(ROOT)} crosses service boundaries: "
                f"{', '.join(sorted(forbidden))}"
            )

    main_source = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    main_imports = imported_modules(ROOT / "backend" / "main.py")
    if main_imports != {"backend.app_factory"}:
        fail(
            "backend/main.py must remain a minimal ASGI entry point that only "
            f"imports backend.app_factory; found {sorted(main_imports)}"
        )
    forbidden_compatibility_names = {
        "register", "create_shoe", "create_run", "seed_default_data", "lifespan",
    }
    main_tree = ast.parse(main_source)
    assigned_names = {
        target.id
        for node in ast.walk(main_tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in (
            node.targets if isinstance(node, ast.Assign) else [node.target]
        )
        if isinstance(target, ast.Name)
    }
    leaked_aliases = sorted(assigned_names & forbidden_compatibility_names)
    if leaked_aliases:
        fail(f"backend/main.py restored compatibility aliases: {leaked_aliases}")
    main_routes = len(re.findall(r"(?m)^@app\.(?:get|post|put|delete|patch)\(", main_source))
    if main_routes > MAIN_ROUTE_BUDGET:
        fail(
            f"backend/main.py has {main_routes} routes; the ratcheted budget is "
            f"{MAIN_ROUTE_BUDGET}. Add new endpoints through a router."
        )

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

    actual_contract = sorted(f"{method} {path}" for method, path in route_keys)
    expected_contract = json.loads(API_CONTRACT.read_text(encoding="utf-8"))
    if actual_contract != expected_contract:
        added = sorted(set(actual_contract) - set(expected_contract))
        removed = sorted(set(expected_contract) - set(actual_contract))
        fail(f"API contract changed; added={added}, removed={removed}")

    api_paths = {
        route.path
        for route in routes
        if getattr(route, "path", "").startswith("/api/")
    }
    required = {
        "/api/auth/register",
        "/api/running-goal",
        "/api/monthly-mileage",
        "/api/agent/chat/stream",
        "/api/reports/generate",
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
        f"{len(router_files) - 1} router modules, {len(route_keys)} API method/path pairs, "
        f"{main_routes}/{MAIN_ROUTE_BUDGET} routes remaining in main."
    )


if __name__ == "__main__":
    main()
