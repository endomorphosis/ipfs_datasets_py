"""Regression corpus tests for mixed-domain extraction invariants."""

from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    ExtractionConfig,
    ExtractionStrategy,
    OntologyGenerationContext,
    OntologyGenerator,
)


FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "graphrag"
    / "mixed_domain_corpus_invariants.json"
)


def _lower_set(values: list[str]) -> set[str]:
    return {v.lower() for v in values}


def test_mixed_domain_regression_corpus_invariants():
    """Mixed-domain corpus should satisfy frozen, domain-specific invariants."""
    payload = json.loads(FIXTURE_PATH.read_text())
    generator = OntologyGenerator(use_ipfs_accelerate=False)

    for case in payload["cases"]:
        context = OntologyGenerationContext(
            data_source=f"corpus:{case['id']}",
            data_type="text",
            domain=case["domain"],
            extraction_strategy=ExtractionStrategy.RULE_BASED,
            config=ExtractionConfig(
                confidence_threshold=0.0,
                llm_fallback_threshold=0.0,
            ),
        )
        result = generator.extract_entities(case["text"], context)

        entities = result.entities or []
        entity_texts = _lower_set([e.text for e in entities])
        entity_types = {e.type for e in entities}

        assert len(entities) >= int(case["min_entities"]), case["id"]
        assert len(result.relationships or []) >= 0, case["id"]
        assert result.confidence >= 0.0, case["id"]

        for expected_text in case["required_entity_texts"]:
            assert expected_text.lower() in entity_texts, (case["id"], expected_text)

        for expected_type in case["required_entity_types"]:
            assert expected_type in entity_types, (case["id"], expected_type)
