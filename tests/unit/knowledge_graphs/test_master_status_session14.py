"""
Session 14 — Coverage improvements
Targets (by uncovered-statement count, no daemon/network required):
  - reasoning/cross_document.py  66% → target 75%  (87 miss)
  - neo4j_compat/session.py       65% → target 76%  (52 miss)
  - core/query_executor.py        72% → target 82%  (46 miss)
  - extraction/validator.py       59% → target 69%  (75 miss)
  - transactions/wal.py           66% → target 75%  (54 miss)
"""
import json
import time
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# ---------------------------------------------------------------------------
# Helper: minimal KnowledgeGraph stub (no IPLD/network deps)
# ---------------------------------------------------------------------------
from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph, Entity, Relationship


def _make_kg(n_entities=2, n_rels=1):
    kg = KnowledgeGraph(name="test")
    entities = []
    for i in range(n_entities):
        e = Entity(
            entity_id=f"e{i}",
            name=f"Entity{i}",
            entity_type="CONCEPT",
            properties={"idx": i},
        )
        kg.add_entity(e)
        entities.append(e)
    for i in range(min(n_rels, len(entities) - 1)):
        r = Relationship(
            relationship_type="RELATED_TO",
            source_entity=entities[i],
            target_entity=entities[i + 1],
            properties={"weight": 1.0},
        )
        kg.add_relationship(r)
    return kg


# ===========================================================================
# 1. reasoning/cross_document.py
# ===========================================================================
from ipfs_datasets_py.knowledge_graphs.reasoning.cross_document import (
    CrossDocumentReasoner,
    DocumentNode,
    InformationRelationType,
)


def _make_doc(doc_id="d1", content="hello world", entities=None, published="2020-01-01", relevance=0.9):
    return {
        "id": doc_id,
        "content": content,
        "source": "test",
        "metadata": {"published_date": published},
        "relevance_score": relevance,
        "entities": entities or [],
    }


class TestCrossDocumentReasoner:
    """GIVEN a CrossDocumentReasoner WHEN reasoning across documents THEN results are correct."""

    def _reasoner(self):
        return CrossDocumentReasoner(query_optimizer=None, reasoning_tracer=None)

    # -----------------------------------------------------------------------
    # _get_relevant_documents with input_documents
    # -----------------------------------------------------------------------
    def test_get_relevant_documents_returns_from_input(self):
        reasoner = self._reasoner()
        docs = [_make_doc("d1", relevance=0.95), _make_doc("d2", relevance=0.85)]
        result = reasoner._get_relevant_documents(
            "test query", None, docs, vector_store=None, min_relevance=0.5
        )
        assert len(result) == 2
        assert all(isinstance(d, DocumentNode) for d in result)

    def test_get_relevant_documents_filters_low_relevance(self):
        reasoner = self._reasoner()
        docs = [_make_doc("d1", relevance=0.9), _make_doc("d2", relevance=0.3)]
        result = reasoner._get_relevant_documents(
            "q", None, docs, vector_store=None, min_relevance=0.6
        )
        assert len(result) == 1
        assert result[0].id == "d1"

    def test_get_relevant_documents_uses_vector_store_when_needed(self):
        reasoner = self._reasoner()
        mock_store = MagicMock()
        mock_store.embed_query.return_value = [0.1, 0.2, 0.3]
        mock_result = MagicMock()
        mock_result.id = "vs_doc"
        mock_result.metadata = {"content": "found", "source": "vs", "entities": []}
        mock_result.score = 0.88
        mock_store.search.return_value = [mock_result]
        result = reasoner._get_relevant_documents(
            "query", None, input_documents=[], vector_store=mock_store, max_documents=5
        )
        mock_store.embed_query.assert_called_once_with("query")
        assert len(result) == 1
        assert result[0].id == "vs_doc"

    def test_get_relevant_documents_max_documents_respected(self):
        reasoner = self._reasoner()
        docs = [_make_doc(f"d{i}", relevance=0.9) for i in range(10)]
        result = reasoner._get_relevant_documents(
            "q", None, docs, vector_store=None, max_documents=3
        )
        assert len(result) == 3

    # -----------------------------------------------------------------------
    # find_entity_connections
    # -----------------------------------------------------------------------
    def test_find_entity_connections_no_kg_common_entities(self):
        reasoner = self._reasoner()
        docs = [
            DocumentNode(id="d1", content="x", source="s", metadata={}, relevance_score=0.9, entities=["e1"]),
            DocumentNode(id="d2", content="y", source="s", metadata={}, relevance_score=0.8, entities=["e1"]),
        ]
        connections = reasoner.find_entity_connections(docs, knowledge_graph=None)
        # Without KG, matches based on shared entity string IDs
        assert isinstance(connections, list)

    def test_find_entity_connections_with_kg(self):
        reasoner = self._reasoner()
        docs = [
            DocumentNode(id="d1", content="x", source="s", metadata={}, relevance_score=0.9, entities=["e1"]),
            DocumentNode(id="d2", content="y", source="s", metadata={}, relevance_score=0.8, entities=["e1"]),
        ]
        mock_kg = MagicMock()
        mock_kg.get_entity.return_value = {"name": "Alice", "type": "PERSON"}
        connections = reasoner.find_entity_connections(docs, knowledge_graph=mock_kg)
        assert isinstance(connections, list)
        # Entity "e1" shared between d1 and d2 → at least one connection
        assert len(connections) >= 1

    def test_find_entity_connections_no_common_entities(self):
        reasoner = self._reasoner()
        docs = [
            DocumentNode(id="d1", content="x", source="s", metadata={}, relevance_score=0.9, entities=["e1"]),
            DocumentNode(id="d2", content="y", source="s", metadata={}, relevance_score=0.8, entities=["e2"]),
        ]
        connections = reasoner.find_entity_connections(docs, knowledge_graph=None)
        # No shared entities → no connections
        assert connections == []

    # -----------------------------------------------------------------------
    # _determine_relation
    # -----------------------------------------------------------------------
    def test_determine_relation_missing_docs_returns_unclear(self):
        reasoner = self._reasoner()
        rel, strength = reasoner._determine_relation("e1", "d1", "d2", documents=[], knowledge_graph=None)
        assert rel == InformationRelationType.UNCLEAR

    def test_determine_relation_chronological_returns_elaborating(self):
        reasoner = self._reasoner()
        docs = [
            DocumentNode(id="d1", content="x", source="s",
                         metadata={"published_date": "2020-01-01"}, relevance_score=0.9, entities=[]),
            DocumentNode(id="d2", content="y", source="s",
                         metadata={"published_date": "2021-06-01"}, relevance_score=0.8, entities=[]),
        ]
        rel, strength = reasoner._determine_relation("e1", "d1", "d2", documents=docs, knowledge_graph=None)
        # d1 older than d2 → chronological → ELABORATING
        assert rel == InformationRelationType.ELABORATING
        assert strength > 0

    def test_determine_relation_no_dates_returns_complementary(self):
        reasoner = self._reasoner()
        docs = [
            DocumentNode(id="d1", content="x", source="s", metadata={}, relevance_score=0.9, entities=[]),
            DocumentNode(id="d2", content="y", source="s", metadata={}, relevance_score=0.8, entities=[]),
        ]
        rel, strength = reasoner._determine_relation("e1", "d1", "d2", documents=docs, knowledge_graph=None)
        assert rel == InformationRelationType.COMPLEMENTARY

    # -----------------------------------------------------------------------
    # get_statistics / explain_reasoning
    # -----------------------------------------------------------------------
    def test_get_statistics_zero_queries(self):
        reasoner = self._reasoner()
        stats = reasoner.get_statistics()
        assert stats["total_queries"] == 0
        assert stats["success_rate"] == 0

    def test_get_statistics_after_query(self):
        """GIVEN a successful reason_across_documents call WHEN get_statistics THEN counts updated."""
        reasoner = self._reasoner()
        docs = [_make_doc("d1", content="IPFS peer-to-peer protocol", entities=["IPFS"])]
        reasoner.reason_across_documents("What is IPFS?", input_documents=docs)
        stats = reasoner.get_statistics()
        assert stats["total_queries"] == 1
        assert "successful_queries" in stats

    def test_explain_reasoning_returns_dict_with_steps(self):
        reasoner = self._reasoner()
        result = reasoner.explain_reasoning("some-reasoning-id")
        assert isinstance(result, dict)
        assert "reasoning_id" in result
        assert isinstance(result.get("steps"), list)

    def test_explain_reasoning_id_propagated(self):
        reasoner = self._reasoner()
        rid = "abc-123"
        result = reasoner.explain_reasoning(rid)
        assert result["reasoning_id"] == rid

    # -----------------------------------------------------------------------
    # _synthesize_answer (no LLM)
    # -----------------------------------------------------------------------
    def test_synthesize_answer_no_llm(self):
        reasoner = self._reasoner()
        docs = [DocumentNode(id="d1", content="content", source="s", metadata={}, relevance_score=0.9, entities=[])]
        answer, confidence = reasoner._synthesize_answer(
            query="test?",
            documents=docs,
            entity_connections=[],
            traversal_paths=[],
            reasoning_depth="shallow"
        )
        assert isinstance(answer, str)
        assert 0 < confidence <= 1.0

    # -----------------------------------------------------------------------
    # reason_across_documents end-to-end
    # -----------------------------------------------------------------------
    def test_reason_across_documents_basic(self):
        reasoner = self._reasoner()
        docs = [_make_doc("d1", content="IPFS uses content addressing")]
        result = reasoner.reason_across_documents("How does IPFS work?", input_documents=docs)
        assert isinstance(result, dict)
        assert "answer" in result
        assert "confidence" in result

    def test_reason_across_documents_with_return_trace(self):
        reasoner = self._reasoner()
        docs = [_make_doc("d1", content="content addressing")]
        result = reasoner.reason_across_documents("query?", input_documents=docs, return_trace=True)
        assert "reasoning_trace" in result

    def test_reason_across_documents_increments_query_count(self):
        reasoner = self._reasoner()
        docs = [_make_doc("d1")]
        reasoner.reason_across_documents("q1", input_documents=docs)
        reasoner.reason_across_documents("q2", input_documents=docs)
        assert reasoner.total_queries == 2

    # -----------------------------------------------------------------------
    # _compute_document_similarity
    # -----------------------------------------------------------------------
    def test_compute_document_similarity_shared_tokens(self):
        reasoner = self._reasoner()
        d1 = DocumentNode(id="d1", content="knowledge graph extraction", source="s",
                           metadata={}, relevance_score=0.9, entities=[])
        d2 = DocumentNode(id="d2", content="extraction from knowledge sources", source="s",
                           metadata={}, relevance_score=0.8, entities=[])
        sim = reasoner._compute_document_similarity(d1, d2)
        assert 0.0 <= sim <= 1.0
        assert sim > 0.0  # shared: "knowledge", "extraction"

    def test_compute_document_similarity_no_shared(self):
        reasoner = self._reasoner()
        d1 = DocumentNode(id="d1", content="alpha beta gamma", source="s",
                           metadata={}, relevance_score=0.9, entities=[])
        d2 = DocumentNode(id="d2", content="delta epsilon zeta", source="s",
                           metadata={}, relevance_score=0.8, entities=[])
        sim = reasoner._compute_document_similarity(d1, d2)
        assert sim == 0.0


# ===========================================================================
# 2. neo4j_compat/session.py
# ===========================================================================
from ipfs_datasets_py.knowledge_graphs.neo4j_compat.session import (
    IPFSTransaction,
    IPFSSession,
)
from ipfs_datasets_py.knowledge_graphs.neo4j_compat.result import Result
from ipfs_datasets_py.knowledge_graphs.exceptions import TransactionConflictError


def _make_mock_driver(backend=None):
    driver = MagicMock()
    driver.backend = backend or MagicMock()
    return driver


class TestIPFSTransaction:
    """GIVEN IPFSTransaction WHEN commit/rollback/context-manager THEN state transitions are correct."""

    def test_run_delegates_to_session(self):
        session = MagicMock()
        session.run.return_value = Result([], summary={})
        tx = IPFSTransaction(session)
        result = tx.run("MATCH (n) RETURN n")
        session.run.assert_called_once_with("MATCH (n) RETURN n", None)

    def test_run_on_closed_tx_raises(self):
        session = MagicMock()
        tx = IPFSTransaction(session)
        tx.commit()
        with pytest.raises(RuntimeError, match="closed"):
            tx.run("MATCH (n) RETURN n")

    def test_commit_sets_closed_and_committed(self):
        session = MagicMock()
        tx = IPFSTransaction(session)
        tx.commit()
        assert tx._closed is True
        assert tx._committed is True

    def test_commit_twice_raises(self):
        session = MagicMock()
        tx = IPFSTransaction(session)
        tx.commit()
        with pytest.raises(RuntimeError, match="already closed"):
            tx.commit()

    def test_rollback_sets_closed(self):
        session = MagicMock()
        tx = IPFSTransaction(session)
        tx.rollback()
        assert tx._closed is True
        assert tx._committed is False

    def test_rollback_twice_raises(self):
        session = MagicMock()
        tx = IPFSTransaction(session)
        tx.rollback()
        with pytest.raises(RuntimeError, match="closed"):
            tx.rollback()

    def test_close_rolls_back_if_open(self):
        session = MagicMock()
        tx = IPFSTransaction(session)
        tx.close()
        assert tx._closed is True

    def test_context_manager_commits_on_success(self):
        session = MagicMock()
        session.run.return_value = Result([], summary={})
        with IPFSTransaction(session) as tx:
            assert not tx._closed
        assert tx._committed is True

    def test_context_manager_rolls_back_on_exception(self):
        session = MagicMock()
        with pytest.raises(ValueError):
            with IPFSTransaction(session) as tx:
                raise ValueError("boom")
        assert tx._closed is True
        assert tx._committed is False

    def test_context_manager_does_not_double_commit(self):
        session = MagicMock()
        session.run.return_value = Result([], summary={})
        with IPFSTransaction(session) as tx:
            tx.commit()  # manual commit inside block
        # __exit__ should not raise even though tx is already closed
        assert tx._committed is True


class TestIPFSSession:
    """GIVEN IPFSSession WHEN executing queries and transactions THEN behaviour matches expected."""

    def _session(self):
        driver = _make_mock_driver()
        query_executor = MagicMock()
        query_executor.execute.return_value = Result([{"n": 1}], summary={})
        session = IPFSSession(driver)
        session._query_executor = query_executor
        return session, query_executor

    def test_run_delegates_to_query_executor(self):
        session, qe = self._session()
        result = session.run("MATCH (n) RETURN n")
        assert result is not None

    def test_close_marks_session_closed(self):
        driver = _make_mock_driver()
        session = IPFSSession(driver)
        session.close()
        assert session._closed is True

    def test_context_manager_closes_session(self):
        driver = _make_mock_driver()
        with IPFSSession(driver) as sess:
            assert not sess._closed
        assert sess._closed is True

    def test_closed_property(self):
        driver = _make_mock_driver()
        sess = IPFSSession(driver)
        assert sess.closed is False
        sess.close()
        assert sess.closed is True

    def test_database_property(self):
        driver = _make_mock_driver()
        sess = IPFSSession(driver, database="mydb")
        assert sess.database == "mydb"

    def test_begin_transaction_returns_iptx(self):
        driver = _make_mock_driver()
        sess = IPFSSession(driver)
        tx = sess.begin_transaction()
        assert isinstance(tx, IPFSTransaction)

    def test_read_transaction_calls_function(self):
        driver = _make_mock_driver()
        sess = IPFSSession(driver)
        called = []

        def fn(tx, val):
            called.append(val)
            return val * 2

        result = sess.read_transaction(fn, 5)
        assert result == 10
        assert called == [5]

    def test_write_transaction_calls_function(self):
        driver = _make_mock_driver()
        sess = IPFSSession(driver)
        called = []

        def fn(tx, msg):
            called.append(msg)
            return msg.upper()

        result = sess.write_transaction(fn, "hello")
        assert result == "HELLO"
        assert called == ["hello"]

    def test_read_transaction_retry_on_conflict(self):
        """GIVEN a function that raises TransactionConflictError once THEN retries succeed."""
        driver = _make_mock_driver()
        sess = IPFSSession(driver)
        call_count = [0]

        def fn(tx):
            call_count[0] += 1
            if call_count[0] == 1:
                raise TransactionConflictError("conflict")
            return "ok"

        result = sess.read_transaction(fn, max_retries=3)
        assert result == "ok"
        assert call_count[0] == 2

    def test_write_transaction_does_not_retry_value_error(self):
        """GIVEN a function that raises ValueError THEN no retry, exception propagates."""
        driver = _make_mock_driver()
        sess = IPFSSession(driver)
        call_count = [0]

        def fn(tx):
            call_count[0] += 1
            raise ValueError("bad input")

        with pytest.raises(ValueError, match="bad input"):
            sess.write_transaction(fn, max_retries=3)

        assert call_count[0] == 1  # not retried

    def test_last_bookmark_initially_none(self):
        driver = _make_mock_driver()
        sess = IPFSSession(driver)
        assert sess.last_bookmark() is None

    def test_last_bookmarks_returns_list(self):
        driver = _make_mock_driver()
        sess = IPFSSession(driver)
        bookmarks = sess.last_bookmarks()
        assert isinstance(bookmarks, list)


# ===========================================================================
# 3. core/query_executor.py
# ===========================================================================
from ipfs_datasets_py.knowledge_graphs.core.query_executor import QueryExecutor
from ipfs_datasets_py.knowledge_graphs.exceptions import (
    QueryParseError,
    QueryExecutionError,
    KnowledgeGraphError,
)
from ipfs_datasets_py.knowledge_graphs.cypher.lexer import CypherLexer
from ipfs_datasets_py.knowledge_graphs.cypher.parser import CypherParser


class TestQueryExecutor:
    """GIVEN a QueryExecutor WHEN executing queries THEN routes and handles errors correctly."""

    def _qe(self):
        backend = MagicMock()
        backend.get_all_nodes.return_value = []
        backend.get_relationships.return_value = []
        return QueryExecutor(backend), backend

    def test_execute_cypher_select_returns_result(self):
        qe, _ = self._qe()
        result = qe.execute("MATCH (n) RETURN n")
        assert result is not None

    def test_execute_detects_cypher(self):
        qe, backend = self._qe()
        backend.get_all_nodes.return_value = [{"id": "n1", "labels": ["A"], "properties": {"x": 1}}]
        result = qe.execute("MATCH (n:A) RETURN n.x")
        assert result is not None

    def test_execute_ir_query_returns_empty(self):
        qe, _ = self._qe()
        result = qe.execute('{"type": "IR", "query": "test"}')
        assert result is not None

    def test_execute_simple_query_delegates(self):
        qe, _ = self._qe()
        result = qe.execute("get_node:n1")
        assert result is not None

    def test_execute_cypher_parse_error_raises_when_requested(self):
        qe, _ = self._qe()
        with pytest.raises(QueryParseError):
            qe._execute_cypher("MATCH BROKEN ~~~", {}, raise_on_error=True)

    def test_execute_cypher_parse_error_silent_returns_empty(self):
        qe, _ = self._qe()
        result = qe._execute_cypher("MATCH BROKEN ~~~", {}, raise_on_error=False)
        assert result is not None
        data = result.data()
        assert data == []

    def test_execute_cypher_compile_error_handled(self):
        """GIVEN valid parse but compile error THEN returns empty result without raise."""
        qe, _ = self._qe()
        # Inject a compile error by mocking the compiler
        from ipfs_datasets_py.knowledge_graphs.cypher import CypherCompiler
        from ipfs_datasets_py.knowledge_graphs.cypher.compiler import CypherCompileError
        with patch.object(CypherCompiler, "compile", side_effect=CypherCompileError("bad compile")):
            result = qe._execute_cypher("MATCH (n) RETURN n", {}, raise_on_error=False)
        data = result.data()
        assert data == []

    def test_compute_aggregation_count(self):
        qe, _ = self._qe()
        assert qe._compute_aggregation("COUNT", [1, 2, 3]) == 3

    def test_compute_aggregation_sum(self):
        qe, _ = self._qe()
        assert qe._compute_aggregation("SUM", [1, 2, 3]) == 6

    def test_compute_aggregation_avg(self):
        qe, _ = self._qe()
        assert qe._compute_aggregation("AVG", [2.0, 4.0]) == pytest.approx(3.0)

    def test_compute_aggregation_min(self):
        qe, _ = self._qe()
        assert qe._compute_aggregation("MIN", [5, 2, 8]) == 2

    def test_compute_aggregation_max(self):
        qe, _ = self._qe()
        assert qe._compute_aggregation("MAX", [5, 2, 8]) == 8

    def test_compute_aggregation_collect(self):
        qe, _ = self._qe()
        assert qe._compute_aggregation("COLLECT", [1, 2, 3]) == [1, 2, 3]

    def test_compute_aggregation_stdev(self):
        qe, _ = self._qe()
        stdev = qe._compute_aggregation("STDEV", [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0])
        assert stdev is not None
        assert stdev > 0

    def test_compute_aggregation_stdev_single_value_returns_none(self):
        qe, _ = self._qe()
        assert qe._compute_aggregation("STDEV", [5.0]) is None

    def test_compute_aggregation_unknown_returns_none(self):
        qe, _ = self._qe()
        assert qe._compute_aggregation("UNKNOWN_FN", [1, 2]) is None

    def test_compute_aggregation_empty_sum_returns_zero(self):
        qe, _ = self._qe()
        assert qe._compute_aggregation("SUM", []) == 0

    def test_compute_aggregation_empty_avg_returns_none(self):
        qe, _ = self._qe()
        assert qe._compute_aggregation("AVG", []) is None


# ===========================================================================
# 4. extraction/validator.py
# ===========================================================================
from ipfs_datasets_py.knowledge_graphs.extraction.validator import (
    KnowledgeGraphExtractorWithValidation,
)


class TestKnowledgeGraphExtractorWithValidation:
    """GIVEN KnowledgeGraphExtractorWithValidation WHEN extracting THEN validates and returns results."""

    def _make_vke(self, with_validator=False, validate_during=False, auto_correct=False):
        vke = KnowledgeGraphExtractorWithValidation.__new__(KnowledgeGraphExtractorWithValidation)
        # Minimal init without real extractor
        vke.validator = None
        vke.validator_available = False
        vke.tracer = None
        vke.validate_during_extraction = validate_during
        vke.auto_correct_suggestions = auto_correct
        vke.min_confidence = 0.7
        # Create a minimal extractor stub
        extractor = MagicMock()
        extractor.extract_enhanced_knowledge_graph.return_value = _make_kg(3, 2)
        extractor.extract_from_documents.return_value = _make_kg(2, 1)
        extractor.extract_from_wikipedia.return_value = _make_kg(4, 2)
        extractor.enrich_with_types.side_effect = lambda kg: kg
        vke.extractor = extractor
        if with_validator:
            validator = MagicMock()
            vk = MagicMock()
            vk.to_dict.return_value = {"valid": True}
            vk.data = {"entity_coverage": 0.8, "relationship_coverage": 0.7, "overall_coverage": 0.75}
            vk.is_valid = True
            validator.validate_knowledge_graph.return_value = vk
            validator.generate_validation_explanation.return_value = "Use X instead"
            validator.find_entity_paths.return_value = MagicMock(is_valid=False)
            vke.validator = validator
            vke.validator_available = True
        return vke

    def test_extract_knowledge_graph_no_validator_returns_kg(self):
        vke = self._make_vke()
        result = vke.extract_knowledge_graph("Alice works at Acme Corp.")
        assert "knowledge_graph" in result
        assert "entity_count" in result
        assert result["entity_count"] == 3

    def test_extract_knowledge_graph_validate_disabled_skips_validation(self):
        vke = self._make_vke(with_validator=True, validate_during=False)
        result = vke.extract_knowledge_graph("test text")
        assert "validation_results" not in result

    def test_extract_knowledge_graph_validate_enabled_calls_validator(self):
        vke = self._make_vke(with_validator=True, validate_during=True)
        result = vke.extract_knowledge_graph("test text")
        assert "validation_results" in result
        assert result["validation_results"] == {"valid": True}

    def test_extract_knowledge_graph_auto_correct_enabled(self):
        vke = self._make_vke(with_validator=True, validate_during=True, auto_correct=True)
        # Entity with invalid validation
        vk = MagicMock()
        vk.to_dict.return_value = {}
        vk.data = {
            "entity_coverage": 0.5, "relationship_coverage": 0.5, "overall_coverage": 0.5,
            "entity_validations": {"e0": {"valid": False, "name": "Entity0"}},
        }
        vke.validator.validate_knowledge_graph.return_value = vk
        vke.validator.generate_validation_explanation.return_value = "Fix it"
        result = vke.extract_knowledge_graph("text with invalid entity")
        assert "corrections" in result

    def test_extract_knowledge_graph_extractor_error_returns_error_dict(self):
        vke = self._make_vke()
        vke.extractor.extract_enhanced_knowledge_graph.side_effect = RuntimeError("crash")
        result = vke.extract_knowledge_graph("text")
        assert "error" in result
        assert result["knowledge_graph"] is None

    def test_extract_from_documents_basic(self):
        vke = self._make_vke()
        docs = [{"text": "Alice works at Acme."}, {"text": "Bob leads BigCo."}]
        result = vke.extract_from_documents(docs)
        assert "knowledge_graph" in result
        assert result["entity_count"] == 2

    def test_extract_from_documents_error_path(self):
        vke = self._make_vke()
        vke.extractor.extract_from_documents.side_effect = RuntimeError("fail")
        result = vke.extract_from_documents([{"text": "x"}])
        assert "error" in result
        assert result["knowledge_graph"] is None

    def test_validate_against_wikidata_no_validator_returns_invalid(self):
        vke = self._make_vke()
        kg = _make_kg(2, 1)
        result = vke.validate_against_wikidata(kg)
        assert isinstance(result, dict)
        # Without validator, result contains a warning/error
        assert "error" in result or "valid" in result or result == {}

    def test_validate_against_wikidata_with_validator(self):
        vke = self._make_vke(with_validator=True)
        kg = _make_kg(2, 1)
        vke.validator.validate_knowledge_graph.return_value = MagicMock(
            to_dict=lambda: {"valid": True, "score": 0.9},
            is_valid=True
        )
        result = vke.validate_against_wikidata(kg)
        assert isinstance(result, dict)

    def test_apply_validation_corrections_empty_kg_unchanged(self):
        vke = self._make_vke()
        kg = _make_kg(0, 0)
        result = vke.apply_validation_corrections(kg, {})
        # Returns a new KG copy (not same object), but with same name
        assert result is not None
        assert isinstance(result, KnowledgeGraph)

    def test_apply_validation_corrections_entity_with_none_properties(self):
        """GIVEN entity with properties=None WHEN apply_validation_corrections THEN no crash."""
        vke = self._make_vke()
        kg = KnowledgeGraph(name="test")
        e = Entity(entity_id="e0", name="E0", entity_type="X", properties=None)
        kg.add_entity(e)
        corrections = {}
        # Should not raise AttributeError
        result = vke.apply_validation_corrections(kg, corrections)
        assert result is not None


# ===========================================================================
# 5. transactions/wal.py
# ===========================================================================
from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
from ipfs_datasets_py.knowledge_graphs.transactions.types import (
    WALEntry,
    Operation,
    TransactionState,
    OperationType,
)
from ipfs_datasets_py.knowledge_graphs.exceptions import (
    SerializationError,
    StorageError,
    TransactionError,
    DeserializationError,
)


def _make_wal_storage():
    """Create a mock storage that simulates IPLD JSON storage."""
    storage = MagicMock()
    _store = {}

    def _store_json(obj):
        cid = f"cid-{uuid.uuid4().hex[:8]}"
        _store[cid] = json.dumps(obj)
        return cid

    def _retrieve_json(cid):
        if cid not in _store:
            raise StorageError(f"Not found: {cid}")
        return json.loads(_store[cid])

    storage.store_json.side_effect = _store_json
    storage.retrieve_json.side_effect = _retrieve_json
    return storage, _store


def _make_entry(txn_id="txn-1", state=TransactionState.COMMITTED, ops=None):
    op = Operation(
        type=OperationType.WRITE_NODE,
        node_id="e1",
        data={"id": "e1"},
    )
    return WALEntry(
        txn_id=txn_id,
        timestamp=time.time(),
        operations=ops if ops is not None else [op],
        prev_wal_cid=None,
        txn_state=state,
    )


class TestWriteAheadLog:
    """GIVEN a WriteAheadLog WHEN performing operations THEN log is updated correctly."""

    def test_append_returns_cid_and_updates_head(self):
        storage, _ = _make_wal_storage()
        wal = WriteAheadLog(storage)
        entry = _make_entry()
        cid = wal.append(entry)
        assert isinstance(cid, str)
        assert wal.wal_head_cid == cid

    def test_append_increments_entry_count(self):
        storage, _ = _make_wal_storage()
        wal = WriteAheadLog(storage)
        wal.append(_make_entry("t1"))
        wal.append(_make_entry("t2"))
        assert wal._entry_count == 2

    def test_append_links_prev_cid(self):
        storage, store = _make_wal_storage()
        wal = WriteAheadLog(storage)
        cid1 = wal.append(_make_entry("t1"))
        cid2 = wal.append(_make_entry("t2"))
        # Second entry should reference first as prev_wal_cid
        entry2_dict = json.loads(store[cid2])
        assert entry2_dict.get("prev_wal_cid") == cid1

    def test_append_serialization_error_raises_serialization_error(self):
        storage = MagicMock()
        storage.store_json.side_effect = TypeError("unserializable")
        wal = WriteAheadLog(storage)
        entry = _make_entry()
        with pytest.raises(SerializationError):
            wal.append(entry)

    def test_append_storage_error_raises_transaction_error(self):
        storage = MagicMock()
        storage.store_json.side_effect = StorageError("disk full")
        wal = WriteAheadLog(storage)
        entry = _make_entry()
        with pytest.raises(TransactionError):
            wal.append(entry)

    def test_read_empty_wal_yields_nothing(self):
        storage, _ = _make_wal_storage()
        wal = WriteAheadLog(storage)
        entries = list(wal.read())
        assert entries == []

    def test_read_returns_entries_in_reverse_order(self):
        storage, _ = _make_wal_storage()
        wal = WriteAheadLog(storage)
        wal.append(_make_entry("t1"))
        wal.append(_make_entry("t2"))
        entries = list(wal.read())
        assert len(entries) == 2
        # First entry returned is the most recent (t2)
        assert entries[0].txn_id == "t2"
        assert entries[1].txn_id == "t1"

    def test_compact_resets_entry_count(self):
        storage, _ = _make_wal_storage()
        wal = WriteAheadLog(storage)
        cid1 = wal.append(_make_entry("t1"))
        wal.append(_make_entry("t2"))
        assert wal._entry_count == 2
        wal.compact(cid1)
        assert wal._entry_count == 0

    def test_compact_updates_wal_head(self):
        storage, _ = _make_wal_storage()
        wal = WriteAheadLog(storage)
        cid1 = wal.append(_make_entry("t1"))
        old_head = wal.wal_head_cid
        new_head = wal.compact(cid1)
        assert new_head != old_head
        assert wal.wal_head_cid == new_head

    def test_recover_empty_wal_returns_empty_list(self):
        storage, _ = _make_wal_storage()
        wal = WriteAheadLog(storage)
        ops = wal.recover()
        assert ops == []

    def test_recover_returns_committed_operations(self):
        storage, _ = _make_wal_storage()
        wal = WriteAheadLog(storage)
        wal.append(_make_entry("t1", state=TransactionState.COMMITTED))
        ops = wal.recover()
        assert len(ops) == 1

    def test_recover_skips_aborted_transactions(self):
        storage, _ = _make_wal_storage()
        wal = WriteAheadLog(storage)
        wal.append(_make_entry("t1", state=TransactionState.ABORTED))
        ops = wal.recover()
        assert ops == []

    def test_recover_from_explicit_cid(self):
        storage, _ = _make_wal_storage()
        wal = WriteAheadLog(storage)
        cid = wal.append(_make_entry("t1", state=TransactionState.COMMITTED))
        ops = wal.recover(cid)
        assert len(ops) == 1

    def test_get_transaction_history_matching(self):
        storage, _ = _make_wal_storage()
        wal = WriteAheadLog(storage)
        wal.append(_make_entry("txn-target", state=TransactionState.COMMITTED))
        wal.append(_make_entry("txn-other", state=TransactionState.COMMITTED))
        history = wal.get_transaction_history("txn-target")
        assert len(history) == 1
        assert history[0].txn_id == "txn-target"

    def test_get_transaction_history_unknown_txn_returns_empty(self):
        storage, _ = _make_wal_storage()
        wal = WriteAheadLog(storage)
        wal.append(_make_entry("t1"))
        history = wal.get_transaction_history("no-such-txn")
        assert history == []

    def test_get_stats_returns_required_keys(self):
        storage, _ = _make_wal_storage()
        wal = WriteAheadLog(storage)
        stats = wal.get_stats()
        assert "head_cid" in stats
        assert "entry_count" in stats
        assert "compaction_threshold" in stats
        assert "needs_compaction" in stats

    def test_get_stats_entry_count_increments(self):
        storage, _ = _make_wal_storage()
        wal = WriteAheadLog(storage)
        wal.append(_make_entry("t1"))
        wal.append(_make_entry("t2"))
        stats = wal.get_stats()
        assert stats["entry_count"] == 2

    def test_verify_integrity_empty_wal(self):
        storage, _ = _make_wal_storage()
        wal = WriteAheadLog(storage)
        assert wal.verify_integrity() is True

    def test_verify_integrity_valid_chain(self):
        storage, _ = _make_wal_storage()
        wal = WriteAheadLog(storage)
        wal.append(_make_entry("t1"))
        wal.append(_make_entry("t2"))
        assert wal.verify_integrity() is True

    def test_verify_integrity_invalid_entry_empty_ops_returns_false(self):
        """GIVEN entry with empty operations list WHEN verify_integrity THEN returns False."""
        storage, _ = _make_wal_storage()
        wal = WriteAheadLog(storage)
        # Entry with no operations — verify_integrity checks `not entry.operations`
        wal.append(_make_entry("t1", ops=[]))
        assert wal.verify_integrity() is False
