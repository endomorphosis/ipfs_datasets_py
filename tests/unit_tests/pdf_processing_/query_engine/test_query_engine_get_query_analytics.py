#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/query_engine.py
# Auto-generated on 2025-07-07 02:28:56"

import pytest
import os
import anyio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, List, Any, Optional

from tests._test_utils import (
    has_good_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

work_dir = "/home/runner/work/ipfs_datasets_py/ipfs_datasets_py"
file_path = os.path.join(work_dir, "ipfs_datasets_py/pdf_processing/query_engine.py")
md_path = os.path.join(work_dir, "ipfs_datasets_py/pdf_processing/query_engine_stubs.md")

# Make sure the input file and documentation file exist.
assert os.path.exists(file_path), f"Input file does not exist: {file_path}. Check to see if the file exists or has been moved or renamed."
assert os.path.exists(md_path), f"Documentation file does not exist: {md_path}. Check to see if the file exists or has been moved or renamed."

from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine, QueryResponse, QueryResult

# Check if each classes methods are accessible:
assert QueryEngine.query
assert QueryEngine._normalize_query
assert QueryEngine._detect_query_type
assert QueryEngine._process_entity_query
assert QueryEngine._process_relationship_query
assert QueryEngine._process_semantic_query
assert QueryEngine._process_document_query
assert QueryEngine._process_cross_document_query
assert QueryEngine._process_graph_traversal_query
assert QueryEngine._extract_entity_names_from_query
assert QueryEngine._get_entity_documents
assert QueryEngine._get_relationship_documents
assert QueryEngine._generate_query_suggestions
assert QueryEngine.get_query_analytics

# Check if the modules's imports are accessible:
import anyio
import logging
import json
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from datetime import datetime
import re

from sklearn.metrics.pairwise import cosine_similarity
from sentence_transformers import SentenceTransformer

from ipfs_datasets_py.ipld import IPLDStorage
from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator, Entity, Relationship


def create_mock_query_response(query: str, query_type: str, num_results: int, processing_time: float) -> QueryResponse:
    """Helper function to create mock QueryResponse objects for testing."""
    results = [
        QueryResult(
            id=f"result_{i}",
            type="entity",
            content=f"Test entity {i}",
            relevance_score=0.9 - (i * 0.1),
            source_document=f"doc_{i % 3}",
            source_chunks=[f"chunk_{i}"],
            metadata={"test": True}
        )
        for i in range(num_results)
    ]
    
    return QueryResponse(
        query=query,
        query_type=query_type,
        results=results,
        total_results=num_results,
        processing_time=processing_time,
        suggestions=[f"suggestion_{i}" for i in range(2)],
        metadata={"normalized_query": query.lower(), "timestamp": datetime.now().isoformat()}
    )


class TestQueryEngineGetQueryAnalytics:
    """Test QueryEngine.get_query_analytics method for system performance and usage analytics."""

    def setup_method(self):
        """Set up test fixtures for each test method."""
        self.mock_graphrag = Mock(spec=GraphRAGIntegrator)
        self.mock_storage = Mock(spec=IPLDStorage)
        
        # Create QueryEngine instance with mocked dependencies
        with patch('ipfs_datasets_py.pdf_processing.query_engine.SentenceTransformer'):
            self.query_engine = QueryEngine(
                graphrag_integrator=self.mock_graphrag,
                storage=self.mock_storage,
                embedding_model="test-model"
            )

    @pytest.mark.asyncio
    async def test_get_query_analytics_comprehensive_metrics(self):
        """
        GIVEN a QueryEngine instance with cached query data
        AND multiple queries processed and cached
        WHEN get_query_analytics is called
        THEN expect analytics dict containing:
            - 'total_queries': int (total number of queries processed)
            - 'query_types': dict (distribution of query types with counts)
            - 'average_processing_time': float (mean processing time in seconds)
            - 'average_results_per_query': float (mean number of results per query)
            - 'cache_size': int (number of cached query responses)
            - 'embedding_cache_size': int (number of cached embeddings)
        """
        # Setup query cache with varied data
        self.query_engine.query_cache = {
            "query1": create_mock_query_response("test1", "entity_search", 5, 0.1),
            "query2": create_mock_query_response("test2", "relationship_search", 3, 0.2),
            "query3": create_mock_query_response("test3", "entity_search", 7, 0.15),
            "query4": create_mock_query_response("test4", "semantic_search", 2, 0.25),
        }
        
        # Setup embedding cache
        self.query_engine.embedding_cache = {
            "embed1": [0.1, 0.2, 0.3],
            "embed2": [0.4, 0.5, 0.6],
            "embed3": [0.7, 0.8, 0.9]
        }
        
        # Execute method
        analytics = await self.query_engine.get_query_analytics()
        
        # Verify comprehensive metrics
        assert isinstance(analytics, dict)
        assert analytics["total_queries"] == 4
        
        expected_query_types = {
            "entity_search": 2,
            "relationship_search": 1,
            "semantic_search": 1
        }
        assert analytics["query_types"] == expected_query_types
        
        # Average processing time: (0.1 + 0.2 + 0.15 + 0.25) / 4 = 0.175
        assert abs(analytics["average_processing_time"] - 0.175) < 0.001
        
        # Average results per query: (5 + 3 + 7 + 2) / 4 = 4.25
        assert abs(analytics["average_results_per_query"] - 4.25) < 0.001
        
        assert analytics["cache_size"] == 4
        assert analytics["embedding_cache_size"] == 3

    @pytest.mark.asyncio
    async def test_get_query_analytics_no_query_data_available(self):
        """
        GIVEN a QueryEngine instance with no processed queries
        AND empty query cache
        WHEN get_query_analytics is called
        THEN expect:
            - {'message': 'No query data available'} returned
            - Graceful handling of empty cache
            - No exceptions raised
        """
        # Ensure empty caches
        self.query_engine.query_cache = {}
        self.query_engine.embedding_cache = {}
        
        # Execute method
        analytics = await self.query_engine.get_query_analytics()
        
        # Verify empty cache handling
        assert analytics == {'message': 'No query data available'}

    @pytest.mark.asyncio
    async def test_get_query_analytics_query_type_distribution(self):
        """
        GIVEN a QueryEngine instance with varied query types in cache
        AND queries of types: entity_search, semantic_search, relationship_search, etc.
        WHEN get_query_analytics is called
        THEN expect:
            - 'query_types' dict with accurate counts for each type
            - All query types represented in distribution
            - Counts match actual cached queries
        """
        # Setup cache with diverse query types
        self.query_engine.query_cache = {
            "q1": create_mock_query_response("test1", "entity_search", 1, 0.1),
            "q2": create_mock_query_response("test2", "entity_search", 1, 0.1),
            "q3": create_mock_query_response("test3", "entity_search", 1, 0.1),
            "q4": create_mock_query_response("test4", "relationship_search", 1, 0.1),
            "q5": create_mock_query_response("test5", "relationship_search", 1, 0.1),
            "q6": create_mock_query_response("test6", "semantic_search", 1, 0.1),
            "q7": create_mock_query_response("test7", "document_search", 1, 0.1),
            "q8": create_mock_query_response("test8", "cross_document", 1, 0.1),
            "q9": create_mock_query_response("test9", "graph_traversal", 1, 0.1),
        }
        self.query_engine.embedding_cache = {}
        
        analytics = await self.query_engine.get_query_analytics()
        
        expected_distribution = {
            "entity_search": 3,
            "relationship_search": 2,
            "semantic_search": 1,
            "document_search": 1,
            "cross_document": 1,
            "graph_traversal": 1
        }
        
        assert analytics["query_types"] == expected_distribution
        assert analytics["total_queries"] == 9

    @pytest.mark.asyncio
    async def test_get_query_analytics_processing_time_calculation(self):
        """
        GIVEN a QueryEngine instance with cached queries having processing times
        AND queries with known processing times
        WHEN get_query_analytics is called
        THEN expect:
            - 'average_processing_time' accurately calculated
            - Mean of all cached query processing times
            - Time measurement includes full query pipeline
        """
        # Setup cache with specific processing times
        processing_times = [0.05, 0.12, 0.18, 0.09, 0.21]
        self.query_engine.query_cache = {}
        
        for i, time in enumerate(processing_times):
            self.query_engine.query_cache[f"query_{i}"] = create_mock_query_response(
                f"test_{i}", "entity_search", 1, time
            )
        
        self.query_engine.embedding_cache = {}
        
        analytics = await self.query_engine.get_query_analytics()
        
        expected_avg_time = sum(processing_times) / len(processing_times)  # 0.13
        assert abs(analytics["average_processing_time"] - expected_avg_time) < 0.001

    @pytest.mark.asyncio
    async def test_get_query_analytics_results_per_query_calculation(self):
        """
        GIVEN a QueryEngine instance with cached queries having varying result counts
        AND queries returning different numbers of results
        WHEN get_query_analytics is called
        THEN expect:
            - 'average_results_per_query' accurately calculated
            - Mean of result counts across all cached queries
            - Calculation based on actual returned results
        """
        # Setup cache with varying result counts
        result_counts = [1, 5, 10, 3, 8, 2, 6]
        self.query_engine.query_cache = {}
        
        for i, count in enumerate(result_counts):
            self.query_engine.query_cache[f"query_{i}"] = create_mock_query_response(
                f"test_{i}", "entity_search", count, 0.1
            )
        
        self.query_engine.embedding_cache = {}
        
        analytics = await self.query_engine.get_query_analytics()
        
        expected_avg_results = sum(result_counts) / len(result_counts)  # 5.0
        assert abs(analytics["average_results_per_query"] - expected_avg_results) < 0.001

    @pytest.mark.asyncio
    async def test_get_query_analytics_cache_size_accuracy(self):
        """
        GIVEN a QueryEngine instance with known cache contents
        AND specific number of cached queries and embeddings
        WHEN get_query_analytics is called
        THEN expect:
            - 'cache_size' matches actual query cache size
            - 'embedding_cache_size' matches actual embedding cache size
            - Cache size metrics accurate and current
        """
        # Setup known cache sizes
        query_cache_size = 15
        embedding_cache_size = 8
        
        self.query_engine.query_cache = {}
        for i in range(query_cache_size):
            self.query_engine.query_cache[f"query_{i}"] = create_mock_query_response(
                f"test_{i}", "entity_search", 1, 0.1
            )
        
        self.query_engine.embedding_cache = {}
        for i in range(embedding_cache_size):
            self.query_engine.embedding_cache[f"embed_{i}"] = [0.1, 0.2, 0.3]
        
        analytics = await self.query_engine.get_query_analytics()
        
        assert analytics["cache_size"] == query_cache_size
        assert analytics["embedding_cache_size"] == embedding_cache_size

    @pytest.mark.asyncio
    async def test_get_query_analytics_corrupted_cache_data(self):
        """
        GIVEN a QueryEngine instance with corrupted cache data
        AND cache containing invalid or corrupted entries
        WHEN get_query_analytics is called
        THEN expect RuntimeError to be raised
        """
        # Setup cache with corrupted data (missing required attributes)
        corrupted_response = Mock()
        del corrupted_response.processing_time  # Remove required attribute
        
        self.query_engine.query_cache = {
            "valid": create_mock_query_response("test", "entity_search", 1, 0.1),
            "corrupted": corrupted_response
        }
        self.query_engine.embedding_cache = {}
        
        with pytest.raises(RuntimeError, match="Cache data is corrupted"):
            await self.query_engine.get_query_analytics()

    @pytest.mark.asyncio
    async def test_get_query_analytics_missing_timing_information(self):
        """
        GIVEN a QueryEngine instance with cached queries missing processing times
        AND some QueryResponse objects lacking processing_time
        WHEN get_query_analytics is called
        THEN expect RuntimeError to be raised
        """
        # Create response with None processing_time
        response_without_time = create_mock_query_response("test", "entity_search", 1, 0.1)
        response_without_time.processing_time = None
        
        self.query_engine.query_cache = {
            "valid": create_mock_query_response("test1", "entity_search", 1, 0.1),
            "missing_time": response_without_time
        }
        self.query_engine.embedding_cache = {}
        
        # Missing this key is considered a corruption.
        with pytest.raises(RuntimeError, match="Cache data is corrupted"):
            await self.query_engine.get_query_analytics()

    @pytest.mark.asyncio
    async def test_get_query_analytics_performance_monitoring_insights(self):
        """
        GIVEN a QueryEngine instance with comprehensive query history
        AND queries with varying performance characteristics
        WHEN get_query_analytics is called
        THEN expect:
            - Analytics suitable for performance monitoring
            - Insights into query patterns and system usage
            - Metrics useful for optimization decisions
        """
        # Setup realistic performance data
        self.query_engine.query_cache = {
            "fast_query_1": create_mock_query_response("q1", "entity_search", 2, 0.05),
            "fast_query_2": create_mock_query_response("q2", "entity_search", 1, 0.03),
            "medium_query_1": create_mock_query_response("q3", "semantic_search", 8, 0.15),
            "medium_query_2": create_mock_query_response("q4", "relationship_search", 5, 0.12),
            "slow_query_1": create_mock_query_response("q5", "graph_traversal", 15, 0.45),
            "slow_query_2": create_mock_query_response("q6", "cross_document", 20, 0.38),
        }
        self.query_engine.embedding_cache = {f"embed_{i}": [0.1] * 10 for i in range(25)}
        
        analytics = await self.query_engine.get_query_analytics()
        
        # Verify analytics provide performance insights
        assert analytics["total_queries"] == 6
        assert analytics["average_processing_time"] > 0.15  # Should reflect slower queries
        assert analytics["average_results_per_query"] > 8.0  # Should reflect high result counts
        assert "entity_search" in analytics["query_types"]
        assert "graph_traversal" in analytics["query_types"]
        
        # Cache utilization insights
        assert analytics["cache_size"] == 6
        assert analytics["embedding_cache_size"] == 25

    @pytest.mark.asyncio
    async def test_get_query_analytics_user_behavior_patterns(self):
        """
        GIVEN a QueryEngine instance with diverse query patterns
        AND queries representing different user behaviors
        WHEN get_query_analytics is called
        THEN expect:
            - Query type distribution reflects user behavior patterns
            - Analytics help understand user needs
            - Pattern analysis supports UX improvements
        """
        # Simulate user behavior: mostly entity searches, some semantic, occasional complex
        user_behavior_cache = {}
        
        # Heavy entity search usage (typical user behavior)
        for i in range(50):
            user_behavior_cache[f"entity_{i}"] = create_mock_query_response(
                f"entity_query_{i}", "entity_search", 3, 0.08
            )
        
        # Moderate semantic search usage
        for i in range(20):
            user_behavior_cache[f"semantic_{i}"] = create_mock_query_response(
                f"semantic_query_{i}", "semantic_search", 8, 0.18
            )
        
        # Light complex query usage
        for i in range(5):
            user_behavior_cache[f"complex_{i}"] = create_mock_query_response(
                f"complex_query_{i}", "graph_traversal", 12, 0.35
            )
        
        self.query_engine.query_cache = user_behavior_cache
        self.query_engine.embedding_cache = {}
        
        analytics = await self.query_engine.get_query_analytics()
        
        # Verify behavior pattern insights
        assert analytics["total_queries"] == 75
        assert analytics["query_types"]["entity_search"] == 50  # Most common
        assert analytics["query_types"]["semantic_search"] == 20  # Moderate
        assert analytics["query_types"]["graph_traversal"] == 5   # Least common
        
        # Performance reflects usage patterns
        assert analytics["average_processing_time"] < 0.15  # Dominated by fast entity queries

    @pytest.mark.asyncio
    async def test_get_query_analytics_system_health_monitoring(self):
        """
        GIVEN a QueryEngine instance with performance data
        AND queries with timing and result metrics
        WHEN get_query_analytics is called
        THEN expect:
            - Analytics support system health monitoring
            - Performance metrics indicate system status
            - Health indicators available for alerting
        """
        # Setup health monitoring scenario with performance degradation
        healthy_queries = {f"healthy_{i}": create_mock_query_response(f"q{i}", "entity_search", 5, 0.08) for i in range(80)}
        degraded_queries = {f"slow_{i}": create_mock_query_response(f"q{i}", "entity_search", 5, 0.25) for i in range(20)}
        
        self.query_engine.query_cache = {**healthy_queries, **degraded_queries}
        self.query_engine.embedding_cache = {f"embed_{i}": [0.1] * 5 for i in range(100)}
        
        analytics = await self.query_engine.get_query_analytics()
        
        # Health indicators for monitoring
        assert analytics["total_queries"] == 100
        assert 0.10 < analytics["average_processing_time"] < 0.12  # Mix of healthy and degraded
        assert analytics["cache_size"] == 100  # Cache utilization
        assert analytics["embedding_cache_size"] == 100  # Memory usage indicator
        
        # System load indicators
        total_processing_time = analytics["average_processing_time"] * analytics["total_queries"]
        assert total_processing_time > 10.0  # Indicates system load

    @pytest.mark.asyncio
    async def test_get_query_analytics_memory_usage_insights(self):
        """
        GIVEN a QueryEngine instance with cache data
        AND embedding and query caches with known sizes
        WHEN get_query_analytics is called
        THEN expect:
            - Cache metrics indicate memory usage patterns
            - Memory optimization opportunities identified
            - Cache utilization insights provided
        """
        # Setup large cache scenario for memory analysis
        large_query_cache = {}
        for i in range(500):
            large_query_cache[f"query_{i}"] = create_mock_query_response(
                f"test_{i}", "semantic_search", 10, 0.15
            )
        
        large_embedding_cache = {}
        for i in range(1000):
            large_embedding_cache[f"embed_{i}"] = [0.1] * 384  # Typical embedding size
        
        self.query_engine.query_cache = large_query_cache
        self.query_engine.embedding_cache = large_embedding_cache
        
        analytics = await self.query_engine.get_query_analytics()
        
        # Memory usage insights
        assert analytics["cache_size"] == 500  # Query cache memory usage
        assert analytics["embedding_cache_size"] == 1000  # Embedding cache memory usage
        assert analytics["total_queries"] == 500
        
        # Cache efficiency indicators
        cache_hit_potential = analytics["cache_size"] / analytics["total_queries"]
        assert cache_hit_potential == 1.0  # Perfect cache retention

    @pytest.mark.asyncio
    async def test_get_query_analytics_optimization_decision_support(self):
        """
        GIVEN a QueryEngine instance with comprehensive analytics
        AND sufficient query history for analysis
        WHEN get_query_analytics is called
        THEN expect:
            - Analytics support optimization decisions
            - Performance bottlenecks identifiable
            - Optimization priorities clear from metrics
        """
        # Setup scenario showing optimization opportunities
        bottleneck_cache = {}
        
        # Fast queries that could benefit from better caching
        for i in range(30):
            bottleneck_cache[f"fast_{i}"] = create_mock_query_response(
                f"fast_query_{i}", "entity_search", 2, 0.05
            )
        
        # Slow semantic queries that need optimization
        for i in range(10):
            bottleneck_cache[f"slow_semantic_{i}"] = create_mock_query_response(
                f"semantic_query_{i}", "semantic_search", 15, 0.40
            )
        
        # Very slow graph queries that need architectural changes
        for i in range(5):
            bottleneck_cache[f"very_slow_{i}"] = create_mock_query_response(
                f"graph_query_{i}", "graph_traversal", 25, 0.80
            )
        
        self.query_engine.query_cache = bottleneck_cache
        self.query_engine.embedding_cache = {f"embed_{i}": [0.1] * 100 for i in range(15)}
        
        analytics = await self.query_engine.get_query_analytics()
        
        # Optimization decision support
        assert analytics["total_queries"] == 45
        
        # Performance bottleneck identification
        query_types = analytics["query_types"]
        assert query_types["entity_search"] == 30  # High volume, optimization opportunity
        assert query_types["semantic_search"] == 10  # Medium volume, performance issue
        assert query_types["graph_traversal"] == 5   # Low volume, severe performance issue
        
        # Average time indicates mixed performance
        assert 0.15 < analytics["average_processing_time"] < 0.25

    @pytest.mark.asyncio
    async def test_get_query_analytics_async_method_behavior(self):
        """
        GIVEN a QueryEngine instance
        AND analytics data available
        WHEN get_query_analytics is called as async method
        THEN expect:
            - Method executes asynchronously without blocking
            - Async/await pattern supported correctly
            - Concurrent execution possible
        """
        # Setup test data
        self.query_engine.query_cache = {
            "test": create_mock_query_response("test", "entity_search", 1, 0.1)
        }
        self.query_engine.embedding_cache = {}
        
        # Test async execution
        coroutine = self.query_engine.get_query_analytics()
        assert asyncio.iscoroutine(coroutine)
        
        # Test concurrent execution
        tasks = [
            self.query_engine.get_query_analytics(),
            self.query_engine.get_query_analytics(),
            self.query_engine.get_query_analytics()
        ]
        
        results = await asyncio.gather(*tasks)
        
        # All results should be identical and valid
        assert len(results) == 3
        for result in results:
            assert result["total_queries"] == 1
            assert result["cache_size"] == 1

    @pytest.mark.asyncio
    async def test_get_query_analytics_data_consistency(self):
        """
        GIVEN a QueryEngine instance with stable cache contents
        AND multiple calls to get_query_analytics
        WHEN get_query_analytics is called repeatedly
        THEN expect:
            - Consistent analytics across calls (if cache unchanged)
            - Deterministic calculation results
            - Data integrity maintained
        """
        # Setup stable cache
        self.query_engine.query_cache = {
            "q1": create_mock_query_response("test1", "entity_search", 5, 0.12),
            "q2": create_mock_query_response("test2", "relationship_search", 3, 0.18),
            "q3": create_mock_query_response("test3", "semantic_search", 8, 0.25),
        }
        self.query_engine.embedding_cache = {"e1": [0.1], "e2": [0.2]}
        
        # Multiple calls
        result1 = await self.query_engine.get_query_analytics()
        result2 = await self.query_engine.get_query_analytics()
        result3 = await self.query_engine.get_query_analytics()
        
        # Verify consistency
        assert result1 == result2 == result3
        assert result1["total_queries"] == 3
        assert result1["cache_size"] == 3
        assert result1["embedding_cache_size"] == 2
        
        # Verify deterministic calculations
        expected_avg_time = (0.12 + 0.18 + 0.25) / 3
        assert abs(result1["average_processing_time"] - expected_avg_time) < 0.001

    @pytest.mark.asyncio
    async def test_get_query_analytics_large_cache_performance(self):
        """
        GIVEN a QueryEngine instance with large cache sizes
        AND thousands of cached queries and embeddings
        WHEN get_query_analytics is called
        THEN expect:
            - Method completes within reasonable time
            - Performance scales appropriately with cache size
            - Memory usage during calculation controlled
        """
        # Setup large cache
        large_cache_size = 2000
        large_embedding_cache_size = 5000
        
        self.query_engine.query_cache = {}
        for i in range(large_cache_size):
            self.query_engine.query_cache[f"query_{i}"] = create_mock_query_response(
                f"test_{i}", 
                ["entity_search", "semantic_search", "relationship_search"][i % 3],
                i % 10 + 1,  # 1-10 results
                (i % 20) / 100.0  # 0.00-0.19 processing time
            )
        
        self.query_engine.embedding_cache = {}
        for i in range(large_embedding_cache_size):
            self.query_engine.embedding_cache[f"embed_{i}"] = [0.1] * 50
        
        # Measure execution time
        start_time = asyncio.get_event_loop().time()
        analytics = await self.query_engine.get_query_analytics()
        end_time = asyncio.get_event_loop().time()
        
        execution_time = end_time - start_time
        
        # Performance expectations
        assert execution_time < 1.0  # Should complete within 1 second
        assert analytics["total_queries"] == large_cache_size
        assert analytics["cache_size"] == large_cache_size
        assert analytics["embedding_cache_size"] == large_embedding_cache_size
        
        # Verify calculations are still accurate with large dataset
        assert isinstance(analytics["average_processing_time"], float)
        assert isinstance(analytics["average_results_per_query"], float)

    @pytest.mark.asyncio
    async def test_get_query_analytics_real_time_metrics(self):
        """
        GIVEN a QueryEngine instance with recently updated cache
        AND new queries added to cache since last analytics call
        WHEN get_query_analytics is called
        THEN expect:
            - Analytics reflect current cache state
            - Real-time metrics without stale data
            - Most recent query data included in calculations
        """
        # Initial cache state
        self.query_engine.query_cache = {
            "old1": create_mock_query_response("old1", "entity_search", 3, 0.1),
            "old2": create_mock_query_response("old2", "entity_search", 4, 0.12),
        }
        self.query_engine.embedding_cache = {"old_embed": [0.1]}
        
        # First analytics call
        initial_analytics = await self.query_engine.get_query_analytics()
        assert initial_analytics["total_queries"] == 2
        assert initial_analytics["cache_size"] == 2
        assert initial_analytics["embedding_cache_size"] == 1
        
        # Add new queries to cache (simulating real-time updates)
        self.query_engine.query_cache["new1"] = create_mock_query_response("new1", "semantic_search", 8, 0.25)
        self.query_engine.query_cache["new2"] = create_mock_query_response("new2", "relationship_search", 2, 0.15)
        self.query_engine.embedding_cache["new_embed1"] = [0.2]
        self.query_engine.embedding_cache["new_embed2"] = [0.3]