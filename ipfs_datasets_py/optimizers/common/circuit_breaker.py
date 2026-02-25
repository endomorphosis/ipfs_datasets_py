"""Circuit-breaker pattern for LLM backend calls with exponential backoff.

Provides resilience to transient failures and helps prevent cascading failures
by temporarily disabling calls to failing services.

The circuit-breaker has three states:
- CLOSED: Normal operation, calls pass through
- OPEN: Too many failures, calls are rejected immediately  
- HALF_OPEN: Testing if service recovered, limited calls allowed

Examples:
    Wrap an LLM backend call:

        breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60,
            name="llm_backend"
        )
        
        @breaker.call
        def my_llm_call(prompt: str) -> str:
            return llm_backend.generate(prompt)
        
        try:
            result = my_llm_call("Some prompt")
        except CircuitBreakerOpen:
            print("LLM backend is currently unavailable")
"""

import logging
import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, Optional, TypeVar

_logger = logging.getLogger(__name__)

T = TypeVar('T')


class CircuitState(str, Enum):
    """States of the circuit-breaker."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject calls
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreakerOpen(Exception):
    """Raised when circuit is OPEN and calls are rejected."""

    def __init__(self, service_name: str, recovery_time: float):
        """Initialize exception.
        
        Args:
            service_name: Name of the blocked service
            recovery_time: Time until next recovery attempt (seconds)
        """
        self.service_name = service_name
        self.recovery_time = recovery_time
        super().__init__(
            f"Circuit breaker for '{service_name}' is OPEN. "
            f"Service unavailable for ~{recovery_time:.1f}s"
        )


@dataclass
class CircuitBreakerMetrics:
    """Metrics tracking circuit breaker behavior."""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0  # Calls rejected while OPEN
    state_changes: int = 0
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        if self.total_calls == 0:
            return 0.0
        return 100.0 * self.successful_calls / self.total_calls
    
    @property
    def failure_rate(self) -> float:
        """Calculate failure rate as percentage."""
        if self.total_calls == 0:
            return 0.0
        return 100.0 * self.failed_calls / self.total_calls


class CircuitBreaker(Generic[T]):
    """Circuit-breaker pattern for resilient function calls.
    
    Helps handle transient failures in external services by:
    - Tracking failure rates
    - Temporarily rejecting calls when failure threshold exceeded
    - Allowing recovery testing in HALF_OPEN state
    - Providing metrics about circuit behavior
    
    Attributes:
        name: Identifier for this circuit breaker
        failure_threshold: Number of failures before opening circuit
        recovery_timeout: Seconds to wait before testing recovery
        expected_exception: Exception type(s) that count as failures
    """
    
    def __init__(
        self,
        name: str = "circuit_breaker",
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: type[BaseException] | tuple[type[BaseException], ...] = Exception,
    ):
        """Initialize circuit-breaker.
        
        Args:
            name: Name for logging and identification
            failure_threshold: Number of failures before OPEN
            recovery_timeout: Seconds between OPEN and HALF_OPEN
            expected_exception: Exception(s) to treat as failures
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: Optional[float] = None
        self._opened_at: Optional[float] = None
        self._metrics = CircuitBreakerMetrics()
    
    @property
    def state(self) -> CircuitState:
        """Get current circuit state, updating if needed."""
        if self._state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            if self._opened_at is not None:
                if time.time() - self._opened_at >= self.recovery_timeout:
                    _logger.info(
                        f"Circuit '{self.name}' transitioning OPEN → HALF_OPEN "
                        f"(recovery timeout passed)"
                    )
                    self._state = CircuitState.HALF_OPEN
                    self._metrics.state_changes += 1
        
        return self._state
    
    @property
    def is_active(self) -> bool:
        """Check if circuit is accepting calls."""
        return self.state != CircuitState.OPEN
    
    def metrics(self) -> CircuitBreakerMetrics:
        """Get current metrics snapshot."""
        return CircuitBreakerMetrics(
            total_calls=self._metrics.total_calls,
            successful_calls=self._metrics.successful_calls,
            failed_calls=self._metrics.failed_calls,
            rejected_calls=self._metrics.rejected_calls,
            state_changes=self._metrics.state_changes,
            last_failure_time=self._metrics.last_failure_time,
            last_success_time=self._metrics.last_success_time,
        )
    
    def call(self, func: Callable[..., T]) -> Callable[..., T]:
        """Decorator to wrap a function with circuit-breaker logic.
        
        Args:
            func: Function to wrap
            
        Returns:
            Wrapped function that respects circuit state
        """
        def wrapper(*args: Any, **kwargs: Any) -> T:
            return self._execute(func, args, kwargs)
        
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper
    
    def _execute(
        self,
        func: Callable[..., T],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> T:
        """Execute function with circuit-breaker protection.
        
        Args:
            func: Function to execute
            args: Positional arguments
            kwargs: Keyword arguments
            
        Returns:
            Function result
            
        Raises:
            CircuitBreakerOpen: If circuit is OPEN
        """
        current_state = self.state
        
        if current_state == CircuitState.OPEN:
            # Reject all calls while OPEN
            self._metrics.rejected_calls += 1
            self._metrics.total_calls += 1
            recovery_time = self.recovery_timeout
            if self._opened_at is not None:
                elapsed = time.time() - self._opened_at
                recovery_time = max(0, self.recovery_timeout - elapsed)
            raise CircuitBreakerOpen(self.name, recovery_time)
        
        try:
            # Execute the function
            result = func(*args, **kwargs)
            
            # Success - record metrics and potentially close circuit
            self._metrics.total_calls += 1
            self._metrics.successful_calls += 1
            self._metrics.last_success_time = time.time()
            self._failure_count = 0
            
            if current_state == CircuitState.HALF_OPEN:
                # Success in HALF_OPEN state means we can close circuit
                _logger.info(
                    f"Circuit '{self.name}' recovery successful, "
                    f"transitioning HALF_OPEN → CLOSED"
                )
                self._state = CircuitState.CLOSED
                self._metrics.state_changes += 1
            
            return result
            
        except self.expected_exception as e:
            # Failure - track and potentially open circuit
            self._metrics.total_calls += 1
            self._metrics.failed_calls += 1
            self._metrics.last_failure_time = time.time()
            self._failure_count += 1
            self._last_failure_time = time.time()
            
            _logger.warning(
                f"Circuit '{self.name}' call failed "
                f"({self._failure_count}/{self.failure_threshold}): {e}"
            )
            
            if self._failure_count >= self.failure_threshold:
                if self._state != CircuitState.OPEN:
                    _logger.error(
                        f"Circuit '{self.name}' failure threshold exceeded, "
                        f"opening circuit. Will retry in {self.recovery_timeout}s"
                    )
                    self._state = CircuitState.OPEN
                    self._opened_at = time.time()
                    self._metrics.state_changes += 1
            
            raise


def circuit_breaker(
    name: str = "circuit_breaker",
    failure_threshold: int = 5,
    recovery_timeout: float = 60.0,
    expected_exception: type[BaseException] | tuple[type[BaseException], ...] = Exception,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator factory for circuit-breaker pattern.
    
    Args:
        name: Circuit breaker identifier
        failure_threshold: Failures before opening
        recovery_timeout: Recovery test delay
        expected_exception: Exception type(s) to catch
        
    Returns:
        Decorator function
        
    Example:
        @circuit_breaker(
            name="llm_api",
            failure_threshold=3,
            recovery_timeout=30,
            expected_exception=TimeoutError
        )
        def call_llm_api(prompt: str) -> str:
            return llm_backend.generate(prompt)
    """
    breaker: CircuitBreaker[Any] = CircuitBreaker(
        name=name,
        failure_threshold=failure_threshold,
        recovery_timeout=recovery_timeout,
        expected_exception=expected_exception,
    )
    
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        return breaker.call(func)
    
    return decorator
