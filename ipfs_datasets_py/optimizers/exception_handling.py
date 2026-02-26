"""Batch 329: Exception Handling Improvements Implementation

Provides structured exception types and handling utilities.
Replaces bare except clauses with specific, classifiable exceptions.

Usage:
    from .exception_handling import (
        RetriableException,
        TransientException,
        ValidationException,
        FatalException,
    )
    
    try:
        # operation
        pass
    except ConnectionError as e:
        raise TransientException("Network error", original_exception=e)
    except ValueError as e:
        raise ValidationException("Invalid input", field_name="user_id")

"""

from typing import Any, Dict, Optional, Type
from enum import Enum
from dataclasses import dataclass, field


class ExceptionSeverity(Enum):
    """Severity level of exceptions."""
    CRITICAL = "critical"  # System-level, unrecoverable failure
    ERROR = "error"  # Operation failure
    WARNING = "warning"  # Degraded functionality
    INFO = "info"  # Notable event


class ExceptionCategory(Enum):
    """Category of exception for handling strategy."""
    RETRIABLE = "retriable"  # Retry might succeed
    TRANSIENT = "transient"  # Temporary condition (timeout, network)
    VALIDATION = "validation"  # Invalid input/config
    FATAL = "fatal"  # Operation cannot proceed


@dataclass
class ExceptionMetadata:
    """Metadata for exception context and recovery."""
    severity: ExceptionSeverity
    category: ExceptionCategory
    exception_type: Type[Exception]
    context_data: Dict[str, Any] = field(default_factory=dict)
    original_exception: Optional[Exception] = None
    
    @property
    def is_retriable(self) -> bool:
        """Whether exception allows retry."""
        return self.category in (ExceptionCategory.RETRIABLE, ExceptionCategory.TRANSIENT)
    
    @property
    def is_client_error(self) -> bool:
        """Whether this is a client-side error (validation)."""
        return self.category == ExceptionCategory.VALIDATION
    
    @property
    def is_server_error(self) -> bool:
        """Whether this is a server/system error."""
        return self.category in (ExceptionCategory.TRANSIENT, ExceptionCategory.FATAL)


class StructuredException(Exception):
    """Base class for structured exceptions with context.
    
    Provides consistent metadata, logging support, and context preservation.
    """
    
    severity: ExceptionSeverity = ExceptionSeverity.ERROR
    category: ExceptionCategory = ExceptionCategory.FATAL
    
    def __init__(
        self,
        message: str,
        severity: Optional[ExceptionSeverity] = None,
        category: Optional[ExceptionCategory] = None,
        context: Optional[Dict[str, Any]] = None,
        original_exception: Optional[Exception] = None,
    ):
        """Initialize structured exception.
        
        Args:
            message: Human-readable error message
            severity: Custom severity level
            category: Exception category (retriable, transient, etc)
            context: Additional context data (operation, file, line, etc)
            original_exception: Original exception being wrapped
        """
        self.message = message
        self.severity = severity or self.__class__.severity
        self.category = category or self.__class__.category
        self.context = context or {}
        self.original_exception = original_exception
        super().__init__(self.message)
    
    def __str__(self) -> str:
        """Format exception with severity and context."""
        parts = [f"[{self.severity.value.upper()}] {self.message}"]
        if self.context:
            context_str = ", ".join(f"{k}={v}" for k, v in self.context.items())
            parts.append(f"({context_str})")
        if self.original_exception:
            parts.append(f"→ {type(self.original_exception).__name__}")
        return " ".join(parts)
    
    def get_metadata(self) -> ExceptionMetadata:
        """Get structured metadata for logging/handling."""
        return ExceptionMetadata(
            severity=self.severity,
            category=self.category,
            exception_type=type(self),
            context_data=self.context,
            original_exception=self.original_exception,
        )


class RetriableException(StructuredException):
    """Exception that might succeed if retried.
    
    Use for operations that failed transiently and should be retried with
    backoff. Examples: rate limiting, momentary resource unavailability.
    """
    
    severity = ExceptionSeverity.WARNING
    category = ExceptionCategory.RETRIABLE
    
    def __init__(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        original_exception: Optional[Exception] = None,
    ):
        """Initialize retriable exception."""
        super().__init__(
            message,
            severity=self.severity,
            category=self.category,
            context=context,
            original_exception=original_exception,
        )


class TransientException(StructuredException):
    """Exception from temporary/transient conditions.
    
    Use for network timeouts, temporary service unavailability, and other
    conditions that are likely to resolve if retried. Different from RetriableException
    in that it's not necessarily due to rate limiting or resource exhaustion.
    """
    
    severity = ExceptionSeverity.WARNING
    category = ExceptionCategory.TRANSIENT
    
    def __init__(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        original_exception: Optional[Exception] = None,
    ):
        """Initialize transient exception."""
        super().__init__(
            message,
            severity=self.severity,
            category=self.category,
            context=context,
            original_exception=original_exception,
        )


class ValidationException(StructuredException):
    """Exception for invalid input or configuration.
    
    Use when user-provided data or config fails validation. Client is responsible
    for fixing the input. These are not retriable by the system.
    """
    
    severity = ExceptionSeverity.ERROR
    category = ExceptionCategory.VALIDATION
    
    def __init__(
        self,
        message: str,
        field_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        """Initialize validation exception.
        
        Args:
            message: Error description
            field_name: Name of field that failed validation
            context: Additional context (value, constraints, etc)
        """
        if field_name:
            message = f"{message} (field: {field_name})"
        
        context = context or {}
        if field_name and field_name not in context:
            context["field"] = field_name
        
        super().__init__(
            message,
            severity=self.severity,
            category=self.category,
            context=context,
        )


class FatalException(StructuredException):
    """Exception indicating fatal, unrecoverable error.
    
    Use for system-level failures where retry won't help (database corruption,
    permission denied, etc). These require operator intervention to resolve.
    """
    
    severity = ExceptionSeverity.CRITICAL
    category = ExceptionCategory.FATAL
    
    def __init__(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        original_exception: Optional[Exception] = None,
    ):
        """Initialize fatal exception."""
        super().__init__(
            message,
            severity=self.severity,
            category=self.category,
            context=context,
            original_exception=original_exception,
        )


class ExceptionHandler:
    """Handler dispatcher for exceptions.
    
    Matches exceptions to specific handlers and applies recovery strategies.
    Enables consistent exception handling across modules.
    """
    
    def __init__(self):
        """Initialize exception handler."""
        self.handlers: Dict[Type[Exception], callable] = {}
    
    def register(self, exc_type: Type[Exception], handler: callable) -> None:
        """Register handler for exception type.
        
        Args:
            exc_type: Exception class to handle
            handler: Callable(exc) -> Any
        """
        self.handlers[exc_type] = handler
    
    def handle(self, exc: Exception) -> Any:
        """Find and apply appropriate handler.
        
        Args:
            exc: Exception to handle
            
        Returns:
            Result from handler
            
        Raises:
            Exception: If no handler registered and reraise=True
        """
        # Check exact type first
        if type(exc) in self.handlers:
            return self.handlers[type(exc)](exc)
        
        # Check inheritance chain
        for exc_type, handler in self.handlers.items():
            if isinstance(exc, exc_type):
                return handler(exc)
        
        # No handler found
        raise exc


def wrap_exception(
    exc: Exception,
    message: Optional[str] = None,
    category: ExceptionCategory = ExceptionCategory.FATAL,
) -> StructuredException:
    """Wrap native exception as structured exception.
    
    Args:
        exc: Original exception
        message: Custom message (uses str(exc) if None)
        category: Exception category
        
    Returns:
        Wrapped StructuredException with original as cause
    """
    msg = message or str(exc)
    
    if category == ExceptionCategory.VALIDATION:
        return ValidationException(msg, original_exception=exc)
    elif category == ExceptionCategory.RETRIABLE:
        return RetriableException(msg, original_exception=exc)
    elif category == ExceptionCategory.TRANSIENT:
        return TransientException(msg, original_exception=exc)
    else:
        return FatalException(msg, original_exception=exc)


def classify_exception(exc: Exception) -> ExceptionCategory:
    """Classify exception for handling strategy.
    
    Args:
        exc: Exception to classify
        
    Returns:
        ExceptionCategory enum value
    """
    # Network/transient exceptions
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return ExceptionCategory.TRANSIENT
    
    # Validation exceptions
    if isinstance(exc, (ValueError, TypeError, KeyError, AttributeError)):
        return ExceptionCategory.VALIDATION
    
    # File system exceptions
    if isinstance(exc, FileNotFoundError):
        return ExceptionCategory.VALIDATION
    if isinstance(exc, (PermissionError, IsADirectoryError)):
        return ExceptionCategory.FATAL
    
    # Permission/auth exceptions
    if isinstance(exc, (PermissionError, RuntimeError)):
        return ExceptionCategory.FATAL
    
    # Retriable on specific conditions
    if isinstance(exc, RuntimeError) and "resource" in str(exc).lower():
        return ExceptionCategory.RETRIABLE
    
    # Default to fatal
    return ExceptionCategory.FATAL


def should_retry(exc: Exception, retry_count: int = 0, max_retries: int = 3) -> bool:
    """Determine if exception should be retried.
    
    Args:
        exc: Exception to evaluate
        retry_count: Current retry attempt number
        max_retries: Maximum retries allowed
        
    Returns:
        Whether operation should be retried
    """
    if retry_count >= max_retries:
        return False
    
    category = classify_exception(exc)
    return category in (ExceptionCategory.RETRIABLE, ExceptionCategory.TRANSIENT)


def get_retry_delay(retry_count: int, base_delay: float = 0.1, backoff: float = 2.0) -> float:
    """Calculate exponential backoff delay for retry.
    
    Args:
        retry_count: Which retry attempt (0-based)
        base_delay: Initial delay in seconds
        backoff: Multiply factor per retry
        
    Returns:
        Delay in seconds before next retry
    """
    return base_delay * (backoff ** retry_count)
