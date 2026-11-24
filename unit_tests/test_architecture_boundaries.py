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


def test_frontend_coupling_matches_the_recorded_ratchet():
    """SPEC-100: the recorded baseline is exactly today's cross-script coupling."""
    import json

    frontend = check_architecture.ROOT / "frontend"
    manifest = json.loads((frontend / "assets.json").read_text(encoding="utf-8"))
    baseline = json.loads(check_architecture.RATCHET_BASELINE.read_text(encoding="utf-8"))
    measured = check_architecture.frontend_coupling(frontend, manifest["scripts"])
    assert measured == {key: baseline[key] for key in ("cross_script_names", "mutual_pairs")}
    assert check_architecture.coupling_violations(measured, baseline) == []


def test_coupling_ratchet_rejects_growth_and_unrecorded_improvement(tmp_path):
    """SPEC-100: a new shared name or mutual pair fails, and so does a stale baseline."""
    (tmp_path / "a.js").write_text(
        "function alpha() { return beta(); }\n"
        "// gamma is only mentioned in a comment\n"
        "/* delta too */\n"
        "const hooks = { gamma: 1, delta: () => hooks.gamma };\n"
        "const pick = ok ? hooks : other;\n", encoding="utf-8")
    (tmp_path / "b.js").write_text("let beta = () => alpha([...delta]);\n", encoding="utf-8")
    (tmp_path / "c.js").write_text(
        "function gamma() { const alpha = 1; return alpha; }\nconst delta = [2];\n", encoding="utf-8")
    scripts = ["a.js", "b.js", "c.js"]
    assert check_architecture.frontend_script_dependencies(tmp_path, scripts) == {
        ("a.js", "b.js"): {"beta"}, ("b.js", "a.js"): {"alpha"}, ("b.js", "c.js"): {"delta"}}
    measured = check_architecture.frontend_coupling(tmp_path, scripts)
    assert measured == {"cross_script_names": 3, "mutual_pairs": [["a.js", "b.js"]]}

    assert check_architecture.coupling_violations(measured, measured) == []
    grown = check_architecture.coupling_violations(measured, {"cross_script_names": 1, "mutual_pairs": []})
    assert len(grown) == 2 and "budget is 1" in grown[0] and "a.js and b.js now use each other" in grown[1]
    stale = check_architecture.coupling_violations(
        measured, {"cross_script_names": 4, "mutual_pairs": [["a.js", "b.js"], ["b.js", "c.js"]]})
    assert len(stale) == 2 and "from 4 to 3" in stale[0] and "remove the pair" in stale[1]


def test_backend_complexity_is_linted_and_exemptions_only_shrink(tmp_path):
    """SPEC-100: ruff enforces C901 at 10 on backend code; `# noqa: C901` lines are budgeted."""
    import json
    import tomllib

    lint = tomllib.loads((check_architecture.ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["ruff"]["lint"]
    assert "C901" in lint["select"] and lint["mccabe"]["max-complexity"] == 10
    assert not any(path.startswith("backend") for path in lint.get("per-file-ignores", {}))

    baseline = json.loads(check_architecture.RATCHET_BASELINE.read_text(encoding="utf-8"))
    exemptions = check_architecture.complexity_exemptions(check_architecture.ROOT / "backend")
    assert len(exemptions) == baseline["complexity_exemptions"]

    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / "big.py").write_text(
        "def big():  # noqa: C901\n    pass\n\n\ndef other():  # noqa: E501, C901\n    pass\n"
        "# C901 mentioned without noqa\n", encoding="utf-8")
    assert check_architecture.complexity_exemptions(backend) == ["backend/big.py:1", "backend/big.py:5"]
    assert check_architecture.complexity_exemption_violations(["x", "y"], 2) == []
    assert "split the new one" in check_architecture.complexity_exemption_violations(["x", "y"], 1)[0]
    assert "from 3 to 2" in check_architecture.complexity_exemption_violations(["x", "y"], 3)[0]
