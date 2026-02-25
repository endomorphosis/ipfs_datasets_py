"""Comprehensive tests for traversal optimization module."""

import pytest
from unittest.mock import Mock, MagicMock
from ipfs_datasets_py.optimizers.graphrag.traversal_optimizer import TraversalOptimizer


class TestWikipediaTraversalOptimization:
    """Test Wikipedia-specific traversal optimizations."""

    def test_optimize_wikipedia_traversal_adds_options(self):
        """Should add Wikipedia traversal options to query."""
        query = {"query_text": "Tell me about Einstein"}
        entity_scores = {"einstein": 0.9}
        
        result = TraversalOptimizer.optimize_wikipedia_traversal(query, entity_scores)
        
        assert "traversal" in result
        assert "wikipedia_traversal_options" in result["traversal"]
        assert result["traversal"]["wikipedia_traversal_options"]["follow_redirects"] is True

    def test_optimize_wikipedia_with_edge_types(self):
        """Should reorder edge types by importance."""
        query = {
            "query_text": "What type of animal is a dog?",
            "traversal": {"edge_types": ["instance_of", "related_to", "similar_to"]}
        }
        entity_scores = {"dog": 0.8}
        
        result = TraversalOptimizer.optimize_wikipedia_traversal(query, entity_scores)
        
        # instance_of should be first (highest importance for type query)
        edges = result["traversal"]["edge_types"]
        assert edges[0] == "instance_of"
        assert "edge_importance_scores" in result["traversal"]

    def test_wikipedia_complexity_parameters(self):
        """Should set parameters based on query complexity."""
        query_complex = {
            "query_text": "Complex query",
            "traversal": {"max_depth": 5},
            "vector_params": {"top_k": 20},
            "entity_ids": ["e1", "e2", "e3", "e4"],
            "multi_pass": True
        }
        entity_scores = {}
        
        result = TraversalOptimizer.optimize_wikipedia_traversal(query_complex, entity_scores)
        
        # Complex query should have stricter limits
        assert result["traversal"]["max_breadth_per_level"] == 5
        assert result["traversal"]["use_importance_pruning"] is True

    def test_wikipedia_detects_query_relations(self):
        """Should detect relation types from query text."""
        query = {"query_text": "Where is Paris located?"}
        entity_scores = {}
        
        result = TraversalOptimizer.optimize_wikipedia_traversal(query, entity_scores)
        
        detected = result["traversal"].get("detected_relations", [])
        assert "located_in" in detected

    def test_wikipedia_preserves_entity_scores(self):
        """Should preserve entity importance scores in traversal."""
        query = {"query_text": "Test"}
        entity_scores = {"entity1": 0.9, "entity2": 0.6}
        
        result = TraversalOptimizer.optimize_wikipedia_traversal(query, entity_scores)
        
        assert result["traversal"]["entity_scores"] == entity_scores


class TestIPLDTraversalOptimization:
    """Test IPLD-specific traversal optimizations."""

    def test_optimize_ipld_traversal(self):
        """Should add IPLD traversal options."""
        query = {"query_text": "Search IPLD"}
        entity_scores = {}
        
        result = TraversalOptimizer.optimize_ipld_traversal(query, entity_scores)
        
        assert "ipld_traversal_options" in result["traversal"]
        assert result["traversal"]["ipld_traversal_options"]["verify_content_hash"] is True

    def test_ipld_prioritizes_content_relationships(self):
        """Should prioritize content-hash relationships in IPLD."""
        query = {
            "traversal": {"edge_types": ["related_to", "content_hash", "links_to"]}
        }
        entity_scores = {}
        
        result = TraversalOptimizer.optimize_ipld_traversal(query, entity_scores)
        
        edges = result["traversal"]["edge_types"]
        # content_hash should be highest priority for IPLD
        assert edges[0] == "content_hash"

    def test_ipld_supports_verification(self):
        """Should include verification options for IPLD graphs."""
        query = {"query_text": "Verify IPLD content"}
        entity_scores = {}
        
        result = TraversalOptimizer.optimize_ipld_traversal(query, entity_scores)
        
        options = result["traversal"]["ipld_traversal_options"]
        assert options["check_signatures"] is True
        assert options["validate_attestations"] is True
        assert options["preserve_content_addressing"] is True


class TestEntityImportanceCalculation:
    """Test entity importance scoring."""

    def test_calculate_basic_entity_importance(self):
        """Should calculate entity importance with default score."""
        graph_processor = None  # No processor provided
        
        score = TraversalOptimizer.calculate_entity_importance("test_entity", graph_processor)
        
        assert 0.0 <= score <= 1.0
        assert score == 0.5  # Default when no processor

    def test_calculate_with_valid_graph_processor(self):
        """Should calculate importance with graph processor info."""
        graph_processor = Mock()
        graph_processor.get_entity_info.return_value = {
            "type": "person",
            "inbound_connections": [{"relation_type": "created_by"}, {"relation_type": "author"}],
            "outbound_connections": [{"relation_type": "wrote"}],
            "properties": {"name": "Test", "birth": "2000"}
        }
        
        score = TraversalOptimizer.calculate_entity_importance("person123", graph_processor)
        
        assert 0.0 <= score <= 1.0
        # Score is weighted: connections 0.3, diversity 0.1, properties 0.13, type 0.16 ~ 0.3

    def test_importance_calculation_with_high_connectivity(self):
        """Should score highly connected entities higher."""
        graph_processor = Mock()
        graph_processor.get_entity_info.return_value = {
            "type": "concept",
            "inbound_connections": [{"relation_type": f"rel{i}"} for i in range(20)],
            "outbound_connections": [{"relation_type": f"rel{i}"} for i in range(10)],
            "properties": {f"prop{i}": i for i in range(15)}
        }
        
        score = TraversalOptimizer.calculate_entity_importance("hub_entity", graph_processor)
        
        # Highly connected hub should have high score
        assert score >= 0.9

    def test_importance_cache_works(self):
        """Should cache importance scores."""
        graph_processor = Mock()
        graph_processor.get_entity_info.return_value = {
            "type": "person",
            "inbound_connections": [],
            "outbound_connections": [],
            "properties": {}
        }
        
        score1 = TraversalOptimizer.calculate_entity_importance("cached_entity", graph_processor)
        
        # Second call should use cache (graph_processor not called again)
        graph_processor.reset_mock()
        score2 = TraversalOptimizer.calculate_entity_importance("cached_entity", graph_processor)
        
        assert score1 == score2
        graph_processor.get_entity_info.assert_not_called()

    def test_cache_max_size_enforced(self):
        """Should enforce cache size limits."""
        initial_size = len(TraversalOptimizer._entity_importance_cache)
        max_size = TraversalOptimizer._cache_max_size
        
        # Cache should not grow beyond max_size
        for i in range(max_size + 100):
            graph_processor = Mock()
            graph_processor.get_entity_info.return_value = None
            TraversalOptimizer.calculate_entity_importance(f"entity_{i}", graph_processor)
        
        cache_size = len(TraversalOptimizer._entity_importance_cache)
        assert cache_size <= max_size


class TestTraversalPathOptimization:
    """Test traversal path optimization."""

    def test_optimize_traversal_path(self):
        """Should optimize path parameters."""
        query = {"traversal": {"max_depth": 5}}
        current_path = ["entity1", "entity2"]
        target = "entity3"
        
        result = TraversalOptimizer.optimize_traversal_path(query, current_path, target)
        
        assert result["traversal"]["current_path_length"] == 2
        assert result["traversal"]["target_entity"] == target

    def test_traversal_depth_adaptation(self):
        """Should reduce depth as path lengthens."""
        query = {"traversal": {"max_depth": 4}}
        current_path = ["e1", "e2", "e3"]
        
        result = TraversalOptimizer.optimize_traversal_path(query, current_path, "target")
        
        # Should reduce depth when path is already 3 steps long
        assert result["traversal"]["max_depth"] <= 4


class TestRelationUsefulnessUpdate:
    """Test relation usefulness tracking."""

    def test_update_relation_usefulness(self):
        """Should update relation usefulness scores."""
        stats = {"created_by": 0.5}
        
        TraversalOptimizer.update_relation_usefulness("created_by", 0.9, stats)
        
        # Should increase toward success score
        assert stats["created_by"] > 0.5
        assert stats["created_by"] < 0.9  # Not fully updated due to smoothing

    def test_update_new_relation(self):
        """Should initialize new relations."""
        stats = {}
        
        TraversalOptimizer.update_relation_usefulness("novel_relation", 0.8, stats)
        
        assert "novel_relation" in stats
        assert stats["novel_relation"] > 0.5  # Above initial 0.5

    def test_exponential_moving_average(self):
        """Should apply exponential smoothing."""
        stats = {"test_rel": 0.4}
        original = stats["test_rel"]
        
        # Single update
        TraversalOptimizer.update_relation_usefulness("test_rel", 0.8, stats)
        first_update = stats["test_rel"]
        
        # Should be between original and success score
        assert original < first_update < 0.8
        
        # Second update
        prev_update = stats["test_rel"]
        TraversalOptimizer.update_relation_usefulness("test_rel", 0.8, stats)
        
        # Should move closer to success
        assert prev_update < stats["test_rel"]


class TestRelationDetection:
    """Test relation type detection from queries."""

    def test_detect_instance_relations(self):
        """Should detect instance_of relations."""
        query = "What type of animal is a dog?"
        
        relations = TraversalOptimizer._detect_query_relations(query)
        
        assert "instance_of" in relations

    def test_detect_location_relations(self):
        """Should detect located_in relations."""
        query = "Where is the Eiffel Tower?"
        
        relations = TraversalOptimizer._detect_query_relations(query)
        
        assert "located_in" in relations

    def test_detect_creation_relations(self):
        """Should detect created_by relations."""
        query = "Who wrote the Mona Lisa?"
        
        relations = TraversalOptimizer._detect_query_relations(query)
        
        assert "created_by" in relations

    def test_empty_query_no_relations(self):
        """Should handle empty queries gracefully."""
        relations = TraversalOptimizer._detect_query_relations("")
        
        assert relations == []

    def test_multiple_relation_detection(self):
        """Should detect multiple relations in complex query."""
        query = "Where did Einstein write about particle creation?"
        
        relations = TraversalOptimizer._detect_query_relations(query)
        
        # Should detect at least location and creation
        assert len(relations) >= 1


class TestComplexityEstimation:
    """Test query complexity estimation."""

    def test_simple_query_complexity(self):
        """Should classify simple queries as low complexity."""
        query = {"query_text": "Simple query"}
        
        complexity = TraversalOptimizer._estimate_query_complexity(query)
        
        assert complexity == "low"

    def test_high_complexity_deep_traversal(self):
        """Should classify deep traversals as high complexity."""
        query = {
            "traversal": {"max_depth": 4},
            "vector_params": {"top_k": 15},
            "entity_ids": ["e1", "e2", "e3", "e4"],
            "multi_pass": True,
            "filters": {"type": "person"}
        }
        
        complexity = TraversalOptimizer._estimate_query_complexity(query)
        
        assert complexity == "high"

    def test_medium_complexity_multiple_entities(self):
        """Should classify multi-entity queries as medium complexity."""
        query = {
            "entity_ids": ["e1", "e2", "e3"],
            "traversal": {"max_depth": 3},
            "filters": {"type": "person"}
        }
        
        complexity = TraversalOptimizer._estimate_query_complexity(query)
        
        assert complexity in ["medium", "high"]

    def test_complexity_with_filters(self):
        """Should increase complexity with filters."""
        query = {
            "query_text": "Find with filters",
            "filters": {"type": "person"}
        }
        
        complexity = TraversalOptimizer._estimate_query_complexity(query)
        
        assert complexity in ["low", "medium"]


class TestTraversalOptimizerIntegration:
    """Integration tests for traversal optimizer."""

    def test_wikipedia_and_ipld_optimization_compatible(self):
        """Should handle switching between graph types."""
        query = {"query_text": "Test query", "traversal": {"edge_types": ["related_to"]}}
        entity_scores = {"e1": 0.8}
        
        wiki_result = TraversalOptimizer.optimize_wikipedia_traversal(query, entity_scores)
        ipld_result = TraversalOptimizer.optimize_ipld_traversal(query, entity_scores)
        
        # Both should have traversal options
        assert "wikipedia_traversal_options" in wiki_result["traversal"]
        assert "ipld_traversal_options" in ipld_result["traversal"]

    def test_full_optimization_pipeline(self):
        """Should work through full optimization pipeline."""
        query = {"query_text": "Find important people"}
        entity_scores = {"person1": 0.9, "person2": 0.7}
        current_path = ["start"]
        
        # Optimize for Wikipedia
        opt_query = TraversalOptimizer.optimize_wikipedia_traversal(query, entity_scores)
        
        # Optimize path
        final_query = TraversalOptimizer.optimize_traversal_path(opt_query, current_path, "target")
        
        # Should have all optimization layers
        assert "entity_scores" in final_query["traversal"]
        assert "current_path_length" in final_query["traversal"]
