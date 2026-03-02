"""Resilience primitives for unified orchestration.

Includes a provider-level circuit breaker and retry policy runner used by
search/fetch executors.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, Optional, TypeVar


T = TypeVar("T")


class CircuitState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    """Configuration for provider circuit breakers."""

    failure_threshold: int = 3
    recovery_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.failure_threshold <= 0:
            raise ValueError("failure_threshold must be > 0")
        if self.recovery_timeout_seconds <= 0:
            raise ValueError("recovery_timeout_seconds must be > 0")


@dataclass
class CircuitBreakerRecord:
    """Mutable state for one provider+operation breaker."""

    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    open_until_ts: float = 0.0


class CircuitBreakerRegistry:
    """Registry of provider-level circuit breakers."""

    def __init__(
        self,
        config: Optional[CircuitBreakerConfig] = None,
        *,
        time_fn: Callable[[], float] = time.time,
    ):
        self.config = config or CircuitBreakerConfig()
        self.time_fn = time_fn
        self._records: Dict[str, CircuitBreakerRecord] = {}

    def allow_request(self, key: str) -> bool:
        """Return whether a request is allowed under current breaker state."""
        record = self._records.setdefault(key, CircuitBreakerRecord())
        now = self.time_fn()

        if record.state == CircuitState.OPEN:
            if now >= record.open_until_ts:
                record.state = CircuitState.HALF_OPEN
                return True
            return False
        return True

    def record_success(self, key: str) -> None:
        """Record successful request and close/reset breaker."""
        record = self._records.setdefault(key, CircuitBreakerRecord())
        record.state = CircuitState.CLOSED
        record.consecutive_failures = 0
        record.open_until_ts = 0.0

    def record_failure(self, key: str) -> None:
        """Record failed request and open breaker when threshold is reached."""
        record = self._records.setdefault(key, CircuitBreakerRecord())

        if record.state == CircuitState.HALF_OPEN:
            record.state = CircuitState.OPEN
            record.consecutive_failures = self.config.failure_threshold
            record.open_until_ts = self.time_fn() + self.config.recovery_timeout_seconds
            return

        record.consecutive_failures += 1
        if record.consecutive_failures >= self.config.failure_threshold:
            record.state = CircuitState.OPEN
            record.open_until_ts = self.time_fn() + self.config.recovery_timeout_seconds

    def get_state(self, key: str) -> CircuitState:
        """Get current state for a key; defaults to closed."""
        return self._records.get(key, CircuitBreakerRecord()).state


@dataclass
class RetryPolicy:
    """Retry policy for transient provider failures."""

    max_attempts: int = 2
    base_delay_seconds: float = 0.25
    max_delay_seconds: float = 2.0
    jitter_ratio: float = 0.1

    def __post_init__(self) -> None:
        if self.max_attempts <= 0:
            raise ValueError("max_attempts must be > 0")
        if self.base_delay_seconds < 0:
            raise ValueError("base_delay_seconds must be >= 0")
        if self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError("max_delay_seconds must be >= base_delay_seconds")
        if not 0.0 <= self.jitter_ratio <= 1.0:
            raise ValueError("jitter_ratio must be in [0.0, 1.0]")


def execute_with_retry(
    func: Callable[[], T],
    *,
    policy: RetryPolicy,
    is_retryable: Optional[Callable[[Exception], bool]] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    random_fn: Callable[[], float] = random.random,
) -> T:
    """Execute callable with exponential backoff retry behavior."""
    last_error: Optional[Exception] = None

    for attempt in range(1, policy.max_attempts + 1):
        try:
            return func()
        except Exception as exc:  # pragma: no cover - branch exercised in tests
            last_error = exc
            retryable = True if is_retryable is None else bool(is_retryable(exc))
            if not retryable or attempt >= policy.max_attempts:
                raise

            delay = min(
                policy.max_delay_seconds,
                policy.base_delay_seconds * (2 ** (attempt - 1)),
            )
            # jitter in +/- jitter_ratio range
            jitter = delay * policy.jitter_ratio * ((random_fn() * 2.0) - 1.0)
            sleep_for = max(0.0, delay + jitter)
            sleep_fn(sleep_for)

    # Safety fallback; should not be reached due raise in loop.
    if last_error is not None:  # pragma: no cover
        raise last_error
    raise RuntimeError("execute_with_retry exited unexpectedly")  # pragma: no cover


__all__ = [
    "CircuitState",
    "CircuitBreakerConfig",
    "CircuitBreakerRecord",
    "CircuitBreakerRegistry",
    "RetryPolicy",
    "execute_with_retry",
]
