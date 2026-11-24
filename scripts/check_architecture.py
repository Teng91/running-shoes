"""Executable architecture constraints for the modular backend."""

import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

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


# SPEC-094/095: core account data lives in the runtime/core-data.mjs store. Scripts read it
# through the read-only `coreData` view; only app-resources.js installs the store.
CORE_DATA_FIELDS = (
    "shoes", "retiredShoes", "monthlyMileages", "runningGoal", "stravaImports", "spendingSummary", "monthlySpending",
)
CORE_DATA_WRITER = "app-resources.js"
CORE_DATA_DECLARATIONS = "app-state.js"
_MUTATING_METHODS = "push|pop|shift|unshift|splice|sort|reverse|fill|copyWithin"


def _code_lines(path: Path) -> list[tuple[int, str, str]]:
    """(number, code without a trailing // comment, original line) for each line."""
    lines = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        cut = re.search(r"(?:^|\s)//", line)
        code = line[:cut.start()] if cut and line[:cut.start()].count("'") % 2 == 0 else line
        lines.append((number, code, line))
    return lines


def core_data_violations(frontend: Path, scripts: list[str]) -> list[str]:
    """Writes to core data, or reads of the removed globals, outside their owners (SPEC-095)."""
    names = "|".join(CORE_DATA_FIELDS)
    writes = (
        # Replacing the view itself.
        (re.compile(r"(?<![\w.$])coreData\s*=(?![=>])"), {CORE_DATA_WRITER, CORE_DATA_DECLARATIONS}),
        # Writing a field or an element: coreData.shoes = x, coreData.runningGoal.version = 2
        (re.compile(r"(?<![\w.$])coreData(?:\.\w+|\[[^\]\n]+\])+\s*(?:[-+*/]?=)(?![=>])"), set()),
        # In-place array mutation: coreData.shoes.sort(...)
        (re.compile(rf"(?<![\w.$])coreData\.\w+\.(?:{_MUTATING_METHODS})\("), set()),
        # Re-creating a global of the old name.
        (re.compile(rf"^(?:let|var|const)\s+(?:{names})\b"), set()),
    )
    bare = re.compile(rf"(?:(?<=\.\.\.)|(?<![\w$'\"/.\-]))({names})\b(?!\s*:(?!:))")
    offenders = []
    for filename in scripts:
        lines = _code_lines(frontend / filename)
        source = "\n".join(code for _number, code, _line in lines)
        # A name a script declares itself (local variable or parameter) is not the old global.
        local = {name for name in CORE_DATA_FIELDS if re.search(
            rf"(?:\b(?:let|const|var)\s+(?:\[[^\]]*)?\b{name}\b|\([^()]*\b{name}\b[^()]*\)\s*(?:=>|\{{)|\b{name}\s*=>)",
            source)}
        for number, code, line in lines:
            if any(pattern.search(code) and filename not in allowed for pattern, allowed in writes):
                offenders.append(f"{filename}:{number}: {line.strip()}")
                continue
            if any(match.group(1) not in local for match in bare.finditer(code)):
                offenders.append(f"{filename}:{number}: reads a removed global: {line.strip()}")
    return offenders


# SPEC-100: the classic scripts share one global scope, so a dependency between two of them is
# only a bare name. The ratchet records how many top-level names another script uses and which
# script pairs use each other; both may shrink, neither may grow.
RATCHET_BASELINE = ROOT / "scripts" / "architecture_ratchet.json"
COMPLEXITY_EXEMPTION = re.compile(r"#\s*noqa:[^#\n]*\bC901\b")
_TOP_LEVEL_DECLARATION = re.compile(
    r"^(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)|^(?:let|const|var|class)\s+([A-Za-z_$][\w$]*)", re.M)
_ANY_DECLARATION = re.compile(r"\b(?:function\s*\*?\s*|let\s+|const\s+|var\s+|class\s+)([A-Za-z_$][\w$]*)")
# A bare name or a spread (...name); a property access (hooks.render) is not a use of a global.
_IDENTIFIER = re.compile(r"(?:(?<=\.\.\.)|(?<![\w$.]))[A-Za-z_$][\w$]*")
# An object-literal key ({ render: ... }, , key: ...) names a property, not a global.
_OBJECT_KEY = re.compile(r"([{,]\s*)[A-Za-z_$][\w$]*(?=\s*:(?!:))")


def _script_code(path: Path) -> str:
    """A script without comments or object keys, so a name in prose or a property is not a dependency."""
    code = "\n".join(code for _number, code, _line in _code_lines(path))
    return _OBJECT_KEY.sub(r"\1", re.sub(r"/\*.*?\*/", " ", code, flags=re.S))


def frontend_script_dependencies(frontend: Path, scripts: list[str]) -> dict[tuple[str, str], set[str]]:
    """{(user, owner): names} for each top-level name a script uses from another script.

    A script that declares a name itself, at any depth, uses its own binding.
    """
    code = {filename: _script_code(frontend / filename) for filename in scripts}
    owners: dict[str, str] = {}
    for filename in scripts:
        for match in _TOP_LEVEL_DECLARATION.finditer(code[filename]):
            owners.setdefault(match.group(1) or match.group(2), filename)
    dependencies: dict[tuple[str, str], set[str]] = {}
    for filename in scripts:
        own = set(_ANY_DECLARATION.findall(code[filename]))
        for name in set(_IDENTIFIER.findall(code[filename])) - own:
            owner = owners.get(name)
            if owner is not None and owner != filename:
                dependencies.setdefault((filename, owner), set()).add(name)
    return dependencies


def frontend_coupling(frontend: Path, scripts: list[str]) -> dict[str, Any]:
    """The two ratcheted numbers: cross-script names and mutually dependent script pairs."""
    dependencies = frontend_script_dependencies(frontend, scripts)
    names: set[str] = set().union(*dependencies.values())
    mutual = sorted({tuple(sorted(pair)) for pair in dependencies if (pair[1], pair[0]) in dependencies})
    return {"cross_script_names": len(names), "mutual_pairs": [list(pair) for pair in mutual]}


def coupling_violations(measured: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    """Growth fails; so does an improvement the baseline has not recorded yet."""
    problems = []
    count, budget = measured["cross_script_names"], baseline["cross_script_names"]
    if count > budget:
        problems.append(f"{count} top-level names are used from another script; the budget is {budget}. "
                        "Pass the value in, or move the shared code into a runtime module.")
    elif count < budget:
        problems.append(f"only {count} top-level names are used from another script now; lower "
                        f"cross_script_names in {RATCHET_BASELINE.name} from {budget} to {count}.")
    allowed = {tuple(pair) for pair in baseline["mutual_pairs"]}
    current = {tuple(pair) for pair in measured["mutual_pairs"]}
    for first, second in sorted(current - allowed):
        problems.append(f"{first} and {second} now use each other; one of them must stop.")
    for first, second in sorted(allowed - current):
        problems.append(f"{first} and {second} no longer use each other; remove the pair from "
                        f"{RATCHET_BASELINE.name}.")
    return problems


def complexity_exemptions(backend: Path) -> list[str]:
    """Backend lines that silence ruff's C901, i.e. functions still above complexity 10."""
    return [
        f"{path.relative_to(backend.parent).as_posix()}:{number}"
        for path in sorted(backend.rglob("*.py"))
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if COMPLEXITY_EXEMPTION.search(line)
    ]


def complexity_exemption_violations(exemptions: list[str], budget: int) -> list[str]:
    """New `# noqa: C901` lines fail; a split function lowers the recorded budget."""
    if len(exemptions) > budget:
        return [f"{len(exemptions)} backend functions silence C901 (budget {budget}): split the new one "
                f"instead of adding `# noqa: C901` ({', '.join(exemptions)})."]
    if len(exemptions) < budget:
        return [f"only {len(exemptions)} backend functions silence C901 now; lower complexity_exemptions in "
                f"{RATCHET_BASELINE.name} from {budget} to {len(exemptions)}."]
    return []


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
    for offender in core_data_violations(frontend, manifest["scripts"]):
        fail(f"core data is read through coreData and written only by applyCoreResource() in {CORE_DATA_WRITER}: "
             f"{offender}")
    baseline = json.loads(RATCHET_BASELINE.read_text(encoding="utf-8"))
    problems = coupling_violations(frontend_coupling(frontend, manifest["scripts"]), baseline)
    problems += complexity_exemption_violations(complexity_exemptions(ROOT / "backend"),
                                                baseline["complexity_exemptions"])
    if problems:
        fail("architecture ratchet (SPEC-100): " + " ".join(problems))


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
