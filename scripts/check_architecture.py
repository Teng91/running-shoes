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


def project_dependencies(path: Path) -> set[str]:
    """Resolve imported submodules as well as relative/from-package imports."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = list(path.relative_to(ROOT).with_suffix("").parts[:-1])
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                base = ".".join(package[:len(package) - node.level + 1] + ([base] if base else []))
            if base:
                modules.add(base)
                for alias in node.names:
                    candidate = base + "." + alias.name
                    if module_path(candidate) is not None:
                        modules.add(candidate)
    return modules


def module_path(name: str) -> Path | None:
    if not name.startswith("backend"):
        return None
    relative = ROOT.joinpath(*name.split("."))
    for path in (relative.with_suffix(".py"), relative / "__init__.py"):
        if path.is_file():
            return path
    return None


def forbidden_dependency_chain(start: Path, forbidden: tuple[str, ...]) -> list[str] | None:
    """Find a direct or transitive forbidden dependency, retaining its explanation."""
    queue = [(start, [start.relative_to(ROOT).as_posix()])]
    visited: set[Path] = set()
    while queue:
        path, chain = queue.pop(0)
        if path in visited:
            continue
        visited.add(path)
        for name in sorted(project_dependencies(path)):
            if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden):
                return [*chain, name]
            dependency = module_path(name)
            if dependency is not None:
                queue.append((dependency, [*chain, name]))
    return None


def router_cross_imports(routers: Path) -> list[str]:
    """SPEC-090: a route module never imports another one.

    Shared HTTP helpers (``errors.py``, ``password_notices.py``) define no router and may be
    imported by any route module.
    """
    route_modules = {
        path.stem for path in routers.glob("*.py")
        if re.search(r"^router = APIRouter\(", path.read_text(encoding="utf-8"), re.M)
    }
    offenders = []
    for path in sorted(routers.glob("*.py")):
        for name in sorted(project_dependencies(path)):
            parts = name.split(".")
            if parts[:2] == ["backend", "routers"] and len(parts) > 2 and parts[2] in route_modules:
                offenders.append(f"{path.name} -> {name}")
    return offenders


def check_feature_boundaries() -> None:
    for filename in ("runs.py", "shoes.py", "monthly.py", "auth.py", "goals.py", "reports.py", "workspace.py"):
        path = ROUTERS / filename
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"commit", "rollback", "add", "add_all", "flush", "execute", "update", "delete"}
                and not (
                    isinstance(node.func.value, ast.Name) and node.func.value.id == "router"
                )
            ):
                fail(f"{path.relative_to(ROOT)} must delegate mutations to application services")
    for directory in (SERVICES, ROOT / "backend" / "read_models"):
        for path in sorted(directory.glob("*.py")):
            chain = forbidden_dependency_chain(path, ("fastapi", "starlette", "backend.routers", "backend.main", "backend.tools"))
            if chain:
                fail("domain/service dependency violation: " + " -> ".join(chain))
    for offender in router_cross_imports(ROUTERS):
        fail(f"router modules must not import each other: {offender}")
    frontend = ROOT / "frontend"
    manifest = json.loads((frontend / "assets.json").read_text(encoding="utf-8"))
    owners: dict[str, str] = {}
    for filename in manifest["scripts"]:
        source = (frontend / filename).read_text(encoding="utf-8")
        for name in re.findall(r"registerFeatureReset\('([^']+)'", source):
            if name in owners:
                fail(f"duplicate frontend lifecycle owner {name}: {owners[name]}, {filename}")
            owners[name] = filename
    for filename in manifest["modules"]:
        source = (frontend / filename).read_text(encoding="utf-8")
        if re.search(r"\b(?:document|window|localStorage|fetch)\b", source):
            fail(f"native runtime module must remain DOM/transport independent: {filename}")


def iter_routes(routes):
    """Flatten FastAPI's deferred included-router entries."""
    for route in routes:
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            yield from iter_routes(original_router.routes)
        else:
            yield route


def main() -> None:
    check_feature_boundaries()
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
        fail("the analytics/export/spending routers are not fully registered on the FastAPI app")

    print(
        "Architecture constraints passed: "
        f"{len(router_files) - 1} router modules, {len(route_keys)} API method/path pairs, "
        f"{main_routes}/{MAIN_ROUTE_BUDGET} routes remaining in main."
    )


if __name__ == "__main__":
    main()
