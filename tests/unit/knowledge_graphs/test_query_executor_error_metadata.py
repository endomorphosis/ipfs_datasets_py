import pytest

from ipfs_datasets_py.knowledge_graphs.core.query_executor import QueryExecutor


def test_execute_cypher_parse_error_includes_structured_metadata():
    executor = QueryExecutor(graph_engine=None)

    # Invalid Cypher (missing closing paren)
    result = executor.execute("MATCH (n RETURN n")

    assert len(result) == 0
    assert result.summary.get("query_type") == "Cypher"
    assert result.summary.get("error")
    assert result.summary.get("error_type") == "parse"
    assert result.summary.get("error_stage") == "parse"
    assert result.summary.get("error_class") == "QueryParseError"


def test_execute_cypher_execution_error_includes_structured_metadata():
    executor = QueryExecutor(graph_engine=None)

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    executor._execute_ir_operations = _boom  # type: ignore[method-assign]

    result = executor.execute("MATCH (n) RETURN n")

    assert len(result) == 0
    assert result.summary.get("query_type") == "Cypher"
    assert result.summary.get("error")
    assert result.summary.get("error_type") == "execution"
    assert result.summary.get("error_stage") == "execute"
    assert result.summary.get("error_class") == "QueryExecutionError"
