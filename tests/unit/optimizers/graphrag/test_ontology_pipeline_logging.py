"""Tests for structured pipeline run logging."""

from __future__ import annotations

import json
import logging
import re

from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
from ipfs_datasets_py.optimizers.common.structured_logging import DEFAULT_SCHEMA_VERSION


def _extract_json_payloads(captured: str, marker: str) -> list[dict]:
    payloads: list[dict] = []
    for match in re.finditer(rf"{re.escape(marker)}\s*(\{{.*\}})", captured):
        try:
            payloads.append(json.loads(match.group(1)))
        except json.JSONDecodeError:
            continue
    return payloads


def _extract_json_payload(captured: str, marker: str) -> dict:
    payloads = _extract_json_payloads(captured, marker)
    assert payloads, f"Expected {marker} JSON payload in captured output"
    return payloads[0]


def _assert_canonical_log_fields(payload: dict) -> None:
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


def test_pipeline_run_emits_json_log(caplog, capsys):
    """Pipeline run should emit structured JSON log payload."""
    pipeline = OntologyPipeline(domain="general", use_llm=False, max_rounds=1)

    # Capture globally; scoping to a single logger can miss INFO logs depending
    # on handler configuration.
    with caplog.at_level(logging.INFO):
        result = pipeline.run("Alice works at Acme.", data_source="test", refine=False)

    captured = (caplog.text or "") + "\n" + capsys.readouterr().err
    payload = _extract_json_payload(captured, "PIPELINE_RUN:")
    _assert_canonical_log_fields(payload)

    assert payload["event"] == "ontology_pipeline_run"
    assert payload["level"] == "INFO"
    assert payload["component"] == "ontology_pipeline"
    assert payload["optimizer_type"] == "graphrag"
    assert payload["optimizer_pipeline"] == "graphrag"
    assert payload["schema"] == "ipfs_datasets_py.optimizer_log"
    assert payload["schema_version"] == DEFAULT_SCHEMA_VERSION
    assert payload["domain"] == "general"
    assert payload["data_source"] == "test"
    assert payload["data_type"] == "text"
    assert payload["refine"] is False
    assert isinstance(payload["entity_count"], int)
    assert isinstance(payload["relationship_count"], int)
    assert payload["duration_ms"] >= 0.0
    assert isinstance(payload.get("stage_durations_ms"), dict)
    assert "extracting" in payload["stage_durations_ms"]
    assert "evaluating" in payload["stage_durations_ms"]
    if payload["score"] is not None:
        assert 0.0 <= payload["score"] <= 1.0

    assert result is not None


def test_pipeline_run_emits_start_json_log(caplog, capsys):
    """Pipeline run should emit structured JSON start payload."""
    pipeline = OntologyPipeline(domain="general", use_llm=False, max_rounds=1)

    with caplog.at_level(logging.INFO):
        pipeline.run("Alice works at Acme.", data_source="test", refine=False)

    captured = (caplog.text or "") + "\n" + capsys.readouterr().err
    payload = _extract_json_payload(captured, "PIPELINE_RUN_START:")
    _assert_canonical_log_fields(payload)

    assert payload["event"] == "ontology_pipeline_run_start"
    assert payload["level"] == "INFO"
    assert payload["component"] == "ontology_pipeline"
    assert payload["optimizer_type"] == "graphrag"
    assert payload["optimizer_pipeline"] == "graphrag"
    assert payload["schema"] == "ipfs_datasets_py.optimizer_log"
    assert payload["schema_version"] == DEFAULT_SCHEMA_VERSION
    assert payload["domain"] == "general"
    assert payload["data_source"] == "test"
    assert payload["data_type"] == "text"
    assert payload["refine"] is False
    assert payload["status"] == "started"


def test_pipeline_run_failure_emits_json_log(caplog, capsys, monkeypatch):
    """Pipeline run failure should emit structured JSON failure payload."""
    pipeline = OntologyPipeline(domain="general", use_llm=False, max_rounds=1)

    def _boom(*args, **kwargs):
        raise RuntimeError("forced extraction failure")

    monkeypatch.setattr(pipeline._generator, "extract_entities", _boom)

    with caplog.at_level(logging.INFO):
        try:
            pipeline.run("Alice works at Acme.", data_source="test", refine=False)
        except RuntimeError:
            pass
        else:  # pragma: no cover - defensive: expected RuntimeError path
            assert False, "Expected RuntimeError"

    captured = (caplog.text or "") + "\n" + capsys.readouterr().err
    payloads = _extract_json_payloads(captured, "PIPELINE_RUN:")
    payload = next((p for p in payloads if p.get("status") == "failure"), None)
    assert payload is not None
    _assert_canonical_log_fields(payload)

    assert payload["event"] == "ontology_pipeline_run"
    assert payload["level"] == "ERROR"
    assert payload["component"] == "ontology_pipeline"
    assert payload["optimizer_type"] == "graphrag"
    assert payload["optimizer_pipeline"] == "graphrag"
    assert payload["schema"] == "ipfs_datasets_py.optimizer_log"
    assert payload["schema_version"] == DEFAULT_SCHEMA_VERSION
    assert payload["domain"] == "general"
    assert payload["data_source"] == "test"
    assert payload["data_type"] == "text"
    assert payload["refine"] is False
    assert payload["status"] == "failure"
    assert payload["error_type"] == "RuntimeError"
    assert "forced extraction failure" in payload["error"]
    assert payload["duration_ms"] >= 0.0


def test_pipeline_batch_emits_json_log(caplog, capsys):
    """Pipeline batch run should emit structured JSON log payload."""
    pipeline = OntologyPipeline(domain="general", use_llm=False, max_rounds=1)

    docs = ["Alice works at Acme.", "Bob manages the NY office."]

    with caplog.at_level(logging.INFO):
        results = pipeline.run_batch(docs, data_source="batch", refine=False)

    captured = (caplog.text or "") + "\n" + capsys.readouterr().err

    payloads = _extract_json_payloads(captured, "PIPELINE_BATCH:")
    payload = next(
        (p for p in payloads if p.get("event") == "ontology_pipeline_batch" and "domain" in p),
        None,
    )
    assert payload is not None, "Expected at least one full PIPELINE_BATCH payload with domain"
    _assert_canonical_log_fields(payload)

    assert payload["event"] == "ontology_pipeline_batch"
    assert payload["level"] == "INFO"
    assert payload["component"] == "ontology_pipeline"
    assert payload["optimizer_type"] == "graphrag"
    assert payload["optimizer_pipeline"] == "graphrag"
    assert payload["schema"] == "ipfs_datasets_py.optimizer_log"
    assert payload["schema_version"] == DEFAULT_SCHEMA_VERSION
    assert payload["domain"] == "general"
    assert payload["data_source"] == "batch"
    assert payload["data_type"] == "text"
    assert payload["refine"] is False
    assert payload["doc_count"] == 2
    assert payload["duration_ms"] >= 0.0

    if payload["mean_score"] is not None:
        assert 0.0 <= payload["mean_score"] <= 1.0
    if payload["min_score"] is not None:
        assert 0.0 <= payload["min_score"] <= 1.0
    if payload["max_score"] is not None:
        assert 0.0 <= payload["max_score"] <= 1.0

    assert len(results) == 2


def test_pipeline_run_redacts_sensitive_data_source(caplog, capsys):
    """Pipeline run log should redact sensitive token-like values."""
    pipeline = OntologyPipeline(domain="general", use_llm=False, max_rounds=1)

    with caplog.at_level(logging.INFO):
        pipeline.run(
            "Alice works at Acme.",
            data_source="authorization=Bearer token1234567890",
            refine=False,
        )

    captured = (caplog.text or "") + "\n" + capsys.readouterr().err
    payload = _extract_json_payload(captured, "PIPELINE_RUN:")

    assert "token1234567890" not in payload["data_source"]
    assert "***REDACTED***" in payload["data_source"]
