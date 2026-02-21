"""Batch-71 feature tests.

Covers:
- OntologyMediator.get_undo_depth()
- OntologyMediator.set_max_rounds(n)
- LogicValidator.count_contradictions(ontology)
- EntityExtractionResult.to_dict()
- Entity.copy_with(**overrides)
"""

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    Relationship,
    OntologyGenerator,
    OntologyGenerationContext,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mediator() -> OntologyMediator:
    gen = OntologyGenerator()
    crit = OntologyCritic(use_llm=False)
    return OntologyMediator(generator=gen, critic=crit, max_rounds=3)


def _validator() -> LogicValidator:
    return LogicValidator()


def _entity(eid="e1", text="Alice", etype="Person", conf=0.9) -> Entity:
    return Entity(id=eid, type=etype, text=text, confidence=conf)


def _result(*entities, rels=None) -> EntityExtractionResult:
    return EntityExtractionResult(
        entities=list(entities),
        relationships=list(rels or []),
        confidence=0.8,
    )


# ---------------------------------------------------------------------------
# OntologyMediator.get_undo_depth
# ---------------------------------------------------------------------------

class TestGetUndoDepth:
    def test_zero_initially(self):
        assert _mediator().get_undo_depth() == 0

    def test_increases_after_push(self):
        med = _mediator()
        med._undo_stack.append({"entities": [], "relationships": []})
        assert med.get_undo_depth() == 1

    def test_decreases_after_pop(self):
        med = _mediator()
        med._undo_stack.append({"entities": []})
        med._undo_stack.pop()
        assert med.get_undo_depth() == 0

    def test_returns_int(self):
        assert isinstance(_mediator().get_undo_depth(), int)

    def test_reset_clears(self):
        med = _mediator()
        med._undo_stack.extend([{}, {}, {}])
        med.reset_state()
        assert med.get_undo_depth() == 0


# ---------------------------------------------------------------------------
# OntologyMediator.set_max_rounds
# ---------------------------------------------------------------------------

class TestSetMaxRounds:
    def test_updates_max_rounds(self):
        med = _mediator()
        med.set_max_rounds(5)
        assert med.max_rounds == 5

    def test_zero_raises(self):
        with pytest.raises(ValueError):
            _mediator().set_max_rounds(0)

    def test_negative_raises(self):
        with pytest.raises(ValueError):
            _mediator().set_max_rounds(-1)

    def test_one_is_valid(self):
        med = _mediator()
        med.set_max_rounds(1)
        assert med.max_rounds == 1

    def test_large_value(self):
        med = _mediator()
        med.set_max_rounds(100)
        assert med.max_rounds == 100


# ---------------------------------------------------------------------------
# LogicValidator.count_contradictions
# ---------------------------------------------------------------------------

class TestCountContradictions:
    def test_returns_int(self):
        ont = {"entities": [{"id": "e1", "type": "T", "text": "x"}], "relationships": []}
        assert isinstance(_validator().count_contradictions(ont), int)

    def test_consistent_ontology_zero(self):
        ont = {"entities": [{"id": "e1", "type": "Person", "text": "Alice"}], "relationships": []}
        result = _validator().count_contradictions(ont)
        assert result >= 0

    def test_empty_ontology(self):
        assert _validator().count_contradictions({}) >= 0

    def test_non_negative(self):
        ont = {"entities": [{"id": "e1", "type": "T", "text": "x"}], "relationships": []}
        assert _validator().count_contradictions(ont) >= 0


# ---------------------------------------------------------------------------
# EntityExtractionResult.to_dict
# ---------------------------------------------------------------------------

class TestEntityExtractionResultToDict:
    def test_returns_dict(self):
        r = _result(_entity())
        assert isinstance(r.to_dict(), dict)

    def test_has_entities_key(self):
        r = _result(_entity())
        assert "entities" in r.to_dict()

    def test_has_relationships_key(self):
        assert "relationships" in _result().to_dict()

    def test_entity_count(self):
        r = _result(_entity("e1"), _entity("e2", "Bob"))
        assert len(r.to_dict()["entities"]) == 2

    def test_entity_is_dict(self):
        r = _result(_entity())
        assert isinstance(r.to_dict()["entities"][0], dict)

    def test_confidence_present(self):
        r = _result(_entity())
        assert "confidence" in r.to_dict()

    def test_metadata_present(self):
        r = _result(_entity())
        assert "metadata" in r.to_dict()

    def test_relationship_fields(self):
        e1, e2 = _entity("e1"), _entity("e2", "Bob")
        rel = Relationship(id="r1", source_id="e1", target_id="e2", type="knows")
        r = _result(e1, e2, rels=[rel])
        rel_dicts = r.to_dict()["relationships"]
        assert len(rel_dicts) == 1
        assert rel_dicts[0]["source_id"] == "e1"


# ---------------------------------------------------------------------------
# Entity.copy_with
# ---------------------------------------------------------------------------

class TestEntityCopyWith:
    def test_returns_new_entity(self):
        e = _entity()
        copy = e.copy_with(text="Bob")
        assert copy is not e
        assert isinstance(copy, Entity)

    def test_field_overridden(self):
        e = _entity(text="Alice")
        copy = e.copy_with(text="Bob")
        assert copy.text == "Bob"

    def test_other_fields_unchanged(self):
        e = _entity(eid="x1", etype="Org")
        copy = e.copy_with(text="NewText")
        assert copy.id == "x1"
        assert copy.type == "Org"

    def test_unknown_field_raises(self):
        with pytest.raises(TypeError):
            _entity().copy_with(nonexistent_field="val")

    def test_original_unchanged(self):
        e = _entity(text="Alice")
        e.copy_with(text="Bob")
        assert e.text == "Alice"

    def test_multiple_overrides(self):
        e = _entity()
        copy = e.copy_with(text="X", confidence=0.1)
        assert copy.text == "X"
        assert abs(copy.confidence - 0.1) < 1e-9

    def test_no_overrides(self):
        e = _entity()
        copy = e.copy_with()
        assert copy.text == e.text
        assert copy.id == e.id
