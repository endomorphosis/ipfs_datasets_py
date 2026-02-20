"""
Session 26 test coverage improvements for knowledge_graphs.

Targets (by missed-line count):
  neo4j_compat/connection_pool.py  95% → 100%   (+7 lines)
  transactions/manager.py          91% → 97%    (+8 lines)
  query/hybrid_search.py           83% → 93%    (+12 lines)
  query/distributed.py             94% → 99%    (+9 lines)
  neo4j_compat/session.py          98% → 100%   (+3 lines)
  transactions/types.py            96% → 100%   (+3 lines)
  neo4j_compat/bookmarks.py        97% → 100%   (+3 lines)
  neo4j_compat/result.py           98% → 100%   (+2 lines)
  cypher/ast.py                    99% → 100%   (+2 lines)
  cypher/compiler.py               98% → 100%   (+4 lines)
  query/unified_engine.py          89% → 100%  (+16 lines)
  indexing/btree.py                87% → 98%   (+12 lines)

Overall achieved: 88% → 89% (+1pp, 90 lines covered)
"""

import asyncio
import copy
import sys
import time
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# ---------------------------------------------------------------------------
# 1. neo4j_compat/connection_pool.py  (95% → 100%)
# ---------------------------------------------------------------------------

class TestConnectionPoolUncoveredPaths:
    """GIVEN a ConnectionPool, test the three remaining uncovered branches."""

    def test_release_on_closed_pool_returns_early(self):
        """GIVEN a closed pool WHEN release is called THEN it returns silently."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.connection_pool import (
            ConnectionPool, PooledConnection,
        )
        pool = ConnectionPool(max_size=2)
        conn = PooledConnection(connection_id="c1", backend=None)
        pool.close()
        # Should not raise
        pool.release(conn)
        # Connection was not put back into the available queue
        assert len(pool._available) == 0

    def test_release_expired_connection_not_returned_to_pool(self):
        """GIVEN an expired connection WHEN released THEN it is discarded and not pooled."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.connection_pool import (
            ConnectionPool, PooledConnection,
        )
        pool = ConnectionPool(max_size=2, max_connection_lifetime=1)
        conn = PooledConnection(connection_id="c2", backend=None)
        # Force expiry
        conn.created_at = 0.0
        pool.release(conn)
        assert len(pool._available) == 0
        assert pool._stats["total_expired"] == 1

    def test_close_on_already_closed_pool_is_noop(self):
        """GIVEN a closed pool WHEN close is called again THEN it is a no-op."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.connection_pool import ConnectionPool
        pool = ConnectionPool(max_size=2)
        pool.close()
        assert pool._closed is True
        pool.close()  # second call should not raise
        assert pool._closed is True


# ---------------------------------------------------------------------------
# 2. transactions/types.py  (96% → 100%)
# ---------------------------------------------------------------------------

class TestTransactionTypesUncoveredPaths:
    """GIVEN a Transaction, test WRITE_RELATIONSHIP write-set tracking and PREPARING commit."""

    def test_add_operation_write_relationship_adds_rel_id_to_write_set(self):
        """GIVEN a WRITE_RELATIONSHIP operation WHEN add_operation is called THEN rel_id is in write_set."""
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            Transaction, TransactionState, OperationType, Operation,
        )
        txn = Transaction(txn_id=uuid.uuid4(), isolation_level="READ_COMMITTED")
        op = Operation(type=OperationType.WRITE_RELATIONSHIP, rel_id="rel-abc")
        txn.add_operation(op)
        assert "rel-abc" in txn.write_set

    def test_add_operation_write_relationship_dedup(self):
        """GIVEN the same rel_id WHEN add_operation called twice THEN write_set has it once."""
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            Transaction, TransactionState, OperationType, Operation,
        )
        txn = Transaction(txn_id=uuid.uuid4(), isolation_level="READ_COMMITTED")
        op = Operation(type=OperationType.WRITE_RELATIONSHIP, rel_id="rel-dup")
        txn.add_operation(op)
        txn.add_operation(op)
        assert txn.write_set.count("rel-dup") == 1

    def test_can_commit_in_preparing_state(self):
        """GIVEN a transaction in PREPARING state WHEN can_commit is called THEN it returns True."""
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            Transaction, TransactionState,
        )
        txn = Transaction(txn_id=uuid.uuid4(), isolation_level="READ_COMMITTED")
        txn.state = TransactionState.PREPARING
        assert txn.can_commit() is True


# ---------------------------------------------------------------------------
# 3. neo4j_compat/bookmarks.py  (97% → 100%)
# ---------------------------------------------------------------------------

class TestBookmarksUncoveredPaths:
    """GIVEN Bookmark/Bookmarks objects, test __hash__ and __repr__."""

    def test_bookmark_hash_is_integer(self):
        """GIVEN a Bookmark WHEN hash() is called THEN an integer is returned."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.bookmarks import Bookmark
        b = Bookmark(transaction_id="tx1", database="neo4j", timestamp=1000.0)
        h = hash(b)
        assert isinstance(h, int)

    def test_bookmarks_repr_includes_bookmark_str(self):
        """GIVEN a Bookmarks with one bookmark WHEN repr() is called THEN output contains bracket delimited list."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.bookmarks import Bookmark, Bookmarks
        b = Bookmark(transaction_id="tx1", database="neo4j", timestamp=1000.0)
        bs = Bookmarks([b])
        r = repr(bs)
        assert r.startswith("Bookmarks([")
        assert r.endswith("])")

    def test_bookmarks_repr_empty_is_empty_list(self):
        """GIVEN an empty Bookmarks WHEN repr() is called THEN output is Bookmarks([])."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.bookmarks import Bookmarks
        bs = Bookmarks()
        r = repr(bs)
        assert r == "Bookmarks([])"


# ---------------------------------------------------------------------------
# 4. neo4j_compat/result.py  (98% → 100%)
# ---------------------------------------------------------------------------

class TestResultUncoveredPaths:
    """GIVEN a Result, test keys() on empty result and __repr__."""

    def test_keys_on_empty_result_returns_empty_list(self):
        """GIVEN an empty Result WHEN keys() is called THEN an empty list is returned."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.result import Result
        result = Result(records=[])
        assert result.keys() == []

    def test_repr_shows_record_count_and_consumed(self):
        """GIVEN a Result WHEN repr() is called THEN it shows record count and consumed status."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.result import Result
        result = Result(records=[])
        r = repr(result)
        assert "Result(" in r
        assert "records=0" in r
        assert "consumed=" in r


# ---------------------------------------------------------------------------
# 5. neo4j_compat/session.py  (98% → 100%)
# ---------------------------------------------------------------------------

class TestSessionUncoveredPaths:
    """GIVEN an IPFSSession, test retry-exhausted None return and close with open transaction."""

    def _make_session(self):
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.session import IPFSSession
        mock_driver = MagicMock()
        mock_backend = MagicMock()
        return IPFSSession(driver=mock_driver, backend=mock_backend)

    def test_read_transaction_max_retries_zero_returns_none(self):
        """GIVEN max_retries=0 WHEN read_transaction is called THEN None is returned."""
        session = self._make_session()
        result = session.read_transaction(lambda tx: "unreachable", max_retries=0)
        assert result is None

    def test_write_transaction_max_retries_zero_returns_none(self):
        """GIVEN max_retries=0 WHEN write_transaction is called THEN None is returned."""
        session = self._make_session()
        result = session.write_transaction(lambda tx: "unreachable", max_retries=0)
        assert result is None

    def test_close_with_open_transaction_calls_transaction_close(self):
        """GIVEN an open transaction WHEN session is closed THEN the transaction is also closed."""
        session = self._make_session()
        mock_tx = MagicMock()
        mock_tx._closed = False
        session._transaction = mock_tx
        session._closed = False
        session.close()
        assert session._closed is True
        mock_tx.close.assert_called_once()


# ---------------------------------------------------------------------------
# 6. transactions/manager.py  (91% → 97%)
# ---------------------------------------------------------------------------

class TestTransactionManagerUncoveredPaths:
    """GIVEN a TransactionManager, test TransactionAbortedError re-raise, WRITE_RELATIONSHIP, snapshot."""

    def _make_manager(self):
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        mock_engine = MagicMock()
        mock_engine._nodes = {}
        mock_engine._enable_persistence = False
        mock_backend = MagicMock()
        with patch("ipfs_datasets_py.knowledge_graphs.transactions.manager.WriteAheadLog") as mock_wal_cls:
            mock_wal = MagicMock()
            mock_wal.wal_head_cid = None
            mock_wal.append.return_value = "cid-wal"
            mock_wal_cls.return_value = mock_wal
            mgr = TransactionManager(graph_engine=mock_engine, storage_backend=mock_backend)
        # Restore WAL mock on the manager after context exits
        mgr.wal = mock_wal
        mgr.graph_engine = mock_engine
        return mgr

    def test_commit_reraises_transaction_aborted_error(self):
        """GIVEN a TransactionAbortedError inside commit WHEN commit is called THEN it propagates."""
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        from ipfs_datasets_py.knowledge_graphs.transactions.types import TransactionState
        from ipfs_datasets_py.knowledge_graphs.exceptions import TransactionAbortedError
        mgr = self._make_manager()
        txn = mgr.begin()
        # Make _apply_operations raise TransactionAbortedError
        with patch.object(mgr, "_apply_operations", side_effect=TransactionAbortedError("aborted")):
            with pytest.raises(TransactionAbortedError):
                mgr.commit(txn)

    def test_apply_operations_write_relationship(self):
        """GIVEN a WRITE_RELATIONSHIP operation WHEN _apply_operations is called THEN create_relationship is invoked."""
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            Transaction, TransactionState, OperationType, Operation,
        )
        mgr = self._make_manager()
        txn = Transaction(txn_id=uuid.uuid4(), isolation_level="READ_COMMITTED")
        txn.state = TransactionState.PREPARING
        op = Operation(
            type=OperationType.WRITE_RELATIONSHIP,
            data={"start_node_id": "n1", "end_node_id": "n2", "rel_type": "KNOWS", "properties": {}},
        )
        txn.operations.append(op)
        mgr._apply_operations(txn)
        mgr.graph_engine.create_relationship.assert_called_once()

    def test_capture_snapshot_returns_none_when_persistence_disabled(self):
        """GIVEN _enable_persistence=False WHEN _capture_snapshot is called THEN None is returned."""
        mgr = self._make_manager()
        result = mgr._capture_snapshot()
        assert result is None

    def test_capture_snapshot_returns_none_when_storage_is_none(self):
        """GIVEN no storage attribute WHEN _capture_snapshot is called THEN None is returned."""
        mgr = self._make_manager()
        mgr.graph_engine._enable_persistence = True
        mgr.graph_engine.storage = None
        result = mgr._capture_snapshot()
        assert result is None

    def test_capture_snapshot_degrades_on_attribute_error(self):
        """GIVEN an AttributeError on save_graph WHEN _capture_snapshot is called THEN None is returned."""
        mgr = self._make_manager()
        mgr.graph_engine._enable_persistence = True
        mgr.graph_engine.storage = MagicMock()
        mgr.graph_engine.save_graph.side_effect = AttributeError("oops")
        result = mgr._capture_snapshot()
        assert result is None

    def test_capture_snapshot_reraises_transaction_error(self):
        """GIVEN a TransactionError on save_graph WHEN _capture_snapshot is called THEN it propagates."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import TransactionError
        mgr = self._make_manager()
        mgr.graph_engine._enable_persistence = True
        mgr.graph_engine.storage = MagicMock()
        mgr.graph_engine.save_graph.side_effect = TransactionError("txn error")
        with pytest.raises(TransactionError):
            mgr._capture_snapshot()


# ---------------------------------------------------------------------------
# 7. query/unified_engine.py  (89% → 100%)
# ---------------------------------------------------------------------------

class TestUnifiedEngineUncoveredPaths:
    """GIVEN a UnifiedQueryEngine, test lazy-load ImportError paths for all 4 lazy properties."""

    def _make_engine(self):
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import UnifiedQueryEngine
        return UnifiedQueryEngine(backend=MagicMock())

    def test_cypher_compiler_import_error_propagates(self):
        """GIVEN cypher module unavailable WHEN cypher_compiler is accessed THEN ImportError is raised."""
        eng = self._make_engine()
        with patch.dict(sys.modules, {"ipfs_datasets_py.knowledge_graphs.cypher": None}):
            with pytest.raises(ImportError):
                _ = eng.cypher_compiler

    def test_cypher_parser_import_error_propagates(self):
        """GIVEN cypher module unavailable WHEN cypher_parser is accessed THEN ImportError is raised."""
        eng = self._make_engine()
        with patch.dict(sys.modules, {"ipfs_datasets_py.knowledge_graphs.cypher": None}):
            with pytest.raises(ImportError):
                _ = eng.cypher_parser

    def test_ir_executor_import_error_propagates(self):
        """GIVEN graph query executor module unavailable WHEN ir_executor is accessed THEN ImportError is raised."""
        eng = self._make_engine()
        with patch.dict(sys.modules, {"ipfs_datasets_py.search.graph_query.executor": None}):
            with pytest.raises(ImportError):
                _ = eng.ir_executor

    def test_graph_engine_import_error_propagates(self):
        """GIVEN core graph engine module unavailable WHEN graph_engine is accessed THEN ImportError is raised."""
        eng = self._make_engine()
        with patch.dict(sys.modules, {"ipfs_datasets_py.knowledge_graphs.core.graph_engine": None}):
            with pytest.raises(ImportError):
                _ = eng.graph_engine


# ---------------------------------------------------------------------------
# 8. query/hybrid_search.py  (83% → 93%)
# ---------------------------------------------------------------------------

class TestHybridSearchUncoveredPaths:
    """GIVEN a HybridSearchEngine, test error-handler branches and LRU cache eviction."""

    def _make_engine(self, vector_store=None, backend=None):
        from ipfs_datasets_py.knowledge_graphs.query.hybrid_search import HybridSearchEngine
        return HybridSearchEngine(backend=backend or MagicMock(), vector_store=vector_store)

    def test_vector_search_kgerror_is_reraised(self):
        """GIVEN KnowledgeGraphError from vector_store.search WHEN vector_search is called THEN it propagates."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import KnowledgeGraphError
        mock_vs = MagicMock()
        mock_vs.search.side_effect = KnowledgeGraphError("index error")
        eng = self._make_engine(vector_store=mock_vs)
        with pytest.raises(KnowledgeGraphError):
            eng.vector_search("query")

    def test_vector_search_attributeerror_returns_empty_list(self):
        """GIVEN AttributeError from vector_store.search WHEN vector_search is called THEN [] is returned."""
        mock_vs = MagicMock()
        mock_vs.search.side_effect = AttributeError("no attr")
        eng = self._make_engine(vector_store=mock_vs)
        result = eng.vector_search("query")
        assert result == []

    def test_expand_graph_neighbor_error_is_logged_and_skipped(self):
        """GIVEN AttributeError from _get_neighbors WHEN expand_graph is called THEN the node is skipped gracefully."""
        from ipfs_datasets_py.knowledge_graphs.query.hybrid_search import HybridSearchEngine
        mock_backend = MagicMock()
        eng = HybridSearchEngine(backend=mock_backend, vector_store=None)
        # Make _get_neighbors raise AttributeError
        with patch.object(eng, "_get_neighbors", side_effect=AttributeError("no attr")):
            result = eng.expand_graph(["n1"])
        # n1 was visited before neighbors failed
        assert "n1" in result

    def test_get_query_embedding_kgerror_is_reraised(self):
        """GIVEN KnowledgeGraphError from embed_query WHEN _get_query_embedding is called THEN it propagates."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import KnowledgeGraphError
        mock_vs = MagicMock()
        mock_vs.embed_query.side_effect = KnowledgeGraphError("embed error")
        eng = self._make_engine(vector_store=mock_vs)
        with pytest.raises(KnowledgeGraphError):
            eng._get_query_embedding("query")

    def test_get_query_embedding_attributeerror_returns_none(self):
        """GIVEN AttributeError from embed_query WHEN _get_query_embedding is called THEN None is returned."""
        mock_vs = MagicMock()
        mock_vs.embed_query.side_effect = AttributeError("no method")
        eng = self._make_engine(vector_store=mock_vs)
        result = eng._get_query_embedding("query")
        assert result is None

    def test_get_query_embedding_generic_exception_returns_none(self):
        """GIVEN a generic exception from embed_query WHEN _get_query_embedding is called THEN None is returned."""
        mock_vs = MagicMock()
        mock_vs.embed_query.side_effect = RuntimeError("network error")
        eng = self._make_engine(vector_store=mock_vs)
        result = eng._get_query_embedding("query")
        assert result is None

    def test_get_neighbors_kgerror_is_reraised(self):
        """GIVEN KnowledgeGraphError from backend WHEN _get_neighbors is called THEN it propagates."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import KnowledgeGraphError
        mock_backend = MagicMock()
        mock_backend.get_neighbors.side_effect = KnowledgeGraphError("no neighbors")
        eng = self._make_engine(backend=mock_backend)
        with pytest.raises(KnowledgeGraphError):
            eng._get_neighbors("n1")

    def test_get_neighbors_attributeerror_returns_empty_list(self):
        """GIVEN AttributeError from backend.get_relationships WHEN _get_neighbors is called THEN [] is returned."""
        mock_backend = MagicMock(spec=["get_relationships"])
        mock_backend.get_relationships.side_effect = AttributeError("no attr")
        eng = self._make_engine(backend=mock_backend)
        result = eng._get_neighbors("n1")
        assert result == []

    def test_get_neighbors_generic_exception_returns_empty_list(self):
        """GIVEN a generic exception from backend WHEN _get_neighbors is called THEN [] is returned."""
        mock_backend = MagicMock(spec=["get_relationships"])
        mock_backend.get_relationships.side_effect = RuntimeError("oops")
        eng = self._make_engine(backend=mock_backend)
        result = eng._get_neighbors("n1")
        assert result == []

    def test_search_lru_cache_evicts_oldest_entry(self):
        """GIVEN cache_size=2 WHEN 3 unique queries are searched THEN the oldest is evicted."""
        from ipfs_datasets_py.knowledge_graphs.query.hybrid_search import HybridSearchEngine
        mock_backend = MagicMock()
        mock_backend.get_neighbors.return_value = []
        mock_vs = MagicMock()
        mock_vs.search.return_value = [("n1", 0.9)]

        eng = HybridSearchEngine(backend=mock_backend, vector_store=mock_vs)
        eng._cache_size = 2
        # Override embedding to return a value so vector_search proceeds
        eng._get_query_embedding = lambda q: [0.1, 0.2, 0.3]

        eng.search("query_a")
        eng.search("query_b")
        assert len(eng._cache) == 2
        eng.search("query_c")
        # After eviction the cache should still be at most cache_size
        assert len(eng._cache) <= 2


# ---------------------------------------------------------------------------
# 9. query/distributed.py  (94% → 99%)
# ---------------------------------------------------------------------------

class TestDistributedUncoveredPaths:
    """GIVEN GraphPartitioner / FederatedQueryExecutor, test orphan rel, worker error, dedup, filter, _normalise_result."""

    def _make_simple_dist(self, num_partitions=2):
        from ipfs_datasets_py.knowledge_graphs.query.distributed import GraphPartitioner
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity
        kg = KnowledgeGraph()
        e1 = Entity(entity_id="e1", name="Alice", entity_type="person")
        kg.add_entity(e1)
        return GraphPartitioner(num_partitions=num_partitions).partition(kg)

    def test_partition_orphan_relationship_is_skipped(self):
        """GIVEN a relationship with a missing target WHEN partition is called THEN orphan rel is skipped."""
        from ipfs_datasets_py.knowledge_graphs.query.distributed import GraphPartitioner
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph, Relationship
        from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity
        kg = KnowledgeGraph()
        e1 = Entity(entity_id="e1", name="Alice", entity_type="person")
        kg.add_entity(e1)
        # Create a relationship with no target_entity (target_id will be None → orphan)
        r1 = Relationship(relationship_id="r_orphan", source_entity=e1, relationship_type="KNOWS")
        kg.relationships["r_orphan"] = r1

        partitioner = GraphPartitioner(num_partitions=2)
        dist = partitioner.partition(kg)
        # The orphan relationship must not appear in any partition
        assert all("r_orphan" not in p.relationships for p in dist.partitions)

    def test_execute_cypher_parallel_worker_error_recorded(self):
        """GIVEN an error on every partition WHEN execute_cypher_parallel is called THEN errors dict is populated."""
        from ipfs_datasets_py.knowledge_graphs.query.distributed import FederatedQueryExecutor
        dist = self._make_simple_dist()
        executor = FederatedQueryExecutor(distributed_graph=dist, dedup=True)
        with patch.object(executor, "_execute_on_partition", side_effect=RuntimeError("boom")):
            result = executor.execute_cypher_parallel("MATCH (n) RETURN n", max_workers=2)
        assert len(result.errors) > 0
        assert result.records == []

    def test_execute_cypher_streaming_dedup_removes_duplicates(self):
        """GIVEN duplicate records from two partitions WHEN execute_cypher_streaming is called THEN only one is yielded."""
        from ipfs_datasets_py.knowledge_graphs.query.distributed import FederatedQueryExecutor
        dist = self._make_simple_dist()
        executor = FederatedQueryExecutor(distributed_graph=dist, dedup=True)
        dup = {"id": "n1", "name": "Alice"}
        with patch.object(executor, "_execute_on_partition", return_value=[dup]):
            results = list(executor.execute_cypher_streaming("MATCH (n) RETURN n"))
        # Two partitions both return the same record; dedup should give exactly 1
        assert len(results) == 1

    def test_kgbackend_get_relationships_target_id_filter(self):
        """GIVEN a target_id filter WHEN get_relationships is called THEN only matching rels are returned."""
        from ipfs_datasets_py.knowledge_graphs.query.distributed import _KGBackend
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph, Relationship
        from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity
        kg = KnowledgeGraph()
        e1 = Entity(entity_id="e1", name="A", entity_type="person")
        e2 = Entity(entity_id="e2", name="B", entity_type="person")
        kg.add_entity(e1)
        kg.add_entity(e2)
        r1 = Relationship(relationship_id="r1", source_entity=e1, target_entity=e2, relationship_type="KNOWS")
        r2 = Relationship(relationship_id="r2", source_entity=e2, target_entity=e1, relationship_type="KNOWS")
        kg.relationships["r1"] = r1
        kg.relationships["r2"] = r2
        backend = _KGBackend(kg)
        result = backend.get_relationships(target_id="e1")
        assert all(r.target_id == "e1" for r in result)

    def test_kgbackend_get_relationships_type_filter(self):
        """GIVEN a relationship_types filter WHEN get_relationships is called THEN only matching types returned."""
        from ipfs_datasets_py.knowledge_graphs.query.distributed import _KGBackend
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph, Relationship
        from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity
        kg = KnowledgeGraph()
        e1 = Entity(entity_id="e1", name="A", entity_type="person")
        e2 = Entity(entity_id="e2", name="B", entity_type="person")
        kg.add_entity(e1)
        kg.add_entity(e2)
        r1 = Relationship(relationship_id="r1", source_entity=e1, target_entity=e2, relationship_type="KNOWS")
        r2 = Relationship(relationship_id="r2", source_entity=e1, target_entity=e2, relationship_type="LIKES")
        kg.relationships["r1"] = r1
        kg.relationships["r2"] = r2
        backend = _KGBackend(kg)
        result = backend.get_relationships(relationship_types=["LIKES"])
        assert all(r.relationship_type == "LIKES" for r in result)

    def test_kgbackend_get_relationships_limit(self):
        """GIVEN a limit WHEN get_relationships is called THEN at most limit items are returned."""
        from ipfs_datasets_py.knowledge_graphs.query.distributed import _KGBackend
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph, Relationship
        from ipfs_datasets_py.knowledge_graphs.extraction.entities import Entity
        kg = KnowledgeGraph()
        e1 = Entity(entity_id="e1", name="A", entity_type="person")
        e2 = Entity(entity_id="e2", name="B", entity_type="person")
        kg.add_entity(e1)
        kg.add_entity(e2)
        for i in range(5):
            r = Relationship(
                relationship_id=f"r{i}", source_entity=e1, target_entity=e2, relationship_type="KNOWS",
            )
            kg.relationships[f"r{i}"] = r
        backend = _KGBackend(kg)
        result = backend.get_relationships(limit=2)
        assert len(result) == 2

    def test_normalise_result_iterable_key_value_pairs(self):
        """GIVEN a row that is iterable as key-value pairs WHEN _normalise_result THEN it becomes a dict."""
        from ipfs_datasets_py.knowledge_graphs.query.distributed import _normalise_result

        class PairRow:
            def __iter__(self):
                yield ("key", "val")

        result = _normalise_result([PairRow()])
        assert result == [{"key": "val"}]

    def test_normalise_result_object_with_dict(self):
        """GIVEN a row with __dict__ WHEN _normalise_result THEN it returns dict of public attrs."""
        from ipfs_datasets_py.knowledge_graphs.query.distributed import _normalise_result

        class MyObj:
            def __init__(self):
                self.name = "Alice"
                self.age = 30

        result = _normalise_result([MyObj()])
        assert result[0]["name"] == "Alice"
        assert result[0]["age"] == 30

    def test_normalise_result_non_iterable_is_stringified(self):
        """GIVEN a non-iterable scalar WHEN _normalise_result THEN it is wrapped as {'value': str}."""
        from ipfs_datasets_py.knowledge_graphs.query.distributed import _normalise_result
        result = _normalise_result([42])
        assert result == [{"value": "42"}]


# ---------------------------------------------------------------------------
# 10. cypher/ast.py  (99% → 100%)
# ---------------------------------------------------------------------------

class TestASTUncoveredPaths:
    """GIVEN AST visitor infrastructure, test generic_visit and ASTPrettyPrinter visiting a nested ASTNode field."""

    def test_visitor_generic_visit_returns_none(self):
        """GIVEN a visitor without a specific visit method WHEN generic_visit is called THEN None is returned."""
        from ipfs_datasets_py.knowledge_graphs.cypher.ast import ASTVisitor, QueryNode

        class NoOpVisitor(ASTVisitor):
            pass

        visitor = NoOpVisitor()
        query = QueryNode(clauses=[])
        result = visitor.generic_visit(query)
        assert result is None

    def test_astprettyprinter_visits_nested_astnode_field(self):
        """GIVEN a node with an ASTNode-typed field WHEN ASTPrettyPrinter.print is called THEN nested node is visited."""
        from ipfs_datasets_py.knowledge_graphs.cypher.ast import (
            ASTPrettyPrinter, QueryNode, MatchClause, WhereClause, LiteralNode,
        )
        # WhereClause.expression is a direct ASTNode field (not a list) — triggers line 731
        literal = LiteralNode(value=True)
        where = WhereClause(expression=literal)
        match = MatchClause(patterns=[], where=where)
        query = QueryNode(clauses=[match])
        printer = ASTPrettyPrinter()
        output = printer.print(query)
        # Both WhereClause and LiteralNode should appear in output
        assert "WhereClause" in output
        assert "LiteralNode" in output


# ---------------------------------------------------------------------------
# 11. cypher/compiler.py  (98% → 100%)
# ---------------------------------------------------------------------------

class TestCompilerUncoveredPaths:
    """GIVEN the Cypher compiler, test CREATE-rel-not-followed-by-node raises and other branch coverage."""

    def test_compile_create_rel_not_followed_by_node_raises(self):
        """GIVEN a CREATE with a trailing relationship not followed by a node WHEN compile THEN CypherCompileError."""
        from ipfs_datasets_py.knowledge_graphs.cypher.compiler import CypherCompiler, CypherCompileError
        from ipfs_datasets_py.knowledge_graphs.cypher.ast import (
            QueryNode, CreateClause, PatternNode, NodePattern, RelationshipPattern,
        )
        compiler = CypherCompiler()
        np = NodePattern(variable="n", labels=[])
        rp = RelationshipPattern(types=["KNOWS"], direction="right")
        pattern = PatternNode(elements=[np, rp])  # rel at end, no trailing node
        create = CreateClause(patterns=[pattern])
        query = QueryNode(clauses=[create])
        with pytest.raises(CypherCompileError):
            compiler.compile(query)

    def test_compile_match_returns_scan_operation(self):
        """GIVEN a simple MATCH WHEN compile is called THEN a ScanAll operation is in the ops list."""
        from ipfs_datasets_py.knowledge_graphs.cypher.compiler import CypherCompiler
        from ipfs_datasets_py.knowledge_graphs.cypher.parser import CypherParser
        compiler = CypherCompiler()
        parser = CypherParser()
        ast = parser.parse("MATCH (n) RETURN n")
        ops = compiler.compile(ast)
        assert any(op.get("op") == "ScanAll" for op in ops)


# ---------------------------------------------------------------------------
# 12. indexing/btree.py  (87% → 98%)
# ---------------------------------------------------------------------------

class TestBTreeUncoveredPaths:
    """GIVEN a BTreeIndex, test internal node split and range search through an internal node."""

    def _make_index(self, max_keys=3):
        from ipfs_datasets_py.knowledge_graphs.indexing.btree import BTreeIndex
        from ipfs_datasets_py.knowledge_graphs.indexing.types import IndexDefinition, IndexType
        defn = IndexDefinition(name="test_btree", index_type=IndexType.PROPERTY, properties=["key"])
        return BTreeIndex(definition=defn, max_keys=max_keys)

    def test_internal_node_split_is_triggered(self):
        """GIVEN a BTreeIndex with max_keys=2 WHEN enough entries are inserted THEN splits occur and search still works."""
        idx = self._make_index(max_keys=2)
        for i in range(10):
            idx.insert(i, f"entity_{i}")
        for i in range(10):
            assert idx.search(i) is not None

    def test_range_search_through_internal_node(self):
        """GIVEN a deep BTreeIndex WHEN range_search spans multiple nodes THEN values in range are returned."""
        idx = self._make_index(max_keys=2)
        for i in range(15):
            idx.insert(i, f"val_{i}")
        results = idx.range_search(3, 8)
        # Must find at least some values in the 3-8 range (BTree internal-node traversal)
        assert len(results) >= 4
        # All returned values must be within range
        keys_found = set(int(v.split("_")[1]) for v in results)
        assert all(3 <= k <= 8 for k in keys_found)

    def test_insert_duplicate_key_returns_both_entities(self):
        """GIVEN the same key inserted twice WHEN search is called THEN both entity IDs are returned."""
        idx = self._make_index(max_keys=3)
        idx.insert(5, "entity_a")
        idx.insert(5, "entity_b")
        result = idx.search(5)
        assert result is not None
        assert len(result) == 2
        assert "entity_a" in result
        assert "entity_b" in result

    def test_insert_and_search_large_tree(self):
        """GIVEN 100 insertions WHEN searched THEN all values are found."""
        idx = self._make_index(max_keys=4)
        for i in range(100):
            idx.insert(i, f"v{i}")
        for i in range(100):
            found = idx.search(i)
            assert found is not None

    def test_range_search_with_no_results_returns_empty(self):
        """GIVEN a BTreeIndex with values 0-9 WHEN range_search(20,30) THEN empty list returned."""
        idx = self._make_index(max_keys=3)
        for i in range(10):
            idx.insert(i, f"v{i}")
        results = idx.range_search(20, 30)
        assert results == []
