#!/usr/bin/env python3
"""
Tests for the Cross-Document Reasoning module.

This module tests the capabilities of the cross-document reasoning
system, including entity-mediated connections, information relation
analysis, and answer synthesis.
"""

import os
import sys
import unittest
import json
import numpy as np
from typing import List, Dict, Any

# Add parent directory to path to import the module
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.append(parent_dir)

from ipfs_datasets_py.cross_document_reasoning import (
    CrossDocumentReasoner,
    DocumentNode,
    EntityMediatedConnection,
    InformationRelationType
)
from ipfs_datasets_py.llm.llm_reasoning_tracer import LLMReasoningTracer
from ipfs_datasets_py import (
    UnifiedGraphRAGQueryOptimizer,
    QueryRewriter,
    QueryBudgetManager
)


class MockVectorStore:
    """Mock vector store for testing."""

    def __init__(self, documents: List[Dict[str, Any]]):
        self.documents = documents

    def embed_query(self, query: str) -> np.ndarray:
        """Mock method to embed a query."""
        return np.random.rand(768)

    def search(self, query_vector: np.ndarray, top_k: int = 5, min_score: float = 0.0) -> List[Any]:
        """Mock method to search for similar vectors."""
        # Create mock search results
        from collections import namedtuple
        SearchResult = namedtuple('SearchResult', ['id', 'score', 'metadata'])

        results = []
        for i, doc in enumerate(self.documents[:top_k]):
            score = 0.9 - (i * 0.05)
            if score >= min_score:
                result = SearchResult(
                    id=doc["id"],
                    score=score,
                    metadata={
                        "content": doc["content"],
                        "source": doc["source"],
                        "entities": doc.get("entities", [])
                    }
                )
                results.append(result)

        return results


class MockKnowledgeGraph:
    """Mock knowledge graph for testing."""

    def __init__(self, entities: Dict[str, Dict[str, Any]]):
        self.entities = entities

    def get_entity(self, entity_id: str) -> Dict[str, Any]:
        """Get entity by ID."""
        return self.entities.get(entity_id, None)


class TestCrossDocumentReasoning(unittest.TestCase):
    """Test cases for the cross-document reasoning module."""

    def setUp(self):
        """Set up test fixtures."""
        # Initialize reasoning tracer
        self.reasoning_tracer = LLMReasoningTracer()

        # Initialize query optimizer
        self.query_optimizer = UnifiedGraphRAGQueryOptimizer()

        # Sample documents for testing
        self.sample_documents = [
            {
                "id": "doc1",
                "content": "IPFS is a peer-to-peer hypermedia protocol that makes the web faster, safer, and more open.",
                "source": "IPFS Documentation",
                "metadata": {"published_date": "2020-01-01"},
                "entities": ["ipfs", "p2p", "protocol", "web"]
            },
            {
                "id": "doc2",
                "content": "IPFS uses content addressing to uniquely identify each file in a global namespace connecting all computing devices.",
                "source": "IPFS Website",
                "metadata": {"published_date": "2021-03-15"},
                "entities": ["ipfs", "content_addressing", "file", "namespace"]
            },
            {
                "id": "doc3",
                "content": "Content addressing is a technique where content is identified by its cryptographic hash rather than by its location.",
                "source": "Distributed Systems Book",
                "metadata": {"published_date": "2019-05-20"},
                "entities": ["content_addressing", "cryptographic_hash", "location"]
            },
            {
                "id": "doc4",
                "content": "Filecoin is a peer-to-peer network that stores files, with built-in economic incentives to ensure files are stored reliably over time.",
                "source": "Filecoin Docs",
                "metadata": {"published_date": "2021-06-10"},
                "entities": ["filecoin", "p2p", "incentives", "storage"]
            },
            {
                "id": "doc5",
                "content": "IPFS and Filecoin are complementary protocols for storing and sharing data in a decentralized file system.",
                "source": "Protocol Labs Blog",
                "metadata": {"published_date": "2022-01-15"},
                "entities": ["ipfs", "filecoin", "decentralized", "storage"]
            }
        ]

        # Sample entities for testing
        self.sample_entities = {
            "ipfs": {
                "name": "IPFS",
                "type": "protocol",
                "description": "InterPlanetary File System"
            },
            "content_addressing": {
                "name": "Content Addressing",
                "type": "technology",
                "description": "Identifying content by its hash"
            },
            "p2p": {
                "name": "Peer-to-Peer",
                "type": "architecture",
                "description": "Decentralized network architecture"
            },
            "filecoin": {
                "name": "Filecoin",
                "type": "protocol",
                "description": "Decentralized storage network"
            }
        }

        # Initialize vector store with sample documents
        self.vector_store = MockVectorStore(self.sample_documents)

        # Initialize knowledge graph with sample entities
        self.knowledge_graph = MockKnowledgeGraph(self.sample_entities)

        # Initialize cross-document reasoner
        self.reasoner = CrossDocumentReasoner(
            query_optimizer=self.query_optimizer,
            reasoning_tracer=self.reasoning_tracer
        )

    def test_initialization(self):
        """Test initializing the cross-document reasoner."""
        self.assertIsNotNone(self.reasoner)
        self.assertEqual(self.reasoner.total_queries, 0)
        self.assertEqual(self.reasoner.successful_queries, 0)

    def test_document_retrieval(self):
        """Test retrieving relevant documents for a query."""
        documents = self.reasoner._get_relevant_documents(
            query="How does IPFS use content addressing?",
            query_embedding=np.random.rand(768),
            input_documents=self.sample_documents,
            vector_store=None,
            max_documents=3,
            min_relevance=0.5
        )

        self.assertEqual(len(documents), 3)
        self.assertEqual(documents[0].id, "doc1")
        self.assertEqual(documents[0].source, "IPFS Documentation")
        self.assertGreaterEqual(documents[0].relevance_score, documents[1].relevance_score)

    def test_entity_connections(self):
        """Test finding entity-mediated connections between documents."""
        # Create document nodes
        documents = [
            DocumentNode(
                id=doc["id"],
                content=doc["content"],
                source=doc["source"],
                metadata=doc["metadata"],
                relevance_score=0.9 - (i * 0.05),
                entities=doc["entities"]
            )
            for i, doc in enumerate(self.sample_documents)
        ]

        # Find entity connections
        connections = self.reasoner._find_entity_connections(
            documents=documents,
            knowledge_graph=self.knowledge_graph,
            max_hops=2
        )

        self.assertGreater(len(connections), 0)

        # Check that we found a connection between docs with "ipfs" entity
        ipfs_connections = [c for c in connections if c.entity_id == "ipfs"]
        self.assertGreater(len(ipfs_connections), 0)

        # Check that we found connection types
        relation_types = set(c.relation_type for c in connections)
        self.assertGreater(len(relation_types), 0)

    def test_traversal_paths(self):
        """Test generating traversal paths for reasoning."""
        # Create document nodes
        documents = [
            DocumentNode(
                id=doc["id"],
                content=doc["content"],
                source=doc["source"],
                metadata=doc["metadata"],
                relevance_score=0.9 - (i * 0.05),
                entities=doc["entities"]
            )
            for i, doc in enumerate(self.sample_documents[:3])  # Use just first 3 docs
        ]

        # Create sample connections
        connections = [
            EntityMediatedConnection(
                entity_id="ipfs",
                entity_name="IPFS",
                entity_type="protocol",
                source_doc_id="doc1",
                target_doc_id="doc2",
                relation_type=InformationRelationType.COMPLEMENTARY,
                connection_strength=0.8
            ),
            EntityMediatedConnection(
                entity_id="content_addressing",
                entity_name="Content Addressing",
                entity_type="technology",
                source_doc_id="doc2",
                target_doc_id="doc3",
                relation_type=InformationRelationType.ELABORATING,
                connection_strength=0.75
            )
        ]

        # Generate traversal paths
        paths = self.reasoner._generate_traversal_paths(
            documents=documents,
            entity_connections=connections,
            reasoning_depth="moderate"
        )

        self.assertGreater(len(paths), 0)
        self.assertIsInstance(paths[0], list)

        # Check that at least one path connects multiple documents
        has_multi_doc_path = False
        for path in paths:
            if len(path) > 1:
                has_multi_doc_path = True
                break
        self.assertTrue(has_multi_doc_path)

    def test_answer_synthesis(self):
        """Test synthesizing an answer from connected information."""
        # Create document nodes
        documents = [
            DocumentNode(
                id=doc["id"],
                content=doc["content"],
                source=doc["source"],
                metadata=doc["metadata"],
                relevance_score=0.9 - (i * 0.05),
                entities=doc["entities"]
            )
            for i, doc in enumerate(self.sample_documents)
        ]

        # Create sample connections
        connections = [
            EntityMediatedConnection(
                entity_id="ipfs",
                entity_name="IPFS",
                entity_type="protocol",
                source_doc_id="doc1",
                target_doc_id="doc2",
                relation_type=InformationRelationType.COMPLEMENTARY,
                connection_strength=0.8
            ),
            EntityMediatedConnection(
                entity_id="content_addressing",
                entity_name="Content Addressing",
                entity_type="technology",
                source_doc_id="doc2",
                target_doc_id="doc3",
                relation_type=InformationRelationType.ELABORATING,
                connection_strength=0.75
            )
        ]

        # Sample traversal paths
        paths = [["doc1", "doc2"], ["doc2", "doc3"]]

        # Synthesize answer
        answer, confidence = self.reasoner._synthesize_answer(
            query="How does IPFS use content addressing?",
            documents=documents,
            entity_connections=connections,
            traversal_paths=paths,
            reasoning_depth="moderate"
        )

        self.assertIsNotNone(answer)
        self.assertIsInstance(answer, str)
        self.assertGreater(len(answer), 0)
        self.assertIsInstance(confidence, float)
        self.assertGreaterEqual(confidence, 0.0)
        self.assertLessEqual(confidence, 1.0)

    def test_cross_document_reasoning(self):
        """Test the complete cross-document reasoning process."""
        result = self.reasoner.reason_across_documents(
            query="How does IPFS use content addressing?",
            input_documents=self.sample_documents,
            reasoning_depth="moderate",
            return_trace=True
        )

        self.assertIsNotNone(result)
        self.assertIn("answer", result)
        self.assertIn("documents", result)
        self.assertIn("entity_connections", result)
        self.assertIn("confidence", result)

        # If we requested a trace, check that it's included
        self.assertIn("reasoning_trace", result)

        # Check the content of the result
        self.assertIsInstance(result["answer"], str)
        self.assertGreater(len(result["answer"]), 0)
        self.assertGreaterEqual(result["confidence"], 0.0)
        self.assertLessEqual(result["confidence"], 1.0)
        self.assertGreater(len(result["documents"]), 0)

        # At minimum, the docs with "ipfs" and "content_addressing" should be connected
        self.assertGreater(len(result["entity_connections"]), 0)

    def test_get_statistics(self):
        """Test getting statistics about cross-document reasoning."""
        # Perform a query to generate statistics
        self.reasoner.reason_across_documents(
            query="How does IPFS use content addressing?",
            input_documents=self.sample_documents[:3]
        )

        stats = self.reasoner.get_statistics()

        self.assertIsNotNone(stats)
        self.assertIn("total_queries", stats)
        self.assertIn("successful_queries", stats)
        self.assertIn("success_rate", stats)
        self.assertIn("avg_document_count", stats)
        self.assertIn("avg_connection_count", stats)
        self.assertIn("avg_confidence", stats)

        self.assertEqual(stats["total_queries"], 1)
        self.assertEqual(stats["successful_queries"], 1)
        self.assertEqual(stats["success_rate"], 1.0)
        self.assertGreater(stats["avg_document_count"], 0)


def run_tests():
    """Run the cross-document reasoning tests."""
    unittest.main()


if __name__ == "__main__":
    run_tests()
