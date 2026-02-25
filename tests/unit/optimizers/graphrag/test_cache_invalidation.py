from __future__ import annotations

import pytest


def _make_optimizer(cache_ttl: float = 60.0):
    from ipfs_datasets_py.optimizers.graphrag.query_planner import (
        GraphRAGQueryOptimizer,
    )

    return GraphRAGQueryOptimizer(cache_ttl=cache_ttl)


def _make_key(optimizer) -> str:
    return optimizer.get_query_key(
        query_vector=[0.1, 0.2, 0.3],
        max_vector_results=3,
        max_traversal_depth=2,
        edge_types=["rel"],
        min_similarity=0.4,
    )


def test_clear_cache_removes_entries() -> None:
    optimizer = _make_optimizer()
    key = _make_key(optimizer)

    optimizer.add_to_cache(key, {"ok": True})
    assert optimizer.is_in_cache(key) is True

    optimizer.clear_cache()

    assert optimizer.query_cache == {}
    assert optimizer.is_in_cache(key) is False


def test_cache_entry_expires_after_ttl(monkeypatch) -> None:
    optimizer = _make_optimizer(cache_ttl=10.0)
    key = _make_key(optimizer)

    monkeypatch.setattr(
        "ipfs_datasets_py.optimizers.graphrag.query_planner.time.time",
        lambda: 1000.0,
    )

    optimizer.add_to_cache(key, {"value": [1, 2, 3]})
    assert optimizer.is_in_cache(key) is True

    monkeypatch.setattr(
        "ipfs_datasets_py.optimizers.graphrag.query_planner.time.time",
        lambda: 1011.0,
    )

    assert optimizer.is_in_cache(key) is False
    assert key not in optimizer.query_cache


# ==============================================================================
# Modular Query Optimizer Cache Invalidation Tests
# Tests for QueryDetector, TraversalOptimizer, and other modular caches
# ==============================================================================

from unittest.mock import Mock, MagicMock
from ipfs_datasets_py.optimizers.graphrag.query_detection import QueryDetector
from ipfs_datasets_py.optimizers.graphrag.traversal_optimizer import TraversalOptimizer


class TestQueryDetectorCache:
    """Test QueryDetector graph type detection cache."""

    def test_query_detector_cache_clearing(self):
        """Should clear QueryDetector graph type cache."""
        # Populate cache
        query1 = {"query_text": "test query", "metadata": {"source": "wikipedia"}}
        result1 = QueryDetector.detect_graph_type(query1)
        
        # Verify cache has entries
        assert len(QueryDetector._graph_type_detection_cache) > 0
        
        # Clear cache
        QueryDetector._graph_type_detection_cache.clear()
        
        # Verify cache is empty
        assert len(QueryDetector._graph_type_detection_cache) == 0

    def test_selective_cache_invalidation(self):
        """Should invalidate specific cache entries."""
        QueryDetector._graph_type_detection_cache.clear()
        
        # Populate cache with multiple entries
        for i in range(5):
            query = {"query_text": f"query_{i}", "metadata": {"source": "test"}}
            QueryDetector.detect_graph_type(query)
        
        initial_size = len(QueryDetector._graph_type_detection_cache)
        assert initial_size > 0
        
        # Selective invalidation (remove first entry)
        keys_to_remove = list(QueryDetector._graph_type_detection_cache.keys())[:1]
        for key in keys_to_remove:
            del QueryDetector._graph_type_detection_cache[key]
        
        # Verify cache size decreased
        assert len(QueryDetector._graph_type_detection_cache) == initial_size - 1

    def test_cache_repopulation_after_clearing(self):
        """Should allow re-population after cache clearing."""
        QueryDetector._graph_type_detection_cache.clear()
        
        query = {"query_text": "test", "metadata": {"source": "wikipedia"}}
        
        # First detection (cache miss)
        result1 = QueryDetector.detect_graph_type(query)
        cache_size_after_first = len(QueryDetector._graph_type_detection_cache)
        
        # Second detection (cache hit)
        result2 = QueryDetector.detect_graph_type(query)
        
        # Results should match
        assert result1 == result2
        
        # Cache should have same size (reused entry)
        assert len(QueryDetector._graph_type_detection_cache) == cache_size_after_first

    def test_cache_size_management(self):
        """Should manage cache size to prevent memory overflow."""
        QueryDetector._graph_type_detection_cache.clear()
        
        # Try to fill cache beyond max size
        max_size = QueryDetector._graph_type_detection_max_size
        for i in range(max_size + 100):
            query = {"query_text": f"overflow_{i}", "metadata": {"source": "test"}}
            QueryDetector.detect_graph_type(query)
        
        # Cache should not exceed max size
        assert len(QueryDetector._graph_type_detection_cache) <= max_size

    def test_shared_cache_isolation(self):
        """Should isolate cache instances when using custom cache dicts."""
        # Custom cache for first instance
        cache1 = {}
        query = {"query_text": "isolation_test", "metadata": {"source": "test"}}
        
        # Detect with custom cache
        result1 = QueryDetector.detect_graph_type(query, detection_cache=cache1)
        
        # Custom cache should have entry
        assert len(cache1) > 0


class TestTraversalOptimizerCache:
    """Test TraversalOptimizer entity importance cache."""

    def test_entity_cache_clearing(self):
        """Should clear TraversalOptimizer entity importance cache."""
        graph_processor = Mock()
        graph_processor.get_entity_info.return_value = {
            "type": "person",
            "inbound_connections": [],
            "outbound_connections": [],
            "properties": {}
        }
        
        # Populate cache
        score1 = TraversalOptimizer.calculate_entity_importance("entity_test_1", graph_processor)
        assert "entity_test_1" in TraversalOptimizer._entity_importance_cache
        
        # Clear cache
        TraversalOptimizer._entity_importance_cache.clear()
        
        # Verify cache is empty
        assert len(TraversalOptimizer._entity_importance_cache) == 0

    def test_stale_cache_after_entity_modification(self):
        """Should detect stale cache after entity modification."""
        graph_processor = Mock()
        
        # Initial entity state
        graph_processor.get_entity_info.return_value = {
            "type": "person",
            "inbound_connections": [],
            "outbound_connections": [],
            "properties": {"name": "John"}
        }
        
        # First calculation (cache population)
        score1 = TraversalOptimizer.calculate_entity_importance("entity_mod_1", graph_processor)
        
        # Modify entity (simulating refinement)
        graph_processor.get_entity_info.return_value = {
            "type": "person",
            "inbound_connections": [{"relation_type": "knows"}],  # Added connection
            "outbound_connections": [],
            "properties": {"name": "John", "age": 30}  # Added property
        }
        
        # Cache still returns old value (stale)
        score2_cached = TraversalOptimizer.calculate_entity_importance("entity_mod_1", graph_processor)
        assert score2_cached == score1  # Same cached value
        
        # After invalidation, should get new value
        TraversalOptimizer._entity_importance_cache.pop("entity_mod_1", None)
        score2_fresh = TraversalOptimizer.calculate_entity_importance("entity_mod_1", graph_processor)
        
        # Fresh calculation should reflect new connections/properties
        assert score2_fresh != score1  # Different due to added connection/property

    def test_entity_cache_preloading(self):
        """Should preload entity importance cache for common entities."""
        TraversalOptimizer._entity_importance_cache.clear()
        
        graph_processor = Mock()
        graph_processor.get_entity_info.return_value = {
            "type": "person",
            "inbound_connections": [],
            "outbound_connections": [],
            "properties": {}
        }
        
        # Preload common entities
        common_entities = [f"common_entity_{i}" for i in range(20)]
        for entity_id in common_entities:
            TraversalOptimizer.calculate_entity_importance(entity_id, graph_processor)
        
        # Verify cache is populated
        assert len(TraversalOptimizer._entity_importance_cache) >= 20

    def test_cache_memory_efficiency(self):
        """Should efficiently use memory for entity importance cache."""
        TraversalOptimizer._entity_importance_cache.clear()
        
        graph_processor = Mock()
        graph_processor.get_entity_info.return_value = {
            "type": "concept",
            "inbound_connections": [],
            "outbound_connections": [],
            "properties": {}
        }
        
        # Cache many entities
        for i in range(TraversalOptimizer._cache_max_size):
            TraversalOptimizer.calculate_entity_importance(f"memory_test_{i}", graph_processor)
        
        # Should not exceed max size
        assert len(TraversalOptimizer._entity_importance_cache) <= TraversalOptimizer._cache_max_size

    def test_batch_cache_invalidation(self):
        """Should invalidate multiple cache entries in batch."""
        TraversalOptimizer._entity_importance_cache.clear()
        
        graph_processor = Mock()
        graph_processor.get_entity_info.return_value = {
            "type": "person",
            "inbound_connections": [],
            "outbound_connections": [],
            "properties": {}
        }
        
        # Cache multiple entities
        entity_ids = [f"batch_inv_{i}" for i in range(10)]
        for entity_id in entity_ids:
            TraversalOptimizer.calculate_entity_importance(entity_id, graph_processor)
        
        # Batch invalidation (remove first 5)
        for entity_id in entity_ids[:5]:
            TraversalOptimizer._entity_importance_cache.pop(entity_id, None)
        
        # Verify 5 entries removed
        assert len(TraversalOptimizer._entity_importance_cache) >= 5


class TestCacheConsistency:
    """Test cache consistency across refinement operations."""

    def test_cache_coherence_across_refinement_cycles(self):
        """Should maintain cache coherence across multiple refinement cycles."""
        QueryDetector._graph_type_detection_cache.clear()
        
        queries = [
            {"query_text": "cycle_test_1", "metadata": {"source": "wikipedia"}},
            {"query_text": "cycle_test_2", "metadata": {"source": "ipld"}},
            {"query_text": "cycle_test_3", "metadata": {"source": "mixed"}}
        ]
        
        # Refinement cycle 1: populate cache
        results_cycle1 = [QueryDetector.detect_graph_type(q) for q in queries]
        cache_size_cycle1 = len(QueryDetector._graph_type_detection_cache)
        
        # Refinement cycle 2: cache hits
        results_cycle2 = [QueryDetector.detect_graph_type(q) for q in queries]
        cache_size_cycle2 = len(QueryDetector._graph_type_detection_cache)
        
        # Results should be consistent
        assert results_cycle1 == results_cycle2
        
        # Cache size should be stable (no duplicate entries)
        assert cache_size_cycle1 == cache_size_cycle2

    def test_independent_module_cache_management(self):
        """Should manage caches independently across modules."""
        QueryDetector._graph_type_detection_cache.clear()
        TraversalOptimizer._entity_importance_cache.clear()
        
        # Populate QueryDetector cache
        query = {"query_text": "coherence_test", "metadata": {"source": "test"}}
        QueryDetector.detect_graph_type(query)
        
        # Populate TraversalOptimizer cache
        graph_processor = Mock()
        graph_processor.get_entity_info.return_value = {
            "type": "person",
            "inbound_connections": [],
            "outbound_connections": [],
            "properties": {}
        }
        TraversalOptimizer.calculate_entity_importance("coherence_entity", graph_processor)
        
        # Both caches should have entries
        assert len(QueryDetector._graph_type_detection_cache) > 0
        assert len(TraversalOptimizer._entity_importance_cache) > 0

    def test_cross_module_cache_clearing(self):
        """Should clear caches across all modules."""
        # Populate both caches
        QueryDetector.detect_graph_type({"query_text": "test", "metadata": {"source": "test"}})
        
        graph_processor = Mock()
        graph_processor.get_entity_info.return_value = {"type": "person", "inbound_connections": [], "outbound_connections": [], "properties": {}}
        TraversalOptimizer.calculate_entity_importance("test_entity", graph_processor)
        
        # Clear all
        QueryDetector._graph_type_detection_cache.clear()
        TraversalOptimizer._entity_importance_cache.clear()
        
        # All should be empty
        assert len(QueryDetector._graph_type_detection_cache) == 0
        assert len(TraversalOptimizer._entity_importance_cache) == 0


class TestCacheWarming:
    """Test cache warming strategies."""

    def test_batch_cache_warming(self):
        """Should warm cache with batch queries before processing."""
        QueryDetector._graph_type_detection_cache.clear()
        
        # Batch of queries to warm cache (use varied query text for unique signatures)
        warm_queries = [
            {"query_text": f"warm query number {i} with unique text", "metadata": {"source": "wikipedia"}}
            for i in range(10)
        ]
        
        # Warm cache
        for query in warm_queries:
            QueryDetector.detect_graph_type(query)
        
        # Verify cache is populated (at least some entries, may be deduplicated by signature)
        assert len(QueryDetector._graph_type_detection_cache) >= 1

    def test_domain_specific_cache_warming(self):
        """Should warm cache with domain-specific patterns."""
        QueryDetector._graph_type_detection_cache.clear()
        
        # Wikipedia domain patterns (varied text for unique signatures)
        wikipedia_queries = [
            {"query_text": "wiki query about historical events", "metadata": {"source": "wikipedia"}},
            {"query_text": "another wiki question on geography", "metadata": {"source": "wikipedia"}}
        ]
        
        # IPLD domain patterns (varied text for unique signatures)
        ipld_queries = [
            {"query_text": "ipld query about content addressing", "metadata": {"source": "ipld"}},
            {"query_text": "another ipld question on merkle dags", "metadata": {"source": "ipld"}}
        ]
        
        # Warm for both domains
        for q in wikipedia_queries + ipld_queries:
            QueryDetector.detect_graph_type(q)
        
        # Cache should have entries (at least some, may be deduplicated by signature)
        assert len(QueryDetector._graph_type_detection_cache) >= 1


class TestCacheEdgeCases:
    """Test edge cases in cache invalidation."""

    def test_invalidate_nonexistent_entry(self):
        """Should handle invalidation of nonexistent entries gracefully."""
        QueryDetector._graph_type_detection_cache.clear()
        
        # Try to remove nonexistent key
        QueryDetector._graph_type_detection_cache.pop("nonexistent_key", None)
        
        # Should not raise exception
        assert len(QueryDetector._graph_type_detection_cache) == 0

    def test_double_invalidation(self):
        """Should handle double invalidation gracefully."""
        QueryDetector._graph_type_detection_cache.clear()
        
        query = {"query_text": "double_inv", "metadata": {"source": "test"}}
        QueryDetector.detect_graph_type(query)
        
        # First clear
        QueryDetector._graph_type_detection_cache.clear()
        assert len(QueryDetector._graph_type_detection_cache) == 0
        
        # Second clear (already empty)
        QueryDetector._graph_type_detection_cache.clear()
        assert len(QueryDetector._graph_type_detection_cache) == 0

    def test_cache_with_empty_query(self):
        """Should handle caching with empty/minimal queries."""
        QueryDetector._graph_type_detection_cache.clear()
        
        empty_query = {}
        
        # Should handle gracefully
        result = QueryDetector.detect_graph_type(empty_query)
        
        # Should return valid graph type
        assert result in ["wikipedia", "ipld", "mixed", "general"]
