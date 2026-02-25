"""Batch 303: Contract tests for graphrag.ontology_types TypedDict API.

Validates that key TypedDicts are exported and preserve expected required/
optional key contracts for stable static typing.
"""

from __future__ import annotations

from ipfs_datasets_py.optimizers.graphrag import ontology_types


def test_ontology_types_exports_include_core_typeddicts() -> None:
    expected = {
        "Entity",
        "Relationship",
        "Ontology",
        "CriticScore",
        "OntologySession",
        "ExtractionConfigDict",
        "OptimizerConfig",
    }

    exported = set(getattr(ontology_types, "__all__", []))
    missing = expected - exported
    assert not missing, f"Missing exports in ontology_types.__all__: {sorted(missing)}"


def test_entity_typeddict_required_and_optional_keys() -> None:
    entity = ontology_types.Entity

    assert entity.__required_keys__ == {"id", "text", "type", "confidence"}
    assert {"properties", "context", "source_span"}.issubset(entity.__optional_keys__)


def test_relationship_typeddict_required_and_optional_keys() -> None:
    relationship = ontology_types.Relationship

    assert relationship.__required_keys__ == {
        "id",
        "source_id",
        "target_id",
        "type",
        "confidence",
    }
    assert {"properties", "context", "distance"}.issubset(relationship.__optional_keys__)


def test_ontology_typeddict_shape_contract() -> None:
    ontology = ontology_types.Ontology

    assert {"entities", "relationships"}.issubset(ontology.__required_keys__)
    assert {"metadata", "statistics"}.issubset(ontology.__optional_keys__)


def test_critic_score_typeddict_shape_contract() -> None:
    critic_score = ontology_types.CriticScore

    assert critic_score.__required_keys__ == {"overall"}
    assert {
        "completeness",
        "consistency",
        "clarity",
        "granularity",
        "domain_alignment",
        "relationship_coherence",
        "recommendations",
    }.issubset(critic_score.__optional_keys__)
