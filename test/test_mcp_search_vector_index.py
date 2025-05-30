import unittest
import asyncio
import os
import sys
from unittest.mock import patch, MagicMock

# Add the parent directory to the path to ensure imports work correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class MockVectorDB:
    def search_index(self, index_name, query_vector, top_k):
        if index_name == "test_index" and query_vector == [0.1, 0.2] and top_k == 5:
            return [{"id": "doc1", "score": 0.9}, {"id": "doc2", "score": 0.8}]
        raise Exception("Failed to search index in mock DB")

class TestMCPSearchVectorIndex(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.mock_vector_db = MockVectorDB()
        self.patcher = patch('ipfs_datasets_py.vector_tools.vector_db.VectorDB', return_value=self.mock_vector_db)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    async def test_search_vector_index_success(self):
        from ipfs_datasets_py.mcp_server.tools.vector_tools.search_vector_index import search_vector_index

        index_name = "test_index"
        query_vector = [0.1, 0.2]
        top_k = 5

        result = await search_vector_index(index_name=index_name, query_vector=query_vector, top_k=top_k)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["index_name"], index_name)
        self.assertEqual(result["top_k"], top_k)
        self.assertEqual(len(result["results"]), 2)
        self.assertEqual(result["results"][0]["id"], "doc1")
        self.assertEqual(result["results"][0]["score"], 0.9)

    async def test_search_vector_index_failure(self):
        from ipfs_datasets_py.mcp_server.tools.vector_tools.search_vector_index import search_vector_index

        index_name = "fail_index"
        query_vector = [0.1, 0.2]
        top_k = 5
        self.mock_vector_db.search_index = MagicMock(side_effect=Exception("Search failed"))

        result = await search_vector_index(index_name=index_name, query_vector=query_vector, top_k=top_k)

        self.assertEqual(result["status"], "error")
        self.assertIn("Search failed", result["message"])
        self.assertEqual(result["index_name"], index_name)
        self.assertEqual(result["top_k"], top_k)

if __name__ == '__main__':
    unittest.main()
