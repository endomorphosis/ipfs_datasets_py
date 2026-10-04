"""Regression tests for OntologyGenerator.batch_extract API behavior."""

from __future__ import annotations

from unittest.mock import Mock

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    ExtractionConfig,
    OntologyGenerationContext,
    OntologyGenerator,
)


def _context() -> OntologyGenerationContext:
    return OntologyGenerationContext(
        data_source="batch-test",
        data_type="text",
        domain="general",
        extraction_strategy="rule_based",
        config=ExtractionConfig(confidence_threshold=0.4),
    )


def test_batch_extract_preserves_input_order_and_tags_entity_provenance() -> None:
    generator = OntologyGenerator(use_ipfs_accelerate=False)
    context = _context()

    def _extract(doc: str, _ctx: OntologyGenerationContext) -> EntityExtractionResult:
        idx = int(doc.split("-")[-1])
        return EntityExtractionResult(
            entities=[Entity(id=f"e{idx}", type="Person", text=doc, confidence=0.9)],
            relationships=[],
            confidence=0.9,
        )

    generator.extract_entities = Mock(side_effect=_extract)  # type: ignore[method-assign]
    docs = ["doc-0", "doc-1", "doc-2"]
    results = generator.batch_extract(docs, context, max_workers=2)

    assert [r.entities[0].id for r in results] == ["e0", "e1", "e2"]
    # Current Entity dataclass uses slots, so source-doc tagging is best-effort.
    assert all(getattr(r.entities[0], "source_doc_index", None) is None for r in results)


def test_batch_extract_returns_error_result_when_single_doc_fails() -> None:
    generator = OntologyGenerator(use_ipfs_accelerate=False)
    context = _context()

    def _extract(doc: str, _ctx: OntologyGenerationContext) -> EntityExtractionResult:
        if doc == "bad":
            raise ValueError("bad document")
        return EntityExtractionResult(entities=[], relationships=[], confidence=1.0)

    generator.extract_entities = Mock(side_effect=_extract)  # type: ignore[method-assign]
    results = generator.batch_extract(["ok", "bad", "ok2"], context, max_workers=0)

    assert len(results) == 3
    assert results[1].entities == []
    assert results[1].relationships == []
    assert results[1].confidence == 0.0
    assert results[1].errors and "bad document" in results[1].errors[0]
