"""Tests for typed exception handling in knowledge-graph integration."""

from __future__ import annotations

from types import SimpleNamespace

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.kg_integration import (
    KnowledgeGraphIntegration,
)


def test_get_context_handles_entity_extraction_error() -> None:
    integration = KnowledgeGraphIntegration(
        kg=SimpleNamespace(),
        enable_entity_extraction=False,
        enable_theorem_augmentation=False,
    )

    class _FailingExtractor:
        def extract_entities(self, text):
            raise ValueError("bad entities")

        def extract_relationships(self, text):
            raise ValueError("bad relationships")

    integration.entity_extractor = _FailingExtractor()
    context = integration.get_context_for_extraction("Alice must pay Bob")

    assert context.entities == []
    assert context.relationships == []


def test_get_context_handles_ontology_and_theorem_errors() -> None:
    integration = KnowledgeGraphIntegration(
        kg=SimpleNamespace(),
        enable_entity_extraction=False,
        enable_theorem_augmentation=False,
    )
    integration.theorem_rag = SimpleNamespace(query_with_theorems=lambda *_a, **_k: (_ for _ in ()).throw(ValueError("bad theorem query")))
    integration._extract_ontology_constraints = lambda: (_ for _ in ()).throw(TypeError("bad ontology"))  # type: ignore[method-assign]

    context = integration.get_context_for_extraction("Alice must pay Bob")

    assert context.ontology == {}
    assert context.relevant_theorems == []


def test_load_ontology_handles_bad_schema_type() -> None:
    integration = KnowledgeGraphIntegration(
        kg=SimpleNamespace(metadata={}),
        enable_entity_extraction=False,
        enable_theorem_augmentation=False,
    )

    ok = integration.load_ontology({"entity_types": ["not-a-dict"]})

    assert ok is False


def test_query_kg_returns_empty_on_typed_query_error() -> None:
    integration = KnowledgeGraphIntegration(
        kg=SimpleNamespace(query=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("query fail"))),
        enable_entity_extraction=False,
        enable_theorem_augmentation=False,
    )

    assert integration.query_kg("x") == []
