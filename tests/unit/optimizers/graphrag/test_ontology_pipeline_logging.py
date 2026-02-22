"""Tests for structured pipeline run logging."""
from __future__ import annotations

import json
import logging

from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline


def test_pipeline_run_emits_json_log(caplog):
    """Pipeline run should emit structured JSON log payload."""
    pipeline = OntologyPipeline(domain="general", use_llm=False, max_rounds=1)
    logger_name = "ipfs_datasets_py.optimizers.graphrag.ontology_pipeline"

    with caplog.at_level(logging.INFO, logger=logger_name):
        result = pipeline.run("Alice works at Acme.", data_source="test", refine=False)

    json_logs = [
        record for record in caplog.records if "PIPELINE_RUN:" in record.message
    ]
    assert json_logs, "Expected at least one PIPELINE_RUN log entry"

    payload_str = json_logs[0].message.replace("PIPELINE_RUN: ", "")
    payload = json.loads(payload_str)

    assert payload["event"] == "ontology_pipeline_run"
    assert payload["domain"] == "general"
    assert payload["data_source"] == "test"
    assert payload["data_type"] == "text"
    assert payload["refine"] is False
    assert isinstance(payload["entity_count"], int)
    assert isinstance(payload["relationship_count"], int)
    assert payload["duration_ms"] >= 0.0
    if payload["score"] is not None:
        assert 0.0 <= payload["score"] <= 1.0

    assert result is not None
