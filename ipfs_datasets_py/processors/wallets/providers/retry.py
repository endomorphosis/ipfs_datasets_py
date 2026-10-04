"""Retry taxonomy, Retry-After parsing, and circuit breaking."""

from __future__ import annotations

import email.utils
import math
import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum

from ..errors import InvalidRequestError, ProviderError


class RetryDisposition(StrEnum):
    """Provider outcome taxonomy used by the retry controller."""

    SUCCESS = "success"
    THROTTLED = "throttled"
    TRANSIENT = "transient"
    PERMANENT = "permanent"


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class ProviderTransportError(ProviderError):
    """Base transport error whose message never contains upstream detail."""

    disposition = RetryDisposition.PERMANENT


class TransientProviderError(ProviderTransportError):
    disposition = RetryDisposition.TRANSIENT


class ThrottledProviderError(TransientProviderError):
    disposition = RetryDisposition.THROTTLED

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = (
            None
            if retry_after is None
            else _finite_nonnegative(retry_after, "retry_after")
        )


class PermanentProviderError(ProviderTransportError):
    disposition = RetryDisposition.PERMANENT


class CircuitOpenError(TransientProviderError):
    """Raised before I/O while a provider circuit is open."""


def _finite_nonnegative(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidRequestError(f"{name} must be a finite non-negative number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise InvalidRequestError(f"{name} must be a finite non-negative number")
    return result


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Finite exponential-backoff policy with bounded server hints."""

    max_attempts: int = 3
    base_delay_seconds: float = 0.25
    max_delay_seconds: float = 5.0
    max_retry_after_seconds: float = 30.0
    jitter_fraction: float = 0.2
    retry_statuses: frozenset[int] = field(
        default_factory=lambda: frozenset({408, 425, 429, 500, 502, 503, 504})
    )

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_attempts, bool)
            or not isinstance(self.max_attempts, int)
            or not 1 <= self.max_attempts <= 20
        ):
            raise InvalidRequestError("max_attempts must be between 1 and 20")
        base = _finite_nonnegative(self.base_delay_seconds, "base_delay_seconds")
        maximum = _finite_nonnegative(self.max_delay_seconds, "max_delay_seconds")
        retry_after = _finite_nonnegative(
            self.max_retry_after_seconds, "max_retry_after_seconds"
        )
        jitter = _finite_nonnegative(self.jitter_fraction, "jitter_fraction")
        if maximum < base:
            raise InvalidRequestError(
                "max_delay_seconds must not be less than base_delay_seconds"
            )
        if jitter > 1:
            raise InvalidRequestError("jitter_fraction must not exceed 1")
        if any(
            isinstance(status, bool)
            or not isinstance(status, int)
            or not 100 <= status <= 599
            for status in self.retry_statuses
        ):
            raise InvalidRequestError("retry_statuses contains an invalid HTTP status")
        object.__setattr__(self, "base_delay_seconds", base)
        object.__setattr__(self, "max_delay_seconds", maximum)
        object.__setattr__(self, "max_retry_after_seconds", retry_after)
        object.__setattr__(self, "jitter_fraction", jitter)
        object.__setattr__(self, "retry_statuses", frozenset(self.retry_statuses))

    def classify_status(self, status: int) -> RetryDisposition:
        # Redirects are never followed by this policy layer.  Delegates must
        # also disable automatic redirects so every destination is validated.
        if 200 <= status < 300:
            return RetryDisposition.SUCCESS
        if status == 429:
            return RetryDisposition.THROTTLED
        if status in self.retry_statuses:
            return RetryDisposition.TRANSIENT
        return RetryDisposition.PERMANENT

    def retry_after_seconds(
        self,
        headers: Mapping[str, str],
        *,
        now: datetime | None = None,
    ) -> float | None:
        """Parse seconds or an HTTP-date and clamp it to the configured bound."""

        value = next(
            (item for key, item in headers.items() if key.lower() == "retry-after"),
            None,
        )
        if value is None:
            return None
        stripped = value.strip()
        try:
            delay = float(stripped)
        except ValueError:
            try:
                target = email.utils.parsedate_to_datetime(stripped)
            except (TypeError, ValueError, OverflowError):
                return None
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            current = now or datetime.now(timezone.utc)
            delay = (target - current).total_seconds()
        if not math.isfinite(delay):
            return None
        return min(max(0.0, delay), self.max_retry_after_seconds)

    def delay_seconds(
        self,
        failed_attempt: int,
        *,
        retry_after: float | None = None,
        random_value: float | None = None,
    ) -> float:
        """Return a bounded delay after the given one-based failed attempt."""

        if (
            isinstance(failed_attempt, bool)
            or not isinstance(failed_attempt, int)
            or failed_attempt <= 0
        ):
            raise InvalidRequestError("failed_attempt must be a positive integer")
        if retry_after is not None:
            return min(
                _finite_nonnegative(retry_after, "retry_after"),
                self.max_retry_after_seconds,
            )
        base = min(
            self.max_delay_seconds,
            self.base_delay_seconds * (2 ** (failed_attempt - 1)),
        )
        sample = random.random() if random_value is None else random_value
        if not 0 <= sample <= 1:
            raise InvalidRequestError("random_value must be between 0 and 1")
        factor = 1 - self.jitter_fraction + (2 * self.jitter_fraction * sample)
        return min(self.max_delay_seconds, max(0.0, base * factor))


@dataclass(frozen=True, slots=True)
class CircuitBreakerPolicy:
    failure_threshold: int = 5
    recovery_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if (
            isinstance(self.failure_threshold, bool)
            or not isinstance(self.failure_threshold, int)
            or self.failure_threshold <= 0
        ):
            raise InvalidRequestError("failure_threshold must be a positive integer")
        object.__setattr__(
            self,
            "recovery_timeout_seconds",
            _finite_nonnegative(
                self.recovery_timeout_seconds, "recovery_timeout_seconds"
            ),
        )
        if self.recovery_timeout_seconds == 0:
            raise InvalidRequestError(
                "recovery_timeout_seconds must be greater than zero"
            )


class CircuitBreaker:
    """Small deterministic state machine for one provider endpoint."""

    __slots__ = (
        "_clock",
        "_failures",
        "_half_open_in_flight",
        "_opened_at",
        "_policy",
        "_state",
    )

    def __init__(
        self,
        policy: CircuitBreakerPolicy | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._policy = policy or CircuitBreakerPolicy()
        self._clock = clock
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._opened_at: float | None = None
        self._half_open_in_flight = False

    @property
    def state(self) -> CircuitState:
        if (
            self._state is CircuitState.OPEN
            and self._opened_at is not None
            and self._clock() - self._opened_at
            >= self._policy.recovery_timeout_seconds
        ):
            self._state = CircuitState.HALF_OPEN
            self._half_open_in_flight = False
        return self._state

    def before_request(self) -> None:
        state = self.state
        if state is CircuitState.OPEN:
            raise CircuitOpenError("provider circuit is open")
        if state is CircuitState.HALF_OPEN:
            if self._half_open_in_flight:
                raise CircuitOpenError("provider circuit probe is already in progress")
            self._half_open_in_flight = True

    def record_success(self) -> None:
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._opened_at = None
        self._half_open_in_flight = False

    def record_failure(self) -> None:
        self._half_open_in_flight = False
        self._failures += 1
        if (
            self._state is CircuitState.HALF_OPEN
            or self._failures >= self._policy.failure_threshold
        ):
            self._state = CircuitState.OPEN
            self._opened_at = float(self._clock())

    def record_permanent_failure(self) -> None:
        """Release a half-open probe without teaching the circuit about 4xx."""

        if self._state is CircuitState.HALF_OPEN:
            self.record_success()


__all__ = [
    "CircuitBreaker",
    "CircuitBreakerPolicy",
    "CircuitOpenError",
    "CircuitState",
    "PermanentProviderError",
    "ProviderTransportError",
    "RetryDisposition",
    "RetryPolicy",
    "ThrottledProviderError",
    "TransientProviderError",
]
