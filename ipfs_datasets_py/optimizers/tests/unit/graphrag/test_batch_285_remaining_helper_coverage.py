"""Coverage for remaining GraphRAG helper methods tracked in TODO."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    ExtractionConfig,
    OntologyGenerator,
    Relationship,
)


def _result() -> EntityExtractionResult:
    return EntityExtractionResult(
        entities=[
            Entity(id="e1", type="Person", text="Alice", confidence=0.9, properties={"role": "engineer"}),
            Entity(id="e2", type="Person", text="Bob", confidence=0.4),
            Entity(id="e3", type="Company", text="Acme", confidence=0.7, properties={"hq": "NY"}),
        ],
        relationships=[
            Relationship(id="r1", source_id="e1", target_id="e2", type="knows", confidence=0.8),
            Relationship(id="r2", source_id="e1", target_id="e3", type="works_for", confidence=0.9),
        ],
        confidence=0.67,
    )


def test_extraction_config_relaxed_and_tightened_clamp_threshold() -> None:
    assert ExtractionConfig(confidence_threshold=0.05).relaxed(delta=0.2).confidence_threshold == 0.0
    assert ExtractionConfig(confidence_threshold=0.95).tightened(delta=0.2).confidence_threshold == 1.0


def test_entity_result_top_confidence_properties_and_entity_ids() -> None:
    result = _result()

    assert result.top_confidence_entity() is not None
    assert result.top_confidence_entity().id == "e1"
    assert [e.id for e in result.entities_with_properties()] == ["e1", "e3"]
    assert result.entity_ids == ["e1", "e2", "e3"]

    empty = EntityExtractionResult(entities=[], relationships=[], confidence=0.0)
    assert empty.top_confidence_entity() is None


def test_generator_relationship_count_confidence_map_and_filter() -> None:
    gen = OntologyGenerator(use_ipfs_accelerate=False)
    result = _result()

    assert gen.relationship_count(result) == 2
    assert gen.entity_confidence_map(result) == {"e1": 0.9, "e2": 0.4, "e3": 0.7}

    filtered = gen.filter_low_confidence(result, threshold=0.7)
    assert [e.id for e in filtered.entities] == ["e1", "e3"]


def test_logic_validator_orphan_and_hub_entities() -> None:
    validator = LogicValidator(use_cache=False)
    ontology = {
        "entities": [
            {"id": "e1", "type": "Person"},
            {"id": "e2", "type": "Person"},
            {"id": "e3", "type": "Company"},
            {"id": "e4", "type": "Place"},
        ],
        "relationships": [
            {"source_id": "e1", "target_id": "e2", "type": "knows"},
            {"source_id": "e1", "target_id": "e3", "type": "works_for"},
        ],
    }

    assert validator.orphan_entities(ontology) == ["e4"]
    assert validator.hub_entities(ontology, min_degree=2) == ["e1"]
    assert validator.hub_entities(ontology, min_degree=1) == ["e1", "e2", "e3"]
