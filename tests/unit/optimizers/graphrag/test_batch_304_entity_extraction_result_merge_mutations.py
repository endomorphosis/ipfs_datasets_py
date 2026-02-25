from __future__ import annotations

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    Relationship,
)


def _entity(entity_id: str, text: str) -> Entity:
    return Entity(id=entity_id, text=text, type="Thing", confidence=0.8)


def _rel(rel_id: str, src: str, tgt: str) -> Relationship:
    return Relationship(id=rel_id, source_id=src, target_id=tgt, type="related_to", confidence=0.7)


def test_merge_deduplicates_entities_within_other_by_casefolded_text() -> None:
    left = EntityExtractionResult(
        entities=[_entity("e1", "Alpha")],
        relationships=[],
        confidence=0.8,
    )
    right = EntityExtractionResult(
        entities=[_entity("e2", "beta"), _entity("e3", "BETA")],
        relationships=[],
        confidence=0.6,
    )

    merged = left.merge(right)

    assert [e.id for e in merged.entities] == ["e1", "e2"]


def test_merge_deduplicates_relationship_ids_within_other() -> None:
    left = EntityExtractionResult(
        entities=[_entity("e1", "Alpha"), _entity("e2", "Beta")],
        relationships=[_rel("r1", "e1", "e2")],
        confidence=0.9,
    )
    right = EntityExtractionResult(
        entities=[_entity("e3", "Gamma")],
        relationships=[
            _rel("r2", "e2", "e3"),
            _rel("r2", "e3", "e1"),
            _rel("r1", "e1", "e3"),
        ],
        confidence=0.5,
    )

    merged = left.merge(right)

    assert [r.id for r in merged.relationships] == ["r1", "r2"]


def test_merge_metadata_prefers_self_on_key_collision() -> None:
    left = EntityExtractionResult(
        entities=[_entity("e1", "Alpha")],
        relationships=[],
        confidence=0.8,
        metadata={"owner": "left", "keep": True},
    )
    right = EntityExtractionResult(
        entities=[_entity("e2", "Beta")],
        relationships=[],
        confidence=0.6,
        metadata={"owner": "right", "other": 1},
    )

    merged = left.merge(right)

    assert merged.metadata["owner"] == "left"
    assert merged.metadata["keep"] is True
    assert merged.metadata["other"] == 1
