"""Tests for standardized JSON logging schema.

Tests cover:
- Log event creation and serialization
- JSON formatter output
- JSONLogger wrapper methods
- Correlation ID tracking
- Operation timer context manager
- Convenience helper functions
"""

import json
import logging
import pytest
import tempfile
from io import StringIO
from ipfs_datasets_py.optimizers.common.json_logging import (
    LogEvent,
    JSONFormatter,
    JSONLogger,
    OperationTimer,
    get_json_logger,
    setup_json_logging,
    log_api_call,
    log_database_query,
    log_cache_access,
)


class TestLogEvent:
    """Test LogEvent creation and serialization."""
    
    def test_log_event_creation(self):
        """Test creating a LogEvent."""
        event = LogEvent(
            timestamp="2026-02-25T10:30:45Z",
            level="INFO",
            logger="test_module",
            message="Test message",
        )
        
        assert event.timestamp == "2026-02-25T10:30:45Z"
        assert event.level == "INFO"
        assert event.logger == "test_module"
        assert event.message == "Test message"
    
    def test_log_event_with_fields(self):
        """Test LogEvent with structured fields."""
        event = LogEvent(
            timestamp="2026-02-25T10:30:45Z",
            level="INFO",
            logger="test",
            message="API call",
            event_type="api_call",
            duration_ms=125.5,
            status="success",
            extra={"endpoint": "/api/test", "status_code": 200},
        )
        
        assert event.event_type == "api_call"
        assert event.duration_ms == 125.5
        assert event.status == "success"
        assert event.extra["endpoint"] == "/api/test"
    
    def test_log_event_to_dict(self):
        """Test converting LogEvent to dictionary."""
        event = LogEvent(
            timestamp="2026-02-25T10:30:45Z",
            level="INFO",
            logger="test",
            message="Test",
            event_type="test_event",
            duration_ms=10.0,
        )
        
        d = event.to_dict()
        assert isinstance(d, dict)
        assert d["message"] == "Test"
        assert d["event_type"] == "test_event"
        assert "correlation_id" not in d  # Should be filtered out if None
    
    def test_log_event_to_json(self):
        """Test converting LogEvent to JSON string."""
        event = LogEvent(
            timestamp="2026-02-25T10:30:45Z",
            level="INFO",
            logger="test",
            message="Test",
            event_type="test",
        )
        
        json_str = event.to_json()
        parsed = json.loads(json_str)
        
        assert parsed["message"] == "Test"
        assert parsed["level"] == "INFO"


class TestJSONFormatter:
    """Test JSONFormatter functionality."""
    
    def test_formatter_basic(self):
        """Test basic JSON formatting."""
        logger = logging.getLogger("test_formatter")
        handler = logging.StreamHandler(StringIO())
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        
        logger.info("Test message")
        
        # Check that output is valid JSON
        stream = handler.stream
        stream.seek(0)
        output = stream.read()
        parsed = json.loads(output.strip())
        
        assert parsed["message"] == "Test message"
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test_formatter"
    
    def test_formatter_with_extra_fields(self):
        """Test formatting with extra fields."""
        logger = logging.getLogger("test_extra")
        handler = logging.StreamHandler(StringIO())
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        
        logger.info(
            "API call",
            extra={
                "event_type": "api_call",
                "duration_ms": 100.5,
                "status": "success",
                "endpoint": "/test",
            }
        )
        
        stream = handler.stream
        stream.seek(0)
        output = stream.read()
        parsed = json.loads(output.strip())
        
        assert parsed["event_type"] == "api_call"
        assert parsed["duration_ms"] == 100.5
        assert parsed["status"] == "success"
        assert parsed["endpoint"] == "/test"


class TestJSONLogger:
    """Test JSONLogger wrapper."""
    
    def test_json_logger_creation(self):
        """Test creating a JSONLogger."""
        std_logger = logging.getLogger("test_json")
        json_logger = JSONLogger(std_logger)
        
        assert json_logger.logger == std_logger
    
    def test_json_logger_debug(self, capsys):
        """Test debug logging method."""
        logger = get_json_logger("test_debug")
        logger.logger.handlers.clear()
        
        handler = logging.StreamHandler(StringIO())
        handler.setFormatter(JSONFormatter())
        logger.logger.addHandler(handler)
        logger.logger.setLevel(logging.DEBUG)
        
        logger.debug("Debug message", event_type="test", custom_field="value")
        
        stream = handler.stream
        stream.seek(0)
        output = stream.read()
        parsed = json.loads(output.strip())
        
        assert parsed["message"] == "Debug message"
        assert parsed["level"] == "DEBUG"
        assert parsed["event_type"] == "test"
    
    def test_json_logger_info(self):
        """Test info logging method."""
        logger = get_json_logger("test_info")
        logger.logger.handlers.clear()
        
        handler = logging.StreamHandler(StringIO())
        handler.setFormatter(JSONFormatter())
        logger.logger.addHandler(handler)
        logger.logger.setLevel(logging.INFO)
        
        logger.info("Info message", event_type="info_test", status="success")
        
        stream = handler.stream
        stream.seek(0)
        output = stream.read()
        parsed = json.loads(output.strip())
        
        assert parsed["level"] == "INFO"
        assert parsed["status"] == "success"
    
    def test_json_logger_error(self):
        """Test error logging method."""
        logger = get_json_logger("test_error")
        logger.logger.handlers.clear()
        
        handler = logging.StreamHandler(StringIO())
        handler.setFormatter(JSONFormatter())
        logger.logger.addHandler(handler)
        logger.logger.setLevel(logging.ERROR)
        
        logger.error("Error message", status="failure")
        
        stream = handler.stream
        stream.seek(0)
        output = stream.read()
        parsed = json.loads(output.strip())
        
        assert parsed["level"] == "ERROR"
        assert parsed["status"] == "failure"
    
    def test_correlation_id(self):
        """Test correlation ID tracking."""
        logger = get_json_logger("test_correlation")
        
        # Initially None
        assert logger.get_correlation_id() is None
        
        # Set correlation ID
        logger.set_correlation_id("test-correlation-123")
        assert logger.get_correlation_id() == "test-correlation-123"
        
        # Generate new correlation ID
        new_id = logger.generate_correlation_id()
        assert logger.get_correlation_id() == new_id
        assert len(new_id) > 0


class TestOperationTimer:
    """Test OperationTimer context manager."""
    
    def test_timer_successful_operation(self):
        """Test timing a successful operation."""
        logger = get_json_logger("test_timer")
        logger.logger.handlers.clear()
        
        handler = logging.StreamHandler(StringIO())
        handler.setFormatter(JSONFormatter())
        logger.logger.addHandler(handler)
        logger.logger.setLevel(logging.INFO)
        
        with OperationTimer(logger, "test_operation", event_type="operation") as timer:
            # Simulate work
            import time
            time.sleep(0.01)
        
        # Check log output
        assert timer.duration_ms is not None
        assert timer.duration_ms >= 10  # Should be at least 10ms
        
        stream = handler.stream
        stream.seek(0)
        output = stream.read()
        parsed = json.loads(output.strip())
        
        assert "completed" in parsed["message"]
        assert parsed["status"] == "success"
        assert parsed["duration_ms"] > 0
    
    def test_timer_failed_operation(self):
        """Test timer when operation fails."""
        logger = get_json_logger("test_timer_fail")
        logger.logger.handlers.clear()
        
        handler = logging.StreamHandler(StringIO())
        handler.setFormatter(JSONFormatter())
        logger.logger.addHandler(handler)
        logger.logger.setLevel(logging.ERROR)
        
        try:
            with OperationTimer(logger, "failing_op"):
                raise ValueError("Test error")
        except ValueError:
            pass
        
        stream = handler.stream
        stream.seek(0)
        output = stream.read()
        parsed = json.loads(output.strip())
        
        assert "failed" in parsed["message"]
        assert parsed["status"] == "failure"
        assert "exception" in parsed


class TestConvenienceFunctions:
    """Test convenience logging functions."""
    
    def test_log_api_call(self):
        """Test logging API calls."""
        logger = get_json_logger("test_api")
        logger.logger.handlers.clear()
        
        handler = logging.StreamHandler(StringIO())
        handler.setFormatter(JSONFormatter())
        logger.logger.addHandler(handler)
        logger.logger.setLevel(logging.INFO)
        
        log_api_call(
            logger,
            endpoint="/api/test",
            method="GET",
            status_code=200,
            duration_ms=50.5,
            response_size=1024,
        )
        
        stream = handler.stream
        stream.seek(0)
        output = stream.read()
        parsed = json.loads(output.strip())
        
        assert parsed["event_type"] == "api_call"
        assert parsed["endpoint"] == "/api/test"
        assert parsed["method"] == "GET"
        assert parsed["status_code"] == 200
        assert parsed["status"] == "success"
    
    def test_log_database_query(self):
        """Test logging database queries."""
        logger = get_json_logger("test_db")
        logger.logger.handlers.clear()
        
        handler = logging.StreamHandler(StringIO())
        handler.setFormatter(JSONFormatter())
        logger.logger.addHandler(handler)
        logger.logger.setLevel(logging.INFO)
        
        log_database_query(
            logger,
            query_type="SELECT",
            duration_ms=25.0,
            rows_affected=10,
            table="users",
        )
        
        stream = handler.stream
        stream.seek(0)
        output = stream.read()
        parsed = json.loads(output.strip())
        
        assert parsed["event_type"] == "database_query"
        assert parsed["query_type"] == "SELECT"
        assert parsed["rows_affected"] == 10
        assert parsed["table"] == "users"
    
    def test_log_cache_hit(self):
        """Test logging cache hits."""
        logger = get_json_logger("test_cache")
        logger.logger.handlers.clear()
        
        handler = logging.StreamHandler(StringIO())
        handler.setFormatter(JSONFormatter())
        logger.logger.addHandler(handler)
        logger.logger.setLevel(logging.DEBUG)
        
        log_cache_access(
            logger,
            cache_key="user:123",
            hit=True,
            duration_ms=1.5,
        )
        
        stream = handler.stream
        stream.seek(0)
        output = stream.read()
        parsed = json.loads(output.strip())
        
        assert parsed["event_type"] == "cache_access"
        assert parsed["status"] == "hit"
        assert parsed["cache_key"] == "user:123"
    
    def test_log_cache_miss(self):
        """Test logging cache misses."""
        logger = get_json_logger("test_cache_miss")
        logger.logger.handlers.clear()
        
        handler = logging.StreamHandler(StringIO())
        handler.setFormatter(JSONFormatter())
        logger.logger.addHandler(handler)
        logger.logger.setLevel(logging.DEBUG)
        
        log_cache_access(
            logger,
            cache_key="user:999",
            hit=False,
            duration_ms=0.5,
        )
        
        stream = handler.stream
        stream.seek(0)
        output = stream.read()
        parsed = json.loads(output.strip())
        
        assert parsed["status"] == "miss"


class TestSetupJsonLogging:
    """Test JSON logging setup."""
    
    def test_setup_default(self):
        """Test default setup."""
        logger = setup_json_logging("test_setup")
        
        assert isinstance(logger, JSONLogger)
        assert logger.logger.name == "test_setup"
    
    def test_setup_with_file(self):
        """Test setup with file output."""
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".log") as f:
            logger = setup_json_logging("test_file", output_file=f.name)
            
            logger.info("Test message", event_type="setup_test")
            
            # Read file content
            with open(f.name) as rf:
                content = rf.read()
            
            parsed = json.loads(content.strip())
            assert parsed["message"] == "Test message"
            assert parsed["event_type"] == "setup_test"


class TestJSONLoggingEdgeCases:
    """Test edge cases and special scenarios."""
    
    def test_none_filtering(self):
        """Test that None values are filtered from output."""
        event = LogEvent(
            timestamp="2026-02-25T10:30:45Z",
            level="INFO",
            logger="test",
            message="Test",
            correlation_id=None,  # Should be filtered
            duration_ms=None,  # Should be filtered
        )
        
        d = event.to_dict()
        assert "correlation_id" not in d
        assert "duration_ms" not in d
    
    def test_special_characters_in_message(self):
        """Test logging with special characters."""
        logger = get_json_logger("test_special")
        logger.logger.handlers.clear()
        
        handler = logging.StreamHandler(StringIO())
        handler.setFormatter(JSONFormatter())
        logger.logger.addHandler(handler)
        logger.logger.setLevel(logging.INFO)
        
        logger.info('Test with "quotes" and \\ backslashes')
        
        stream = handler.stream
        stream.seek(0)
        output = stream.read()
        # Should be valid JSON even with special characters
        parsed = json.loads(output.strip())
        assert "quotes" in parsed["message"]
    
    def test_large_extra_fields(self):
        """Test logging with many extra fields."""
        logger = get_json_logger("test_large")
        logger.logger.handlers.clear()
        
        handler = logging.StreamHandler(StringIO())
        handler.setFormatter(JSONFormatter())
        logger.logger.addHandler(handler)
        logger.logger.setLevel(logging.INFO)
        
        extra_fields = {f"field_{i}": f"value_{i}" for i in range(100)}
        logger.info("Message with many fields", **extra_fields)
        
        stream = handler.stream
        stream.seek(0)
        output = stream.read()
        parsed = json.loads(output.strip())
        
        assert parsed["field_0"] == "value_0"
        assert parsed["field_99"] == "value_99"
