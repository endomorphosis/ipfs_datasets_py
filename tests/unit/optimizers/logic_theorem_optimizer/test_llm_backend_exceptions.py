"""Tests for typed exception handling in logic theorem LLM backend."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.common.exceptions import RetryableBackendError
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.llm_backend import (
    AccelerateBackend,
    get_default_adapter,
    LLMBackendAdapter,
    LLMRequest,
    MockBackend,
    RouterBackend,
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


class _ManagerSensitiveError:
    def run_inference(self, **kwargs):
        raise ValueError("api_key=sk-1234567890abcdef password=hunter2")


def test_default_adapter_prefers_llm_router_codex() -> None:
    adapter = get_default_adapter(fallback_to_mock=False, enable_caching=False)

    assert adapter.active_backend == "llm_router"
    assert isinstance(adapter.backends["llm_router"], RouterBackend)
    assert adapter.router_provider == "codex"
    assert adapter.router_model == "gpt-5.3-codex"


def test_router_backend_calls_llm_router_with_codex_53(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def _fake_generate_text(prompt, **kwargs):
        captured["prompt"] = prompt
        captured["kwargs"] = kwargs
        return "Formula: P(x)"

    def _fake_trace():
        return {
            "effective_provider_name": "codex_cli",
            "effective_model_name": "gpt-5.3-codex",
        }

    monkeypatch.setattr("ipfs_datasets_py.llm_router.generate_text", _fake_generate_text)
    monkeypatch.setattr("ipfs_datasets_py.llm_router.get_last_generation_trace", _fake_trace)

    response = RouterBackend().generate(LLMRequest(prompt="extract logic"))

    assert response.text == "Formula: P(x)"
    assert response.backend == "llm_router"
    assert response.model == "gpt-5.3-codex"
    assert captured["prompt"] == "extract logic"
    assert captured["kwargs"]["provider"] == "codex"
    assert captured["kwargs"]["model_name"] == "gpt-5.3-codex"
    assert captured["kwargs"]["allow_local_fallback"] is False
    assert captured["kwargs"]["disable_model_retry"] is True


def test_router_backend_rejects_non_codex_effective_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ipfs_datasets_py.llm_router.generate_text", lambda *args, **kwargs: "ok")
    monkeypatch.setattr(
        "ipfs_datasets_py.llm_router.get_last_generation_trace",
        lambda: {"effective_provider_name": "openai", "effective_model_name": "gpt-5.3-codex"},
    )

    with pytest.raises(RuntimeError, match="expected Codex provider"):
        RouterBackend().generate(LLMRequest(prompt="extract logic"))


def test_adapter_generate_falls_back_to_mock_on_typed_backend_error() -> None:
    adapter = LLMBackendAdapter(preferred_backend="mock", fallback_to_mock=True, enable_caching=False)
    adapter.backends = {
        "accelerate": _BrokenBackend(),
        "mock": MockBackend(),
    }
    adapter.active_backend = "accelerate"

    response = adapter.generate(LLMRequest(prompt="extract logic from data"))

    assert response.backend == "mock"
    assert response.metadata["mock_fallback"] is True
    assert response.metadata["fallback_from_backend"] == "accelerate"
    assert adapter.stats["errors"] == 1


def test_adapter_generate_respects_disabled_mock_fallback() -> None:
    adapter = LLMBackendAdapter(preferred_backend="mock", fallback_to_mock=False, enable_caching=False)
    adapter.backends = {
        "accelerate": _BrokenBackend(),
        "mock": MockBackend(),
    }
    adapter.active_backend = "accelerate"

    with pytest.raises(RetryableBackendError, match="failed after 3 attempts"):
        adapter.generate(LLMRequest(prompt="extract logic from data"))

    assert adapter.stats["errors"] == 1


def test_accelerate_backend_generate_reraises_typed_errors() -> None:
    backend = AccelerateBackend(_ManagerTypeError())

    with pytest.raises(TypeError, match="bad manager call"):
        backend.generate(LLMRequest(prompt="x"))


def test_accelerate_backend_redacts_sensitive_error_text_in_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    backend = AccelerateBackend(_ManagerSensitiveError())

    with caplog.at_level("ERROR"):
        with pytest.raises(ValueError):
            backend.generate(LLMRequest(prompt="x"))

    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "***REDACTED***" in messages
    assert "sk-1234567890abcdef" not in messages
    assert "hunter2" not in messages


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
