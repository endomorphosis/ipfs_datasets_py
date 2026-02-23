"""
Tests for UNWIND and WITH clauses (deferred features 3.4.3a/b)

This test suite validates:
- UNWIND: expanding a list literal into rows
- UNWIND: expanding a node property list into rows
- UNWIND: chained with MATCH then RETURN
- WITH: projecting columns for the next query part
- WITH + WHERE: filtering projected columns
- WITH + DISTINCT: deduplication after projection
- Async execute: execute_async() on UnifiedQueryEngine

Tests follow GIVEN-WHEN-THEN format per repository standards.
"""

import asyncio
import pytest
from unittest.mock import MagicMock

from ipfs_datasets_py.knowledge_graphs.core.query_executor import QueryExecutor, GraphEngine
from ipfs_datasets_py.knowledge_graphs.cypher.parser import CypherParser
from ipfs_datasets_py.knowledge_graphs.cypher.compiler import CypherCompiler
from ipfs_datasets_py.knowledge_graphs.cypher.ast import UnwindClause, WithClause


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def fresh_executor():
    """Return a new QueryExecutor with an empty GraphEngine."""
    return QueryExecutor(graph_engine=GraphEngine())


@pytest.fixture()
def people_executor():
    """QueryExecutor pre-populated with two Person nodes."""
    engine = GraphEngine()
    engine.create_node(labels=["Person"], properties={"name": "Alice", "age": 32})
    engine.create_node(labels=["Person"], properties={"name": "Bob", "age": 24})
    return QueryExecutor(graph_engine=engine)


# ---------------------------------------------------------------------------
# AST / Parser
# ---------------------------------------------------------------------------

class TestUnwindParsing:
    """Parser correctly produces UnwindClause nodes."""

    def test_unwind_literal_list(self):
        """
        GIVEN: UNWIND [1, 2, 3] AS x RETURN x
        WHEN: Parsed
        THEN: First clause is UnwindClause with variable='x'
        """
        # GIVEN/WHEN
        ast = CypherParser().parse("UNWIND [1, 2, 3] AS x RETURN x")
        unwind = ast.clauses[0]

        # THEN
        assert isinstance(unwind, UnwindClause)
        assert unwind.variable == "x"

    def test_unwind_property_expression(self):
        """
        GIVEN: UNWIND n.tags AS tag
        WHEN: Parsed
        THEN: UnwindClause variable is 'tag'
        """
        # GIVEN/WHEN
        ast = CypherParser().parse("MATCH (n) UNWIND n.tags AS tag RETURN tag")
        unwind = ast.clauses[1]

        # THEN
        assert isinstance(unwind, UnwindClause)
        assert unwind.variable == "tag"


class TestWithParsing:
    """Parser correctly produces WithClause nodes."""

    def test_with_simple_projection(self):
        """
        GIVEN: MATCH (n:Person) WITH n.name AS name RETURN name
        WHEN: Parsed
        THEN: Second clause is WithClause with one item
        """
        # GIVEN/WHEN
        ast = CypherParser().parse("MATCH (n:Person) WITH n.name AS name RETURN name")
        with_clause = ast.clauses[1]

        # THEN
        assert isinstance(with_clause, WithClause)
        assert len(with_clause.items) == 1

    def test_with_where_preserved(self):
        """
        GIVEN: WITH clause that has a WHERE
        WHEN: Parsed
        THEN: WithClause.where is not None
        """
        # GIVEN/WHEN
        ast = CypherParser().parse(
            "MATCH (n:Person) WITH n.name AS name, n.age AS age WHERE age > 30 RETURN name"
        )
        with_clause = ast.clauses[1]

        # THEN
        assert isinstance(with_clause, WithClause)
        assert with_clause.where is not None


# ---------------------------------------------------------------------------
# Compiler
# ---------------------------------------------------------------------------

class TestUnwindCompilation:
    """Compiler emits correct IR for UNWIND."""

    def test_unwind_emits_unwind_op(self):
        """
        GIVEN: UNWIND query
        WHEN: Compiled
        THEN: First IR op is 'Unwind'
        """
        # GIVEN/WHEN
        ast = CypherParser().parse("UNWIND [1, 2, 3] AS x RETURN x")
        ir = CypherCompiler().compile(ast)

        # THEN
        assert ir[0]["op"] == "Unwind"
        assert ir[0]["variable"] == "x"

    def test_unwind_followed_by_project(self):
        """
        GIVEN: UNWIND ... RETURN
        WHEN: Compiled
        THEN: IR ends with a 'Project' op
        """
        # GIVEN/WHEN
        ast = CypherParser().parse("UNWIND [1, 2] AS x RETURN x")
        ir = CypherCompiler().compile(ast)

        # THEN
        assert ir[-1]["op"] == "Project"


class TestWithCompilation:
    """Compiler emits correct IR for WITH."""

    def test_with_emits_with_project_op(self):
        """
        GIVEN: WITH clause
        WHEN: Compiled
        THEN: IR contains 'WithProject' op
        """
        # GIVEN/WHEN
        ast = CypherParser().parse("MATCH (n:Person) WITH n.name AS name RETURN name")
        ir = CypherCompiler().compile(ast)

        # THEN
        ops = [op["op"] for op in ir]
        assert "WithProject" in ops

    def test_with_where_emits_filter_after_with_project(self):
        """
        GIVEN: WITH ... WHERE
        WHEN: Compiled
        THEN: A 'Filter' op follows the 'WithProject' op
        """
        # GIVEN/WHEN
        ast = CypherParser().parse(
            "MATCH (n:Person) WITH n.name AS name, n.age AS age WHERE age > 30 RETURN name"
        )
        ir = CypherCompiler().compile(ast)

        # THEN
        ops = [op["op"] for op in ir]
        wp_idx = ops.index("WithProject")
        assert ops[wp_idx + 1] == "Filter"


# ---------------------------------------------------------------------------
# Execution: UNWIND
# ---------------------------------------------------------------------------

class TestUnwindExecution:
    """End-to-end execution tests for UNWIND."""

    def test_unwind_literal_list(self, fresh_executor):
        """
        GIVEN: An empty graph
        WHEN: UNWIND [10, 20, 30] AS x RETURN x
        THEN: Returns three rows with x=10, 20, 30
        """
        # GIVEN (fixture)

        # WHEN
        results = list(fresh_executor.execute("UNWIND [10, 20, 30] AS x RETURN x"))

        # THEN
        assert len(results) == 3
        values = [r.get("x") for r in results]
        assert values == [10, 20, 30]

    def test_unwind_empty_list(self, fresh_executor):
        """
        GIVEN: UNWIND of empty list
        WHEN: Executed
        THEN: Returns zero rows
        """
        # GIVEN/WHEN
        results = list(fresh_executor.execute("UNWIND [] AS x RETURN x"))

        # THEN
        assert results == []

    def test_unwind_node_property(self, fresh_executor):
        """
        GIVEN: A Post node with tags property ['a', 'b']
        WHEN: MATCH (p:Post) UNWIND p.tags AS tag RETURN tag
        THEN: Returns one row per tag
        """
        # GIVEN
        fresh_executor.graph_engine.create_node(
            labels=["Post"], properties={"tags": ["a", "b"]}
        )

        # WHEN
        results = list(fresh_executor.execute("MATCH (p:Post) UNWIND p.tags AS tag RETURN tag"))

        # THEN
        assert len(results) == 2
        tags = {r.get("tag") for r in results}
        assert tags == {"a", "b"}

    def test_unwind_preserves_order(self, fresh_executor):
        """
        GIVEN: UNWIND ['c', 'a', 'b'] AS x
        WHEN: Executed
        THEN: Row order is preserved
        """
        # GIVEN/WHEN
        results = list(fresh_executor.execute("UNWIND ['c', 'a', 'b'] AS x RETURN x"))

        # THEN
        values = [r.get("x") for r in results]
        assert values == ["c", "a", "b"]


# ---------------------------------------------------------------------------
# Execution: WITH
# ---------------------------------------------------------------------------

class TestWithExecution:
    """End-to-end execution tests for WITH."""

    def test_with_projects_columns(self, people_executor):
        """
        GIVEN: Two Person nodes
        WHEN: MATCH (n:Person) WITH n.name AS name RETURN name
        THEN: Returns one row per person with the 'name' column
        """
        # GIVEN (fixture)

        # WHEN
        results = list(people_executor.execute(
            "MATCH (n:Person) WITH n.name AS name RETURN name"
        ))

        # THEN
        assert len(results) == 2
        names = {r.get("name") for r in results}
        assert names == {"Alice", "Bob"}

    def test_with_where_filters_correctly(self, people_executor):
        """
        GIVEN: Two Person nodes (ages 32 and 24)
        WHEN: WITH ... WHERE age > 30 RETURN name
        THEN: Only Alice (age 32) is returned
        """
        # GIVEN (fixture)

        # WHEN
        results = list(people_executor.execute(
            "MATCH (n:Person) WITH n.name AS name, n.age AS age WHERE age > 30 RETURN name"
        ))

        # THEN
        assert len(results) == 1
        assert results[0].get("name") == "Alice"

    def test_with_no_where_returns_all(self, people_executor):
        """
        GIVEN: Two Person nodes
        WHEN: WITH without WHERE
        THEN: Both rows are returned
        """
        # GIVEN (fixture)

        # WHEN
        results = list(people_executor.execute(
            "MATCH (n:Person) WITH n.name AS name RETURN name"
        ))

        # THEN
        assert len(results) == 2

    def test_with_multiple_projections(self, people_executor):
        """
        GIVEN: Person nodes
        WHEN: WITH projects both name and age
        THEN: Both columns available in RETURN
        """
        # GIVEN (fixture)

        # WHEN
        results = list(people_executor.execute(
            "MATCH (n:Person) WITH n.name AS nm, n.age AS ag RETURN nm, ag"
        ))

        # THEN
        assert len(results) == 2
        for r in results:
            assert r.get("nm") is not None
            assert r.get("ag") is not None


# ---------------------------------------------------------------------------
# Async execute
# ---------------------------------------------------------------------------

class TestAsyncExecute:
    """Tests for UnifiedQueryEngine.execute_async()."""

    def test_execute_async_exists(self):
        """
        GIVEN: UnifiedQueryEngine
        WHEN: Checking for execute_async attribute
        THEN: It is an async function
        """
        # GIVEN
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import UnifiedQueryEngine
        import inspect

        # WHEN/THEN
        assert hasattr(UnifiedQueryEngine, "execute_async")
        assert inspect.iscoroutinefunction(UnifiedQueryEngine.execute_async)

    def test_execute_async_delegates_to_execute_query(self):
        """
        GIVEN: A UnifiedQueryEngine with mocked execute_query
        WHEN: execute_async is awaited
        THEN: execute_query is called with same arguments
        """
        # GIVEN
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import (
            UnifiedQueryEngine, QueryResult,
        )
        from ipfs_datasets_py.knowledge_graphs.core.query_executor import GraphEngine

        engine = UnifiedQueryEngine(backend=GraphEngine())
        calls: list = []
        fake_result = QueryResult(items=[], stats={}, counters=None, query_type="cypher")

        def fake_execute_query(query, params=None, budgets=None, query_type="auto"):
            calls.append((query, params))
            return fake_result

        engine.execute_query = fake_execute_query  # type: ignore[method-assign]

        # WHEN
        result = asyncio.run(
            engine.execute_async("MATCH (n) RETURN n", params={"k": "v"})
        )

        # THEN
        assert result is fake_result
        assert calls == [("MATCH (n) RETURN n", {"k": "v"})]

    def test_execute_async_concurrency(self):
        """
        GIVEN: A UnifiedQueryEngine with mocked execute_query
        WHEN: Two execute_async calls are awaited concurrently
        THEN: Both complete without error and execute_query is called twice
        """
        # GIVEN
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import (
            UnifiedQueryEngine, QueryResult,
        )
        from ipfs_datasets_py.knowledge_graphs.core.query_executor import GraphEngine

        engine = UnifiedQueryEngine(backend=GraphEngine())
        calls: list = []
        fake_result = QueryResult(items=[], stats={}, counters=None, query_type="cypher")

        def fake_execute_query(query, params=None, budgets=None, query_type="auto"):
            calls.append(query)
            return fake_result

        engine.execute_query = fake_execute_query  # type: ignore[method-assign]

        async def _run():
            r1, r2 = await asyncio.gather(
                engine.execute_async("MATCH (n) RETURN n"),
                engine.execute_async("MATCH (n) RETURN n"),
            )
            return r1, r2

        # WHEN
        r1, r2 = asyncio.run(_run())

        # THEN
        assert r1 is fake_result
        assert r2 is fake_result
        assert len(calls) == 2
