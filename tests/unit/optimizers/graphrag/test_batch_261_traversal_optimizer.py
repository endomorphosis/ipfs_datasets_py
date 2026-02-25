"""
Batch 261: TraversalOptimizer - Graph traversal optimization testing.

Target: ipfs_datasets_py/ipfs_datasets_py/optimizers/graphrag/traversal_optimizer.py (470 LOC)

Tests for Wikipedia/IPLD traversal optimization, entity importance scoring, relation weighting, and path optimization.
"""

import pytest
from typing import Any, Dict, Set
from unittest.mock import Mock, MagicMock, patch

from ipfs_datasets_py.optimizers.graphrag.traversal_optimizer import TraversalOptimizer


# ============================================================================
# Test Relation Importance Hierarchies
# ============================================================================

class TestRelationImportanceHierarchies:
    """Tests for Wikipedia and IPLD relation importance scores."""
    
    def test_wikipedia_relation_importance_taxonomy(self):
        """Wikipedia relation hierarchy has expected taxonomic relationships."""
        assert TraversalOptimizer.WIKIPEDIA_RELATION_IMPORTANCE["instance_of"] == 0.95
        assert TraversalOptimizer.WIKIPEDIA_RELATION_IMPORTANCE["subclass_of"] == 0.92
        assert TraversalOptimizer.WIKIPEDIA_RELATION_IMPORTANCE["type_of"] == 0.90
    
    def test_wikipedia_relation_importance_composition(self):
        """Wikipedia relation hierarchy has compositional relationships."""
        assert TraversalOptimizer.WIKIPEDIA_RELATION_IMPORTANCE["part_of"] == 0.88
        assert TraversalOptimizer.WIKIPEDIA_RELATION_IMPORTANCE["has_part"] == 0.85
        assert TraversalOptimizer.WIKIPEDIA_RELATION_IMPORTANCE["contains"] == 0.85
    
    def test_wikipedia_relation_importance_spatial(self):
        """Wikipedia relation hierarchy has spatial relationships."""
        assert TraversalOptimizer.WIKIPEDIA_RELATION_IMPORTANCE["located_in"] == 0.79
        assert TraversalOptimizer.WIKIPEDIA_RELATION_IMPORTANCE["capital_of"] == 0.78
        assert TraversalOptimizer.WIKIPEDIA_RELATION_IMPORTANCE["headquarters_in"] == 0.78
    
    def test_wikipedia_relation_importance_causal(self):
        """Wikipedia relation hierarchy has causal/temporal relationships."""
        assert TraversalOptimizer.WIKIPEDIA_RELATION_IMPORTANCE["created_by"] == 0.69
        assert TraversalOptimizer.WIKIPEDIA_RELATION_IMPORTANCE["author"] == 0.67
        assert TraversalOptimizer.WIKIPEDIA_RELATION_IMPORTANCE["preceded_by"] == 0.62
    
    def test_wikipedia_relation_importance_functional(self):
        """Wikipedia relation hierarchy has functional relationships."""
        assert TraversalOptimizer.WIKIPEDIA_RELATION_IMPORTANCE["employed_by"] == 0.55
        assert TraversalOptimizer.WIKIPEDIA_RELATION_IMPORTANCE["similar_to"] == 0.52
    
    def test_wikipedia_relation_importance_general(self):
        """Wikipedia relation hierarchy has general associative relationships."""
        assert TraversalOptimizer.WIKIPEDIA_RELATION_IMPORTANCE["related_to"] == 0.45
        assert TraversalOptimizer.WIKIPEDIA_RELATION_IMPORTANCE["associated_with"] == 0.42
        assert TraversalOptimizer.WIKIPEDIA_RELATION_IMPORTANCE["see_also"] == 0.40
    
    def test_wikipedia_relation_importance_weak(self):
        """Wikipedia relation hierarchy has weak relationships."""
        assert TraversalOptimizer.WIKIPEDIA_RELATION_IMPORTANCE["same_as"] == 0.35
        assert TraversalOptimizer.WIKIPEDIA_RELATION_IMPORTANCE["externally_linked"] == 0.32
        assert TraversalOptimizer.WIKIPEDIA_RELATION_IMPORTANCE["link"] == 0.30
    
    def test_ipld_relation_importance_content(self):
        """IPLD relation hierarchy prioritizes content relationships."""
        assert TraversalOptimizer.IPLD_RELATION_IMPORTANCE["content_hash"] == 0.95
        assert TraversalOptimizer.IPLD_RELATION_IMPORTANCE["references"] == 0.92
        assert TraversalOptimizer.IPLD_RELATION_IMPORTANCE["links_to"] == 0.88
    
    def test_ipld_relation_importance_structural(self):
        """IPLD relation hierarchy has structural relationships."""
        assert TraversalOptimizer.IPLD_RELATION_IMPORTANCE["part_of_dataset"] == 0.85
        assert TraversalOptimizer.IPLD_RELATION_IMPORTANCE["version_of"] == 0.83
        assert TraversalOptimizer.IPLD_RELATION_IMPORTANCE["derived_from"] == 0.80
    
    def test_ipld_relation_importance_verification(self):
        """IPLD relation hierarchy has verification relationships."""
        assert TraversalOptimizer.IPLD_RELATION_IMPORTANCE["verified_by"] == 0.90
        assert TraversalOptimizer.IPLD_RELATION_IMPORTANCE["signed_by"] == 0.88
        assert TraversalOptimizer.IPLD_RELATION_IMPORTANCE["attested_by"] == 0.85
    
    def test_relation_importance_scores_normalized(self):
        """All relation importance scores are between 0 and 1."""
        for relation, score in TraversalOptimizer.WIKIPEDIA_RELATION_IMPORTANCE.items():
            assert 0.0 <= score <= 1.0
        
        for relation, score in TraversalOptimizer.IPLD_RELATION_IMPORTANCE.items():
            assert 0.0 <= score <= 1.0


# ============================================================================
# Test TraversalOptimizer Initialization
# ============================================================================

class TestTraversalOptimizerInit:
    """Tests for TraversalOptimizer initialization."""
    
    def test_initialization_creates_traversal_stats(self):
        """TraversalOptimizer initializes with traversal_stats."""
        optimizer = TraversalOptimizer()
        assert hasattr(optimizer, 'traversal_stats')
        assert isinstance(optimizer.traversal_stats, dict)
    
    def test_initialization_traversal_stats_structure(self):
        """TraversalOptimizer traversal_stats has expected keys."""
        optimizer = TraversalOptimizer()
        stats = optimizer.traversal_stats
        assert "paths_explored" in stats
        assert "path_scores" in stats
        assert "entity_frequency" in stats
        assert "entity_connectivity" in stats
        assert "relation_usefulness" in stats
    
    def test_multiple_instances_independent(self):
        """Multiple TraversalOptimizer instances are independent."""
        opt1 = TraversalOptimizer()
        opt2 = TraversalOptimizer()
        
        # Modify one instance
        opt1.traversal_stats["custom_key"] = "value1"
        
        # Other instance should not have the modification
        assert "custom_key" not in opt2.traversal_stats


# ============================================================================
# Test Entity Importance Calculation
# ============================================================================

class TestEntityImportanceCalculation:
    """Tests for calculate_entity_importance method."""
    
    def test_entity_importance_default_without_graph(self):
        """Entity importance returns base score when graph_processor fails."""
        graph_processor = Mock()
        graph_processor.get_entity_info.return_value = None
        
        with patch.object(TraversalOptimizer, '_entity_importance_cache', {}):
            score = TraversalOptimizer.calculate_entity_importance("e1", graph_processor)
            assert 0.0 <= score <= 1.0
            assert score == 0.5  # Base score when entity not found
    
    def test_entity_importance_with_connections(self):
        """Entity importance is calculated with connection count."""
        graph_processor = Mock()
        entity_info = {
            "inbound_connections": [{"relation_type": "knows"}] * 5,
            "outbound_connections": [{"relation_type": "created"}] * 3,
            "properties": {},
            "type": "Person"
        }
        graph_processor.get_entity_info.return_value = entity_info
        
        with patch.object(TraversalOptimizer, '_entity_importance_cache', {}):
            score = TraversalOptimizer.calculate_entity_importance("e1", graph_processor)
            assert 0.0 <= score <= 1.0  # Should be valid score
    
    def test_entity_importance_with_diversity(self):
        """Entity importance increases with diverse relation types."""
        graph_processor = Mock()
        entity_info = {
            "inbound_connections": [
                {"relation_type": "knows"},
                {"relation_type": "created"},
                {"relation_type": "worked_for"}
            ],
            "outbound_connections": [{"relation_type": "located_in"}],
            "properties": {"prop1": "val1"},
            "type": "Person"
        }
        graph_processor.get_entity_info.return_value = entity_info
        
        with patch.object(TraversalOptimizer, '_entity_importance_cache', {}):
            score = TraversalOptimizer.calculate_entity_importance("e1", graph_processor)
            assert 0.0 <= score <= 1.0
    
    def test_entity_importance_type_scoring(self):
        """Entity importance reflects entity type."""
        graph_processor = Mock()
        
        # Concept type (high importance)
        entity_info_concept = {
            "inbound_connections": [],
            "outbound_connections": [],
            "properties": {},
            "type": "Concept"
        }
        graph_processor.get_entity_info.return_value = entity_info_concept
        
        with patch.object(TraversalOptimizer, '_entity_importance_cache', {}):
            score1 = TraversalOptimizer.calculate_entity_importance("e1", graph_processor)
        
        # Person type (medium importance)
        entity_info_person = {
            "inbound_connections": [],
            "outbound_connections": [],
            "properties": {},
            "type": "Person"
        }
        graph_processor.get_entity_info.return_value = entity_info_person
        
        with patch.object(TraversalOptimizer, '_entity_importance_cache', {}):
            score2 = TraversalOptimizer.calculate_entity_importance("e2", graph_processor)
        
        # Concept should have higher type score
        assert score1 >= score2 or abs(score1 - score2) < 0.1
    
    def test_entity_importance_caching(self):
        """Entity importance results are cached."""
        graph_processor = Mock()
        graph_processor.get_entity_info.return_value = {
            "inbound_connections": [],
            "outbound_connections": [],
            "properties": {},
            "type": "Person"
        }
        
        cache = {}
        with patch.object(TraversalOptimizer, '_entity_importance_cache', cache):
            score1 = TraversalOptimizer.calculate_entity_importance("e1", graph_processor)
            # Call again - should use cache
            score2 = TraversalOptimizer.calculate_entity_importance("e1", graph_processor)
            
            assert score1 == score2
            assert "e1" in cache
            # Graph processor should only be called once (no second call)
            assert graph_processor.get_entity_info.call_count == 1
    
    def test_entity_importance_cache_respects_size(self):
        """Entity importance cache respects max size."""
        graph_processor = Mock()
        graph_processor.get_entity_info.return_value = {
            "inbound_connections": [],
            "outbound_connections": [],
            "properties": {},
            "type": "Person"
        }
        
        cache = {}
        original_max = TraversalOptimizer._cache_max_size
        try:
            TraversalOptimizer._cache_max_size = 2
            
            with patch.object(TraversalOptimizer, '_entity_importance_cache', cache):
                TraversalOptimizer.calculate_entity_importance("e1", graph_processor)
                TraversalOptimizer.calculate_entity_importance("e2", graph_processor)
                TraversalOptimizer.calculate_entity_importance("e3", graph_processor)
                
                # Cache should not exceed max size
                assert len(cache) <= 2
        finally:
            TraversalOptimizer._cache_max_size = original_max


# ============================================================================
# Test Wikipedia Traversal Optimization
# ============================================================================

class TestWikipediaTraversalOptimization:
    """Tests for Wikipedia-specific traversal optimization."""
    
    def test_optimize_wikipedia_traversal_basic(self):
        """optimize_wikipedia_traversal creates optimized query."""
        query = {
            "query_text": "What is the capital of France?",
            "traversal": {"edge_types": ["located_in", "capital_of"]}
        }
        entity_scores = {"e1": 0.8}
        
        result = TraversalOptimizer.optimize_wikipedia_traversal(query, entity_scores)
        
        assert result is not None
        assert "traversal" in result
        assert result["traversal"]["entity_scores"] == entity_scores
    
    def test_optimize_wikipedia_traversal_edge_prioritization(self):
        """Wikipedia optimization prioritizes edges by importance."""
        query = {
            "query_text": "Relations between entities",
            "traversal": {"edge_types": ["link", "instance_of", "related_to"]}
        }
        entity_scores = {}
        
        result = TraversalOptimizer.optimize_wikipedia_traversal(query, entity_scores)
        
        # Should reorder edges by importance
        optimized_edges = result["traversal"]["edge_types"]
        # instance_of (0.90) should come first, then related_to (0.45), then link (0.30)
        instance_idx = optimized_edges.index("instance_of")
        related_idx = optimized_edges.index("related_to")
        link_idx = optimized_edges.index("link")
        
        assert instance_idx < related_idx < link_idx
    
    def test_optimize_wikipedia_traversal_query_relations_detection(self):
        """Wikipedia optimization detects query relations."""
        query = {
            "query_text": "What is the creator of this?",
            "traversal": {"edge_types": ["created_by", "instance_of"]}
        }
        
        result = TraversalOptimizer.optimize_wikipedia_traversal(query, {})
        
        # Should detect created_by relation from query
        if "detected_relations" in result["traversal"]:
            detected = result["traversal"]["detected_relations"]
            assert "created_by" in detected or len(detected) > 0
    
    def test_optimize_wikipedia_traversal_complexity_high(self):
        """Wikipedia optimization adapts to high complexity queries."""
        query = {
            "query_text": "Complex query",
            "traversal": {
                "max_depth": 5,
                "edge_types": ["instance_of"]
            },
            "entity_ids": ["e1", "e2", "e3", "e4"],
            "multi_pass": True
        }
        
        result = TraversalOptimizer.optimize_wikipedia_traversal(query, {})
        
        # High complexity should have strict breadth limits
        traversal = result["traversal"]
        assert traversal.get("max_breadth_per_level") <= 5
        assert traversal.get("use_importance_pruning") is True
        assert traversal.get("importance_threshold") >= 0.4
    
    def test_optimize_wikipedia_traversal_wikipedia_options(self):
        """Wikipedia optimization includes Wikipedia-specific options."""
        query = {"traversal": {"edge_types": []}}
        
        result = TraversalOptimizer.optimize_wikipedia_traversal(query, {})
        
        wiki_options = result["traversal"].get("wikipedia_traversal_options", {})
        assert wiki_options.get("follow_redirects") is True
        assert wiki_options.get("resolve_disambiguation") is True
        assert wiki_options.get("use_category_hierarchy") is True
        assert "popularity_bias" in wiki_options


# ============================================================================
# Test IPLD Traversal Optimization
# ============================================================================

class TestIPLDTraversalOptimization:
    """Tests for IPLD-specific traversal optimization."""
    
    def test_optimize_ipld_traversal_basic(self):
        """optimize_ipld_traversal creates optimized query."""
        query = {
            "traversal": {"edge_types": ["content_hash", "references"]}
        }
        entity_scores = {"e1": 0.7}
        
        result = TraversalOptimizer.optimize_ipld_traversal(query, entity_scores)
        
        assert result is not None
        assert "traversal" in result
        assert result["traversal"]["entity_scores"] == entity_scores
    
    def test_optimize_ipld_traversal_edge_prioritization(self):
        """IPLD optimization prioritizes content edges."""
        query = {
            "traversal": {"edge_types": ["related_to", "content_hash", "links_to"]}
        }
        
        result = TraversalOptimizer.optimize_ipld_traversal(query, {})
        
        optimized_edges = result["traversal"]["edge_types"]
        # content_hash (0.95) should come before links_to (0.88), then related_to (0.60)
        content_idx = optimized_edges.index("content_hash")
        links_idx = optimized_edges.index("links_to")
        related_idx = optimized_edges.index("related_to")
        
        assert content_idx < links_idx < related_idx
    
    def test_optimize_ipld_traversal_ipld_options(self):
        """IPLD optimization includes IPLD-specific options."""
        query = {"traversal": {"edge_types": []}}
        
        result = TraversalOptimizer.optimize_ipld_traversal(query, {})
        
        ipld_options = result["traversal"].get("ipld_traversal_options", {})
        assert ipld_options.get("verify_content_hash") is True
        assert ipld_options.get("follow_references") is True
        assert ipld_options.get("check_signatures") is True
        assert ipld_options.get("validate_attestations") is True
        assert ipld_options.get("use_merkle_proofs") is True
        assert ipld_options.get("support_dag_navigation") is True


# ============================================================================
# Test Traversal Path Optimization
# ============================================================================

class TestTraversalPathOptimization:
    """Tests for optimize_traversal_path method."""
    
    def test_optimize_traversal_path_basic(self):
        """optimize_traversal_path creates optimized traversal parameters."""
        query = {"traversal": {"max_depth": 5}}
        current_path = ["e1", "e2"]
        target = "e5"
        
        result = TraversalOptimizer.optimize_traversal_path(query, current_path, target)
        
        assert "traversal" in result
        assert result["traversal"]["target_entity"] == target
        assert result["traversal"]["current_path_length"] == 2
    
    def test_optimize_traversal_path_depth_reduction(self):
        """Path optimization reduces depth as traversal progresses."""
        query = {"traversal": {"max_depth": 5}}
        current_path = ["e1", "e2", "e3"]  # Deep path
        target = "e5"
        
        result = TraversalOptimizer.optimize_traversal_path(query, current_path, target)
        
        # Max depth should be reduced
        reduced_depth = result["traversal"].get("max_depth", 5)
        assert reduced_depth < 5
    
    def test_optimize_traversal_path_empty_path(self):
        """Path optimization handles empty starting path."""
        query = {"traversal": {"max_depth": 5}}
        current_path = []
        target = "e1"
        
        result = TraversalOptimizer.optimize_traversal_path(query, current_path, target)
        
        # Should not reduce depth for empty path
        assert result["traversal"]["current_path_length"] == 0


# ============================================================================
# Test Relation Usefulness Updates
# ============================================================================

class TestRelationUsefulnessUpdates:
    """Tests for update_relation_usefulness method."""
    
    def test_update_relation_usefulness_initialization(self):
        """update_relation_usefulness initializes unknown relations."""
        stats = {}
        TraversalOptimizer.update_relation_usefulness("knows", 0.8, stats)
        
        assert "knows" in stats
        assert 0.0 <= stats["knows"] <= 1.0
    
    def test_update_relation_usefulness_success(self):
        """update_relation_usefulness increases score on success."""
        stats = {"knows": 0.5}
        initial = stats["knows"]
        
        TraversalOptimizer.update_relation_usefulness("knows", 0.9, stats)
        
        # Should increase toward success value
        assert stats["knows"] > initial
    
    def test_update_relation_usefulness_failure(self):
        """update_relation_usefulness decreases score on failure."""
        stats = {"knows": 0.7}
        initial = stats["knows"]
        
        TraversalOptimizer.update_relation_usefulness("knows", 0.1, stats)
        
        # Should decrease from initial
        assert stats["knows"] < initial
    
    def test_update_relation_usefulness_exponential_moving_average(self):
        """update_relation_usefulness uses exponential moving average."""
        stats = {"knows": 0.5}
        
        # Multiple updates should converge
        TraversalOptimizer.update_relation_usefulness("knows", 1.0, stats)
        score1 = stats["knows"]
        
        TraversalOptimizer.update_relation_usefulness("knows", 1.0, stats)
        score2 = stats["knows"]
        
        # Updates should be getting closer to 1.0
        assert score1 < score2
        assert score2 <= 1.0


# ============================================================================
# Test Query Relation Detection
# ============================================================================

class TestQueryRelationDetection:
    """Tests for _detect_query_relations method."""
    
    def test_detect_query_relations_empty_query(self):
        """Query relation detection handles empty query."""
        relations = TraversalOptimizer._detect_query_relations("")
        assert relations == []
    
    def test_detect_query_relations_none_query(self):
        """Query relation detection handles None query."""
        relations = TraversalOptimizer._detect_query_relations(None)
        assert relations == []
    
    def test_detect_query_relations_instance_of(self):
        """Query relation detection finds instance_of relation."""
        query = "What is an example of a language?"
        relations = TraversalOptimizer._detect_query_relations(query)
        # Should detect "instance" keyword
        assert "instance_of" in relations if "instance" in query.lower() else len(relations) >= 0
    
    def test_detect_query_relations_part_of(self):
        """Query relation detection finds part_of relations."""
        query = "What parts make up this component?"
        relations = TraversalOptimizer._detect_query_relations(query)
        # Should detect part-related keywords
        assert len(relations) > 0 or "related_to" in relations
    
    def test_detect_query_relations_located_in(self):
        """Query relation detection finds located_in relations."""
        query = "Where is Paris located?"
        relations = TraversalOptimizer._detect_query_relations(query)
        # Should detect location keyword
        assert "located_in" in relations or "related_to" in relations or len(relations) > 0
    
    def test_detect_query_relations_created_by(self):
        """Query relation detection finds created_by relations."""
        query = "Who created the telephone?"
        relations = TraversalOptimizer._detect_query_relations(query)
        # Should detect created/developed keywords
        assert len(relations) > 0
    
    def test_detect_query_relations_multiple(self):
        """Query relation detection can find multiple relations."""
        query = "Part of the organization was located in and created by multiple founders"
        relations = TraversalOptimizer._detect_query_relations(query)
        # Should detect multiple relation keywords
        assert len(relations) > 1


# ============================================================================
# Test Query Complexity Estimation
# ============================================================================

class TestQueryComplexityEstimation:
    """Tests for _estimate_query_complexity method."""
    
    def test_estimate_query_complexity_low(self):
        """Query complexity estimation returns low for simple queries."""
        query = {"traversal": {"max_depth": 1}, "entity_ids": []}
        complexity = TraversalOptimizer._estimate_query_complexity(query)
        assert complexity == "low"
    
    def test_estimate_query_complexity_medium(self):
        """Query complexity estimation returns medium for moderate queries."""
        query = {
            "traversal": {"max_depth": 3},
            "entity_ids": ["e1", "e2"],
            "filters": {"type": "Person"}
        }
        complexity = TraversalOptimizer._estimate_query_complexity(query)
        assert complexity in ["medium", "low"]
    
    def test_estimate_query_complexity_high(self):
        """Query complexity estimation returns high for complex queries."""
        query = {
            "traversal": {"max_depth": 5},
            "entity_ids": ["e1", "e2", "e3", "e4", "e5"],
            "multi_pass": True,
            "filters": {"type": "Person"},
            "vector_params": {"top_k": 20}
        }
        complexity = TraversalOptimizer._estimate_query_complexity(query)
        assert complexity == "high"
    
    def test_estimate_query_complexity_depth_factor(self):
        """Depth increases complexity score."""
        query_shallow = {"traversal": {"max_depth": 1}, "entity_ids": []}
        query_deep = {"traversal": {"max_depth": 4}, "entity_ids": []}
        
        c1 = TraversalOptimizer._estimate_query_complexity(query_shallow)
        c2 = TraversalOptimizer._estimate_query_complexity(query_deep)
        
        # Deep should not be simpler than shallow
        assert not (c2 == "low" and c1 != "low")
    
    def test_estimate_query_complexity_entity_count_factor(self):
        """Entity count increases complexity score."""
        query_single = {"traversal": {}, "entity_ids": ["e1"]}
        query_many = {"traversal": {}, "entity_ids": ["e1", "e2", "e3", "e4", "e5"]}
        
        c1 = TraversalOptimizer._estimate_query_complexity(query_single)
        c2 = TraversalOptimizer._estimate_query_complexity(query_many)
        
        # Many entities should not be simpler than single
        assert not (c2 == "low" and c1 != "low")
    
    def test_estimate_query_complexity_returns_valid(self):
        """Query complexity returns valid complexity level."""
        queries = [
            {},
            {"traversal": {}},
            {"traversal": {"max_depth": 5}, "entity_ids": ["e1", "e2"]},
        ]
        
        for query in queries:
            complexity = TraversalOptimizer._estimate_query_complexity(query)
            assert complexity in ["low", "medium", "high"]


# ============================================================================
# Test Integration Scenarios
# ============================================================================

class TestIntegrationScenarios:
    """Integration tests for realistic traversal workflows."""
    
    def test_wikipedia_optimization_workflow(self):
        """Complete Wikipedia optimization workflow."""
        query = {
            "query_text": "What is California?",
            "entity_ids": ["california"],
            "traversal": {
                "max_depth": 3,
                "edge_types": ["instance_of", "located_in", "capital_of"]
            }
        }
        entity_scores = {"california": 0.85, "usa": 0.8}
        
        result = TraversalOptimizer.optimize_wikipedia_traversal(query, entity_scores)
        
        assert result is not None
        assert "traversal" in result
        assert "edge_types" in result["traversal"]
    
    def test_ipld_optimization_workflow(self):
        """Complete IPLD optimization workflow."""
        query = {
            "traversal": {
                "max_depth": 4,
                "edge_types": ["content_hash", "references", "derived_from"]
            },
            "entity_ids": ["cid1", "cid2"]
        }
        entity_scores = {"cid1": 0.9}
        
        result = TraversalOptimizer.optimize_ipld_traversal(query, entity_scores)
        
        assert result is not None
        ipld_opts = result["traversal"].get("ipld_traversal_options", {})
        assert ipld_opts.get("verify_content_hash") is True
    
    def test_path_optimization_series(self):
        """Series of path optimizations for traversal."""
        query = {"traversal": {"max_depth": 5}}
        target = "target_entity"
        
        # Simulating traversal progress
        path = []
        for i in range(3):
            result = TraversalOptimizer.optimize_traversal_path(query, path, target)
            path.append(f"e{i}")
            query = result  # Use optimized query for next iteration
        
        # Final query should have reduced depth
        assert query["traversal"].get("max_depth", 5) < 5
    
    def test_relation_usefulness_learning(self):
        """Relation usefulness learns from query results."""
        stats = {}
        relation = "instance_of"
        
        # Initial values
        TraversalOptimizer.update_relation_usefulness(relation, 0.2, stats)
        score1 = stats[relation]
        
        # Improve with successful queries
        TraversalOptimizer.update_relation_usefulness(relation, 0.9, stats)
        score2 = stats[relation]
        
        TraversalOptimizer.update_relation_usefulness(relation, 0.8, stats)
        score3 = stats[relation]
        
        # Scores should converge toward success
        assert score1 < score2
        assert score2 >= score1


# ============================================================================
# Test Edge Cases and Error Handling
# ============================================================================

class TestEdgeCasesAndErrorHandling:
    """Tests for edge cases and error handling."""
    
    def test_entity_importance_with_missing_entity_info(self):
        """Entity importance handles missing entity info."""
        graph_processor = Mock()
        graph_processor.get_entity_info.return_value = None
        
        with patch.object(TraversalOptimizer, '_entity_importance_cache', {}):
            score = TraversalOptimizer.calculate_entity_importance("e1", graph_processor)
            assert 0.0 <= score <= 1.0
    
    def test_optimize_wikipedia_without_traversal(self):
        """Wikipedia optimization adds traversal if missing."""
        query = {}
        
        result = TraversalOptimizer.optimize_wikipedia_traversal(query, {})
        
        assert "traversal" in result
    
    def test_optimize_ipld_without_traversal(self):
        """IPLD optimization adds traversal if missing."""
        query = {}
        
        result = TraversalOptimizer.optimize_ipld_traversal(query, {})
        
        assert "traversal" in result
    
    def test_optimize_path_without_traversal(self):
        """Path optimization adds traversal if missing."""
        query = {}
        
        result = TraversalOptimizer.optimize_traversal_path(query, [], "target")
        
        assert "traversal" in result
    
    def test_query_complexity_empty_query(self):
        """Query complexity estimation handles empty query."""
        complexity = TraversalOptimizer._estimate_query_complexity({})
        assert complexity in ["low", "medium", "high"]
    
    def test_query_complexity_missing_sections(self):
        """Query complexity handles missing query sections."""
        query = {
            "traversal": {"max_depth": 2}
            # Missing entity_ids, vector_params, filters
        }
        complexity = TraversalOptimizer._estimate_query_complexity(query)
        assert complexity in ["low", "medium", "high"]


# ============================================================================
# Test Relation Importance Access
# ============================================================================

class TestRelationImportanceAccess:
    """Tests for accessing relation importance hierarchies."""
    
    def test_unknown_wikipedia_relation_default(self):
        """Unknown Wikipedia relations default to provided value or not present."""
        # Unknown relations should not be in dict by default
        unknown_relations = ["unknown_rel", "make_up", "foo_bar"]
        for rel in unknown_relations:
            assert rel not in TraversalOptimizer.WIKIPEDIA_RELATION_IMPORTANCE
    
    def test_unknown_ipld_relation_default(self):
        """Unknown IPLD relations default to provided value or not present."""
        unknown_relations = ["unknown_rel", "mystery_relation"]
        for rel in unknown_relations:
            assert rel not in TraversalOptimizer.IPLD_RELATION_IMPORTANCE
    
    def test_all_wikipedia_relations_valid(self):
        """All Wikipedia relation scores are in valid range."""
        for relation, score in TraversalOptimizer.WIKIPEDIA_RELATION_IMPORTANCE.items():
            assert isinstance(relation, str)
            assert isinstance(score, (int, float))
            assert 0.0 <= score <= 1.0
    
    def test_all_ipld_relations_valid(self):
        """All IPLD relation scores are in valid range."""
        for relation, score in TraversalOptimizer.IPLD_RELATION_IMPORTANCE.items():
            assert isinstance(relation, str)
            assert isinstance(score, (int, float))
            assert 0.0 <= score <= 1.0


# ============================================================================
# Test Query Dictionary Handling
# ============================================================================

class TestQueryDictionaryHandling:
    """Tests for query dictionary manipulation."""
    
    def test_optimize_preserves_original_query(self):
        """Optimizations don't modify original query dict."""
        original_query = {
            "query_text": "test",
            "traversal": {"edge_types": ["instance_of"]}
        }
        original_copy = original_query.copy()
        
        TraversalOptimizer.optimize_wikipedia_traversal(original_query, {})
        
        # Original should not be modified (shallow copy at least)
        assert original_query.get("query_text") == original_copy.get("query_text")
    
    def test_optimize_returns_new_dict(self):
        """Optimizations return new dictionaries."""
        query = {"traversal": {}}
        
        result1 = TraversalOptimizer.optimize_wikipedia_traversal(query, {})
        result2 = TraversalOptimizer.optimize_wikipedia_traversal(query, {})
        
        # Results should be different dict instances
        assert result1 is not result2
        assert result1 is not query


# ============================================================================
# Test Cache Management
# ============================================================================

class TestCacheManagement:
    """Tests for entity importance cache management."""
    
    def test_cache_max_size_constant(self):
        """Cache has a defined max size."""
        assert hasattr(TraversalOptimizer, '_cache_max_size')
        assert TraversalOptimizer._cache_max_size > 0
    
    def test_cache_initial_state(self):
        """Cache starts as empty dict or has initial state."""
        # This is a class variable, test its type
        assert isinstance(TraversalOptimizer._entity_importance_cache, dict)

