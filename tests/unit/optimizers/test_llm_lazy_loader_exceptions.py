from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.llm_lazy_loader import LazyLLMBackend


def test_lazy_loader_call_wraps_typed_runtime_error(monkeypatch) -> None:
    backend = LazyLLMBackend(backend_type="mock", enabled=True, circuit_breaker_enabled=False)
    backend._circuit_breaker = type(
        "_CB",
        (),
        {"_execute": staticmethod(lambda fn, args, kwargs: (_ for _ in ()).throw(RuntimeError("backend failed")))},
    )()

    monkeypatch.setattr(backend, "get_backend", lambda: type("_B", (), {"__call__": staticmethod(lambda *a, **k: "ok")})())

    with pytest.raises(RuntimeError, match="LLM backend error: backend failed"):
        backend("prompt")


def test_lazy_loader_call_does_not_swallow_keyboard_interrupt(monkeypatch) -> None:
    backend = LazyLLMBackend(backend_type="mock", enabled=True, circuit_breaker_enabled=False)
    backend._circuit_breaker = type(
        "_CB",
        (),
        {"_execute": staticmethod(lambda fn, args, kwargs: (_ for _ in ()).throw(KeyboardInterrupt()))},
    )()

    monkeypatch.setattr(backend, "get_backend", lambda: type("_B", (), {"__call__": staticmethod(lambda *a, **k: "ok")})())

    with pytest.raises(KeyboardInterrupt):
        backend("prompt")


def test_lazy_loader_wrapped_method_wraps_typed_runtime_error(monkeypatch) -> None:
    backend = LazyLLMBackend(backend_type="mock", enabled=True, circuit_breaker_enabled=False)
    backend._circuit_breaker = type(
        "_CB",
        (),
        {"_execute": staticmethod(lambda fn, args, kwargs: (_ for _ in ()).throw(RuntimeError("method failed")))},
    )()

    class _B:
        def generate(self, prompt: str):
            return "ok"

    monkeypatch.setattr(backend, "get_backend", lambda: _B())
    wrapped = backend.generate

    with pytest.raises(RuntimeError, match="LLM backend error during generate: method failed"):
        wrapped("prompt")


def test_lazy_loader_call_uses_common_resilience_wrapper(monkeypatch) -> None:
    backend = LazyLLMBackend(backend_type="mock", enabled=True, circuit_breaker_enabled=False)
    from ipfs_datasets_py.optimizers.common.circuit_breaker import CircuitBreaker

    backend._circuit_breaker = CircuitBreaker(
        name="test_lazy_loader",
        failure_threshold=5,
        recovery_timeout=60.0,
        expected_exception=Exception,
    )
    captured = {"service_name": None}

    def _fake_execute(operation, policy, *, circuit_breaker, sleep_fn=None):
        captured["service_name"] = policy.service_name
        return operation()

    monkeypatch.setattr(
        "ipfs_datasets_py.optimizers.llm_lazy_loader.execute_with_resilience",
        _fake_execute,
    )
    monkeypatch.setattr(
        backend,
        "get_backend",
        lambda: type("_B", (), {"__call__": staticmethod(lambda *a, **k: "ok")})(),
    )

    assert backend("prompt") == "ok"
    assert captured["service_name"] == "lazy_llm_backend_mock"


def test_lazy_loader_call_redacts_sensitive_error_text(monkeypatch) -> None:
    backend = LazyLLMBackend(backend_type="mock", enabled=True, circuit_breaker_enabled=False)
    backend._circuit_breaker = type(
        "_CB",
        (),
        {
            "_execute": staticmethod(
                lambda fn, args, kwargs: (_ for _ in ()).throw(
                    RuntimeError("api_key=sk-1234567890abcdef")
                )
            )
        },
    )()
    monkeypatch.setattr(backend, "get_backend", lambda: type("_B", (), {"__call__": staticmethod(lambda *a, **k: "ok")})())

    with pytest.raises(RuntimeError) as exc_info:
        backend("prompt")

    message = str(exc_info.value)
    assert "***REDACTED***" in message
    assert "sk-1234567890abcdef" not in message


def test_lazy_loader_wrapped_method_redacts_sensitive_error_text(monkeypatch) -> None:
    backend = LazyLLMBackend(backend_type="mock", enabled=True, circuit_breaker_enabled=False)
    backend._circuit_breaker = type(
        "_CB",
        (),
        {
            "_execute": staticmethod(
                lambda fn, args, kwargs: (_ for _ in ()).throw(
                    RuntimeError("password=hunter2")
                )
            )
        },
    )()

    class _B:
        def generate(self, prompt: str):
            return "ok"

    monkeypatch.setattr(backend, "get_backend", lambda: _B())

    with pytest.raises(RuntimeError) as exc_info:
        backend.generate("prompt")

    message = str(exc_info.value)
    assert "***REDACTED***" in message
    assert "hunter2" not in message
