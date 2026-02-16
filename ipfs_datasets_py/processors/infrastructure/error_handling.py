"""
Error handling utilities for processors.

This module provides enhanced error handling with classification, retry logic,
and circuit breaker patterns for robust processor operation.
"""

from __future__ import annotations

import anyio
import logging
import threading
from enum import Enum
from typing import Optional, Callable, Any, TypeVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

T = TypeVar('T')


class ErrorClassification(Enum):
    """
    Classification of errors for intelligent handling.
    
    - TRANSIENT: Temporary failures (network timeout, service unavailable)
    - PERMANENT: Permanent failures (invalid input, unsupported format)
    - RESOURCE: Resource exhaustion (out of memory, disk space)
    - DEPENDENCY: Missing dependencies (API key, external service)
    - UNKNOWN: Unclassified errors
    """
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    RESOURCE = "resource"
    DEPENDENCY = "dependency"
    UNKNOWN = "unknown"


class ProcessorError(Exception):
    """
    Base exception for processor errors with classification.
    
    Attributes:
        message: Error message
        classification: Error classification for handling strategy
        original_error: Original exception if wrapping another error
        suggestions: List of recovery suggestions
    """
    
    def __init__(
        self,
        message: str,
        classification: ErrorClassification = ErrorClassification.UNKNOWN,
        original_error: Optional[Exception] = None,
        suggestions: Optional[list[str]] = None
    ):
        super().__init__(message)
        self.classification = classification
        self.original_error = original_error
        self.suggestions = suggestions or []
    
    def __str__(self) -> str:
        msg = f"[{self.classification.value}] {super().__str__()}"
        if self.suggestions:
            msg += f"\nSuggestions:\n" + "\n".join(f"  - {s}" for s in self.suggestions)
        return msg


class TransientError(ProcessorError):
    """Error that may succeed if retried (network issues, temporary unavailability)."""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, ErrorClassification.TRANSIENT, **kwargs)


class PermanentError(ProcessorError):
    """Error that will not succeed even if retried (invalid input, unsupported format)."""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, ErrorClassification.PERMANENT, **kwargs)


class ResourceError(ProcessorError):
    """Error due to resource exhaustion (memory, disk space, etc)."""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, ErrorClassification.RESOURCE, **kwargs)


class DependencyError(ProcessorError):
    """Error due to missing dependencies or external services."""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, ErrorClassification.DEPENDENCY, **kwargs)


@dataclass
class RetryConfig:
    """
    Configuration for retry logic.
    
    Attributes:
        max_retries: Maximum number of retry attempts
        initial_backoff: Initial backoff delay in seconds
        max_backoff: Maximum backoff delay in seconds
        backoff_multiplier: Multiplier for exponential backoff
        retry_on: Error classifications to retry
    """
    max_retries: int = 3
    initial_backoff: float = 1.0
    max_backoff: float = 60.0
    backoff_multiplier: float = 2.0
    retry_on: set[ErrorClassification] = field(default_factory=lambda: {
        ErrorClassification.TRANSIENT,
        ErrorClassification.UNKNOWN
    })


@dataclass
class CircuitBreakerConfig:
    """
    Configuration for circuit breaker pattern.
    
    Attributes:
        failure_threshold: Number of failures before opening circuit
        success_threshold: Number of successes to close circuit
        timeout_seconds: Time to wait before attempting recovery
    """
    failure_threshold: int = 5
    success_threshold: int = 2
    timeout_seconds: float = 60.0


class CircuitBreakerState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Too many failures, rejecting requests
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreaker:
    """
    Circuit breaker to prevent cascading failures.
    
    When a processor fails repeatedly, the circuit breaker "opens" and
    rejects requests without trying, allowing the service to recover.
    
    Thread-safe for concurrent access.
    """
    config: CircuitBreakerConfig
    state: CircuitBreakerState = CircuitBreakerState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: Optional[datetime] = None
    _lock: threading.Lock = None
    
    def __post_init__(self):
        """Initialize thread lock."""
        if self._lock is None:
            object.__setattr__(self, '_lock', threading.Lock())
    
    def should_allow_request(self) -> bool:
        """Check if request should be allowed (thread-safe)."""
        with self._lock:
            if self.state == CircuitBreakerState.CLOSED:
                return True
            elif self.state == CircuitBreakerState.OPEN:
                # Check if timeout has elapsed
                if self.last_failure_time:
                    elapsed = (datetime.now() - self.last_failure_time).total_seconds()
                    if elapsed >= self.config.timeout_seconds:
                        self.state = CircuitBreakerState.HALF_OPEN
                        self.success_count = 0
                        logger.info("Circuit breaker entering HALF_OPEN state")
                        return True
                return False
            else:  # HALF_OPEN
                return True
    
    def record_success(self):
        """Record successful operation (thread-safe)."""
        with self._lock:
            if self.state == CircuitBreakerState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= self.config.success_threshold:
                    self.state = CircuitBreakerState.CLOSED
                    self.failure_count = 0
                    logger.info("Circuit breaker CLOSED after successful recovery")
            elif self.state == CircuitBreakerState.CLOSED:
                self.failure_count = max(0, self.failure_count - 1)
    
    def record_failure(self):
        """Record failed operation (thread-safe)."""
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = datetime.now()
            
            if self.state == CircuitBreakerState.HALF_OPEN:
                self.state = CircuitBreakerState.OPEN
                logger.warning("Circuit breaker re-OPENED due to failure in HALF_OPEN state")
            elif self.state == CircuitBreakerState.CLOSED:
                if self.failure_count >= self.config.failure_threshold:
                    self.state = CircuitBreakerState.OPEN
                    logger.error(
                        f"Circuit breaker OPENED after {self.failure_count} failures"
                    )


class RetryWithBackoff:
    """
    Retry mechanism with exponential backoff.
    
    Provides intelligent retry logic that:
    - Classifies errors
    - Retries only appropriate error types
    - Uses exponential backoff
    - Respects circuit breakers
    """
    
    def __init__(
        self,
        config: Optional[RetryConfig] = None,
        circuit_breaker: Optional[CircuitBreaker] = None
    ):
        self.config = config or RetryConfig()
        self.circuit_breaker = circuit_breaker
    
    async def execute(
        self,
        func: Callable[..., Any],
        *args,
        **kwargs
    ) -> Any:
        """
        Execute function with retry logic.
        
        Args:
            func: Async function to execute
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func
            
        Returns:
            Result of successful function execution
            
        Raises:
            ProcessorError: If all retries exhausted or non-retriable error
        """
        # Check circuit breaker
        if self.circuit_breaker and not self.circuit_breaker.should_allow_request():
            raise ProcessorError(
                "Circuit breaker is OPEN - requests are being rejected",
                classification=ErrorClassification.TRANSIENT,
                suggestions=[
                    f"Wait {self.circuit_breaker.config.timeout_seconds}s for circuit to recover",
                    "Check processor health before retrying"
                ]
            )
        
        backoff = self.config.initial_backoff
        last_error = None
        
        for attempt in range(self.config.max_retries + 1):
            try:
                result = await func(*args, **kwargs)
                
                # Record success
                if self.circuit_breaker:
                    self.circuit_breaker.record_success()
                
                if attempt > 0:
                    logger.info(f"Operation succeeded after {attempt} retries")
                
                return result
                
            except ProcessorError as e:
                last_error = e
                
                # Record failure
                if self.circuit_breaker:
                    self.circuit_breaker.record_failure()
                
                # Don't retry if error classification is not retriable
                if e.classification not in self.config.retry_on:
                    logger.debug(f"Not retrying {e.classification.value} error")
                    raise
                
                # Don't retry if this was the last attempt
                if attempt >= self.config.max_retries:
                    logger.error(f"Max retries ({self.config.max_retries}) exhausted")
                    raise
                
                # Log retry
                logger.warning(
                    f"Attempt {attempt + 1}/{self.config.max_retries + 1} failed: {e}. "
                    f"Retrying in {backoff:.1f}s..."
                )
                
                # Wait with backoff
                await anyio.sleep(backoff)
                backoff = min(backoff * self.config.backoff_multiplier, self.config.max_backoff)
                
            except Exception as e:
                # Wrap non-ProcessorError exceptions
                last_error = ProcessorError(
                    f"Unexpected error: {str(e)}",
                    classification=ErrorClassification.UNKNOWN,
                    original_error=e
                )
                
                if self.circuit_breaker:
                    self.circuit_breaker.record_failure()
                
                # Retry unknown errors
                if attempt >= self.config.max_retries:
                    raise last_error
                
                logger.warning(
                    f"Attempt {attempt + 1}/{self.config.max_retries + 1} failed with unexpected error. "
                    f"Retrying in {backoff:.1f}s..."
                )
                
                await anyio.sleep(backoff)
                backoff = min(backoff * self.config.backoff_multiplier, self.config.max_backoff)
        
        # Should not reach here, but just in case
        if last_error:
            raise last_error
        raise ProcessorError("Retry logic error - no result and no error")


def classify_exception(exception: Exception) -> ErrorClassification:
    """
    Classify an exception to determine handling strategy.
    
    Args:
        exception: Exception to classify
        
    Returns:
        ErrorClassification enum value
    """
    if isinstance(exception, ProcessorError):
        return exception.classification
    
    # Network/IO errors are usually transient
    if isinstance(exception, (TimeoutError, ConnectionError, IOError)):
        return ErrorClassification.TRANSIENT
    
    # Memory errors are resource issues
    if isinstance(exception, MemoryError):
        return ErrorClassification.RESOURCE
    
    # Import errors are dependency issues
    if isinstance(exception, ImportError):
        return ErrorClassification.DEPENDENCY
    
    # Value/Type errors are usually permanent
    if isinstance(exception, (ValueError, TypeError, KeyError)):
        return ErrorClassification.PERMANENT
    
    # Default to unknown
    return ErrorClassification.UNKNOWN
