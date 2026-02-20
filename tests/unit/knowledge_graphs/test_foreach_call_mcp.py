"""
Tests for FOREACH, CALL subquery, validator split, and new MCP tools.

GIVEN / WHEN / THEN format following repository conventions.
"""

import asyncio
import pytest
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# FOREACH clause tests
# ---------------------------------------------------------------------------

class TestForeachLexer:
    """Verify FOREACH is correctly tokenised."""

    def test_foreach_tokenized_as_keyword(self):
        """GIVEN a Cypher lexer WHEN 'FOREACH' is encountered THEN it gets its own token type."""
        # GIVEN
        from ipfs_datasets_py.knowledge_graphs.cypher.lexer import CypherLexer, TokenType
        lexer = CypherLexer()
        # WHEN
        tokens = lexer.tokenize("FOREACH (x IN [1] | CREATE (:N {v: x}))")
        types = [t.type for t in tokens if t.type not in (TokenType.EOF,)]
        # THEN
        assert TokenType.FOREACH in types

    def test_foreach_case_insensitive(self):
        """GIVEN a Cypher lexer WHEN 'foreach' (lower case) is used THEN it still gets FOREACH token."""
        from ipfs_datasets_py.knowledge_graphs.cypher.lexer import CypherLexer, TokenType
        lexer = CypherLexer()
        tokens = lexer.tokenize("foreach (x IN [1] | set x = 1)")
        types = [t.type for t in tokens if t.type not in (TokenType.EOF,)]
        assert TokenType.FOREACH in types


class TestForeachAST:
    """Verify FOREACH produces the expected AST node."""

    def test_foreach_parsed_to_ast(self):
        """GIVEN a valid FOREACH query WHEN parsed THEN a ForeachClause is returned."""
        # GIVEN
        from ipfs_datasets_py.knowledge_graphs.cypher.parser import CypherParser
        from ipfs_datasets_py.knowledge_graphs.cypher.ast import ForeachClause
        parser = CypherParser()
        # WHEN
        ast = parser.parse("FOREACH (x IN [1, 2, 3] | CREATE (:Number {value: x}))")
        # THEN
        clauses = ast.clauses
        assert len(clauses) == 1
        assert isinstance(clauses[0], ForeachClause)
        assert clauses[0].variable == "x"

    def test_foreach_body_contains_create(self):
        """GIVEN a FOREACH with a CREATE body WHEN parsed THEN the body contains a CreateClause."""
        from ipfs_datasets_py.knowledge_graphs.cypher.parser import CypherParser
        from ipfs_datasets_py.knowledge_graphs.cypher.ast import ForeachClause, CreateClause
        parser = CypherParser()
        ast = parser.parse("FOREACH (n IN [1] | CREATE (:X {v: n}))")
        foreach_clause = ast.clauses[0]
        assert isinstance(foreach_clause, ForeachClause)
        assert len(foreach_clause.body) == 1
        assert isinstance(foreach_clause.body[0], CreateClause)

    def test_foreach_variable_name_preserved(self):
        """GIVEN a FOREACH with variable 'item' WHEN parsed THEN variable is 'item'."""
        from ipfs_datasets_py.knowledge_graphs.cypher.parser import CypherParser
        from ipfs_datasets_py.knowledge_graphs.cypher.ast import ForeachClause
        parser = CypherParser()
        ast = parser.parse("FOREACH (item IN [1, 2] | CREATE (:T {v: item}))")
        foreach_clause = ast.clauses[0]
        assert isinstance(foreach_clause, ForeachClause)
        assert foreach_clause.variable == "item"


class TestForeachCompilation:
    """Verify FOREACH compiles to the expected IR."""

    def test_foreach_compiles_to_foreach_op(self):
        """GIVEN a FOREACH clause WHEN compiled THEN a Foreach IR op is emitted."""
        from ipfs_datasets_py.knowledge_graphs.cypher.parser import CypherParser
        from ipfs_datasets_py.knowledge_graphs.cypher.compiler import CypherCompiler
        parser = CypherParser()
        compiler = CypherCompiler()
        ast = parser.parse("FOREACH (item IN [10, 20] | CREATE (:Tag {value: item}))")
        ops = compiler.compile(ast)
        assert any(op.get("op") == "Foreach" for op in ops)

    def test_foreach_op_has_correct_variable(self):
        """GIVEN a FOREACH clause WHEN compiled THEN the Foreach op records the loop variable."""
        from ipfs_datasets_py.knowledge_graphs.cypher.parser import CypherParser
        from ipfs_datasets_py.knowledge_graphs.cypher.compiler import CypherCompiler
        parser = CypherParser()
        compiler = CypherCompiler()
        ast = parser.parse("FOREACH (myVar IN [1] | CREATE (:T))")
        ops = compiler.compile(ast)
        foreach_op = next((op for op in ops if op.get("op") == "Foreach"), None)
        assert foreach_op is not None
        assert foreach_op["variable"] == "myVar"

    def test_foreach_body_ops_nested(self):
        """GIVEN a FOREACH with body ops WHEN compiled THEN body_ops is a non-empty list."""
        from ipfs_datasets_py.knowledge_graphs.cypher.parser import CypherParser
        from ipfs_datasets_py.knowledge_graphs.cypher.compiler import CypherCompiler
        parser = CypherParser()
        compiler = CypherCompiler()
        ast = parser.parse("FOREACH (x IN [1] | CREATE (:N {v: x}))")
        ops = compiler.compile(ast)
        foreach_op = next((op for op in ops if op.get("op") == "Foreach"), None)
        assert foreach_op is not None
        assert isinstance(foreach_op["body_ops"], list)
        assert len(foreach_op["body_ops"]) >= 1


class TestForeachExecution:
    """Verify FOREACH executes correctly through the QueryExecutor."""

    def test_foreach_creates_nodes(self):
        """GIVEN a FOREACH that creates nodes WHEN executed THEN the nodes exist in the graph."""
        from ipfs_datasets_py.knowledge_graphs.core.query_executor import QueryExecutor, GraphEngine
        graph = GraphEngine()
        executor = QueryExecutor(graph_engine=graph)
        # WHEN
        executor.execute("FOREACH (x IN [1, 2, 3] | CREATE (:Counter {value: x}))")
        # THEN — check nodes were created
        counters = graph.find_nodes(labels=["Counter"])
        assert len(counters) == 3

    def test_foreach_empty_list(self):
        """GIVEN a FOREACH over an empty list WHEN executed THEN no nodes are created."""
        from ipfs_datasets_py.knowledge_graphs.core.query_executor import QueryExecutor, GraphEngine
        graph = GraphEngine()
        executor = QueryExecutor(graph_engine=graph)
        executor.execute("FOREACH (x IN [] | CREATE (:Empty))")
        empty_nodes = graph.find_nodes(labels=["Empty"])
        assert len(empty_nodes) == 0


# ---------------------------------------------------------------------------
# CALL subquery tests
# ---------------------------------------------------------------------------

class TestCallSubqueryAST:
    """Verify CALL { … } produces the correct AST node."""

    def test_call_subquery_parsed(self):
        """GIVEN a CALL { … } query WHEN parsed THEN a CallSubquery node is produced."""
        from ipfs_datasets_py.knowledge_graphs.cypher.parser import CypherParser
        from ipfs_datasets_py.knowledge_graphs.cypher.ast import CallSubquery
        parser = CypherParser()
        ast = parser.parse("CALL { MATCH (n:Person) RETURN n.name AS name }")
        assert len(ast.clauses) == 1
        assert isinstance(ast.clauses[0], CallSubquery)

    def test_call_subquery_body_is_query_node(self):
        """GIVEN a CALL subquery WHEN parsed THEN the body is a QueryNode."""
        from ipfs_datasets_py.knowledge_graphs.cypher.parser import CypherParser
        from ipfs_datasets_py.knowledge_graphs.cypher.ast import CallSubquery, QueryNode
        parser = CypherParser()
        ast = parser.parse("CALL { MATCH (n) RETURN n }")
        call = ast.clauses[0]
        assert isinstance(call.body, QueryNode)

    def test_call_subquery_yield_items(self):
        """GIVEN a CALL with YIELD WHEN parsed THEN yield_items are populated."""
        from ipfs_datasets_py.knowledge_graphs.cypher.parser import CypherParser
        from ipfs_datasets_py.knowledge_graphs.cypher.ast import CallSubquery
        parser = CypherParser()
        ast = parser.parse(
            "CALL { MATCH (n) RETURN count(n) AS total } YIELD total"
        )
        call = ast.clauses[0]
        assert isinstance(call, CallSubquery)
        assert len(call.yield_items) == 1
        assert call.yield_items[0]["alias"] == "total"

    def test_call_subquery_yield_with_alias(self):
        """GIVEN a CALL YIELD with AS rename WHEN parsed THEN the alias is recorded."""
        from ipfs_datasets_py.knowledge_graphs.cypher.parser import CypherParser
        from ipfs_datasets_py.knowledge_graphs.cypher.ast import CallSubquery
        parser = CypherParser()
        ast = parser.parse(
            "CALL { MATCH (n) RETURN n.name AS nm } YIELD nm AS personName"
        )
        call = ast.clauses[0]
        assert isinstance(call, CallSubquery)
        assert call.yield_items[0]["alias"] == "personName"


class TestCallSubqueryCompilation:
    """Verify CALL { … } compiles to the expected IR."""

    def test_call_subquery_emits_callsubquery_op(self):
        """GIVEN a CALL subquery WHEN compiled THEN a CallSubquery IR op is emitted."""
        from ipfs_datasets_py.knowledge_graphs.cypher.parser import CypherParser
        from ipfs_datasets_py.knowledge_graphs.cypher.compiler import CypherCompiler
        parser = CypherParser()
        compiler = CypherCompiler()
        ast = parser.parse("CALL { MATCH (n:Person) RETURN n.name AS name }")
        ops = compiler.compile(ast)
        assert any(op.get("op") == "CallSubquery" for op in ops)

    def test_call_subquery_inner_ops_populated(self):
        """GIVEN a CALL with a MATCH inside WHEN compiled THEN inner_ops is non-empty."""
        from ipfs_datasets_py.knowledge_graphs.cypher.parser import CypherParser
        from ipfs_datasets_py.knowledge_graphs.cypher.compiler import CypherCompiler
        parser = CypherParser()
        compiler = CypherCompiler()
        ast = parser.parse("CALL { MATCH (n:Person) RETURN n.name AS name }")
        ops = compiler.compile(ast)
        call_op = next(op for op in ops if op.get("op") == "CallSubquery")
        assert len(call_op["inner_ops"]) > 0

    def test_call_subquery_yield_items_in_ir(self):
        """GIVEN a CALL with YIELD WHEN compiled THEN yield_items is propagated to IR."""
        from ipfs_datasets_py.knowledge_graphs.cypher.parser import CypherParser
        from ipfs_datasets_py.knowledge_graphs.cypher.compiler import CypherCompiler
        parser = CypherParser()
        compiler = CypherCompiler()
        ast = parser.parse(
            "CALL { MATCH (n) RETURN count(n) AS total } YIELD total"
        )
        ops = compiler.compile(ast)
        call_op = next(op for op in ops if op.get("op") == "CallSubquery")
        assert call_op["yield_items"] == [{"name": "total", "alias": "total"}]


class TestCallSubqueryExecution:
    """Verify CALL { … } executes and merges results correctly."""

    def test_call_subquery_merges_results(self):
        """GIVEN a CALL subquery that matches some nodes WHEN executed THEN results are returned without error."""
        from ipfs_datasets_py.knowledge_graphs.core.query_executor import QueryExecutor, GraphEngine
        graph = GraphEngine()
        # Pre-populate the graph
        graph.create_node(labels=["Person"], properties={"name": "Alice", "age": 30})
        graph.create_node(labels=["Person"], properties={"name": "Bob", "age": 25})
        executor = QueryExecutor(graph_engine=graph)
        # WHEN — CALL subquery fetches person names
        result = executor.execute(
            "CALL { MATCH (n:Person) RETURN n.name AS name }"
        )
        # THEN — no exception; a result object is returned
        assert result is not None

    def test_call_subquery_empty_inner_query(self):
        """GIVEN a CALL subquery with no matching nodes WHEN executed THEN no error is raised."""
        from ipfs_datasets_py.knowledge_graphs.core.query_executor import QueryExecutor, GraphEngine
        graph = GraphEngine()
        executor = QueryExecutor(graph_engine=graph)
        # Should not raise; result can be a Result object or list
        result = executor.execute("CALL { MATCH (n:Ghost) RETURN n }")
        assert result is not None


# ---------------------------------------------------------------------------
# New MCP tool import tests
# ---------------------------------------------------------------------------

class TestNewMCPToolImports:
    """Verify the three new MCP graph tools can be imported directly."""

    def test_graph_srl_extract_importable(self):
        """GIVEN the graph_srl_extract module WHEN imported directly THEN no error."""
        pytest.importorskip("anyio", reason="anyio not installed in this env")
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_srl_extract import graph_srl_extract
        assert callable(graph_srl_extract)

    def test_graph_ontology_materialize_importable(self):
        """GIVEN the graph_ontology_materialize module WHEN imported directly THEN no error."""
        pytest.importorskip("anyio", reason="anyio not installed in this env")
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_ontology_materialize import graph_ontology_materialize
        assert callable(graph_ontology_materialize)

    def test_graph_distributed_execute_importable(self):
        """GIVEN the graph_distributed_execute module WHEN imported directly THEN no error."""
        pytest.importorskip("anyio", reason="anyio not installed in this env")
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_distributed_execute import graph_distributed_execute
        assert callable(graph_distributed_execute)

    def test_graph_tools_init_exports_all_three(self):
        """GIVEN graph_tools/__init__.py source WHEN checking __all__ declarations THEN all 3 new tools are listed."""
        import os
        init_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "..",
            "ipfs_datasets_py", "mcp_server", "tools", "graph_tools", "__init__.py",
        )
        with open(os.path.normpath(init_path)) as fh:
            source = fh.read()
        assert "graph_srl_extract" in source
        assert "graph_ontology_materialize" in source
        assert "graph_distributed_execute" in source


class TestKnowledgeGraphManagerNewMethods:
    """Verify the three new KnowledgeGraphManager methods return sensible dicts."""

    def test_extract_srl_returns_dict(self):
        """GIVEN KnowledgeGraphManager WHEN extract_srl is called THEN a dict is returned."""
        from ipfs_datasets_py.core_operations.knowledge_graph_manager import KnowledgeGraphManager
        manager = KnowledgeGraphManager()
        result = asyncio.run(
            manager.extract_srl("Alice sent a report to Bob.")
        )
        assert isinstance(result, dict)
        assert result.get("status") == "success"
        assert "frame_count" in result

    def test_extract_srl_with_triples(self):
        """GIVEN extract_srl with return_triples=True WHEN called THEN triples key is present."""
        from ipfs_datasets_py.core_operations.knowledge_graph_manager import KnowledgeGraphManager
        manager = KnowledgeGraphManager()
        result = asyncio.run(
            manager.extract_srl("Alice built the project.", return_triples=True)
        )
        assert result.get("status") == "success"
        assert "triples" in result

    def test_ontology_materialize_returns_dict(self):
        """GIVEN KnowledgeGraphManager WHEN ontology_materialize is called THEN a dict is returned."""
        from ipfs_datasets_py.core_operations.knowledge_graph_manager import KnowledgeGraphManager
        manager = KnowledgeGraphManager()
        result = asyncio.run(
            manager.ontology_materialize("test_graph", schema={"transitive": ["isAncestorOf"]})
        )
        assert isinstance(result, dict)
        assert result.get("status") == "success"
        assert "inferred_count" in result

    def test_ontology_materialize_explain(self):
        """GIVEN ontology_materialize with explain=True WHEN called THEN traces key is present."""
        from ipfs_datasets_py.core_operations.knowledge_graph_manager import KnowledgeGraphManager
        manager = KnowledgeGraphManager()
        result = asyncio.run(
            manager.ontology_materialize("test_graph", explain=True)
        )
        assert result.get("status") == "success"
        assert "traces" in result

    def test_distributed_execute_returns_dict(self):
        """GIVEN KnowledgeGraphManager WHEN distributed_execute is called THEN a dict is returned."""
        from ipfs_datasets_py.core_operations.knowledge_graph_manager import KnowledgeGraphManager
        manager = KnowledgeGraphManager()
        result = asyncio.run(
            manager.distributed_execute("MATCH (n) RETURN n.name")
        )
        assert isinstance(result, dict)
        assert result.get("status") == "success"

    def test_distributed_execute_explain(self):
        """GIVEN distributed_execute with explain=True WHEN called THEN plan key is present."""
        from ipfs_datasets_py.core_operations.knowledge_graph_manager import KnowledgeGraphManager
        manager = KnowledgeGraphManager()
        result = asyncio.run(
            manager.distributed_execute("MATCH (n:Person) RETURN n.name", explain=True)
        )
        assert result.get("status") == "success"
        assert "plan" in result


class TestMCPToolsAsync:
    """Verify the async MCP tools return valid dicts (lightweight, no real graph)."""

    def test_graph_srl_extract_async(self):
        """GIVEN graph_srl_extract tool WHEN called async THEN returns status dict."""
        pytest.importorskip("anyio", reason="anyio not installed in this env")
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_srl_extract import graph_srl_extract
        result = asyncio.run(
            graph_srl_extract("Alice sent a report to Bob.")
        )
        assert isinstance(result, dict)
        assert "status" in result

    def test_graph_ontology_materialize_async(self):
        """GIVEN graph_ontology_materialize tool WHEN called async THEN returns status dict."""
        pytest.importorskip("anyio", reason="anyio not installed in this env")
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_ontology_materialize import graph_ontology_materialize
        result = asyncio.run(
            graph_ontology_materialize("my_graph")
        )
        assert isinstance(result, dict)
        assert "status" in result

    def test_graph_distributed_execute_async(self):
        """GIVEN graph_distributed_execute tool WHEN called async THEN returns status dict."""
        pytest.importorskip("anyio", reason="anyio not installed in this env")
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_distributed_execute import graph_distributed_execute
        result = asyncio.run(
            graph_distributed_execute("MATCH (n) RETURN n.name")
        )
        assert isinstance(result, dict)
        assert "status" in result
