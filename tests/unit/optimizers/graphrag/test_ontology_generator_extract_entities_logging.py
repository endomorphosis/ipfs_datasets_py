"""Tests for structured logging emitted by OntologyGenerator.extract_entities().

Note: In this repo's pytest logging configuration, INFO logs show up in captured
stderr but are not consistently available via caplog.records.
"""

from __future__ import annotations

import json
import logging
import re
from unittest.mock import patch

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    ExtractionStrategy,
    OntologyGenerationContext,
    OntologyGenerator,
    Relationship,
)


def test_extract_entities_emits_structured_json_log(capsys, caplog):
    caplog.set_level(logging.INFO)
    gen = OntologyGenerator()
    ctx = OntologyGenerationContext(
        data_source="test",
        data_type="text",
        domain="general",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
    )

    stub_result = EntityExtractionResult(
        entities=[
            Entity(id="e1", type="person", text="Alice", confidence=0.9),
            Entity(id="e2", type="person", text="Bob", confidence=0.8),
        ],
        relationships=[
            Relationship(
                id="r1",
                source_id="e1",
                target_id="e2",
                type="met",
                confidence=0.75,
            )
        ],
        confidence=0.82,
        metadata={},
        errors=[],
    )
    with patch.object(gen, "_extract_with_llm_fallback", return_value=stub_result):
        result = gen.extract_entities("Alice met Bob.", ctx)

    captured = capsys.readouterr()
    payload = None
    for record in caplog.records:
        message = record.getMessage()
        if "EXTRACT_ENTITIES: " in message:
            payload = json.loads(message.split("EXTRACT_ENTITIES: ", 1)[1])
            break

    if payload is None:
        matches = re.findall(r"EXTRACT_ENTITIES: (\{.*\})", captured.err)
        assert matches, "Expected an EXTRACT_ENTITIES JSON payload in logs"
        payload = json.loads(matches[-1])
    for key in (
        "timestamp",
        "level",
        "event",
        "module",
        "component",
        "optimizer_type",
        "run_id",
        "schema_version",
        "message",
    ):
        assert key in payload
    assert payload["event"] == "extract_entities"
    assert payload["level"] == "INFO"
    assert payload["component"] == "ontology_generator"
    assert payload["optimizer_type"] == "graphrag"
    assert payload["optimizer_pipeline"] == "graphrag"
    assert payload["strategy"] == ExtractionStrategy.RULE_BASED.value
    assert payload["entity_count"] == len(result.entities)
    assert payload["relationship_count"] == len(result.relationships)
    assert isinstance(payload["confidence"], float)
