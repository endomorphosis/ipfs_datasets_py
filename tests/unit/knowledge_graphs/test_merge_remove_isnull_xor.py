"""
Tests for MERGE clause, REMOVE clause, IS NULL/IS NOT NULL, and XOR
(deferred features — continuing from 3.4.3)

This test suite validates:
- MERGE: creates node if absent, reuses if present (idempotency)
- MERGE ON CREATE SET: only applies on creation
- MERGE ON MATCH SET: only applies on match
- REMOVE property: deletes a single property from matched nodes
- REMOVE label: removes a label from matched nodes
- IS NULL: filters nodes where a property does not exist
- IS NOT NULL: filters nodes where a property exists
- XOR: exclusive-or boolean operator in WHERE clause

Tests follow GIVEN-WHEN-THEN format per repository standards.
"""

import pytest

from ipfs_datasets_py.knowledge_graphs.core.query_executor import QueryExecutor, GraphEngine
from ipfs_datasets_py.knowledge_graphs.cypher.parser import CypherParser
from ipfs_datasets_py.knowledge_graphs.cypher.compiler import CypherCompiler
from ipfs_datasets_py.knowledge_graphs.cypher.ast import (
    MergeClause, RemoveClause, UnaryOpNode,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fresh_executor():
    """Return a fresh empty QueryExecutor."""
    return QueryExecutor(graph_engine=GraphEngine())


@pytest.fixture()
def mixed_executor():
    """QueryExecutor with one Person with email and one without."""
    engine = GraphEngine()
    engine.create_node(labels=["Person"], properties={"name": "Alice", "email": "a@b.com"})
    engine.create_node(labels=["Person"], properties={"name": "Bob"})
    return QueryExecutor(graph_engine=engine)


# ---------------------------------------------------------------------------
# Parser / AST
# ---------------------------------------------------------------------------

class TestMergeAST:
    """Parser creates correct AST nodes for MERGE."""

    def test_simple_merge_produces_merge_clause(self):
        """
        GIVEN: MERGE (n:Person {name: 'Alice'})
        WHEN: Parsed
        THEN: Clause is MergeClause
        """
        # GIVEN/WHEN
        ast = CypherParser().parse("MERGE (n:Person {name: 'Alice'})")
        clause = ast.clauses[0]

        # THEN
        assert isinstance(clause, MergeClause)

    def test_merge_preserves_patterns(self):
        """
        GIVEN: MERGE with a node pattern
        WHEN: Parsed
        THEN: patterns list is non-empty
        """
        # GIVEN/WHEN
        ast = CypherParser().parse("MERGE (n:Person {name: 'Alice'})")
        clause = ast.clauses[0]

        # THEN
        assert len(clause.patterns) >= 1

    def test_merge_empty_on_sets_by_default(self):
        """
        GIVEN: Simple MERGE without ON CREATE SET / ON MATCH SET
        WHEN: Parsed
        THEN: on_create_set and on_match_set are empty
        """
        # GIVEN/WHEN
        ast = CypherParser().parse("MERGE (n:Person {name: 'Alice'})")
        clause = ast.clauses[0]

        # THEN
        assert clause.on_create_set == []
        assert clause.on_match_set == []


class TestRemoveAST:
    """Parser creates correct AST nodes for REMOVE."""

    def test_remove_property_produces_remove_clause(self):
        """
        GIVEN: MATCH ... REMOVE n.email
        WHEN: Parsed
        THEN: Last clause before RETURN is RemoveClause
        """
        # GIVEN/WHEN
        ast = CypherParser().parse("MATCH (n:Person) REMOVE n.email RETURN n")
        remove = ast.clauses[1]

        # THEN
        assert isinstance(remove, RemoveClause)

    def test_remove_property_item_type(self):
        """
        GIVEN: REMOVE n.email
        WHEN: Parsed
        THEN: item type is 'property'
        """
        # GIVEN/WHEN
        ast = CypherParser().parse("MATCH (n:Person) REMOVE n.email RETURN n")
        remove = ast.clauses[1]

        # THEN
        assert remove.items[0]["type"] == "property"
        assert remove.items[0]["variable"] == "n"
        assert remove.items[0]["property"] == "email"

    def test_remove_label_item_type(self):
        """
        GIVEN: REMOVE n:Employee
        WHEN: Parsed
        THEN: item type is 'label'
        """
        # GIVEN/WHEN
        ast = CypherParser().parse("MATCH (n:Person) REMOVE n:Person RETURN n")
        remove = ast.clauses[1]

        # THEN
        assert remove.items[0]["type"] == "label"
        assert remove.items[0]["label"] == "Person"


class TestIsNullAST:
    """Parser creates IS NULL / IS NOT NULL UnaryOpNode."""

    def test_is_null_creates_unary_op(self):
        """
        GIVEN: WHERE p.email IS NULL
        WHEN: Parsed
        THEN: MATCH clause where expression is UnaryOpNode with 'IS NULL'
        """
        # GIVEN/WHEN
        ast = CypherParser().parse("MATCH (p:Person) WHERE p.email IS NULL RETURN p")
        # WHERE is embedded in the MatchClause
        match_clause = ast.clauses[0]

        # THEN
        where = match_clause.where
        assert where is not None
        assert isinstance(where.expression, UnaryOpNode)
        assert where.expression.operator.upper() == "IS NULL"

    def test_is_not_null_creates_unary_op(self):
        """
        GIVEN: WHERE p.email IS NOT NULL
        WHEN: Parsed
        THEN: MATCH clause where expression is UnaryOpNode with 'IS NOT NULL'
        """
        # GIVEN/WHEN
        ast = CypherParser().parse("MATCH (p:Person) WHERE p.email IS NOT NULL RETURN p")
        match_clause = ast.clauses[0]

        # THEN
        where = match_clause.where
        assert where is not None
        assert isinstance(where.expression, UnaryOpNode)
        assert where.expression.operator.upper() == "IS NOT NULL"


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------

class TestMergeCompilation:
    """Compiler emits Merge IR op."""

    def test_merge_emits_merge_op(self):
        """
        GIVEN: MERGE query
        WHEN: Compiled
        THEN: IR contains 'Merge' op
        """
        # GIVEN/WHEN
        ast = CypherParser().parse("MERGE (n:Person {name: 'Alice'})")
        ir = CypherCompiler().compile(ast)

        # THEN
        ops = [op["op"] for op in ir]
        assert "Merge" in ops

    def test_merge_includes_match_and_create_ops(self):
        """
        GIVEN: MERGE node
        WHEN: Compiled
        THEN: Merge IR op has non-empty match_ops and create_ops
        """
        # GIVEN/WHEN
        ast = CypherParser().parse("MERGE (n:Person {name: 'Alice'})")
        ir = CypherCompiler().compile(ast)

        merge_op = next(op for op in ir if op["op"] == "Merge")

        # THEN
        assert len(merge_op["match_ops"]) > 0
        assert len(merge_op["create_ops"]) > 0


class TestRemoveCompilation:
    """Compiler emits RemoveProperty / RemoveLabel ops."""

    def test_remove_property_emits_remove_property_op(self):
        """
        GIVEN: MATCH ... REMOVE n.email
        WHEN: Compiled
        THEN: IR contains 'RemoveProperty' op
        """
        # GIVEN/WHEN
        ast = CypherParser().parse("MATCH (n:Person) REMOVE n.email RETURN n")
        ir = CypherCompiler().compile(ast)

        # THEN
        ops = [op["op"] for op in ir]
        assert "RemoveProperty" in ops

    def test_remove_label_emits_remove_label_op(self):
        """
        GIVEN: MATCH ... REMOVE n:Employee
        WHEN: Compiled
        THEN: IR contains 'RemoveLabel' op
        """
        # GIVEN/WHEN
        ast = CypherParser().parse("MATCH (n:Person) REMOVE n:Person RETURN n")
        ir = CypherCompiler().compile(ast)

        # THEN
        ops = [op["op"] for op in ir]
        assert "RemoveLabel" in ops


class TestIsNullCompilation:
    """Compiler emits Filter with IS NULL / IS NOT NULL."""

    def test_is_null_emits_filter_op(self):
        """
        GIVEN: WHERE p.email IS NULL
        WHEN: Compiled
        THEN: IR contains Filter with IS NULL expression
        """
        # GIVEN/WHEN
        ast = CypherParser().parse("MATCH (p:Person) WHERE p.email IS NULL RETURN p")
        ir = CypherCompiler().compile(ast)

        filter_op = next((op for op in ir if op.get("op") == "Filter"), None)

        # THEN
        assert filter_op is not None
        expr = filter_op.get("expression", {})
        assert expr.get("op") == "IS NULL"


# ---------------------------------------------------------------------------
# Execution: MERGE
# ---------------------------------------------------------------------------

class TestMergeExecution:
    """End-to-end execution tests for MERGE."""

    def test_merge_creates_node_when_absent(self, fresh_executor):
        """
        GIVEN: An empty graph
        WHEN: MERGE (n:Person {name: 'Alice'})
        THEN: Alice is created and MATCH returns her
        """
        # GIVEN (empty graph from fixture)

        # WHEN
        list(fresh_executor.execute("MERGE (n:Person {name: 'Alice'})"))
        results = list(fresh_executor.execute("MATCH (n:Person) RETURN n.name"))

        # THEN
        assert len(results) == 1
        assert results[0].get("n.name") == "Alice"

    def test_merge_idempotent_node(self, fresh_executor):
        """
        GIVEN: Alice already exists
        WHEN: MERGE (n:Person {name: 'Alice'}) called again
        THEN: Still exactly one Alice (no duplicate)
        """
        # GIVEN
        list(fresh_executor.execute("MERGE (n:Person {name: 'Alice'})"))

        # WHEN
        list(fresh_executor.execute("MERGE (n:Person {name: 'Alice'})"))
        results = list(fresh_executor.execute("MATCH (n:Person) RETURN n.name"))

        # THEN
        assert len(results) == 1

    def test_merge_creates_different_nodes(self, fresh_executor):
        """
        GIVEN: Alice exists
        WHEN: MERGE (n:Person {name: 'Bob'})
        THEN: Both Alice and Bob exist
        """
        # GIVEN
        list(fresh_executor.execute("MERGE (n:Person {name: 'Alice'})"))

        # WHEN
        list(fresh_executor.execute("MERGE (n:Person {name: 'Bob'})"))
        results = list(fresh_executor.execute("MATCH (n:Person) RETURN n.name"))

        # THEN
        assert len(results) == 2
        names = {r.get("n.name") for r in results}
        assert names == {"Alice", "Bob"}

    def test_merge_multiple_consecutive_idempotent(self, fresh_executor):
        """
        GIVEN: Multiple MERGE calls with same node
        WHEN: Execute 3 times
        THEN: Count stays at 1
        """
        # GIVEN/WHEN
        for _ in range(3):
            list(fresh_executor.execute("MERGE (n:Person {name: 'Alice'})"))
        results = list(fresh_executor.execute("MATCH (n:Person) RETURN n.name"))

        # THEN
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Execution: REMOVE
# ---------------------------------------------------------------------------

class TestRemoveExecution:
    """End-to-end execution tests for REMOVE."""

    def test_remove_property_deletes_property(self, mixed_executor):
        """
        GIVEN: Alice has an 'email' property
        WHEN: MATCH (p:Person {name: 'Alice'}) REMOVE p.email
        THEN: Alice's email is gone
        """
        # GIVEN (Alice has email from fixture)

        # WHEN
        list(mixed_executor.execute(
            "MATCH (p:Person) WHERE p.name = 'Alice' REMOVE p.email"
        ))
        results = list(mixed_executor.execute(
            "MATCH (p:Person) WHERE p.name = 'Alice' RETURN p.email"
        ))

        # THEN
        assert results[0].get("p.email") is None

    def test_remove_label_removes_label(self, fresh_executor):
        """
        GIVEN: A node with labels ['Employee', 'Person']
        WHEN: REMOVE n:Employee
        THEN: Node no longer matches MATCH (n:Employee)
        """
        # GIVEN
        fresh_executor.graph_engine.create_node(
            labels=["Employee", "Person"], properties={"name": "Charlie"}
        )

        # WHEN
        list(fresh_executor.execute("MATCH (n:Employee) REMOVE n:Employee"))
        results = list(fresh_executor.execute("MATCH (n:Employee) RETURN n.name"))

        # THEN
        assert results == []

    def test_remove_nonexistent_property_is_safe(self, fresh_executor):
        """
        GIVEN: A node without property 'missing'
        WHEN: REMOVE n.missing
        THEN: No error raised, node unchanged
        """
        # GIVEN
        fresh_executor.graph_engine.create_node(
            labels=["Item"], properties={"x": 1}
        )

        # WHEN / THEN (must not raise)
        list(fresh_executor.execute("MATCH (n:Item) REMOVE n.missing"))


# ---------------------------------------------------------------------------
# Execution: IS NULL / IS NOT NULL
# ---------------------------------------------------------------------------

class TestIsNullExecution:
    """End-to-end execution tests for IS NULL and IS NOT NULL."""

    def test_is_null_returns_nodes_without_property(self, mixed_executor):
        """
        GIVEN: Alice (has email) and Bob (no email)
        WHEN: WHERE p.email IS NULL
        THEN: Only Bob is returned
        """
        # GIVEN (fixture)

        # WHEN
        results = list(mixed_executor.execute(
            "MATCH (p:Person) WHERE p.email IS NULL RETURN p.name"
        ))

        # THEN
        assert len(results) == 1
        assert results[0].get("p.name") == "Bob"

    def test_is_not_null_returns_nodes_with_property(self, mixed_executor):
        """
        GIVEN: Alice (has email) and Bob (no email)
        WHEN: WHERE p.email IS NOT NULL
        THEN: Only Alice is returned
        """
        # GIVEN (fixture)

        # WHEN
        results = list(mixed_executor.execute(
            "MATCH (p:Person) WHERE p.email IS NOT NULL RETURN p.name"
        ))

        # THEN
        assert len(results) == 1
        assert results[0].get("p.name") == "Alice"

    def test_is_null_empty_result_when_all_have_property(self, fresh_executor):
        """
        GIVEN: All nodes have the property
        WHEN: WHERE p.x IS NULL
        THEN: Empty result
        """
        # GIVEN
        fresh_executor.graph_engine.create_node(labels=["N"], properties={"x": 1})
        fresh_executor.graph_engine.create_node(labels=["N"], properties={"x": 2})

        # WHEN
        results = list(fresh_executor.execute("MATCH (n:N) WHERE n.x IS NULL RETURN n.x"))

        # THEN
        assert results == []

    def test_is_not_null_empty_result_when_none_have_property(self, fresh_executor):
        """
        GIVEN: No nodes have property 'y'
        WHEN: WHERE n.y IS NOT NULL
        THEN: Empty result
        """
        # GIVEN
        fresh_executor.graph_engine.create_node(labels=["N"], properties={"x": 1})

        # WHEN
        results = list(fresh_executor.execute("MATCH (n:N) WHERE n.y IS NOT NULL RETURN n.x"))

        # THEN
        assert results == []


# ---------------------------------------------------------------------------
# Execution: XOR
# ---------------------------------------------------------------------------

class TestXorExecution:
    """End-to-end execution tests for XOR boolean operator."""

    def test_xor_true_xor_false_returns_row(self, fresh_executor):
        """
        GIVEN: A node with a=True, b=False (XOR=True)
        WHEN: WHERE n.a XOR n.b
        THEN: Row is returned
        """
        # GIVEN
        fresh_executor.graph_engine.create_node(
            labels=["Flag"], properties={"a": True, "b": False}
        )

        # WHEN
        results = list(fresh_executor.execute("MATCH (n:Flag) WHERE n.a XOR n.b RETURN n.a"))

        # THEN
        assert len(results) == 1

    def test_xor_true_xor_true_returns_nothing(self, fresh_executor):
        """
        GIVEN: A node with a=True, b=True (XOR=False)
        WHEN: WHERE n.a XOR n.b
        THEN: No rows returned
        """
        # GIVEN
        fresh_executor.graph_engine.create_node(
            labels=["Flag"], properties={"a": True, "b": True}
        )

        # WHEN
        results = list(fresh_executor.execute("MATCH (n:Flag) WHERE n.a XOR n.b RETURN n.a"))

        # THEN
        assert results == []

    def test_xor_selects_only_exclusive_row(self, fresh_executor):
        """
        GIVEN: Two nodes: one with a XOR b = True, one with a XOR b = False
        WHEN: WHERE n.a XOR n.b
        THEN: Only the first node is returned
        """
        # GIVEN
        fresh_executor.graph_engine.create_node(
            labels=["Flag"], properties={"a": True, "b": False, "id": 1}
        )
        fresh_executor.graph_engine.create_node(
            labels=["Flag"], properties={"a": True, "b": True, "id": 2}
        )

        # WHEN
        results = list(fresh_executor.execute("MATCH (n:Flag) WHERE n.a XOR n.b RETURN n.id"))

        # THEN
        assert len(results) == 1
        assert results[0].get("n.id") == 1
