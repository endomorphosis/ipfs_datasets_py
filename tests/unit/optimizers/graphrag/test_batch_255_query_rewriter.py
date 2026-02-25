"""Batch 255: QueryRewriter Comprehensive Test Suite.

Comprehensive testing of the QueryRewriter for query optimization with
predicate pushdown, join reordering, traversal optimization, pattern-specific
optimizations, domain-specific transformations, and adaptive rewriting.

Test Categories:
- Initialization and configuration
- Predicate pushdown optimization
- Join reordering by selectivity
- Traversal path optimization
- Pattern-specific optimizations
- Domain-specific optimizations
- Adaptive optimizations with historical stats
- Query analysis and complexity estimation
"""

import pytest
from typing import Dict, Any, Optional

from ipfs_datasets_py.optimizers.graphrag.query_rewriter import QueryRewriter


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def rewriter():
    """Create a fresh QueryRewriter without traversal stats."""
    return QueryRewriter()


@pytest.fixture
def rewriter_with_stats():
    """Create a QueryRewriter with historical traversal statistics."""
    stats = {
        "paths_explored": [["A", "B", "C"], ["A", "D", "E"]],
        "path_scores": {
            "A->B->C": 0.85,
            "A->D->E": 0.45,
        },
        "entity_frequency": {"A": 10, "B": 5, "C": 3},
        "entity_connectivity": {"A": 20, "B": 8, "C": 3},
        "relation_usefulness": {
            "has_part": 0.9,
            "related_to": 0.3,
            "mentions": 0.6,
        }
    }
    return QueryRewriter(traversal_stats=stats)


@pytest.fixture
def basic_query():
    """Create a basic query structure."""
    return {
        "query_text": "Find related entities",
        "vector_params": {"top_k": 5},
        "traversal": {
            "max_depth": 2,
            "edge_types": ["related_to", "has_part"]
        }
    }


@pytest.fixture
def dense_graph_info():
    """Create graph info for a dense graph."""
    return {
        "graph_density": 0.8,
        "total_nodes": 1000,
        "total_edges": 50000,
    }


@pytest.fixture
def sparse_graph_info():
    """Create graph info for a sparse graph."""
    return {
        "graph_density": 0.1,
        "entity_connectivity": {"A": 2, "B": 3, "C": 1},
    }


@pytest.fixture
def graph_with_selectivity():
    """Create graph info with edge selectivity."""
    return {
        "edge_selectivity": {
            "has_part": 0.2,       # Very selective
            "related_to": 0.8,     # Not selective
            "mentions": 0.5,
        }
    }


# ============================================================================
# Initialization Tests
# ============================================================================

class TestInitialization:
    """Test QueryRewriter initialization."""
    
    def test_init_without_stats(self, rewriter):
        """QueryRewriter initializes with empty traversal stats."""
        assert rewriter.traversal_stats is not None
        assert "paths_explored" in rewriter.traversal_stats
        assert "path_scores" in rewriter.traversal_stats
    
    def test_init_with_stats(self, rewriter_with_stats):
        """QueryRewriter initializes with provided stats."""
        assert len(rewriter_with_stats.traversal_stats["paths_explored"]) == 2
        assert "A->B->C" in rewriter_with_stats.traversal_stats["path_scores"]


# ============================================================================
# Predicate Pushdown Tests
# ============================================================================

class TestPredicatePushdown:
    """Test predicate pushdown optimization."""
    
    def test_pushdown_min_similarity_to_vector_params(self, rewriter):
        """Pushes min_similarity into vector_params."""
        query = {
            "min_similarity": 0.7,
            "vector_params": {"top_k": 5}
        }
        
        result = rewriter.rewrite_query(query)
        
        assert "min_similarity" not in result
        assert result["vector_params"]["min_score"] == 0.7
    
    def test_pushdown_entity_type_filters(self, rewriter):
        """Pushes entity_filters into vector_params."""
        query = {
            "entity_filters": {"entity_types": ["Person", "Organization"]},
            "vector_params": {"top_k": 10}
        }
        
        result = rewriter.rewrite_query(query)
        
        assert "entity_filters" not in result
        assert result["vector_params"]["entity_types"] == ["Person", "Organization"]
    
    def test_no_pushdown_without_vector_params(self, rewriter):
        """Does not push down without vector_params."""
        query = {
            "min_similarity": 0.7,
        }
        
        result = rewriter.rewrite_query(query)
        
        # min_similarity remains in result
        assert "min_similarity" in result


# ============================================================================
# Join Reordering Tests
# ============================================================================

class TestJoinReordering:
    """Test join reordering by selectivity."""
    
    def test_reorder_edge_types_by_selectivity(self, rewriter, graph_with_selectivity):
        """Reorders edge_types by selectivity (lowest first)."""
        query = {
            "edge_types": ["related_to", "has_part", "mentions"]
        }
        
        result = rewriter.rewrite_query(query, graph_info=graph_with_selectivity)
        
        # Should be reordered: has_part (0.2), mentions (0.5), related_to (0.8)
        assert result["traversal"]["edge_types"] == ["has_part", "mentions", "related_to"]
        assert result["traversal"]["reordered_by_selectivity"] is True
    
    def test_edge_types_moved_to_traversal(self, rewriter):
        """Moves edge_types from top level to traversal section."""
        query = {
            "edge_types": ["related_to", "has_part"]
        }
        
        result = rewriter.rewrite_query(query)
        
        assert "edge_types" not in result
        assert result["traversal"]["edge_types"] == ["related_to", "has_part"]
    
    def test_no_reordering_without_selectivity(self, rewriter):
        """Does not reorder without selectivity info."""
        query = {
            "edge_types": ["related_to", "has_part"]
        }
        
        result = rewriter.rewrite_query(query, graph_info={})
        
        # Order preserved
        assert result["traversal"]["edge_types"] == ["related_to", "has_part"]


# ============================================================================
# Traversal Path Optimization Tests
# ============================================================================

class TestTraversalOptimization:
    """Test traversal path optimization."""
    
    def test_dense_graph_uses_sampling(self, rewriter, dense_graph_info):
        """Dense graphs use sampling strategy."""
        query = {
            "query_text": "Find related entities",
            "traversal": {"max_depth": 2}
        }
        
        result = rewriter.rewrite_query(query, graph_info=dense_graph_info)
        
        assert result["traversal"]["strategy"] == "sampling"
        assert result["traversal"]["sample_ratio"] == 0.3
    
    def test_deep_traversal_uses_breadth_limited(self, rewriter):
        """Deep traversal uses breadth-limited strategy."""
        query = {
            "max_traversal_depth": 3
        }
        
        result = rewriter.rewrite_query(query)
        
        assert result["traversal"]["strategy"] == "breadth_limited"
        assert result["traversal"]["max_breadth_per_level"] == 5
    
    def test_max_traversal_depth_moved_to_max_depth(self, rewriter):
        """Moves max_traversal_depth to traversal.max_depth."""
        query = {
            "max_traversal_depth": 2
        }
        
        result = rewriter.rewrite_query(query)
        
        assert "max_traversal_depth" not in result
        assert result["traversal"]["max_depth"] == 2


# ============================================================================
# Pattern-Specific Optimization Tests
# ============================================================================

class TestPatternSpecificOptimizations:
    """Test pattern-specific query optimizations."""
    
    def test_entity_lookup_pattern(self, rewriter):
        """Entity lookup queries skip vector search."""
        query = {
            "entity_id": "E123",
            "vector_params": {"top_k": 5}
        }
        
        result = rewriter.rewrite_query(query)
        
        assert result["skip_vector_search"] is True
    
    def test_relation_centric_pattern(self, rewriter):
        """Relation-centric queries prioritize relationships."""
        query = {
            "edge_types": ["has_part"]
        }
        
        result = rewriter.rewrite_query(query)
        
        assert result["traversal"]["prioritize_relationships"] is True
    
    def test_fact_verification_pattern(self, rewriter):
        """Fact verification queries use path finding."""
        query = {
            "source_entity": "A",
            "target_entity": "B",
            "fact": "A is related to B"
        }
        
        result = rewriter.rewrite_query(query)
        
        assert result["traversal"]["strategy"] == "path_finding"
        assert result["traversal"]["find_shortest_path"] is True
    
    def test_general_pattern_no_special_optimization(self, rewriter, basic_query):
        """General pattern doesn't add special optimizations."""
        result = rewriter.rewrite_query(basic_query)
        
        # No skip_vector_search, no prioritize_relationships
        assert "skip_vector_search" not in result
        assert "prioritize_relationships" not in result["traversal"]


# ============================================================================
# Domain-Specific Optimization Tests
# ============================================================================

class TestDomainOptimizations:
    """Test domain-specific query transformations."""
    
    def test_wikipedia_graph_prioritizes_reliable_edges(self, rewriter):
        """Wikipedia graphs prioritize high-quality relationships."""
        query = {
            "edge_types": ["related_to", "instance_of", "mentions", "subclass_of"]
        }
        graph_info = {"graph_type": "wikipedia"}
        
        result = rewriter.rewrite_query(query, graph_info=graph_info)
        
        # Priority edges should move to front: subclass_of, instance_of
        edge_types = result["traversal"]["edge_types"]
        assert edge_types[0] == "subclass_of"
        assert edge_types[1] == "instance_of"
    
    def test_wikipedia_graph_adds_hierarchical_weight(self, rewriter):
        """Wikipedia graphs add hierarchical relationship weighting."""
        query = {
            "query_text": "Find related entities"
        }
        graph_info = {"graph_type": "wikipedia"}
        
        result = rewriter.rewrite_query(query, graph_info=graph_info)
        
        assert result["traversal"]["hierarchical_weight"] == 1.5
    
    def test_non_wikipedia_graph_no_special_optimization(self, rewriter, basic_query):
        """Non-Wikipedia graphs don't get special optimizations."""
        graph_info = {"graph_type": "custom"}
        
        result = rewriter.rewrite_query(basic_query, graph_info=graph_info)
        
        # No hierarchical_weight
        assert "hierarchical_weight" not in result["traversal"]


# ============================================================================
# Adaptive Optimization Tests
# ============================================================================

class TestAdaptiveOptimizations:
    """Test adaptive optimizations based on historical data."""
    
    def test_relation_usefulness_reordering(self, rewriter_with_stats):
        """Relations reordered by usefulness scores."""
        query = {
            "edge_types": ["related_to", "has_part", "mentions"]
        }
        
        result = rewriter_with_stats.rewrite_query(query)
        
        # Should be ordered by usefulness: has_part (0.9), mentions (0.6), related_to (0.3)
        edge_types = result["traversal"]["edge_types"]
        assert edge_types[0] == "has_part"
        assert edge_types[1] == "mentions"
        assert edge_types[2] == "related_to"
        assert "edge_usefulness" in result["traversal"]
    
    def test_path_hints_for_high_scoring_paths(self, rewriter_with_stats):
        """High-scoring paths added as hints."""
        query = {
            "query_text": "Find entities"
        }
        
        result = rewriter_with_stats.rewrite_query(query)
        
        # Should include path hints (only high-scoring paths > 0.7)
        assert "path_hints" in result["traversal"]
        assert "A->B->C" in result["traversal"]["path_hints"]
    
    def test_importance_pruning_with_entity_scores(self, rewriter):
        """Entity importance scores enable pruning."""
        query = {
            "query_text": "Find entities"
        }
        entity_scores = {"A": 0.9, "B": 0.5, "C": 0.3}
        
        result = rewriter.rewrite_query(query, entity_scores=entity_scores)
        
        assert result["traversal"]["use_importance_pruning"] is True
        assert "importance_threshold" in result["traversal"]
        assert result["traversal"]["entity_scores"] == entity_scores
    
    def test_adaptive_max_depth_for_high_connectivity(self, rewriter):
        """Highly connected graphs reduce max_depth."""
        query = {
            "max_traversal_depth": 3
        }
        # Populate traversal_stats with high connectivity
        rewriter.traversal_stats["entity_connectivity"] = {"A": 20, "B": 18, "C": 16}
        
        result = rewriter.rewrite_query(query)
        
        # Should reduce max_depth to 2 for high connectivity
        assert result["traversal"]["max_depth"] == 2
        assert result["traversal"]["max_breadth_per_level"] == 8
    
    def test_adaptive_max_depth_for_low_connectivity(self, rewriter, sparse_graph_info):
        """Sparsely connected graphs increase max_depth."""
        query = {
            "max_traversal_depth": 2
        }
        # Populate traversal_stats with low connectivity
        rewriter.traversal_stats["entity_connectivity"] = {"A": 2, "B": 3, "C": 1}
        
        result = rewriter.rewrite_query(query)
        
        # Should increase max_depth to 3 for low connectivity
        assert result["traversal"]["max_depth"] == 3


# ============================================================================
# Query Analysis Tests
# ============================================================================

class TestAnalyzeQuery:
    """Test query analysis and characterization."""
    
    def test_analyze_returns_dict(self, rewriter, basic_query):
        """analyze_query returns dictionary."""
        result = rewriter.analyze_query(basic_query)
        
        assert isinstance(result, dict)
        assert "pattern" in result
        assert "complexity" in result
        assert "optimizations" in result
    
    def test_analyze_detects_entity_lookup(self, rewriter):
        """Detects entity_lookup pattern."""
        query = {"entity_id": "E123"}
        
        result = rewriter.analyze_query(query)
        
        assert result["pattern"] == "entity_lookup"
    
    def test_analyze_detects_fact_verification(self, rewriter):
        """Detects fact_verification pattern."""
        query = {"source_entity": "A", "target_entity": "B"}
        
        result = rewriter.analyze_query(query)
        
        assert result["pattern"] == "fact_verification"
    
    def test_analyze_detects_relation_centric(self, rewriter):
        """Detects relation_centric pattern."""
        query = {"edge_types": ["has_part"]}
        
        result = rewriter.analyze_query(query)
        
        assert result["pattern"] == "relation_centric"
    
    def test_analyze_detects_complex_question(self, rewriter):
        """Detects complex_question pattern."""
        query = {"query_text": "What are the relationships between entities in the medical domain related to treatment?"}
        
        result = rewriter.analyze_query(query)
        
        assert result["pattern"] == "complex_question"
    
    def test_analyze_estimates_low_complexity(self, rewriter):
        """Estimates low complexity correctly."""
        query = {
            "vector_params": {"top_k": 3},
            "traversal": {"max_depth": 1}
        }
        
        result = rewriter.analyze_query(query)
        
        assert result["complexity"] == "low"
    
    def test_analyze_estimates_medium_complexity(self, rewriter):
        """Estimates medium complexity correctly."""
        query = {
            "vector_params": {"top_k": 10},
            "traversal": {"max_depth": 2, "edge_types": ["a", "b", "c"]}
        }
        
        result = rewriter.analyze_query(query)
        
        assert result["complexity"] == "medium"
    
    def test_analyze_estimates_high_complexity(self, rewriter):
        """Estimates high complexity correctly."""
        query = {
            "vector_params": {"top_k": 20},
            "traversal": {"max_depth": 4, "edge_types": ["a", "b", "c", "d", "e"]}
        }
        
        result = rewriter.analyze_query(query)
        
        assert result["complexity"] == "high"
    
    def test_analyze_suggests_threshold_increase(self, rewriter):
        """Suggests threshold increase for low similarity."""
        query = {"min_similarity": 0.3}
        
        result = rewriter.analyze_query(query)
        
        # Should suggest threshold increase
        assert len(result["optimizations"]) > 0
        assert any(opt["type"] == "threshold_increase" for opt in result["optimizations"])
    
    def test_analyze_suggests_depth_reduction(self, rewriter):
        """Suggests depth reduction for deep traversal."""
        query = {"traversal": {"max_depth": 5}}
        
        result = rewriter.analyze_query(query)
        
        # Should suggest depth reduction
        assert len(result["optimizations"]) > 0
        assert any(opt["type"] == "depth_reduction" for opt in result["optimizations"])


# ============================================================================
# Integration Tests
# ============================================================================

class TestQueryRewriterIntegration:
    """Integration tests for complete query rewriting workflows."""
    
    def test_full_rewrite_workflow(self, rewriter_with_stats, graph_with_selectivity):
        """Complete rewrite applies all optimizations."""
        query = {
            "min_similarity": 0.7,
            "entity_filters": {"entity_types": ["Person"]},
            "edge_types": ["related_to", "has_part", "mentions"],
            "max_traversal_depth": 2,
            "vector_params": {"top_k": 5}
        }
        entity_scores = {"A": 0.9, "B": 0.6, "C": 0.4}
        
        result = rewriter_with_stats.rewrite_query(
            query,
            graph_info=graph_with_selectivity,
            entity_scores=entity_scores
        )
        
        # Predicate pushdown applied
        assert "min_similarity" not in result
        assert "entity_filters" not in result
        assert result["vector_params"]["min_score"] == 0.7
        
        # Join reordering applied (by selectivity)
        assert result["traversal"]["edge_types"][0] == "has_part"
        
        # Traversal optimization applied
        assert result["traversal"]["max_depth"] == 2
        
        # Adaptive optimizations applied
        assert result["traversal"]["use_importance_pruning"] is True
        assert "edge_usefulness" in result["traversal"]
    
    def test_analyze_then_rewrite_workflow(self, rewriter, basic_query):
        """Analyze query before rewriting."""
        # Analyze first
        analysis = rewriter.analyze_query(basic_query)
        
        assert analysis["pattern"] == "general"
        assert analysis["complexity"] in ["low", "medium", "high"]
        
        # Then rewrite
        result = rewriter.rewrite_query(basic_query)
        
        assert "traversal" in result
        assert result["traversal"]["max_depth"] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
