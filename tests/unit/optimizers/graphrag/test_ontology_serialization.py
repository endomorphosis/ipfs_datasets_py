"""Tests for graphrag.ontology_serialization helpers."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    Relationship,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_serialization import (
    build_ontology_dict,
    entity_dict_to_model,
    entity_model_to_dict,
    models_from_ontology_dict,
    ontology_from_extraction_result,
    relationship_dict_to_model,
    relationship_model_to_dict,
)


def test_entity_model_to_dict_emits_canonical_keys_only() -> None:
    entity = Entity(
        id="e1",
        type="Person",
        text="Alice",
        confidence=0.9,
        properties={"role": "buyer"},
        source_span=(10, 15),
        last_seen=123.0,
    )

    data = entity_model_to_dict(entity)

    assert set(data.keys()) == {"id", "text", "type", "confidence", "properties"}
    assert data["id"] == "e1"
    assert data["properties"] == {"role": "buyer"}


def test_relationship_model_to_dict_emits_canonical_keys_only() -> None:
    rel = Relationship(
        id="r1",
        source_id="e1",
        target_id="e2",
        type="obligates",
        confidence=0.8,
        properties={"type_confidence": 0.85},
        direction="subject_to_object",
    )

    data = relationship_model_to_dict(rel)

    assert set(data.keys()) == {
        "id",
        "source_id",
        "target_id",
        "type",
        "confidence",
        "properties",
    }
    assert data["properties"]["type_confidence"] == 0.85
    assert "direction" not in data


def test_entity_dict_to_model_roundtrip_preserves_public_fields() -> None:
    original = {
        "id": "e1",
        "type": "Person",
        "text": "Alice",
        "confidence": 0.9,
        "properties": {"k": "v"},
    }

    model = entity_dict_to_model(original)
    rebuilt = entity_model_to_dict(model)

    assert rebuilt == original


def test_relationship_dict_to_model_roundtrip_preserves_public_fields() -> None:
    original = {
        "id": "r1",
        "source_id": "e1",
        "target_id": "e2",
        "type": "related_to",
        "confidence": 0.7,
        "properties": {"p": 1},
    }

    model = relationship_dict_to_model(original)
    rebuilt = relationship_model_to_dict(model)

    assert rebuilt == original


def test_ontology_from_extraction_result_includes_relationship_properties() -> None:
    extraction = EntityExtractionResult(
        entities=[
            Entity(id="e1", type="Person", text="Alice", confidence=0.9, properties={}),
            Entity(id="e2", type="Person", text="Bob", confidence=0.9, properties={}),
        ],
        relationships=[
            Relationship(
                id="r1",
                source_id="e1",
                target_id="e2",
                type="obligates",
                confidence=0.8,
                properties={"type_confidence": 0.85},
                direction="subject_to_object",
            )
        ],
        confidence=0.88,
        metadata={},
        errors=[],
    )

    ontology = ontology_from_extraction_result(extraction)

    assert ontology["relationships"][0]["properties"]["type_confidence"] == 0.85
    assert "direction" not in ontology["relationships"][0]


def test_models_from_ontology_dict_rehydrates_models() -> None:
    ontology = build_ontology_dict(
        entities=[Entity(id="e1", type="Thing", text="X", confidence=0.5, properties={})],
        relationships=[],
    )

    entities, relationships = models_from_ontology_dict(ontology)

    assert len(entities) == 1
    assert entities[0].id == "e1"
    assert relationships == []
