"""Property-based tests for ontology stats mathematical consistency.

Verifies that various statistics and metrics computed on ontologies satisfy
mathematical invariants and consistency properties using Hypothesis-generated
random inputs.
"""

import pytest
from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    OntologyGenerator,
    Relationship,
    OntologyGenerationContext,
    DataType,
    ExtractionStrategy,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import (
    OntologyCritic,
    CriticScore,
)
from tests.unit.optimizers.graphrag.strategies import valid_entity


# ──────────────────────────────────────────────────────────────────────────────
# Hypothesis strategies for ontology structures
# ──────────────────────────────────────────────────────────────────────────────

@st.composite
def valid_extraction_result(draw):
    """Generate a valid EntityExtractionResult with random entities and relationships."""
    entities = draw(st.lists(valid_entity(), min_size=0, max_size=20))
    
    # Create relationships between existing entities
    if len(entities) >= 2:
        num_relationships = draw(st.integers(min_value=0, max_value=min(10, len(entities) * 2)))
        relationships = []
        for i in range(num_relationships):
            source_entity = draw(st.sampled_from(entities))
            target_entity = draw(st.sampled_from(entities))
            rel_type = draw(st.sampled_from(["has", "is", "part_of", "related_to", "mentions"]))
            rel_confidence = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
            relationships.append(Relationship(
                id=f"rel_{i}",
                source_id=source_entity.id,
                target_id=target_entity.id,
                type=rel_type,
                confidence=rel_confidence,
            ))
    else:
        relationships = []
    
    confidence = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
    
    return EntityExtractionResult(
        entities=entities,
        relationships=relationships,
        confidence=confidence,
        metadata={},
    )


@st.composite
def valid_ontology_dict(draw):
    """Generate a valid ontology dict structure."""
    entities_list = draw(st.lists(valid_entity(), min_size=0, max_size=15))
    entities_dicts = [
        {
            "id": e.id,
            "type": e.type,
            "text": e.text,
            "confidence": e.confidence,
            "properties": e.properties,
        }
        for e in entities_list
    ]
    
    # Create relationships between entities
    if len(entities_dicts) >= 2:
        num_rels = draw(st.integers(min_value=0, max_value=min(8, len(entities_dicts) * 2)))
        relationships = []
        for _ in range(num_rels):
            source_e = draw(st.sampled_from(entities_dicts))
            target_e = draw(st.sampled_from(entities_dicts))
            rel_type = draw(st.sampled_from(["related", "connected", "has", "is"]))
            relationships.append({
                "source": source_e["id"],
                "target": target_e["id"],
                "type": rel_type,
            })
    else:
        relationships = []
    
    return {
        "entities": entities_dicts,
        "relationships": relationships,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Property tests for EntityExtractionResult statistics
# ──────────────────────────────────────────────────────────────────────────────

class TestEntityExtractionResultProperties:
    """Property tests for EntityExtractionResult stats consistency."""

    @given(result=valid_extraction_result())
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_is_empty_matches_no_entities_and_relationships(self, result: EntityExtractionResult):
        """is_empty() is True iff both entities and relationships are empty."""
        expected_empty = len(result.entities) == 0 and len(result.relationships) == 0
        assert result.is_empty() == expected_empty

    @given(result=valid_extraction_result())
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_filter_by_confidence_reduces_or_maintains_count(self, result: EntityExtractionResult):
        """Filtering reduces or maintains entity count, never increases."""
        assume(len(result.entities) > 0)  # Skip empty results
        
        # Get a threshold that won't filter everything
        threshold = 0.3
        filtered = result.filter_by_confidence(threshold)
        
        assert len(filtered.entities) <= len(result.entities)
        assert len(filtered.relationships) <= len(result.relationships)

    @given(result=valid_extraction_result(), threshold=st.floats(min_value=0.0, max_value=1.0))
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_filter_by_confidence_only_keeps_high_confidence_entities(
        self, result: EntityExtractionResult, threshold: float
    ):
        """All entities in filtered result have confidence >= threshold."""
        filtered = result.filter_by_confidence(threshold)
        
        for entity in filtered.entities:
            assert entity.confidence >= threshold

    @given(result=valid_extraction_result())
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_filter_at_zero_threshold_keeps_all_entities(self, result: EntityExtractionResult):
        """Filtering with threshold=0.0 keeps all entities."""
        filtered = result.filter_by_confidence(0.0)
        
        assert len(filtered.entities) == len(result.entities)

    @given(result=valid_extraction_result())
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_filter_at_one_threshold_only_keeps_perfect_entities(self, result: EntityExtractionResult):
        """Filtering with threshold=1.0 only keeps entities with confidence=1.0."""
        filtered = result.filter_by_confidence(1.0)
        
        for entity in filtered.entities:
            assert entity.confidence == 1.0
        
        # Count should match entities with confidence == 1.0
        expected_count = sum(1 for e in result.entities if e.confidence == 1.0)
        assert len(filtered.entities) == expected_count


# ──────────────────────────────────────────────────────────────────────────────
# Property tests for OntologyGenerator.filter_by_confidence() stats
# ──────────────────────────────────────────────────────────────────────────────

class TestOntologyGeneratorFilterStatsProperties:
    """Property tests for filter_by_confidence() statistics consistency."""

    @given(result=valid_extraction_result(), threshold=st.floats(min_value=0.0, max_value=1.0))
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_retention_rate_matches_filtered_over_original(
        self, result: EntityExtractionResult, threshold: float
    ):
        """retention_rate = filtered_entity_count / original_entity_count."""
        assume(len(result.entities) > 0)  # Avoid division by zero
        
        generator = OntologyGenerator()
        filtered_data = generator.filter_by_confidence(result, threshold)
        stats = filtered_data["stats"]
        
        expected_retention = stats["filtered_entity_count"] / stats["original_entity_count"]
        assert stats["retention_rate"] == pytest.approx(expected_retention, abs=1e-9)

    @given(result=valid_extraction_result(), threshold=st.floats(min_value=0.0, max_value=1.0))
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_removed_count_equals_original_minus_filtered(
        self, result: EntityExtractionResult, threshold: float
    ):
        """removed_entity_count = original_entity_count - filtered_entity_count."""
        generator = OntologyGenerator()
        filtered_data = generator.filter_by_confidence(result, threshold)
        stats = filtered_data["stats"]
        
        expected_removed = stats["original_entity_count"] - stats["filtered_entity_count"]
        assert stats["removed_entity_count"] == expected_removed
        
        expected_removed_rels = stats["original_relationship_count"] - stats["filtered_relationship_count"]
        assert stats["removed_relationship_count"] == expected_removed_rels

    @given(result=valid_extraction_result(), threshold=st.floats(min_value=0.0, max_value=1.0))
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_filtered_entity_count_matches_result_length(
        self, result: EntityExtractionResult, threshold: float
    ):
        """filtered_entity_count matches len(filtered_result.entities)."""
        generator = OntologyGenerator()
        filtered_data = generator.filter_by_confidence(result, threshold)
        stats = filtered_data["stats"]
        filtered_result = filtered_data["result"]
        
        assert stats["filtered_entity_count"] == len(filtered_result.entities)
        assert stats["filtered_relationship_count"] == len(filtered_result.relationships)

    @given(result=valid_extraction_result(), threshold=st.floats(min_value=0.0, max_value=1.0))
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_avg_confidence_after_greater_equal_threshold(
        self, result: EntityExtractionResult, threshold: float
    ):
        """avg_confidence_after >= threshold (when entities remain)."""
        assume(len(result.entities) > 0)
        
        generator = OntologyGenerator()
        filtered_data = generator.filter_by_confidence(result, threshold)
        stats = filtered_data["stats"]
        
        if stats["filtered_entity_count"] > 0:
            assert stats["avg_confidence_after"] >= threshold or \
                   abs(stats["avg_confidence_after"] - threshold) < 1e-9

    @given(result=valid_extraction_result(), threshold=st.floats(min_value=0.0, max_value=1.0))
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_avg_confidence_after_greater_equal_before(
        self, result: EntityExtractionResult, threshold: float
    ):
        """avg_confidence_after >= avg_confidence_before (filtering removes low confidence)."""
        assume(len(result.entities) > 0)
        
        generator = OntologyGenerator()
        filtered_data = generator.filter_by_confidence(result, threshold)
        stats = filtered_data["stats"]
        
        if stats["filtered_entity_count"] > 0:
            assert stats["avg_confidence_after"] >= stats["avg_confidence_before"] or \
                   abs(stats["avg_confidence_after"] - stats["avg_confidence_before"]) < 1e-9

    @given(result=valid_extraction_result(), threshold=st.floats(min_value=0.0, max_value=1.0))
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_retention_rate_in_zero_to_one_range(
        self, result: EntityExtractionResult, threshold: float
    ):
        """retention_rate is always in [0.0, 1.0]."""
        generator = OntologyGenerator()
        filtered_data = generator.filter_by_confidence(result, threshold)
        stats = filtered_data["stats"]
        
        assert 0.0 <= stats["retention_rate"] <= 1.0

    @given(result=valid_extraction_result())
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_stats_dict_has_all_expected_keys(self, result: EntityExtractionResult):
        """Stats dict contains all 10 expected keys."""
        generator = OntologyGenerator()
        filtered_data = generator.filter_by_confidence(result, 0.5)
        stats = filtered_data["stats"]
        
        expected_keys = {
            "original_entity_count",
            "filtered_entity_count",
            "removed_entity_count",
            "original_relationship_count",
            "filtered_relationship_count",
            "removed_relationship_count",
            "threshold",
            "retention_rate",
            "avg_confidence_before",
            "avg_confidence_after",
        }
        assert set(stats.keys()) == expected_keys


# ──────────────────────────────────────────────────────────────────────────────
# Property tests for OntologyCritic score consistency
# ──────────────────────────────────────────────────────────────────────────────

class TestOntologyCriticScoreProperties:
    """Property tests for CriticScore mathematical consistency."""

    @pytest.fixture
    def ctx(self):
        """Create a shared context fixture for all tests."""
        return OntologyGenerationContext(
            data_source="test",
            data_type=DataType.TEXT,
            domain="general",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
        )

    @given(ontology=valid_ontology_dict())
    @settings(
        max_examples=30,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_all_dimension_scores_in_zero_to_one_range(self, ontology: dict, ctx):
        """All dimension scores are in [0.0, 1.0]."""
        assume(len(ontology.get("entities", [])) > 0)  # Need non-empty ontology
        
        critic = OntologyCritic()
        result = critic.evaluate(ontology, ctx)
        score = result.dimensions  # CriticResult has dimensions dict
        
        assert 0.0 <= score["completeness"] <= 1.0
        assert 0.0 <= score["consistency"] <= 1.0
        # Note: CriticResult uses different dimension names
        assert 0.0 <= score.get("clarity", 0.0) <= 1.0
        assert 0.0 <= score.get("granularity", 0.0) <= 1.0
        assert 0.0 <= score.get("relationship_coherence", 0.0) <= 1.0

    @given(ontology=valid_ontology_dict())
    @settings(
        max_examples=30,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_overall_score_in_zero_to_one_range(self, ontology: dict, ctx):
        """overall score is in [0.0, 1.0]."""
        assume(len(ontology.get("entities", [])) > 0)
        
        critic = OntologyCritic()
        result = critic.evaluate(ontology, ctx)
        
        assert 0.0 <= result.score <= 1.0

    @given(ontology=valid_ontology_dict())
    @settings(
        max_examples=30,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_get_worst_entity_returns_none_or_valid_id(self, ontology: dict, ctx):
        """get_worst_entity() returns None or an entity ID from ontology."""
        critic = OntologyCritic()
        worst_id = critic.get_worst_entity(ontology)
        
        if worst_id is None:
            # Should be None for empty ontologies
            assert len(ontology.get("entities", [])) == 0 or \
                   all("id" not in e for e in ontology.get("entities", []))
        else:
            # Should be a valid entity ID
            entity_ids = {e.get("id") for e in ontology.get("entities", []) if "id" in e}
            assert worst_id in entity_ids
