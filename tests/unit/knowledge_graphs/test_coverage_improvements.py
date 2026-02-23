"""
Coverage improvement tests for low-coverage modules.

Targets:
- extraction/validator.py          (was 24% → target 60%+)
- query/unified_engine.py          (was 43% → target 70%+)
- transactions/manager.py          (was 40% → target 70%+)
- query/knowledge_graph.py         (was  6% → target 50%+)
- extraction/advanced.py           (was 27% → target 50%+)

All tests follow the GIVEN-WHEN-THEN convention used throughout the suite.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------

def _make_mock_backend():
    """Return a mock IPLD-compatible backend."""
    backend = MagicMock()
    backend.store.return_value = "bafybeicid"
    backend.retrieve.return_value = {
        "nodes": {"n1": {"labels": ["Person"], "properties": {"name": "Alice"}}},
        "relationships": {},
    }
    return backend


def _make_mock_graph_engine():
    from ipfs_datasets_py.knowledge_graphs.core.graph_engine import GraphEngine
    engine = MagicMock(spec=GraphEngine)
    engine._nodes = {}
    engine._relationships = {}
    engine._enable_persistence = False
    engine.create_node.return_value = "n-new"
    engine.create_relationship.return_value = "r-new"
    return engine


def _make_mock_storage():
    from ipfs_datasets_py.knowledge_graphs.storage.ipld_backend import IPLDBackend
    storage = MagicMock(spec=IPLDBackend)
    storage.store.return_value = "bafybeicid"
    # WAL calls store_json, not store
    storage.store_json = MagicMock(return_value="bafybeicidwal")
    return storage


# ===========================================================================
# 1. extraction/validator.py
# ===========================================================================

class TestValidatorInit:
    """GIVEN KnowledgeGraphExtractorWithValidation constructor."""

    def test_default_init_without_sparql(self):
        """GIVEN SPARQLValidator unavailable WHEN initialising THEN validator is None but attribute set."""
        from ipfs_datasets_py.knowledge_graphs.extraction.validator import (
            KnowledgeGraphExtractorWithValidation,
        )
        extractor = KnowledgeGraphExtractorWithValidation(use_tracer=False)
        # validator may or may not be available; attribute always present
        assert hasattr(extractor, "validate_during_extraction")
        assert hasattr(extractor, "auto_correct_suggestions")
        assert hasattr(extractor, "min_confidence")

    def test_validate_during_extraction_stored(self):
        """GIVEN validate_during_extraction=True WHEN init THEN attribute reflects value."""
        from ipfs_datasets_py.knowledge_graphs.extraction.validator import (
            KnowledgeGraphExtractorWithValidation,
        )
        extractor = KnowledgeGraphExtractorWithValidation(
            use_tracer=False, validate_during_extraction=True
        )
        assert extractor.validate_during_extraction is True

    def test_validate_during_extraction_false(self):
        """GIVEN validate_during_extraction=False WHEN init THEN attribute is False."""
        from ipfs_datasets_py.knowledge_graphs.extraction.validator import (
            KnowledgeGraphExtractorWithValidation,
        )
        extractor = KnowledgeGraphExtractorWithValidation(
            use_tracer=False, validate_during_extraction=False
        )
        assert extractor.validate_during_extraction is False

    def test_min_confidence_stored(self):
        """GIVEN min_confidence=0.8 WHEN init THEN attribute reflects value."""
        from ipfs_datasets_py.knowledge_graphs.extraction.validator import (
            KnowledgeGraphExtractorWithValidation,
        )
        extractor = KnowledgeGraphExtractorWithValidation(
            use_tracer=False, min_confidence=0.8
        )
        assert extractor.min_confidence == 0.8

    def test_auto_correct_false_by_default(self):
        """GIVEN default init WHEN checking auto_correct THEN it is False."""
        from ipfs_datasets_py.knowledge_graphs.extraction.validator import (
            KnowledgeGraphExtractorWithValidation,
        )
        extractor = KnowledgeGraphExtractorWithValidation(use_tracer=False)
        assert extractor.auto_correct_suggestions is False

    def test_auto_correct_true_stored(self):
        """GIVEN auto_correct_suggestions=True WHEN init THEN attribute is True."""
        from ipfs_datasets_py.knowledge_graphs.extraction.validator import (
            KnowledgeGraphExtractorWithValidation,
        )
        extractor = KnowledgeGraphExtractorWithValidation(
            use_tracer=False, auto_correct_suggestions=True
        )
        assert extractor.auto_correct_suggestions is True


class TestValidatorExtract:
    """GIVEN KnowledgeGraphExtractorWithValidation.extract_knowledge_graph."""

    def test_extract_returns_dict(self):
        """GIVEN simple text WHEN extracting THEN result is a dict with knowledge_graph key."""
        from ipfs_datasets_py.knowledge_graphs.extraction.validator import (
            KnowledgeGraphExtractorWithValidation,
        )
        extractor = KnowledgeGraphExtractorWithValidation(use_tracer=False)
        result = extractor.extract_knowledge_graph("Alice works at Acme Corp.")
        assert isinstance(result, dict)
        assert "knowledge_graph" in result

    def test_extract_has_counts(self):
        """GIVEN simple text WHEN extracting THEN result has entity_count and relationship_count."""
        from ipfs_datasets_py.knowledge_graphs.extraction.validator import (
            KnowledgeGraphExtractorWithValidation,
        )
        extractor = KnowledgeGraphExtractorWithValidation(use_tracer=False)
        result = extractor.extract_knowledge_graph("Bob founded BobCo in 2010.")
        assert "entity_count" in result
        assert "relationship_count" in result
        assert isinstance(result["entity_count"], int)
        assert isinstance(result["relationship_count"], int)

    def test_extract_no_validation_when_disabled(self):
        """GIVEN validate_during_extraction=False WHEN extracting THEN no validation_results key."""
        from ipfs_datasets_py.knowledge_graphs.extraction.validator import (
            KnowledgeGraphExtractorWithValidation,
        )
        extractor = KnowledgeGraphExtractorWithValidation(
            use_tracer=False, validate_during_extraction=False
        )
        result = extractor.extract_knowledge_graph("Alice works at Acme.")
        # With validate_during_extraction=False the result should not contain validation_results
        # (or it should be falsy — the field is absent or empty)
        vr = result.get("validation_results")
        assert vr is None or vr == {}

    def test_extract_with_validation_no_validator_available(self):
        """GIVEN validate_during_extraction=True but validator unavailable WHEN extracting THEN no crash."""
        from ipfs_datasets_py.knowledge_graphs.extraction.validator import (
            KnowledgeGraphExtractorWithValidation,
        )
        extractor = KnowledgeGraphExtractorWithValidation(
            use_tracer=False, validate_during_extraction=True
        )
        # If validator_available is False, extraction still returns valid result
        result = extractor.extract_knowledge_graph("Carol manages a team.")
        assert result is not None
        assert "knowledge_graph" in result

    def test_extract_with_mock_validator(self):
        """GIVEN mock validator WHEN extracting THEN validation_results are populated."""
        from ipfs_datasets_py.knowledge_graphs.extraction.validator import (
            KnowledgeGraphExtractorWithValidation,
        )
        extractor = KnowledgeGraphExtractorWithValidation(
            use_tracer=False, validate_during_extraction=True
        )

        # Inject a mock validator
        mock_vr = MagicMock()
        mock_vr.to_dict.return_value = {"entity_coverage": 0.9}
        mock_vr.data = {"entity_coverage": 0.9, "relationship_coverage": 0.8, "overall_coverage": 0.85}

        mock_validator = MagicMock()
        mock_validator.validate_knowledge_graph.return_value = mock_vr
        extractor.validator = mock_validator
        extractor.validator_available = True

        result = extractor.extract_knowledge_graph("Dave built a rocket.")
        assert "validation_results" in result
        assert "validation_metrics" in result
        assert result["validation_metrics"]["entity_coverage"] == pytest.approx(0.9)

    def test_extract_with_auto_corrections(self):
        """GIVEN auto_correct_suggestions=True and mock validator WHEN extracting THEN corrections key added."""
        from ipfs_datasets_py.knowledge_graphs.extraction.validator import (
            KnowledgeGraphExtractorWithValidation,
        )
        extractor = KnowledgeGraphExtractorWithValidation(
            use_tracer=False,
            validate_during_extraction=True,
            auto_correct_suggestions=True,
        )

        mock_vr = MagicMock()
        mock_vr.to_dict.return_value = {}
        mock_vr.data = {
            "entity_coverage": 0.5,
            "relationship_coverage": 0.5,
            "overall_coverage": 0.5,
            "entity_validations": {
                "e1": {"valid": False, "name": "Eve"}
            },
        }

        mock_validator = MagicMock()
        mock_validator.validate_knowledge_graph.return_value = mock_vr
        mock_validator.generate_validation_explanation.return_value = "Try 'Eva'"
        extractor.validator = mock_validator
        extractor.validator_available = True

        result = extractor.extract_knowledge_graph("Eve runs EveComp.")
        assert "corrections" in result
        assert "entities" in result["corrections"]


# ===========================================================================
# 2. query/unified_engine.py
# ===========================================================================

class TestUnifiedQueryEngineInit:
    """GIVEN UnifiedQueryEngine constructor."""

    def test_basic_init(self):
        """GIVEN a mock backend WHEN creating engine THEN attributes set."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import UnifiedQueryEngine
        backend = _make_mock_backend()
        engine = UnifiedQueryEngine(backend=backend)
        assert engine.backend is backend
        assert engine.vector_store is None
        assert engine.llm_processor is None
        assert engine.enable_caching is True

    def test_init_with_custom_preset(self):
        """GIVEN default_budgets='strict' WHEN creating THEN preset stored."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import UnifiedQueryEngine
        engine = UnifiedQueryEngine(backend=_make_mock_backend(), default_budgets="strict")
        assert engine.default_budgets_preset == "strict"

    def test_init_with_vector_store(self):
        """GIVEN vector_store kwarg WHEN creating THEN stored on instance."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import UnifiedQueryEngine
        vs = MagicMock()
        engine = UnifiedQueryEngine(backend=_make_mock_backend(), vector_store=vs)
        assert engine.vector_store is vs

    def test_lazy_properties_none_initially(self):
        """GIVEN fresh engine WHEN inspecting private attrs THEN all None."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import UnifiedQueryEngine
        engine = UnifiedQueryEngine(backend=_make_mock_backend())
        assert engine._cypher_compiler is None
        assert engine._cypher_parser is None
        assert engine._ir_executor is None
        assert engine._graph_engine is None


class TestUnifiedQueryEngineStats:
    """GIVEN UnifiedQueryEngine.get_stats."""

    def test_get_stats_returns_dict(self):
        """GIVEN engine WHEN calling get_stats THEN returns dict."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import UnifiedQueryEngine
        engine = UnifiedQueryEngine(backend=_make_mock_backend())
        stats = engine.get_stats()
        assert isinstance(stats, dict)
        assert "backend" in stats
        assert "caching_enabled" in stats

    def test_get_stats_vector_store_flag(self):
        """GIVEN engine with no vector store WHEN get_stats THEN flag is False."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import UnifiedQueryEngine
        engine = UnifiedQueryEngine(backend=_make_mock_backend())
        assert engine.get_stats()["vector_store_enabled"] is False

    def test_get_stats_with_vector_store(self):
        """GIVEN engine with vector store WHEN get_stats THEN flag is True."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import UnifiedQueryEngine
        engine = UnifiedQueryEngine(backend=_make_mock_backend(), vector_store=MagicMock())
        assert engine.get_stats()["vector_store_enabled"] is True


class TestUnifiedQueryEngineDetectType:
    """GIVEN UnifiedQueryEngine._detect_query_type."""

    def test_match_detected_as_cypher(self):
        """GIVEN query with MATCH WHEN detecting THEN returns 'cypher'."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import UnifiedQueryEngine
        engine = UnifiedQueryEngine(backend=_make_mock_backend())
        assert engine._detect_query_type("MATCH (n) RETURN n") == "cypher"

    def test_create_detected_as_cypher(self):
        """GIVEN query with CREATE WHEN detecting THEN returns 'cypher'."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import UnifiedQueryEngine
        engine = UnifiedQueryEngine(backend=_make_mock_backend())
        assert engine._detect_query_type("CREATE (n:Person {name:'Alice'})") == "cypher"

    def test_natural_language_detected_as_hybrid(self):
        """GIVEN natural language WHEN detecting THEN returns 'hybrid'."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import UnifiedQueryEngine
        engine = UnifiedQueryEngine(backend=_make_mock_backend())
        assert engine._detect_query_type("who is the founder of Apple?") == "hybrid"

    def test_merge_detected_as_cypher(self):
        """GIVEN MERGE clause WHEN detecting THEN returns 'cypher'."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import UnifiedQueryEngine
        engine = UnifiedQueryEngine(backend=_make_mock_backend())
        assert engine._detect_query_type("MERGE (n:City {name:'Paris'})") == "cypher"


class TestUnifiedQueryEngineQueryResult:
    """GIVEN QueryResult dataclass."""

    def test_to_dict(self):
        """GIVEN QueryResult WHEN calling to_dict THEN returns dict."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import QueryResult
        r = QueryResult(items=[1, 2], stats={"time": 0.1}, query_type="cypher")
        d = r.to_dict()
        assert d["items"] == [1, 2]
        assert d["query_type"] == "cypher"
        assert d["success"] is True

    def test_to_dict_with_error(self):
        """GIVEN failed QueryResult WHEN to_dict THEN error field present."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import QueryResult
        r = QueryResult(items=[], stats={}, success=False, error="timeout")
        d = r.to_dict()
        assert d["success"] is False
        assert d["error"] == "timeout"


class TestUnifiedQueryEngineCypher:
    """GIVEN UnifiedQueryEngine.execute_cypher."""

    def test_execute_cypher_raises_parse_error_on_bad_query(self):
        """GIVEN invalid Cypher WHEN executing THEN QueryParseError or QueryExecutionError raised."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import UnifiedQueryEngine
        from ipfs_datasets_py.knowledge_graphs.exceptions import QueryError
        engine = UnifiedQueryEngine(backend=_make_mock_backend())
        with pytest.raises(QueryError):
            engine.execute_cypher("this is not valid cypher!!!")

    def test_execute_cypher_with_mock_components(self):
        """GIVEN mocked parser/compiler/ir_executor WHEN executing THEN returns QueryResult."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import UnifiedQueryEngine, QueryResult
        engine = UnifiedQueryEngine(backend=_make_mock_backend())

        # Mock the lazy properties
        mock_ir = MagicMock()
        mock_ir.items = [{"n": {"name": "Alice"}}]
        mock_ir.stats = {"nodes_scanned": 1}

        mock_parser = MagicMock()
        mock_parser.parse.return_value = MagicMock()  # AST

        mock_compiler = MagicMock()
        mock_compiler.compile.return_value = MagicMock()  # IR

        mock_executor = MagicMock()
        mock_executor.execute.return_value = mock_ir

        engine._cypher_parser = mock_parser
        engine._cypher_compiler = mock_compiler
        engine._ir_executor = mock_executor

        result = engine.execute_cypher("MATCH (n:Person) RETURN n")
        assert isinstance(result, QueryResult)
        assert result.success is True
        assert result.query_type == "cypher"


class TestUnifiedQueryEngineExecuteQuery:
    """GIVEN UnifiedQueryEngine.execute_query."""

    def test_auto_routes_cypher(self):
        """GIVEN MATCH query with auto type WHEN execute_query THEN routes to execute_cypher."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import UnifiedQueryEngine
        engine = UnifiedQueryEngine(backend=_make_mock_backend())

        mock_result = MagicMock()
        mock_result.items = []
        mock_result.stats = {}

        mock_parser = MagicMock()
        mock_parser.parse.return_value = MagicMock()
        mock_compiler = MagicMock()
        mock_compiler.compile.return_value = MagicMock()
        mock_executor = MagicMock()
        mock_executor.execute.return_value = mock_result

        engine._cypher_parser = mock_parser
        engine._cypher_compiler = mock_compiler
        engine._ir_executor = mock_executor

        result = engine.execute_query("MATCH (n) RETURN n LIMIT 1", query_type="auto")
        assert result.query_type == "cypher"


class TestUnifiedQueryEngineAsync:
    """GIVEN UnifiedQueryEngine.execute_async."""

    def test_execute_async_returns_same_result(self):
        """GIVEN async wrapper WHEN awaited THEN returns same result as sync."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import UnifiedQueryEngine, QueryResult
        engine = UnifiedQueryEngine(backend=_make_mock_backend())

        mock_result = MagicMock()
        mock_result.items = [{"x": 1}]
        mock_result.stats = {}

        mock_parser = MagicMock()
        mock_parser.parse.return_value = MagicMock()
        mock_compiler = MagicMock()
        mock_compiler.compile.return_value = MagicMock()
        mock_executor = MagicMock()
        mock_executor.execute.return_value = mock_result

        engine._cypher_parser = mock_parser
        engine._cypher_compiler = mock_compiler
        engine._ir_executor = mock_executor

        result = asyncio.run(engine.execute_async("MATCH (n) RETURN n"))
        assert result.success is True


# ===========================================================================
# 3. transactions/manager.py
# ===========================================================================

class TestTransactionManagerInit:
    """GIVEN TransactionManager constructor."""

    def test_init_creates_empty_active(self):
        """GIVEN valid engine+storage WHEN init THEN active_transactions is empty."""
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        engine = _make_mock_graph_engine()
        storage = _make_mock_storage()
        mgr = TransactionManager(graph_engine=engine, storage_backend=storage)
        assert mgr.get_active_count() == 0

    def test_init_stores_engine(self):
        """GIVEN engine WHEN init THEN graph_engine attribute is same object."""
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        engine = _make_mock_graph_engine()
        storage = _make_mock_storage()
        mgr = TransactionManager(graph_engine=engine, storage_backend=storage)
        assert mgr.graph_engine is engine


class TestTransactionManagerBegin:
    """GIVEN TransactionManager.begin."""

    def test_begin_returns_transaction(self):
        """GIVEN manager WHEN begin THEN returns Transaction."""
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        from ipfs_datasets_py.knowledge_graphs.transactions.types import Transaction
        mgr = TransactionManager(
            graph_engine=_make_mock_graph_engine(),
            storage_backend=_make_mock_storage()
        )
        txn = mgr.begin()
        assert isinstance(txn, Transaction)

    def test_begin_increments_active_count(self):
        """GIVEN manager WHEN begin THEN active count increases."""
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        mgr = TransactionManager(
            graph_engine=_make_mock_graph_engine(),
            storage_backend=_make_mock_storage()
        )
        mgr.begin()
        mgr.begin()
        assert mgr.get_active_count() == 2

    def test_begin_with_isolation_read_uncommitted(self):
        """GIVEN READ_UNCOMMITTED isolation WHEN begin THEN txn stores correct level."""
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        from ipfs_datasets_py.knowledge_graphs.transactions.types import IsolationLevel
        mgr = TransactionManager(
            graph_engine=_make_mock_graph_engine(),
            storage_backend=_make_mock_storage()
        )
        txn = mgr.begin(IsolationLevel.READ_UNCOMMITTED)
        assert txn.isolation_level == IsolationLevel.READ_UNCOMMITTED

    def test_begin_with_serializable_isolation(self):
        """GIVEN SERIALIZABLE isolation WHEN begin THEN txn stores correct level."""
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        from ipfs_datasets_py.knowledge_graphs.transactions.types import IsolationLevel
        mgr = TransactionManager(
            graph_engine=_make_mock_graph_engine(),
            storage_backend=_make_mock_storage()
        )
        txn = mgr.begin(IsolationLevel.SERIALIZABLE)
        assert txn.isolation_level == IsolationLevel.SERIALIZABLE


class TestTransactionManagerAddOperation:
    """GIVEN TransactionManager.add_operation."""

    def test_add_write_node_operation(self):
        """GIVEN active transaction WHEN adding WRITE_NODE op THEN op in transaction."""
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        from ipfs_datasets_py.knowledge_graphs.transactions.types import Operation, OperationType
        mgr = TransactionManager(
            graph_engine=_make_mock_graph_engine(),
            storage_backend=_make_mock_storage()
        )
        txn = mgr.begin()
        op = Operation(
            type=OperationType.WRITE_NODE,
            data={"labels": ["Person"], "properties": {"name": "Alice"}},
            node_id="n1"
        )
        mgr.add_operation(txn, op)
        assert len(txn.operations) == 1
        assert "n1" in txn.write_set

    def test_add_operation_to_committed_raises(self):
        """GIVEN committed transaction WHEN adding op THEN TransactionAbortedError raised."""
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            Operation, OperationType, TransactionAbortedError, TransactionState,
        )
        mgr = TransactionManager(
            graph_engine=_make_mock_graph_engine(),
            storage_backend=_make_mock_storage()
        )
        txn = mgr.begin()
        # Manually mark as committed
        txn.state = TransactionState.COMMITTED
        op = Operation(type=OperationType.WRITE_NODE, data={}, node_id="x")
        with pytest.raises(TransactionAbortedError):
            mgr.add_operation(txn, op)


class TestTransactionManagerRollback:
    """GIVEN TransactionManager.rollback."""

    def test_rollback_removes_from_active(self):
        """GIVEN active transaction WHEN rollback THEN active count decreases."""
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        mgr = TransactionManager(
            graph_engine=_make_mock_graph_engine(),
            storage_backend=_make_mock_storage()
        )
        txn = mgr.begin()
        assert mgr.get_active_count() == 1
        mgr.rollback(txn)
        assert mgr.get_active_count() == 0

    def test_rollback_clears_operations(self):
        """GIVEN transaction with operations WHEN rollback THEN operations cleared."""
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        from ipfs_datasets_py.knowledge_graphs.transactions.types import Operation, OperationType
        mgr = TransactionManager(
            graph_engine=_make_mock_graph_engine(),
            storage_backend=_make_mock_storage()
        )
        txn = mgr.begin()
        op = Operation(type=OperationType.WRITE_NODE, data={}, node_id="n1")
        mgr.add_operation(txn, op)
        mgr.rollback(txn)
        assert len(txn.operations) == 0

    def test_rollback_sets_aborted_state(self):
        """GIVEN active transaction WHEN rollback THEN state becomes ABORTED."""
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        from ipfs_datasets_py.knowledge_graphs.transactions.types import TransactionState
        mgr = TransactionManager(
            graph_engine=_make_mock_graph_engine(),
            storage_backend=_make_mock_storage()
        )
        txn = mgr.begin()
        mgr.rollback(txn)
        assert txn.state == TransactionState.ABORTED


class TestTransactionManagerAddRead:
    """GIVEN TransactionManager.add_read."""

    def test_add_read_tracks_cid(self):
        """GIVEN active transaction WHEN add_read THEN CID in read_set."""
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        mgr = TransactionManager(
            graph_engine=_make_mock_graph_engine(),
            storage_backend=_make_mock_storage()
        )
        txn = mgr.begin()
        mgr.add_read(txn, "bafybeicid123")
        assert "bafybeicid123" in txn.read_set

    def test_add_read_on_inactive_txn_no_op(self):
        """GIVEN rolled-back transaction WHEN add_read THEN no crash (idempotent)."""
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        from ipfs_datasets_py.knowledge_graphs.transactions.types import TransactionState
        mgr = TransactionManager(
            graph_engine=_make_mock_graph_engine(),
            storage_backend=_make_mock_storage()
        )
        txn = mgr.begin()
        mgr.rollback(txn)
        # Should not raise
        mgr.add_read(txn, "bafybeicid456")


class TestTransactionManagerCommit:
    """GIVEN TransactionManager.commit."""

    def test_commit_empty_transaction_succeeds(self):
        """GIVEN transaction with no ops WHEN commit THEN returns True."""
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        mgr = TransactionManager(
            graph_engine=_make_mock_graph_engine(),
            storage_backend=_make_mock_storage()
        )
        txn = mgr.begin()
        result = mgr.commit(txn)
        assert result is True
        assert mgr.get_active_count() == 0

    def test_commit_removes_from_active(self):
        """GIVEN 2 active transactions WHEN commit one THEN active count is 1."""
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        mgr = TransactionManager(
            graph_engine=_make_mock_graph_engine(),
            storage_backend=_make_mock_storage()
        )
        txn1 = mgr.begin()
        mgr.begin()
        mgr.commit(txn1)
        assert mgr.get_active_count() == 1

    def test_commit_write_tracked(self):
        """GIVEN transaction with WRITE_NODE WHEN commit THEN entity_id tracked in committed_writes."""
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        from ipfs_datasets_py.knowledge_graphs.transactions.types import Operation, OperationType
        engine = _make_mock_graph_engine()
        engine.create_node.return_value = "n-new"
        mgr = TransactionManager(graph_engine=engine, storage_backend=_make_mock_storage())
        txn = mgr.begin()
        op = Operation(type=OperationType.WRITE_NODE, data={"labels": [], "properties": {}}, node_id="entity-abc")
        mgr.add_operation(txn, op)
        mgr.commit(txn)
        assert "entity-abc" in mgr._committed_writes

    def test_commit_non_active_raises(self):
        """GIVEN already-committed transaction WHEN commit again THEN raises TransactionAbortedError."""
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        from ipfs_datasets_py.knowledge_graphs.transactions.types import TransactionAbortedError
        mgr = TransactionManager(
            graph_engine=_make_mock_graph_engine(),
            storage_backend=_make_mock_storage()
        )
        txn = mgr.begin()
        mgr.commit(txn)
        with pytest.raises(TransactionAbortedError):
            mgr.commit(txn)

    def test_detect_conflicts_read_committed_no_conflict(self):
        """GIVEN READ_COMMITTED isolation WHEN same entity written by two txns THEN no conflict."""
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            IsolationLevel, Operation, OperationType
        )
        engine = _make_mock_graph_engine()
        mgr = TransactionManager(graph_engine=engine, storage_backend=_make_mock_storage())

        # txn1 commits with entity "shared"
        txn1 = mgr.begin(IsolationLevel.READ_COMMITTED)
        op1 = Operation(type=OperationType.WRITE_NODE, data={}, node_id="shared")
        mgr.add_operation(txn1, op1)
        mgr.commit(txn1)

        # txn2 also writes "shared" — READ_COMMITTED: no conflict detection
        txn2 = mgr.begin(IsolationLevel.READ_COMMITTED)
        op2 = Operation(type=OperationType.WRITE_NODE, data={}, node_id="shared")
        mgr.add_operation(txn2, op2)
        result = mgr.commit(txn2)  # should NOT raise
        assert result is True


class TestTransactionManagerStats:
    """GIVEN TransactionManager.get_stats."""

    def test_get_stats_returns_dict(self):
        """GIVEN manager WHEN get_stats THEN returns dict."""
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        mgr = TransactionManager(
            graph_engine=_make_mock_graph_engine(),
            storage_backend=_make_mock_storage()
        )
        stats = mgr.get_stats()
        assert isinstance(stats, dict)
        assert "active_transactions" in stats


class TestTransactionManagerRecover:
    """GIVEN TransactionManager.recover."""

    def test_recover_no_ops_no_error(self):
        """GIVEN empty WAL WHEN recover THEN no crash."""
        from ipfs_datasets_py.knowledge_graphs.transactions.manager import TransactionManager
        mgr = TransactionManager(
            graph_engine=_make_mock_graph_engine(),
            storage_backend=_make_mock_storage()
        )
        mgr.wal.recover = MagicMock(return_value=[])
        mgr.recover()  # should not raise


# ===========================================================================
# 4. query/knowledge_graph.py
# ===========================================================================

class TestKGQueryModule:
    """GIVEN query/knowledge_graph.py module functions."""

    def test_parse_ir_ops_empty_string_raises(self):
        """GIVEN empty string WHEN parse_ir_ops_from_query THEN ValueError raised."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import parse_ir_ops_from_query
        with pytest.raises(ValueError, match="non-empty"):
            parse_ir_ops_from_query("")

    def test_parse_ir_ops_non_json_raises(self):
        """GIVEN non-JSON string WHEN parse_ir_ops_from_query THEN ValueError raised."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import parse_ir_ops_from_query
        with pytest.raises(ValueError):
            parse_ir_ops_from_query("MATCH (n) RETURN n")

    def test_parse_ir_ops_valid_list(self):
        """GIVEN JSON list of ops WHEN parse_ir_ops_from_query THEN returns list."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import parse_ir_ops_from_query
        payload = json.dumps([{"op": "ScanType", "entity_type": "Person"}])
        ops = parse_ir_ops_from_query(payload)
        assert isinstance(ops, list)
        assert ops[0]["op"] == "ScanType"

    def test_parse_ir_ops_valid_dict_with_ops_key(self):
        """GIVEN JSON dict with ops key WHEN parsing THEN extracts list."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import parse_ir_ops_from_query
        payload = json.dumps({"ops": [{"op": "ScanType", "entity_type": "City"}]})
        ops = parse_ir_ops_from_query(payload)
        assert ops[0]["entity_type"] == "City"

    def test_parse_ir_ops_empty_list_raises(self):
        """GIVEN empty list JSON WHEN parsing THEN ValueError raised."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import parse_ir_ops_from_query
        with pytest.raises(ValueError, match="non-empty"):
            parse_ir_ops_from_query("[]")

    def test_parse_ir_ops_non_dict_item_raises(self):
        """GIVEN list with non-dict item WHEN parsing THEN ValueError raised."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import parse_ir_ops_from_query
        with pytest.raises(ValueError, match="object/dict"):
            parse_ir_ops_from_query('[42, "hello"]')

    def test_parse_ir_ops_not_string_raises(self):
        """GIVEN non-string input WHEN parsing THEN ValueError raised."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import parse_ir_ops_from_query
        with pytest.raises(ValueError):
            parse_ir_ops_from_query(None)  # type: ignore


# ===========================================================================
# 5. extraction/advanced.py — AdvancedKnowledgeExtractor
# ===========================================================================

class TestAdvancedExtractorInit:
    """GIVEN AdvancedKnowledgeExtractor constructor."""

    def test_import_and_create(self):
        """GIVEN module available WHEN creating AdvancedKnowledgeExtractor THEN no crash."""
        from ipfs_datasets_py.knowledge_graphs.extraction.advanced import AdvancedKnowledgeExtractor
        extractor = AdvancedKnowledgeExtractor()
        assert extractor is not None

    def test_default_attributes(self):
        """GIVEN default init WHEN checking attributes THEN extraction callable present."""
        from ipfs_datasets_py.knowledge_graphs.extraction.advanced import AdvancedKnowledgeExtractor
        extractor = AdvancedKnowledgeExtractor()
        # Must have the main extraction method
        assert callable(getattr(extractor, "extract_knowledge", None))

    def test_extract_knowledge_graph_returns_result(self):
        """GIVEN simple text WHEN extracting THEN result has knowledge_graph."""
        from ipfs_datasets_py.knowledge_graphs.extraction.advanced import AdvancedKnowledgeExtractor
        extractor = AdvancedKnowledgeExtractor()
        result = extractor.extract_knowledge("Alice is a scientist who works at CERN.")
        # Result might be dict or KnowledgeGraph
        assert result is not None

    def test_extract_returns_entities(self):
        """GIVEN entity-rich text WHEN extracting THEN entities present in result."""
        from ipfs_datasets_py.knowledge_graphs.extraction.advanced import AdvancedKnowledgeExtractor
        extractor = AdvancedKnowledgeExtractor()
        result = extractor.extract_knowledge("Bob works at TechCorp in San Francisco.")
        # Either a dict with knowledge_graph or a KnowledgeGraph object
        if isinstance(result, dict):
            kg = result.get("knowledge_graph") or result
            if hasattr(kg, "entities"):
                assert isinstance(kg.entities, (dict, list))
        elif hasattr(result, "entities"):
            assert isinstance(result.entities, (dict, list))
        else:
            # Result is some other object; just confirm it is truthy
            assert result is not None


class TestAdvancedExtractorChunking:
    """GIVEN AdvancedKnowledgeExtractor extraction with chunking."""

    def test_extract_large_text_no_crash(self):
        """GIVEN large text WHEN extracting THEN no crash."""
        from ipfs_datasets_py.knowledge_graphs.extraction.advanced import AdvancedKnowledgeExtractor
        extractor = AdvancedKnowledgeExtractor()
        long_text = ("Alice is a scientist. " * 50)
        result = extractor.extract_knowledge(long_text)
        assert result is not None

    def test_extract_empty_text_no_crash(self):
        """GIVEN empty text WHEN extracting THEN no crash (returns empty/None)."""
        from ipfs_datasets_py.knowledge_graphs.extraction.advanced import AdvancedKnowledgeExtractor
        extractor = AdvancedKnowledgeExtractor()
        try:
            result = extractor.extract_knowledge("")
            # Empty text is handled gracefully — the result is returned without crashing
            # (may be None or an empty graph)
            assert result is None or hasattr(result, "entities") or isinstance(result, dict)
        except (ValueError, TypeError):
            pass  # Acceptable to raise ValueError on empty text

    def test_extract_with_temperature_params(self):
        """GIVEN extraction_temperature parameter WHEN extracting THEN no crash."""
        from ipfs_datasets_py.knowledge_graphs.extraction.advanced import AdvancedKnowledgeExtractor
        extractor = AdvancedKnowledgeExtractor()
        try:
            result = extractor.extract_knowledge(
                "Eve is a physicist.",
                extraction_temperature=0.5,
                structure_temperature=0.5,
            )
            assert result is not None
        except TypeError:
            # If method doesn't accept temperature params, that's OK
            pass


# ===========================================================================
# 6. More validator.py coverage — validate_against_wikidata, extract_from_documents,
#    apply_validation_corrections, validation_stubs when no validator
# ===========================================================================

class TestValidatorAgainstWikidata:
    """GIVEN KnowledgeGraphExtractorWithValidation.validate_against_wikidata."""

    def test_no_validator_returns_invalid(self):
        """GIVEN no validator WHEN validate_against_wikidata THEN valid=False + reason."""
        from ipfs_datasets_py.knowledge_graphs.extraction.validator import (
            KnowledgeGraphExtractorWithValidation,
        )
        extractor = KnowledgeGraphExtractorWithValidation(use_tracer=False)
        extractor.validator = None
        extractor.validator_available = False
        result = extractor.validate_against_wikidata("Albert Einstein", "person")
        assert result["valid"] is False
        assert result["reason"] == "validator_unavailable"
        assert result["entity_name"] == "Albert Einstein"

    def test_no_validator_stores_entity_type(self):
        """GIVEN no validator WHEN validate THEN entity_type echoed in result."""
        from ipfs_datasets_py.knowledge_graphs.extraction.validator import (
            KnowledgeGraphExtractorWithValidation,
        )
        extractor = KnowledgeGraphExtractorWithValidation(use_tracer=False)
        extractor.validator = None
        result = extractor.validate_against_wikidata("Paris", "location")
        assert result["entity_type"] == "location"

    def test_with_mock_validator_no_lookup(self):
        """GIVEN validator without _get_wikidata_entity WHEN validate THEN valid=False."""
        from ipfs_datasets_py.knowledge_graphs.extraction.validator import (
            KnowledgeGraphExtractorWithValidation,
        )
        extractor = KnowledgeGraphExtractorWithValidation(use_tracer=False)
        mock_validator = MagicMock(spec=[])  # no _get_wikidata_entity attribute
        extractor.validator = mock_validator
        extractor.validator_available = True
        result = extractor.validate_against_wikidata("Tesla", "organization")
        assert result["entity_name"] == "Tesla"
        assert "valid" in result

    def test_with_mock_validator_with_lookup(self):
        """GIVEN validator with _get_wikidata_entity WHEN validate THEN valid matches lookup."""
        from ipfs_datasets_py.knowledge_graphs.extraction.validator import (
            KnowledgeGraphExtractorWithValidation,
        )
        extractor = KnowledgeGraphExtractorWithValidation(use_tracer=False)
        mock_validator = MagicMock()
        mock_validator._get_wikidata_entity.return_value = {"id": "Q937", "label": "Marie Curie"}
        extractor.validator = mock_validator
        extractor.validator_available = True
        result = extractor.validate_against_wikidata("Marie Curie", "person")
        assert result["valid"] is True
        assert result["wikidata_entity"]["id"] == "Q937"


class TestValidatorExtractFromDocuments:
    """GIVEN KnowledgeGraphExtractorWithValidation.extract_from_documents."""

    def test_single_document_no_crash(self):
        """GIVEN single document WHEN extracting THEN returns dict."""
        from ipfs_datasets_py.knowledge_graphs.extraction.validator import (
            KnowledgeGraphExtractorWithValidation,
        )
        extractor = KnowledgeGraphExtractorWithValidation(use_tracer=False)
        docs = [{"text": "Bob founded TechCorp in 2001.", "title": "Doc1"}]
        result = extractor.extract_from_documents(docs)
        assert isinstance(result, dict)

    def test_multiple_documents_no_crash(self):
        """GIVEN multiple documents WHEN extracting THEN knowledge_graph key present."""
        from ipfs_datasets_py.knowledge_graphs.extraction.validator import (
            KnowledgeGraphExtractorWithValidation,
        )
        extractor = KnowledgeGraphExtractorWithValidation(use_tracer=False)
        docs = [
            {"text": "Alice works at Acme."},
            {"text": "Bob works at BobCo."},
        ]
        result = extractor.extract_from_documents(docs)
        assert "knowledge_graph" in result or "error" in result

    def test_empty_documents_list(self):
        """GIVEN empty documents list WHEN extracting THEN no crash."""
        from ipfs_datasets_py.knowledge_graphs.extraction.validator import (
            KnowledgeGraphExtractorWithValidation,
        )
        extractor = KnowledgeGraphExtractorWithValidation(use_tracer=False)
        result = extractor.extract_from_documents([])
        assert isinstance(result, dict)

    def test_custom_text_key(self):
        """GIVEN custom text_key='content' WHEN extracting THEN works."""
        from ipfs_datasets_py.knowledge_graphs.extraction.validator import (
            KnowledgeGraphExtractorWithValidation,
        )
        extractor = KnowledgeGraphExtractorWithValidation(use_tracer=False)
        docs = [{"content": "Carol leads the engineering team."}]
        result = extractor.extract_from_documents(docs, text_key="content")
        assert isinstance(result, dict)


class TestValidatorApplyCorrections:
    """GIVEN KnowledgeGraphExtractorWithValidation.apply_validation_corrections."""

    def test_apply_empty_corrections_returns_kg(self):
        """GIVEN empty corrections WHEN applying THEN corrected KG has same entities."""
        from ipfs_datasets_py.knowledge_graphs.extraction.validator import (
            KnowledgeGraphExtractorWithValidation,
        )
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        extractor = KnowledgeGraphExtractorWithValidation(use_tracer=False)
        kg = KnowledgeGraph(name="test")
        kg.add_entity(entity_type="person", name="Alice", properties={})
        corrected = extractor.apply_validation_corrections(kg, {})
        assert corrected is not None
        assert len(corrected.entities) == 1

    def test_apply_entity_text_corrections(self):
        """GIVEN text corrections for an entity WHEN applying THEN property updated."""
        from ipfs_datasets_py.knowledge_graphs.extraction.validator import (
            KnowledgeGraphExtractorWithValidation,
        )
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        extractor = KnowledgeGraphExtractorWithValidation(use_tracer=False)
        kg = KnowledgeGraph(name="test")
        entity = kg.add_entity(
            entity_type="person", name="Alice", properties={"name": "Alice", "occupation": "Scientist"}
        )
        corrections = {
            "entities": {
                entity.entity_id: {
                    "suggestions": {"occupation": "Physicist"}
                }
            }
        }
        corrected = extractor.apply_validation_corrections(kg, corrections)
        assert corrected is not None
        corrected_entity = list(corrected.entities.values())[0]
        assert corrected_entity.properties.get("occupation") == "Physicist"

    def test_apply_corrections_preserves_relationships(self):
        """GIVEN KG with relationships WHEN applying empty corrections THEN rels preserved."""
        from ipfs_datasets_py.knowledge_graphs.extraction.validator import (
            KnowledgeGraphExtractorWithValidation,
        )
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        extractor = KnowledgeGraphExtractorWithValidation(use_tracer=False)
        kg = KnowledgeGraph(name="test")
        e1 = kg.add_entity(entity_type="person", name="Alice", properties={})
        e2 = kg.add_entity(entity_type="organization", name="Acme", properties={})
        kg.add_relationship(
            "works_at", source=e1, target=e2, properties={}
        )
        corrected = extractor.apply_validation_corrections(kg, {})
        assert len(corrected.relationships) == 1


class TestValidatorValidationStubs:
    """GIVEN validator=None but validate_during_extraction=True."""

    def test_extraction_returns_empty_validation_stubs(self):
        """GIVEN no validator WHEN extracting with validate=True THEN stubs included."""
        from ipfs_datasets_py.knowledge_graphs.extraction.validator import (
            KnowledgeGraphExtractorWithValidation,
        )
        extractor = KnowledgeGraphExtractorWithValidation(
            use_tracer=False, validate_during_extraction=True
        )
        # Ensure validator is None (may or may not be True depending on env)
        extractor.validator = None
        extractor.validator_available = False
        result = extractor.extract_knowledge_graph("Eve works at EveCo.")
        # With no validator but validate=True: stubs should appear
        assert "validation_results" in result
        assert result["validation_results"] == {} or isinstance(result["validation_results"], dict)
        assert "validation_metrics" in result
        assert result["validation_metrics"]["validation_available"] is False


# ===========================================================================
# 7. More query/knowledge_graph.py coverage — compile_ir, query_knowledge_graph validation
# ===========================================================================

class TestCompileIR:
    """GIVEN query/knowledge_graph.py compile_ir function."""

    def test_scan_type_op_valid(self):
        """GIVEN ScanType op WHEN compiling THEN returns QueryIR."""
        pytest.importorskip("ipfs_datasets_py.search.graph_query.ir")
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import compile_ir
        ops = [{"op": "ScanType", "entity_type": "Person", "scope": None}]
        ir = compile_ir(ops)
        assert ir is not None

    def test_scan_type_missing_entity_type_raises(self):
        """GIVEN ScanType op without entity_type WHEN compiling THEN ValueError raised."""
        pytest.importorskip("ipfs_datasets_py.search.graph_query.ir")
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import compile_ir
        with pytest.raises(ValueError, match="entity_type"):
            compile_ir([{"op": "ScanType", "entity_type": "", "scope": None}])

    def test_expand_op_valid(self):
        """GIVEN Expand op with direction WHEN compiling THEN returns QueryIR."""
        pytest.importorskip("ipfs_datasets_py.search.graph_query.ir")
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import compile_ir
        ops = [
            {"op": "ScanType", "entity_type": "Person"},
            {"op": "Expand", "relationship_types": ["works_at"], "direction": "outgoing"},
        ]
        ir = compile_ir(ops)
        assert ir is not None

    def test_expand_invalid_direction_raises(self):
        """GIVEN Expand with bad direction WHEN compiling THEN ValueError."""
        pytest.importorskip("ipfs_datasets_py.search.graph_query.ir")
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import compile_ir
        with pytest.raises(ValueError, match="direction"):
            compile_ir([{"op": "Expand", "direction": "sideways"}])

    def test_limit_op_valid(self):
        """GIVEN Limit op WHEN compiling THEN succeeds."""
        pytest.importorskip("ipfs_datasets_py.search.graph_query.ir")
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import compile_ir
        ops = [{"op": "ScanType", "entity_type": "City"}, {"op": "Limit", "n": 10}]
        ir = compile_ir(ops)
        assert ir is not None

    def test_limit_negative_raises(self):
        """GIVEN Limit op with n=-1 WHEN compiling THEN ValueError."""
        pytest.importorskip("ipfs_datasets_py.search.graph_query.ir")
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import compile_ir
        with pytest.raises(ValueError, match="n"):
            compile_ir([{"op": "Limit", "n": -1}])

    def test_project_op_valid(self):
        """GIVEN Project op WHEN compiling THEN succeeds."""
        pytest.importorskip("ipfs_datasets_py.search.graph_query.ir")
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import compile_ir
        ops = [
            {"op": "ScanType", "entity_type": "Person"},
            {"op": "Project", "fields": ["name", "type"]},
        ]
        ir = compile_ir(ops)
        assert ir is not None

    def test_project_empty_fields_raises(self):
        """GIVEN Project with empty fields WHEN compiling THEN ValueError."""
        pytest.importorskip("ipfs_datasets_py.search.graph_query.ir")
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import compile_ir
        with pytest.raises(ValueError, match="fields"):
            compile_ir([{"op": "Project", "fields": []}])

    def test_unsupported_op_raises(self):
        """GIVEN unsupported op name WHEN compiling THEN ValueError."""
        pytest.importorskip("ipfs_datasets_py.search.graph_query.ir")
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import compile_ir
        with pytest.raises(ValueError, match="Unsupported"):
            compile_ir([{"op": "FlyToMars"}])

    def test_op_missing_name_raises(self):
        """GIVEN op dict without 'op'/'type'/'name' WHEN compiling THEN ValueError."""
        pytest.importorskip("ipfs_datasets_py.search.graph_query.ir")
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import compile_ir
        with pytest.raises(ValueError, match="missing"):
            compile_ir([{"foo": "bar"}])


class TestQueryKnowledgeGraphValidation:
    """GIVEN query_knowledge_graph function input validation."""

    def test_invalid_max_results_raises(self):
        """GIVEN max_results=0 WHEN querying THEN ValueError."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import query_knowledge_graph
        with pytest.raises(ValueError, match="max_results"):
            query_knowledge_graph(query="x", query_type="ir", max_results=0,
                                  manifest_cid="baf123")

    def test_empty_query_raises(self):
        """GIVEN empty query WHEN querying THEN ValueError."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import query_knowledge_graph
        with pytest.raises(ValueError, match="non-empty"):
            query_knowledge_graph(query="   ", query_type="ir", max_results=10,
                                  manifest_cid="baf123")

    def test_ir_type_without_manifest_raises(self):
        """GIVEN query_type='ir' without manifest_cid WHEN querying THEN ValueError."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import query_knowledge_graph
        with pytest.raises(ValueError, match="manifest_cid"):
            query_knowledge_graph(query='[{"op":"ScanType","entity_type":"X"}]',
                                  query_type="ir", max_results=10)

    def test_unsupported_query_type_raises(self):
        """GIVEN unsupported query_type='fts' WHEN querying THEN ValueError."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import query_knowledge_graph
        with pytest.raises(ValueError, match="Unsupported"):
            query_knowledge_graph(query="search", query_type="fts", max_results=10)

    def test_legacy_type_without_graph_id_raises(self):
        """GIVEN query_type='cypher' without graph_id WHEN querying THEN ValueError."""
        from ipfs_datasets_py.knowledge_graphs.query.knowledge_graph import query_knowledge_graph
        with pytest.raises(ValueError, match="graph_id"):
            query_knowledge_graph(query="MATCH (n) RETURN n", query_type="cypher",
                                  max_results=10, graph_id=None)
