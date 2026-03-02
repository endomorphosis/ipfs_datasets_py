#!/usr/bin/env python3

from ipfs_datasets_py.processors.web_archiving.orchestration.resilience import (
    CircuitBreakerConfig,
    CircuitBreakerRegistry,
    CircuitState,
    RetryPolicy,
    execute_with_retry,
)


class FakeClock:
    def __init__(self, start: float = 100.0):
        self.now = start

    def time(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_circuit_breaker_opens_and_recovers_to_half_open() -> None:
    clock = FakeClock()
    registry = CircuitBreakerRegistry(
        CircuitBreakerConfig(failure_threshold=2, recovery_timeout_seconds=10),
        time_fn=clock.time,
    )

    key = "provider:search"
    assert registry.allow_request(key) is True

    registry.record_failure(key)
    assert registry.get_state(key) == CircuitState.CLOSED

    registry.record_failure(key)
    assert registry.get_state(key) == CircuitState.OPEN
    assert registry.allow_request(key) is False

    clock.advance(11)
    assert registry.allow_request(key) is True
    assert registry.get_state(key) == CircuitState.HALF_OPEN


def test_circuit_breaker_half_open_failure_reopens() -> None:
    clock = FakeClock()
    registry = CircuitBreakerRegistry(
        CircuitBreakerConfig(failure_threshold=1, recovery_timeout_seconds=5),
        time_fn=clock.time,
    )

    key = "provider:search"
    registry.record_failure(key)
    assert registry.get_state(key) == CircuitState.OPEN

    clock.advance(6)
    assert registry.allow_request(key) is True
    assert registry.get_state(key) == CircuitState.HALF_OPEN

    registry.record_failure(key)
    assert registry.get_state(key) == CircuitState.OPEN


def test_execute_with_retry_succeeds_after_transient_failures() -> None:
    attempts = {"count": 0}
    sleeps = []

    def flaky() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("temporary")
        return "ok"

    result = execute_with_retry(
        flaky,
        policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.1, max_delay_seconds=1.0, jitter_ratio=0.0),
        sleep_fn=sleeps.append,
        random_fn=lambda: 0.5,
    )

    assert result == "ok"
    assert attempts["count"] == 3
    assert len(sleeps) == 2


def test_execute_with_retry_stops_for_non_retryable() -> None:
    attempts = {"count": 0}

    def always_fail() -> str:
        attempts["count"] += 1
        raise ValueError("fatal")

    try:
        execute_with_retry(
            always_fail,
            policy=RetryPolicy(max_attempts=5),
            is_retryable=lambda exc: not isinstance(exc, ValueError),
            sleep_fn=lambda _: None,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Expected ValueError")

    assert attempts["count"] == 1
