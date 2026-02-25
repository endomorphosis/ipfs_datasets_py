"""Tests for query detection module."""

import pytest
from ipfs_datasets_py.optimizers.graphrag.query_detection import QueryDetector


class TestGraphTypeDetection:
    """Test graph type detection functionality."""

    def test_explicit_graph_type_takes_priority(self):
        """Should return explicit graph_type without further checks."""
        query = {
            "graph_type": "custom_type",
            "query": "wikipedia search",
            "entity_source": "ipld",
        }
        result = QueryDetector.detect_graph_type(query)
        assert result == "custom_type"

    def test_detect_wikipedia_from_entity_source(self):
        """Should detect Wikipedia from entity_source field."""
        query = {"entity_source": "wikipedia"}
        result = QueryDetector.detect_graph_type(query)
        assert result == "wikipedia"

    def test_detect_ipld_from_entity_source(self):
        """Should detect IPLD from entity_source field."""
        query = {"entity_source": "ipld"}
        result = QueryDetector.detect_graph_type(query)
        assert result == "ipld"

    def test_detect_wikipedia_from_query_text(self):
        """Should detect Wikipedia from query text keywords."""
        query = {"query": "Tell me about this wikipedia page"}
        result = QueryDetector.detect_graph_type(query)
        assert result == "wikipedia"

    def test_detect_ipld_from_query_text(self):
        """Should detect IPLD from query text keywords."""
        query = {"query": "Retrieve IPLD DAG structure"}
        result = QueryDetector.detect_graph_type(query)
        assert result == "ipld"

    def test_detect_mixed_from_multiple_sources(self):
        """Should detect mixed graph from multiple entity sources."""
        query = {"entity_sources": ["wikipedia", "ipld", "custom"]}
        result = QueryDetector.detect_graph_type(query)
        assert result == "mixed"

    def test_detect_ipld_from_cid_prefix(self):
        """Should detect IPLD from CID entity ID prefix."""
        query = {"entity_ids": ["QmABC123def456"]}
        result = QueryDetector.detect_graph_type(query)
        assert result == "ipld"

    def test_detect_ipld_from_bafy_prefix(self):
        """Should detect IPLD from bafy CID format."""
        query = {"entity_ids": ["bafyABC123def456"]}
        result = QueryDetector.detect_graph_type(query)
        assert result == "ipld"

    def test_default_to_general_type(self):
        """Should default to 'general' when no markers found."""
        # Use empty cache to avoid cache pollution
        independent_cache = {}
        query = {"query": "search"}
        result = QueryDetector.detect_graph_type(query, detection_cache=independent_cache)
        assert result == "general"

    def test_caching_behavior(self):
        """Should cache detection results."""
        cache = {}
        query = {"query": "wikipedia test"}
        
        # First call should cache
        result1 = QueryDetector.detect_graph_type(query, cache)
        assert len(cache) > 0
        
        # Second call should use cache
        result2 = QueryDetector.detect_graph_type(query, cache)
        assert result1 == result2

    def test_single_source_not_mixed(self):
        """Should not treat single source as mixed."""
        query = {"entity_sources": ["wikipedia"]}
        result = QueryDetector.detect_graph_type(query)
        assert result != "mixed"


class TestFactVerificationDetection:
    """Test fact verification query detection."""

    def test_explicit_verify_marker(self):
        """Should detect explicit verify keywords."""
        query = {"query_text": "verify this fact"}
        assert QueryDetector.is_fact_verification_query(query)

    def test_fact_check_marker(self):
        """Should detect fact-check keywords."""
        query = {"query_text": "fact-check this claim"}
        assert QueryDetector.is_fact_verification_query(query)

    def test_confirmation_request(self):
        """Should detect confirmation requests."""
        query = {"query_text": "is it true that...?"}
        assert QueryDetector.is_fact_verification_query(query)

    def test_yes_no_question(self):
        """Should detect yes/no question format."""
        query = {"query_text": "Is the sky blue?"}
        assert QueryDetector.is_fact_verification_query(query)

    def test_shallow_targeted_traversal(self):
        """Should detect fact verification from traversal parameters."""
        query = {
            "traversal": {"max_depth": 1},
            "target_entity": "entity_123",
        }
        assert QueryDetector.is_fact_verification_query(query)

    def test_deep_without_target_not_fact_verification(self):
        """Should not treat deep traversal without target as fact verification."""
        query = {
            "traversal": {"max_depth": 5},
        }
        assert not QueryDetector.is_fact_verification_query(query)

    def test_non_fact_query(self):
        """Should return false for non-fact queries."""
        query = {"query_text": "Tell me more"}
        assert not QueryDetector.is_fact_verification_query(query)


class TestExploratoryQueryDetection:
    """Test exploratory query detection."""

    def test_explicit_exploration_marker(self):
        """Should detect explicit exploration keywords."""
        query = {"exploration": True}
        assert QueryDetector.is_exploratory_query(query)

    def test_discover_keyword(self):
        """Should detect 'discover' keyword."""
        query = {"query_text": "discover new information"}
        assert QueryDetector.is_exploratory_query(query)

    def test_broad_what_question(self):
        """Should detect broad 'what' questions."""
        query = {"query_text": "what is this?"}
        assert QueryDetector.is_exploratory_query(query)

    def test_tell_me_about_pattern(self):
        """Should detect 'tell me about' pattern."""
        query = {"query_text": "tell me about the topic"}
        assert QueryDetector.is_exploratory_query(query)

    def test_deep_traversal_without_target(self):
        """Should detect exploratory deep traversal."""
        query = {
            "traversal": {"max_depth": 4},
        }
        assert QueryDetector.is_exploratory_query(query)

    def test_high_top_k_vector_search(self):
        """Should detect broad vector search as exploratory."""
        query = {
            "vector_params": {"top_k": 50},
        }
        assert QueryDetector.is_exploratory_query(query)

    def test_non_exploratory_query(self):
        """Should return false for targeted queries."""
        query = {
            "query_text": "Retrieve data for entity ABC",
            "traversal": {"max_depth": 2},
            "target_entity": "entity_123",
        }
        assert not QueryDetector.is_exploratory_query(query)


class TestEntityTypeDetection:
    """Test entity type detection from query text."""

    def test_detect_person_type(self):
        """Should detect person entity type."""
        query_text = "Who is Albert Einstein?"
        types = QueryDetector.detect_entity_types(query_text)
        assert "person" in types

    def test_detect_organization_type(self):
        """Should detect organization entity type."""
        query_text = "Tell me about the company Apple"
        types = QueryDetector.detect_entity_types(query_text)
        assert "organization" in types

    def test_detect_location_type(self):
        """Should detect location entity type."""
        query_text = "Where is Paris located?"
        types = QueryDetector.detect_entity_types(query_text)
        assert "location" in types

    def test_detect_concept_type(self):
        """Should detect concept entity type."""
        query_text = "Explain what gravity is"
        types = QueryDetector.detect_entity_types(query_text)
        assert "concept" in types

    def test_detect_event_type(self):
        """Should detect event entity type."""
        query_text = "What happened during World War II?"
        types = QueryDetector.detect_entity_types(query_text)
        assert "event" in types

    def test_detect_product_type(self):
        """Should detect product entity type."""
        query_text = "Tell me about the device iPhone"
        types = QueryDetector.detect_entity_types(query_text)
        assert "product" in types

    def test_predefined_types_override(self):
        """Should use predefined types if provided."""
        predefined = ["custom_type1", "custom_type2"]
        types = QueryDetector.detect_entity_types("any text", predefined_types=predefined)
        assert types == predefined

    def test_empty_text_returns_empty(self):
        """Should return empty list for empty query text."""
        types = QueryDetector.detect_entity_types("")
        assert types == []

    def test_default_to_concept_when_no_match(self):
        """Should default to 'concept' if no patterns match."""
        types = QueryDetector.detect_entity_types("xyz abc 123")
        assert "concept" in types

    def test_multiple_type_detection(self):
        """Should detect multiple entity types in same query."""
        query_text = "Tell me about author Steve Jobs and company Apple"
        types = QueryDetector.detect_entity_types(query_text)
        assert "person" in types
        assert "organization" in types


class TestQueryComplexityEstimation:
    """Test query complexity estimation."""

    def test_low_complexity_simple_query(self):
        """Should estimate low complexity for simple queries."""
        query = {
            "vector_params": {"top_k": 3},
            "traversal": {"max_depth": 1},
        }
        complexity = QueryDetector.estimate_query_complexity(query)
        assert complexity == "low"

    def test_medium_complexity_moderate_query(self):
        """Should estimate medium complexity for moderate queries."""
        query = {
            "vector_params": {"top_k": 5},
            "traversal": {"max_depth": 2, "edge_types": ["knows", "relates_to"]},
        }
        complexity = QueryDetector.estimate_query_complexity(query)
        assert complexity == "medium"

    def test_high_complexity_deep_traversal(self):
        """Should estimate high complexity for deep traversals."""
        query = {
            "vector_params": {"top_k": 20},
            "traversal": {"max_depth": 5, "edge_types": ["knows", "relates_to", "created"]},
            "multi_pass": True,
        }
        complexity = QueryDetector.estimate_query_complexity(query)
        assert complexity == "high"

    def test_complexity_with_filters(self):
        """Should increase complexity for queries with filters."""
        query = {
            "traversal": {
                "max_depth": 2,
                "filters": {"property": "value"},
            },
        }
        complexity = QueryDetector.estimate_query_complexity(query)
        # Filters add to score
        assert complexity in ["low", "medium"]

    def test_empty_query_low_complexity(self):
        """Should estimate low complexity for empty query."""
        query = {}
        complexity = QueryDetector.estimate_query_complexity(query)
        assert complexity == "low"


class TestFastDetectionSignature:
    """Test fast detection signature generation."""

    def test_signature_includes_entity_source(self):
        """Should include entity_source in signature."""
        query = {"entity_source": "wikipedia"}
        sig = QueryDetector._create_fast_detection_signature(query)
        assert "src:wikipedia" in sig

    def test_signature_includes_wikipedia_text_marker(self):
        """Should mark Wikipedia in signature from text."""
        query = {"query": "search wikipedia for data"}
        sig = QueryDetector._create_fast_detection_signature(query)
        assert "wiki_text" in sig

    def test_signature_includes_ipld_text_marker(self):
        """Should mark IPLD in signature from text."""
        query = {"query": "retrieve ipld content"}
        sig = QueryDetector._create_fast_detection_signature(query)
        assert "ipld_text" in sig

    def test_signature_includes_multi_source_marker(self):
        """Should mark multi-source in signature."""
        query = {"entity_sources": ["wiki", "ipld"]}
        sig = QueryDetector._create_fast_detection_signature(query)
        assert "multi_source" in sig

    def test_signature_default_for_empty_query(self):
        """Should return default signature for empty query."""
        query = {}
        sig = QueryDetector._create_fast_detection_signature(query)
        assert sig == "default"


class TestDetectionEdgeCases:
    """Test edge cases and error handling."""

    def test_none_query_text(self):
        """Should handle None query text gracefully."""
        independent_cache = {}
        query = {"query": None}
        result = QueryDetector.detect_graph_type(query, detection_cache=independent_cache)
        assert result == "general"

    def test_empty_entity_ids_list(self):
        """Should handle empty entity IDs list."""
        independent_cache = {}
        query = {"entity_ids": []}
        result = QueryDetector.detect_graph_type(query, detection_cache=independent_cache)
        assert result == "general"

    def test_non_list_entity_sources(self):
        """Should handle non-list entity_sources gracefully."""
        independent_cache = {}
        query = {"entity_sources": "wikipedia"}
        result = QueryDetector.detect_graph_type(query, detection_cache=independent_cache)
        assert result == "general"

    def test_case_insensitivity(self):
        """Should handle case variations."""
        query1 = {"entity_source": "WIKIPEDIA"}
        query2 = {"entity_source": "Wikipedia"}
        query3 = {"entity_source": "wikipedia"}
        
        result1 = QueryDetector.detect_graph_type(query1)
        result2 = QueryDetector.detect_graph_type(query2)
        result3 = QueryDetector.detect_graph_type(query3)
        
        assert result1 == result2 == result3 == "wikipedia"

    def test_mixed_case_query_text(self):
        """Should handle mixed case in query text."""
        query = {"query": "Search Wikipedia for INFO"}
        result = QueryDetector.detect_graph_type(query)
        assert result == "wikipedia"

    def test_complexity_with_missing_fields(self):
        """Should handle missing fields gracefully in complexity estimation."""
        query = {"vector_params": {"top_k": 5}}  # no traversal
        complexity = QueryDetector.estimate_query_complexity(query)
        assert complexity in ["low", "medium", "high"]

    def test_entity_type_detection_with_special_chars(self):
        """Should handle special characters in entity type detection."""
        query_text = "Who was [Albert Einstein]?"
        types = QueryDetector.detect_entity_types(query_text)
        assert types  # Should not crash


class TestDetectionCaching:
    """Test detection caching behavior."""

    def test_cache_size_limit(self):
        """Should respect cache size limit."""
        cache = {}
        QueryDetector._graph_type_detection_max_size = 3
        
        # Fill cache
        for i in range(5):
            query = {"query": f"query_{i}"}
            QueryDetector.detect_graph_type(query, cache)
        
        # Cache should not exceed max size
        assert len(cache) <= 3

    def test_cache_hit_count_tracking(self):
        """Should track cache hits."""
        cache = {}
        query = {"entity_source": "wikipedia"}
        
        initial_hits = QueryDetector._type_detection_hit_count
        
        # First call - cache miss
        QueryDetector.detect_graph_type(query, cache)
        
        # Second call - cache hit
        QueryDetector.detect_graph_type(query, cache)
        
        assert QueryDetector._type_detection_hit_count > initial_hits

    def test_independent_cache_instances(self):
        """Should support independent cache instances."""
        cache1 = {}
        cache2 = {}
        
        query = {"entity_source": "wikipedia"}
        
        QueryDetector.detect_graph_type(query, cache1)
        QueryDetector.detect_graph_type(query, cache2)
        
        assert len(cache1) == 1
        assert len(cache2) == 1
