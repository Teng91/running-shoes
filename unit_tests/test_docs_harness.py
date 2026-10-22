import json

import pytest

from scripts import check_docs


def test_docs_harness_reads_frontend_test_count():
    _python_count, documented_frontend_count = check_docs.documented_counts()
    assert check_docs.frontend_test_count() == documented_frontend_count


def test_docs_harness_reads_agent_tool_count():
    assert check_docs.agent_tool_count() == 8


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
