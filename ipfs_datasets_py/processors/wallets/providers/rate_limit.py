"""Deterministic token-bucket rate limiting for wallet providers."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from ..errors import DeadlineExceededError, InvalidRequestError
from ..protocols import OperationContext


Clock = Callable[[], float]
Sleeper = Callable[[float], Awaitable[None]]


def _positive_number(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise InvalidRequestError(f"{name} must be a positive finite number")
    result = float(value)
    if result == float("inf") or result != result:
        raise InvalidRequestError(f"{name} must be a positive finite number")
    return result


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    """Finite token-bucket parameters."""

    requests_per_second: float = 10.0
    burst: int = 10
    max_wait_seconds: float = 30.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "requests_per_second",
            _positive_number(self.requests_per_second, "requests_per_second"),
        )
        if (
            isinstance(self.burst, bool)
            or not isinstance(self.burst, int)
            or self.burst <= 0
        ):
            raise InvalidRequestError("burst must be a positive integer")
        object.__setattr__(
            self,
            "max_wait_seconds",
            _positive_number(self.max_wait_seconds, "max_wait_seconds"),
        )


class RateLimiter:
    """An async token bucket with injected time and sleep functions."""

    __slots__ = ("_clock", "_last", "_lock", "_policy", "_sleep", "_tokens")

    def __init__(
        self,
        policy: RateLimitPolicy | None = None,
        *,
        clock: Clock = time.monotonic,
        sleep: Sleeper = asyncio.sleep,
    ) -> None:
        self._policy = policy or RateLimitPolicy()
        self._clock = clock
        self._sleep = sleep
        self._tokens = float(self._policy.burst)
        self._last = float(clock())
        self._lock = asyncio.Lock()

    @property
    def policy(self) -> RateLimitPolicy:
        return self._policy

    def __repr__(self) -> str:
        return f"RateLimiter(policy={self._policy!r})"

    async def acquire(self, *, context: OperationContext) -> float:
        """Acquire one request token and return the time spent throttled."""

        total_wait = 0.0
        while True:
            context.check_active()
            async with self._lock:
                now = float(self._clock())
                elapsed = max(0.0, now - self._last)
                self._tokens = min(
                    float(self._policy.burst),
                    self._tokens + elapsed * self._policy.requests_per_second,
                )
                self._last = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return total_wait
                wait = (1.0 - self._tokens) / self._policy.requests_per_second
            if total_wait + wait > self._policy.max_wait_seconds:
                raise DeadlineExceededError("provider rate-limit wait exceeded its bound")
            remaining = context.remaining_seconds()
            if remaining is not None and wait >= remaining:
                raise DeadlineExceededError("provider rate-limit wait exceeds deadline")
            await self._sleep(wait)
            total_wait += wait


__all__ = ["RateLimitPolicy", "RateLimiter"]
