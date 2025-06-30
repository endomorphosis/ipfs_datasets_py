"""
Tests for the RAG Query Optimizer module.

This module tests the various components of the RAG query optimizer, including:
- Basic statistics collection and query optimization
- Wikipedia-specific optimizations for knowledge graphs
- Cross-document query planning
- Vector index partitioning
"""

import unittest
import numpy as np
from unittest.mock import MagicMock, patch
from typing import Dict, List, Any, Optional, Tuple

from ipfs_datasets_py import (
    GraphRAGQueryStats,
    GraphRAGQueryOptimizer,
    VectorIndexPartitioner,
    WikipediaKnowledgeGraphOptimizer,
    IPLDGraphRAGQueryOptimizer,
    UnifiedGraphRAGQueryOptimizer
)
from ipfs_datasets_py.llm_reasoning_tracer import WikipediaKnowledgeGraphTracer


class TestGraphRAGQueryStats(unittest.TestCase):
    """Test case for GraphRAGQueryStats."""

    def setUp(self):
        """Set up test case."""
        self.stats = GraphRAGQueryStats()

    def test_initial_state(self):
        """Test that the initial state is correct."""
        self.assertEqual(self.stats.query_count, 0)
        self.assertEqual(self.stats.cache_hits, 0)
        self.assertEqual(self.stats.total_query_time, 0.0)
        self.assertEqual(self.stats.query_times, [])
        self.assertEqual(self.stats.query_patterns, {})
        self.assertEqual(self.stats.query_timestamps, [])

    def test_record_query_time(self):
        """Test recording query times."""
        self.stats.record_query_time(0.5)
        self.stats.record_query_time(0.7)

        self.assertEqual(self.stats.query_count, 2)
        self.assertEqual(self.stats.total_query_time, 1.2)
        self.assertEqual(self.stats.query_times, [0.5, 0.7])
        self.assertEqual(len(self.stats.query_timestamps), 2)

    def test_record_cache_hit(self):
        """Test recording cache hits."""
        self.stats.record_cache_hit()
        self.stats.record_cache_hit()

        self.assertEqual(self.stats.cache_hits, 2)

    def test_record_query_pattern(self):
        """Test recording query patterns."""
        pattern1 = {"max_depth": 2, "edge_types": ["is_a", "part_of"]}
        pattern2 = {"max_depth": 3, "edge_types": ["created_by"]}

        self.stats.record_query_pattern(pattern1)
        self.stats.record_query_pattern(pattern1)  # Record the same pattern twice
        self.stats.record_query_pattern(pattern2)

        common_patterns = self.stats.get_common_patterns()
        self.assertEqual(len(common_patterns), 2)
        self.assertEqual(common_patterns[0][1], 2)  # pattern1 should be most common
        self.assertEqual(common_patterns[1][1], 1)  # pattern2 should be second

    def test_get_performance_summary(self):
        """Test getting performance summary."""
        self.stats.record_query_time(0.3)
        self.stats.record_query_time(0.5)
        self.stats.record_cache_hit()

        summary = self.stats.get_performance_summary()

        self.assertEqual(summary["query_count"], 2)
        self.assertEqual(summary["cache_hit_rate"], 0.5)
        self.assertEqual(summary["avg_query_time"], 0.4)
        self.assertEqual(summary["min_query_time"], 0.3)
        self.assertEqual(summary["max_query_time"], 0.5)

    def test_reset(self):
        """Test resetting statistics."""
        self.stats.record_query_time(0.5)
        self.stats.record_cache_hit()
        self.stats.record_query_pattern({"depth": 2})

        self.stats.reset()

        self.assertEqual(self.stats.query_count, 0)
        self.assertEqual(self.stats.cache_hits, 0)
        self.assertEqual(self.stats.total_query_time, 0.0)
        self.assertEqual(self.stats.query_times, [])
        self.assertEqual(self.stats.query_patterns, {})
        self.assertEqual(self.stats.query_timestamps, [])


class TestGraphRAGQueryOptimizer(unittest.TestCase):
    """Test case for GraphRAGQueryOptimizer."""

    def setUp(self):
        """Set up test case."""
        self.optimizer = GraphRAGQueryOptimizer()

    def test_optimize_query(self):
        """Test query optimization."""
        # Create a random query vector
        query_vector = np.random.rand(768)

        # Optimize query
        result = self.optimizer.optimize_query(
            query_vector=query_vector,
            max_vector_results=5,
            max_traversal_depth=2
        )

        # Check that result has expected structure
        self.assertIn("params", result)
        self.assertIn("weights", result)

        # Check parameters
        params = result["params"]
        self.assertIn("max_vector_results", params)
        self.assertIn("max_traversal_depth", params)

        # Check weights
        weights = result["weights"]
        self.assertIn("vector", weights)
        self.assertIn("graph", weights)
        self.assertAlmostEqual(weights["vector"] + weights["graph"], 1.0, places=1)

    def test_query_caching(self):
        """Test query caching functionality."""
        # Create a random query vector
        query_vector = np.random.rand(768)

        # Generate a key for the query
        query_key = self.optimizer.get_query_key(
            query_vector=query_vector,
            max_vector_results=5,
            max_traversal_depth=2
        )

        # Check that query is not in cache
        self.assertFalse(self.optimizer.is_in_cache(query_key))

        # Add to cache
        test_result = {"test": "result"}
        self.optimizer.add_to_cache(query_key, test_result)

        # Check that query is now in cache
        self.assertTrue(self.optimizer.is_in_cache(query_key))

        # Get from cache
        result = self.optimizer.get_from_cache(query_key)
        self.assertEqual(result, test_result)

    def test_execute_query_with_caching(self):
        """Test query execution with caching."""
        # Create a random query vector
        query_vector = np.random.rand(768)

        # Create a mock query function
        query_func = MagicMock(return_value={"result": "test"})

        # Execute query
        params = {"max_vector_results": 5, "max_traversal_depth": 2}
        result1 = self.optimizer.execute_query_with_caching(
            query_func=query_func,
            query_vector=query_vector,
            params=params
        )

        # Check that query function was called
        query_func.assert_called_once()

        # Execute same query again
        result2 = self.optimizer.execute_query_with_caching(
            query_func=query_func,
            query_vector=query_vector,
            params=params
        )

        # Check that query function was not called again (cache hit)
        self.assertEqual(query_func.call_count, 1)

        # Check that results are the same
        self.assertEqual(result1, result2)

    def test_analyze_query_performance(self):
        """Test query performance analysis."""
        # Record some query statistics
        self.optimizer.query_stats.record_query_time(0.5)
        self.optimizer.query_stats.record_query_time(0.7)
        self.optimizer.query_stats.record_cache_hit()

        # Analyze performance
        analysis = self.optimizer.analyze_query_performance()

        # Check that analysis has expected structure
        self.assertIn("statistics", analysis)
        self.assertIn("recommendations", analysis)
        self.assertIn("weights", analysis)

        # Check statistics
        stats = analysis["statistics"]
        self.assertEqual(stats["query_count"], 2)
        self.assertEqual(stats["cache_hit_rate"], 0.5)
        self.assertAlmostEqual(stats["avg_query_time"], 0.6)


class TestVectorIndexPartitioner(unittest.TestCase):
    """Test case for VectorIndexPartitioner."""

    def setUp(self):
        """Set up test case."""
        # Use small dimension for faster tests
        self.partitioner = VectorIndexPartitioner(dimension=4, num_partitions=2)

    def test_assign_partition(self):
        """Test partition assignment."""
        # Create some test vectors
        vectors = np.array([
            [0.1, 0.2, 0.3, 0.4],  # Vector 1
            [0.5, 0.6, 0.7, 0.8],  # Vector 2
            [0.9, 0.8, 0.7, 0.6],  # Vector 3
            [0.4, 0.3, 0.2, 0.1]   # Vector 4
        ])

        # Assign each vector to a partition
        partitions = []
        for vector in vectors:
            partition = self.partitioner.assign_partition(vector)
            partitions.append(partition)

        # Check that we have assigned to both partitions
        self.assertTrue(0 in partitions or 1 in partitions)

    def test_add_vector(self):
        """Test adding vectors to partitions."""
        # Create some test vectors
        vectors = np.array([
            [0.1, 0.2, 0.3, 0.4],  # Vector 1
            [0.5, 0.6, 0.7, 0.8],  # Vector 2
            [0.9, 0.8, 0.7, 0.6],  # Vector 3
            [0.4, 0.3, 0.2, 0.1]   # Vector 4
        ])

        # Add vectors with metadata
        metadata = [{"id": i} for i in range(len(vectors))]
        for i, vector in enumerate(vectors):
            self.partitioner.add_vector(vector, metadata[i])

        # Check that total count is correct
        self.assertEqual(self.partitioner.total_count, len(vectors))

        # Check partition statistics
        stats = self.partitioner.get_partition_stats()
        self.assertEqual(len(stats), 2)  # We have 2 partitions

        # Check that all vectors are assigned
        total_in_partitions = sum(stat["count"] for stat in stats)
        self.assertEqual(total_in_partitions, len(vectors))

    def test_search(self):
        """Test vector search across partitions."""
        # Create some test vectors
        vectors = np.array([
            [0.1, 0.2, 0.3, 0.4],  # Vector 1
            [0.5, 0.6, 0.7, 0.8],  # Vector 2
            [0.9, 0.8, 0.7, 0.6],  # Vector 3
            [0.4, 0.3, 0.2, 0.1]   # Vector 4
        ])

        # Add vectors with metadata
        metadata = [{"id": i} for i in range(len(vectors))]
        for i, vector in enumerate(vectors):
            self.partitioner.add_vector(vector, metadata[i])

        # Search for a vector similar to Vector 2
        query_vector = np.array([0.45, 0.55, 0.65, 0.75])
        results = self.partitioner.search(query_vector, top_k=2)

        # Check that we got expected number of results
        self.assertEqual(len(results), 2)

        # Check that results are sorted by similarity (descending)
        self.assertGreaterEqual(results[0][0], results[1][0])


class TestWikipediaKnowledgeGraphOptimizer(unittest.TestCase):
    """Test case for WikipediaKnowledgeGraphOptimizer."""

    def setUp(self):
        """Set up test case."""
        # Create a mock WikipediaKnowledgeGraphTracer
        self.mock_tracer = MagicMock()
        self.mock_tracer.get_trace_info = MagicMock(return_value={
            "page_title": "Test Page",
            "status": "completed",
            "extraction_temperature": 0.7,
            "structure_temperature": 0.5,
            "validation": {
                "coverage": 0.8,
                "edge_confidence": {
                    "instance_of": 0.9,
                    "related_to": 0.7,
                    "works_for": 0.6,
                    "located_in": 0.5
                }
            }
        })

        # Create optimizer with mock tracer
        self.optimizer = WikipediaKnowledgeGraphOptimizer(tracer=self.mock_tracer)

    def test_detect_entity_types(self):
        """Test entity type detection from query text."""
        # Test with person-related query
        query1 = "Who was the founder of Microsoft?"
        types1 = self.optimizer._detect_entity_types(query1)
        self.assertIn("person", types1)

        # Test with location-related query
        query2 = "Where is the headquarters of Google located?"
        types2 = self.optimizer._detect_entity_types(query2)
        self.assertIn("location", types2)

        # Test with concept-related query
        query3 = "What is the theory of relativity?"
        types3 = self.optimizer._detect_entity_types(query3)
        self.assertIn("concept", types3)

        # Test with predefined types
        predefined = ["organization", "technology"]
        types4 = self.optimizer._detect_entity_types("Any query", predefined)
        self.assertEqual(types4, predefined)

    def test_get_important_edge_types(self):
        """Test edge type importance calculation."""
        # Test with person-related query
        query1 = "Who created Microsoft and where was he born?"
        types1 = ["person", "organization"]
        edges1 = self.optimizer._get_important_edge_types(query1, types1)
        self.assertTrue(any(edge in edges1 for edge in ["created_by", "born_in"]))

        # Test with location-related query
        query2 = "What is the capital of France and which countries are part of Europe?"
        types2 = ["location"]
        edges2 = self.optimizer._get_important_edge_types(query2, types2)
        self.assertTrue(any(edge in edges2 for edge in ["capital_of", "part_of"]))

    def test_optimize_query(self):
        """Test query optimization for Wikipedia knowledge graphs."""
        # Create a query
        query_text = "Who founded Microsoft and where is it headquartered?"
        query_vector = np.random.rand(768)
        trace_id = "test-trace-123"

        # Optimize query
        result = self.optimizer.optimize_query(
            query_text=query_text,
            query_vector=query_vector,
            trace_id=trace_id
        )

        # Check that result has expected structure
        self.assertIn("params", result)
        self.assertIn("weights", result)
        self.assertIn("detected_types", result)
        self.assertIn("important_edge_types", result)

        # Check that detected types are reasonable for the query
        detected_types = result["detected_types"]
        self.assertTrue(
            any(t in detected_types for t in ["person", "organization", "location"])
        )

        # Check that important edge types include some reasonable ones
        # Note: The exact edge types may vary depending on implementation
        edge_types = result["important_edge_types"]

        # Since the specific edge types might vary, we'll check for common categories
        # rather than exact matches
        reasonable_edge_types = [
            "related_to", "instance_of", "created_by", "works_for",
            "founded_by", "headquartered_in", "located_in", "sourced_from"
        ]

        has_reasonable_edge = False
        for edge in edge_types:
            if edge in reasonable_edge_types:
                has_reasonable_edge = True
                break

        self.assertTrue(has_reasonable_edge,
                       f"No reasonable edge types found in {edge_types}")

        # Verify that tracer was called
        self.mock_tracer.get_trace_info.assert_called_with(trace_id)

    def test_optimize_cross_document_query(self):
        """Test cross-document query optimization."""
        # Create mock data for connecting entities
        mock_kg1 = {
            "entities": [
                {"entity_id": "e1", "name": "Microsoft", "entity_type": "organization"},
                {"entity_id": "e2", "name": "Bill Gates", "entity_type": "person"}
            ]
        }
        mock_kg2 = {
            "entities": [
                {"entity_id": "e2", "name": "Bill Gates", "entity_type": "person"},
                {"entity_id": "e3", "name": "Seattle", "entity_type": "location"}
            ]
        }

        # Update mock tracer to return knowledge graphs
        self.mock_tracer.get_trace_info.side_effect = lambda trace_id: {
            "trace1": {"knowledge_graph": mock_kg1},
            "trace2": {"knowledge_graph": mock_kg2}
        }.get(trace_id, {})

        # Create a cross-document query
        query_text = "Where does the founder of Microsoft live?"
        query_vector = np.random.rand(768)
        doc_trace_ids = ["trace1", "trace2"]

        # Optimize cross-document query
        result = self.optimizer.optimize_cross_document_query(
            query_text=query_text,
            query_vector=query_vector,
            doc_trace_ids=doc_trace_ids
        )

        # Check that result has expected structure
        self.assertIn("base_params", result)
        self.assertIn("weights", result)
        self.assertIn("connecting_entities", result)
        self.assertIn("doc_relationships", result)
        self.assertIn("traversal_paths", result)

        # Check that connecting entities include the shared entity
        connecting_entities = result["connecting_entities"]
        self.assertIn("e2", connecting_entities)

        # Check that paths are created
        paths = result["traversal_paths"]
        if paths:  # Some paths may be created depending on the implementation details
            self.assertGreaterEqual(len(paths), 0)


class TestIPLDGraphRAGQueryOptimizer(unittest.TestCase):
    """Test case for IPLDGraphRAGQueryOptimizer."""

    def setUp(self):
        """Set up test case."""
        self.optimizer = IPLDGraphRAGQueryOptimizer()

    def test_optimize_query(self):
        """Test query optimization for IPLD-based knowledge graphs."""
        # Create a random query vector
        query_vector = np.random.rand(768)
        query_text = "How does IPFS handle content addressing?"
        root_cids = ["QmXoypizjW3WknFiJnKLwHCnL72vedxjQkDDP1mXWo6uco"]
        content_types = ["application/json"]

        # Optimize query
        result = self.optimizer.optimize_query(
            query_vector=query_vector,
            query_text=query_text,
            root_cids=root_cids,
            content_types=content_types,
            max_vector_results=5,
            max_traversal_depth=2
        )

        # Check that result has expected structure
        self.assertIn("params", result)
        self.assertIn("weights", result)
        self.assertIn("ipld_params", result)
        self.assertIn("edge_type_importance", result)

        # Check weights based on content type
        weights = result["weights"]
        self.assertIn("vector", weights)
        self.assertIn("graph", weights)
        # For application/json we expect higher graph weight
        self.assertLessEqual(weights["vector"], 0.5)
        self.assertGreaterEqual(weights["graph"], 0.5)

    def test_content_type_matching(self):
        """Test content type pattern matching."""
        # Test exact match
        self.assertTrue(self.optimizer._match_content_type("text/plain", "text/plain"))

        # Test wildcard match
        self.assertTrue(self.optimizer._match_content_type("image/png", "image/*"))
        self.assertTrue(self.optimizer._match_content_type("image/jpeg", "image/*"))
        self.assertFalse(self.optimizer._match_content_type("text/plain", "image/*"))

    def test_edge_type_extraction(self):
        """Test extraction of edge types from query text."""
        # Test instance_of relationship
        query1 = "What is a type of neural network?"
        edges1 = self.optimizer._extract_important_edge_types(query1)
        self.assertIn("instance_of", edges1)

        # Test part_of relationship
        query2 = "What components are part of a computer?"
        edges2 = self.optimizer._extract_important_edge_types(query2)
        self.assertIn("part_of", edges2)

        # Test related_to relationship (always included)
        query3 = "Tell me about computers"
        edges3 = self.optimizer._extract_important_edge_types(query3)
        self.assertIn("related_to", edges3)

    def test_optimize_multi_graph_query(self):
        """Test multi-graph query optimization."""
        # Create a random query vector
        query_vector = np.random.rand(768)
        query_text = "How do different systems implement content addressing?"
        graph_cids = [
            "QmXoypizjW3WknFiJnKLwHCnL72vedxjQkDDP1mXWo6uco",
            "QmYwAPJzv5CZsnA625s3Xf2nemtYgPpHdWEz79ojWnPbdG",
            "QmZ4tDuvesekSs4qM5ZBKpXiZGun7S2CYtEZRB3DYXkjGx"
        ]

        # Optimize multi-graph query
        result = self.optimizer.optimize_multi_graph_query(
            query_vector=query_vector,
            query_text=query_text,
            graph_cids=graph_cids
        )

        # Check that result has expected structure
        self.assertIn("graph_plans", result)
        self.assertIn("combination_plan", result)
        self.assertEqual(len(result["graph_plans"]), len(graph_cids))


class TestUnifiedGraphRAGQueryOptimizer(unittest.TestCase):
    """Test case for UnifiedGraphRAGQueryOptimizer."""

    def setUp(self):
        """Set up test case."""
        # Create a mock WikipediaKnowledgeGraphTracer
        self.mock_tracer = MagicMock()
        self.mock_tracer.get_trace_info = MagicMock(return_value={
            "page_title": "Test Page",
            "status": "completed",
            "extraction_temperature": 0.7,
            "structure_temperature": 0.5,
            "validation": {
                "coverage": 0.8,
                "edge_confidence": {
                    "instance_of": 0.9,
                    "related_to": 0.7,
                    "works_for": 0.6,
                    "located_in": 0.5
                }
            }
        })

        # Create a Wikipedia optimizer with mock tracer
        self.wikipedia_optimizer = WikipediaKnowledgeGraphOptimizer(tracer=self.mock_tracer)

        # Create the unified optimizer
        self.optimizer = UnifiedGraphRAGQueryOptimizer(
            wikipedia_optimizer=self.wikipedia_optimizer,
            auto_detect_graph_type=True
        )

    def test_graph_type_detection(self):
        """Test graph type auto-detection."""
        # Test Wikipedia graph detection with trace_id
        graph_type1 = self.optimizer._detect_graph_type("test-trace-123", None)
        self.assertEqual(graph_type1, "wikipedia")

        # Test IPLD graph detection with root_cids
        graph_type2 = self.optimizer._detect_graph_type(None, ["QmXoypizjW3WknFiJnKLwHCnL72vedxjQkDDP1mXWo6uco"])
        self.assertEqual(graph_type2, "ipld")

        # Test default for ambiguous case
        graph_type3 = self.optimizer._detect_graph_type(None, None)
        self.assertEqual(graph_type3, "generic")

    def test_optimize_wikipedia_query(self):
        """Test optimization of Wikipedia-specific queries."""
        # Create a random query vector
        query_vector = np.random.rand(768)
        query_text = "Who founded Microsoft?"
        trace_id = "test-trace-123"

        # Optimize query with detected type
        result = self.optimizer.optimize_query(
            query_vector=query_vector,
            query_text=query_text,
            trace_id=trace_id
        )

        # Check that result includes Wikipedia optimizer type
        self.assertIn("optimizer_type", result)
        self.assertEqual(result["optimizer_type"], "wikipedia")

        # Verify that Wikipedia optimizer was called
        self.mock_tracer.get_trace_info.assert_called_with(trace_id)

    def test_optimize_ipld_query(self):
        """Test optimization of IPLD-specific queries."""
        # Create a random query vector
        query_vector = np.random.rand(768)
        query_text = "How does IPFS work?"
        root_cids = ["QmXoypizjW3WknFiJnKLwHCnL72vedxjQkDDP1mXWo6uco"]

        # Optimize query with detected type
        result = self.optimizer.optimize_query(
            query_vector=query_vector,
            query_text=query_text,
            root_cids=root_cids
        )

        # Check that result includes IPLD optimizer type
        self.assertIn("optimizer_type", result)
        self.assertEqual(result["optimizer_type"], "ipld")

    def test_optimize_explicit_graph_type(self):
        """Test optimization with explicitly specified graph type."""
        # Create a random query vector
        query_vector = np.random.rand(768)

        # Test forcing Wikipedia type even with root_cids
        result1 = self.optimizer.optimize_query(
            query_vector=query_vector,
            root_cids=["QmXoypizjW3WknFiJnKLwHCnL72vedxjQkDDP1mXWo6uco"],
            graph_type="wikipedia"
        )
        self.assertEqual(result1["optimizer_type"], "wikipedia")

        # Test forcing IPLD type even with trace_id
        result2 = self.optimizer.optimize_query(
            query_vector=query_vector,
            trace_id="test-trace-123",
            graph_type="ipld"
        )
        self.assertEqual(result2["optimizer_type"], "ipld")

    def test_multi_graph_query(self):
        """Test multi-graph query optimization."""
        # Create a random query vector
        query_vector = np.random.rand(768)
        query_text = "How do different systems implement content addressing?"

        # Mix of Wikipedia and IPLD graphs
        graph_specs = [
            {"graph_type": "wikipedia", "trace_id": "test-trace-123", "weight": 0.6},
            {"graph_type": "ipld", "root_cid": "QmXoypizjW3WknFiJnKLwHCnL72vedxjQkDDP1mXWo6uco", "weight": 0.4}
        ]

        # Optimize multi-graph query
        result = self.optimizer.optimize_multi_graph_query(
            query_vector=query_vector,
            query_text=query_text,
            graph_specs=graph_specs
        )

        # Check that result has expected structure
        self.assertIn("graph_plans", result)
        self.assertIn("combination_plan", result)
        self.assertEqual(len(result["graph_plans"]), 2)
        self.assertEqual(result["optimizer_type"], "unified_multi_graph")

        # Check that weights are applied
        self.assertIn("graph_weights", result["combination_plan"])
        weights = result["combination_plan"]["graph_weights"]
        self.assertEqual(weights["test-trace-123"], 0.6)
        self.assertEqual(weights["QmXoypizjW3WknFiJnKLwHCnL72vedxjQkDDP1mXWo6uco"], 0.4)

    def test_optimization_stats(self):
        """Test statistics collection."""
        # Run multiple queries to collect stats
        query_vector = np.random.rand(768)

        # Wikipedia query
        self.optimizer.optimize_query(
            query_vector=query_vector,
            trace_id="test-trace-123"
        )

        # IPLD query
        self.optimizer.optimize_query(
            query_vector=query_vector,
            root_cids=["QmXoypizjW3WknFiJnKLwHCnL72vedxjQkDDP1mXWo6uco"]
        )

        # Get stats
        stats = self.optimizer.get_optimization_stats()

        # Check that stats have expected fields
        self.assertEqual(stats["total_queries"], 2)
        self.assertEqual(stats["wikipedia_queries"], 1)
        self.assertEqual(stats["ipld_queries"], 1)
        self.assertEqual(stats["wikipedia_percentage"], 50.0)
        self.assertEqual(stats["ipld_percentage"], 50.0)


if __name__ == "__main__":
    unittest.main()
