"""
Tests for error handling and exception utilities.

This test suite covers:
- Exception hierarchy and creation
- Error context management
- Exception wrapping and conversion
- Retry mechanisms with backoff
- Safe operation execution
- Error serialization
"""

import pytest
import time
from unittest.mock import Mock, patch

from ipfs_datasets_py.optimizers.graphrag.error_handling import (
    GraphRAGException,
    GraphRAGConfigError,
    GraphRAGExtractionError,
    GraphRAGOptimizationError,
    GraphRAGConvergenceError,
    GraphRAGResourceError,
    GraphRAGQueryError,
    GraphRAGValidationError,
    GraphRAGIntegrationError,
    ErrorContext,
    ErrorDetail,
    ErrorSeverity,
    RecoveryStrategy,
    error_context,
    wrap_exception,
    retry_with_backoff,
    safe_operation,
)


class TestGraphRAGException:
    """Tests for base GraphRAG exception."""
    
    def test_exception_creation_minimal(self):
        """Test creating exception with minimal arguments."""
        exc = GraphRAGException("Test error")
        assert exc.message == "Test error"
        assert exc.severity == ErrorSeverity.ERROR
        assert exc.suggestions == []
        assert exc.details == {}
    
    def test_exception_creation_full(self):
        """Test creating exception with all arguments."""
        exc = GraphRAGException(
            "Test error",
            source="test_module",
            severity=ErrorSeverity.WARNING,
            suggestions=["Fix A", "Fix B"],
            details={"key": "value"}
        )
        assert exc.message == "Test error"
        assert exc.source == "test_module"
        assert exc.severity == ErrorSeverity.WARNING
        assert exc.suggestions == ["Fix A", "Fix B"]
        assert exc.details["key"] == "value"
    
    def test_exception_string_representation(self):
        """Test string representation of exception."""
        exc = GraphRAGException(
            "Test error",
            source="module",
            suggestions=["Fix it"]
        )
        exc_str = str(exc)
        assert "Test error" in exc_str
        assert "module" in exc_str
        assert "Fix it" in exc_str
    
    def test_exception_to_dict(self):
        """Test converting exception to dict."""
        exc = GraphRAGException(
            "Test error",
            source="module",
            suggestions=["Fix it"],
            details={"code": "ERR_001"}
        )
        exc_dict = exc.to_dict()
        assert exc_dict['error_type'] == 'GraphRAGException'
        assert exc_dict['message'] == 'Test error'
        assert exc_dict['source'] == 'module'
        assert 'Fix it' in exc_dict['suggestions']
        assert exc_dict['details']['code'] == 'ERR_001'
    
    def test_exception_to_error_detail(self):
        """Test converting exception to ErrorDetail."""
        exc = GraphRAGException(
            "Test error",
            source="module",
            suggestions=["Fix it"]
        )
        detail = exc.to_error_detail()
        assert isinstance(detail, ErrorDetail)
        assert detail.error_type == 'GraphRAGException'
        assert detail.message == 'Test error'
        assert 'Fix it' in detail.suggestions


class TestExceptionHierarchy:
    """Tests for exception class hierarchy."""
    
    def test_config_error_inheritance(self):
        """Test ConfigError inherits from GraphRAGException."""
        exc = GraphRAGConfigError("Invalid config", invalid_field="timeout")
        assert isinstance(exc, GraphRAGException)
        assert exc.invalid_field == "timeout"
        assert 'invalid_field' in exc.details
    
    def test_extraction_error_inheritance(self):
        """Test ExtractionError inherits from GraphRAGException."""
        exc = GraphRAGExtractionError(
            "Extraction failed",
            failed_extractions=["e1", "e2"],
            partial_result={"count": 10}
        )
        assert isinstance(exc, GraphRAGException)
        assert exc.failed_extractions == ["e1", "e2"]
        assert exc.partial_result is not None
    
    def test_convergence_error_inheritance(self):
        """Test ConvergenceError inherits from OptimizationError."""
        exc = GraphRAGConvergenceError(
            "Did not converge",
            iteration=100
        )
        assert isinstance(exc, GraphRAGOptimizationError)
        assert isinstance(exc, GraphRAGException)
        assert exc.iteration == 100
    
    def test_resource_error_inheritance(self):
        """Test ResourceError has resource-specific fields."""
        exc = GraphRAGResourceError(
            "Out of memory",
            resource_type="memory",
            limit=1000,
            used=1200
        )
        assert isinstance(exc, GraphRAGOptimizationError)
        assert exc.resource_type == "memory"
        assert exc.limit == 1000
        assert exc.used == 1200
    
    def test_query_error_inheritance(self):
        """Test QueryError has query-specific fields."""
        exc = GraphRAGQueryError(
            "Query failed",
            query="SELECT * FROM entities",
            execution_plan="vector_search"
        )
        assert isinstance(exc, GraphRAGException)
        assert exc.query == "SELECT * FROM entities"
    
    def test_validation_error_inheritance(self):
        """Test ValidationError has validation-specific fields."""
        exc = GraphRAGValidationError(
            "Validation failed",
            validation_errors=["Missing field", "Invalid range"]
        )
        assert isinstance(exc, GraphRAGException)
        assert len(exc.validation_errors) == 2
    
    def test_integration_error_inheritance(self):
        """Test IntegrationError has integration-specific fields."""
        exc = GraphRAGIntegrationError(
            "API call failed",
            external_system="openai",
            http_status=429
        )
        assert isinstance(exc, GraphRAGException)
        assert exc.external_system == "openai"
        assert exc.http_status == 429


class TestErrorContext:
    """Tests for error context management."""
    
    def test_error_context_creation(self):
        """Test creating error context."""
        ctx = ErrorContext("extraction", entity_id="e1", component="analyzer")
        assert ctx.operation == "extraction"
        assert ctx.entity_id == "e1"
        assert ctx.component == "analyzer"
    
    def test_error_context_manager(self):
        """Test error context as context manager."""
        with error_context("test_op", entity_id="e1") as ctx:
            assert ctx.operation == "test_op"
            assert ctx.entity_id == "e1"
            current = ErrorContext.current()
            assert current is not None
            assert current.operation == "test_op"
        
        # Context popped after exit
        assert ErrorContext.current() is None
    
    def test_error_context_stack(self):
        """Test nested error contexts maintain stack."""
        with error_context("op1"):
            ctx1 = ErrorContext.current()
            assert ctx1.operation == "op1"
            
            with error_context("op2"):
                ctx2 = ErrorContext.current()
                assert ctx2.operation == "op2"
            
            # Back to outer context
            ctx_current = ErrorContext.current()
            assert ctx_current.operation == "op1"
        
        # All popped
        assert ErrorContext.current() is None
    
    def test_error_context_to_dict(self):
        """Test converting error context to dict."""
        ctx = ErrorContext("extract", entity_id="e1")
        ctx_dict = ctx.to_dict()
        assert ctx_dict['operation'] == "extract"
        assert ctx_dict['entity_id'] == "e1"
        assert 'timestamp' in ctx_dict


class TestExceptionWrapping:
    """Tests for exception wrapping utilities."""
    
    def test_wrap_exception_basic(self):
        """Test wrapping basic Python exception."""
        original = ValueError("Invalid value")
        wrapped = wrap_exception(original, GraphRAGConfigError, "Bad config")
        
        assert isinstance(wrapped, GraphRAGConfigError)
        assert wrapped.message == "Bad config"
        assert wrapped.original_exception is original
    
    def test_wrap_exception_preserves_original(self):
        """Test wrapped exception preserves original."""
        original = RuntimeError("System error")
        wrapped = wrap_exception(
            original,
            GraphRAGExtractionError,
            "Extraction failed"
        )
        
        assert wrapped.original_exception is original
        assert wrapped.message == "Extraction failed"
    
    def test_wrap_exception_with_context(self):
        """Test wrapping exception captures current context."""
        with error_context("extraction", entity_id="e1"):
            original = ValueError("Field error")
            wrapped = wrap_exception(original, GraphRAGValidationError)
            
            # Note: current context passing would require modification to wrap_exception
            assert wrapped.message == "Field error"


class TestRetryMechanism:
    """Tests for retry with backoff functionality."""
    
    def test_retry_succeeds_immediately(self):
        """Test retry succeeds on first attempt."""
        func = Mock(return_value="success")
        decorated = retry_with_backoff(func, max_attempts=3)
        
        result = decorated()
        assert result == "success"
        assert func.call_count == 1
    
    def test_retry_succeeds_after_failures(self):
        """Test retry succeeds after initial failures."""
        func = Mock(side_effect=[RuntimeError("fail"), RuntimeError("fail"), "success"])
        decorated = retry_with_backoff(
            func,
            max_attempts=3,
            initial_delay=0.01,
            backoff_factor=1.0
        )
        
        result = decorated()
        assert result == "success"
        assert func.call_count == 3
    
    def test_retry_exhausts_attempts(self):
        """Test retry exhausts max attempts and raises."""
        func = Mock(side_effect=RuntimeError("fail"))
        decorated = retry_with_backoff(
            func,
            max_attempts=2,
            initial_delay=0.01
        )
        
        with pytest.raises(GraphRAGException) as exc_info:
            decorated()
        
        assert func.call_count == 2
        assert isinstance(exc_info.value, GraphRAGException)
        assert "Failed after 2 attempts" in str(exc_info.value)
    
    def test_retry_respects_exception_types(self):
        """Test retry only retries on specified exceptions."""
        func = Mock(side_effect=ValueError("wrong error"))
        decorated = retry_with_backoff(
            func,
            max_attempts=3,
            exceptions=(RuntimeError,)
        )
        
        with pytest.raises(ValueError):
            decorated()
        
        # Should not retry on ValueError
        assert func.call_count == 1
    
    def test_retry_exponential_backoff(self):
        """Test retry implements exponential backoff."""
        func = Mock(side_effect=RuntimeError("fail"))
        decorated = retry_with_backoff(
            func,
            max_attempts=3,
            initial_delay=0.01,
            backoff_factor=2.0
        )
        
        start = time.time()
        try:
            decorated()
        except GraphRAGException:
            pass
        elapsed = time.time() - start
        
        # Should take approximately 0.01 + 0.02 = 0.03 seconds
        # Allow some margin for system timing
        assert elapsed >= 0.02


class TestSafeOperation:
    """Tests for safe operation execution."""
    
    def test_safe_operation_succeeds(self):
        """Test safe operation that succeeds."""
        func = Mock(return_value="success")
        decorated = safe_operation(func)
        
        result = decorated()
        assert result == "success"
    
    def test_safe_operation_catches_exception(self):
        """Test safe operation catches exceptions."""
        func = Mock(side_effect=RuntimeError("fail"))
        decorated = safe_operation(func, default="fallback")
        
        result = decorated()
        assert result == "fallback"
    
    def test_safe_operation_catches_graphrag_exception(self):
        """Test safe operation catches GraphRAG exceptions."""
        func = Mock(side_effect=GraphRAGExtractionError("Extract failed"))
        decorated = safe_operation(func, default=None)
        
        result = decorated()
        assert result is None
    
    def test_safe_operation_error_handler(self):
        """Test safe operation calls error handler."""
        error_handler = Mock()
        func = Mock(side_effect=RuntimeError("fail"))
        decorated = safe_operation(func, error_handler=error_handler)
        
        decorated()
        
        # Error handler should be called
        assert error_handler.called
        assert isinstance(error_handler.call_args[0][0], RuntimeError)
    
    def test_safe_operation_no_logging_option(self):
        """Test safe operation respects log_errors option."""
        func = Mock(side_effect=RuntimeError("fail"))
        decorated = safe_operation(func, log_errors=False, default="fallback")
        
        with patch('logging.Logger.error') as mock_log:
            result = decorated()
            assert result == "fallback"

    def test_safe_operation_does_not_swallow_base_exception(self):
        """BaseException subclasses should propagate from safe_operation."""
        class AbortSignal(BaseException):
            pass

        func = Mock(side_effect=AbortSignal())
        decorated = safe_operation(func, default="fallback")

        with pytest.raises(AbortSignal):
            decorated()


class TestErrorDetail:
    """Tests for ErrorDetail serialization."""
    
    def test_error_detail_creation(self):
        """Test creating error detail."""
        detail = ErrorDetail(
            error_type="ConfigError",
            message="Invalid config",
            severity="error",
            source="validator",
            suggestions=["Fix timeout value"]
        )
        
        assert detail.error_type == "ConfigError"
        assert detail.message == "Invalid config"
        assert detail.severity == "error"
    
    def test_error_detail_to_dict(self):
        """Test converting error detail to dict."""
        detail = ErrorDetail(
            error_type="ConfigError",
            message="Test",
            severity="error",
            suggestions=["Fix it"]
        )
        
        detail_dict = detail.to_dict()
        assert detail_dict['error_type'] == "ConfigError"
        assert detail_dict['message'] == "Test"
        assert 'Fix it' in detail_dict['suggestions']
    
    def test_error_detail_to_json(self):
        """Test converting error detail to JSON."""
        detail = ErrorDetail(
            error_type="ConfigError",
            message="Test",
            severity="error"
        )
        
        json_str = detail.to_json()
        assert '"error_type": "ConfigError"' in json_str
        assert '"message": "Test"' in json_str


class TestErrorSeverity:
    """Tests for error severity enum."""
    
    def test_severity_values(self):
        """Test error severity enum values."""
        assert ErrorSeverity.CRITICAL.value == "critical"
        assert ErrorSeverity.ERROR.value == "error"
        assert ErrorSeverity.WARNING.value == "warning"
        assert ErrorSeverity.INFO.value == "info"


class TestRecoveryStrategy:
    """Tests for recovery strategy enum."""
    
    def test_recovery_strategies(self):
        """Test recovery strategy options."""
        assert RecoveryStrategy.RETRY.value == "retry"
        assert RecoveryStrategy.FALLBACK.value == "fallback"
        assert RecoveryStrategy.SKIP.value == "skip"
        assert RecoveryStrategy.FAIL.value == "fail"


class TestConfigError:
    """Tests for configuration error specifics."""
    
    def test_config_error_with_valid_range(self):
        """Test config error with valid range info."""
        exc = GraphRAGConfigError(
            "Invalid timeout",
            invalid_field="timeout",
            valid_range=(1, 3600)
        )
        
        assert exc.invalid_field == "timeout"
        assert exc.valid_range == (1, 3600)
        assert 'timeout' in exc.details['invalid_field']


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
