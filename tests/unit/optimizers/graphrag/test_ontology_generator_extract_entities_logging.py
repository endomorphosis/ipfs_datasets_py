"""Tests for structured logging emitted by OntologyGenerator.extract_entities().

Note: In this repo's pytest logging configuration, INFO logs show up in captured
stderr but are not consistently available via caplog.records.
"""

from __future__ import annotations

import json
import logging
import re

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    ExtractionStrategy,
    OntologyGenerationContext,
    OntologyGenerator,
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
    assert payload["event"] == "extract_entities"
    assert payload["strategy"] == ExtractionStrategy.RULE_BASED.value
    assert payload["entity_count"] == len(result.entities)
    assert payload["relationship_count"] == len(result.relationships)
    assert isinstance(payload["confidence"], float)
