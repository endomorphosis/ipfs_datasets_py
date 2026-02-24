"""Tests for typed exception handling in logic theorem LLM backend."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.llm_backend import (
    AccelerateBackend,
    LLMBackendAdapter,
    LLMRequest,
    MockBackend,
)


class _BrokenBackend:
    def generate(self, request: LLMRequest):
        raise ValueError("backend failure")


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
