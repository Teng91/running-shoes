import json

import pytest

from scripts import check_docs


def test_docs_harness_reads_frontend_test_count():
    _python_count, documented_frontend_count = check_docs.documented_counts()
    assert check_docs.frontend_test_count() == documented_frontend_count


def test_docs_harness_reads_agent_tool_count():
    assert check_docs.agent_tool_count() == 13


def test_docs_harness_reads_layout_matrix_count():
    assert check_docs.layout_matrix_count() == 40


def test_docs_harness_rejects_stale_release_asset_count(monkeypatch, capsys):
    actual = check_docs.release_asset_count()
    documented_python, _frontend = check_docs.documented_counts()
    stale = check_docs.README.replace(
        f"manifest 對應的 {actual} 個 shell／worker 資產",
        f"manifest 對應的 {actual - 1} 個 shell／worker 資產",
    )
    assert stale != check_docs.README
    monkeypatch.setattr(check_docs, "README", stale)
    # Exercise the real docs-check entry point without recursively collecting
    # this running pytest suite. All other repository facts remain real.
    monkeypatch.setattr(check_docs, "collected_pytest_count", lambda: documented_python)
    with pytest.raises(SystemExit):
        check_docs.main()
    assert f"release asset says {actual - 1}, but the repository has {actual}" in capsys.readouterr().err


def test_docs_harness_counts_new_manifest_modules(monkeypatch):
    manifest = json.loads((check_docs.ROOT / "frontend" / "assets.json").read_text(encoding="utf-8"))
    previous = check_docs.release_asset_count(manifest)
    manifest["modules"].append("runtime/new-feature.mjs")
    actual = check_docs.release_asset_count(manifest)
    assert actual == previous + 1
    monkeypatch.setattr(check_docs, "README", f"manifest 對應的 {previous} 個 shell／worker 資產")
    with pytest.raises(SystemExit):
        check_docs.require_readme_number(r"manifest 對應的 (\d+) 個 shell／worker 資產", actual, "release asset")


def test_document_links_reject_missing_files_and_anchors_but_ignore_examples(tmp_path):
    from scripts.document_contracts import link_errors
    readme = tmp_path / 'README.md'
    other = tmp_path / 'other.md'
    other.write_text('# Existing heading\n', encoding='utf-8')
    source = '[valid](other.md#existing-heading) [bad](missing.md) [anchor](other.md#missing)\n```md\n[example](example.md)\n```\n`[inline](inline.md)`\n[web](https://example.com/no-local-file)'
    errors = link_errors(tmp_path, readme, source)
    assert len(errors) == 2
    assert 'missing.md' in errors[0]
    assert 'other.md#missing' in errors[1]


def test_document_links_accept_encoded_paths_and_reference_links(tmp_path):
    from scripts.document_contracts import link_errors
    (tmp_path / 'with space.md').write_text('# Hello\n', encoding='utf-8')
    path = tmp_path / 'README.md'
    assert link_errors(tmp_path, path, '[file](with%20space.md#hello)\n[ref]: <with%20space.md>') == []


def test_spec_contract_rejects_missing_sections_unchecked_criteria_and_missing_test(tmp_path):
    from scripts.document_contracts import SPEC_SECTIONS, spec_errors
    directory = tmp_path / 'docs' / 'specs'
    directory.mkdir(parents=True)
    path = directory / '020-test.md'
    source = '- 狀態：Implemented\n- Owner：Tests\n' + '\n'.join('## ' + section + '\n' for section in SPEC_SECTIONS[:-2])
    source += '## Acceptance criteria\n- [ ] AC-1：Pending\n## Test traceability\n| AC | Test |\n| --- | --- |\n| AC-2 | `unit_tests/missing.py` |\n'
    errors = spec_errors(tmp_path, path, source.replace('## Goals\n', ''))
    assert any('missing section Goals' in error for error in errors)
    assert any('unchecked' in error for error in errors)
    assert any('missing traceability file' in error for error in errors)
    assert any('AC-1 has no traceability row' in error for error in errors)


def test_current_document_contracts_are_valid():
    from scripts.document_contracts import document_errors
    assert document_errors(check_docs.ROOT) == []


def test_named_traceability_resolves_python_classes_parameters_and_node_titles(tmp_path):
    from scripts.document_contracts import named_test_exists

    tests = tmp_path / 'unit_tests'
    tests.mkdir()
    (tests / 'test_named.py').write_text('def test_one(): pass\nclass TestGroup:\n    def test_method(self): pass\n')
    (tests / 'named.test.cjs').write_text("test('SPEC-023 keeps a new draft', async () => {});\n")
    assert named_test_exists(tmp_path, 'unit_tests/test_named.py::test_one[case]')
    assert named_test_exists(tmp_path, 'unit_tests/test_named.py::TestGroup::test_method')
    assert named_test_exists(tmp_path, 'unit_tests/named.test.cjs::SPEC-023 keeps a new draft')
    assert not named_test_exists(tmp_path, 'unit_tests/test_named.py::test_deleted')
    assert not named_test_exists(tmp_path, 'unit_tests/named.test.cjs::renamed title')
    assert not named_test_exists(tmp_path, '../outside.py::test_one')


def test_new_spec_traceability_rejects_file_only_and_missing_named_cases(tmp_path):
    from scripts.document_contracts import SPEC_SECTIONS, spec_errors

    tests = tmp_path / 'unit_tests'
    tests.mkdir()
    (tests / 'test_case.py').write_text('def test_real(): pass\n')
    path = tmp_path / 'docs/specs/023-test.md'
    source = '- 狀態：Implemented\n- Owner：Tests\n' + '\n'.join('## ' + section + '\n' for section in SPEC_SECTIONS[:-2])
    source += '## Acceptance criteria\n- [x] AC-1：Done\n## Test traceability\n| AC | Test |\n| --- | --- |\n| AC-1 | `unit_tests/test_case.py::test_real` |\n'
    assert spec_errors(tmp_path, path, source) == []
    assert any('named test' in error for error in spec_errors(tmp_path, path, source.replace('::test_real', '')))
    assert any('missing named test' in error for error in spec_errors(tmp_path, path, source.replace('::test_real', '::test_missing')))


def test_readme_tree_parser_builds_nested_paths_and_ignores_comments():
    from scripts.document_contracts import readme_tree_paths

    readme = (
        "# Title\n\n## 目錄結構\n\n```\nrepo/\n"
        "├── backend/              # API\n"
        "│   ├── main.py           # entry\n"
        "│   └── tools/\n"
        "│       └── search.py# no space before the comment\n"
        "└── README.md\n```\n\n## Next\n\n```\n├── ignored.py\n```\n"
    )
    assert readme_tree_paths(readme) == {
        "backend/", "backend/main.py", "backend/tools/", "backend/tools/search.py", "README.md",
    }


def test_inventory_rejects_unlisted_modules_stale_entries_and_unplaced_sdd_modules(tmp_path):
    from scripts.document_contracts import inventory_errors

    for name in ("backend/listed.py", "backend/new_module.py", "frontend/app-new.js", "scripts/tool.cjs"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("", encoding="utf-8")
    (tmp_path / "backend" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "backend" / "settings.py").write_text(
        'a = env.get("DOCUMENTED_VAR", "")\nb = _positive_int(env, "HIDDEN_LIMIT", 3)\n', encoding="utf-8"
    )
    (tmp_path / "README.md").write_text(
        "`DOCUMENTED_VAR` is set.\n\n"
        "## 目錄結構\n\n```\nrepo/\n├── backend/\n│   ├── listed.py\n│   ├── settings.py\n│   └── removed.py\n"
        "└── scripts/\n    └── tool.cjs\n```\n",
        encoding="utf-8",
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "architecture.md").write_text(
        "`backend/listed.py`, `settings.py` and `tool.cjs`", encoding="utf-8"
    )
    assert inventory_errors(tmp_path) == [
        "README.md: environment variable HIDDEN_LIMIT read by backend/settings.py is undocumented",
        "README.md: 目錄結構 does not list backend/new_module.py",
        "README.md: 目錄結構 does not list frontend/app-new.js",
        "README.md: 目錄結構 lists a path that does not exist: backend/removed.py",
        "docs/architecture.md: the SDD does not place backend/new_module.py",
        "docs/architecture.md: the SDD does not place frontend/app-new.js",
    ]


def test_current_readme_tree_and_sdd_place_every_module():
    from scripts.document_contracts import inventory_errors
    assert inventory_errors(check_docs.ROOT) == []


def test_api_reference_requires_every_contract_route_exactly(tmp_path):
    """SPEC-058: a route counts as documented only as its own `METHOD /path` code span."""
    from scripts.document_contracts import api_reference_errors

    (tmp_path / "unit_tests").mkdir()
    (tmp_path / "unit_tests" / "api_contract.json").write_text(
        json.dumps(["GET /api/runs", "GET /api/runs/summary", "GET /api/running-goal/year", "PUT /api/shoes/{shoe_id}"]),
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text(
        "| `GET /api/runs/summary` | x |\n| `GET /api/running-goal/year?year=` | y |\n`PUT /api/shoes/{shoe_id}`\n",
        encoding="utf-8",
    )
    assert api_reference_errors(tmp_path) == ["README.md: API 一覽 does not document GET /api/runs"]


def test_current_readme_documents_every_api_route():
    from scripts.document_contracts import api_reference_errors
    assert api_reference_errors(check_docs.ROOT) == []
