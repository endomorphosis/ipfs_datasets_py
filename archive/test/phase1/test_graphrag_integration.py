"""
Test GraphRAG Integration Module

This module contains tests for the GraphRAG integration, combining
vector search, knowledge graph traversal, and LLM-enhanced reasoning.
"""

import os
import numpy as np
import tempfile
import shutil
import unittest
from unittest.mock import MagicMock, patch
from typing import List, Dict, Any

from ipfs_datasets_py.ipld import (
    IPLDStorage, IPLDVectorStore, IPLDKnowledgeGraph,
    Entity, Relationship
)
from ipfs_datasets_py.graphrag_integration import (
    GraphRAGFactory, HybridVectorGraphSearch, GraphRAGQueryEngine,
    CrossDocumentReasoner
)
from ipfs_datasets_py.rag.rag_query_optimizer import UnifiedGraphRAGQueryOptimizer
from ipfs_datasets_py.examples.graphrag_example import GraphRAGDemo

class TestGraphRAGIntegration(unittest.TestCase):
    """Test cases for the GraphRAG integration."""

    def setUp(self):
        """Set up test environment."""
        # Create temporary directory for test data
        self.temp_dir = tempfile.mkdtemp()

        # Create a smaller dimension for testing
        self.dimension = 64

        # Create IPLD storage
        self.storage = IPLDStorage()

        # Create vector store
        self.vector_store = IPLDVectorStore(
            dimension=self.dimension,
            metric="cosine",
            storage=self.storage
        )

        # Create knowledge graph
        self.kg = IPLDKnowledgeGraph(
            name="test_graph",
            storage=self.storage,
            vector_store=self.vector_store
        )

        # Create test vectors
        self.test_vectors = [
            np.array([1.0, 0.0, 0.0] + [0.0] * (self.dimension - 3), dtype=np.float32),
            np.array([0.0, 1.0, 0.0] + [0.0] * (self.dimension - 3), dtype=np.float32),
            np.array([0.0, 0.0, 1.0] + [0.0] * (self.dimension - 3), dtype=np.float32),
            np.array([0.5, 0.5, 0.0] + [0.0] * (self.dimension - 3), dtype=np.float32),
            np.array([0.0, 0.5, 0.5] + [0.0] * (self.dimension - 3), dtype=np.float32),
        ]

        # Create test entities and relationships
        self._create_test_graph()

        # Initialize query optimizer (with mocked components for testing)
        self.query_optimizer = UnifiedGraphRAGQueryOptimizer(
            predicate_pushdown_enabled=True,
            join_reordering_enabled=True,
            max_traversal_depth=2,
            max_resource_utilization=100
        )

    def tearDown(self):
        """Clean up after tests."""
        # Clean up temp directory
        shutil.rmtree(self.temp_dir)

    def _create_test_graph(self):
        """Create a test knowledge graph."""
        # Add document entities
        self.doc1 = self.kg.add_entity(
            entity_type="document",
            name="Document 1",
            properties={"content": "This is document 1 about IPFS."},
            vector=self.test_vectors[0]
        )

        self.doc2 = self.kg.add_entity(
            entity_type="document",
            name="Document 2",
            properties={"content": "This is document 2 about content addressing."},
            vector=self.test_vectors[1]
        )

        self.doc3 = self.kg.add_entity(
            entity_type="document",
            name="Document 3",
            properties={"content": "This is document 3 about IPLD."},
            vector=self.test_vectors[2]
        )

        # Add concept entities
        self.concept1 = self.kg.add_entity(
            entity_type="concept",
            name="IPFS",
            properties={"description": "InterPlanetary File System"},
            vector=self.test_vectors[3]
        )

        self.concept2 = self.kg.add_entity(
            entity_type="concept",
            name="Content Addressing",
            properties={"description": "Method of identifying data by its content"},
            vector=self.test_vectors[4]
        )

        # Add relationships
        self.rel1 = self.kg.add_relationship(
            relationship_type="mentions",
            source=self.doc1,
            target=self.concept1,
            properties={"confidence": 0.9}
        )

        self.rel2 = self.kg.add_relationship(
            relationship_type="mentions",
            source=self.doc2,
            target=self.concept2,
            properties={"confidence": 0.8}
        )

        self.rel3 = self.kg.add_relationship(
            relationship_type="related_to",
            source=self.concept1,
            target=self.concept2,
            properties={"strength": 0.7}
        )

    def test_hybrid_search(self):
        """Test hybrid search combining vector and graph."""
        # Create hybrid search
        hybrid_search = HybridVectorGraphSearch(
            self.kg,
            vector_weight=0.6,
            graph_weight=0.4,
            max_graph_hops=2
        )

        # Create a query vector similar to IPFS concept
        query_vector = np.array([0.6, 0.4, 0.0] + [0.0] * (self.dimension - 3), dtype=np.float32)
        query_vector = query_vector / np.linalg.norm(query_vector)

        # Perform hybrid search
        results = hybrid_search.hybrid_search(
            query_vector,
            top_k=5
        )

        # Check if we got results
        self.assertGreater(len(results), 0)

        # Check if we found documents and concepts
        entity_types = set(r["entity"].type for r in results)
        self.assertIn("document", entity_types)
        self.assertIn("concept", entity_types)

        # Check if paths were created for non-direct matches
        non_direct_matches = [r for r in results if r["hops"] > 0]
        for match in non_direct_matches:
            self.assertGreater(len(match["path"]), 0)

    def test_entity_mediated_search(self):
        """Test entity-mediated search to find connected documents."""
        # Create hybrid search
        hybrid_search = HybridVectorGraphSearch(
            self.kg,
            vector_weight=0.6,
            graph_weight=0.4,
            max_graph_hops=2
        )

        # Create a query vector similar to IPFS concept
        query_vector = np.array([0.6, 0.4, 0.0] + [0.0] * (self.dimension - 3), dtype=np.float32)
        query_vector = query_vector / np.linalg.norm(query_vector)

        # Perform entity-mediated search
        connected_pairs = hybrid_search.entity_mediated_search(
            query_vector,
            entity_types=["concept"],
            top_k=5
        )

        # Check if we got results
        self.assertGreater(len(connected_pairs), 0)

        # Check if we found document pairs
        for pair in connected_pairs:
            self.assertEqual(pair["doc1"]["type"], "document")
            self.assertEqual(pair["doc2"]["type"], "document")
            self.assertEqual(pair["entity"]["type"], "concept")

    @patch('ipfs_datasets_py.graphrag_integration.GraphRAGLLMProcessor')
    def test_query_engine(self, mock_llm_processor):
        """Test GraphRAG query engine."""
        # Mock LLM processor
        mock_llm_processor.return_value = MagicMock()

        # Create vector stores dictionary
        vector_stores = {"default": self.vector_store}

        # Create hybrid search
        hybrid_search = HybridVectorGraphSearch(
            self.kg,
            vector_weight=0.6,
            graph_weight=0.4,
            max_graph_hops=2
        )

        # Create query engine
        query_engine = GraphRAGQueryEngine(
            dataset=self.kg,
            vector_stores=vector_stores,
            graph_store=self.kg,
            model_weights=None,
            hybrid_search=hybrid_search,
            query_optimizer=self.query_optimizer,
            enable_cross_document_reasoning=True
        )

        # Create a query vector
        query_vector = np.array([0.6, 0.4, 0.0] + [0.0] * (self.dimension - 3), dtype=np.float32)
        query_vector = query_vector / np.linalg.norm(query_vector)

        # Create query embeddings
        query_embeddings = {"default": query_vector}

        # Execute query
        results = query_engine.query(
            query_text="What is IPFS?",
            query_embeddings=query_embeddings,
            top_k=5,
            include_vector_results=True,
            include_graph_results=True,
            include_cross_document_reasoning=True
        )

        # Check if we got results
        self.assertIn("query", results)
        self.assertIn("vector_results", results)

        if "hybrid_results" in results:
            self.assertGreater(len(results["hybrid_results"]), 0)

    def test_graphrag_demo(self):
        """Test the GraphRAG demo class."""
        # Create demo
        demo = GraphRAGDemo(dimension=self.dimension)

        # Create sample graph
        demo.create_sample_graph()

        # Check if we have documents, entities, and relationships
        self.assertGreater(len(demo.documents), 0)
        self.assertGreater(len(demo.entities), 0)
        self.assertGreater(len(demo.relationships), 0)

        # Export to CAR files
        car_files = demo.export_to_car(self.temp_dir)

        # Check if files were created
        self.assertTrue(os.path.exists(car_files["vector_store"]))
        self.assertTrue(os.path.exists(car_files["knowledge_graph"]))

        # Reload from CAR files
        reloaded_demo = GraphRAGDemo.from_car_files(
            car_files["vector_store"],
            car_files["knowledge_graph"],
            dimension=self.dimension
        )

        # Check if we have the same number of entities
        self.assertEqual(len(demo.documents) + len(demo.entities), len(reloaded_demo.documents) + len(reloaded_demo.entities))
        self.assertEqual(len(demo.relationships), len(reloaded_demo.relationships))

if __name__ == "__main__":
    unittest.main()
