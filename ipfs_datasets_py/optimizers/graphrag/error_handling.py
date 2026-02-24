"""
Unified error handling and exception utilities for the GraphRAG optimization system.

This module provides a consistent, hierarchical exception structure and utilities
for error handling across all GraphRAG components. Features include:
- Hierarchical exception classes for different error categories
- Context-preserving error wrapping with stack trace preservation
- Error recovery strategies and retry mechanisms
- Error reporting and logging utilities
- Error serialization for API responses

Exception Hierarchy:
    GraphRAGException (base)
    ├── GraphRAGConfigError
    ├── GraphRAGExtractionError
    ├── GraphRAGOptimizationError
    │   ├── GraphRAGConvergenceError
    │   └── GraphRAGResourceError
    ├── GraphRAGQueryError
    ├── GraphRAGValidationError
    └── GraphRAGIntegrationError

Usage:
    try:
        result = process_ontology(config)
    except GraphRAGValidationError as e:
        logger.error(f"Validation failed: {e.message}", extra=e.to_dict())
        handle_validation_error(e)
    except GraphRAGExtractionError as e:
        logger.warning(f"Extraction partially failed: {e.details}")
        # Attempt recovery or fallback

Examples:
    >>> try:
    ...     validate_config(config)
    ... except GraphRAGConfigError as e:
    ...     print(f"Config error at {e.source}: {e.message}")
    ...     if e.suggestions:
    ...         print(f"Suggestions: {e.suggestions}")
    
    >>> with error_context("entity_extraction", entity_id="e1"):
    ...     extract_entities(document)
"""

from typing import (
    Any, Dict, List, Optional, Callable, Type, TypeVar, Union, 
    Tuple, Generic, Protocol
)
from datetime import datetime
from abc import abstractmethod, ABC
import traceback
import logging
import json
from enum import Enum
from dataclasses import dataclass, field, asdict
import functools
import time


logger = logging.getLogger(__name__)
T = TypeVar('T')


class ErrorSeverity(Enum):
    """Severity levels for errors."""
    CRITICAL = "critical"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class RecoveryStrategy(Enum):
    """Strategies for error recovery."""
    RETRY = "retry"
    FALLBACK = "fallback"
    SKIP = "skip"
    FAIL = "fail"


@dataclass
class ErrorContext:
    """Context information for an error."""
    operation: str
    component: str = ""
    entity_id: Optional[str] = None
    additional_info: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class ErrorDetail:
    """Detailed error information for serialization."""
    error_type: str
    message: str
    severity: str
    source: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    suggestions: Optional[List[str]] = None
    details: Optional[Dict[str, Any]] = None
    traceback_str: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)
    
    def to_json(self) -> str:
        """Convert to JSON for API responses."""
        return json.dumps(self.to_dict())


class GraphRAGException(Exception):
    """Base exception for all GraphRAG operations.
    
    Attributes:
        message: Human-readable error message
        source: Source component or function that raised the error
        severity: Error severity level
        context: Error context information
        suggestions: List of suggested actions or fixes
        details: Additional error details
        original_exception: Original exception if this is a wrap
    """
    
    def __init__(
        self,
        message: str,
        source: Optional[str] = None,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        context: Optional[ErrorContext] = None,
        suggestions: Optional[List[str]] = None,
        details: Optional[Dict[str, Any]] = None,
        original_exception: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.message = message
        self.source = source
        self.severity = severity
        self.context = context or ErrorContext(operation="unknown")
        self.suggestions = suggestions or []
        self.details = details or {}
        self.original_exception = original_exception
        self.timestamp = datetime.now().isoformat()
        self.traceback_str = traceback.format_exc() if original_exception else None
    
    def __str__(self) -> str:
        """String representation of the exception."""
        parts = [f"[{self.severity.value.upper()}]", self.message]
        if self.source:
            parts.append(f"(source: {self.source})")
        if self.suggestions:
            parts.append(f"Suggestions: {'; '.join(self.suggestions)}")
        return " ".join(parts)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging and serialization."""
        context_dict = None
        if self.context:
            context_dict = self.context.to_dict() if hasattr(self.context, 'to_dict') else asdict(self.context)
        return {
            'error_type': self.__class__.__name__,
            'message': self.message,
            'source': self.source,
            'severity': self.severity.value,
            'context': context_dict,
            'suggestions': self.suggestions,
            'details': self.details,
            'timestamp': self.timestamp,
        }
    
    def to_error_detail(self) -> ErrorDetail:
        """Convert to ErrorDetail dataclass."""
        context_dict = None
        if self.context:
            context_dict = self.context.to_dict() if hasattr(self.context, 'to_dict') else asdict(self.context)
        return ErrorDetail(
            error_type=self.__class__.__name__,
            message=self.message,
            severity=self.severity.value,
            source=self.source,
            context=context_dict,
            suggestions=self.suggestions,
            details=self.details,
            traceback_str=self.traceback_str,
        )


class GraphRAGConfigError(GraphRAGException):
    """Configuration validation error.
    
    Raised when configuration is invalid, missing required fields, or
    contains values outside acceptable ranges.
    """
    
    def __init__(
        self,
        message: str,
        invalid_field: Optional[str] = None,
        valid_range: Optional[Tuple[Any, Any]] = None,
        **kwargs
    ):
        self.invalid_field = invalid_field
        self.valid_range = valid_range
        details = kwargs.get('details', {})
        if invalid_field:
            details['invalid_field'] = invalid_field
        if valid_range:
            details['valid_range'] = str(valid_range)
        kwargs['details'] = details
        super().__init__(message, severity=ErrorSeverity.ERROR, **kwargs)


class GraphRAGExtractionError(GraphRAGException):
    """Entity/relationship extraction error.
    
    Raised during entity or relationship extraction, including parsing,
    type inference, or LLM integration issues.
    """
    
    def __init__(
        self,
        message: str,
        failed_extractions: Optional[List[str]] = None,
        partial_result: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        self.failed_extractions = failed_extractions or []
        self.partial_result = partial_result
        details = kwargs.get('details', {})
        details['failed_count'] = len(self.failed_extractions)
        if partial_result:
            details['partial_result_available'] = True
        kwargs['details'] = details
        super().__init__(message, severity=ErrorSeverity.WARNING, **kwargs)


class GraphRAGOptimizationError(GraphRAGException):
    """Optimization process error.
    
    Raised during ontology optimization cycles, including convergence issues,
    resource exhaustion, or invalid state transitions.
    """
    
    def __init__(
        self,
        message: str,
        iteration: Optional[int] = None,
        best_score: Optional[float] = None,
        **kwargs
    ):
        self.iteration = iteration
        self.best_score = best_score
        details = kwargs.get('details', {})
        if iteration is not None:
            details['iteration'] = iteration
        if best_score is not None:
            details['best_score'] = best_score
        kwargs['details'] = details
        super().__init__(message, severity=ErrorSeverity.ERROR, **kwargs)


class GraphRAGConvergenceError(GraphRAGOptimizationError):
    """Optimization convergence error.
    
    Raised when optimization fails to converge within iteration/time limits
    or resource constraints.
    """
    pass


class GraphRAGResourceError(GraphRAGOptimizationError):
    """Resource constraint error.
    
    Raised when resource limits (memory, computation time, API quota) are exceeded
    during optimization.
    """
    
    def __init__(
        self,
        message: str,
        resource_type: str,
        limit: Optional[float] = None,
        used: Optional[float] = None,
        **kwargs
    ):
        self.resource_type = resource_type
        self.limit = limit
        self.used = used
        details = kwargs.get('details', {})
        details['resource_type'] = resource_type
        if limit is not None:
            details['limit'] = limit
        if used is not None:
            details['used'] = used
        kwargs['details'] = details
        super().__init__(message, **kwargs)


class GraphRAGQueryError(GraphRAGException):
    """Query execution error.
    
    Raised during query planning or execution failures.
    """
    
    def __init__(
        self,
        message: str,
        query: Optional[str] = None,
        execution_plan: Optional[str] = None,
        **kwargs
    ):
        self.query = query
        self.execution_plan = execution_plan
        details = kwargs.get('details', {})
        if query:
            details['query'] = query
        if execution_plan:
            details['execution_plan'] = execution_plan
        kwargs['details'] = details
        super().__init__(message, **kwargs)


class GraphRAGValidationError(GraphRAGException):
    """Data validation error.
    
    Raised when extracted or processed data fails schema or constraint validation.
    """
    
    def __init__(
        self,
        message: str,
        validation_errors: Optional[List[str]] = None,
        **kwargs
    ):
        self.validation_errors = validation_errors or []
        details = kwargs.get('details', {})
        details['validation_error_count'] = len(self.validation_errors)
        kwargs['details'] = details
        super().__init__(message, **kwargs)


class GraphRAGIntegrationError(GraphRAGException):
    """External system integration error.
    
    Raised when integration with LLM APIs, vector databases, or other
    external systems fails.
    """
    
    def __init__(
        self,
        message: str,
        external_system: str,
        http_status: Optional[int] = None,
        **kwargs
    ):
        self.external_system = external_system
        self.http_status = http_status
        details = kwargs.get('details', {})
        details['external_system'] = external_system
        if http_status:
            details['http_status'] = http_status
        kwargs['details'] = details
        super().__init__(message, severity=ErrorSeverity.WARNING, **kwargs)


class ErrorContext:
    """Context manager for tracking error context during operations."""
    
    _stack: List[ErrorContext] = []
    
    def __init__(self, operation: str, **kwargs):
        self.operation = operation
        self.component = kwargs.pop('component', '')
        self.entity_id = kwargs.pop('entity_id', None)
        self.additional_info = kwargs
        self.timestamp = datetime.now().isoformat()
    
    def __enter__(self):
        ErrorContext._stack.append(self)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if ErrorContext._stack and ErrorContext._stack[-1] is self:
            ErrorContext._stack.pop()
        return False
    
    @classmethod
    def current(cls) -> Optional['ErrorContext']:
        """Get current error context."""
        return cls._stack[-1] if cls._stack else None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'operation': self.operation,
            'component': self.component,
            'entity_id': self.entity_id,
            'additional_info': self.additional_info,
            'timestamp': self.timestamp,
        }


def error_context(operation: str, **kwargs) -> ErrorContext:
    """Create an error context.
    
    Usage:
        with error_context("extraction", entity_id="e1"):
            result = extract_entity(data)
    """
    return ErrorContext(operation, **kwargs)


def wrap_exception(
    exception: Exception,
    error_class: Type[GraphRAGException] = GraphRAGException,
    message: Optional[str] = None,
    **kwargs
) -> GraphRAGException:
    """Wrap an exception with GraphRAG exception.
    
    Preserves original exception while providing additional context.
    """
    wrapped_message = message or str(exception)
    context = error_context.current() if hasattr(error_context, 'current') else None
    kwargs['context'] = context
    kwargs['original_exception'] = exception
    return error_class(wrapped_message, **kwargs)


def retry_with_backoff(
    func: Callable[..., T],
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
) -> Callable[..., T]:
    """Decorator for retrying function with exponential backoff.
    
    Args:
        func: Function to retry
        max_attempts: Maximum retry attempts
        initial_delay: Initial delay between retries (seconds)
        backoff_factor: Multiplier for delay between retries
        exceptions: Tuple of exceptions to catch and retry on
        
    Returns:
        Decorated function with retry logic
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> T:
        delay = initial_delay
        last_exception = None
        func_name = getattr(func, '__name__', 'unknown_function')
        
        for attempt in range(max_attempts):
            try:
                return func(*args, **kwargs)
            except exceptions as e:
                last_exception = e
                if attempt < max_attempts - 1:
                    logger.warning(
                        f"Attempt {attempt + 1}/{max_attempts} failed, "
                        f"retrying in {delay}s: {e}"
                    )
                    time.sleep(delay)
                    delay *= backoff_factor
                else:
                    logger.error(
                        f"All {max_attempts} attempts failed for {func_name}"
                    )
        
        raise wrap_exception(
            last_exception,
            GraphRAGException,
            f"Failed after {max_attempts} attempts: {last_exception}"
        )
    
    return wrapper


def safe_operation(
    func: Callable[..., T],
    default: Optional[T] = None,
    log_errors: bool = True,
    error_handler: Optional[Callable[[Exception], None]] = None,
) -> Callable[..., Optional[T]]:
    """Decorator for safe operation execution with error handling.
    
    Args:
        func: Function to execute safely
        default: Default value to return on error
        log_errors: Whether to log errors
        error_handler: Optional callback for error handling
        
    Returns:
        Decorated function that handles errors gracefully
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> Optional[T]:
        func_name = getattr(func, '__name__', 'unknown_function')
        try:
            return func(*args, **kwargs)
        except GraphRAGException as e:
            if log_errors:
                logger.error(f"GraphRAG error in {func_name}: {e}")
            if error_handler:
                error_handler(e)
            return default
        except Exception as e:
            if log_errors:
                logger.exception(f"Unexpected error in {func_name}: {e}")
            if error_handler:
                error_handler(e)
            return default
    
    return wrapper


if __name__ == '__main__':
    # Example usage
    try:
        with error_context("test_operation", entity_id="e1"):
            raise GraphRAGExtractionError(
                "Failed to extract entities",
                suggestions=["Check input format", "Verify API credentials"],
                details={"processed": 100, "failed": 5}
            )
    except GraphRAGExtractionError as e:
        print(f"Error: {e}")
        print(f"Details: {e.to_dict()}")
