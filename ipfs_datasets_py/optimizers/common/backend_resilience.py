"""Unified timeout/retry/circuit-breaker policy for backend calls."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Callable, Optional, TypeVar

from .circuit_breaker import CircuitBreaker, CircuitBreakerOpen
from .exceptions import (
    CircuitBreakerOpenError,
    OptimizerTimeoutError,
    RetryableBackendError,
)

T = TypeVar("T")


@dataclass(frozen=True)
class BackendCallPolicy:
    """Policy controlling timeout, retries, and circuit-breaker behavior."""

    service_name: str = "external_backend"
    timeout_seconds: float = 30.0
    max_retries: int = 2
    initial_backoff_seconds: float = 0.1
    backoff_multiplier: float = 2.0
    max_backoff_seconds: float = 2.0
    circuit_failure_threshold: int = 5
    circuit_recovery_timeout: float = 60.0

    def validate(self) -> None:
        if not self.service_name.strip():
            raise ValueError("service_name must be non-empty")
        if self.timeout_seconds < 0.0:
            raise ValueError("timeout_seconds must be >= 0.0")
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if self.initial_backoff_seconds < 0.0:
            raise ValueError("initial_backoff_seconds must be >= 0.0")
        if self.backoff_multiplier < 1.0:
            raise ValueError("backoff_multiplier must be >= 1.0")
        if self.max_backoff_seconds < 0.0:
            raise ValueError("max_backoff_seconds must be >= 0.0")
        if self.circuit_failure_threshold < 1:
            raise ValueError("circuit_failure_threshold must be >= 1")
        if self.circuit_recovery_timeout < 0.0:
            raise ValueError("circuit_recovery_timeout must be >= 0.0")


def _run_with_timeout(operation: Callable[[], T], timeout_seconds: float) -> T:
    """Run operation with an optional timeout."""
    if timeout_seconds <= 0.0:
        return operation()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(operation)
        try:
            return future.result(timeout=timeout_seconds)
        except FutureTimeoutError as exc:
            future.cancel()
            raise OptimizerTimeoutError(
                f"Timed out after {timeout_seconds}s",
                service="timeout_guard",
                details={"timeout_seconds": timeout_seconds},
            ) from exc


def _backoff_seconds(policy: BackendCallPolicy, attempt: int) -> float:
    """Compute backoff delay for a zero-based retry attempt."""
    delay = policy.initial_backoff_seconds * (policy.backoff_multiplier ** attempt)
    return min(delay, policy.max_backoff_seconds)


def execute_with_resilience(
    operation: Callable[[], T],
    policy: BackendCallPolicy,
    *,
    circuit_breaker: Optional[CircuitBreaker[T]] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> T:
    """Execute a backend operation with timeout, retry, and circuit-breaker guards."""
    policy.validate()
    breaker = circuit_breaker or CircuitBreaker[T](
        name=policy.service_name,
        failure_threshold=policy.circuit_failure_threshold,
        recovery_timeout=policy.circuit_recovery_timeout,
        expected_exception=Exception,
    )

    guarded = breaker.call(lambda: _run_with_timeout(operation, policy.timeout_seconds))
    attempts = policy.max_retries + 1

    for attempt in range(attempts):
        try:
            return guarded()
        except CircuitBreakerOpen as exc:
            raise CircuitBreakerOpenError(
                f"Circuit is open for {policy.service_name}",
                service=policy.service_name,
                details={"recovery_time": exc.recovery_time},
            ) from exc
        except (OptimizerTimeoutError, Exception) as exc:
            if attempt >= policy.max_retries:
                raise RetryableBackendError(
                    f"{policy.service_name} failed after {attempts} attempts",
                    service=policy.service_name,
                    details={"attempts": attempts, "last_error": str(exc)},
                ) from exc
            delay = _backoff_seconds(policy, attempt)
            if delay > 0.0:
                sleep_fn(delay)

    raise RetryableBackendError(
        f"{policy.service_name} failed after {attempts} attempts",
        service=policy.service_name,
        details={"attempts": attempts},
    )


__all__ = [
    "BackendCallPolicy",
    "execute_with_resilience",
]

