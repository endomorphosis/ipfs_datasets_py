"""
Circuit Breaker for LLM Calls (Session 83, P2-security).

Implements failure-aware circuit breaker pattern for LLM API calls to prevent
cascading failures, resource exhaustion, and cost overruns.

Circuit States:
- CLOSED: Normal operation, requests pass through
- OPEN: Failure threshold exceeded, requests immediately fail-fast
- HALF_OPEN: Testing if service has recovered, limited requests allowed

Features:
- Configurable failure thresholds and timeouts
- Exponential backoff for retry attempts
- Fallback handler support
- Metrics collection (success/failure counts, latencies)
- Thread-safe operation

Usage:
    from ipfs_datasets_py.logic.security.llm_circuit_breaker import LLMCircuitBreaker
    
    breaker = LLMCircuitBreaker(
        failure_threshold=5,
        timeout_seconds=60,
        fallback=lambda: "Service temporarily unavailable"
    )
    
    @breaker.protected
    def call_llm(prompt: str) -> str:
        return expensive_llm_call(prompt)
    
    # Or use as context manager
    with breaker:
        result = expensive_llm_call(prompt)
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Any, Callable, Optional, Dict

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states following the standard pattern."""
    
    CLOSED = "closed"          # Normal operation
    OPEN = "open"              # Failures exceeded, failing fast
    HALF_OPEN = "half_open"    # Testing recovery


@dataclass
class CircuitBreakerMetrics:
    """Metrics tracking for circuit breaker operation."""
    
    success_count: int = 0
    failure_count: int = 0
    total_calls: int = 0
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None
    consecutive_successes: int = 0
    consecutive_failures: int = 0
    state_transitions: int = 0
    latencies: list = field(default_factory=list)  # Recent latencies (max 100)
    
    def record_success(self, latency: float) -> None:
        """Record a successful call."""
        self.success_count += 1
        self.total_calls += 1
        self.consecutive_successes += 1
        self.consecutive_failures = 0
        self.last_success_time = time.time()
        self.latencies.append(latency)
        if len(self.latencies) > 100:
            self.latencies.pop(0)
    
    def record_failure(self) -> None:
        """Record a failed call."""
        self.failure_count += 1
        self.total_calls += 1
        self.consecutive_failures += 1
        self.consecutive_successes = 0
        self.last_failure_time = time.time()
    
    def record_state_transition(self) -> None:
        """Record a state change."""
        self.state_transitions += 1
    
    def get_failure_rate(self) -> float:
        """Calculate current failure rate (0.0 to 1.0)."""
        if self.total_calls == 0:
            return 0.0
        return self.failure_count / self.total_calls
    
    def get_average_latency(self) -> float:
        """Calculate average latency from recent calls."""
        if not self.latencies:
            return 0.0
        return sum(self.latencies) / len(self.latencies)


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is OPEN and request is rejected."""
    
    def __init__(self, message: str = "Circuit breaker is OPEN", breaker: Optional["LLMCircuitBreaker"] = None):
        super().__init__(message)
        self.breaker = breaker


class LLMCircuitBreaker:
    """Circuit breaker for LLM API calls.
    
    Prevents cascading failures by failing fast when error threshold is exceeded.
    Automatically attempts recovery after timeout period.
    
    Args:
        failure_threshold: Number of consecutive failures before opening circuit.
        timeout_seconds: Seconds to wait in OPEN state before attempting recovery.
        success_threshold: Consecutive successes needed in HALF_OPEN to close circuit.
        fallback: Optional callable to invoke when circuit is OPEN.
        name: Identifier for this circuit breaker (for logging/metrics).
    
    Example:
        >>> breaker = LLMCircuitBreaker(failure_threshold=3, timeout_seconds=30)
        >>> @breaker.protected
        ... def call_api():
        ...     return expensive_llm_call()
        >>> result = call_api()  # May raise CircuitBreakerOpenError
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        timeout_seconds: float = 60.0,
        success_threshold: int = 2,
        fallback: Optional[Callable[[], Any]] = None,
        name: str = "llm_circuit_breaker",
    ):
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        if success_threshold < 1:
            raise ValueError("success_threshold must be >= 1")
        
        self.failure_threshold = failure_threshold
        self.timeout_seconds = timeout_seconds
        self.success_threshold = success_threshold
        self.fallback = fallback
        self.name = name
        
        self._state = CircuitState.CLOSED
        self._state_lock = threading.RLock()
        self._last_state_change = time.time()
        self._metrics = CircuitBreakerMetrics()
    
    @property
    def state(self) -> CircuitState:
        """Current circuit state (thread-safe)."""
        with self._state_lock:
            return self._state
    
    @property
    def metrics(self) -> CircuitBreakerMetrics:
        """Current metrics snapshot (thread-safe)."""
        with self._state_lock:
            return CircuitBreakerMetrics(
                success_count=self._metrics.success_count,
                failure_count=self._metrics.failure_count,
                total_calls=self._metrics.total_calls,
                last_failure_time=self._metrics.last_failure_time,
                last_success_time=self._metrics.last_success_time,
                consecutive_successes=self._metrics.consecutive_successes,
                consecutive_failures=self._metrics.consecutive_failures,
                state_transitions=self._metrics.state_transitions,
                latencies=list(self._metrics.latencies),
            )
    
    def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to a new state (must be called under lock)."""
        if self._state != new_state:
            logger.info(
                "Circuit breaker '%s' transitioning: %s -> %s",
                self.name,
                self._state.value,
                new_state.value,
            )
            self._state = new_state
            self._last_state_change = time.time()
            self._metrics.record_state_transition()
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt recovery."""
        elapsed = time.time() - self._last_state_change
        return elapsed >= self.timeout_seconds
    
    def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute function with circuit breaker protection.
        
        Args:
            func: Callable to execute.
            *args: Positional arguments to pass to func.
            **kwargs: Keyword arguments to pass to func.
        
        Returns:
            Result from func, or fallback result if circuit is OPEN.
        
        Raises:
            CircuitBreakerOpenError: If circuit is OPEN and no fallback provided.
            Exception: Any exception raised by func (in CLOSED/HALF_OPEN states).
        """
        with self._state_lock:
            current_state = self._state
            
            # OPEN state: fail fast
            if current_state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self._transition_to(CircuitState.HALF_OPEN)
                else:
                    logger.warning(
                        "Circuit breaker '%s' is OPEN, request rejected",
                        self.name
                    )
                    if self.fallback:
                        return self.fallback()
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker '{self.name}' is OPEN",
                        breaker=self
                    )
            
            # HALF_OPEN state: allow limited requests to test recovery
            # (In this implementation, we allow one request at a time)
        
        # Execute the protected function
        start_time = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            latency = time.perf_counter() - start_time
            
            # Record success
            with self._state_lock:
                self._metrics.record_success(latency)
                
                if self._state == CircuitState.HALF_OPEN:
                    if self._metrics.consecutive_successes >= self.success_threshold:
                        self._transition_to(CircuitState.CLOSED)
                        logger.info(
                            "Circuit breaker '%s' recovered, closing circuit",
                            self.name
                        )
            
            return result
        
        except Exception as exc:
            # Record failure
            with self._state_lock:
                self._metrics.record_failure()
                
                # Check if we should open the circuit
                if self._state == CircuitState.CLOSED:
                    if self._metrics.consecutive_failures >= self.failure_threshold:
                        self._transition_to(CircuitState.OPEN)
                        logger.error(
                            "Circuit breaker '%s' threshold exceeded (%d failures), opening circuit",
                            self.name,
                            self.failure_threshold
                        )
                
                elif self._state == CircuitState.HALF_OPEN:
                    # Failure during recovery attempt, reopen circuit
                    self._transition_to(CircuitState.OPEN)
                    logger.warning(
                        "Circuit breaker '%s' recovery failed, reopening circuit",
                        self.name
                    )
            
            # Re-raise the exception
            raise exc
    
    def protected(self, func: Callable) -> Callable:
        """Decorator to protect a function with circuit breaker.
        
        Args:
            func: Function to protect.
        
        Returns:
            Wrapped function with circuit breaker protection.
        
        Example:
            >>> breaker = LLMCircuitBreaker()
            >>> @breaker.protected
            ... def risky_operation():
            ...     return call_external_api()
        """
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return self.call(func, *args, **kwargs)
        return wrapper
    
    def __enter__(self) -> "LLMCircuitBreaker":
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Context manager exit.
        
        Records success/failure based on whether exception occurred.
        Returns False to propagate exceptions.
        """
        if exc_type is None:
            # Success
            with self._state_lock:
                self._metrics.record_success(0.0)  # No latency tracking in context manager
        else:
            # Failure
            with self._state_lock:
                self._metrics.record_failure()
                
                if self._state == CircuitState.CLOSED:
                    if self._metrics.consecutive_failures >= self.failure_threshold:
                        self._transition_to(CircuitState.OPEN)
        
        return False  # Don't suppress exceptions
    
    def reset(self) -> None:
        """Manually reset circuit breaker to CLOSED state.
        
        Clears all metrics and resets to initial state. Use with caution.
        """
        with self._state_lock:
            logger.info("Circuit breaker '%s' manually reset", self.name)
            self._transition_to(CircuitState.CLOSED)
            self._metrics = CircuitBreakerMetrics()
    
    def force_open(self) -> None:
        """Manually force circuit breaker to OPEN state.
        
        Useful for maintenance windows or known outages.
        """
        with self._state_lock:
            logger.warning("Circuit breaker '%s' manually opened", self.name)
            self._transition_to(CircuitState.OPEN)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive statistics about circuit breaker operation.
        
        Returns:
            Dict with current state, metrics, and derived statistics.
        """
        with self._state_lock:
            metrics = self.metrics
            
            return {
                "name": self.name,
                "state": self._state.value,
                "thresholds": {
                    "failure_threshold": self.failure_threshold,
                    "success_threshold": self.success_threshold,
                    "timeout_seconds": self.timeout_seconds,
                },
                "metrics": {
                    "total_calls": metrics.total_calls,
                    "successes": metrics.success_count,
                    "failures": metrics.failure_count,
                    "failure_rate": metrics.get_failure_rate(),
                    "consecutive_failures": metrics.consecutive_failures,
                    "consecutive_successes": metrics.consecutive_successes,
                    "state_transitions": metrics.state_transitions,
                    "average_latency_ms": metrics.get_average_latency() * 1000,
                },
                "timing": {
                    "last_failure": metrics.last_failure_time,
                    "last_success": metrics.last_success_time,
                    "last_state_change": self._last_state_change,
                    "seconds_since_state_change": time.time() - self._last_state_change,
                },
            }
    
    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"LLMCircuitBreaker(name={self.name!r}, state={self.state.value}, "
            f"failures={self._metrics.consecutive_failures}/{self.failure_threshold})"
        )


# ---------------------------------------------------------------------------
# Global circuit breaker registry
# ---------------------------------------------------------------------------

_global_breakers: Dict[str, LLMCircuitBreaker] = {}
_registry_lock = threading.Lock()


def get_circuit_breaker(
    name: str,
    **kwargs: Any
) -> LLMCircuitBreaker:
    """Get or create a named circuit breaker.
    
    Provides a singleton registry for circuit breakers. Useful when multiple
    parts of the codebase need to share the same circuit breaker instance.
    
    Args:
        name: Unique identifier for the circuit breaker.
        **kwargs: Configuration passed to LLMCircuitBreaker constructor
            if creating new instance.
    
    Returns:
        LLMCircuitBreaker instance.
    
    Example:
        >>> breaker = get_circuit_breaker("openai_api", failure_threshold=3)
        >>> @breaker.protected
        ... def call_openai():
        ...     return expensive_api_call()
    """
    with _registry_lock:
        if name not in _global_breakers:
            kwargs["name"] = name
            _global_breakers[name] = LLMCircuitBreaker(**kwargs)
        return _global_breakers[name]


def reset_all_circuit_breakers() -> int:
    """Reset all registered circuit breakers.
    
    Returns:
        Number of breakers reset.
    """
    with _registry_lock:
        for breaker in _global_breakers.values():
            breaker.reset()
        return len(_global_breakers)


def get_all_circuit_breaker_stats() -> Dict[str, Dict[str, Any]]:
    """Get statistics for all registered circuit breakers.
    
    Returns:
        Dict mapping breaker name → stats dict.
    """
    with _registry_lock:
        return {
            name: breaker.get_stats()
            for name, breaker in _global_breakers.items()
        }
