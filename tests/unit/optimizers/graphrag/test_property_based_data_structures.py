"""Property-based tests for core GraphRAG data structures using Hypothesis.

These tests use Hypothesis to generate random valid instances and verify
invariants that should always hold, such as:
- Round-trip serialization (to_dict → from_dict identity)
- Bounds validation (confidence, scores in [0.0, 1.0])
- Type consistency and immutability properties
- Statistical properties (weighted averages, ratios)
- Configuration constraint satisfaction (max > min, non-negative counts)
"""

import pytest
from hypothesis import given, assume, strategies as st, settings, HealthCheck
from typing import Dict, List, Any

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    Relationship,
    ExtractionConfig,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore


# ==============================================================================
# Hypothesis strategies for generating test data
# ==============================================================================

@st.composite
def entity_strategy(draw):
    """Generate a random valid Entity instance."""
    entity_id = draw(st.text(min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz0123456789_"))
    entity_type = draw(st.sampled_from([
        "Person", "Organization", "Location", "Event", "Concept", "Product",
        "Service", "Document", "Obligation", "Right"
    ]))
    text = draw(st.text(
        min_size=1,
        max_size=100,
        alphabet=st.characters(blacklist_characters="\x00\n\r"),
    ))
    
    # Generate random properties (0-3 properties)
    num_props = draw(st.integers(min_value=0, max_value=3))
    properties = {
        f"prop_{i}": draw(st.one_of(
            st.text(max_size=20),
            st.integers(min_value=0, max_value=1000),
            st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
        ))
        for i in range(num_props)
    }
    
    confidence = draw(st.floats(
        min_value=0.0,
        max_value=1.0,
        allow_nan=False,
        allow_infinity=False,
    ))
    
    # Optional source span
    source_span = None
    if draw(st.booleans()):
        start = draw(st.integers(min_value=0, max_value=1000))
        end = draw(st.integers(min_value=start, max_value=start + 100))
        source_span = (start, end)
    
    # Optional last_seen timestamp
    last_seen = None
    if draw(st.booleans()):
        last_seen = draw(st.floats(
            min_value=1000000000.0,  # ~year 2001
            max_value=2000000000.0,  # ~year 2033
            allow_nan=False,
            allow_infinity=False,
        ))
    
    return Entity(
        id=entity_id,
        type=entity_type,
        text=text,
        properties=properties,
        confidence=confidence,
        source_span=source_span,
        last_seen=last_seen,
    )


@st.composite
def relationship_strategy(draw, entity_ids=None):
    """Generate a random valid Relationship instance."""
    rel_id = draw(st.text(
        min_size=1,
        max_size=20,
        alphabet="abcdefghijklmnopqrstuvwxyz0123456789_",
    ))
    
    # Use provided entity IDs or generate random ones
    if entity_ids and len(entity_ids) >= 2:
        source_id = draw(st.sampled_from(entity_ids))
        target_id = draw(st.sampled_from(entity_ids))
    else:
        source_id = draw(st.text(min_size=1, max_size=10, alphabet="abcdefghijk"))
        target_id = draw(st.text(min_size=1, max_size=10, alphabet="abcdefghijk"))
    
    rel_type = draw(st.sampled_from([
        "owns", "works_for", "located_in", "caused_by", "related_to",
        "mentions", "contains", "obligates", "permits", "requires",
    ]))
    
    # Random properties
    num_props = draw(st.integers(min_value=0, max_value=2))
    properties = {
        f"prop_{i}": draw(st.one_of(
            st.text(max_size=20),
            st.integers(min_value=0, max_value=100),
        ))
        for i in range(num_props)
    }
    
    confidence = draw(st.floats(
        min_value=0.0,
        max_value=1.0,
        allow_nan=False,
        allow_infinity=False,
    ))
    
    direction = draw(st.sampled_from([
        "subject_to_object",
        "undirected",
        "unknown",
    ]))
    
    return Relationship(
        id=rel_id,
        source_id=source_id,
        target_id=target_id,
        type=rel_type,
        properties=properties,
        confidence=confidence,
        direction=direction,
    )


@st.composite
def extraction_config_strategy(draw):
    """Generate a random valid ExtractionConfig instance."""
    # All fields have valid ranges and defaults
    return ExtractionConfig(
        confidence_threshold=draw(st.floats(
            min_value=0.0,
            max_value=1.0,
            allow_nan=False,
            allow_infinity=False,
        )),
        max_entities=draw(st.integers(min_value=0, max_value=5000)),
        max_relationships=draw(st.integers(min_value=0, max_value=5000)),
        window_size=draw(st.integers(min_value=1, max_value=100)),
        sentence_window=draw(st.integers(min_value=0, max_value=50)),
        include_properties=draw(st.booleans()),
        domain_vocab={},  # Simplified to reduce complexity
        custom_rules=[],  # Simplified
        llm_fallback_threshold=draw(st.floats(
            min_value=0.0,
            max_value=1.0,
            allow_nan=False,
            allow_infinity=False,
        )),
        min_entity_length=draw(st.integers(min_value=1, max_value=20)),
        stopwords=draw(st.lists(
            st.text(min_size=1, max_size=10),
            max_size=10,
        )),
        allowed_entity_types=draw(st.lists(
            st.text(min_size=1, max_size=20),
            max_size=5,
        )),
        max_confidence=draw(st.floats(
            min_value=0.5,
            max_value=1.0,
            allow_nan=False,
            allow_infinity=False,
        )),
        enable_parallel_inference=draw(st.booleans()),
        max_workers=draw(st.integers(min_value=1, max_value=16)),
    )


@st.composite
def critic_score_strategy(draw):
    """Generate a random valid CriticScore instance."""
    dimensions = {
        "completeness": draw(st.floats(
            min_value=0.0,
            max_value=1.0,
            allow_nan=False,
            allow_infinity=False,
        )),
        "consistency": draw(st.floats(
            min_value=0.0,
            max_value=1.0,
            allow_nan=False,
            allow_infinity=False,
        )),
        "clarity": draw(st.floats(
            min_value=0.0,
            max_value=1.0,
            allow_nan=False,
            allow_infinity=False,
        )),
        "granularity": draw(st.floats(
            min_value=0.0,
            max_value=1.0,
            allow_nan=False,
            allow_infinity=False,
        )),
        "relationship_coherence": draw(st.floats(
            min_value=0.0,
            max_value=1.0,
            allow_nan=False,
            allow_infinity=False,
        )),
        "domain_alignment": draw(st.floats(
            min_value=0.0,
            max_value=1.0,
            allow_nan=False,
            allow_infinity=False,
        )),
    }
    
    num_strengths = draw(st.integers(min_value=0, max_value=3))
    strengths = [
        draw(st.text(min_size=5, max_size=50))
        for _ in range(num_strengths)
    ]
    
    num_weaknesses = draw(st.integers(min_value=0, max_value=3))
    weaknesses = [
        draw(st.text(min_size=5, max_size=50))
        for _ in range(num_weaknesses)
    ]
    
    num_recommendations = draw(st.integers(min_value=0, max_value=3))
    recommendations = [
        draw(st.text(min_size=5, max_size=50))
        for _ in range(num_recommendations)
    ]
    
    return CriticScore(
        completeness=dimensions["completeness"],
        consistency=dimensions["consistency"],
        clarity=dimensions["clarity"],
        granularity=dimensions["granularity"],
        relationship_coherence=dimensions["relationship_coherence"],
        domain_alignment=dimensions["domain_alignment"],
        strengths=strengths,
        weaknesses=weaknesses,
        recommendations=recommendations,
        metadata={},
    )


# ==============================================================================
# Entity property tests
# ==============================================================================

class TestEntityProperties:
    """Test invariants for Entity instances."""
    
    @given(entity_strategy())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_entity_round_trip_serialization(self, entity):
        """Entity → dict → Entity should be identity (except mutable fields)."""
        d = entity.to_dict()
        entity2 = Entity.from_dict(d)
        
        # Check all fields
        assert entity2.id == entity.id
        assert entity2.type == entity.type
        assert entity2.text == entity.text
        assert entity2.confidence == entity.confidence
        assert entity2.properties == entity.properties
        assert entity2.source_span == entity.source_span
        assert entity2.last_seen == entity.last_seen
    
    @given(entity_strategy())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_entity_to_dict_has_required_fields(self, entity):
        """Entity.to_dict() must include all required fields."""
        d = entity.to_dict()
        
        required_fields = {"id", "type", "text", "confidence", "properties", "source_span", "last_seen"}
        assert required_fields.issubset(set(d.keys()))
    
    @given(entity_strategy())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_entity_confidence_in_bounds(self, entity):
        """Entity confidence must be in [0.0, 1.0]."""
        assert 0.0 <= entity.confidence <= 1.0
    
    @given(entity_strategy())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_entity_text_not_empty(self, entity):
        """Entity text must be non-empty."""
        assert len(entity.text) > 0
    
    @given(entity_strategy())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_entity_id_not_empty(self, entity):
        """Entity ID must be non-empty."""
        assert len(entity.id) > 0
    
    @given(entity_strategy())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_entity_type_not_empty(self, entity):
        """Entity type must be non-empty."""
        assert len(entity.type) > 0
    
    @given(entity_strategy())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_entity_source_span_valid_range(self, entity):
        """Source span must have start <= end if present."""
        if entity.source_span is not None:
            start, end = entity.source_span
            assert start >= 0
            assert end >= start
    
    @given(entity_strategy())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_entity_to_json_valid(self, entity):
        """Entity.to_json() must produce valid JSON string."""
        import json
        json_str = entity.to_json()
        # Should not raise
        parsed = json.loads(json_str)
        
        assert parsed["id"] == entity.id
        assert parsed["type"] == entity.type
        assert parsed["text"] == entity.text


# ==============================================================================
# Relationship property tests
# ==============================================================================

class TestRelationshipProperties:
    """Test invariants for Relationship instances."""
    
    @given(relationship_strategy())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_relationship_round_trip_serialization(self, rel):
        """Relationship → dict → Relationship should be identity."""
        d = rel.to_dict()
        rel2 = Relationship.from_dict(d)
        
        assert rel2.id == rel.id
        assert rel2.source_id == rel.source_id
        assert rel2.target_id == rel.target_id
        assert rel2.type == rel.type
        assert rel2.confidence == rel.confidence
        assert rel2.properties == rel.properties
        assert rel2.direction == rel.direction
    
    @given(relationship_strategy())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_relationship_to_dict_has_required_fields(self, rel):
        """Relationship.to_dict() must include all required fields."""
        d = rel.to_dict()
        
        required_fields = {"id", "source_id", "target_id", "type", "confidence", "properties", "direction"}
        assert required_fields.issubset(set(d.keys()))
    
    @given(relationship_strategy())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_relationship_confidence_in_bounds(self, rel):
        """Relationship confidence must be in [0.0, 1.0]."""
        assert 0.0 <= rel.confidence <= 1.0
    
    @given(relationship_strategy())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_relationship_direction_valid(self, rel):
        """Relationship direction must be one of known values."""
        valid_directions = {"subject_to_object", "undirected", "unknown"}
        assert rel.direction in valid_directions
    
    @given(relationship_strategy())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_relationship_source_target_not_empty(self, rel):
        """Source and target IDs must be non-empty."""
        assert len(rel.source_id) > 0
        assert len(rel.target_id) > 0
    
    @given(relationship_strategy())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_relationship_equality(self, rel):
        """Relationship equality based on all fields."""
        rel_copy = Relationship.from_dict(rel.to_dict())
        assert rel == rel_copy
    
    @given(relationship_strategy())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_relationship_to_json_valid(self, rel):
        """Relationship.to_json() must produce valid JSON string."""
        import json
        json_str = rel.to_json()
        parsed = json.loads(json_str)
        
        assert parsed["id"] == rel.id
        assert parsed["source_id"] == rel.source_id
        assert parsed["target_id"] == rel.target_id


# ==============================================================================
# ExtractionConfig property tests
# ==============================================================================

class TestExtractionConfigProperties:
    """Test invariants for ExtractionConfig instances."""
    
    @given(extraction_config_strategy())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_extraction_config_round_trip_serialization(self, config):
        """ExtractionConfig → dict → ExtractionConfig should be identity."""
        d = config.to_dict()
        config2 = ExtractionConfig.from_dict(d)
        
        assert config2.confidence_threshold == config.confidence_threshold
        assert config2.max_entities == config.max_entities
        assert config2.max_relationships == config.max_relationships
        assert config2.window_size == config.window_size
        assert config2.sentence_window == config.sentence_window
        assert config2.include_properties == config.include_properties
        assert config2.llm_fallback_threshold == config.llm_fallback_threshold
        assert config2.min_entity_length == config.min_entity_length
        assert config2.max_confidence == config.max_confidence
    
    @given(extraction_config_strategy())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_extraction_config_confidence_thresholds_in_bounds(self, config):
        """Confidence thresholds must be in valid ranges."""
        assert 0.0 <= config.confidence_threshold <= 1.0
        assert 0.0 <= config.llm_fallback_threshold <= 1.0
        assert 0.5 <= config.max_confidence <= 1.0
    
    @given(extraction_config_strategy())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_extraction_config_positive_integers(self, config):
        """Integer bounds must be non-negative."""
        assert config.max_entities >= 0
        assert config.max_relationships >= 0
        assert config.window_size >= 1
        assert config.sentence_window >= 0
        assert config.min_entity_length >= 1
        assert config.max_workers >= 1
    
    @given(extraction_config_strategy())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_extraction_config_lists_are_lists(self, config):
        """Config lists should remain lists after round-trip."""
        d = config.to_dict()
        config2 = ExtractionConfig.from_dict(d)
        
        assert isinstance(config2.stopwords, list)
        assert isinstance(config2.allowed_entity_types, list)
    
    @given(extraction_config_strategy())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_extraction_config_booleans_preserved(self, config):
        """Boolean flags must be preserved."""
        d = config.to_dict()
        config2 = ExtractionConfig.from_dict(d)
        
        assert config2.include_properties == config.include_properties
        assert config2.enable_parallel_inference == config.enable_parallel_inference


# ==============================================================================
# CriticScore property tests
# ==============================================================================

class TestCriticScoreProperties:
    """Test invariants for CriticScore instances."""
    
    @given(critic_score_strategy())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_critic_score_dimensions_in_bounds(self, score):
        """All score dimensions must be in [0.0, 1.0]."""
        assert 0.0 <= score.completeness <= 1.0
        assert 0.0 <= score.consistency <= 1.0
        assert 0.0 <= score.clarity <= 1.0
        assert 0.0 <= score.granularity <= 1.0
        assert 0.0 <= score.relationship_coherence <= 1.0
        assert 0.0 <= score.domain_alignment <= 1.0
    
    @given(critic_score_strategy())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_critic_score_overall_in_bounds(self, score):
        """Overall score (weighted average) must be in [0.0, 1.0]."""
        assert 0.0 <= score.overall <= 1.0
    
    @given(critic_score_strategy())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_critic_score_overall_is_weighted_average(self, score):
        """Overall score should be weighted average of dimensions."""
        # Get the weights from the CriticScore module
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import DIMENSION_WEIGHTS
        
        expected = (
            DIMENSION_WEIGHTS['completeness'] * score.completeness +
            DIMENSION_WEIGHTS['consistency'] * score.consistency +
            DIMENSION_WEIGHTS['clarity'] * score.clarity +
            DIMENSION_WEIGHTS['granularity'] * score.granularity +
            DIMENSION_WEIGHTS['relationship_coherence'] * score.relationship_coherence +
            DIMENSION_WEIGHTS['domain_alignment'] * score.domain_alignment
        )
        
        assert abs(score.overall - expected) < 1e-6
    
    @given(critic_score_strategy())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_critic_score_to_list_has_six_values(self, score):
        """to_list() must return exactly 6 dimension scores."""
        scores_list = score.to_list()
        
        assert len(scores_list) == 6
        assert all(0.0 <= s <= 1.0 for s in scores_list)
    
    @given(critic_score_strategy())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_critic_score_to_list_order(self, score):
        """to_list() must return values in canonical order."""
        scores_list = score.to_list()
        
        assert scores_list[0] == score.completeness
        assert scores_list[1] == score.consistency
        assert scores_list[2] == score.clarity
        assert scores_list[3] == score.granularity
        assert scores_list[4] == score.relationship_coherence
        assert scores_list[5] == score.domain_alignment
    
    @given(critic_score_strategy())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_critic_score_to_dict_has_required_fields(self, score):
        """to_dict() must include all required fields."""
        d = score.to_dict()
        
        required_fields = {"overall", "dimensions", "weights", "strengths", "weaknesses", "recommendations"}
        assert required_fields.issubset(set(d.keys()))
        
        assert isinstance(d["dimensions"], dict)
        assert len(d["dimensions"]) == 6
    
    @given(critic_score_strategy())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_critic_score_feedback_are_lists(self, score):
        """Strengths, weaknesses, and recommendations must be lists."""
        assert isinstance(score.strengths, list)
        assert isinstance(score.weaknesses, list)
        assert isinstance(score.recommendations, list)
    
    @given(critic_score_strategy(), st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_critic_score_is_passing_threshold(self, score, threshold):
        """is_passing() should correctly evaluate threshold."""
        result = score.is_passing(threshold=threshold)
        
        if score.overall >= threshold:
            assert result is True
        else:
            assert result is False


# ==============================================================================
# Cross-property tests
# ==============================================================================

class TestDataStructureConsistency:
    """Test consistency across data structures."""
    
    @given(entity_strategy())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_entity_copy_with_preserves_other_fields(self, entity):
        """copy_with() should preserve unmodified fields."""
        modified = entity.copy_with(confidence=0.5)
        
        assert modified.id == entity.id
        assert modified.type == entity.type
        assert modified.text == entity.text
        assert modified.confidence == 0.5
        assert modified.properties == entity.properties
    
    @given(extraction_config_strategy())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_extraction_config_determinism(self, config):
        """Converting config twice should produce identical results."""
        d1 = config.to_dict()
        config_copy = ExtractionConfig.from_dict(d1)
        d2 = config_copy.to_dict()
        
        assert d1 == d2
    
    @given(critic_score_strategy())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_critic_score_determinism(self, score):
        """Overall score should be computed consistently."""
        overall1 = score.overall
        overall2 = score.overall
        
        assert overall1 == overall2


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
