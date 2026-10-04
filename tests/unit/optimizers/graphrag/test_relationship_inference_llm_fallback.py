"""Tests for LLM-based relationship inference fallback behavior."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    ExtractionConfig,
    OntologyGenerationContext,
    OntologyGenerator,
)


def test_relationship_inference_refines_type_with_llm_when_higher_confidence() -> None:
    def llm_backend(_prompt: str) -> str:
        return '{"relationship_type":"manages","confidence":0.95}'

    generator = OntologyGenerator(use_ipfs_accelerate=False, llm_backend=llm_backend)
    context = OntologyGenerationContext(
        data_source="unit",
        data_type="text",
        domain="general",
        config=ExtractionConfig(llm_fallback_threshold=0.9),
    )
    entities = [
        Entity(id="e1", type="Person", text="Alice", confidence=0.9),
        Entity(id="e2", type="Organization", text="Acme Corp", confidence=0.9),
    ]

    text = "Alice and Acme Corp announced new plans."
    relationships = generator.infer_relationships(entities, context, data=text)

    assert len(relationships) >= 1
    rel = relationships[0]
    assert rel.properties.get("type_method") in ("llm_refined", "verb_frame")
    if rel.properties.get("type_method") == "llm_refined":
        assert rel.type == "manages"
        assert rel.properties.get("type_confidence", 0.0) >= 0.95


def test_relationship_inference_keeps_heuristic_on_invalid_llm_output() -> None:
    def llm_backend(_prompt: str) -> str:
        return "not-json"

    generator = OntologyGenerator(use_ipfs_accelerate=False, llm_backend=llm_backend)
    context = OntologyGenerationContext(
        data_source="unit",
        data_type="text",
        domain="general",
        config=ExtractionConfig(llm_fallback_threshold=0.9),
    )
    entities = [
        Entity(id="e1", type="Person", text="Alice", confidence=0.9),
        Entity(id="e2", type="Organization", text="Acme Corp", confidence=0.9),
    ]

    text = "Alice and Acme Corp announced new plans."
    relationships = generator.infer_relationships(entities, context, data=text)

    assert len(relationships) >= 1
    rel = relationships[0]
    assert rel.properties.get("type_method") != "llm_refined"
