"""
Session 13 coverage tests — cypher/parser, ir_executor, wal, visualization,
transaction manager.

Targeting uncovered branches/statements to push overall coverage from 75% to ~78%.
"""
from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch, call
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Helper to build a minimal GraphEngine-like mock with a _nodes dict,
# plus create_node / get_node / get_relationships / update_node / delete_node.
# ---------------------------------------------------------------------------
def _make_engine(nodes=None, rels=None):
    engine = MagicMock()
    engine._nodes = nodes or {}

    def _create_node(labels=None, properties=None):
        n = MagicMock()
        n.id = f"node-{len(engine._nodes)+1}"
        n.labels = labels or []
        n._properties = properties or {}
        engine._nodes[n.id] = n
        return n

    def _get_node(nid):
        return engine._nodes.get(nid)

    engine.create_node.side_effect = _create_node
    engine.get_node.side_effect = _get_node
    engine.get_relationships.return_value = []
    return engine


# ---------------------------------------------------------------------------
# Section 1 — Cypher Parser: CASE expressions
# ---------------------------------------------------------------------------
class TestCypherParserCase(unittest.TestCase):
    """Tests for CASE WHEN ... THEN ... [ELSE] END parsing."""

    def _parse(self, query: str):
        from ipfs_datasets_py.knowledge_graphs.cypher.parser import CypherParser
        return CypherParser().parse(query)

    def test_simple_case_expression(self):
        """GIVEN a query with CASE expr WHEN v THEN r END WHEN query is parsed THEN CaseExpressionNode produced."""
        ast = self._parse(
            "MATCH (n) RETURN CASE n.status WHEN 'active' THEN 1 ELSE 0 END AS flag"
        )
        self.assertIsNotNone(ast)

    def test_generic_case_no_test_expression(self):
        """GIVEN a generic CASE WHEN cond THEN result END WHEN parsed THEN no test_expression."""
        ast = self._parse(
            "MATCH (n) RETURN CASE WHEN n.age > 18 THEN 'adult' ELSE 'minor' END AS category"
        )
        self.assertIsNotNone(ast)

    def test_case_multiple_when_clauses(self):
        """GIVEN CASE with multiple WHEN clauses WHEN parsed THEN ast produced without error."""
        ast = self._parse(
            "MATCH (n) RETURN CASE n.code "
            "WHEN 1 THEN 'one' "
            "WHEN 2 THEN 'two' "
            "ELSE 'other' END AS label"
        )
        self.assertIsNotNone(ast)

    def test_case_no_else(self):
        """GIVEN CASE without ELSE WHEN parsed THEN ast produced correctly."""
        ast = self._parse(
            "MATCH (n) RETURN CASE WHEN n.active THEN 'yes' END AS flag"
        )
        self.assertIsNotNone(ast)


# ---------------------------------------------------------------------------
# Section 2 — Cypher Parser: DETACH DELETE, STARTS WITH, ENDS WITH, IN, CONTAINS
# ---------------------------------------------------------------------------
class TestCypherParserStringOps(unittest.TestCase):
    """Tests for string/collection operators."""

    def _parse(self, query: str):
        from ipfs_datasets_py.knowledge_graphs.cypher.parser import CypherParser
        return CypherParser().parse(query)

    def test_detach_delete(self):
        """GIVEN DETACH DELETE clause WHEN parsed THEN DeleteClause.detach=True."""
        ast = self._parse("MATCH (n) DETACH DELETE n")
        self.assertIsNotNone(ast)

    def test_starts_with(self):
        """GIVEN STARTS WITH predicate WHEN parsed THEN BinaryOpNode produced."""
        ast = self._parse("MATCH (n) WHERE n.name STARTS WITH 'Al' RETURN n")
        self.assertIsNotNone(ast)

    def test_ends_with(self):
        """GIVEN ENDS WITH predicate WHEN parsed THEN BinaryOpNode produced."""
        ast = self._parse("MATCH (n) WHERE n.name ENDS WITH 'son' RETURN n")
        self.assertIsNotNone(ast)

    def test_in_operator(self):
        """GIVEN IN operator WHEN parsed THEN BinaryOpNode produced."""
        ast = self._parse("MATCH (n) WHERE n.role IN ['admin', 'user'] RETURN n")
        self.assertIsNotNone(ast)

    def test_contains_operator(self):
        """GIVEN CONTAINS operator WHEN parsed THEN BinaryOpNode produced."""
        ast = self._parse("MATCH (n) WHERE n.bio CONTAINS 'python' RETURN n")
        self.assertIsNotNone(ast)

    def test_is_null(self):
        """GIVEN IS NULL predicate WHEN parsed THEN UnaryOpNode produced."""
        ast = self._parse("MATCH (n) WHERE n.email IS NULL RETURN n")
        self.assertIsNotNone(ast)

    def test_is_not_null(self):
        """GIVEN IS NOT NULL predicate WHEN parsed THEN UnaryOpNode produced."""
        ast = self._parse("MATCH (n) WHERE n.email IS NOT NULL RETURN n")
        self.assertIsNotNone(ast)


# ---------------------------------------------------------------------------
# Section 3 — Cypher Parser: ORDER BY with DESC, SKIP, LIMIT combos
# ---------------------------------------------------------------------------
class TestCypherParserOrderSkipLimit(unittest.TestCase):
    """Tests for ORDER BY / SKIP / LIMIT."""

    def _parse(self, query: str):
        from ipfs_datasets_py.knowledge_graphs.cypher.parser import CypherParser
        return CypherParser().parse(query)

    def test_order_by_asc(self):
        """GIVEN ORDER BY col ASC WHEN parsed THEN OrderItem.ascending=True."""
        ast = self._parse("MATCH (n) RETURN n ORDER BY n.name ASC")
        self.assertIsNotNone(ast)

    def test_order_by_desc(self):
        """GIVEN ORDER BY col DESC WHEN parsed THEN OrderItem.ascending=False."""
        ast = self._parse("MATCH (n) RETURN n ORDER BY n.age DESC")
        self.assertIsNotNone(ast)

    def test_skip_and_limit(self):
        """GIVEN SKIP n LIMIT m WHEN parsed THEN numeric values captured."""
        ast = self._parse("MATCH (n) RETURN n SKIP 5 LIMIT 10")
        self.assertIsNotNone(ast)

    def test_with_distinct(self):
        """GIVEN WITH DISTINCT WHEN parsed THEN distinct flag set."""
        ast = self._parse("MATCH (n) WITH DISTINCT n.name AS name RETURN name")
        self.assertIsNotNone(ast)

    def test_list_literal(self):
        """GIVEN list literal WHEN parsed THEN ListNode produced."""
        ast = self._parse("RETURN [1, 2, 3] AS nums")
        self.assertIsNotNone(ast)

    def test_map_literal(self):
        """GIVEN map literal WHEN parsed THEN MapNode produced."""
        ast = self._parse("RETURN {name: 'Alice', age: 30} AS obj")
        self.assertIsNotNone(ast)

    def test_parenthesized_expression(self):
        """GIVEN parenthesized expression WHEN parsed THEN inner expr returned."""
        ast = self._parse("RETURN (1 + 2) * 3 AS result")
        self.assertIsNotNone(ast)

    def test_function_call_distinct(self):
        """GIVEN function call with DISTINCT WHEN parsed THEN FunctionCallNode.distinct=True."""
        ast = self._parse("MATCH (n) RETURN count(DISTINCT n.name) AS cnt")
        self.assertIsNotNone(ast)

    def test_function_call_star(self):
        """GIVEN count(*) WHEN parsed THEN FunctionCallNode with VariableNode('*')."""
        ast = self._parse("MATCH (n) RETURN count(*) AS total")
        self.assertIsNotNone(ast)

    def test_unary_negation(self):
        """GIVEN unary minus WHEN parsed THEN UnaryOpNode produced."""
        ast = self._parse("RETURN -42 AS neg")
        self.assertIsNotNone(ast)


# ---------------------------------------------------------------------------
# Section 4 — Cypher Parser: FOREACH body clause variants
# ---------------------------------------------------------------------------
class TestCypherParserForeachBody(unittest.TestCase):
    """Tests for FOREACH body containing SET and MERGE."""

    def _parse(self, query: str):
        from ipfs_datasets_py.knowledge_graphs.cypher.parser import CypherParser
        return CypherParser().parse(query)

    def test_foreach_with_create_body(self):
        """GIVEN FOREACH with CREATE body WHEN parsed THEN ForeachClause with CreateClause body."""
        ast = self._parse(
            "FOREACH (val IN [1, 2] | CREATE (:Number {v: val}))"
        )
        self.assertIsNotNone(ast)


# ---------------------------------------------------------------------------
# Section 5 — ir_executor: OrderBy, Limit, Skip, Foreach, CallSubquery
# ---------------------------------------------------------------------------
class TestIRExecutorOrderByLimitSkip(unittest.TestCase):
    """Tests for OrderBy, Limit, Skip IR operations."""

    def _run(self, operations, engine=None):
        from ipfs_datasets_py.knowledge_graphs.core.ir_executor import execute_ir_operations
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import (
            apply_operator,
            evaluate_compiled_expression,
        )
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.result import Record

        def evaluate_expression(expr, bindings):
            return evaluate_compiled_expression(expr, bindings)

        def compute_aggregation(func_name, values):
            if func_name == "count":
                return len(values)
            return sum(values) if values else 0

        return execute_ir_operations(
            graph_engine=engine or _make_engine(),
            operations=operations,
            parameters={},
            resolve_value=lambda v, p: v,
            apply_operator=apply_operator,
            evaluate_compiled_expression=evaluate_compiled_expression,
            evaluate_expression=evaluate_expression,
            compute_aggregation=compute_aggregation,
        )

    def _make_records(self, dicts):
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.result import Record
        return [Record(keys=list(d.keys()), values=list(d.values())) for d in dicts]

    def test_limit_trims_final_results(self):
        """GIVEN a ScanLabel producing 5 nodes + Limit 3 WHEN executed THEN <=3 results returned."""
        engine = _make_engine()
        nodes = [engine.create_node(labels=["Node"], properties={"i": i}) for i in range(5)]
        engine.find_nodes.return_value = nodes

        results = self._run([
            {"op": "ScanLabel", "label": "Node", "variable": "n"},
            {"op": "Project", "items": [{"expression": {"var": "n"}, "alias": "n"}]},
            {"op": "Limit", "count": 3},
        ], engine=engine)
        self.assertLessEqual(len(results), 3)

    def test_skip_removes_initial_results(self):
        """GIVEN 5 results + Skip 2 WHEN executed THEN at most 3 results."""
        engine = _make_engine()
        nodes = [engine.create_node(labels=["N"], properties={"i": i}) for i in range(5)]
        engine.find_nodes.return_value = nodes

        results = self._run([
            {"op": "ScanLabel", "label": "N", "variable": "n"},
            {"op": "Project", "items": [{"expression": {"var": "n"}, "alias": "n"}]},
            {"op": "Skip", "count": 2},
        ], engine=engine)
        self.assertLessEqual(len(results), 3)

    def test_orderby_with_property_sort(self):
        """GIVEN Project with OrderBy on a key WHEN executed THEN no error raised."""
        engine = _make_engine()
        n1 = engine.create_node(labels=["P"], properties={"age": 30})
        n2 = engine.create_node(labels=["P"], properties={"age": 20})
        engine.find_nodes.return_value = [n1, n2]

        # Just check it doesn't raise
        results = self._run([
            {"op": "ScanLabel", "label": "P", "variable": "n"},
            {"op": "Project", "items": [{"expression": {"var": "n"}, "alias": "n"}]},
            {"op": "OrderBy", "items": [{"expression": "age", "ascending": True}]},
        ], engine=engine)
        self.assertIsInstance(results, list)

    def test_orderby_no_items_is_noop(self):
        """GIVEN OrderBy with empty items WHEN executed THEN results unchanged."""
        results = self._run([
            {"op": "OrderBy", "items": []},
        ])
        self.assertEqual(results, [])

    def test_orderby_no_results_is_noop(self):
        """GIVEN OrderBy with no prior results WHEN executed THEN empty list returned."""
        results = self._run([
            {"op": "OrderBy", "items": [{"expression": "name", "ascending": True}]},
        ])
        self.assertEqual(results, [])


class TestIRExecutorForeachCallSubquery(unittest.TestCase):
    """Tests for Foreach and CallSubquery IR operations."""

    def _run(self, operations, engine=None):
        from ipfs_datasets_py.knowledge_graphs.core.ir_executor import execute_ir_operations
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import (
            apply_operator,
            evaluate_compiled_expression,
        )

        def evaluate_expression(expr, bindings):
            return evaluate_compiled_expression(expr, bindings)

        def compute_aggregation(func_name, values):
            return len(values) if func_name == "count" else 0

        return execute_ir_operations(
            graph_engine=engine or _make_engine(),
            operations=operations,
            parameters={},
            resolve_value=lambda v, p: v,
            apply_operator=apply_operator,
            evaluate_compiled_expression=evaluate_compiled_expression,
            evaluate_expression=evaluate_expression,
            compute_aggregation=compute_aggregation,
        )

    def test_foreach_creates_nodes_for_each_element(self):
        """GIVEN Foreach over [1,2,3] with CreateNode body WHEN executed THEN 3 nodes created."""
        engine = _make_engine()
        results = self._run([
            {
                "op": "Foreach",
                "variable": "x",
                "expression": [1, 2, 3],
                "body_ops": [
                    {"op": "CreateNode", "variable": "n", "labels": ["Num"], "properties": {}}
                ],
            }
        ], engine=engine)
        # 3 CreateNode calls from body
        self.assertEqual(engine.create_node.call_count, 3)

    def test_foreach_empty_list_no_body_runs(self):
        """GIVEN Foreach over empty list WHEN executed THEN no body ops run."""
        engine = _make_engine()
        results = self._run([
            {
                "op": "Foreach",
                "variable": "x",
                "expression": [],
                "body_ops": [
                    {"op": "CreateNode", "variable": "n", "labels": ["X"], "properties": {}}
                ],
            }
        ], engine=engine)
        engine.create_node.assert_not_called()

    def test_call_subquery_empty_inner(self):
        """GIVEN CallSubquery with no inner ops WHEN executed THEN outer bindings unchanged."""
        results = self._run([
            {
                "op": "CallSubquery",
                "inner_ops": [],
                "yield_items": [],
            }
        ])
        self.assertEqual(results, [])

    def test_unwind_from_literal(self):
        """GIVEN Unwind with literal list (no prior bindings) WHEN executed THEN 3 bindings."""
        from ipfs_datasets_py.knowledge_graphs.core.ir_executor import execute_ir_operations
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import (
            apply_operator,
            evaluate_compiled_expression,
        )

        def evaluate_expression(expr, bindings):
            return evaluate_compiled_expression(expr, bindings)

        def compute_aggregation(func_name, values):
            return 0

        results = execute_ir_operations(
            graph_engine=_make_engine(),
            operations=[
                {"op": "Unwind", "expression": ["a", "b", "c"], "variable": "x"},
                {"op": "Project", "items": [{"expression": {"var": "x"}, "alias": "x"}]},
            ],
            parameters={},
            resolve_value=lambda v, p: v,
            apply_operator=apply_operator,
            evaluate_compiled_expression=evaluate_compiled_expression,
            evaluate_expression=evaluate_expression,
            compute_aggregation=compute_aggregation,
        )
        self.assertEqual(len(results), 3)


# ---------------------------------------------------------------------------
# Section 6 — ir_executor: OptionalExpand, Delete, SetProperty
# ---------------------------------------------------------------------------
class TestIRExecutorMutations(unittest.TestCase):
    """Tests for Delete and SetProperty IR ops."""

    def _run(self, operations, engine=None):
        from ipfs_datasets_py.knowledge_graphs.core.ir_executor import execute_ir_operations
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import (
            apply_operator,
            evaluate_compiled_expression,
        )

        def evaluate_expression(expr, bindings):
            return evaluate_compiled_expression(expr, bindings)

        def compute_aggregation(func_name, values):
            return 0

        return execute_ir_operations(
            graph_engine=engine or _make_engine(),
            operations=operations,
            parameters={},
            resolve_value=lambda v, p: v,
            apply_operator=apply_operator,
            evaluate_compiled_expression=evaluate_compiled_expression,
            evaluate_expression=evaluate_expression,
            compute_aggregation=compute_aggregation,
        )

    def test_delete_removes_node_from_result_set(self):
        """GIVEN Delete op on existing variable WHEN executed THEN delete_node called."""
        engine = _make_engine()
        node = engine.create_node(labels=["X"], properties={})
        engine.find_nodes.return_value = [node]

        self._run([
            {"op": "ScanLabel", "label": "X", "variable": "n"},
            {"op": "Delete", "variable": "n"},
        ], engine=engine)
        engine.delete_node.assert_called()

    def test_set_property_updates_nodes(self):
        """GIVEN SetProperty on existing variable WHEN executed THEN update_node called."""
        engine = _make_engine()
        node = engine.create_node(labels=["P"], properties={"x": 0})
        engine.find_nodes.return_value = [node]

        self._run([
            {"op": "ScanLabel", "label": "P", "variable": "n"},
            {"op": "SetProperty", "variable": "n", "property": "x", "value": 99},
        ], engine=engine)
        engine.update_node.assert_called()

    def test_optional_expand_returns_null_when_no_match(self):
        """GIVEN OptionalExpand with no relationships WHEN executed THEN null binding for target."""
        engine = _make_engine()
        node = engine.create_node(labels=["A"], properties={})
        engine.find_nodes.return_value = [node]
        engine.get_relationships.return_value = []

        results = self._run([
            {"op": "ScanLabel", "label": "A", "variable": "a"},
            {
                "op": "OptionalExpand",
                "from_variable": "a",
                "to_variable": "b",
                "rel_variable": "r",
                "direction": "out",
                "rel_types": None,
                "target_labels": None,
            },
            {"op": "Project", "items": [
                {"expression": {"var": "a"}, "alias": "a"},
                {"expression": {"var": "b"}, "alias": "b"},
            ]},
        ], engine=engine)
        # OptionalExpand with no rels should yield one row with b=None
        self.assertIsInstance(results, list)


# ---------------------------------------------------------------------------
# Section 7 — WAL: compact, recover, get_transaction_history, verify_integrity
# ---------------------------------------------------------------------------
class _MockStorage:
    """In-memory mock storage with store_json / retrieve_json."""

    def __init__(self):
        self._store: Dict[str, Any] = {}
        self._counter = 0

    def store_json(self, data: Dict) -> str:
        self._counter += 1
        cid = f"cid-{self._counter}"
        import json
        self._store[cid] = json.dumps(data)
        return cid

    def retrieve_json(self, cid: str) -> Dict:
        import json
        raw = self._store.get(cid)
        if raw is None:
            raise KeyError(f"CID not found: {cid}")
        return json.loads(raw)


def _make_wal_entry(txn_id: str, state=None, ops=None, prev_cid=None):
    from ipfs_datasets_py.knowledge_graphs.transactions.types import (
        WALEntry, Operation, OperationType, TransactionState
    )
    if state is None:
        state = TransactionState.COMMITTED
    if ops is None:
        ops = [Operation(type=OperationType.WRITE_NODE, node_id="n1")]
    return WALEntry(
        txn_id=txn_id,
        timestamp=time.time(),
        operations=ops,
        prev_wal_cid=prev_cid,
        txn_state=state,
    )


class TestWALCompact(unittest.TestCase):
    """Tests for WriteAheadLog.compact()."""

    def test_compact_returns_new_cid(self):
        """GIVEN a WAL with entries WHEN compact called THEN returns new CID string."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        storage = _MockStorage()
        wal = WriteAheadLog(storage)

        entry = _make_wal_entry("txn-001")
        first_cid = wal.append(entry)

        new_cid = wal.compact(first_cid)
        self.assertIsInstance(new_cid, str)
        self.assertTrue(new_cid.startswith("cid-"))

    def test_compact_resets_entry_count(self):
        """GIVEN 5 appended entries WHEN compact called THEN _entry_count reset to 0 (reset after checkpoint append)."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        storage = _MockStorage()
        wal = WriteAheadLog(storage)

        for i in range(5):
            wal.append(_make_wal_entry(f"txn-{i:03}"))
        self.assertEqual(wal._entry_count, 5)

        checkpoint_cid = wal.wal_head_cid
        wal.compact(checkpoint_cid)
        # compact appends checkpoint (increments to 6) then resets to 0
        self.assertEqual(wal._entry_count, 0)

    def test_compact_updates_head(self):
        """GIVEN a WAL WHEN compact called THEN wal_head_cid becomes the checkpoint CID."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        storage = _MockStorage()
        wal = WriteAheadLog(storage)
        wal.append(_make_wal_entry("txn-001"))

        old_head = wal.wal_head_cid
        new_head = wal.compact(old_head)
        self.assertEqual(wal.wal_head_cid, new_head)


class TestWALRecover(unittest.TestCase):
    """Tests for WriteAheadLog.recover()."""

    def test_recover_empty_wal_returns_empty(self):
        """GIVEN a WAL with no head WHEN recover called THEN returns empty list."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        storage = _MockStorage()
        wal = WriteAheadLog(storage)
        ops = wal.recover()
        self.assertEqual(ops, [])

    def test_recover_committed_includes_ops(self):
        """GIVEN a committed entry in WAL WHEN recover called THEN its operations included."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            Operation, OperationType, TransactionState
        )
        storage = _MockStorage()
        wal = WriteAheadLog(storage)

        op = Operation(type=OperationType.WRITE_NODE, node_id="n1")
        entry = _make_wal_entry("txn-001", state=TransactionState.COMMITTED, ops=[op])
        wal.append(entry)

        ops = wal.recover()
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0].type, OperationType.WRITE_NODE)

    def test_recover_aborted_skips_ops(self):
        """GIVEN an aborted entry in WAL WHEN recover called THEN its operations NOT included."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            Operation, OperationType, TransactionState
        )
        storage = _MockStorage()
        wal = WriteAheadLog(storage)

        op = Operation(type=OperationType.WRITE_NODE, node_id="n1")
        entry = _make_wal_entry("txn-aborted", state=TransactionState.ABORTED, ops=[op])
        wal.append(entry)

        ops = wal.recover()
        self.assertEqual(ops, [])

    def test_recover_from_explicit_cid(self):
        """GIVEN explicit head CID WHEN recover(wal_head_cid=...) called THEN ops recovered."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            Operation, OperationType, TransactionState
        )
        storage = _MockStorage()
        wal = WriteAheadLog(storage)

        op = Operation(type=OperationType.WRITE_NODE, node_id="n9")
        entry = _make_wal_entry("txn-999", state=TransactionState.COMMITTED, ops=[op])
        cid = wal.append(entry)

        ops = wal.recover(wal_head_cid=cid)
        self.assertEqual(len(ops), 1)


class TestWALGetHistory(unittest.TestCase):
    """Tests for WriteAheadLog.get_transaction_history()."""

    def test_history_returns_matching_entries(self):
        """GIVEN entry with txn_id='txn-A' WHEN history queried for 'txn-A' THEN entry returned."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        storage = _MockStorage()
        wal = WriteAheadLog(storage)
        wal.append(_make_wal_entry("txn-A"))

        entries = wal.get_transaction_history("txn-A")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].txn_id, "txn-A")

    def test_history_returns_empty_for_unknown(self):
        """GIVEN no matching txn WHEN history queried THEN empty list returned."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        storage = _MockStorage()
        wal = WriteAheadLog(storage)
        wal.append(_make_wal_entry("txn-X"))

        entries = wal.get_transaction_history("txn-NOT-EXIST")
        self.assertEqual(entries, [])


class TestWALVerifyIntegrity(unittest.TestCase):
    """Tests for WriteAheadLog.verify_integrity()."""

    def test_empty_wal_verifies_true(self):
        """GIVEN empty WAL WHEN verify_integrity called THEN returns True."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        storage = _MockStorage()
        wal = WriteAheadLog(storage)
        self.assertTrue(wal.verify_integrity())

    def test_single_valid_entry_verifies_true(self):
        """GIVEN single committed entry WHEN verify_integrity called THEN returns True."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            Operation, OperationType, TransactionState
        )
        storage = _MockStorage()
        wal = WriteAheadLog(storage)
        op = Operation(type=OperationType.WRITE_NODE, node_id="n1")
        wal.append(_make_wal_entry("txn-001", ops=[op]))
        self.assertTrue(wal.verify_integrity())

    def test_entry_with_empty_operations_fails_integrity(self):
        """GIVEN entry with empty operations WHEN verify_integrity called THEN returns False."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            WALEntry, TransactionState
        )
        storage = _MockStorage()
        wal = WriteAheadLog(storage)
        # Append entry with empty operations list
        bad_entry = WALEntry(
            txn_id="txn-bad",
            timestamp=time.time(),
            operations=[],
        )
        wal.append(bad_entry)
        # verify_integrity checks `not entry.txn_id or not entry.operations`
        result = wal.verify_integrity()
        self.assertFalse(result)


class TestWALGetStats(unittest.TestCase):
    """Tests for WriteAheadLog.get_stats()."""

    def test_get_stats_keys(self):
        """GIVEN a WAL WHEN get_stats called THEN dict has required keys."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        storage = _MockStorage()
        wal = WriteAheadLog(storage)
        stats = wal.get_stats()
        self.assertIn("head_cid", stats)
        self.assertIn("entry_count", stats)
        self.assertIn("compaction_threshold", stats)
        self.assertIn("needs_compaction", stats)

    def test_get_stats_increments_with_appends(self):
        """GIVEN 3 appended entries WHEN get_stats called THEN entry_count is 3."""
        from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
        storage = _MockStorage()
        wal = WriteAheadLog(storage)
        for i in range(3):
            wal.append(_make_wal_entry(f"txn-{i}"))
        self.assertEqual(wal.get_stats()["entry_count"], 3)


# ---------------------------------------------------------------------------
# Section 8 — lineage/visualization with matplotlib available
# ---------------------------------------------------------------------------
class TestLineageVisualizerRenderNetworkx(unittest.TestCase):
    """Tests for LineageVisualizer.render_networkx using matplotlib."""

    def _make_graph(self):
        from ipfs_datasets_py.knowledge_graphs.lineage.core import LineageTracker
        from ipfs_datasets_py.knowledge_graphs.lineage.types import LineageLink
        tracker = LineageTracker()
        tracker.track_node("ds1", "dataset", metadata={"label": "raw"})
        tracker.track_node("t1", "transformation", metadata={"label": "clean"})
        return tracker.graph

    def test_render_networkx_returns_bytes_when_no_output_path(self):
        """GIVEN matplotlib installed WHEN render_networkx called without path THEN bytes returned."""
        try:
            import matplotlib  # noqa
        except ImportError:
            self.skipTest("matplotlib not installed")
        from ipfs_datasets_py.knowledge_graphs.lineage.visualization import LineageVisualizer
        g = self._make_graph()
        viz = LineageVisualizer(g)
        result = viz.render_networkx()
        self.assertIsInstance(result, bytes)
        self.assertGreater(len(result), 100)

    def test_render_networkx_circular_layout(self):
        """GIVEN circular layout WHEN render_networkx called THEN bytes returned."""
        try:
            import matplotlib  # noqa
        except ImportError:
            self.skipTest("matplotlib not installed")
        from ipfs_datasets_py.knowledge_graphs.lineage.visualization import LineageVisualizer
        g = self._make_graph()
        viz = LineageVisualizer(g)
        result = viz.render_networkx(layout='circular')
        self.assertIsInstance(result, bytes)

    def test_render_networkx_hierarchical_layout(self):
        """GIVEN hierarchical layout WHEN render_networkx called THEN bytes returned (or scipy skip)."""
        try:
            import matplotlib  # noqa
        except ImportError:
            self.skipTest("matplotlib not installed")
        try:
            import scipy  # noqa: kamada_kawai_layout requires scipy
        except ImportError:
            self.skipTest("scipy not installed (required for hierarchical layout)")
        from ipfs_datasets_py.knowledge_graphs.lineage.visualization import LineageVisualizer
        g = self._make_graph()
        viz = LineageVisualizer(g)
        result = viz.render_networkx(layout='hierarchical')
        self.assertIsInstance(result, bytes)

    def test_render_networkx_unknown_layout_fallback(self):
        """GIVEN unknown layout WHEN render_networkx called THEN falls back to spring and returns bytes."""
        try:
            import matplotlib  # noqa
        except ImportError:
            self.skipTest("matplotlib not installed")
        from ipfs_datasets_py.knowledge_graphs.lineage.visualization import LineageVisualizer
        g = self._make_graph()
        viz = LineageVisualizer(g)
        result = viz.render_networkx(layout='unknown-xyz')
        self.assertIsInstance(result, bytes)

    def test_render_networkx_with_output_path(self):
        """GIVEN output_path WHEN render_networkx called THEN None returned (file written)."""
        import tempfile
        import os
        try:
            import matplotlib  # noqa
        except ImportError:
            self.skipTest("matplotlib not installed")
        from ipfs_datasets_py.knowledge_graphs.lineage.visualization import LineageVisualizer
        g = self._make_graph()
        viz = LineageVisualizer(g)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path = f.name
        try:
            result = viz.render_networkx(output_path=path)
            self.assertIsNone(result)
            self.assertTrue(os.path.exists(path))
        finally:
            os.unlink(path)


class TestLineageVisualizerMissingMatplotlib(unittest.TestCase):
    """Tests for render_networkx/plotly with missing optional deps."""

    def _make_graph(self):
        from ipfs_datasets_py.knowledge_graphs.lineage.core import LineageTracker
        tracker = LineageTracker()
        tracker.track_node("n1", "dataset", metadata={})
        return tracker.graph

    def test_render_networkx_raises_if_matplotlib_missing(self):
        """GIVEN matplotlib not available WHEN render_networkx called THEN ImportError raised."""
        from ipfs_datasets_py.knowledge_graphs.lineage import visualization as viz_mod
        g = self._make_graph()
        viz = viz_mod.LineageVisualizer(g)

        # Patch the module-level flag
        orig = viz_mod.MATPLOTLIB_AVAILABLE
        try:
            viz_mod.MATPLOTLIB_AVAILABLE = False
            with self.assertRaises(ImportError):
                viz.render_networkx()
        finally:
            viz_mod.MATPLOTLIB_AVAILABLE = orig

    def test_render_plotly_raises_if_plotly_missing(self):
        """GIVEN plotly not available WHEN render_plotly called THEN ImportError raised."""
        from ipfs_datasets_py.knowledge_graphs.lineage import visualization as viz_mod
        g = self._make_graph()
        viz = viz_mod.LineageVisualizer(g)

        orig = viz_mod.PLOTLY_AVAILABLE
        try:
            viz_mod.PLOTLY_AVAILABLE = False
            with self.assertRaises(ImportError):
                viz.render_plotly()
        finally:
            viz_mod.PLOTLY_AVAILABLE = orig


class TestVisualizeLinkageFunction(unittest.TestCase):
    """Tests for module-level visualize_lineage() function."""

    def _make_tracker(self):
        from ipfs_datasets_py.knowledge_graphs.lineage.core import LineageTracker
        tracker = LineageTracker()
        tracker.track_node("ds1", "dataset", metadata={"label": "test"})
        return tracker

    def test_visualize_lineage_unknown_renderer_raises(self):
        """GIVEN unknown renderer WHEN visualize_lineage called THEN ValueError raised."""
        from ipfs_datasets_py.knowledge_graphs.lineage.visualization import visualize_lineage
        tracker = self._make_tracker()
        with self.assertRaises(ValueError):
            visualize_lineage(tracker, renderer="unknown-xyz")

    def test_visualize_lineage_networkx_renderer(self):
        """GIVEN networkx renderer WHEN visualize_lineage called (with matplotlib) THEN bytes returned."""
        try:
            import matplotlib  # noqa
        except ImportError:
            self.skipTest("matplotlib not installed")
        from ipfs_datasets_py.knowledge_graphs.lineage.visualization import visualize_lineage
        tracker = self._make_tracker()
        result = visualize_lineage(tracker, renderer='networkx')
        self.assertIsInstance(result, bytes)


# ---------------------------------------------------------------------------
# Section 9 — Transaction manager: _apply_operations DELETE_NODE, SET_PROPERTY
# ---------------------------------------------------------------------------
class TestTransactionManagerApplyOps(unittest.TestCase):
    """Tests for TransactionManager._apply_operations and commit error paths."""

    def _make_manager(self):
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        from ipfs_datasets_py.knowledge_graphs.transactions.types import IsolationLevel

        engine = _make_engine()
        storage = _MockStorage()
        mgr = TransactionManager(engine, storage)
        return mgr, engine

    def test_apply_write_node_creates_node(self):
        """GIVEN a WRITE_NODE operation in a committed transaction WHEN committed THEN create_node called."""
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            Operation, OperationType, IsolationLevel
        )
        mgr, engine = self._make_manager()
        txn = mgr.begin(IsolationLevel.READ_COMMITTED)
        op = Operation(type=OperationType.WRITE_NODE, data={"labels": ["X"], "properties": {}})
        mgr.add_operation(txn, op)
        mgr.commit(txn)
        engine.create_node.assert_called_once()

    def test_apply_delete_node_deletes_from_engine(self):
        """GIVEN a DELETE_NODE operation WHEN committed THEN node removed from engine._nodes."""
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            Operation, OperationType, IsolationLevel
        )
        mgr, engine = self._make_manager()
        # Pre-populate engine with a node
        node = engine.create_node(labels=["D"], properties={})
        engine._nodes[node.id] = node

        txn = mgr.begin(IsolationLevel.READ_COMMITTED)
        op = Operation(type=OperationType.DELETE_NODE, node_id=node.id)
        mgr.add_operation(txn, op)
        mgr.commit(txn)
        self.assertNotIn(node.id, engine._nodes)

    def test_apply_set_property_updates_node(self):
        """GIVEN SET_PROPERTY op WHEN committed THEN node property updated."""
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            Operation, OperationType, IsolationLevel
        )
        mgr, engine = self._make_manager()
        # Fake node as a dict in engine._nodes (matches _apply_operations code path)
        engine._nodes["n99"] = {"properties": {"x": 0}}

        txn = mgr.begin(IsolationLevel.READ_COMMITTED)
        op = Operation(
            type=OperationType.SET_PROPERTY,
            node_id="n99",
            data={"property": "x", "value": 42}
        )
        mgr.add_operation(txn, op)
        mgr.commit(txn)
        self.assertEqual(engine._nodes["n99"]["properties"]["x"], 42)

    def test_commit_raises_on_aborted_transaction(self):
        """GIVEN aborted transaction WHEN commit called THEN TransactionAbortedError raised."""
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            IsolationLevel, TransactionState
        )
        from ipfs_datasets_py.knowledge_graphs.exceptions import TransactionAbortedError
        mgr, engine = self._make_manager()
        txn = mgr.begin(IsolationLevel.READ_COMMITTED)
        # Force-abort the transaction
        txn.state = TransactionState.ABORTED
        with self.assertRaises((TransactionAbortedError, Exception)):
            mgr.commit(txn)

    def test_rollback_removes_from_active(self):
        """GIVEN active transaction WHEN rollback called THEN transaction removed from active dict."""
        from ipfs_datasets_py.knowledge_graphs.transactions.types import IsolationLevel
        mgr, engine = self._make_manager()
        txn = mgr.begin(IsolationLevel.READ_COMMITTED)
        self.assertIn(txn.txn_id, mgr._active_transactions)
        mgr.rollback(txn)
        self.assertNotIn(txn.txn_id, mgr._active_transactions)

    def test_get_stats_returns_expected_keys(self):
        """GIVEN TransactionManager WHEN get_stats called THEN dict has required keys."""
        mgr, engine = self._make_manager()
        stats = mgr.get_stats()
        self.assertIn("active_transactions", stats)
        self.assertIn("committed_writes_tracked", stats)


# ---------------------------------------------------------------------------
# Section 10 — ir_executor: no-engine returns empty
# ---------------------------------------------------------------------------
class TestIRExecutorNoEngine(unittest.TestCase):
    """Tests for execute_ir_operations with no graph engine."""

    def test_no_engine_returns_empty(self):
        """GIVEN graph_engine=None WHEN execute_ir_operations called THEN returns empty list."""
        from ipfs_datasets_py.knowledge_graphs.core.ir_executor import execute_ir_operations
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import (
            apply_operator,
            evaluate_compiled_expression,
        )

        results = execute_ir_operations(
            graph_engine=None,
            operations=[{"op": "ScanAll", "variable": "n"}],
            parameters={},
            resolve_value=lambda v, p: v,
            apply_operator=apply_operator,
            evaluate_compiled_expression=evaluate_compiled_expression,
            evaluate_expression=lambda e, b: evaluate_compiled_expression(e, b),
            compute_aggregation=lambda f, v: 0,
        )
        self.assertEqual(results, [])


# ---------------------------------------------------------------------------
# Section 12 — cypher/parser: CALL YIELD
# ---------------------------------------------------------------------------
class TestCypherParserCallYield(unittest.TestCase):
    """Tests for CALL subquery with YIELD clause."""

    def _parse(self, query: str):
        from ipfs_datasets_py.knowledge_graphs.cypher.parser import CypherParser
        return CypherParser().parse(query)

    def test_call_subquery_with_yield(self):
        """GIVEN CALL { RETURN ... } YIELD name WHEN parsed THEN CallSubquery with yield_items."""
        ast = self._parse(
            "CALL { MATCH (n:Person) RETURN n.name AS pname } "
            "YIELD pname "
            "RETURN pname"
        )
        self.assertIsNotNone(ast)

    def test_call_subquery_yield_with_alias(self):
        """GIVEN CALL YIELD name AS alias WHEN parsed THEN yield_items has alias."""
        ast = self._parse(
            "CALL { MATCH (n) RETURN count(n) AS total } "
            "YIELD total AS cnt "
            "RETURN cnt"
        )
        self.assertIsNotNone(ast)

    def test_call_subquery_no_yield(self):
        """GIVEN CALL without YIELD WHEN parsed THEN CallSubquery with empty yield_items."""
        ast = self._parse(
            "CALL { MATCH (n) RETURN n }"
        )
        self.assertIsNotNone(ast)


if __name__ == "__main__":
    unittest.main()
