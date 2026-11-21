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


def test_core_data_is_read_through_the_view_and_written_only_by_the_bridge(tmp_path):
    """SPEC-094/095: scripts read coreData.<field>; only app-resources.js installs and feeds the store."""
    import json

    frontend = check_architecture.ROOT / "frontend"
    manifest = json.loads((frontend / "assets.json").read_text(encoding="utf-8"))
    assert check_architecture.core_data_violations(frontend, manifest["scripts"]) == []
    assert "runtime/core-data.mjs" in manifest["modules"]

    (tmp_path / "app-state.js").write_text("let coreData = Object.freeze({ shoes: [] });\n", encoding="utf-8")
    (tmp_path / "app-resources.js").write_text("function useCoreDataStore(store) { coreData = store.view; }\n",
                                               encoding="utf-8")
    (tmp_path / "app-feature.js").write_text(
        "coreData = {};\n"
        "coreData.runningGoal.version = 2;\n"
        "coreData.shoes.sort(byDate);\n"
        "let shoes = [];\n"
        "const total = coreData.shoes.length; if (coreData.shoes === other) show([...coreData.shoes]);\n"
        "const view = { shoes: [], runningGoal: coreData.runningGoal };\n"
        "// coreData = {} in a comment is fine\n",
        encoding="utf-8")
    (tmp_path / "app-local.js").write_text(
        "function draw(shoes) { return shoes.map(shoe => shoe.id); }\n"
        "const picks = list.filter(retiredShoes => retiredShoes.id);\n",
        encoding="utf-8")
    offenders = check_architecture.core_data_violations(
        tmp_path, ["app-state.js", "app-resources.js", "app-feature.js", "app-local.js"])
    assert [line.split(":")[:2] for line in offenders] == [
        ["app-feature.js", "1"], ["app-feature.js", "2"], ["app-feature.js", "3"], ["app-feature.js", "4"]]

    (tmp_path / "app-reader.js").write_text("function count() { return shoes.length; }\n", encoding="utf-8")
    assert check_architecture.core_data_violations(tmp_path, ["app-reader.js"]) == [
        "app-reader.js:1: reads a removed global: function count() { return shoes.length; }"]
