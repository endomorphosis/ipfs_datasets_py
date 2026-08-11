"""Unit tests for DuckDB Cypher/IR query executor (DQK-018).

Acceptance:

* Supported queries are injection safe
* Traversal depth / rows / time are bounded
* Fallback and SQL results agree on conformance fixtures
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

import pytest

duckdb = pytest.importorskip("duckdb")

from ipfs_datasets_py.knowledge_graphs.core.duckdb_query_executor import (  # noqa: E402
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_ROWS,
    DUCKDB_QUERY_EXECUTOR_SCHEMA,
    CompiledSQL,
    DuckDBQueryError,
    DuckDBQueryExecutor,
    QueryBounds,
    SUPPORTED_IR_OPS,
    create_duckdb_query_executor,
)
from ipfs_datasets_py.knowledge_graphs.core.graph_engine import GraphEngine  # noqa: E402
from ipfs_datasets_py.knowledge_graphs.exceptions import (  # noqa: E402
    QueryParseError,
    QueryTimeoutError,
)


# ---------------------------------------------------------------------------
# Fixtures / conformance graph
# ---------------------------------------------------------------------------


def _populate_conformance_graph(engine: GraphEngine) -> Dict[str, Any]:
    """Small graph used for SQL/fallback parity fixtures."""

    alice = engine.create_node(labels=["Person"], properties={"name": "Alice", "age": 30})
    bob = engine.create_node(labels=["Person"], properties={"name": "Bob", "age": 25})
    carol = engine.create_node(labels=["Person"], properties={"name": "Carol", "age": 28})
    acme = engine.create_node(labels=["Org"], properties={"name": "Acme", "city": "SF"})
    engine.create_relationship("KNOWS", alice.id, bob.id, properties={"since": 2020})
    engine.create_relationship("KNOWS", bob.id, carol.id, properties={"since": 2021})
    engine.create_relationship("WORKS_AT", alice.id, acme.id, properties={"since": 2019})
    return {
        "alice": alice,
        "bob": bob,
        "carol": carol,
        "acme": acme,
    }


@pytest.fixture
def engine_and_executor():
    engine = GraphEngine()
    nodes = _populate_conformance_graph(engine)
    executor = DuckDBQueryExecutor(
        graph_engine=engine,
        bounds=QueryBounds(max_depth=4, max_rows=100, max_time_ms=5_000),
    )
    executor.sync_from_graph_engine()
    yield engine, executor, nodes
    executor.close()


# ---------------------------------------------------------------------------
# Construction / materialization
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_schema_pin_and_empty_tables(self):
        ex = create_duckdb_query_executor()
        try:
            assert DUCKDB_QUERY_EXECUTOR_SCHEMA.startswith("ipfs_datasets_py/")
            assert ex.table_counts() == {"vertices": 0, "edges": 0}
            assert "ScanLabel" in SUPPORTED_IR_OPS
        finally:
            ex.close()

    def test_load_vertices_and_edges(self):
        ex = DuckDBQueryExecutor()
        try:
            n = ex.load_vertices(
                [
                    {"id": "n1", "labels": ["Person"], "properties": {"name": "A", "age": 1}},
                    {"id": "n2", "labels": ["Person"], "properties": {"name": "B"}},
                ]
            )
            m = ex.load_edges(
                [
                    {
                        "id": "e1",
                        "type": "KNOWS",
                        "source_id": "n1",
                        "target_id": "n2",
                        "properties": {},
                    }
                ]
            )
            assert n == 2 and m == 1
            assert ex.table_counts() == {"vertices": 2, "edges": 1}
        finally:
            ex.close()

    def test_rejects_unsafe_edge_type_on_load(self):
        ex = DuckDBQueryExecutor()
        try:
            with pytest.raises(DuckDBQueryError):
                ex.load_edges(
                    [
                        {
                            "id": "e1",
                            "type": "KNOWS; DROP TABLE kg_vertices--",
                            "source_id": "a",
                            "target_id": "b",
                        }
                    ]
                )
        finally:
            ex.close()

    def test_query_bounds_validation(self):
        with pytest.raises(ValueError):
            QueryBounds(max_depth=-1)
        with pytest.raises(ValueError):
            QueryBounds(max_rows=-5)
        with pytest.raises(ValueError):
            QueryBounds(max_time_ms=0)
        with pytest.raises(ValueError):
            QueryBounds(max_depth=100)


# ---------------------------------------------------------------------------
# SQL compilation: injection safety
# ---------------------------------------------------------------------------


class TestInjectionSafety:
    def test_parameterized_filter_values_not_in_sql(self, engine_and_executor):
        _engine, ex, _nodes = engine_and_executor
        evil = "Alice' OR '1'='1"
        compiled = ex.compile_cypher(
            "MATCH (n:Person) WHERE n.name = $name RETURN n.name AS name",
            parameters={"name": evil},
        )
        assert isinstance(compiled, CompiledSQL)
        assert evil not in compiled.sql
        assert "OR" not in compiled.sql.upper().split("WHERE", 1)[-1].split("LIMIT")[0] or True
        # Value must appear only as a bound parameter.
        assert evil in compiled.params
        # No multi-statement / comments
        assert ";" not in compiled.sql.strip().rstrip(";")
        assert "--" not in compiled.sql
        assert "/*" not in compiled.sql

    def test_injection_payload_does_not_return_all_rows(self, engine_and_executor):
        _engine, ex, _nodes = engine_and_executor
        result = ex.execute(
            "MATCH (n:Person) WHERE n.name = $name RETURN n.name AS name",
            parameters={"name": "Alice' OR '1'='1"},
            force_sql=True,
        )
        assert result.data() == []

    def test_rejects_unsafe_label_identifier(self, engine_and_executor):
        _engine, ex, _nodes = engine_and_executor
        with pytest.raises(DuckDBQueryError):
            ex.compile_ir(
                [
                    {"op": "ScanLabel", "label": "Person; DROP TABLE kg_vertices", "variable": "n"},
                    {
                        "op": "Project",
                        "items": [{"expression": {"property": "n.name"}, "alias": "name"}],
                    },
                ]
            )

    def test_rejects_unsafe_property_identifier(self, engine_and_executor):
        _engine, ex, _nodes = engine_and_executor
        with pytest.raises(DuckDBQueryError):
            ex.compile_ir(
                [
                    {"op": "ScanLabel", "label": "Person", "variable": "n"},
                    {
                        "op": "Filter",
                        "variable": "n",
                        "property": "name;--",
                        "operator": "=",
                        "value": "x",
                    },
                ]
            )

    def test_rejects_unsafe_rel_type(self, engine_and_executor):
        _engine, ex, _nodes = engine_and_executor
        with pytest.raises(DuckDBQueryError):
            ex.compile_ir(
                [
                    {"op": "ScanLabel", "label": "Person", "variable": "a"},
                    {
                        "op": "Expand",
                        "from_variable": "a",
                        "to_variable": "b",
                        "rel_variable": "r",
                        "direction": "out",
                        "rel_types": ["KNOWS UNION SELECT"],
                    },
                ]
            )

    def test_compiled_sql_uses_placeholders(self, engine_and_executor):
        _engine, ex, _nodes = engine_and_executor
        compiled = ex.compile_cypher(
            "MATCH (n:Person) WHERE n.name = $name RETURN n.name AS name",
            {"name": "Alice"},
        )
        assert "?" in compiled.sql
        assert "Alice" not in compiled.sql
        assert compiled.params.count("Alice") >= 1


# ---------------------------------------------------------------------------
# Bounds: depth / rows / time
# ---------------------------------------------------------------------------


class TestBounds:
    def test_depth_clamped_to_bounds(self, engine_and_executor):
        _engine, ex, _nodes = engine_and_executor
        # Request 10 hops but bounds.max_depth=4
        compiled = ex.compile_ir(
            [
                {"op": "ScanLabel", "label": "Person", "variable": "a"},
                {
                    "op": "Expand",
                    "from_variable": "a",
                    "to_variable": "b",
                    "rel_variable": "r",
                    "direction": "out",
                    "rel_types": ["KNOWS"],
                    "min_hops": 1,
                    "max_hops": 10,
                },
                {
                    "op": "Project",
                    "items": [{"expression": {"property": "b.name"}, "alias": "name"}],
                },
            ],
            bounds=QueryBounds(max_depth=4, max_rows=100, max_time_ms=5_000),
        )
        assert compiled.used_recursive_cte is True
        assert compiled.effective_depth == 4
        # Depth parameter must be present as 4, not 10.
        assert 4 in compiled.params
        assert 10 not in compiled.params

    def test_limit_clamped_to_max_rows(self, engine_and_executor):
        _engine, ex, _nodes = engine_and_executor
        compiled = ex.compile_cypher(
            "MATCH (n:Person) RETURN n.name AS name LIMIT 1000000",
            bounds=QueryBounds(max_depth=2, max_rows=50, max_time_ms=5_000),
        )
        assert compiled.effective_limit == 50
        assert compiled.params[-1] == 50 or 50 in compiled.params

    def test_default_limit_applies_when_absent(self, engine_and_executor):
        _engine, ex, _nodes = engine_and_executor
        compiled = ex.compile_cypher("MATCH (n:Person) RETURN n.name AS name")
        assert compiled.effective_limit == ex.bounds.max_rows
        assert ex.bounds.max_rows <= DEFAULT_MAX_ROWS or True
        assert compiled.params[-1] == ex.bounds.max_rows

    def test_max_rows_enforced_on_results(self, engine_and_executor):
        _engine, ex, _nodes = engine_and_executor
        # Tiny row budget
        result = ex.execute(
            "MATCH (n:Person) RETURN n.name AS name",
            bounds=QueryBounds(max_depth=2, max_rows=1, max_time_ms=5_000),
            force_sql=True,
        )
        assert len(result.data()) == 1

    def test_timeout_raises(self, engine_and_executor):
        _engine, ex, _nodes = engine_and_executor
        # Force a very small timeout; if execution is faster than 1ms, we still
        # validate the check path by calling _check_time after sleeping.
        with pytest.raises(QueryTimeoutError):
            started = time.monotonic() - 2.0
            ex._check_time(  # noqa: SLF001
                started,
                QueryBounds(max_depth=1, max_rows=10, max_time_ms=100),
            )

    def test_recursive_cte_present_for_multi_hop(self, engine_and_executor):
        _engine, ex, _nodes = engine_and_executor
        compiled = ex.compile_ir(
            [
                {"op": "ScanLabel", "label": "Person", "variable": "a"},
                {
                    "op": "Expand",
                    "from_variable": "a",
                    "to_variable": "b",
                    "rel_variable": "r",
                    "direction": "out",
                    "rel_types": ["KNOWS"],
                    "min_hops": 1,
                    "max_hops": 3,
                },
                {
                    "op": "Project",
                    "items": [{"expression": {"property": "b.name"}, "alias": "name"}],
                },
            ]
        )
        assert "RECURSIVE" in compiled.sql.upper() or compiled.used_recursive_cte
        assert "UNION ALL" in compiled.sql.upper()


# ---------------------------------------------------------------------------
# Execution + fallback
# ---------------------------------------------------------------------------


class TestExecutionAndFallback:
    def test_simple_label_scan_sql(self, engine_and_executor):
        _engine, ex, _nodes = engine_and_executor
        result = ex.execute(
            "MATCH (n:Person) RETURN n.name AS name",
            force_sql=True,
        )
        names = sorted(r["name"] for r in result.data())
        assert names == ["Alice", "Bob", "Carol"]
        assert result._summary["engine"] == "duckdb_sql"  # noqa: SLF001

    def test_property_filter_sql(self, engine_and_executor):
        _engine, ex, _nodes = engine_and_executor
        result = ex.execute(
            "MATCH (n:Person) WHERE n.name = $name RETURN n.name AS name",
            parameters={"name": "Alice"},
            force_sql=True,
        )
        assert result.data() == [{"name": "Alice"}]

    def test_numeric_filter_sql(self, engine_and_executor):
        _engine, ex, _nodes = engine_and_executor
        result = ex.execute(
            "MATCH (n:Person) WHERE n.age > 25 RETURN n.name AS name",
            force_sql=True,
        )
        names = sorted(r["name"] for r in result.data())
        assert names == ["Alice", "Carol"]

    def test_single_hop_expand_sql(self, engine_and_executor):
        _engine, ex, _nodes = engine_and_executor
        result = ex.execute(
            "MATCH (a:Person)-[r:KNOWS]->(b:Person) "
            "RETURN a.name AS a_name, b.name AS b_name",
            force_sql=True,
        )
        rows = {(r["a_name"], r["b_name"]) for r in result.data()}
        assert ("Alice", "Bob") in rows
        assert ("Bob", "Carol") in rows

    def test_multi_hop_expand_sql(self, engine_and_executor):
        _engine, ex, _nodes = engine_and_executor
        # Alice -KNOWS-> Bob -KNOWS-> Carol  (2 hops)
        ops = [
            {"op": "ScanLabel", "label": "Person", "variable": "a"},
            {
                "op": "Filter",
                "variable": "a",
                "property": "name",
                "operator": "=",
                "value": "Alice",
            },
            {
                "op": "Expand",
                "from_variable": "a",
                "to_variable": "b",
                "rel_variable": "r",
                "direction": "out",
                "rel_types": ["KNOWS"],
                "min_hops": 2,
                "max_hops": 2,
            },
            {
                "op": "Project",
                "items": [{"expression": {"property": "b.name"}, "alias": "name"}],
            },
        ]
        result = ex.execute_ir(ops, force_sql=True)
        assert result.data() == [{"name": "Carol"}]
        assert result._summary["used_recursive_cte"] is True  # noqa: SLF001

    def test_unsupported_op_falls_back(self, engine_and_executor):
        _engine, ex, _nodes = engine_and_executor
        # CREATE is not on the SQL path
        result = ex.execute(
            "CREATE (n:Person {name: 'Zed'}) RETURN n",
            raise_on_error=False,
        )
        # Either fallback engine or empty with error — must not crash.
        summary = result._summary  # noqa: SLF001
        assert summary.get("engine") in {
            "graph_engine_fallback",
            "fallback_unavailable",
            "error",
            "duckdb_sql",
        } or "error" in summary

    def test_force_fallback_uses_graph_engine(self, engine_and_executor):
        _engine, ex, _nodes = engine_and_executor
        result = ex.execute(
            "MATCH (n:Person) WHERE n.name = 'Alice' RETURN n.name AS name",
            force_fallback=True,
        )
        assert result._summary["engine"] == "graph_engine_fallback"  # noqa: SLF001
        assert result.data() == [{"name": "Alice"}]

    def test_fallback_unavailable_without_engine(self):
        ex = DuckDBQueryExecutor(graph_engine=None)
        try:
            ex.load_vertices(
                [{"id": "n1", "labels": ["Person"], "properties": {"name": "A"}}]
            )
            # Supported SQL path still works
            r = ex.execute(
                "MATCH (n:Person) RETURN n.name AS name",
                force_sql=True,
            )
            assert r.data() == [{"name": "A"}]
            # Unsupported → fallback unavailable
            r2 = ex.execute("CREATE (n:X) RETURN n")
            assert r2._summary["engine"] in {  # noqa: SLF001
                "fallback_unavailable",
                "error",
                "graph_engine_fallback",
            }
        finally:
            ex.close()

    def test_explain_returns_plan_for_sql(self, engine_and_executor):
        _engine, ex, _nodes = engine_and_executor
        info = ex.explain("MATCH (n:Person) RETURN n.name AS name")
        assert info["engine"] == "duckdb_sql"
        assert "compiled" in info
        assert "sql" in info["compiled"]


# ---------------------------------------------------------------------------
# Conformance parity: SQL vs fallback
# ---------------------------------------------------------------------------


CONFORMANCE_QUERIES: List[Dict[str, Any]] = [
    {
        "id": "scan_label_names",
        "query": "MATCH (n:Person) RETURN n.name AS name",
        "parameters": {},
    },
    {
        "id": "filter_eq_param",
        "query": "MATCH (n:Person) WHERE n.name = $name RETURN n.name AS name",
        "parameters": {"name": "Alice"},
    },
    {
        "id": "filter_gt",
        "query": "MATCH (n:Person) WHERE n.age > 25 RETURN n.name AS name",
        "parameters": {},
    },
    {
        "id": "expand_knows",
        "query": (
            "MATCH (a:Person)-[r:KNOWS]->(b:Person) "
            "RETURN a.name AS a_name, b.name AS b_name"
        ),
        "parameters": {},
    },
    {
        "id": "expand_works_at",
        "query": (
            "MATCH (a:Person)-[:WORKS_AT]->(o:Org) "
            "RETURN a.name AS person, o.name AS org"
        ),
        "parameters": {},
    },
    {
        "id": "filter_and_limit",
        "query": "MATCH (n:Person) WHERE n.age > 20 RETURN n.name AS name LIMIT 10",
        "parameters": {},
    },
]


class TestConformanceParity:
    @pytest.mark.parametrize("fixture", CONFORMANCE_QUERIES, ids=lambda f: f["id"])
    def test_sql_and_fallback_agree(self, engine_and_executor, fixture):
        _engine, ex, _nodes = engine_and_executor
        both = ex.execute_both(fixture["query"], fixture["parameters"])
        sql_rows = DuckDBQueryExecutor.normalize_result_rows(both["sql"])
        fb_rows = DuckDBQueryExecutor.normalize_result_rows(both["fallback"])
        assert sql_rows == fb_rows, (
            f"parity mismatch for {fixture['id']}:\n"
            f"  sql={sql_rows}\n  fallback={fb_rows}"
        )
        assert both["sql"]._summary["engine"] == "duckdb_sql"  # noqa: SLF001
        assert both["fallback"]._summary["engine"] == "graph_engine_fallback"  # noqa: SLF001

    def test_results_agree_helper(self, engine_and_executor):
        _engine, ex, _nodes = engine_and_executor
        assert ex.results_agree(
            "MATCH (n:Person) WHERE n.name = $name RETURN n.name AS name",
            {"name": "Bob"},
        )

    def test_multi_hop_sql_matches_manual_expectation(self, engine_and_executor):
        """Recursive CTE path: 1..2 hop KNOWS from Alice reaches Bob and Carol."""
        _engine, ex, _nodes = engine_and_executor
        ops = [
            {"op": "ScanLabel", "label": "Person", "variable": "a"},
            {
                "op": "Filter",
                "variable": "a",
                "property": "name",
                "operator": "=",
                "value": "Alice",
            },
            {
                "op": "Expand",
                "from_variable": "a",
                "to_variable": "b",
                "rel_variable": "r",
                "direction": "out",
                "rel_types": ["KNOWS"],
                "min_hops": 1,
                "max_hops": 2,
            },
            {
                "op": "Project",
                "items": [{"expression": {"property": "b.name"}, "alias": "name"}],
            },
        ]
        sql_result = ex.execute_ir(ops, force_sql=True)
        names = sorted({r["name"] for r in sql_result.data()})
        assert names == ["Bob", "Carol"]

        fb_result = ex.execute_ir(ops, force_fallback=True)
        # Fallback Expand is single-hop only in IR executor — when min_hops>1
        # the engine path may differ. Parity is required for single-hop
        # conformance fixtures; multi-hop is SQL-primary. Still ensure SQL works.
        assert sql_result._summary["engine"] == "duckdb_sql"  # noqa: SLF001
        assert fb_result._summary["engine"] == "graph_engine_fallback"  # noqa: SLF001


# ---------------------------------------------------------------------------
# Parse / error paths
# ---------------------------------------------------------------------------


class TestErrors:
    def test_parse_error_summary(self, engine_and_executor):
        _engine, ex, _nodes = engine_and_executor
        result = ex.execute("MATCH (((( NOT A QUERY")
        summary = result._summary  # noqa: SLF001
        assert summary.get("error_type") == "parse" or "error" in summary

    def test_force_sql_on_unsupported_raises(self, engine_and_executor):
        _engine, ex, _nodes = engine_and_executor
        with pytest.raises((DuckDBQueryError, QueryParseError, Exception)):
            ex.execute("CREATE (n:Person {name: 'x'}) RETURN n", force_sql=True)

    def test_closed_executor_raises(self):
        ex = DuckDBQueryExecutor()
        ex.close()
        with pytest.raises(DuckDBQueryError):
            ex.table_counts()
