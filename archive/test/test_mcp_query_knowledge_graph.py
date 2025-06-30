import unittest
import asyncio
import os
import sys
from unittest.mock import patch, MagicMock

# Add the parent directory to the path to ensure imports work correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class MockGraph:
    def __init__(self, graph_id):
        self.graph_id = graph_id

class MockGraphRAGProcessor:
    def load_graph(self, graph_id):
        if graph_id == "test_graph":
            return MockGraph(graph_id)
        raise ValueError(f"Graph {graph_id} not found")

    def execute_sparql(self, graph, query, limit):
        if query == "SELECT * WHERE {?s ?p ?o} LIMIT 10":
            return [{"s": "node1", "p": "has_type", "o": "TypeA"}]
        return []

    def execute_cypher(self, graph, query, limit):
        if query == "MATCH (n) RETURN n LIMIT 10":
            return [{"n": {"id": "node1", "label": "TypeA"}}]
        return []

    def execute_gremlin(self, graph, query, limit):
        if query == "g.V().limit(10)":
            return [{"id": "node1", "label": "TypeA"}]
        return []

    def execute_semantic_query(self, graph, query, limit):
        if query == "find all TypeA nodes":
            return [{"id": "node1", "label": "TypeA", "semantic_score": 0.9}]
        return []

@patch('ipfs_datasets_py.rag_query_optimizer.GraphRAGProcessor', new=MockGraphRAGProcessor)
class TestMCPQueryKnowledgeGraph(unittest.IsolatedAsyncioTestCase):

    async def test_query_knowledge_graph_sparql_success(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.query_knowledge_graph import query_knowledge_graph

        graph_id = "test_graph"
        query = "SELECT * WHERE {?s ?p ?o} LIMIT 10"
        query_type = "sparql"

        result = await query_knowledge_graph(graph_id=graph_id, query=query, query_type=query_type)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["graph_id"], graph_id)
        self.assertEqual(result["query_type"], query_type)
        self.assertEqual(result["num_results"], 1)
        self.assertEqual(result["results"][0]["s"], "node1")

    async def test_query_knowledge_graph_cypher_success(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.query_knowledge_graph import query_knowledge_graph

        graph_id = "test_graph"
        query = "MATCH (n) RETURN n LIMIT 10"
        query_type = "cypher"

        result = await query_knowledge_graph(graph_id=graph_id, query=query, query_type=query_type)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["graph_id"], graph_id)
        self.assertEqual(result["query_type"], query_type)
        self.assertEqual(result["num_results"], 1)
        self.assertEqual(result["results"][0]["n"]["id"], "node1")

    async def test_query_knowledge_graph_gremlin_success(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.query_knowledge_graph import query_knowledge_graph

        graph_id = "test_graph"
        query = "g.V().limit(10)"
        query_type = "gremlin"

        result = await query_knowledge_graph(graph_id=graph_id, query=query, query_type=query_type)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["graph_id"], graph_id)
        self.assertEqual(result["query_type"], query_type)
        self.assertEqual(result["num_results"], 1)
        self.assertEqual(result["results"][0]["id"], "node1")

    async def test_query_knowledge_graph_semantic_success(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.query_knowledge_graph import query_knowledge_graph

        graph_id = "test_graph"
        query = "find all TypeA nodes"
        query_type = "semantic"

        result = await query_knowledge_graph(graph_id=graph_id, query=query, query_type=query_type)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["graph_id"], graph_id)
        self.assertEqual(result["query_type"], query_type)
        self.assertEqual(result["num_results"], 1)
        self.assertEqual(result["results"][0]["id"], "node1")

    async def test_query_knowledge_graph_unsupported_query_type(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.query_knowledge_graph import query_knowledge_graph

        graph_id = "test_graph"
        query = "some query"
        query_type = "unsupported"

        result = await query_knowledge_graph(graph_id=graph_id, query=query, query_type=query_type)

        self.assertEqual(result["status"], "error")
        self.assertIn("Unsupported query type", result["message"])
        self.assertEqual(result["graph_id"], graph_id)

    async def test_query_knowledge_graph_error_handling(self):
        from ipfs_datasets_py.mcp_server.tools.graph_tools.query_knowledge_graph import query_knowledge_graph

        # Simulate an error during graph loading
        with patch('ipfs_datasets_py.rag_query_optimizer.GraphRAGProcessor.load_graph', side_effect=Exception("Graph load error")):
            result = await query_knowledge_graph(graph_id="error_graph", query="query", query_type="sparql")
            self.assertEqual(result["status"], "error")
            self.assertIn("Graph load error", result["message"])
            self.assertEqual(result["graph_id"], "error_graph")

if __name__ == '__main__':
    unittest.main()
