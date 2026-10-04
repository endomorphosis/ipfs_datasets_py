"""Audit tests for structured JSON logging contract across optimizer pipelines."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from unittest.mock import patch

from ipfs_datasets_py.optimizers.common.profiling import ProfilingConfig, profile_section
from ipfs_datasets_py.optimizers.common.structured_logging import (
    DEFAULT_SCHEMA,
    DEFAULT_SCHEMA_VERSION,
    EventType,
    log_event,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
from ipfs_datasets_py.optimizers.graphrag.pipeline_json_logger import PipelineJSONLogger
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_optimizer import LogicOptimizer
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.unified_optimizer import (
    LogicTheoremOptimizer,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_extractor import (
    ExtractionMode,
)
from ipfs_datasets_py.optimizers.common.base_optimizer import (
    OptimizerConfig,
    OptimizationContext,
)


def _find_record_payload(caplog, marker: str) -> dict:
    for record in caplog.records:
        message = record.getMessage()
        if marker == "json" and message.startswith("{"):
            return json.loads(message)
        if marker in message:
            return json.loads(message.split(marker, 1)[1].strip())
    raise AssertionError(f"No log payload found for marker: {marker}")


def _assert_common_schema_fields(payload: dict, expected_pipeline: str) -> None:
    assert payload["schema"] == DEFAULT_SCHEMA
    assert payload["schema_version"] == DEFAULT_SCHEMA_VERSION
    assert payload["optimizer_pipeline"] == expected_pipeline
    assert "timestamp" in payload


def _assert_canonical_fields(payload: dict) -> None:
    required = {
        "timestamp",
        "level",
        "message",
        "module",
        "component",
        "optimizer_type",
        "run_id",
        "status",
    }
    assert required.issubset(payload.keys())


def _find_payload_by_event(caplog, event_name: str) -> dict:
    for record in caplog.records:
        message = record.getMessage()
        if not message.startswith("{"):
            continue
        payload = json.loads(message)
        if payload.get("event") == event_name:
            return payload
    raise AssertionError(f"No payload found for event: {event_name}")


def test_common_log_event_emits_schema_contract(caplog) -> None:
    logger = logging.getLogger("test.structured.audit.common")
    caplog.set_level(logging.INFO, logger=logger.name)

    log_event(
        logger,
        EventType.EXTRACTION_STARTED,
        {
            "input_length": 10,
            "api_key": "sk-testsecret",
        },
        optimizer_pipeline="common",
    )

    payload = _find_record_payload(caplog, "json")
    _assert_common_schema_fields(payload, expected_pipeline="common")
    assert payload["event"] == EventType.EXTRACTION_STARTED.value
    assert payload["api_key"] == "***REDACTED***"


def test_profiling_logs_emit_schema_contract(caplog) -> None:
    profiling_logger = logging.getLogger("ipfs_datasets_py.optimizers.common.profiling")
    caplog.set_level(logging.INFO, logger=profiling_logger.name)

    with profile_section(
        "audit.profile",
        metadata={"auth_token": "Bearer abcdefghijklmnop"},
        config=ProfilingConfig(enabled=True, emit_logs=True, min_duration_ms=0.0),
    ):
        pass

    payload = _find_record_payload(caplog, "PROFILING: ")
    _assert_common_schema_fields(payload, expected_pipeline="common")
    assert payload["event"] == "profiling_result"
    assert payload["metadata"]["auth_token"] == "***REDACTED***"


def test_cross_pipeline_optimizer_logs_emit_schema_contract(caplog) -> None:
    graphrag_logger = logging.getLogger("test.structured.audit.graphrag")
    caplog.set_level(logging.INFO)

    graphrag_optimizer = OntologyOptimizer(logger=graphrag_logger, enable_tracing=False)
    graphrag_optimizer._emit_analyze_batch_summary(
        {
            "batch_size": 1,
            "token": "Bearer abcdefghijklmnop",
        }
    )

    logic_optimizer = LogicOptimizer()
    logic_optimizer.analyze_batch(
        [
            SimpleNamespace(
                critic_score=SimpleNamespace(
                    overall=0.75,
                    dimension_scores=[],
                    weaknesses=[],
                ),
                success=True,
            )
        ]
    )

    graphrag_payload = _find_record_payload(caplog, "json")
    _assert_common_schema_fields(graphrag_payload, expected_pipeline="graphrag")
    _assert_canonical_fields(graphrag_payload)
    assert graphrag_payload["event"] == "ontology_optimizer.analyze_batch.summary"
    assert graphrag_payload["token"] == "Bearer ***REDACTED***"

    logic_payload = _find_record_payload(caplog, "LOGIC_BATCH_ANALYSIS: ")
    _assert_common_schema_fields(logic_payload, expected_pipeline="logic_theorem")
    _assert_canonical_fields(logic_payload)
    assert logic_payload["event"] == "logic_optimizer_analyze_batch"


def test_logic_run_session_log_emits_schema_and_canonical_fields(caplog) -> None:
    caplog.set_level(logging.INFO)

    optimizer = LogicTheoremOptimizer(
        config=OptimizerConfig(max_iterations=1, target_score=0.5),
        extraction_mode=ExtractionMode.FOL,
        use_provers=["z3"],
    )
    context = OptimizationContext(
        session_id="audit-session-001",
        input_data="All humans are mortal. Socrates is human.",
        domain="general",
    )

    # Keep this audit fast/deterministic by avoiding full theorem pipeline execution.
    with patch(
        "ipfs_datasets_py.optimizers.common.base_optimizer.BaseOptimizer.run_session",
        return_value={
            "score": 0.81,
            "valid": True,
            "iterations": 1,
            "artifact": {"statements": ["P -> Q", "P", "Q"]},
            "metrics": {"feedback": []},
        },
    ):
        optimizer.run_session(
            input_data="All humans are mortal. Socrates is human.",
            context=context,
        )

    payload = _find_record_payload(caplog, "LOGIC_SESSION_RUN: ")
    _assert_common_schema_fields(payload, expected_pipeline="logic_theorem")
    _assert_canonical_fields(payload)
    assert payload["event"] == "logic_theorem_optimizer_run_session"
    assert payload["run_id"] == "audit-session-001"


def test_pipeline_json_logger_emits_schema_and_canonical_fields(caplog) -> None:
    logger = logging.getLogger("test.structured.audit.pipeline_json_logger")
    caplog.set_level(logging.INFO, logger=logger.name)

    pipeline_logger = PipelineJSONLogger(domain="audit", logger=logger)
    pipeline_logger.start_run(run_id="audit-run-001", data_source="unit")
    pipeline_logger.end_run(success=True)

    payload = _find_payload_by_event(caplog, "pipeline.run.started")
    _assert_common_schema_fields(payload, expected_pipeline="graphrag")
    _assert_canonical_fields(payload)
    assert payload["component"] == "pipeline_json_logger"
    assert payload["optimizer_type"] == "graphrag"
