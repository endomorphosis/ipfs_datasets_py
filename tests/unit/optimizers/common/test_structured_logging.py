"""Tests for structured logging helpers.

Validates EventType enum, with_schema, enrich_with_timestamp, and log_event function.
"""

import json
import logging
import time
from unittest.mock import MagicMock

import pytest

from ipfs_datasets_py.optimizers.common.structured_logging import (
    DEFAULT_SCHEMA,
    DEFAULT_SCHEMA_VERSION,
    EventType,
    enrich_with_timestamp,
    log_event,
    with_schema,
)


class TestWithSchema:
    """Tests for with_schema function."""
    
    def test_adds_schema_metadata(self):
        """GIVEN: Plain payload WITHOUT schema
        WHEN: with_schema called
        THEN: Returns payload with schema and schema_version
        """
        payload = {"event": "test", "data": 123}
        result = with_schema(payload)
        
        assert result["event"] == "test"
        assert result["data"] == 123
        assert result["schema"] == DEFAULT_SCHEMA
        assert result["schema_version"] == DEFAULT_SCHEMA_VERSION
    
    def test_preserves_existing_schema(self):
        """GIVEN: Payload WITH existing schema
        WHEN: with_schema called
        THEN: Existing schema is preserved
        """
        payload = {"event": "test", "schema": "custom.schema", "schema_version": 99}
        result = with_schema(payload)
        
        assert result["schema"] == "custom.schema"
        assert result["schema_version"] == 99
    
    def test_custom_schema(self):
        """GIVEN: Custom schema parameters
        WHEN: with_schema called with schema and schema_version
        THEN: Uses custom values
        """
        payload = {"event": "test"}
        result = with_schema(payload, schema="my.schema", schema_version=5)
        
        assert result["schema"] == "my.schema"
        assert result["schema_version"] == 5


class TestEnrichWithTimestamp:
    """Tests for enrich_with_timestamp function."""
    
    def test_adds_timestamp(self):
        """GIVEN: Payload without timestamp
        WHEN: enrich_with_timestamp called
        THEN: Adds current timestamp
        """
        before = time.time()
        payload = {"event": "test"}
        result = enrich_with_timestamp(payload)
        after = time.time()
        
        assert "timestamp" in result
        assert before <= result["timestamp"] <= after
    
    def test_preserves_existing_timestamp(self):
        """GIVEN: Payload with existing timestamp
        WHEN: enrich_with_timestamp called
        THEN: Existing timestamp is preserved
        """
        original_ts = 1234567890.0
        payload = {"event": "test", "timestamp": original_ts}
        result = enrich_with_timestamp(payload)
        
        assert result["timestamp"] == original_ts
    
    def test_custom_timestamp_key(self):
        """GIVEN: Custom timestamp key
        WHEN: enrich_with_timestamp called with timestamp_key
        THEN: Uses custom key
        """
        payload = {"event": "test"}
        result = enrich_with_timestamp(payload, timestamp_key="ts")
        
        assert "ts" in result
        assert "timestamp" not in result


class TestEventType:
    """Tests for EventType enum."""
    
    def test_has_pipeline_events(self):
        """GIVEN: EventType enum
        WHEN: Accessing pipeline events
        THEN: All pipeline event types exist
        """
        assert EventType.PIPELINE_RUN_STARTED.value == "pipeline.run.started"
        assert EventType.PIPELINE_RUN_COMPLETED.value == "pipeline.run.completed"
        assert EventType.PIPELINE_RUN_FAILED.value == "pipeline.run.failed"
    
    def test_has_extraction_events(self):
        """GIVEN: EventType enum
        WHEN: Accessing extraction events
        THEN: All extraction event types exist
        """
        assert EventType.EXTRACTION_STARTED.value == "extraction.started"
        assert EventType.EXTRACTION_COMPLETED.value == "extraction.completed"
        assert EventType.EXTRACTION_FAILED.value == "extraction.failed"
    
    def test_has_critic_events(self):
        """GIVEN: EventType enum
        WHEN: Accessing critic events
        THEN: All critic event types exist
        """
        assert EventType.CRITIC_SCORE_STARTED.value == "critic.score.started"
        assert EventType.CRITIC_SCORE_COMPLETED.value == "critic.score.completed"
        assert EventType.CRITIC_SCORE_FAILED.value == "critic.score.failed"
    
    def test_has_refinement_events(self):
        """GIVEN: EventType enum
        WHEN: Accessing refinement events
        THEN: All refinement event types exist
        """
        assert EventType.REFINEMENT_ROUND_STARTED.value == "refinement.round.started"
        assert EventType.REFINEMENT_ROUND_COMPLETED.value == "refinement.round.completed"
        assert EventType.REFINEMENT_CONVERGED.value == "refinement.converged"


class TestLogEvent:
    """Tests for log_event function."""
    
    def test_logs_basic_event(self):
        """GIVEN: Logger and event type
        WHEN: log_event called
        THEN: Logs JSON with event, schema, and timestamp
        """
        logger = MagicMock(spec=logging.Logger)
        
        log_event(logger, EventType.EXTRACTION_STARTED)
        
        # Verify logger.log was called
        assert logger.log.called
        
        # Get the logged message
        call_args = logger.log.call_args
        level, message = call_args[0]
        
        assert level == logging.INFO
        
        # Parse JSON message
        data = json.loads(message)
        assert data["event"] == "extraction.started"
        assert data["optimizer_pipeline"] == "common"
        assert data["schema"] == DEFAULT_SCHEMA
        assert data["schema_version"] == DEFAULT_SCHEMA_VERSION
        assert "timestamp" in data
    
    def test_logs_event_with_data(self):
        """GIVEN: Event with additional data
        WHEN: log_event called
        THEN: Includes data in log payload
        """
        logger = MagicMock(spec=logging.Logger)
        
        log_event(logger, EventType.EXTRACTION_COMPLETED, {"entities": 42, "duration": 1.5})
        
        message = logger.log.call_args[0][1]
        data = json.loads(message)
        
        assert data["event"] == "extraction.completed"
        assert data["optimizer_pipeline"] == "common"
        assert data["entities"] == 42
        assert data["duration"] == 1.5

    def test_redacts_sensitive_fields_in_data(self):
        """Sensitive key-based fields should be redacted before logging."""
        logger = MagicMock(spec=logging.Logger)

        log_event(
            logger,
            EventType.EXTRACTION_COMPLETED,
            {
                "api_key": "sk-1234567890abcdef",
                "nested": {"password": "hunter2"},
                "max_tokens": 512,
            },
        )

        message = logger.log.call_args[0][1]
        data = json.loads(message)
        assert data["api_key"] == "***REDACTED***"
        assert data["nested"]["password"] == "***REDACTED***"
        assert data["max_tokens"] == 512

    def test_redacts_bearer_token_in_string_values(self):
        """Pattern-based redaction should scrub bearer tokens in string payload values."""
        logger = MagicMock(spec=logging.Logger)
        token = "abcDEF1234567890.token"

        log_event(
            logger,
            EventType.EXTRACTION_COMPLETED,
            {"auth_header": f"Bearer {token}"},
        )

        message = logger.log.call_args[0][1]
        data = json.loads(message)
        assert data["auth_header"] == "Bearer ***REDACTED***"

    def test_custom_optimizer_pipeline(self):
        """GIVEN: custom optimizer_pipeline
        WHEN: log_event called
        THEN: payload carries the explicit pipeline id
        """
        logger = MagicMock(spec=logging.Logger)

        log_event(
            logger,
            EventType.EXTRACTION_STARTED,
            optimizer_pipeline="graphrag",
        )

        message = logger.log.call_args[0][1]
        data = json.loads(message)
        assert data["optimizer_pipeline"] == "graphrag"
    
    def test_logs_at_custom_level(self):
        """GIVEN: Custom log level
        WHEN: log_event called with level parameter
        THEN: Uses specified level
        """
        logger = MagicMock(spec=logging.Logger)
        
        log_event(logger, EventType.EXTRACTION_FAILED, level=logging.ERROR)
        
        level = logger.log.call_args[0][0]
        assert level == logging.ERROR
    
    def test_without_schema(self):
        """GIVEN: include_schema=False
        WHEN: log_event called
        THEN: Does not include schema metadata
        """
        logger = MagicMock(spec=logging.Logger)
        
        log_event(logger, EventType.EXTRACTION_STARTED, include_schema=False)
        
        message = logger.log.call_args[0][1]
        data = json.loads(message)
        
        assert "schema" not in data
        assert "schema_version" not in data
    
    def test_without_timestamp(self):
        """GIVEN: include_timestamp=False
        WHEN: log_event called
        THEN: Does not include timestamp
        """
        logger = MagicMock(spec=logging.Logger)
        
        log_event(logger, EventType.EXTRACTION_STARTED, include_timestamp=False)
        
        message = logger.log.call_args[0][1]
        data = json.loads(message)
        
        assert "timestamp" not in data
    
    def test_handles_json_serialization_failure(self):
        """GIVEN: Data that cannot be JSON serialized
        WHEN: log_event called
        THEN: Falls back to debug logging
        """
        logger = MagicMock(spec=logging.Logger)
        
        # Create a mock object that json.dumps will handle via default=str
        log_event(logger, EventType.EXTRACTION_STARTED, {"obj": object()})
        
        # Should still call logger.log (using default=str)
        assert logger.log.called

    def test_falls_back_to_debug_for_typed_logger_failure(self):
        """GIVEN: logger.log raises RuntimeError
        WHEN: log_event called
        THEN: Fallback debug logging is used
        """
        logger = MagicMock(spec=logging.Logger)
        logger.log.side_effect = RuntimeError("sink unavailable")

        log_event(logger, EventType.EXTRACTION_STARTED, {"k": "v"})

        assert logger.debug.called

    def test_does_not_swallow_keyboard_interrupt(self):
        """GIVEN: logger.log raises KeyboardInterrupt
        WHEN: log_event called
        THEN: KeyboardInterrupt propagates
        """
        logger = MagicMock(spec=logging.Logger)
        logger.log.side_effect = KeyboardInterrupt()

        with pytest.raises(KeyboardInterrupt):
            log_event(logger, EventType.EXTRACTION_STARTED, {"k": "v"})
