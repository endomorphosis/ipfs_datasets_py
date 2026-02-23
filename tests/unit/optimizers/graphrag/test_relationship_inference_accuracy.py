"""Accuracy tests for relationship inference heuristics.

Focuses on verb-frame matching and co-occurrence inference behavior.
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    OntologyGenerationContext,
    Entity,
    ExtractionStrategy,
    DataType,
)


@pytest.fixture
def generator() -> OntologyGenerator:
    return OntologyGenerator(use_ipfs_accelerate=False)


@pytest.fixture
def ctx() -> OntologyGenerationContext:
    return OntologyGenerationContext(
        data_source="test",
        data_type=DataType.TEXT,
        domain="general",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
    )


def _entity(eid: str, text: str, etype: str = "person") -> Entity:
    return Entity(id=eid, type=etype, text=text, confidence=0.8)


@pytest.mark.parametrize(
    "text,subject_text,object_text,expected_type",
    [
        ("Alice must pay Bob", "Alice", "Bob", "obligates"),
        ("Alice owns Bob", "Alice", "Bob", "owns"),
        ("Alice manages Bob", "Alice", "Bob", "manages"),
        ("Alice employs Bob", "Alice", "Bob", "employs"),
        ("Rain causes Flooding", "Rain", "Flooding", "causes"),
        ("Dog is a Animal", "Dog", "Animal", "is_a"),
        ("Wheel part of Car", "Wheel", "Car", "part_of"),
    ],
)
def test_verb_frame_patterns_infer_expected_types(
    generator: OntologyGenerator,
    ctx: OntologyGenerationContext,
    text: str,
    subject_text: str,
    object_text: str,
    expected_type: str,
) -> None:
    entities = [_entity("e1", subject_text), _entity("e2", object_text, "person")]
    rels = generator.infer_relationships(entities, ctx, text)
    rel_types = {r.type for r in rels}
    assert expected_type in rel_types


def test_verb_frame_relationship_includes_type_metadata(
    generator: OntologyGenerator,
    ctx: OntologyGenerationContext,
) -> None:
    entities = [_entity("e1", "Alice"), _entity("e2", "Bob", "person")]
    rels = generator.infer_relationships(entities, ctx, "Alice manages Bob")

    matches = [r for r in rels if r.type == "manages"]
    assert matches

    rel = matches[0]
    props = getattr(rel, "properties", {})
    assert props.get("type_method") == "verb_frame"
    assert props.get("type_confidence") == pytest.approx(0.80)


def test_person_org_cooccurrence_infers_works_for(
    generator: OntologyGenerator,
    ctx: OntologyGenerationContext,
) -> None:
    entities = [
        _entity("e1", "Alice", "person"),
        _entity("e2", "Acme", "organization"),
    ]
    text = "Alice joined Acme as an engineer."
    rels = generator.infer_relationships(entities, ctx, text)
    assert any(r.type in {"works_for", "related_to"} for r in rels)


def test_cooccurrence_relationship_includes_type_metadata(
    generator: OntologyGenerator,
    ctx: OntologyGenerationContext,
) -> None:
    entities = [
        _entity("e1", "Alice", "person"),
        _entity("e2", "Acme", "organization"),
    ]
    text = "Alice started at Acme last week."

    rels = generator.infer_relationships(entities, ctx, text)
    matches = [r for r in rels if r.type == "works_for"]
    assert matches

    props = getattr(matches[0], "properties", {})
    assert props.get("type_method") == "cooccurrence"
    assert props.get("type_confidence") == pytest.approx(0.65)


def test_person_location_cooccurrence_infers_located_in(
    generator: OntologyGenerator,
    ctx: OntologyGenerationContext,
) -> None:
    entities = [
        _entity("e1", "Alice", "person"),
        _entity("e2", "Paris", "location"),
    ]
    text = "Alice moved to Paris last year."
    rels = generator.infer_relationships(entities, ctx, text)
    assert any(r.type in {"located_in", "related_to"} for r in rels)


def test_entities_far_apart_not_linked(
    generator: OntologyGenerator,
    ctx: OntologyGenerationContext,
) -> None:
    entities = [_entity("e1", "Alpha"), _entity("e2", "Gamma")]
    text = "Alpha" + " " * 400 + "Gamma"
    rels = generator.infer_relationships(entities, ctx, text)
    # No co-occurrence relationship expected beyond 200-char window
    co_occ = [r for r in rels if r.type in {"related_to", "works_for", "located_in", "produces"}]
    assert co_occ == []


def test_no_self_links_created(
    generator: OntologyGenerator,
    ctx: OntologyGenerationContext,
) -> None:
    entities = [_entity("e1", "Alice")]
    text = "Alice must pay Alice"
    rels = generator.infer_relationships(entities, ctx, text)
    assert all(r.source_id != r.target_id for r in rels)
