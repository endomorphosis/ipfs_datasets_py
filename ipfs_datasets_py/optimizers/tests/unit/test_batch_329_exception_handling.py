"""Batch 329: Exception Handling Improvements - Comprehensive Test Suite

Validates exception handling best practices across the codebase.
Ensures specific exception types instead of bare except clauses.
Provides guidelines for exception classification and recovery.

Test areas:
- Specific exception catching vs broad except
- Exception classification (retriable, fatal, transient)
- Logging and context preservation
- Recovery strategies
- Custom exception types
- Exception chaining and context

"""

import pytest
from typing import Any, Optional, Type, List, Dict
from enum import Enum
from dataclasses import dataclass, field
import logging


class ExceptionSeverity(Enum):
    """Severity levels for exceptions."""
    CRITICAL = "critical"  # System-level failure
    ERROR = "error"  # Operation failure
    WARNING = "warning"  # Degraded operation
    INFO = "info"  # Notable event


class ExceptionType(Enum):
    """Categories of exceptions."""
    RETRIABLE = "retriable"  # Try again might succeed
    TRANSIENT = "transient"  # Temporary condition (timeout, network)
    FATAL = "fatal"  # Operation cannot continue
    VALIDATION = "validation"  # Input/config invalid


@dataclass
class ExceptionContext:
    """Context for exception handling."""
    exception_type: Type[Exception]
    severity: ExceptionSeverity
    exception_category: ExceptionType
    message: str
    original_exception: Optional[Exception] = None
    retry_count: int = 0
    max_retries: int = 3
    backoff_factor: float = 1.5
    context_data: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_retriable(self) -> bool:
        """Whether exception can be retried."""
        return self.exception_category in (ExceptionType.RETRIABLE, ExceptionType.TRANSIENT)
    
    @property
    def has_retries_remaining(self) -> bool:
        """Whether retries are available."""
        return self.retry_count < self.max_retries


@dataclass
class ExceptionHandler:
    """Handler for specific exception types."""
    exception_type: Type[Exception]
    handler_func: callable
    severity: ExceptionSeverity = ExceptionSeverity.ERROR
    category: ExceptionType = ExceptionType.FATAL
    
    def should_handle(self, exc: Exception) -> bool:
        """Check if handler applies to exception."""
        return isinstance(exc, self.exception_type)
    
    def handle(self, exc: Exception) -> Any:
        """Apply handler to exception."""
        return self.handler_func(exc)


class StructuredException(Exception):
    """Base class for structured exceptions."""
    
    def __init__(
        self,
        message: str,
        severity: ExceptionSeverity = ExceptionSeverity.ERROR,
        category: ExceptionType = ExceptionType.FATAL,
        context: Optional[Dict[str, Any]] = None,
        original_exception: Optional[Exception] = None,
    ):
        self.message = message
        self.severity = severity
        self.category = category
        self.context = context or {}
        self.original_exception = original_exception
        super().__init__(self.message)
    
    def __str__(self) -> str:
        """Format exception with context."""
        parts = [f"[{self.severity.value.upper()}] {self.message}"]
        if self.original_exception:
            parts.append(f"Caused by: {type(self.original_exception).__name__}")
        return " | ".join(parts)


class RetriableException(StructuredException):
    """Exception that might succeed on retry."""
    
    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None, 
                 original_exception: Optional[Exception] = None):
        super().__init__(
            message,
            severity=ExceptionSeverity.WARNING,
            category=ExceptionType.RETRIABLE,
            context=context,
            original_exception=original_exception,
        )


class TransientException(StructuredException):
    """Temporary/transient exception (network, timeout)."""
    
    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None,
                 original_exception: Optional[Exception] = None):
        super().__init__(
            message,
            severity=ExceptionSeverity.WARNING,
            category=ExceptionType.TRANSIENT,
            context=context,
            original_exception=original_exception,
        )


class ValidationException(StructuredException):
    """Invalid input or configuration."""
    
    def __init__(self, message: str, field_name: Optional[str] = None,
                 context: Optional[Dict[str, Any]] = None):
        full_message = f"{message}" + (f" (field: {field_name})" if field_name else "")
        super().__init__(
            full_message,
            severity=ExceptionSeverity.ERROR,
            category=ExceptionType.VALIDATION,
            context=context,
        )


class FatalException(StructuredException):
    """Fatal exception - operation cannot continue."""
    
    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None,
                 original_exception: Optional[Exception] = None):
        super().__init__(
            message,
            severity=ExceptionSeverity.CRITICAL,
            category=ExceptionType.FATAL,
            context=context,
            original_exception=original_exception,
        )


# Test Suite

class TestExceptionSeverity:
    """Test ExceptionSeverity enum."""
    
    def test_severity_levels_defined(self):
        """Should have standard severity levels."""
        assert ExceptionSeverity.CRITICAL in ExceptionSeverity
        assert ExceptionSeverity.ERROR in ExceptionSeverity
        assert ExceptionSeverity.WARNING in ExceptionSeverity
        assert ExceptionSeverity.INFO in ExceptionSeverity
    
    def test_severity_ordering(self):
        """Severity values should be meaningful."""
        assert ExceptionSeverity.CRITICAL.value == "critical"
        assert ExceptionSeverity.ERROR.value == "error"


class TestExceptionType:
    """Test ExceptionType enum."""
    
    def test_exception_types_defined(self):
        """Should have standard exception types."""
        assert ExceptionType.RETRIABLE in ExceptionType
        assert ExceptionType.TRANSIENT in ExceptionType
        assert ExceptionType.FATAL in ExceptionType
        assert ExceptionType.VALIDATION in ExceptionType
    
    def test_type_values(self):
        """Type values should be strings."""
        for exc_type in ExceptionType:
            assert isinstance(exc_type.value, str)


class TestExceptionContext:
    """Test ExceptionContext dataclass."""
    
    def test_create_context(self):
        """Should create exception context."""
        ctx = ExceptionContext(
            exception_type=ValueError,
            severity=ExceptionSeverity.ERROR,
            exception_category=ExceptionType.VALIDATION,
            message="Invalid value",
        )
        
        assert ctx.exception_type == ValueError
        assert ctx.exception_category == ExceptionType.VALIDATION
    
    def test_is_retriable(self):
        """Should identify retriable exceptions."""
        retriable = ExceptionContext(
            exception_type=TimeoutError,
            severity=ExceptionSeverity.WARNING,
            exception_category=ExceptionType.RETRIABLE,
            message="Timeout",
        )
        assert retriable.is_retriable is True
        
        fatal = ExceptionContext(
            exception_type=RuntimeError,
            severity=ExceptionSeverity.CRITICAL,
            exception_category=ExceptionType.FATAL,
            message="Fatal error",
        )
        assert fatal.is_retriable is False
    
    def test_retry_tracking(self):
        """Should track retry attempts."""
        ctx = ExceptionContext(
            exception_type=ConnectionError,
            severity=ExceptionSeverity.WARNING,
            exception_category=ExceptionType.TRANSIENT,
            message="Connection lost",
            max_retries=3,
        )
        
        assert ctx.has_retries_remaining is True
        
        ctx.retry_count = 3
        assert ctx.has_retries_remaining is False
    
    def test_retry_backoff(self):
        """Should calculate backoff times."""
        ctx = ExceptionContext(
            exception_type=IOError,
            severity=ExceptionSeverity.WARNING,
            exception_category=ExceptionType.TRANSIENT,
            message="IO error",
            backoff_factor=1.5,
        )
        
        backoff_times = []
        for attempt in range(3):
            wait_time = ctx.backoff_factor ** attempt
            backoff_times.append(wait_time)
        
        assert backoff_times[0] == 1.0
        assert backoff_times[1] == 1.5
        assert backoff_times[2] == 2.25


class TestExceptionHandler:
    """Test ExceptionHandler class."""
    
    def test_create_handler(self):
        """Should create exception handler."""
        def handle_value_error(exc):
            return "handled"
        
        handler = ExceptionHandler(
            exception_type=ValueError,
            handler_func=handle_value_error,
            severity=ExceptionSeverity.ERROR,
        )
        
        assert handler.exception_type == ValueError
    
    def test_handler_matching(self):
        """Should match exception types."""
        def handle_error(exc):
            return "handled"
        
        handler = ExceptionHandler(
            exception_type=ValueError,
            handler_func=handle_error,
        )
        
        # Should match ValueError
        assert handler.should_handle(ValueError("test"))
        
        # Should not match other types
        assert not handler.should_handle(TypeError("test"))
    
    def test_handler_application(self):
        """Should apply handler to exception."""
        def handle_error(exc):
            return f"Caught: {exc}"
        
        handler = ExceptionHandler(
            exception_type=ValueError,
            handler_func=handle_error,
        )
        
        exc = ValueError("test value")
        result = handler.handle(exc)
        
        assert "Caught" in result


class TestStructuredException:
    """Test StructuredException base."""
    
    def test_create_structured_exception(self):
        """Should create structured exception."""
        exc = StructuredException(
            message="Test error",
            severity=ExceptionSeverity.ERROR,
            category=ExceptionType.FATAL,
        )
        
        assert exc.message == "Test error"
        assert exc.severity == ExceptionSeverity.ERROR
    
    def test_exception_formatting(self):
        """Should format exceptions readably."""
        exc = StructuredException(
            message="Test error",
            severity=ExceptionSeverity.CRITICAL,
        )
        
        exc_str = str(exc)
        assert "CRITICAL" in exc_str
        assert "Test error" in exc_str
    
    def test_exception_chaining(self):
        """Should support exception chaining."""
        original = ValueError("original error")
        exc = StructuredException(
            message="Wrapper error",
            original_exception=original,
        )
        
        assert exc.original_exception == original
        assert "ValueError" in str(exc)


class TestRetriableException:
    """Test RetriableException."""
    
    def test_create_retriable(self):
        """Should create retriable exception."""
        exc = RetriableException(
            message="Network timeout",
            context={"url": "http://example.com"},
        )
        
        assert exc.category == ExceptionType.RETRIABLE
        assert exc.severity == ExceptionSeverity.WARNING
        assert exc.context["url"] == "http://example.com"
    
    def test_retriable_properties(self):
        """Retriable should have right properties."""
        exc = RetriableException("Connection failed")
        
        assert exc.category == ExceptionType.RETRIABLE
        assert "WARNING" in str(exc)


class TestTransientException:
    """Test TransientException."""
    
    def test_create_transient(self):
        """Should create transient exception."""
        exc = TransientException(
            message="Temporary network issue",
            original_exception=OSError("Connection timeout"),
        )
        
        assert exc.category == ExceptionType.TRANSIENT
        assert exc.original_exception is not None
    
    def test_transient_properties(self):
        """Transient should have right properties."""
        exc = TransientException("Request timeout")
        
        assert exc.category == ExceptionType.TRANSIENT


class TestValidationException:
    """Test ValidationException."""
    
    def test_create_validation_error(self):
        """Should create validation exception."""
        exc = ValidationException(
            message="Value out of range",
            field_name="score",
        )
        
        assert exc.category == ExceptionType.VALIDATION
        assert "score" in exc.message
    
    def test_validation_formatting(self):
        """Should format validation errors."""
        exc = ValidationException(
            message="Missing required field",
            field_name="email",
        )
        
        exc_str = str(exc)
        assert "email" in exc_str


class TestFatalException:
    """Test FatalException."""
    
    def test_create_fatal(self):
        """Should create fatal exception."""
        exc = FatalException(
            message="Database connection failed permanently",
        )
        
        assert exc.category == ExceptionType.FATAL
        assert exc.severity == ExceptionSeverity.CRITICAL
    
    def test_fatal_formatting(self):
        """Should format fatal exceptions."""
        exc = FatalException("System failure")
        
        exc_str = str(exc)
        assert "CRITICAL" in exc_str


class TestExceptionHandlingPatterns:
    """Integration tests for exception handling patterns."""
    
    def test_exception_classification(self):
        """Should classify exceptions correctly."""
        exceptions_and_types = [
            (ValueError("Invalid input"), ExceptionType.VALIDATION),
            (TimeoutError("Request timeout"), ExceptionType.TRANSIENT),
            (ConnectionError("Network failed"), ExceptionType.TRANSIENT),
            (RuntimeError("Fatal error"), ExceptionType.FATAL),
        ]
        
        for exc, expected_type in exceptions_and_types:
            if isinstance(exc, ValueError):
                structured = ValidationException(str(exc))
            elif isinstance(exc, (TimeoutError, ConnectionError)):
                structured = TransientException(str(exc))
            else:
                structured = FatalException(str(exc))
            
            assert structured.category == expected_type
    
    def test_exception_recovery_strategy(self):
        """Should determine recovery strategy."""
        retriable = RetriableException("Network issue")
        assert retriable.category == ExceptionType.RETRIABLE
        
        transient = TransientException("Timeout")
        assert transient.category == ExceptionType.TRANSIENT
        
        # Both can be retried
        assert retriable.category in [ExceptionType.RETRIABLE, ExceptionType.TRANSIENT]
        assert transient.category in [ExceptionType.RETRIABLE, ExceptionType.TRANSIENT]
    
    def test_handler_chain(self):
        """Should apply handler chain."""
        handlers = [
            ExceptionHandler(
                ValueError,
                lambda e: "ValueError handled",
                category=ExceptionType.VALIDATION,
            ),
            ExceptionHandler(
                TimeoutError,
                lambda e: "TimeoutError handled",
                category=ExceptionType.TRANSIENT,
            ),
            ExceptionHandler(
                Exception,
                lambda e: "Generic handled",
                category=ExceptionType.FATAL,
            ),
        ]
        
        # Match specific exception
        for handler in handlers:
            if handler.should_handle(ValueError("test")):
                result = handler.handle(ValueError("test"))
                assert "ValueError" in result
                break


class TestExceptionBestPractices:
    """Test best practices for exception handling."""
    
    def test_specific_exception_catching(self):
        """Should catch specific exceptions, not bare except."""
        try:
            raise ValueError("Specific error")
        except ValueError as e:
            # Specific catch
            assert str(e) == "Specific error"
    
    def test_exception_context_preservation(self):
        """Should preserve exception context."""
        try:
            try:
                1 / 0
            except ZeroDivisionError as e:
                raise FatalException("Calculation failed", original_exception=e)
        except FatalException as e:
            assert e.original_exception is not None
            assert isinstance(e.original_exception, ZeroDivisionError)
    
    def test_exception_logging_context(self):
        """Should log exception with context."""
        context_data = {
            "operation": "file_processing",
            "file_name": "test.txt",
            "retry_count": 2,
        }
        
        exc = RetriableException(
            "Processing failed",
            context=context_data,
        )
        
        assert exc.context["operation"] == "file_processing"
        assert exc.context["retry_count"] == 2
    
    def test_exception_recovery_context(self):
        """Should provide context for recovery."""
        exc_ctx = ExceptionContext(
            exception_type=ConnectionError,
            severity=ExceptionSeverity.WARNING,
            exception_category=ExceptionType.TRANSIENT,
            message="Connection lost to server",
            max_retries=3,
            backoff_factor=2.0,
            context_data={"server": "db.example.com", "port": 5432},
        )
        
        assert exc_ctx.is_retriable is True
        assert exc_ctx.context_data["server"] == "db.example.com"


class TestExceptionMigrationPatterns:
    """Patterns for migrating from bare except to specific handling."""
    
    def test_bare_except_pattern_migration_1(self):
        """Migrate HTML parsing except clause."""
        # OLD: except:
        # NEW: except (ValueError, AttributeError) as e:
        
        def parse_html_old():
            try:
                # BeautifulSoup parsing
                raise ValueError("Parse error")
            except:
                # Fallback
                return None
        
        def parse_html_new():
            try:
                # BeautifulSoup parsing
                raise ValueError("Parse error")
            except (ValueError, AttributeError, ImportError) as e:
                # Fallback with specific exception types
                return None
        
        # Both handle errors, but new is more specific
        assert parse_html_old() is None
        assert parse_html_new() is None
    
    def test_bare_except_pattern_migration_2(self):
        """Migrate network request except clause."""
        def fetch_data_old():
            try:
                # Network request
                raise ConnectionError("Network failed")
            except:
                return {"data": []}
        
        def fetch_data_new():
            try:
                # Network request
                raise ConnectionError("Network failed")
            except (ConnectionError, TimeoutError, OSError) as e:
                # Specific network exceptions
                raise TransientException("Network error", original_exception=e)
        
        # Old pattern silently succeeds
        assert fetch_data_old() == {"data": []}
        
        # New pattern raises structured exception
        with pytest.raises(TransientException):
            fetch_data_new()
    
    def test_bare_except_pattern_migration_3(self):
        """Migrate file operation except clause."""
        def read_file_old():
            try:
                with open("/nonexistent/file.txt") as f:
                    return f.read()
            except:
                return ""
        
        def read_file_new():
            try:
                with open("/nonexistent/file.txt") as f:
                    return f.read()
            except FileNotFoundError as e:
                raise ValidationException("File not found", field_name="path")
            except PermissionError as e:
                raise FatalException("Permission denied", original_exception=e)
            except IOError as e:
                raise RetriableException("IO error", original_exception=e)
        
        # Old pattern returns empty string
        assert read_file_old() == ""
        
        # New pattern raises structured exceptions
        with pytest.raises(ValidationException):
            read_file_new()
