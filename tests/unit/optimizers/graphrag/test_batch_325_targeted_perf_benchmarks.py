"""Batch 325: Targeted performance benchmarks for remaining TODO items.

Covers:
- OntologyGenerator.extract_entities() on 10k-token documents
- LogicValidator.validate_ontology() on 100-entity ontologies
"""

import time

from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerationContext,
    OntologyGenerator,
)


def _build_linear_ontology(entity_count: int) -> dict:
    entities = [
        {"id": f"e{i}", "text": f"Entity {i}", "type": "Thing", "confidence": 0.9}
        for i in range(entity_count)
    ]
    relationships = [
        {
            "id": f"r{i}",
            "source_id": f"e{i}",
            "target_id": f"e{i + 1}",
            "type": "related_to",
            "confidence": 0.8,
        }
        for i in range(max(0, entity_count - 1))
    ]
    return {"entities": entities, "relationships": relationships}


def test_extract_entities_10k_tokens_benchmark():
    generator = OntologyGenerator(use_ipfs_accelerate=False)
    context = OntologyGenerationContext(
        data_source="benchmark-doc",
        data_type="text",
        domain="general",
        extraction_strategy="rule_based",
    )

    text = " ".join(["token"] * 10_000)

    start = time.perf_counter()
    result = generator.extract_entities(text, context)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert result is not None
    assert isinstance(result.entities, list)
    assert elapsed_ms < 20_000, f"extract_entities(10k) took {elapsed_ms:.0f}ms"


def test_validate_ontology_100_entities_benchmark():
    validator = LogicValidator(use_cache=False)
    validator._tdfol_available = False  # benchmark structural validator path deterministically

    ontology = _build_linear_ontology(100)

    start = time.perf_counter()
    result = validator.validate_ontology(ontology)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert result is not None
    assert isinstance(result.is_consistent, bool)
    assert elapsed_ms < 5_000, f"validate_ontology(100 entities) took {elapsed_ms:.0f}ms"
