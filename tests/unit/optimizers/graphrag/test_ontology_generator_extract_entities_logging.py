"""Tests for structured logging emitted by OntologyGenerator.extract_entities()."""

from __future__ import annotations

import json
import logging

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    ExtractionStrategy,
    OntologyGenerationContext,
    OntologyGenerator,
)


def test_extract_entities_emits_structured_json_log(caplog):
    gen = OntologyGenerator()
    ctx = OntologyGenerationContext(
        data_source="test",
        data_type="text",
        domain="general",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
    )

    with caplog.at_level(logging.INFO):
        result = gen.extract_entities("Alice met Bob.", ctx)

    messages = [record.getMessage() for record in caplog.records]
    structured = [m for m in messages if m.startswith("EXTRACT_ENTITIES: ")]
    assert structured, "Expected an EXTRACT_ENTITIES structured log line"

    payload = json.loads(structured[-1].split("EXTRACT_ENTITIES: ", 1)[1])
    assert payload["event"] == "extract_entities"
    assert payload["strategy"] == ExtractionStrategy.RULE_BASED.value
    assert payload["entity_count"] == len(result.entities)
    assert payload["relationship_count"] == len(result.relationships)
    assert isinstance(payload["confidence"], float)
