"""Unit tests for EntityExtractionResult.validate().

This focuses on structural invariants like dangling relationships, duplicate IDs,
empty text, and confidence bounds.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parents[4]))

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    Relationship,
)


def _entity(eid: str, text: str = "Alice", etype: str = "PERSON", conf: float = 0.9) -> Entity:
    return Entity(id=eid, type=etype, text=text, confidence=conf)


def _rel(rid: str, src: str, tgt: str, rtype: str = "RELATED", conf: float = 0.8) -> Relationship:
    return Relationship(id=rid, source_id=src, target_id=tgt, type=rtype, confidence=conf)


class TestEntityExtractionResultValidate:
    def test_validate_ok(self) -> None:
        e1 = _entity("e1", "Alice")
        e2 = _entity("e2", "Bob")
        r1 = _rel("r1", "e1", "e2")
        result = EntityExtractionResult(entities=[e1, e2], relationships=[r1], confidence=1.0)

        assert result.validate() == []

    def test_validate_duplicate_entity_ids(self) -> None:
        e1 = _entity("e1", "Alice")
        e1b = _entity("e1", "Alice 2")
        result = EntityExtractionResult(entities=[e1, e1b], relationships=[], confidence=1.0)

        errors = result.validate()
        assert any("Duplicate entity id" in e for e in errors)

    def test_validate_empty_entity_text(self) -> None:
        e1 = _entity("e1", "   ")
        result = EntityExtractionResult(entities=[e1], relationships=[], confidence=1.0)

        errors = result.validate()
        assert any("Empty entity text" in e for e in errors)

    def test_validate_entity_confidence_out_of_range(self) -> None:
        e1 = _entity("e1", "Alice", conf=1.5)
        result = EntityExtractionResult(entities=[e1], relationships=[], confidence=1.0)

        errors = result.validate()
        assert any("Entity confidence out of range" in e for e in errors)

    def test_validate_dangling_relationship(self) -> None:
        e1 = _entity("e1", "Alice")
        r1 = _rel("r1", "e1", "missing")
        result = EntityExtractionResult(entities=[e1], relationships=[r1], confidence=1.0)

        errors = result.validate()
        assert any("references missing target entity" in e for e in errors)

    def test_validate_self_loop_relationship(self) -> None:
        e1 = _entity("e1", "Alice")
        r1 = _rel("r1", "e1", "e1")
        result = EntityExtractionResult(entities=[e1], relationships=[r1], confidence=1.0)

        errors = result.validate()
        assert any("Self-loop relationship" in e for e in errors)
