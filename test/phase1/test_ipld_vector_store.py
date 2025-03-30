"""
Test IPLD Vector Store Module

This module contains tests for the IPLDVectorStore class which implements
IPLD-based vector storage with similarity search capabilities.
"""

import os
import numpy as np
import tempfile
import shutil
import unittest
from typing import List, Dict, Any

from ipfs_datasets_py.ipld import IPLDStorage, IPLDVectorStore, SearchResult

class TestIPLDVectorStore(unittest.TestCase):
    """Test cases for the IPLDVectorStore class."""
    
    def setUp(self):
        """Set up test environment."""
        # Create temporary directory for test data
        self.temp_dir = tempfile.mkdtemp()
        
        # Create a simple IPLD storage
        self.storage = IPLDStorage()
        
        # Create a small test vector store
        self.vector_store = IPLDVectorStore(
            dimension=10,
            metric="cosine",
            storage=self.storage
        )
        
        # Create some test vectors
        self.test_vectors = [
            np.array([1, 0, 0, 0, 0, 0, 0, 0, 0, 0], dtype=np.float32),
            np.array([0, 1, 0, 0, 0, 0, 0, 0, 0, 0], dtype=np.float32),
            np.array([0, 0, 1, 0, 0, 0, 0, 0, 0, 0], dtype=np.float32),
            np.array([0, 0, 0, 1, 0, 0, 0, 0, 0, 0], dtype=np.float32),
            np.array([0, 0, 0, 0, 1, 0, 0, 0, 0, 0], dtype=np.float32),
        ]
        
        # Create metadata for test vectors
        self.test_metadata = [
            {"id": "v1", "name": "Vector 1", "category": "test"},
            {"id": "v2", "name": "Vector 2", "category": "test"},
            {"id": "v3", "name": "Vector 3", "category": "example"},
            {"id": "v4", "name": "Vector 4", "category": "example"},
            {"id": "v5", "name": "Vector 5", "category": "test"},
        ]
        
    def tearDown(self):
        """Clean up after tests."""
        # Clean up temp directory
        shutil.rmtree(self.temp_dir)
    
    def test_add_vectors(self):
        """Test adding vectors to the store."""
        # Add test vectors
        vector_ids = self.vector_store.add_vectors(
            self.test_vectors,
            self.test_metadata
        )
        
        # Check if we got the correct number of IDs
        self.assertEqual(len(vector_ids), len(self.test_vectors))
        
        # Check if the vector store has the correct count
        self.assertEqual(len(self.vector_store), len(self.test_vectors))
        
        # Check if we can retrieve the vectors by ID
        for i, vector_id in enumerate(vector_ids):
            # Get vector
            vector = self.vector_store.get_vector(vector_id)
            self.assertIsNotNone(vector)
            
            # Check if vector is approximately equal to the original
            # (allowing for normalization differences)
            np.testing.assert_allclose(
                vector / np.linalg.norm(vector),
                self.test_vectors[i] / np.linalg.norm(self.test_vectors[i]),
                rtol=1e-5
            )
            
            # Get metadata
            metadata = self.vector_store.get_metadata(vector_id)
            self.assertEqual(metadata, self.test_metadata[i])
    
    def test_search_cosine(self):
        """Test vector search with cosine similarity."""
        # Add test vectors
        vector_ids = self.vector_store.add_vectors(
            self.test_vectors,
            self.test_metadata
        )
        
        # Create a query vector that should be closest to the first test vector
        query_vector = np.array([0.9, 0.1, 0, 0, 0, 0, 0, 0, 0, 0], dtype=np.float32)
        
        # Search for similar vectors
        results = self.vector_store.search(query_vector, top_k=3)
        
        # Check if we got the correct number of results
        self.assertEqual(len(results), 3)
        
        # Check if the first result is the closest one
        self.assertEqual(results[0].id, vector_ids[0])
        
        # Check if the second result is the second closest one
        self.assertEqual(results[1].id, vector_ids[1])
    
    def test_search_l2(self):
        """Test vector search with L2 distance."""
        # Create a vector store with L2 metric
        l2_store = IPLDVectorStore(
            dimension=10,
            metric="l2",
            storage=self.storage
        )
        
        # Add test vectors
        vector_ids = l2_store.add_vectors(
            self.test_vectors,
            self.test_metadata
        )
        
        # Create a query vector that should be closest to the first test vector
        query_vector = np.array([0.9, 0.1, 0, 0, 0, 0, 0, 0, 0, 0], dtype=np.float32)
        
        # Search for similar vectors
        results = l2_store.search(query_vector, top_k=3)
        
        # Check if we got the correct number of results
        self.assertEqual(len(results), 3)
        
        # Check if the first result is the closest one
        self.assertEqual(results[0].id, vector_ids[0])
    
    def test_update_metadata(self):
        """Test updating metadata for a vector."""
        # Add test vectors
        vector_ids = self.vector_store.add_vectors(
            self.test_vectors,
            self.test_metadata
        )
        
        # Update metadata for the first vector
        new_metadata = {
            "id": "v1-updated",
            "name": "Updated Vector 1",
            "category": "updated",
            "new_field": "new value"
        }
        
        result = self.vector_store.update_metadata(vector_ids[0], new_metadata)
        self.assertTrue(result)
        
        # Check if the metadata was updated
        updated_metadata = self.vector_store.get_metadata(vector_ids[0])
        self.assertEqual(updated_metadata, new_metadata)
    
    def test_delete_vectors(self):
        """Test deleting vectors from the store."""
        # Add test vectors
        vector_ids = self.vector_store.add_vectors(
            self.test_vectors,
            self.test_metadata
        )
        
        # Get initial count
        initial_count = len(self.vector_store)
        
        # Delete the first two vectors
        vectors_to_delete = vector_ids[:2]
        result = self.vector_store.delete_vectors(vectors_to_delete)
        self.assertTrue(result)
        
        # Check if the count was updated
        self.assertEqual(len(self.vector_store), initial_count - len(vectors_to_delete))
        
        # Check if the deleted vectors are no longer retrievable
        for vector_id in vectors_to_delete:
            vector = self.vector_store.get_vector(vector_id)
            self.assertIsNone(vector)
            
            metadata = self.vector_store.get_metadata(vector_id)
            self.assertIsNone(metadata)
    
    def test_export_import_car(self):
        """Test exporting and importing using CAR files."""
        # Skip if ipld_car is not available
        try:
            import ipld_car
        except ImportError:
            self.skipTest("ipld_car is not available")
        
        # Add test vectors
        original_vector_ids = self.vector_store.add_vectors(
            self.test_vectors,
            self.test_metadata
        )
        
        # Define CAR file path
        car_path = os.path.join(self.temp_dir, "test_vectors.car")
        
        # Export to CAR file
        root_cid = self.vector_store.export_to_car(car_path)
        self.assertIsNotNone(root_cid)
        self.assertTrue(os.path.exists(car_path))
        
        # Import from CAR file
        imported_store = IPLDVectorStore.from_car(car_path)
        
        # Check if the imported store has the same vectors
        self.assertEqual(len(imported_store), len(self.test_vectors))
        
        # Test search on the imported store
        query_vector = np.array([0.9, 0.1, 0, 0, 0, 0, 0, 0, 0, 0], dtype=np.float32)
        results = imported_store.search(query_vector, top_k=3)
        
        # Check if we got the correct number of results
        self.assertEqual(len(results), 3)
        
        # Check if the first result has the expected metadata
        self.assertEqual(results[0].metadata["id"], "v1")
    
    def test_filter_search(self):
        """Test search with filtering."""
        # Add test vectors
        vector_ids = self.vector_store.add_vectors(
            self.test_vectors,
            self.test_metadata
        )
        
        # Create a query vector
        query_vector = np.array([0.2, 0.2, 0.2, 0.2, 0.2, 0, 0, 0, 0, 0], dtype=np.float32)
        
        # Create a filter function that only includes vectors in the "test" category
        def filter_test_category(metadata):
            return metadata.get("category") == "test"
        
        # Search with filter
        results = self.vector_store.search(
            query_vector,
            top_k=5,
            filter_fn=filter_test_category
        )
        
        # Check if all results have the "test" category
        for result in results:
            self.assertEqual(result.metadata["category"], "test")
        
        # Check if we don't have results from the "example" category
        for result in results:
            self.assertNotEqual(result.metadata["category"], "example")

if __name__ == "__main__":
    unittest.main()