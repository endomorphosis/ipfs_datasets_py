"""Tests for unified backend timeout/retry/circuit-breaker policy."""

from __future__ import annotations

import time

import pytest

from ipfs_datasets_py.optimizers.common.backend_resilience import (
    BackendCallPolicy,
    execute_with_resilience,
)
from ipfs_datasets_py.optimizers.common.circuit_breaker import CircuitBreaker
from ipfs_datasets_py.optimizers.common.exceptions import (
    CircuitBreakerOpenError,
    OptimizerTimeoutError,
    RetryableBackendError,
)


def test_execute_with_resilience_success_no_retry() -> None:
    policy = BackendCallPolicy(max_retries=0)
    result = execute_with_resilience(lambda: "ok", policy)
    assert result == "ok"


def test_execute_with_resilience_retries_then_succeeds() -> None:
    policy = BackendCallPolicy(max_retries=2, initial_backoff_seconds=0.0)
    calls = {"n": 0}

    def _op() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("transient")
        return "ok"

    result = execute_with_resilience(_op, policy, sleep_fn=lambda _: None)
    assert result == "ok"
    assert calls["n"] == 3


def test_execute_with_resilience_exhausts_retries() -> None:
    policy = BackendCallPolicy(
        service_name="backend-a",
        max_retries=1,
        initial_backoff_seconds=0.0,
    )

    with pytest.raises(RetryableBackendError) as exc_info:
        execute_with_resilience(lambda: (_ for _ in ()).throw(ValueError("boom")), policy, sleep_fn=lambda _: None)

    assert "backend-a failed after 2 attempts" in str(exc_info.value)


def test_execute_with_resilience_redacts_sensitive_last_error() -> None:
    policy = BackendCallPolicy(
        service_name="backend-sensitive",
        max_retries=0,
        initial_backoff_seconds=0.0,
    )

    with pytest.raises(RetryableBackendError) as exc_info:
        execute_with_resilience(
            lambda: (_ for _ in ()).throw(ValueError("api_key=sk-1234567890abcdef password=hunter2")),
            policy,
            sleep_fn=lambda _: None,
        )

    details = exc_info.value.details if isinstance(exc_info.value.details, dict) else {}
    last_error = str(details.get("last_error", ""))
    assert "***REDACTED***" in last_error
    assert "sk-1234567890abcdef" not in last_error
    assert "hunter2" not in last_error


def test_execute_with_resilience_maps_timeout_error() -> None:
    policy = BackendCallPolicy(timeout_seconds=0.01, max_retries=0, initial_backoff_seconds=0.0)

    def _slow() -> str:
        time.sleep(0.05)
        return "late"

    with pytest.raises(RetryableBackendError) as exc_info:
        execute_with_resilience(_slow, policy, sleep_fn=lambda _: None)

    assert isinstance(exc_info.value.__cause__, OptimizerTimeoutError)


def test_execute_with_resilience_maps_circuit_open() -> None:
    policy = BackendCallPolicy(
        service_name="backend-b",
        max_retries=0,
        initial_backoff_seconds=0.0,
        circuit_failure_threshold=1,
        circuit_recovery_timeout=60.0,
    )
    breaker: CircuitBreaker[str] = CircuitBreaker(
        name="backend-b",
        failure_threshold=1,
        recovery_timeout=60.0,
        expected_exception=Exception,
    )

    with pytest.raises(RetryableBackendError):
        execute_with_resilience(
            lambda: (_ for _ in ()).throw(ValueError("first failure")),
            policy,
            circuit_breaker=breaker,
            sleep_fn=lambda _: None,
        )

    with pytest.raises(CircuitBreakerOpenError):
        execute_with_resilience(
            lambda: "never runs",
            policy,
            circuit_breaker=breaker,
            sleep_fn=lambda _: None,
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"service_name": ""},
        {"timeout_seconds": -1.0},
        {"max_retries": -1},
        {"initial_backoff_seconds": -0.1},
        {"backoff_multiplier": 0.9},
        {"max_backoff_seconds": -0.1},
        {"circuit_failure_threshold": 0},
        {"circuit_recovery_timeout": -1.0},
    ],
)
def test_backend_call_policy_validation(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        BackendCallPolicy(**kwargs).validate()
