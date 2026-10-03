from scripts import check_docs


def test_docs_harness_reads_frontend_test_count():
    _python_count, documented_frontend_count = check_docs.documented_counts()
    assert check_docs.frontend_test_count() == documented_frontend_count


def test_docs_harness_reads_agent_tool_count():
    assert check_docs.agent_tool_count() == 8


def test_docs_harness_reads_layout_matrix_count():
    assert check_docs.layout_matrix_count() == 28
