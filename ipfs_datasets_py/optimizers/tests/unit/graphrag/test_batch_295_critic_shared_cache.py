"""Regression coverage for shared ontology critic cache across instances."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    ExtractionConfig,
    OntologyGenerationContext,
)


def _context() -> OntologyGenerationContext:
    return OntologyGenerationContext(
        data_source="cache-test",
        data_type="text",
        domain="general",
        extraction_strategy="rule_based",
        config=ExtractionConfig(),
    )


def test_evaluate_ontology_uses_shared_cache_across_instances(monkeypatch) -> None:
    OntologyCritic.clear_shared_cache()

    ontology = {
        "entities": [
            {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.9},
            {"id": "e2", "text": "Acme", "type": "Organization", "confidence": 0.8},
        ],
        "relationships": [
            {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "works_at", "confidence": 0.7}
        ],
    }
    context = _context()

    first = OntologyCritic(use_llm=False)
    score1 = first.evaluate_ontology(ontology, context)
    assert score1 is not None
    assert OntologyCritic.shared_cache_size() >= 1

    second = OntologyCritic(use_llm=False)

    def _fail_if_called(*_args, **_kwargs):
        raise AssertionError("completeness evaluator should not run when shared cache hits")

    monkeypatch.setattr(second, "_evaluate_completeness", _fail_if_called)
    score2 = second.evaluate_ontology(ontology, context)

    assert score2.overall == score1.overall
    assert OntologyCritic.shared_cache_size() >= 1
