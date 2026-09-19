from scripts import check_docs


def test_docs_harness_reads_frontend_test_count():
    assert check_docs.frontend_test_count() == 14


def test_docs_harness_reads_agent_tool_count():
    assert check_docs.agent_tool_count() == 7


def test_docs_harness_reads_layout_matrix_count():
    assert check_docs.layout_matrix_count() == 28

