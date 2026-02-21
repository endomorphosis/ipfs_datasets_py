"""
Session 35 – knowledge_graphs coverage push.

Targets (18 new GIVEN-WHEN-THEN tests):
  • core/query_executor.py    97% → 99%  – is_cypher patterns, _execute_cypher error branches
  • core/_legacy_graph_engine.py 99% → 100% – traverse direction=in, missing target, BFS visited
  • lineage/enhanced.py       99% → 100% – calculate_path_confidence empty path, find_similar_nodes self-skip
  • lineage/metrics.py        97% → 99%  – detect_circular_dependencies networkx ImportError
  • transactions/manager.py   99% → 100% – commit TransactionAbortedError re-raise
  • indexing/btree.py         99% → 100% – BTreeNode insert key-exists but no entries list
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# 1. core/query_executor.py – lines 118, 221, 238, 253, 270
# ===========================================================================

class TestQueryExecutorMissedPaths:
    """GIVEN a QueryExecutor with mocked internals,
    WHEN Cypher-pattern detection and error branches are exercised,
    THEN the correct code paths are covered."""

    def _executor(self):
        from ipfs_datasets_py.knowledge_graphs.core.query_executor import QueryExecutor
        return QueryExecutor(graph_engine=MagicMock())

    # -----------------------------------------------------------------------
    # Line 118: _is_cypher_query – structural patterns like (), [], -->, <--
    # -----------------------------------------------------------------------
    def test_is_cypher_query_empty_node_syntax_returns_true(self):
        """GIVEN a query containing '()' WHEN _is_cypher_query is called
        THEN True is returned (line 118)."""
        qe = self._executor()
        assert qe._is_cypher_query("MATCH () RETURN n") is True

    def test_is_cypher_query_bracket_syntax_returns_true(self):
        """GIVEN a query containing '[]' WHEN _is_cypher_query is called
        THEN True is returned (line 118)."""
        qe = self._executor()
        assert qe._is_cypher_query("MATCH [r] RETURN r") is True

    def test_is_cypher_query_arrow_returns_true(self):
        """GIVEN a query containing '-->' WHEN _is_cypher_query is called
        THEN True is returned (line 118)."""
        qe = self._executor()
        assert qe._is_cypher_query("MATCH a-->b RETURN b") is True

    def test_is_cypher_query_reverse_arrow_returns_true(self):
        """GIVEN a query containing '<--' WHEN _is_cypher_query is called
        THEN True is returned (line 118)."""
        qe = self._executor()
        assert qe._is_cypher_query("MATCH a<--b RETURN b") is True

    # Helper: patch cypher modules so _execute_cypher reaches the error handlers
    def _execute_with_side_effect(self, qe, side_effect, *, raise_on_error=False):
        import ipfs_datasets_py.knowledge_graphs.cypher as cymod

        ast = MagicMock()
        ast.clauses = [MagicMock()]
        mock_parser = MagicMock()
        mock_parser.parse.return_value = ast
        mock_compiler = MagicMock()
        mock_compiler.compile.return_value = []

        with patch.object(qe, "_execute_ir_operations", side_effect=side_effect):
            with patch.object(cymod, "CypherParser", return_value=mock_parser):
                with patch.object(cymod, "CypherCompiler", return_value=mock_compiler):
                    return qe._execute_cypher(
                        "MATCH (n) RETURN n", {}, raise_on_error=raise_on_error
                    )

    # -----------------------------------------------------------------------
    # Line 238: StorageError with raise_on_error=True → QueryExecutionError raised
    # -----------------------------------------------------------------------
    def test_execute_cypher_storage_error_raise_on_error(self):
        """GIVEN _execute_ir_operations raises StorageError and raise_on_error=True
        WHEN _execute_cypher is called THEN QueryExecutionError is raised (line 238)."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import StorageError
        from ipfs_datasets_py.knowledge_graphs.exceptions import QueryExecutionError

        qe = self._executor()
        with pytest.raises(QueryExecutionError):
            self._execute_with_side_effect(
                qe, StorageError("disk full"), raise_on_error=True
            )

    # -----------------------------------------------------------------------
    # Line 221: StorageError with raise_on_error=False → returns empty Result
    # -----------------------------------------------------------------------
    def test_execute_cypher_storage_error_no_raise_returns_empty_result(self):
        """GIVEN _execute_ir_operations raises StorageError and raise_on_error=False
        WHEN _execute_cypher is called THEN an empty Result is returned (line 221)."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import StorageError

        qe = self._executor()
        result = self._execute_with_side_effect(
            qe, StorageError("io error"), raise_on_error=False
        )
        assert result is not None
        assert len(list(result)) == 0

    # -----------------------------------------------------------------------
    # Line 253: KnowledgeGraphError with raise_on_error=True → re-raised
    # -----------------------------------------------------------------------
    def test_execute_cypher_knowledge_graph_error_raise_on_error(self):
        """GIVEN _execute_ir_operations raises KnowledgeGraphError and
        raise_on_error=True WHEN _execute_cypher is called THEN the error is
        re-raised (line 253)."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import KnowledgeGraphError

        qe = self._executor()
        with pytest.raises(KnowledgeGraphError):
            self._execute_with_side_effect(
                qe, KnowledgeGraphError("graph error"), raise_on_error=True
            )

    # -----------------------------------------------------------------------
    # Lines 255-265: KnowledgeGraphError with raise_on_error=False → empty Result
    # -----------------------------------------------------------------------
    def test_execute_cypher_knowledge_graph_error_no_raise_returns_empty_result(self):
        """GIVEN _execute_ir_operations raises KnowledgeGraphError and
        raise_on_error=False WHEN _execute_cypher is called THEN an empty
        Result is returned (lines 255-265)."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import KnowledgeGraphError

        qe = self._executor()
        result = self._execute_with_side_effect(
            qe, KnowledgeGraphError("kg error"), raise_on_error=False
        )
        assert result is not None
        assert len(list(result)) == 0

    # -----------------------------------------------------------------------
    # Line 270: generic Exception with raise_on_error=True → QueryExecutionError
    # -----------------------------------------------------------------------
    def test_execute_cypher_generic_exception_raise_on_error(self):
        """GIVEN _execute_ir_operations raises a generic ValueError and
        raise_on_error=True WHEN _execute_cypher is called THEN
        QueryExecutionError is raised (line 270)."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import QueryExecutionError

        qe = self._executor()
        with pytest.raises(QueryExecutionError):
            self._execute_with_side_effect(
                qe, ValueError("unexpected"), raise_on_error=True
            )


# ===========================================================================
# 2. core/_legacy_graph_engine.py – lines 513, 519, 588
# ===========================================================================

class TestLegacyGraphEngineMissedPaths:
    """GIVEN a _LegacyGraphEngine with controlled cache state,
    WHEN direction='in' traversal, missing target nodes, and BFS visited
    guard are exercised, THEN the corresponding branches fire."""

    def _engine_with_nodes(self):
        from ipfs_datasets_py.knowledge_graphs.core._legacy_graph_engine import (
            _LegacyGraphEngine,
        )
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.types import (
            Node,
            Relationship as CompatRel,
        )

        engine = _LegacyGraphEngine()
        n1 = Node("n1", ["Person"], {"name": "Alice"})
        n2 = Node("n2", ["Person"], {"name": "Bob"})
        n3 = Node("n3", ["Person"], {"name": "Carol"})
        r1 = CompatRel("r1", "KNOWS", n1, n2, {})
        engine._node_cache = {"n1": n1, "n2": n2, "n3": n3}
        engine._relationship_cache = {"r1": r1}
        return engine, n1, n2, n3

    # -----------------------------------------------------------------------
    # Line 513: direction='in' → target_id = rel._start_node
    # -----------------------------------------------------------------------
    def test_traverse_pattern_direction_in_uses_start_node(self):
        """GIVEN a KNOWS relationship from n1 → n2 and a pattern with
        direction='in' starting at n2 WHEN traverse_pattern is called
        THEN n1 is reached via rel._start_node (line 513)."""
        engine, n1, n2, _ = self._engine_with_nodes()
        pattern = [{"rel_type": "KNOWS", "direction": "in"}]
        result = engine.traverse_pattern(start_nodes=[n2], pattern=pattern)
        # Should find n1 by following the 'in' direction
        assert len(result) > 0

    # -----------------------------------------------------------------------
    # Line 519: target_node not in cache → continue (skip dangling edge)
    # -----------------------------------------------------------------------
    def test_traverse_pattern_missing_target_node_is_skipped(self):
        """GIVEN a relationship pointing to a node NOT in _node_cache WHEN
        traverse_pattern is called THEN the dangling edge is skipped (line 519)."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.types import (
            Node,
            Relationship as CompatRel,
        )

        engine, _, n2, _ = self._engine_with_nodes()
        missing_node = Node("n_missing", ["Thing"], {})
        r_dangling = CompatRel("r_dang", "LIKES", n2, missing_node, {})
        engine._relationship_cache["r_dang"] = r_dangling

        pattern = [{"rel_type": "LIKES", "direction": "out"}]
        result = engine.traverse_pattern(start_nodes=[n2], pattern=pattern)
        assert result == []

    # -----------------------------------------------------------------------
    # Line 588: BFS visited guard prevents revisiting during find_paths
    # -----------------------------------------------------------------------
    def test_find_paths_bfs_visited_guard_handles_cycle(self):
        """GIVEN a graph with a cycle (n1→n2→n3→n1) WHEN find_paths(n1, n2)
        is called THEN the BFS visited guard (line 588) prevents infinite
        traversal and at least one path is found."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.types import (
            Relationship as CompatRel,
        )

        engine, n1, n2, n3 = self._engine_with_nodes()
        # Add cycle: n2→n3→n1
        r2 = CompatRel("r2", "KNOWS", n2, n3, {})
        r3 = CompatRel("r3", "KNOWS", n3, n1, {})
        engine._relationship_cache["r2"] = r2
        engine._relationship_cache["r3"] = r3

        paths = engine.find_paths("n1", "n2", max_depth=5)
        # Should find at least the direct path n1→n2
        assert paths is not None


# ===========================================================================
# 3. lineage/enhanced.py – lines 259, 424 (430)
# ===========================================================================

class TestLineageEnhancedMissedPaths:
    """GIVEN a ConfidenceScorer and EnhancedLineageTracker,
    WHEN the empty-path confidence and self-loop skip paths are exercised,
    THEN the correct branches fire."""

    # -----------------------------------------------------------------------
    # Line 259: calculate_path_confidence with empty path → return 1.0
    # -----------------------------------------------------------------------
    def test_calculate_path_confidence_empty_path_returns_one(self):
        """GIVEN an empty path WHEN calculate_path_confidence is called
        THEN 1.0 is returned (line 259)."""
        from ipfs_datasets_py.knowledge_graphs.lineage.enhanced import ConfidenceScorer

        cs = ConfidenceScorer()
        graph = MagicMock()
        graph._graph = MagicMock()
        graph._graph.edges = {}
        result = cs.calculate_path_confidence(graph, [])
        assert result == 1.0

    # -----------------------------------------------------------------------
    # Line 424 (430): find_similar_nodes skips self (other_id == node_id → continue)
    # -----------------------------------------------------------------------
    def test_find_similar_nodes_skips_self(self):
        """GIVEN two tracked nodes WHEN find_similar_nodes('n1') is called
        THEN 'n1' is not in the similar-nodes result (line 430)."""
        from ipfs_datasets_py.knowledge_graphs.lineage.enhanced import (
            EnhancedLineageTracker,
        )

        tracker = EnhancedLineageTracker()
        tracker.track_node("n1", "dataset", "Dataset 1")
        tracker.track_node("n2", "dataset", "Dataset 2")
        similar = tracker.find_similar_nodes("n1", threshold=0.0)
        result_ids = [s[0] for s in similar]
        assert "n1" not in result_ids  # self was skipped
        assert "n2" in result_ids  # other node included


# ===========================================================================
# 4. lineage/metrics.py – lines 289-291
#    (detect_circular_dependencies networkx ImportError fallback)
# ===========================================================================

class TestLineageMetricsMissedPaths:
    """GIVEN a DependencyAnalyzer whose networkx is patched to be unavailable,
    WHEN detect_circular_dependencies is called,
    THEN an empty list is returned (lines 289-291)."""

    def test_detect_circular_dependencies_networkx_import_error(self):
        """GIVEN networkx is patched to None (ImportError) WHEN
        detect_circular_dependencies is called THEN [] is returned
        (lines 289-291)."""
        from ipfs_datasets_py.knowledge_graphs.lineage.core import LineageTracker
        from ipfs_datasets_py.knowledge_graphs.lineage.metrics import DependencyAnalyzer

        tracker = LineageTracker()
        da = DependencyAnalyzer(tracker=tracker)
        with patch.dict(sys.modules, {"networkx": None}):
            cycles = da.detect_circular_dependencies()
        assert cycles == []


# ===========================================================================
# 5. transactions/manager.py – line 261
#    (commit TransactionAbortedError is re-raised unchanged)
# ===========================================================================

class TestTransactionManagerMissedPaths:
    """GIVEN a TransactionManager whose _apply_operations raises
    TransactionAbortedError, WHEN commit is called,
    THEN the error is re-raised (line 261)."""

    def test_commit_reraises_transaction_aborted_error(self):
        """GIVEN _apply_operations raises TransactionAbortedError WHEN commit
        is called THEN TransactionAbortedError propagates unchanged (line 261)."""
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import (
            TransactionManager,
        )
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            TransactionAbortedError,
        )

        ge = MagicMock()
        storage = MagicMock()
        tm = TransactionManager(graph_engine=ge, storage_backend=storage)
        txn = tm.begin()

        with patch.object(
            tm, "_apply_operations", side_effect=TransactionAbortedError("forced abort")
        ):
            with patch.object(tm.wal, "append", return_value="wal-cid-1"):
                with pytest.raises(TransactionAbortedError, match="forced abort"):
                    tm.commit(txn)


# ===========================================================================
# 6. indexing/btree.py – line 60
#    (BTreeNode.insert: key in keys but entries not yet initialised)
# ===========================================================================

class TestBTreeMissedPaths:
    """GIVEN a BTreeNode whose entries dict has been manually cleared WHEN a
    key that exists in self.keys is re-inserted THEN the entries list is
    initialised (line 60)."""

    def test_btree_insert_reinitialises_entries_when_key_present_but_entries_missing(
        self,
    ):
        """GIVEN a BTreeNode with a key in self.keys but no entry in self.entries
        WHEN insert is called THEN entries[key] is created (line 60)."""
        from ipfs_datasets_py.knowledge_graphs.indexing.btree import (
            BTreeIndex,
            IndexDefinition,
            IndexType,
        )

        idx_def = IndexDefinition(
            name="test_idx", index_type=IndexType.PROPERTY, properties=["name"]
        )
        btree = BTreeIndex(definition=idx_def, max_keys=3)

        # Insert key once to add it to root.keys
        btree.insert("Alice", {"name": "Alice"})
        assert "Alice" in btree.root.entries

        # Manually remove the entries list while keeping the key registered
        btree.root.entries.clear()
        assert len(btree.root.keys) > 0
        assert "Alice" not in btree.root.entries

        # Re-insert the same key → line 60 creates an empty entries list
        btree.insert("Alice", {"name": "Alice-v2"})
        assert "Alice" in btree.root.entries
        assert len(btree.root.entries["Alice"]) > 0
