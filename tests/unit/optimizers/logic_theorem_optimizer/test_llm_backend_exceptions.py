"""Tests for typed exception handling in logic theorem LLM backend."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.common.exceptions import RetryableBackendError
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.llm_backend import (
    AccelerateBackend,
    LLMBackendAdapter,
    LLMRequest,
    MockBackend,
)


class _BrokenBackend:
    def generate(self, request: LLMRequest):
        raise ValueError("backend failure")


class _BatchBackend:
    def generate(self, request: LLMRequest):
        return MockBackend().generate(request)

    def generate_batch(self, requests):
        return [MockBackend().generate(req) for req in requests]


class _ManagerTypeError:
    def run_inference(self, **kwargs):
        raise TypeError("bad manager call")


def test_adapter_generate_falls_back_to_mock_on_typed_backend_error() -> None:
    adapter = LLMBackendAdapter(preferred_backend="mock", fallback_to_mock=True, enable_caching=False)
    adapter.backends = {
        "accelerate": _BrokenBackend(),
        "mock": MockBackend(),
    }
    adapter.active_backend = "accelerate"

    response = adapter.generate(LLMRequest(prompt="extract logic from data"))

    assert response.backend == "mock"
    assert adapter.stats["errors"] == 1


def test_accelerate_backend_generate_reraises_typed_errors() -> None:
    backend = AccelerateBackend(_ManagerTypeError())

    with pytest.raises(TypeError, match="bad manager call"):
        backend.generate(LLMRequest(prompt="x"))


def test_adapter_generate_uses_common_backend_resilience_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = LLMBackendAdapter(preferred_backend="mock", fallback_to_mock=True, enable_caching=False)
    adapter.backends = {
        "accelerate": MockBackend(),
        "mock": MockBackend(),
    }
    adapter.active_backend = "accelerate"
    captured = {"service_name": None, "breaker_name": None}

    def _fake_resilience(operation, policy, *, circuit_breaker, sleep_fn=None):
        captured["service_name"] = policy.service_name
        captured["breaker_name"] = getattr(circuit_breaker, "name", None)
        return operation()

    monkeypatch.setattr(
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer.llm_backend.execute_with_resilience",
        _fake_resilience,
    )

    response = adapter.generate(LLMRequest(prompt="extract logic from data"))

    assert response.backend == "accelerate"
    assert captured["service_name"] == "logic_theorem_optimizer_backend_accelerate"
    assert captured["breaker_name"] == "logic_theorem_optimizer_backend_accelerate"


def test_adapter_generate_falls_back_to_mock_on_retryable_backend_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = LLMBackendAdapter(preferred_backend="mock", fallback_to_mock=True, enable_caching=False)
    adapter.backends = {
        "accelerate": _BrokenBackend(),
        "mock": MockBackend(),
    }
    adapter.active_backend = "accelerate"

    def _raise_retryable(operation, policy, *, circuit_breaker, sleep_fn=None):
        raise RetryableBackendError("backend unavailable", service=policy.service_name)

    monkeypatch.setattr(
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer.llm_backend.execute_with_resilience",
        _raise_retryable,
    )

    response = adapter.generate(LLMRequest(prompt="extract logic from data"))

    assert response.backend == "mock"
    assert adapter.stats["errors"] == 1


def test_generate_stream_does_not_mutate_request_stream_flag() -> None:
    adapter = LLMBackendAdapter(preferred_backend="mock", fallback_to_mock=True, enable_caching=False)
    request = LLMRequest(prompt="stream test", stream=False)

    chunks = list(adapter.generate_stream(request))

    assert chunks
    assert request.stream is False


def test_generate_batch_uses_common_backend_resilience_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = LLMBackendAdapter(preferred_backend="mock", fallback_to_mock=True, enable_caching=False)
    adapter.backends = {
        "accelerate": _BatchBackend(),
        "mock": MockBackend(),
    }
    adapter.active_backend = "accelerate"
    captured = {"service_name": None, "breaker_name": None}

    def _fake_resilience(operation, policy, *, circuit_breaker, sleep_fn=None):
        captured["service_name"] = policy.service_name
        captured["breaker_name"] = getattr(circuit_breaker, "name", None)
        return operation()

    monkeypatch.setattr(
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer.llm_backend.execute_with_resilience",
        _fake_resilience,
    )

    responses = adapter.generate_batch([LLMRequest(prompt="a"), LLMRequest(prompt="b")])

    assert len(responses) == 2
    assert captured["service_name"] == "logic_theorem_optimizer_backend_accelerate"
    assert captured["breaker_name"] == "logic_theorem_optimizer_backend_accelerate"


def test_adapter_generate_redacts_sensitive_error_text_in_logs(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    adapter = LLMBackendAdapter(preferred_backend="mock", fallback_to_mock=True, enable_caching=False)
    adapter.backends = {
        "accelerate": _BrokenBackend(),
        "mock": MockBackend(),
    }
    adapter.active_backend = "accelerate"

    def _raise_retryable(operation, policy, *, circuit_breaker, sleep_fn=None):
        raise RetryableBackendError(
            "api_key=sk-1234567890abcdef",
            service=policy.service_name,
            details={"last_error": "password=hunter2"},
        )

    monkeypatch.setattr(
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer.llm_backend.execute_with_resilience",
        _raise_retryable,
    )

    with caplog.at_level("ERROR"):
        response = adapter.generate(LLMRequest(prompt="extract logic from data"))

    assert response.backend == "mock"
    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "***REDACTED***" in messages
    assert "sk-1234567890abcdef" not in messages
    assert "hunter2" not in messages
