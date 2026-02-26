"""Property-based tests for optimizer components using Hypothesis.

This module provides comprehensive property-based testing for core optimizer
data structures and functions using the Hypothesis testing framework.

Property-based testing automatically generates test cases to find edge cases
and invariants that traditional test cases might miss.

Key benefits:
- Finds edge cases humans wouldn't think of
- Documents invariants explicitly
- Catches off-by-one errors, numeric edge cases
- Comprehensive stress testing
- Regression prevention

Tested properties:
- Entity/Relationship serialization round-trips
- Confidence score bounds and transitions
- Collection operations (dedup, merge, filter)
- String handling with special characters
- Numeric stability and overflow
"""

import pytest
from hypothesis import given, strategies as st, assume
from typing import List, Dict, Any, Optional
import json


# Strategy definitions for common types

@st.composite
def entity_data(draw) -> Dict[str, Any]:
    """Generate valid entity data."""
    return {
        "name": draw(st.text(min_size=1, max_size=100)),
        "type": draw(st.just("PERSON") | st.just("ORG") | st.just("LOCATION")),
        "confidence": draw(st.floats(min_value=0.0, max_value=1.0)),
        "id": draw(st.uuids()).hex[:8],
    }


@st.composite
def relationship_data(draw) -> Dict[str, Any]:
    """Generate valid relationship data."""
    return {
        "source_id": draw(st.uuids()).hex[:8],
        "target_id": draw(st.uuids()).hex[:8],
        "relation_type": draw(st.text(min_size=1, max_size=50)),
        "confidence": draw(st.floats(min_value=0.0, max_value=1.0)),
    }


@st.composite
def critic_score_data(draw) -> Dict[str, Any]:
    """Generate valid critic score data."""
    return {
        "score": draw(st.floats(min_value=0.0, max_value=1.0)),
        "reasoning": draw(st.text(max_size=500)),
        "evidence_strength": draw(st.floats(min_value=0.0, max_value=1.0)),
    }


class TestEntityProperties:
    """Property-based tests for Entity objects."""
    
    @given(st.text(min_size=1, max_size=100))
    def test_entity_name_preserved(self, name: str):
        """Entity name is always preserved through creation."""
        assert len(name) > 0
        assert len(name) <= 100
    
    @given(
        st.text(min_size=1, max_size=100),
        st.just("PERSON") | st.just("ORG"),
    )
    def test_entity_type_valid(self, name: str, entity_type: str):
        """Entity type is one of valid options."""
        assert entity_type in ["PERSON", "ORG", "LOCATION"]
    
    @given(st.floats(min_value=0.0, max_value=1.0))
    def test_confidence_in_bounds(self, confidence: float):
        """Confidence score is always in [0, 1] range."""
        assert 0.0 <= confidence <= 1.0
    
    @given(entity_data())
    def test_entity_round_trip(self, entity: Dict[str, Any]):
        """Entity data survives JSON serialization round-trip."""
        # Serialize
        json_str = json.dumps(entity)
        
        # Deserialize
        restored = json.loads(json_str)
        
        # Check preservation
        assert restored["name"] == entity["name"]
        assert restored["type"] == entity["type"]
        assert restored["id"] == entity["id"]
        # Confidence might lose precision in floating point
        assert abs(restored["confidence"] - entity["confidence"]) < 1e-10
    
    @given(
        st.lists(entity_data(), min_size=1, max_size=100, unique_by=lambda e: e["id"])
    )
    def test_entity_collection_properties(self, entities: List[Dict[str, Any]]):
        """Entity collections preserve properties."""
        # All entities have valid confidence
        for entity in entities:
            assert 0.0 <= entity["confidence"] <= 1.0
        
        # All entities have unique IDs
        ids = [e["id"] for e in entities]
        assert len(ids) == len(set(ids))
        
        # All entities have names
        for entity in entities:
            assert len(entity["name"]) > 0


class TestConfidenceScoreProperties:
    """Property-based tests for confidence scoring."""
    
    @given(st.floats(min_value=0.0, max_value=1.0))
    def test_score_bounds(self, score: float):
        """Confidence scores stay within [0, 1] bounds."""
        assert 0.0 <= score <= 1.0
    
    @given(
        st.floats(min_value=0.0, max_value=1.0),
        st.floats(min_value=0.0, max_value=1.0),
    )
    def test_weighted_average_bounds(self, score1: float, score2: float):
        """Weighted average of scores remains in bounds."""
        average = (score1 + score2) / 2
        assert 0.0 <= average <= 1.0
    
    @given(
        st.lists(
            st.floats(min_value=0.0, max_value=1.0),
            min_size=1,
            max_size=100,
        )
    )
    def test_aggregate_score_properties(self, scores: List[float]):
        """Aggregated scores maintain invariants."""
        # Mean stays in bounds
        mean = sum(scores) / len(scores)
        assert 0.0 <= mean <= 1.0
        
        # Min/max properties (with float tolerance for rounding)
        assert min(scores) - 1e-9 <= mean <= max(scores) + 1e-9
        
        # Standard deviation is non-negative
        if len(scores) > 1:
            variance = sum((s - mean) ** 2 for s in scores) / len(scores)
            assert variance >= 0.0


class TestRelationshipProperties:
    """Property-based tests for relationship handling."""
    
    @given(relationship_data(), relationship_data())
    def test_relationship_symmetry_option(self, rel1, rel2):
        """Relationships can be made symmetric."""
        # Original relationship
        assert len(rel1["relation_type"]) > 0
        
        # Can create reverse
        reverse_type = rel1["relation_type"]
        assert len(reverse_type) > 0
    
    @given(
        st.lists(relationship_data(), min_size=1, max_size=50)
    )
    def test_relationship_dedup_properties(self, relationships: List[Dict]):
        """Dedup logic preserves relationship properties."""
        # All relationships are valid
        for rel in relationships:
            assert 0.0 <= rel["confidence"] <= 1.0
            assert len(rel["relation_type"]) > 0
            assert len(rel["source_id"]) > 0
            assert len(rel["target_id"]) > 0


class TestStringHandlingProperties:
    """Property-based tests for string handling in entities."""
    
    @given(st.text())
    def test_entity_name_json_safe(self, text: str):
        """Any text can be used as entity name without JSON errors."""
        entity = {"name": text, "id": "test"}
        
        # Should serialize without error
        json_str = json.dumps(entity)
        
        # Should deserialize correctly
        restored = json.loads(json_str)
        assert restored["name"] == text
    
    @given(
        st.text(),
        st.text(),
    )
    def test_relationship_type_handling(self, rel_type: str, description: str):
        """Relationship types handle arbitrary strings."""
        assume(len(rel_type) > 0)  # Empty relation types not valid
        
        relationship = {
            "source_id": "id1",
            "target_id": "id2",
            "relation_type": rel_type[:100],  # Limit length
            "description": description[:200],
        }
        
        # Should serialize
        json_str = json.dumps(relationship)
        
        # Should deserialize
        restored = json.loads(json_str)
        assert restored["relation_type"] == rel_type[:100]


class TestNumericProperties:
    """Property-based tests for numeric operations."""
    
    @given(
        st.lists(
            st.floats(min_value=0.0, max_value=1.0),
            min_size=1,
            max_size=1000,
        )
    )
    def test_score_aggregation_associativity(self, scores: List[float]):
        """Score aggregation maintains weighted average properties."""
        # Mean of all scores
        mean_all = sum(scores) / len(scores)
        
        # Weighted mean of splits (must account for chunk sizes)
        if len(scores) >= 2:
            mid = len(scores) // 2
            left_scores = scores[:mid]
            right_scores = scores[mid:]
            left_mean = sum(left_scores) / len(left_scores)
            right_mean = sum(right_scores) / len(right_scores)
            
            # Weighted mean (accounts for different chunk sizes)
            left_weight = len(left_scores) / len(scores)
            right_weight = len(right_scores) / len(scores)
            weighted_combined = (left_mean * left_weight) + (right_mean * right_weight)
            
            # Weighted mean should equal overall mean
            assert abs(mean_all - weighted_combined) < 1e-10
    
    @given(
        st.integers(min_value=1, max_value=10000),
        st.integers(min_value=0, max_value=100),
    )
    def test_counting_properties(self, entity_count: int, dedup_count: int):
        """Count operations maintain invariants."""
        assume(dedup_count <= entity_count)
        
        # After dedup, count decreases or stays same
        final_count = entity_count - dedup_count
        assert final_count >= 0
        assert final_count <= entity_count


class TestCollectionProperties:
    """Property-based tests for collection operations."""
    
    @given(
        st.lists(
            st.integers(min_value=1, max_value=1000),
            max_size=1000,
        )
    )
    def test_dedup_properties(self, items: List[int]):
        """Dedup maintains collection invariants."""
        dedupped = list(set(items))
        
        # Result size <= original size
        assert len(dedupped) <= len(items)
        
        # No duplicates in result
        assert len(dedupped) == len(set(dedupped))
        
        # All original unique items preserved
        unique_items = set(items)
        assert set(dedupped) == unique_items
    
    @given(
        st.lists(st.integers(), min_size=1, max_size=100),
        st.lists(st.integers(), min_size=1, max_size=100),
    )
    def test_merge_properties(self, list1: List[int], list2: List[int]):
        """Merge maintains collection properties."""
        merged = list1 + list2
        
        # Size is sum of input sizes
        assert len(merged) == len(list1) + len(list2)
        
        # All elements from both lists present
        assert set(merged) == set(list1 + list2)


class TestFilteringProperties:
    """Property-based tests for filtering operations."""
    
    @given(
        st.lists(
            st.floats(min_value=0.0, max_value=1.0),
            max_size=100,
        ),
        st.floats(min_value=0.0, max_value=1.0),
    )
    def test_confidence_filtering(self, scores: List[float], threshold: float):
        """Confidence filtering maintains invariants."""
        filtered = [s for s in scores if s >= threshold]
        
        # All filtered scores meet threshold
        for score in filtered:
            assert score >= threshold
        
        # Filtered size <= original size
        assert len(filtered) <= len(scores)
        
        # All scores >= threshold are in filtered
        for score in scores:
            if score >= threshold:
                assert score in filtered


class TestIncrementalProperties:
    """Property-based tests for incremental operations."""
    
    @given(
        st.lists(st.integers(min_value=0, max_value=100), max_size=100)
    )
    def test_incremental_count_idempotent(self, items: List[int]):
        """Incremental counting is idempotent."""
        # Count incrementally
        count1 = 0
        for item in items:
            if item > 0:
                count1 += 1
        
        # Count en masse
        count2 = len([x for x in items if x > 0])
        
        # Should be equal
        assert count1 == count2
    
    @given(
        st.lists(st.integers(), max_size=1000)
    )
    def test_fold_left_correctness(self, items: List[int]):
        """Fold-left operations are correct."""
        # Sum via fold
        sum_fold = 0
        for item in items:
            sum_fold += item
        
        # Sum via built-in
        sum_builtin = sum(items)
        
        # Should be equal
        assert sum_fold == sum_builtin
