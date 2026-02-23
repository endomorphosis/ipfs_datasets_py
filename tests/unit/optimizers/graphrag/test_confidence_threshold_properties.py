"""Property-based tests for confidence threshold filtering and ordering constraints."""

from __future__ import annotations

from hypothesis import given, settings, strategies as st, assume

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    Relationship,
    EntityExtractionResult,
    OntologyGenerator,
)


def _build_result(confidences: list[float]) -> EntityExtractionResult:
    entities = [
        Entity(
            id=f"e{i}",
            type="Concept",
            text=f"Entity {i}",
            confidence=conf,
            properties={},
        )
        for i, conf in enumerate(confidences)
    ]
    relationships = []
    for i in range(len(entities) - 1):
        relationships.append(
            Relationship(
                id=f"r{i}",
                source_id=entities[i].id,
                target_id=entities[i + 1].id,
                type="related_to",
                confidence=min(entities[i].confidence, entities[i + 1].confidence),
                properties={},
            )
        )
    return EntityExtractionResult(
        entities=entities,
        relationships=relationships,
        confidence=1.0,
        metadata={},
        errors=[],
    )


@given(
    confidences=st.lists(
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=30,
    ),
    threshold_low=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    threshold_high=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
)
def test_filter_by_confidence_monotonic_entities(confidences, threshold_low, threshold_high):
    """Higher thresholds should never increase the number of retained entities."""
    assume(threshold_low <= threshold_high)
    result = _build_result(confidences)

    filtered_low = result.filter_by_confidence(threshold_low)
    filtered_high = result.filter_by_confidence(threshold_high)

    assert len(filtered_high.entities) <= len(filtered_low.entities)
    assert all(e.confidence >= threshold_high for e in filtered_high.entities)
    assert all(e.confidence >= threshold_low for e in filtered_low.entities)


@given(
    confidences=st.lists(
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        min_size=2,
        max_size=20,
    ),
    threshold=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
)
def test_filter_by_confidence_prunes_relationships(confidences, threshold):
    """Filtered relationships must only reference retained entities."""
    result = _build_result(confidences)
    filtered = result.filter_by_confidence(threshold)

    kept_ids = {e.id for e in filtered.entities}
    for rel in filtered.relationships:
        assert rel.source_id in kept_ids
        assert rel.target_id in kept_ids


@given(
    confidences=st.lists(
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=30,
    ),
    threshold_low=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    threshold_high=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
)
@settings(deadline=None)
def test_generator_filter_stats_monotonic(confidences, threshold_low, threshold_high):
    """Generator filter stats should be monotonic as thresholds increase."""
    assume(threshold_low <= threshold_high)
    result = _build_result(confidences)

    generator = OntologyGenerator()
    data_low = generator.filter_by_confidence(result, threshold=threshold_low)
    data_high = generator.filter_by_confidence(result, threshold=threshold_high)

    stats_low = data_low["stats"]
    stats_high = data_high["stats"]

    assert stats_high["filtered_entity_count"] <= stats_low["filtered_entity_count"]
    assert stats_high["retention_rate"] <= stats_low["retention_rate"]
    assert 0.0 <= stats_low["retention_rate"] <= 1.0
    assert 0.0 <= stats_high["retention_rate"] <= 1.0
