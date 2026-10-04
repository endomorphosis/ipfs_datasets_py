"""Batch-315 tests for result-level confidence decay."""

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    Relationship,
)


def _make_result(entities, relationships=None):
    return EntityExtractionResult(
        entities=list(entities),
        relationships=list(relationships or []),
        confidence=1.0,
        metadata={},
        errors=[],
    )


def test_apply_confidence_decay_reduces_stale_more_than_fresh():
    now = 1_700_000_000.0
    stale = Entity(
        id="e-stale",
        type="Person",
        text="Alice",
        confidence=0.9,
        last_seen=now - (60 * 86400),
    )
    fresh = Entity(
        id="e-fresh",
        type="Person",
        text="Bob",
        confidence=0.9,
        last_seen=now - (1 * 86400),
    )

    result = _make_result([stale, fresh])
    decayed = result.apply_confidence_decay(current_time=now, half_life_days=30.0)

    stale_after = next(e for e in decayed.entities if e.id == "e-stale")
    fresh_after = next(e for e in decayed.entities if e.id == "e-fresh")

    assert stale_after.confidence < fresh_after.confidence
    assert fresh_after.confidence < 0.9
    assert decayed.metadata.get("confidence_decay_applied") is True


def test_apply_confidence_decay_drop_below_prunes_entities_and_relationships():
    now = 1_700_000_000.0
    stale = Entity(
        id="e-old",
        type="Org",
        text="Old Org",
        confidence=0.2,
        last_seen=now - (365 * 86400),
    )
    fresh = Entity(
        id="e-new",
        type="Org",
        text="New Org",
        confidence=0.95,
        last_seen=now,
    )
    rel = Relationship(id="r1", source_id="e-old", target_id="e-new", type="linked_to")

    result = _make_result([stale, fresh], [rel])
    decayed = result.apply_confidence_decay(
        current_time=now,
        half_life_days=30.0,
        min_confidence=0.1,
        drop_below=0.3,
    )

    assert [e.id for e in decayed.entities] == ["e-new"]
    assert decayed.relationships == []
    assert decayed.metadata.get("confidence_decay_entities_before") == 2
    assert decayed.metadata.get("confidence_decay_entities_after") == 1


def test_apply_confidence_decay_keeps_entities_without_timestamp_unchanged():
    entity = Entity(id="e1", type="Thing", text="X", confidence=0.77, last_seen=None)
    result = _make_result([entity])

    decayed = result.apply_confidence_decay(current_time=1_700_000_000.0)

    assert decayed.entities[0].confidence == pytest.approx(0.77)


def test_apply_confidence_decay_rejects_non_positive_half_life():
    result = _make_result([Entity(id="e1", type="Thing", text="X", confidence=0.9)])

    with pytest.raises(ValueError, match="half_life_days"):
        result.apply_confidence_decay(half_life_days=0.0)
