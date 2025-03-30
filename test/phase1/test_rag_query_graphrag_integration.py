#!/usr/bin/env python
"""
Tests for the integration between RAG Query Optimizer and GraphRAG LLM processor.

These tests verify that the RAG Query Optimizer correctly integrates with
the GraphRAG LLM processor for enhanced cross-document reasoning.
"""

import unittest
import numpy as np
from unittest.mock import MagicMock, patch
from typing import Dict, List, Any

from ipfs_datasets_py.rag_query_optimizer import (
    UnifiedGraphRAGQueryOptimizer,
    WikipediaKnowledgeGraphOptimizer,
    IPLDGraphRAGQueryOptimizer
)
from ipfs_datasets_py.llm_graphrag import (
    GraphRAGLLMProcessor,
    ReasoningEnhancer
)
from ipfs_datasets_py.llm_reasoning_tracer import WikipediaKnowledgeGraphTracer


class TestRAGQueryOptimizerGraphRAGIntegration(unittest.TestCase):
    """Test the integration between RAG Query Optimizer and GraphRAG LLM processor."""

    def setUp(self):
        """Set up test fixtures."""
        # Create a mock LLM interface
        self.mock_llm = MagicMock()
        self.mock_llm.generate_with_structured_output.return_value = {
            "answer": "This is a test answer.",
            "reasoning": "Test reasoning process.",
            "confidence": 0.8,
            "references": ["doc1", "doc2"],
            "knowledge_gaps": ["Gap in knowledge about X."]
        }
        self.mock_llm.count_tokens.return_value = 100

        # Create a mock tracer for Wikipedia optimizer
        self.mock_tracer = MagicMock(spec=WikipediaKnowledgeGraphTracer)
        self.mock_tracer.get_trace_info.return_value = {
            "knowledge_graph": {
                "entities": [
                    {"entity_id": "entity1", "name": "Test Entity", "type": "concept"}
                ]
            },
            "validation": {
                "coverage": 0.8,
                "edge_confidence": {"related_to": 0.9}
            }
        }
        self.mock_tracer.record_query_plan.return_value = None

        # Create test data
        self.test_query = "Test query"
        self.test_vector = np.random.rand(768)
        self.test_documents = [
            {
                "id": "doc1",
                "title": "Test Document 1",
                "content": "Test content 1",
                "trace_id": "trace1"
            },
            {
                "id": "doc2",
                "title": "Test Document 2",
                "content": "Test content 2",
                "root_cid": "bafy123"
            }
        ]
        self.test_connections = [
            {
                "doc1": {"id": "doc1", "title": "Test Document 1"},
                "doc2": {"id": "doc2", "title": "Test Document 2"},
                "entity": {"id": "entity1", "name": "Test Entity", "type": "concept"},
                "connection_type": "related_to",
                "explanation": "Test connection explanation."
            }
        ]

    def test_wikipedia_optimizer_integration(self):
        """Test integration with Wikipedia Knowledge Graph Optimizer."""
        # Create Wikipedia optimizer
        wikipedia_optimizer = WikipediaKnowledgeGraphOptimizer(
            tracer=self.mock_tracer
        )

        # Create unified optimizer with Wikipedia optimizer
        unified_optimizer = UnifiedGraphRAGQueryOptimizer(
            wikipedia_optimizer=wikipedia_optimizer
        )

        # Create GraphRAG LLM processor with optimizer
        with patch('ipfs_datasets_py.llm_interface.LLMInterfaceFactory.create', return_value=self.mock_llm):
            processor = GraphRAGLLMProcessor(
                query_optimizer=unified_optimizer
            )

            # Create ReasoningEnhancer with processor and optimizer
            enhancer = ReasoningEnhancer(
                llm_processor=processor,
                query_optimizer=unified_optimizer
            )

            # Test optimize_and_reason
            doc_trace_ids = ["trace1"]
            result = enhancer.optimize_and_reason(
                query=self.test_query,
                query_vector=self.test_vector,
                documents=self.test_documents,
                connections=self.test_connections,
                reasoning_depth="moderate",
                doc_trace_ids=doc_trace_ids
            )

            # Verify the result
            self.assertIn("answer", result)
            self.assertIn("confidence", result)
            self.assertIn("raw_connections", result)
            self.assertEqual(result["answer"], "This is a test answer.")
            self.assertEqual(result["confidence"], 0.8)

            # Verify optimizer was used
            self.mock_tracer.get_trace_info.assert_called()

    def test_ipld_optimizer_integration(self):
        """Test integration with IPLD-based Graph RAG Optimizer."""
        # Create IPLD optimizer
        ipld_optimizer = IPLDGraphRAGQueryOptimizer()

        # Create unified optimizer with IPLD optimizer
        unified_optimizer = UnifiedGraphRAGQueryOptimizer(
            ipld_optimizer=ipld_optimizer
        )

        # Create GraphRAG LLM processor with optimizer
        with patch('ipfs_datasets_py.llm_interface.LLMInterfaceFactory.create', return_value=self.mock_llm):
            processor = GraphRAGLLMProcessor(
                query_optimizer=unified_optimizer
            )

            # Create ReasoningEnhancer with processor and optimizer
            enhancer = ReasoningEnhancer(
                llm_processor=processor,
                query_optimizer=unified_optimizer
            )

            # Test optimize_and_reason
            root_cids = ["bafy123"]
            result = enhancer.optimize_and_reason(
                query=self.test_query,
                query_vector=self.test_vector,
                documents=self.test_documents,
                connections=self.test_connections,
                reasoning_depth="moderate",
                root_cids=root_cids
            )

            # Verify the result
            self.assertIn("answer", result)
            self.assertIn("confidence", result)
            self.assertIn("raw_connections", result)
            self.assertEqual(result["answer"], "This is a test answer.")
            self.assertEqual(result["confidence"], 0.8)

    def test_unified_optimizer_integration(self):
        """Test integration with Unified Graph RAG Optimizer."""
        # Create component optimizers
        wikipedia_optimizer = WikipediaKnowledgeGraphOptimizer(
            tracer=self.mock_tracer
        )
        ipld_optimizer = IPLDGraphRAGQueryOptimizer()

        # Create unified optimizer with both component optimizers
        unified_optimizer = UnifiedGraphRAGQueryOptimizer(
            wikipedia_optimizer=wikipedia_optimizer,
            ipld_optimizer=ipld_optimizer,
            auto_detect_graph_type=True
        )

        # Create GraphRAG LLM processor with optimizer
        with patch('ipfs_datasets_py.llm_interface.LLMInterfaceFactory.create', return_value=self.mock_llm):
            processor = GraphRAGLLMProcessor(
                query_optimizer=unified_optimizer
            )

            # Create ReasoningEnhancer with processor and optimizer
            enhancer = ReasoningEnhancer(
                llm_processor=processor,
                query_optimizer=unified_optimizer
            )

            # Test optimize_and_reason with auto-detection
            result = enhancer.optimize_and_reason(
                query=self.test_query,
                query_vector=self.test_vector,
                documents=self.test_documents,
                connections=self.test_connections,
                reasoning_depth="moderate"
            )

            # Verify the result
            self.assertIn("answer", result)
            self.assertIn("confidence", result)
            self.assertIn("raw_connections", result)
            self.assertEqual(result["answer"], "This is a test answer.")
            self.assertEqual(result["confidence"], 0.8)

    def test_fallback_without_optimizer(self):
        """Test fallback behavior when no optimizer is available."""
        # Create ReasoningEnhancer without an optimizer
        with patch('ipfs_datasets_py.llm_interface.LLMInterfaceFactory.create', return_value=self.mock_llm):
            processor = GraphRAGLLMProcessor()
            enhancer = ReasoningEnhancer(
                llm_processor=processor
            )

            # Test optimize_and_reason without an optimizer
            result = enhancer.optimize_and_reason(
                query=self.test_query,
                query_vector=self.test_vector,
                documents=self.test_documents,
                connections=self.test_connections,
                reasoning_depth="moderate"
            )

            # Verify the result still works without optimizer
            self.assertIn("answer", result)
            self.assertIn("confidence", result)
            self.assertIn("raw_connections", result)
            self.assertEqual(result["answer"], "This is a test answer.")
            self.assertEqual(result["confidence"], 0.8)

    def test_optimize_multi_graph_query(self):
        """Test multi-graph query optimization."""
        # Create component optimizers
        wikipedia_optimizer = WikipediaKnowledgeGraphOptimizer(
            tracer=self.mock_tracer
        )
        ipld_optimizer = IPLDGraphRAGQueryOptimizer()

        # Create unified optimizer with both component optimizers
        unified_optimizer = UnifiedGraphRAGQueryOptimizer(
            wikipedia_optimizer=wikipedia_optimizer,
            ipld_optimizer=ipld_optimizer
        )

        # Create graph specifications for multi-graph query
        graph_specs = [
            {
                "graph_type": "wikipedia",
                "trace_id": "trace1",
                "weight": 0.6
            },
            {
                "graph_type": "ipld",
                "root_cid": "bafy123",
                "weight": 0.4
            }
        ]

        # Test multi-graph query optimization
        plan = unified_optimizer.optimize_multi_graph_query(
            query_vector=self.test_vector,
            query_text=self.test_query,
            graph_specs=graph_specs
        )

        # Verify the plan structure
        self.assertIn("graph_plans", plan)
        self.assertIn("combination_plan", plan)
        self.assertIn("global_params", plan)
        self.assertEqual(plan["optimizer_type"], "unified_multi_graph")

        # Verify weights in combination plan
        self.assertEqual(
            plan["combination_plan"]["graph_weights"]["trace1"], 0.6
        )
        self.assertEqual(
            plan["combination_plan"]["graph_weights"]["bafy123"], 0.4
        )


if __name__ == '__main__':
    unittest.main()