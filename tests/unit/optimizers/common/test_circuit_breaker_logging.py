"""Tests for circuit-breaker logging redaction behavior."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.common.circuit_breaker import CircuitBreaker


def test_circuit_breaker_redacts_sensitive_error_text_in_failure_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    breaker: CircuitBreaker[str] = CircuitBreaker(
        name="redaction-test",
        failure_threshold=3,
        recovery_timeout=60.0,
        expected_exception=Exception,
    )

    def _failing_operation() -> str:
        raise ValueError("api_key=sk-1234567890abcdef password=hunter2")

    wrapped = breaker.call(_failing_operation)

    with caplog.at_level("WARNING"):
        with pytest.raises(ValueError):
            wrapped()

    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "***REDACTED***" in messages
    assert "sk-1234567890abcdef" not in messages
    assert "hunter2" not in messages
