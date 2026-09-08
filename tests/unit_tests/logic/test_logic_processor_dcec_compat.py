"""Compatibility coverage for the LogicProcessor DCEC bridge."""

from __future__ import annotations

from types import SimpleNamespace

from ipfs_datasets_py.core_operations.logic_processor import _try_dcec_prove
from ipfs_datasets_py.logic.CEC import native
from ipfs_datasets_py.logic.CEC.provers import ProverManager, ProverStrategy


def test_dcec_bridge_maps_legacy_solver_and_normalizes_unified_result(
    monkeypatch,
) -> None:
    captured = {}

    monkeypatch.setattr(native, "parse_dcec_string", lambda value: value)

    def fake_prove(self, *, formula, axioms, strategy, timeout):
        captured.update(
            formula=formula,
            axioms=axioms,
            strategy=strategy,
            timeout=timeout,
        )
        return SimpleNamespace(
            is_valid=True,
            best_prover="z3",
            total_time=0.25,
        )

    monkeypatch.setattr(ProverManager, "prove", fake_prove)

    result = _try_dcec_prove("goal", ["axiom"], "z3", 7)

    assert captured == {
        "formula": "goal",
        "axioms": ["axiom"],
        "strategy": ProverStrategy.AUTO,
        "timeout": 7,
    }
    assert result == {
        "proved": True,
        "prover_used": "z3",
        "proof_steps": 0,
        "execution_time": 0.25,
    }
