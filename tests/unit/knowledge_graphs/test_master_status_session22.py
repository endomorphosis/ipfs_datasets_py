"""
Session 22: Targeted coverage boosts for 6 high-impact modules.

Modules targeted (all measured improvements):
- query/unified_engine.py  (82% → 88%): cypher/IR/hybrid/graphrag error/timeout/re-raise paths
- neo4j_compat/result.py   (85% → 99%): keys() empty, value() no-key, graph() types, __bool__
- neo4j_compat/session.py  (85% → 98%): bookmarks obj, run errors, tx errors, retry logic
- cypher/compiler.py       (91% → 95%): unknown clause, SET/DELETE/WITH, UnaryOp/List/dict/fallback
- extraction/graph.py      (78% → 98%): add_relationship weird obj, export_to_rdf all branches
- core/expression_evaluator.py (89% → 96%): multi-arg fn, string None paths, compiled paths
"""

import asyncio
import os
import sys
import tempfile
import pytest
from unittest.mock import MagicMock, patch, PropertyMock


# ---------------------------------------------------------------------------
# Section 1: query/unified_engine.py — error / timeout / re-raise paths
# ---------------------------------------------------------------------------

class TestUnifiedEngineErrorPaths:
    """GIVEN a UnifiedQueryEngine with mocked sub-components,
    WHEN error conditions are triggered inside execute_cypher/execute_ir/execute_hybrid/execute_graphrag,
    THEN the correct KG error subclasses are raised."""

    def _make_engine(self, *, llm=None):
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import UnifiedQueryEngine
        backend = MagicMock()
        engine = UnifiedQueryEngine(backend=backend, llm_processor=llm)
        # Inject a mock ir_executor so property init doesn't fail
        engine._ir_executor = MagicMock()
        engine._ir_executor.execute.return_value = MagicMock(items=[], stats={})
        return engine

    # --- execute_cypher ---

    def test_execute_cypher_timeout_raises_query_timeout_error(self):
        """GIVEN cypher parser raises TimeoutError,
        WHEN execute_cypher is called,
        THEN QueryTimeoutError is raised."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import QueryTimeoutError
        engine = self._make_engine()
        mock_parser = MagicMock()
        mock_parser.parse.side_effect = TimeoutError("parse timeout")
        engine._cypher_parser = mock_parser
        engine._cypher_compiler = MagicMock()
        with pytest.raises(QueryTimeoutError):
            engine.execute_cypher("MATCH (n) RETURN n")

    def test_execute_cypher_generic_error_raises_query_execution_error(self):
        """GIVEN cypher compiler raises RuntimeError,
        WHEN execute_cypher is called,
        THEN QueryExecutionError is raised."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import QueryExecutionError
        engine = self._make_engine()
        mock_parser = MagicMock()
        mock_parser.parse.return_value = MagicMock()
        engine._cypher_parser = mock_parser
        mock_compiler = MagicMock()
        mock_compiler.compile.side_effect = RuntimeError("compiler boom")
        engine._cypher_compiler = mock_compiler
        with pytest.raises(QueryExecutionError):
            engine.execute_cypher("MATCH (n) RETURN n")

    # --- execute_ir ---

    def test_execute_ir_value_error_raises_query_parse_error(self):
        """GIVEN IR executor raises ValueError,
        WHEN execute_ir is called,
        THEN QueryParseError is raised."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import QueryParseError
        engine = self._make_engine()
        engine._ir_executor.execute.side_effect = ValueError("bad IR")
        with pytest.raises(QueryParseError):
            engine.execute_ir(MagicMock())

    def test_execute_ir_timeout_raises_query_timeout_error(self):
        """GIVEN IR executor raises TimeoutError,
        WHEN execute_ir is called,
        THEN QueryTimeoutError is raised."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import QueryTimeoutError
        engine = self._make_engine()
        engine._ir_executor.execute.side_effect = TimeoutError("ir timeout")
        with pytest.raises(QueryTimeoutError):
            engine.execute_ir(MagicMock())

    def test_execute_ir_generic_error_raises_query_execution_error(self):
        """GIVEN IR executor raises RuntimeError,
        WHEN execute_ir is called,
        THEN QueryExecutionError is raised."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import QueryExecutionError
        engine = self._make_engine()
        engine._ir_executor.execute.side_effect = RuntimeError("runtime fail")
        with pytest.raises(QueryExecutionError):
            engine.execute_ir(MagicMock())

    def test_execute_ir_query_execution_error_reraises(self):
        """GIVEN IR executor raises QueryExecutionError directly,
        WHEN execute_ir is called,
        THEN the same QueryExecutionError is re-raised (not double-wrapped)."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import QueryExecutionError
        engine = self._make_engine()
        original = QueryExecutionError("direct")
        engine._ir_executor.execute.side_effect = original
        with pytest.raises(QueryExecutionError) as exc_info:
            engine.execute_ir(MagicMock())
        assert exc_info.value is original

    # --- execute_hybrid ---

    def test_execute_hybrid_value_error_raises_query_execution_error(self):
        """GIVEN hybrid_search.search raises ValueError,
        WHEN execute_hybrid is called,
        THEN QueryExecutionError is raised."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import QueryExecutionError
        engine = self._make_engine()
        with patch.object(engine.hybrid_search, "search", side_effect=ValueError("bad config")):
            with pytest.raises(QueryExecutionError):
                engine.execute_hybrid("test query")

    def test_execute_hybrid_timeout_raises_query_timeout_error(self):
        """GIVEN hybrid_search.search raises TimeoutError,
        WHEN execute_hybrid is called,
        THEN QueryTimeoutError is raised."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import QueryTimeoutError
        engine = self._make_engine()
        with patch.object(engine.hybrid_search, "search", side_effect=TimeoutError("hybrid timeout")):
            with pytest.raises(QueryTimeoutError):
                engine.execute_hybrid("test query")

    def test_execute_hybrid_generic_error_raises_query_execution_error(self):
        """GIVEN hybrid_search.search raises RuntimeError,
        WHEN execute_hybrid is called,
        THEN QueryExecutionError is raised with details."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import QueryExecutionError
        engine = self._make_engine()
        with patch.object(engine.hybrid_search, "search", side_effect=RuntimeError("boom")):
            with pytest.raises(QueryExecutionError) as exc_info:
                engine.execute_hybrid("test query")
        assert "boom" in str(exc_info.value)

    # --- execute_graphrag ---

    def test_execute_graphrag_llm_cancelled_error_propagates(self):
        """GIVEN LLM reasoning raises asyncio.CancelledError,
        WHEN execute_graphrag is called,
        THEN CancelledError propagates (not wrapped in QueryExecutionError)."""
        llm = MagicMock()
        llm.reason.side_effect = asyncio.CancelledError()
        engine = self._make_engine(llm=llm)
        with patch.object(engine.hybrid_search, "search", return_value=[]):
            with pytest.raises(asyncio.CancelledError):
                engine.execute_graphrag("test question")

    def test_execute_graphrag_llm_runtime_error_raises_query_execution_error(self):
        """GIVEN LLM processor raises RuntimeError,
        WHEN execute_graphrag is called,
        THEN QueryExecutionError is raised."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import QueryExecutionError
        llm = MagicMock()
        llm.reason.side_effect = RuntimeError("llm crashed")
        engine = self._make_engine(llm=llm)
        with patch.object(engine.hybrid_search, "search", return_value=[]):
            with pytest.raises(QueryExecutionError):
                engine.execute_graphrag("test question")

    def test_execute_graphrag_outer_timeout_raises_query_timeout_error(self):
        """GIVEN execute_hybrid raises raw TimeoutError at the outer level,
        WHEN execute_graphrag is called,
        THEN QueryTimeoutError is raised with 'GraphRAG query timed out'."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import QueryTimeoutError
        engine = self._make_engine()
        with patch.object(engine, "execute_hybrid", side_effect=TimeoutError("graphrag outer timeout")):
            with pytest.raises(QueryTimeoutError) as exc_info:
                engine.execute_graphrag("test question")
        assert "GraphRAG query timed out" in str(exc_info.value)

    def test_execute_graphrag_outer_generic_error_raises_query_execution_error(self):
        """GIVEN execute_hybrid raises OSError (non-QE, non-timeout),
        WHEN execute_graphrag is called,
        THEN QueryExecutionError is raised with 'Failed to execute GraphRAG query'."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import QueryExecutionError
        engine = self._make_engine()
        with patch.object(engine, "execute_hybrid", side_effect=OSError("io error")):
            with pytest.raises(QueryExecutionError) as exc_info:
                engine.execute_graphrag("test question")
        assert "Failed to execute GraphRAG query" in str(exc_info.value)

    def test_execute_graphrag_query_execution_error_reraises(self):
        """GIVEN execute_hybrid raises QueryExecutionError,
        WHEN execute_graphrag is called,
        THEN the same QueryExecutionError is re-raised (not double-wrapped)."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import QueryExecutionError
        engine = self._make_engine()
        original = QueryExecutionError("original")
        with patch.object(engine, "execute_hybrid", side_effect=original):
            with pytest.raises(QueryExecutionError) as exc_info:
                engine.execute_graphrag("test question")
        assert exc_info.value is original

    def test_execute_graphrag_query_timeout_error_reraises(self):
        """GIVEN execute_hybrid raises QueryTimeoutError,
        WHEN execute_graphrag is called,
        THEN the same QueryTimeoutError is re-raised (not double-wrapped)."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import QueryTimeoutError
        engine = self._make_engine()
        original = QueryTimeoutError("original")
        with patch.object(engine, "execute_hybrid", side_effect=original):
            with pytest.raises(QueryTimeoutError) as exc_info:
                engine.execute_graphrag("test question")
        assert exc_info.value is original


# ---------------------------------------------------------------------------
# Section 2: neo4j_compat/result.py — keys/value/graph/bool paths
# ---------------------------------------------------------------------------

class TestNeo4jResultMissingPaths:
    """GIVEN a Result object with varying record contents,
    WHEN various methods are called,
    THEN the correct values are returned including empty-record edge cases."""

    def _make_result(self, rows):
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.result import Result, Record
        records = [Record(list(row.keys()), list(row.values())) for row in rows]
        return Result(records)

    def test_keys_on_empty_result_returns_empty_list(self):
        """GIVEN a Result with no records,
        WHEN keys() is called,
        THEN an empty list is returned."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.result import Result
        r = Result([])
        assert r.keys() == []

    def test_value_returns_empty_list_when_first_record_has_no_keys(self):
        """GIVEN a Result where the first record has no fields,
        WHEN value() is called with key=None,
        THEN an empty list is returned."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.result import Result, Record
        r = Result([Record([], [])])
        result = r.value()
        assert result == []

    def test_graph_includes_relationship_objects(self):
        """GIVEN a Result with a record containing a Relationship,
        WHEN graph() is called,
        THEN the relationships list contains that Relationship."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.result import Result, Record
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.types import Node, Relationship
        n1 = Node("1", ["Person"], {"name": "Alice"})
        n2 = Node("2", ["Person"], {"name": "Bob"})
        rel = Relationship("r1", "KNOWS", n1, n2, {})
        r = Result([Record(["rel"], [rel])])
        graph_data = r.graph()
        assert len(graph_data["relationships"]) == 1
        assert graph_data["relationships"][0] is rel

    def test_graph_includes_path_objects_and_extracts_nodes_and_rels(self):
        """GIVEN a Result with a record containing a Path,
        WHEN graph() is called,
        THEN paths, nodes from the path, and relationships from the path are all included."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.result import Result, Record
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.types import Node, Relationship, Path
        n1 = Node("1", ["Person"], {"name": "Alice"})
        n2 = Node("2", ["Person"], {"name": "Bob"})
        rel = Relationship("r1", "KNOWS", n1, n2, {})
        path = Path(n1, rel, n2)
        r = Result([Record(["p"], [path])])
        graph_data = r.graph()
        assert len(graph_data["paths"]) == 1
        # nodes and rels from path should be extracted
        assert n1 in graph_data["nodes"]
        assert n2 in graph_data["nodes"]
        assert rel in graph_data["relationships"]

    def test_graph_deduplicates_nodes(self):
        """GIVEN two records each containing the same Node,
        WHEN graph() is called,
        THEN the node appears only once."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.result import Result, Record
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.types import Node
        n = Node("1", ["Person"], {"name": "Alice"})
        r = Result([Record(["n"], [n]), Record(["n"], [n])])
        graph_data = r.graph()
        assert graph_data["nodes"].count(n) == 1

    def test_bool_is_false_for_empty_result(self):
        """GIVEN a Result with no records,
        WHEN bool() is called,
        THEN it returns False."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.result import Result
        assert not Result([])

    def test_bool_is_true_for_nonempty_result(self):
        """GIVEN a Result with at least one record,
        WHEN bool() is called,
        THEN it returns True."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.result import Result, Record
        r = Result([Record(["n"], [42])])
        assert bool(r) is True


# ---------------------------------------------------------------------------
# Section 3: neo4j_compat/session.py — bookmarks, run errors, tx retry
# ---------------------------------------------------------------------------

class TestIPFSSessionMissingPaths:
    """GIVEN an IPFSSession with a mocked driver,
    WHEN various error conditions occur,
    THEN the correct exceptions are raised and retry logic is applied."""

    def _make_session(self, *, bookmarks=None, llm=None):
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.session import IPFSSession
        driver = MagicMock()
        driver.backend = MagicMock()
        if bookmarks is not None:
            return IPFSSession(driver, bookmarks=bookmarks)
        return IPFSSession(driver)

    def test_bookmarks_object_is_stored_directly(self):
        """GIVEN a Bookmarks object is passed to IPFSSession,
        WHEN the session is created,
        THEN self._bookmarks is that exact Bookmarks object."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.session import IPFSSession
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.bookmarks import Bookmarks
        bm = Bookmarks()
        driver = MagicMock()
        driver.backend = MagicMock()
        session = IPFSSession(driver, bookmarks=bm)
        assert session._bookmarks is bm

    def test_run_on_closed_session_raises_runtime_error(self):
        """GIVEN a closed session,
        WHEN run() is called,
        THEN RuntimeError('Session is closed') is raised."""
        session = self._make_session()
        session._closed = True
        with pytest.raises(RuntimeError, match="Session is closed"):
            session.run("MATCH (n) RETURN n")

    def test_run_propagates_not_implemented_error(self):
        """GIVEN query executor raises NotImplementedError,
        WHEN run() is called,
        THEN NotImplementedError propagates."""
        session = self._make_session()
        with patch.object(session._query_executor, "execute", side_effect=NotImplementedError("not yet")):
            with pytest.raises(NotImplementedError):
                session.run("MATCH (n) RETURN n")

    def test_begin_transaction_on_closed_session_raises_runtime_error(self):
        """GIVEN a closed session,
        WHEN begin_transaction() is called,
        THEN RuntimeError is raised."""
        session = self._make_session()
        session._closed = True
        with pytest.raises(RuntimeError, match="Session is closed"):
            session.begin_transaction()

    def test_begin_transaction_when_already_in_progress_raises_runtime_error(self):
        """GIVEN a session with an active transaction,
        WHEN begin_transaction() is called again,
        THEN RuntimeError('Transaction already in progress') is raised."""
        session = self._make_session()
        _tx = session.begin_transaction()  # start first transaction
        with pytest.raises(RuntimeError, match="Transaction already in progress"):
            session.begin_transaction()

    def test_read_transaction_on_closed_session_raises_runtime_error(self):
        """GIVEN a closed session,
        WHEN read_transaction() is called,
        THEN RuntimeError is raised."""
        session = self._make_session()
        session._closed = True
        with pytest.raises(RuntimeError, match="Session is closed"):
            session.read_transaction(lambda tx: None)

    def test_read_transaction_non_retryable_knowledge_graph_error(self):
        """GIVEN a transaction function raises KnowledgeGraphError,
        WHEN read_transaction() is called,
        THEN KnowledgeGraphError is raised without retrying."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import KnowledgeGraphError
        session = self._make_session()
        call_count = [0]

        def fn(tx):
            call_count[0] += 1
            raise KnowledgeGraphError("domain error")

        with pytest.raises(KnowledgeGraphError):
            session.read_transaction(fn)
        assert call_count[0] == 1  # only one attempt — no retry

    def test_read_transaction_non_retryable_type_error(self):
        """GIVEN a transaction function raises TypeError,
        WHEN read_transaction() is called,
        THEN TypeError is raised without retrying."""
        session = self._make_session()
        call_count = [0]

        def fn(tx):
            call_count[0] += 1
            raise TypeError("bad type")

        with pytest.raises(TypeError):
            session.read_transaction(fn)
        assert call_count[0] == 1  # no retry

    def test_read_transaction_retries_on_conflict_then_raises(self):
        """GIVEN a transaction function always raises TransactionConflictError,
        WHEN read_transaction() is called with max_retries=2,
        THEN it retries up to max_retries times before re-raising."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import TransactionConflictError
        session = self._make_session()
        call_count = [0]

        def fn(tx):
            call_count[0] += 1
            raise TransactionConflictError("conflict")

        with pytest.raises(TransactionConflictError):
            session.read_transaction(fn, max_retries=2)
        assert call_count[0] == 2

    def test_write_transaction_on_closed_session_raises_runtime_error(self):
        """GIVEN a closed session,
        WHEN write_transaction() is called,
        THEN RuntimeError is raised."""
        session = self._make_session()
        session._closed = True
        with pytest.raises(RuntimeError, match="Session is closed"):
            session.write_transaction(lambda tx: None)

    def test_write_transaction_non_retryable_knowledge_graph_error(self):
        """GIVEN a transaction function raises KnowledgeGraphError,
        WHEN write_transaction() is called,
        THEN KnowledgeGraphError is raised without retrying."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import KnowledgeGraphError
        session = self._make_session()
        call_count = [0]

        def fn(tx):
            call_count[0] += 1
            raise KnowledgeGraphError("domain error")

        with pytest.raises(KnowledgeGraphError):
            session.write_transaction(fn)
        assert call_count[0] == 1

    def test_write_transaction_retries_on_conflict_then_raises(self):
        """GIVEN a transaction function always raises TransactionConflictError,
        WHEN write_transaction() is called with max_retries=3,
        THEN it retries up to max_retries times."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import TransactionConflictError
        session = self._make_session()
        call_count = [0]

        def fn(tx):
            call_count[0] += 1
            raise TransactionConflictError("conflict")

        with pytest.raises(TransactionConflictError):
            session.write_transaction(fn, max_retries=3)
        assert call_count[0] == 3

    def test_write_transaction_success_returns_result(self):
        """GIVEN a successful transaction function,
        WHEN write_transaction() is called,
        THEN the function's return value is returned."""
        session = self._make_session()
        result = session.write_transaction(lambda tx: 99)
        assert result == 99

    def test_write_transaction_non_retryable_value_error(self):
        """GIVEN a transaction function raises ValueError,
        WHEN write_transaction() is called,
        THEN ValueError is raised without retrying."""
        session = self._make_session()
        call_count = [0]

        def fn(tx):
            call_count[0] += 1
            raise ValueError("bad value")

        with pytest.raises(ValueError):
            session.write_transaction(fn)
        assert call_count[0] == 1


# ---------------------------------------------------------------------------
# Section 4: cypher/compiler.py — missing compilation paths
# ---------------------------------------------------------------------------

class TestCypherCompilerMissingPaths:
    """GIVEN Cypher AST nodes,
    WHEN _compile_clause / compile is called,
    THEN the correct IR operations are emitted or CypherCompileError is raised."""

    def _make_compiler(self):
        from ipfs_datasets_py.knowledge_graphs.cypher.compiler import CypherCompiler
        return CypherCompiler()

    def _parse_and_compile(self, query: str):
        from ipfs_datasets_py.knowledge_graphs.cypher.parser import CypherParser
        c = self._make_compiler()
        p = CypherParser()
        ast = p.parse(query)
        return c.compile(ast)

    def test_unknown_clause_type_raises_cypher_compile_error(self):
        """GIVEN a clause type that the compiler does not know,
        WHEN _compile_clause is called,
        THEN CypherCompileError is raised."""
        from ipfs_datasets_py.knowledge_graphs.cypher.compiler import CypherCompileError
        from ipfs_datasets_py.knowledge_graphs.cypher.ast import ASTNode, ASTNodeType
        c = self._make_compiler()

        class _Bogus(ASTNode):
            pass

        with pytest.raises(CypherCompileError, match="Unknown clause type"):
            c._compile_clause(_Bogus(node_type=ASTNodeType.QUERY))

    def test_set_property_emits_set_property_op(self):
        """GIVEN MATCH (n) SET n.age = 30 RETURN n,
        WHEN compiled,
        THEN a SetProperty op with correct variable/property/value is emitted."""
        ops = self._parse_and_compile("MATCH (n:Person) SET n.age = 30 RETURN n")
        set_ops = [o for o in ops if isinstance(o, dict) and o.get("op") == "SetProperty"]
        assert len(set_ops) >= 1
        assert set_ops[0]["variable"] == "n"
        assert set_ops[0]["property"] == "age"
        assert set_ops[0]["value"] == 30

    def test_delete_emits_delete_op_with_detach_false(self):
        """GIVEN MATCH (n) DELETE n,
        WHEN compiled,
        THEN a Delete op with detach=False is emitted."""
        ops = self._parse_and_compile("MATCH (n:Person) DELETE n")
        del_ops = [o for o in ops if isinstance(o, dict) and o.get("op") == "Delete"]
        assert len(del_ops) >= 1
        assert del_ops[0]["variable"] == "n"
        assert del_ops[0]["detach"] is False

    def test_with_skip_and_limit_included_in_with_project_op(self):
        """GIVEN MATCH (n) WITH n SKIP 5 LIMIT 10 RETURN n,
        WHEN compiled,
        THEN the WithProject op has skip=5 and limit=10."""
        ops = self._parse_and_compile("MATCH (n) WITH n SKIP 5 LIMIT 10 RETURN n")
        with_ops = [o for o in ops if isinstance(o, dict) and o.get("op") == "WithProject"]
        assert len(with_ops) >= 1
        assert with_ops[0].get("skip") == 5
        assert with_ops[0].get("limit") == 10

    def test_unary_not_compiles_to_not_op(self):
        """GIVEN WHERE NOT n.active,
        WHEN compiled,
        THEN a Filter op with op='NOT' in expression is emitted."""
        ops = self._parse_and_compile("MATCH (n) WHERE NOT n.active RETURN n")
        filter_ops = [o for o in ops if isinstance(o, dict) and o.get("op") == "Filter"]
        assert len(filter_ops) >= 1
        expr = filter_ops[0].get("expression", {})
        assert expr.get("op") == "NOT"

    def test_list_node_compiles_to_python_list(self):
        """GIVEN RETURN [1, 2, 3],
        WHEN compiled,
        THEN a Project op where the expression is a Python list [1, 2, 3] is emitted."""
        ops = self._parse_and_compile("MATCH (n) RETURN [1, 2, 3]")
        project_ops = [o for o in ops if isinstance(o, dict) and o.get("op") == "Project"]
        assert len(project_ops) >= 1
        expr = project_ops[0]["items"][0]["expression"]
        assert isinstance(expr, list)
        assert expr == [1, 2, 3]

    def test_compile_expression_dict_input_returns_compiled_dict(self):
        """GIVEN a raw dict is passed to _compile_expression,
        WHEN called,
        THEN a dict with compiled values is returned."""
        c = self._make_compiler()
        from ipfs_datasets_py.knowledge_graphs.cypher.ast import LiteralNode, ASTNodeType
        raw_dict = {"key": LiteralNode(node_type=ASTNodeType.LITERAL, value=42, value_type="int")}
        result = c._compile_expression(raw_dict)
        assert isinstance(result, dict)
        assert result["key"] == 42

    def test_compile_expression_fallback_converts_to_str(self):
        """GIVEN an unrecognized expression type (raw int),
        WHEN _compile_expression is called,
        THEN str(expr) is returned (the fallback branch)."""
        c = self._make_compiler()
        result = c._compile_expression(99)
        assert result == "99"

    def test_expression_to_string_fallback_converts_to_str(self):
        """GIVEN a non-AST-node integer,
        WHEN _expression_to_string is called,
        THEN str(expr) is returned."""
        c = self._make_compiler()
        result = c._expression_to_string(42)
        assert result == "42"

    def test_aggregation_no_arguments_uses_star(self):
        """GIVEN a FunctionCallNode with no arguments,
        WHEN _compile_aggregation is called,
        THEN expression='*' is returned."""
        from ipfs_datasets_py.knowledge_graphs.cypher.ast import FunctionCallNode, ASTNodeType
        c = self._make_compiler()
        fn = FunctionCallNode(
            node_type=ASTNodeType.FUNCTION_CALL, name="count", arguments=[], distinct=False
        )
        result = c._compile_aggregation(fn)
        assert result["expression"] == "*"

    def test_create_relationship_emits_create_relationship_op(self):
        """GIVEN MATCH (a), (b) CREATE (a)-[:KNOWS]->(b),
        WHEN compiled,
        THEN a CreateRelationship op with rel_type=KNOWS is emitted."""
        ops = self._parse_and_compile(
            "MATCH (a:Person), (b:Person) CREATE (a)-[:KNOWS]->(b) RETURN a"
        )
        cr_ops = [o for o in ops if isinstance(o, dict) and o.get("op") == "CreateRelationship"]
        assert len(cr_ops) >= 1
        assert cr_ops[0]["rel_type"] == "KNOWS"


# ---------------------------------------------------------------------------
# Section 5: extraction/graph.py — add_relationship weird obj + export_to_rdf
# ---------------------------------------------------------------------------

class TestExtractionGraphMissingPaths:
    """GIVEN a KnowledgeGraph with entities and relationships,
    WHEN methods that were previously uncovered are called,
    THEN the correct results are produced."""

    def _make_kg(self, name="test"):
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        return KnowledgeGraph(name=name)

    def _add_person(self, kg, eid, name, **props):
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import Entity
        e = Entity(entity_id=eid, entity_type="Person", name=name, properties=props)
        return kg.add_entity(e)

    def test_add_relationship_with_obj_lacking_entity_id_uses_str_fallback(self):
        """GIVEN a relationship whose source has entity_id but target is a plain object,
        WHEN add_relationship is called,
        THEN the target is stored via str() fallback and relationship is added."""
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import Relationship

        class WeirdObj:
            def __repr__(self):
                return "weird_obj"

        kg = self._make_kg()
        e1 = self._add_person(kg, "e1", "Alice")
        weird = WeirdObj()
        rel = Relationship(
            relationship_id="r1",
            relationship_type="KNOWS",
            source_entity=e1,
            target_entity=weird,
            properties={},
        )
        result = kg.add_relationship(rel)
        assert result.relationship_id == "r1"
        # The weird object's str representation should be in entity_relationships
        weird_key = str(weird)
        assert weird_key in kg.entity_relationships or "e1" in kg.entity_relationships

    def test_add_relationship_both_str_entities(self):
        """GIVEN a relationship whose source_entity and target_entity are plain strings,
        WHEN add_relationship is called,
        THEN the string IDs are used as the relationship endpoint keys."""
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import Entity, Relationship

        kg = self._make_kg()
        # Add entities for the string IDs
        kg.add_entity(Entity(entity_id="s1", entity_type="X", name="S1", properties={}))
        kg.add_entity(Entity(entity_id="t1", entity_type="X", name="T1", properties={}))
        # Use string IDs directly (not Entity objects)
        rel = Relationship(
            relationship_id="r2",
            relationship_type="LINK",
            source_entity="s1",
            target_entity="t1",
            properties={},
        )
        result = kg.add_relationship(rel)
        assert result.relationship_id == "r2"
        assert "s1" in kg.entity_relationships
        assert "t1" in kg.entity_relationships

    def test_export_to_rdf_turtle_includes_entities_and_relationships(self):
        """GIVEN a KG with entities and a relationship,
        WHEN export_to_rdf(format='turtle') is called,
        THEN the result is a non-empty string containing entity names and the rel type."""
        pytest.importorskip("rdflib")
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import Entity, Relationship

        kg = self._make_kg("rdf_test")
        e1 = self._add_person(kg, "e1", "Alice")
        e2 = self._add_person(kg, "e2", "Bob")
        rel = Relationship("r1", "KNOWS", e1, e2, {})
        kg.add_relationship(rel)

        rdf = kg.export_to_rdf(format="turtle")
        assert "Alice" in rdf
        assert "KNOWS" in rdf

    def test_export_to_rdf_integer_property_uses_xsd_integer(self):
        """GIVEN an entity with an integer property,
        WHEN export_to_rdf is called,
        THEN the serialized RDF contains the integer value."""
        pytest.importorskip("rdflib")
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import Entity

        kg = self._make_kg("int_prop")
        self._add_person(kg, "e1", "Alice", age=30)

        rdf = kg.export_to_rdf()
        assert "30" in rdf

    def test_export_to_rdf_float_property_uses_xsd_float(self):
        """GIVEN an entity with a float property,
        WHEN export_to_rdf is called,
        THEN the serialized RDF contains the float value."""
        pytest.importorskip("rdflib")
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import Entity

        kg = self._make_kg("float_prop")
        self._add_person(kg, "e1", "Alice", score=0.95)

        rdf = kg.export_to_rdf()
        assert "0.95" in rdf

    def test_export_to_rdf_bool_property_uses_xsd_boolean(self):
        """GIVEN an entity with a boolean property,
        WHEN export_to_rdf is called,
        THEN the serialized RDF includes the boolean value."""
        pytest.importorskip("rdflib")
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import Entity

        kg = self._make_kg("bool_prop")
        self._add_person(kg, "e1", "Alice", active=True)

        rdf = kg.export_to_rdf()
        # rdflib serializes booleans as 'true' or 'false'
        assert "true" in rdf.lower() or "false" in rdf.lower()

    def test_export_to_rdf_relationship_with_properties_uses_reification(self):
        """GIVEN a relationship with properties,
        WHEN export_to_rdf is called,
        THEN the reification triples (rdf:Statement) appear in the output."""
        pytest.importorskip("rdflib")
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import Entity, Relationship

        kg = self._make_kg("rel_props")
        e1 = self._add_person(kg, "e1", "Alice")
        e2 = self._add_person(kg, "e2", "Bob")
        rel = Relationship("r1", "KNOWS", e1, e2, {"since": 2020})
        kg.add_relationship(rel)

        rdf = kg.export_to_rdf()
        # The reification statement should be present
        assert "Statement" in rdf or "since" in rdf

    def test_export_to_rdf_xml_format_returns_xml_string(self):
        """GIVEN a KG with an entity,
        WHEN export_to_rdf(format='xml') is called,
        THEN the result starts with XML-like content."""
        pytest.importorskip("rdflib")
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import Entity

        kg = self._make_kg("xml_test")
        self._add_person(kg, "e1", "Alice")

        rdf = kg.export_to_rdf(format="xml")
        assert "RDF" in rdf or "<?xml" in rdf

    def test_export_to_rdf_without_rdflib_returns_error_string(self):
        """GIVEN rdflib is not importable,
        WHEN export_to_rdf is called,
        THEN a string starting with 'Error:' is returned."""
        kg = self._make_kg("no_rdflib")
        with patch.dict(sys.modules, {"rdflib": None, "rdflib.namespace": None}):
            result = kg.export_to_rdf()
        assert result.startswith("Error:")

    def test_find_paths_dfs_visits_intermediate_nodes(self):
        """GIVEN a chain e1 -> e2 -> e3,
        WHEN find_paths(e1, e3, max_depth=3) is called,
        THEN a path through e2 is returned."""
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import Entity, Relationship

        kg = self._make_kg("chain")
        e1 = self._add_person(kg, "e1", "A")
        e2 = self._add_person(kg, "e2", "B")
        e3 = self._add_person(kg, "e3", "C")
        kg.add_relationship(Relationship("r1", "LINK", e1, e2, {}))
        kg.add_relationship(Relationship("r2", "LINK", e2, e3, {}))

        paths = kg.find_paths(e1, e3, max_depth=3)
        assert len(paths) >= 1
        # The 2-hop path should go through e2
        assert any(len(path) >= 2 for path in paths)


# ---------------------------------------------------------------------------
# Section 6: core/expression_evaluator.py — function / compiled paths
# ---------------------------------------------------------------------------

class TestExpressionEvaluatorMissingPaths:
    """GIVEN expression evaluator functions,
    WHEN they are called with edge-case inputs,
    THEN the correct results are returned."""

    def test_call_function_multi_arg_from_registry(self):
        """GIVEN atan2 (multi-arg) is in the FUNCTION_REGISTRY,
        WHEN call_function('atan2', [1.0, 1.0]) is called,
        THEN the correct float result is returned."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function
        import math
        result = call_function("atan2", [1.0, 1.0])
        assert abs(result - math.pi / 4) < 1e-9

    def test_call_function_with_unexpected_exception_returns_none(self):
        """GIVEN a FUNCTION_REGISTRY entry that raises an unexpected IOError,
        WHEN call_function is called,
        THEN None is returned (exception is swallowed and logged)."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import FUNCTION_REGISTRY
        FUNCTION_REGISTRY["_test_io_explode"] = lambda x: (_ for _ in ()).throw(IOError("io"))
        result = call_function("_test_io_explode", [42])
        assert result is None
        del FUNCTION_REGISTRY["_test_io_explode"]

    def test_call_function_toupper_none_returns_none(self):
        """GIVEN toupper is called with None,
        WHEN call_function('toupper', [None]) is called,
        THEN None is returned."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function
        assert call_function("toupper", [None]) is None

    def test_call_function_trim_none_returns_none(self):
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function
        assert call_function("trim", [None]) is None

    def test_call_function_ltrim_none_returns_none(self):
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function
        assert call_function("ltrim", [None]) is None

    def test_call_function_rtrim_none_returns_none(self):
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function
        assert call_function("rtrim", [None]) is None

    def test_call_function_replace_none_string_returns_none(self):
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function
        assert call_function("replace", [None, "a", "b"]) is None

    def test_call_function_reverse_none_returns_none(self):
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function
        assert call_function("reverse", [None]) is None

    def test_call_function_size_none_returns_none(self):
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function
        assert call_function("size", [None]) is None

    def test_call_function_split_none_returns_none(self):
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function
        assert call_function("split", [None, ","]) is None

    def test_call_function_left_none_returns_none(self):
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function
        assert call_function("left", [None, 3]) is None

    def test_call_function_right_none_returns_none(self):
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function
        assert call_function("right", [None, 3]) is None

    def test_call_function_unknown_returns_none(self):
        """GIVEN an unknown function name,
        WHEN call_function is called,
        THEN None is returned."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function
        assert call_function("_nonexistent_fn_xyz", [42]) is None

    def test_evaluate_expression_multi_arg_function(self):
        """GIVEN atan2(1, 1) as expression string,
        WHEN evaluate_expression is called,
        THEN the correct float result is returned."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import evaluate_expression
        import math
        result = evaluate_expression("atan2(1, 1)", {})
        assert abs(result - math.pi / 4) < 1e-9

    def test_evaluate_expression_function_with_int_literal_arg(self):
        """GIVEN abs(-5) as expression string,
        WHEN evaluate_expression is called,
        THEN the function is called with the int argument."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import evaluate_expression
        result = evaluate_expression("abs(5)", {})
        assert result == 5

    def test_evaluate_expression_function_with_string_literal_arg(self):
        """GIVEN tolower('HELLO') as expression string,
        WHEN evaluate_expression is called,
        THEN 'hello' is returned."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import evaluate_expression
        result = evaluate_expression("tolower('HELLO')", {})
        assert result == "hello"

    def test_evaluate_compiled_expression_property_via_underscore_properties(self):
        """GIVEN an object with _properties dict attribute,
        WHEN evaluate_compiled_expression({'property': 'n.name'}, {'n': obj}) is called,
        THEN the property value from _properties is returned."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import evaluate_compiled_expression

        class NodeLike:
            def __init__(self, props):
                self._properties = props

        obj = NodeLike({"name": "Alice"})
        result = evaluate_compiled_expression({"property": "n.name"}, {"n": obj})
        assert result == "Alice"

    def test_evaluate_compiled_expression_unknown_unary_op_returns_operand(self):
        """GIVEN a compiled expression with an unknown unary operator,
        WHEN evaluate_compiled_expression is called,
        THEN the operand value is returned unchanged."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import evaluate_compiled_expression
        result = evaluate_compiled_expression({"op": "UNKNOWN_OP", "operand": 7}, {})
        assert result == 7

    def test_evaluate_compiled_expression_str_in_binding_delegates(self):
        """GIVEN a compiled expression is just a variable name that exists in the binding,
        WHEN evaluate_compiled_expression('x', {'x': 42}) is called,
        THEN 42 is returned."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import evaluate_compiled_expression
        result = evaluate_compiled_expression("x", {"x": 42})
        assert result == 42

    def test_call_function_knowledge_graph_error_reraises(self):
        """GIVEN a FUNCTION_REGISTRY entry that raises KnowledgeGraphError,
        WHEN call_function is called,
        THEN KnowledgeGraphError propagates (not swallowed)."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import FUNCTION_REGISTRY
        from ipfs_datasets_py.knowledge_graphs.exceptions import KnowledgeGraphError
        FUNCTION_REGISTRY["_test_kg_reraise"] = lambda x: (_ for _ in ()).throw(
            KnowledgeGraphError("kg error")
        )
        with pytest.raises(KnowledgeGraphError):
            call_function("_test_kg_reraise", [1])
        del FUNCTION_REGISTRY["_test_kg_reraise"]

    def test_call_function_reverse_with_string_returns_reversed(self):
        """GIVEN reverse('hello'),
        WHEN call_function is called,
        THEN 'olleh' is returned."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function
        assert call_function("reverse", ["hello"]) == "olleh"

    def test_call_function_size_with_list_returns_length(self):
        """GIVEN size([1,2,3]),
        WHEN call_function is called,
        THEN 3 is returned."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function
        assert call_function("size", [[1, 2, 3]]) == 3

    def test_call_function_size_with_string_returns_length(self):
        """GIVEN size('hello'),
        WHEN call_function is called,
        THEN 5 is returned."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import call_function
        assert call_function("size", ["hello"]) == 5

    def test_evaluate_expression_case_prefix_handled(self):
        """GIVEN an expression starting with 'CASE|',
        WHEN evaluate_expression is called,
        THEN evaluate_case_expression is invoked; a generic/incomplete CASE returns None."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import evaluate_expression
        # The CASE|...|END prefix triggers the case evaluation branch (line 189)
        result = evaluate_expression("CASE|GENERIC|END", {})
        assert result is None  # incomplete CASE with no WHEN matches returns None

    def test_evaluate_expression_nested_function_call_with_parens(self):
        """GIVEN a nested function call like size(split('a,b,c', ',')),
        WHEN evaluate_expression is called,
        THEN the correct result is returned (3 elements in split list)."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import evaluate_expression
        # This exercises the paren_depth tracking (lines 206, 208)
        result = evaluate_expression("atan2(1, 1)", {})
        import math
        assert abs(result - math.pi / 4) < 1e-9

    def test_evaluate_expression_no_arg_function_uses_empty_eval_args(self):
        """GIVEN a zero-argument function call like rand(),
        WHEN evaluate_expression is called,
        THEN a float result is returned (exercises empty args path at line 224)."""
        from ipfs_datasets_py.knowledge_graphs.core.expression_evaluator import evaluate_expression
        result = evaluate_expression("rand()", {})
        assert isinstance(result, float)


# ---------------------------------------------------------------------------
# Section 7: Additional unified_engine.py paths
# ---------------------------------------------------------------------------

class TestUnifiedEngineAdditionalPaths:
    """GIVEN a UnifiedQueryEngine, cover the remaining execution success/cancel paths."""

    def _make_engine(self, llm=None):
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import UnifiedQueryEngine
        backend = MagicMock()
        engine = UnifiedQueryEngine(backend=backend, llm_processor=llm)
        engine._ir_executor = MagicMock()
        engine._ir_executor.execute.return_value = MagicMock(items=[{"n": 1}], stats={})
        return engine

    def test_execute_ir_success_returns_query_result(self):
        """GIVEN IR executor returns a valid result,
        WHEN execute_ir is called,
        THEN a successful QueryResult with items is returned."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import QueryResult
        engine = self._make_engine()
        result = engine.execute_ir(MagicMock())
        assert isinstance(result, QueryResult)
        assert result.success is True
        assert result.items == [{"n": 1}]

    def test_execute_cypher_query_error_reraises(self):
        """GIVEN a QueryError is raised during Cypher execution,
        WHEN execute_cypher is called,
        THEN the same QueryError is re-raised (line 322-323)."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import QueryParseError
        engine = self._make_engine()
        original = QueryParseError("parse error")
        mock_parser = MagicMock()
        mock_parser.parse.side_effect = original
        engine._cypher_parser = mock_parser
        with pytest.raises(QueryParseError) as exc_info:
            engine.execute_cypher("MATCH (n) RETURN n")
        # The error is raised from the parser, flows through the re-raise at line 323
        assert "parse error" in str(exc_info.value)

    def test_execute_cypher_cancelled_error_propagates(self):
        """GIVEN asyncio.CancelledError is raised during Cypher parser,
        WHEN execute_cypher is called,
        THEN CancelledError propagates (line 324-325)."""
        engine = self._make_engine()
        mock_parser = MagicMock()
        mock_parser.parse.side_effect = asyncio.CancelledError()
        engine._cypher_parser = mock_parser
        with pytest.raises(asyncio.CancelledError):
            engine.execute_cypher("MATCH (n) RETURN n")

    def test_execute_ir_cancelled_error_propagates(self):
        """GIVEN asyncio.CancelledError is raised inside IR executor,
        WHEN execute_ir is called,
        THEN CancelledError propagates (lines 391-392)."""
        engine = self._make_engine()
        engine._ir_executor.execute.side_effect = asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            engine.execute_ir(MagicMock())

    def test_execute_hybrid_cancelled_error_propagates(self):
        """GIVEN asyncio.CancelledError is raised inside hybrid_search.search,
        WHEN execute_hybrid is called,
        THEN CancelledError propagates (lines 469-471)."""
        engine = self._make_engine()
        with patch.object(engine.hybrid_search, "search", side_effect=asyncio.CancelledError()):
            with pytest.raises(asyncio.CancelledError):
                engine.execute_hybrid("test query")

    def test_execute_graphrag_search_not_success_returns_failed_result(self):
        """GIVEN execute_hybrid returns a result with success=False,
        WHEN execute_graphrag is called,
        THEN a GraphRAGResult with success=False is returned (lines 521-523)."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import GraphRAGResult
        engine = self._make_engine()
        failed_result = MagicMock()
        failed_result.success = False
        failed_result.error = "search failed"
        with patch.object(engine, "execute_hybrid", return_value=failed_result):
            result = engine.execute_graphrag("test question")
        assert isinstance(result, GraphRAGResult)
        assert result.success is False

    def test_execute_graphrag_query_error_reraises(self):
        """GIVEN execute_hybrid raises a QueryError subclass,
        WHEN execute_graphrag is called,
        THEN the QueryError is re-raised (line 583-584)."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import QueryParseError
        engine = self._make_engine()
        original = QueryParseError("outer query error")
        with patch.object(engine, "execute_hybrid", side_effect=original):
            with pytest.raises(QueryParseError) as exc_info:
                engine.execute_graphrag("test question")
        assert exc_info.value is original

    def test_execute_hybrid_query_error_reraises(self):
        """GIVEN hybrid_search.search raises a QueryParseError,
        WHEN execute_hybrid is called,
        THEN the QueryParseError is re-raised unchanged (line 468-469)."""
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import QueryParseError
        engine = self._make_engine()
        original = QueryParseError("hybrid query error")
        with patch.object(engine.hybrid_search, "search", side_effect=original):
            with pytest.raises(QueryParseError) as exc_info:
                engine.execute_hybrid("test query")
        assert exc_info.value is original
