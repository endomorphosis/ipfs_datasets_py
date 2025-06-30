import unittest
import asyncio
import os
import sys
from unittest.mock import patch, MagicMock

# Add the parent directory to the path to ensure imports work correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class MockIPFSKnnIndex:
    def __init__(self, dimension, metric):
        self.dimension = dimension
        self.metric = metric
        self.index_id = "mock_index_id"
        self.index_name = None

    def add_vectors(self, vectors, metadata=None):
        if self.dimension == 128 and len(vectors) > 0:
            return [f"vec_{i}" for i in range(len(vectors))]
        raise Exception("Failed to add vectors in mock IPFSKnnIndex")

class TestMCPCreateVectorIndex(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.mock_ipfs_knn_index = MockIPFSKnnIndex(dimension=128, metric="cosine")
        self.patcher = patch('ipfs_datasets_py.ipfs_knn_index.IPFSKnnIndex', return_value=self.mock_ipfs_knn_index)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    async def test_create_vector_index_success(self):
        from ipfs_datasets_py.mcp_server.tools.vector_tools.create_vector_index import create_vector_index

        vectors = [[0.1]*128, [0.2]*128]
        dimension = 128

        result = await create_vector_index(vectors=vectors, dimension=dimension)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["index_id"], "mock_index_id")
        self.assertEqual(result["num_vectors"], len(vectors))
        self.assertEqual(result["dimension"], dimension)
        self.assertEqual(result["metric"], "cosine")
        self.assertEqual(result["vector_ids"], ["vec_0", "vec_1"])

    async def test_create_vector_index_failure(self):
        from ipfs_datasets_py.mcp_server.tools.vector_tools.create_vector_index import create_vector_index

        vectors = [[0.1]*128]
        dimension = 128
        self.mock_ipfs_knn_index.add_vectors = MagicMock(side_effect=Exception("Vector addition failed"))

        result = await create_vector_index(vectors=vectors, dimension=dimension)

        self.assertEqual(result["status"], "error")
        self.assertIn("Vector addition failed", result["message"])

if __name__ == '__main__':
    unittest.main()
