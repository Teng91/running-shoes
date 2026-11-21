"""Executable dependency direction, including transitive and relative imports."""

from scripts import check_architecture
from scripts.build_frontend import frontend_outputs


def test_transitive_service_dependency_is_detected(tmp_path, monkeypatch):
    monkeypatch.setattr(check_architecture, "ROOT", tmp_path)
    services = tmp_path / "backend" / "services"
    services.mkdir(parents=True)
    service = services / "imports.py"
    service.write_text("from .. import parser\n", encoding="utf-8")
    (tmp_path / "backend" / "parser.py").write_text(
        "from fastapi import HTTPException\n", encoding="utf-8"
    )
    chain = check_architecture.forbidden_dependency_chain(service, ("fastapi",))
    assert chain == ["backend/services/imports.py", "backend.parser", "fastapi"]


def test_domain_service_graph_has_no_http_or_ai_adapter_dependencies():
    check_architecture.check_feature_boundaries()


def test_generated_frontend_is_exactly_reproducible():
    for path, expected in frontend_outputs().items():
        assert path.read_text(encoding="utf-8") == expected, path


def test_reports_depend_on_read_models_not_tool_serialization():
    path = check_architecture.ROOT / "backend" / "read_models" / "report_snapshot.py"
    assert check_architecture.forbidden_dependency_chain(path, ("backend.tools",)) is None


def test_route_modules_never_import_each_other(tmp_path, monkeypatch):
    """SPEC-090: shared HTTP helpers may be imported; another route module may not."""
    assert check_architecture.router_cross_imports(check_architecture.ROUTERS) == []
    monkeypatch.setattr(check_architecture, "ROOT", tmp_path)
    routers = tmp_path / "backend" / "routers"
    routers.mkdir(parents=True)
    (routers / "first.py").write_text("router = APIRouter()\n", encoding="utf-8")
    (routers / "helpers.py").write_text("def shared():\n    return 1\n", encoding="utf-8")
    (routers / "second.py").write_text(
        "from backend.routers.helpers import shared\nfrom backend.routers.first import router as other\n"
        "router = APIRouter()\n", encoding="utf-8")
    assert check_architecture.router_cross_imports(routers) == ["second.py -> backend.routers.first"]


def test_routers_delegate_every_database_query():
    """v4.7.2: HTTP adapters call read models or services; none builds its own query."""
    from pathlib import Path

    offenders = [
        f"{path.name}:{number}"
        for path in sorted(Path("backend/routers").glob("*.py"))
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if ".query(" in line or ".execute(" in line
    ]
    assert offenders == []


def test_core_data_is_written_only_through_the_bridge(tmp_path):
    """SPEC-094: every script reads the core data globals; only app-resources.js assigns them."""
    import json

    frontend = check_architecture.ROOT / "frontend"
    scripts = json.loads((frontend / "assets.json").read_text(encoding="utf-8"))["scripts"]
    assert check_architecture.core_data_writers(frontend, scripts) == []
    assert "runtime/core-data.mjs" in json.loads((frontend / "assets.json").read_text(encoding="utf-8"))["modules"]

    (tmp_path / "app-state.js").write_text("let shoes = [];\nlet runningGoal = {};\n", encoding="utf-8")
    (tmp_path / "app-resources.js").write_text("function assignCoreFields(p) { shoes = p.shoes; }\n", encoding="utf-8")
    (tmp_path / "app-feature.js").write_text(
        "if (ok) [shoes, retiredShoes] = value;\n"
        "runningGoal.version = 2;\n"
        "shoes.sort(byDate);\n"
        "stravaImports += [];\n"
        "const total = shoes.length; if (shoes === other) show(shoes);\n"
        "const view = { shoes: [], runningGoal };\n"
        "// shoes = [] in a comment is fine\n"
        "function local() { const shoes = []; return shoes.map(shoe => shoe.id); }\n",
        encoding="utf-8")
    offenders = check_architecture.core_data_writers(tmp_path, ["app-state.js", "app-resources.js", "app-feature.js"])
    assert [line.split(":")[1] for line in offenders] == ["1", "2", "3", "4"]
