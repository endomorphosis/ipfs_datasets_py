"""Tests for structured JSON logging in OntologyPipeline.run()."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    Relationship,
)


def _make_pipeline_with_mocks() -> OntologyPipeline:
    pipeline = OntologyPipeline(domain="legal", use_llm=False, max_rounds=1)

    extraction = EntityExtractionResult(
        entities=[Entity(id="e1", type="Person", text="Alice", confidence=0.9)],
        relationships=[
            Relationship(id="r1", source_id="e1", target_id="e1", type="self", confidence=0.5)
        ],
        confidence=0.8,
    )

    ontology = {
        "entities": [entity.to_dict() for entity in extraction.entities],
        "relationships": [relationship.to_dict() for relationship in extraction.relationships],
        "metadata": {},
    }
    refined = {
        "entities": ontology["entities"],
        "relationships": ontology["relationships"],
        "metadata": {"refinement_actions": ["normalize_entity_types"]},
    }

    pipeline._generator = Mock()
    pipeline._generator.extract_entities.return_value = extraction

    pipeline._critic = Mock()
    pipeline._critic.evaluate_ontology.return_value = SimpleNamespace(overall=0.82)

    pipeline._mediator = Mock()
    pipeline._mediator.refine_ontology.return_value = refined
    pipeline._mediator.max_rounds = 1

    pipeline._adapter = Mock()
    pipeline._adapter.get_extraction_hint.return_value = 0.5
    return pipeline


def test_pipeline_run_emits_structured_json_log(caplog) -> None:
    caplog.set_level(logging.INFO)
    pipeline = _make_pipeline_with_mocks()

    result = pipeline.run("Alice signed contract", data_source="unit-test", data_type="text", refine=True)
    assert result.score.overall == 0.82

    records = [r for r in caplog.records if "PIPELINE_RUN:" in r.message]
    assert len(records) == 1

    payload = json.loads(records[0].message.split("PIPELINE_RUN: ", 1)[1])
    assert payload["event"] == "ontology_pipeline_run"
    assert payload["domain"] == "legal"
    assert payload["data_source"] == "unit-test"
    assert payload["data_type"] == "text"
    assert payload["refine"] is True
    assert payload["entity_count"] == 1
    assert payload["relationship_count"] == 1
    assert payload["actions_count"] == 1
    assert "duration_ms" in payload
    assert "stage_durations_ms" in payload
    assert {"extracting", "evaluating", "refining"} <= set(payload["stage_durations_ms"].keys())


def test_pipeline_run_logging_failure_is_non_fatal(caplog) -> None:
    caplog.set_level(logging.DEBUG)
    pipeline = _make_pipeline_with_mocks()

    with patch(
        "ipfs_datasets_py.optimizers.common.structured_logging.with_schema",
        side_effect=RuntimeError("schema fail"),
    ):
        result = pipeline.run("Alice signed contract", data_source="unit-test", data_type="text", refine=False)

    assert result is not None
    debug_msgs = [r.message for r in caplog.records if r.levelname == "DEBUG"]
    assert any("Pipeline JSON logging failed" in msg for msg in debug_msgs)
