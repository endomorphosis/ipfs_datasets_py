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
