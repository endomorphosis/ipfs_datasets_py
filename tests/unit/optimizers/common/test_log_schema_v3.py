"""Tests for JSON log schema v3 standardization."""

import json
import logging
from ipfs_datasets_py.optimizers.common.log_schema_v3 import (
    log_session_start,
    log_session_complete,
    log_session_failed,
    log_iteration_started,
    log_iteration_complete,
    log_generate_complete,
    log_critique_complete,
    log_validate_complete,
    log_convergence_detected,
    log_target_reached,
    log_cache_hit,
    log_error,
    SCHEMA_NAME,
    SCHEMA_VERSION,
)


def test_session_start_log_structure(caplog):
    """Verify session_start emits correct JSON schema."""
    logger = logging.getLogger("test")
    
    with caplog.at_level(logging.INFO):
        log_session_start(
            logger,
            session_id="sess-001",
            domain="graph",
            input_size=1000,
            config={"max_iterations": 5},
            component="TestOptimizer",
        )
    
    assert len(caplog.records) == 1
    log_data = json.loads(caplog.records[0].message)
    
    # Required fields
    assert log_data["schema"] == SCHEMA_NAME
    assert log_data["schema_version"] == SCHEMA_VERSION
    assert log_data["event"] == "session.started"
    assert log_data["optimizer_pipeline"] == "common"
    assert "timestamp" in log_data
    
    # Context fields
    assert log_data["session_id"] == "sess-001"
    assert log_data["domain"] == "graph"
    assert log_data["component"] == "TestOptimizer"
    
    # Optional fields
    assert log_data["input_size"] == 1000
    assert log_data["config"]["max_iterations"] == 5


def test_session_complete_log_structure(caplog):
    """Verify session_complete emits correct JSON schema."""
    logger = logging.getLogger("test")
    
    with caplog.at_level(logging.INFO):
        log_session_complete(
            logger,
            session_id="sess-002",
            domain="logic",
            iterations=3,
            final_score=0.85,
            valid=True,
            execution_time_ms=1234.5,
            metrics={"improvement": 0.25},
        )
    
    log_data = json.loads(caplog.records[0].message)
    
    assert log_data["event"] == "session.completed"
    assert log_data["session_id"] == "sess-002"
    assert log_data["iterations"] == 3
    assert log_data["final_score"] == 0.85
    assert log_data["valid"] is True
    assert log_data["execution_time_ms"] == 1234.5
    assert log_data["metrics"]["improvement"] == 0.25


def test_iteration_complete_log_structure(caplog):
    """Verify iteration_complete emits correct JSON schema."""
    logger = logging.getLogger("test")
    
    with caplog.at_level(logging.INFO):
        log_iteration_complete(
            logger,
            session_id="sess-003",
            iteration=2,
            score=0.75,
            score_delta=0.05,
            execution_time_ms=500.0,
            component="Optimizer",
        )
    
    log_data = json.loads(caplog.records[0].message)
    
    assert log_data["event"] == "iteration.completed"
    assert log_data["iteration"] == 2
    assert log_data["score"] == 0.75
    assert log_data["score_delta"] == 0.05
    assert log_data["execution_time_ms"] == 500.0


def test_error_log_structure(caplog):
    """Verify error logs have correct classification."""
    logger = logging.getLogger("test")
    
    with caplog.at_level(logging.WARNING):
        log_error(
            logger,
            error_type="timeout",
            error_msg="Request timed out after 30s",
            session_id="sess-004",
            iteration=1,
            retryable=True,
            component="Generator",
        )
    
    log_data = json.loads(caplog.records[0].message)
    
    assert log_data["event"] == "error.retryable"  # Because retryable=True
    assert log_data["error_type"] == "timeout"
    assert log_data["error_msg"] == "Request timed out after 30s"
    assert log_data["session_id"] == "sess-004"
    assert log_data["iteration"] == 1


def test_error_log_redacts_sensitive_key_fields(caplog):
    """Sensitive key fields should be redacted in schema-v3 logs."""
    logger = logging.getLogger("test")

    with caplog.at_level(logging.WARNING):
        log_error(
            logger,
            error_type="auth",
            error_msg="api_key=sk-live-123",
            session_id="sess-redact",
            retryable=True,
        )

    log_data = json.loads(caplog.records[0].message)
    assert log_data["error_msg"] == "api_key=***REDACTED***"


def test_error_log_redacts_bearer_token_substrings(caplog):
    """Bearer-token substrings should be redacted in schema-v3 logs."""
    logger = logging.getLogger("test")

    with caplog.at_level(logging.WARNING):
        log_error(
            logger,
            error_type="auth",
            error_msg="Authorization: Bearer token1234567890",
            session_id="sess-redact-2",
            retryable=True,
        )

    log_data = json.loads(caplog.records[0].message)
    assert "token1234567890" not in log_data["error_msg"]
    assert "***REDACTED***" in log_data["error_msg"]


def test_convergence_detected_log(caplog):
    """Verify convergence detection logs."""
    logger = logging.getLogger("test")
    
    with caplog.at_level(logging.INFO):
        log_convergence_detected(
            logger,
            session_id="sess-005",
            iteration=3,
            score=0.90,
            score_delta=0.005,
            threshold=0.01,
        )
    
    log_data = json.loads(caplog.records[0].message)
    
    assert log_data["event"] == "convergence.detected"
    assert log_data["score_delta"] == 0.005
    assert log_data["threshold"] == 0.01


def test_cache_hit_log(caplog):
    """Verify cache hit logs."""
    logger = logging.getLogger("test")
    
    with caplog.at_level(logging.DEBUG):
        log_cache_hit(
            logger,
            cache_key="abc123def456ghi789",  # Long key
            hit_rate=0.75,
            component="Cache",
        )
    
    log_data = json.loads(caplog.records[0].message)
    
    assert log_data["event"] == "cache.hit"
    assert log_data["cache_key"] == "abc123def456"  # Truncated to 12 chars
    assert log_data["hit_rate"] == 0.75


def test_timestamp_is_unix_epoch(caplog):
    """Verify timestamp is Unix epoch (not ISO string)."""
    import time
    logger = logging.getLogger("test")
    
    before = time.time()
    
    with caplog.at_level(logging.INFO):
        log_session_start(logger, session_id="test", domain="test")
    
    after = time.time()
    
    log_data = json.loads(caplog.records[0].message)
    timestamp = log_data["timestamp"]
    
    # Timestamp should be float in Unix epoch range
    assert isinstance(timestamp, float)
    assert before <= timestamp <= after


def test_json_serialization_fallback(caplog):
    """Verify graceful fallback when JSON serialization fails."""
    logger = logging.getLogger("test")
    
    # Create unserializable object
    class Unserializable:
        pass
    
    with caplog.at_level(logging.DEBUG):
        log_session_start(
            logger,
            session_id="test",
            domain="test",
            config={"obj": Unserializable()},  # Will use default=str fallback
        )
    
    # Should still produce valid JSON (via default=str)
    log_data = json.loads(caplog.records[0].message)
    assert "config" in log_data
    # Object should be converted to string representation
    assert "Unserializable" in str(log_data["config"]["obj"])


def test_optional_fields_omitted_when_none(caplog):
    """Verify None fields are omitted from logs."""
    logger = logging.getLogger("test")
    
    with caplog.at_level(logging.INFO):
        log_session_start(
            logger,
            session_id="test",
            domain="test",
            input_size=None,  # Should be omitted
            config=None,  # Should be omitted
        )
    
    log_data = json.loads(caplog.records[0].message)
    
    assert "input_size" not in log_data
    assert "config" not in log_data


def test_validate_complete_log_level_varies_by_result(caplog):
    """Verify validation logs use WARNING for failures, INFO for success."""
    logger = logging.getLogger("test")
    
    # Test validation passing
    with caplog.at_level(logging.INFO):
        log_validate_complete(logger, session_id="test", valid=True)
    
    assert caplog.records[0].levelname == "INFO"
    caplog.clear()
    
    # Test validation failing
    with caplog.at_level(logging.WARNING):
        log_validate_complete(logger, session_id="test", valid=False, validation_details="Missing entities")
    
    assert caplog.records[0].levelname == "WARNING"
    log_data = json.loads(caplog.records[0].message)
    assert log_data["validation_details"] == "Missing entities"


def test_all_events_have_required_fields(caplog):
    """Verify all log functions produce logs with required schema fields."""
    logger = logging.getLogger("test")
    required_fields = {"schema", "schema_version", "event", "optimizer_pipeline", "timestamp"}
    
    log_functions = [
        (log_session_start, {"session_id": "t", "domain": "test"}),
        (log_session_complete, {"session_id": "t", "domain": "test", "iterations": 1, "final_score": 0.5, "valid": True, "execution_time_ms": 100}),
        (log_iteration_started, {"session_id": "t", "iteration": 1, "current_score": 0.5, "feedback_count": 1}),
        (log_iteration_complete, {"session_id": "t", "iteration": 1, "score": 0.5, "score_delta": 0.1, "execution_time_ms": 100}),
        (log_generate_complete, {"session_id": "t"}),
        (log_critique_complete, {"session_id": "t", "score": 0.5, "feedback_count": 1}),
        (log_validate_complete, {"session_id": "t", "valid": True}),
        (log_convergence_detected, {"session_id": "t", "iteration": 1, "score": 0.5, "score_delta": 0.01, "threshold": 0.01}),
        (log_target_reached, {"session_id": "t", "iteration": 1, "score": 0.9, "target": 0.85}),
        (log_cache_hit, {"cache_key": "abc"}),
        (log_error, {"error_type": "test", "error_msg": "test"}),
    ]
    
    for log_func, kwargs in log_functions:
        caplog.clear()
        with caplog.at_level(logging.DEBUG):
            log_func(logger, **kwargs)
        
        log_data = json.loads(caplog.records[0].message)
        assert required_fields.issubset(log_data.keys()), f"{log_func.__name__} missing required fields"
