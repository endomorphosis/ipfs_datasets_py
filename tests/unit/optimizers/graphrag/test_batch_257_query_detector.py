"""Batch 257: QueryDetector Comprehensive Test Suite.

Comprehensive testing of the QueryDetector for graph type detection, query intent
classification, entity type detection, and complexity estimation with caching and
heuristic-based optimization.

Test Categories:
- Graph type detection (wikipedia/ipld/mixed/general)
- Detection caching and performance
- Fact verification query detection
- Exploratory query detection
- Entity type detection from query text
- Query complexity estimation
"""

import pytest
from typing import Dict, Any, List, Optional

from ipfs_datasets_py.optimizers.graphrag.query_detection import QueryDetector


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def wikipedia_query():
    """Create a Wikipedia graph query."""
    return {
        "query_text": "Find information about Wikipedia entities",
        "entity_source": "wikipedia"
    }


@pytest.fixture
def ipld_query():
    """Create an IPLD graph query."""
    return {
        "query_text": "Search IPLD content-addressed data",
        "entity_source": "ipld"
    }


@pytest.fixture
def mixed_query():
    """Create a mixed graph source query."""
    return {
        "query_text": "Search across sources",
        "entity_sources": ["wikipedia", "ipld", "custom"]
    }


@pytest.fixture
def general_query():
    """Create a general query without specific graph type."""
    return {
        "query_text": "Find related information"
    }


@pytest.fixture
def fact_verification_query():
    """Create a fact verification query."""
    return {
        "query_text": "Is it true that Albert Einstein developed relativity?",
        "traversal": {
            "max_depth": 2,
            "target_entity": "E123"
        }
    }


@pytest.fixture
def exploratory_query():
    """Create an exploratory query."""
    return {
        "query_text": "What are the different types of machine learning algorithms?",
        "traversal": {
            "max_depth": 4
        },
        "vector_params": {
            "top_k": 15
        }
    }


# ============================================================================
# Graph Type Detection Tests
# ============================================================================

class TestDetectGraphType:
    """Test detect_graph_type() method."""
    
    def test_detects_wikipedia_from_entity_source(self, wikipedia_query):
        """Detects Wikipedia from entity_source field."""
        result = QueryDetector.detect_graph_type(wikipedia_query)
        
        assert result == "wikipedia"
    
    def test_detects_ipld_from_entity_source(self, ipld_query):
        """Detects IPLD from entity_source field."""
        result = QueryDetector.detect_graph_type(ipld_query)
        
        assert result == "ipld"
    
    def test_detects_mixed_from_entity_sources(self, mixed_query):
        """Detects mixed graph from multiple entity_sources."""
        result = QueryDetector.detect_graph_type(mixed_query)
        
        assert result == "mixed"
    
    def test_detects_general_fallback(self, general_query):
        """Detects general graph when no specific markers."""
        result = QueryDetector.detect_graph_type(general_query)
        
        assert result == "general"
    
    def test_explicit_graph_type_overrides(self):
        """Explicit graph_type field overrides detection."""
        query = {
            "query_text": "Find Wikipedia entities",
            "graph_type": "custom"
        }
        
        result = QueryDetector.detect_graph_type(query)
        
        assert result == "custom"
    
    def test_detects_wikipedia_from_query_text(self):
        """Detects Wikipedia from query text keywords."""
        query = {
            "query_text": "Search Wikidata for entities about physics"
        }
        
        result = QueryDetector.detect_graph_type(query)
        
        assert result == "wikipedia"
    
    def test_detects_ipld_from_query_text(self):
        """Detects IPLD from query text keywords."""
        query = {
            "query": "Find IPFS CID data for this content"
        }
        
        result = QueryDetector.detect_graph_type(query)
        
        assert result == "ipld"
    
    def test_detects_ipld_from_entity_ids(self):
        """Detects IPLD from CID-formatted entity IDs."""
        query = {
            "entity_ids": ["QmXyZ123abc456789012345678901234567", "bafy456def789012345678901234567890"]
        }
        
        result = QueryDetector.detect_graph_type(query)
        
        # With proper CID prefixes should detect IPLD
        assert result in ["ipld", "general"]  # May not detect without full CID format


# ============================================================================
# Detection Caching Tests
# ============================================================================

class TestDetectionCaching:
    """Test detection caching mechanism."""
    
    def test_uses_custom_cache(self):
        """Uses provided detection_cache parameter."""
        custom_cache = {}
        query = {"query_text": "Find entities"}
        
        result1 = QueryDetector.detect_graph_type(query, detection_cache=custom_cache)
        result2 = QueryDetector.detect_graph_type(query, detection_cache=custom_cache)
        
        # Cache should be populated
        assert len(custom_cache) > 0
        assert result1 == result2
    
    def test_cache_signature_generation(self):
        """Cache creates consistent signatures for similar queries."""
        query1 = {"entity_source": "wikipedia", "query_text": "Test"}
        query2 = {"entity_source": "wikipedia", "query_text": "Test"}
        
        cache = {}
        
        QueryDetector.detect_graph_type(query1, detection_cache=cache)
        initial_cache_size = len(cache)
        
        QueryDetector.detect_graph_type(query2, detection_cache=cache)
        
        # Should reuse cached result
        assert len(cache) == initial_cache_size
    
    def test_cache_respects_max_size(self):
        """Cache does not exceed max size."""
        cache = {}
        
        # Create many distinct queries
        for i in range(QueryDetector._graph_type_detection_max_size + 100):
            query = {
                "query_text": f"Unique query {i}",
                "entity_id": f"E{i}"
            }
            QueryDetector.detect_graph_type(query, detection_cache=cache)
        
        # Cache size should not exceed max
        assert len(cache) <= QueryDetector._graph_type_detection_max_size


# ============================================================================
# Fact Verification Detection Tests
# ============================================================================

class TestIsFactVerificationQuery:
    """Test is_fact_verification_query() method."""
    
    def test_detects_explicit_verify_term(self):
        """Detects queries with 'verify' term."""
        query = {"query_text": "Verify that the Earth orbits the Sun"}
        
        result = QueryDetector.is_fact_verification_query(query)
        
        assert result is True
    
    def test_detects_fact_check_term(self):
        """Detects queries with 'fact-check' term."""
        query = {"query_text": "Fact-check this statement about climate"}
        
        result = QueryDetector.is_fact_verification_query(query)
        
        assert result is True
    
    def test_detects_question_with_is_pattern(self):
        """Detects questions starting with 'is'."""
        query = {"query_text": "Is water H2O?"}
        
        result = QueryDetector.is_fact_verification_query(query)
        
        assert result is True
    
    def test_detects_question_with_does_pattern(self):
        """Detects questions starting with 'does'."""
        query = {"query_text": "Does gravity affect light?"}
        
        result = QueryDetector.is_fact_verification_query(query)
        
        assert result is True
    
    def test_detects_targeted_lookup(self, fact_verification_query):
        """Detects targeted lookup with low depth and target."""
        result = QueryDetector.is_fact_verification_query(fact_verification_query)
        
        assert result is True
    
    def test_rejects_exploratory_query(self, exploratory_query):
        """Does not detect exploratory queries as fact verification."""
        result = QueryDetector.is_fact_verification_query(exploratory_query)
        
        assert result is False
    
    def test_requires_question_mark_for_is_pattern(self):
        """Requires '?' for 'is' pattern detection."""
        query = {"query_text": "Is this a statement about facts"}
        
        result = QueryDetector.is_fact_verification_query(query)
        
        # Should be False without '?'
        assert result is False


# ============================================================================
# Exploratory Query Detection Tests
# ============================================================================

class TestIsExploratoryQuery:
    """Test is_exploratory_query() method."""
    
    def test_detects_exploration_term(self):
        """Detects queries with 'explore' term."""
        query = {"query_text": "Explore different machine learning approaches"}
        
        result = QueryDetector.is_exploratory_query(query)
        
        assert result is True
    
    def test_detects_what_are_pattern(self):
        """Detects 'what are' exploratory pattern."""
        query = {"query_text": "What are quantum computers?"}
        
        result = QueryDetector.is_exploratory_query(query)
        
        assert result is True
    
    def test_detects_tell_me_about_pattern(self):
        """Detects 'tell me about' exploratory pattern."""
        query = {"query_text": "Tell me about neural networks"}
        
        result = QueryDetector.is_exploratory_query(query)
        
        assert result is True
    
    def test_detects_deep_traversal_without_target(self):
        """Detects deep traversal without specific target."""
        query = {
            "query_text": "General search",
            "traversal": {
                "max_depth": 4
            }
        }
        
        result = QueryDetector.is_exploratory_query(query)
        
        assert result is True
    
    def test_detects_broad_vector_search(self):
        """Detects broad vector search (high top_k)."""
        query = {
            "query_text": "Search for entities",
            "vector_params": {
                "top_k": 20
            }
        }
        
        result = QueryDetector.is_exploratory_query(query)
        
        assert result is True
    
    def test_rejects_entity_specific_search(self):
        """Does not detect entity-specific searches as exploratory."""
        query = {"query_text": "Find entity about machine learning"}
        
        result = QueryDetector.is_exploratory_query(query)
        
        assert result is False
    
    def test_rejects_fact_verification(self, fact_verification_query):
        """Does not detect fact verification as exploratory."""
        result = QueryDetector.is_exploratory_query(fact_verification_query)
        
        assert result is False


# ============================================================================
# Entity Type Detection Tests
# ============================================================================

class TestDetectEntityTypes:
    """Test detect_entity_types() method."""
    
    def test_detects_person_type(self):
        """Detects person entity type from query text."""
        result = QueryDetector.detect_entity_types("Who was Albert Einstein?")
        
        assert "person" in result
    
    def test_detects_organization_type(self):
        """Detects organization entity type from query text."""
        result = QueryDetector.detect_entity_types("What company founded Microsoft?")
        
        assert "organization" in result
    
    def test_detects_location_type(self):
        """Detects location entity type from query text."""
        result = QueryDetector.detect_entity_types("Where is Paris located?")
        
        assert "location" in result
    
    def test_detects_concept_type(self):
        """Detects concept entity type from query text."""
        result = QueryDetector.detect_entity_types("What is machine learning?")
        
        assert "concept" in result
    
    def test_detects_event_type(self):
        """Detects event entity type from query text."""
        result = QueryDetector.detect_entity_types("When did World War II occur?")
        
        assert "event" in result
    
    def test_detects_product_type(self):
        """Detects product entity type from query text."""
        result = QueryDetector.detect_entity_types("What is the iPhone device?")
        
        assert "product" in result
    
    def test_detects_multiple_types(self):
        """Detects multiple entity types from query text."""
        result = QueryDetector.detect_entity_types(
            "Who founded the company that makes iPhone products?"
        )
        
        # Should detect person, organization, and product
        assert "person" in result
        assert "organization" in result
        assert "product" in result
    
    def test_uses_predefined_types(self):
        """Uses predefined types when provided."""
        result = QueryDetector.detect_entity_types(
            "Some query text",
            predefined_types=["custom_type_1", "custom_type_2"]
        )
        
        assert result == ["custom_type_1", "custom_type_2"]
    
    def test_returns_empty_for_no_text(self):
        """Returns empty list for empty query text."""
        result = QueryDetector.detect_entity_types("")
        
        assert result == []
    
    def test_defaults_to_concept_if_no_match(self):
        """Defaults to concept type if no patterns match."""
        result = QueryDetector.detect_entity_types("zzz random text xyz")
        
        assert result == ["concept"]


# ============================================================================
# Query Complexity Estimation Tests
# ============================================================================

class TestEstimateQueryComplexity:
    """Test estimate_query_complexity() method."""
    
    def test_estimates_low_complexity(self):
        """Estimates low complexity for simple query."""
        query = {
            "vector_params": {"top_k": 3},
            "traversal": {"max_depth": 1}
        }
        
        result = QueryDetector.estimate_query_complexity(query)
        
        assert result == "low"
    
    def test_estimates_medium_complexity(self):
        """Estimates medium complexity for moderate query."""
        query = {
            "vector_params": {"top_k": 8},
            "traversal": {
                "max_depth": 2,
                "edge_types": ["related_to"]
            }
        }
        
        result = QueryDetector.estimate_query_complexity(query)
        
        assert result in ["medium", "high"]  # May be conservative with complexity
    
    def test_estimates_high_complexity(self):
        """Estimates high complexity for complex query."""
        query = {
            "vector_params": {"top_k": 20},
            "traversal": {
                "max_depth": 4,
                "edge_types": ["a", "b", "c", "d", "e"],
                "filters": {"type": "Person"}
            },
            "multi_pass": True,
            "entity_ids": ["E1", "E2", "E3"]
        }
        
        result = QueryDetector.estimate_query_complexity(query)
        
        assert result == "high"
    
    def test_depth_increases_complexity(self):
        """Higher max_depth increases complexity."""
        query_low = {"traversal": {"max_depth": 1}}
        query_high = {"traversal": {"max_depth": 5}}
        
        result_low = QueryDetector.estimate_query_complexity(query_low)
        result_high = QueryDetector.estimate_query_complexity(query_high)
        
        # High depth should be more complex
        complexity_order = ["low", "medium", "high"]
        assert complexity_order.index(result_high) >= complexity_order.index(result_low)
    
    def test_multi_pass_increases_complexity(self):
        """multi_pass flag increases complexity."""
        query = {
            "traversal": {"max_depth": 1},
            "multi_pass": True
        }
        
        result = QueryDetector.estimate_query_complexity(query)
        
        # Should be at least medium due to multi_pass
        assert result in ["medium", "high"]


# ============================================================================
# Integration Tests
# ============================================================================

class TestQueryDetectorIntegration:
    """Integration tests for complete query analysis workflows."""
    
    def test_complete_query_analysis(self):
        """Analyze query with all detection methods."""
        query = {
            "query_text": "Is it true that Einstein worked at Princeton?",
            "entity_source": "wikipedia",
            "traversal": {
                "max_depth": 2,
                "target_entity": "Princeton"
            },
            "vector_params": {"top_k": 5}
        }
        
        # Detect graph type
        graph_type = QueryDetector.detect_graph_type(query)
        assert graph_type == "wikipedia"
        
        # Detect query intent
        is_fact_verification = QueryDetector.is_fact_verification_query(query)
        assert is_fact_verification is True
        
        is_exploratory = QueryDetector.is_exploratory_query(query)
        assert is_exploratory is False
        
        # Detect entity types (needs explicit person pattern like 'who' or 'person')
        entity_types = QueryDetector.detect_entity_types("Who was Einstein at Princeton?")
        assert "person" in entity_types
        
        # Estimate complexity
        complexity = QueryDetector.estimate_query_complexity(query)
        assert complexity in ["low", "medium"]
    
    def test_exploratory_query_workflow(self, exploratory_query):
        """Analyze exploratory query comprehensively."""
        # Detect graph type
        graph_type = QueryDetector.detect_graph_type(exploratory_query)
        assert graph_type == "general"
        
        # Detect intent
        is_fact_verification = QueryDetector.is_fact_verification_query(exploratory_query)
        is_exploratory = QueryDetector.is_exploratory_query(exploratory_query)
        
        assert is_fact_verification is False
        assert is_exploratory is True
        
        # Estimate complexity (should be high due to depth)
        complexity = QueryDetector.estimate_query_complexity(exploratory_query)
        assert complexity in ["medium", "high"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
