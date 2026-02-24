"""Tests for typed exception handling in neural-symbolic prover adapters."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import neural_symbolic_prover as nsp


def _build_prover(monkeypatch: pytest.MonkeyPatch) -> nsp.NeuralSymbolicHybridProver:
    monkeypatch.setattr(
        nsp.NeuralSymbolicHybridProver,
        "_init_neural_component",
        lambda self: setattr(self, "neural_component", None),
    )
    monkeypatch.setattr(
        nsp.NeuralSymbolicHybridProver,
        "_init_symbolic_component",
        lambda self: setattr(self, "symbolic_component", None),
    )
    monkeypatch.setattr(
        nsp.NeuralSymbolicHybridProver,
        "_init_embedding_component",
        lambda self: setattr(self, "embedding_component", None),
    )
    return nsp.NeuralSymbolicHybridProver()


def test_run_neural_prover_handles_typed_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    prover = _build_prover(monkeypatch)

    class BrokenNeural:
        def prove(self, *args, **kwargs):
            raise RuntimeError("neural fail")

    prover.neural_component = BrokenNeural()
    result = prover._run_neural_prover("P(a)", context=None, timeout=0.1)

    assert result is not None
    assert result.is_valid is False
    assert result.error_message == "neural fail"


def test_run_neural_prover_does_not_swallow_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    prover = _build_prover(monkeypatch)

    class BrokenNeural:
        def prove(self, *args, **kwargs):
            raise KeyboardInterrupt()

    prover.neural_component = BrokenNeural()

    with pytest.raises(KeyboardInterrupt):
        prover._run_neural_prover("P(a)", context=None, timeout=0.1)


def test_run_symbolic_prover_handles_typed_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    prover = _build_prover(monkeypatch)
    prover.symbolic_component = object()
    result = prover._run_symbolic_prover("P(a)", context=None, timeout=0.1)

    assert result is not None
    assert result.is_valid is False
    assert result.error_message
