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
    path = check_architecture.ROOT / "backend" / "reports.py"
    assert check_architecture.forbidden_dependency_chain(path, ("backend.tools",)) is None
