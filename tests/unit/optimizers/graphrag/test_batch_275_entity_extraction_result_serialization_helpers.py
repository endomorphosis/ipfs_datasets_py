"""Tests for EntityExtractionResult serialization and count helpers."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    Relationship,
)


def _sample_result() -> EntityExtractionResult:
    return EntityExtractionResult(
        entities=[
            Entity(id="e1", type="Person", text="Alice", confidence=0.9),
            Entity(id="e2", type="Organization", text="Acme", confidence=0.8),
        ],
        relationships=[
            Relationship(
                id="r1",
                source_id="e1",
                target_id="e2",
                type="worksFor",
                confidence=0.75,
            )
        ],
        confidence=0.85,
        metadata={"source": "unit"},
        errors=["none"],
    )


def test_entity_extraction_result_to_dict_from_dict_roundtrip() -> None:
    original = _sample_result()

    payload = original.to_dict()
    restored = EntityExtractionResult.from_dict(payload)

    assert restored.entity_count == 2
    assert restored.relationship_count == 1
    assert restored.entities[0].id == "e1"
    assert restored.relationships[0].source_id == "e1"
    assert restored.metadata == {"source": "unit"}
    assert restored.errors == ["none"]


def test_entity_extraction_result_empty_and_relationship_flags() -> None:
    empty = EntityExtractionResult(entities=[], relationships=[], confidence=0.0)
    assert empty.is_empty() is True
    assert empty.has_relationships() is False

    non_empty = _sample_result()
    assert non_empty.is_empty() is False
    assert non_empty.has_relationships() is True
