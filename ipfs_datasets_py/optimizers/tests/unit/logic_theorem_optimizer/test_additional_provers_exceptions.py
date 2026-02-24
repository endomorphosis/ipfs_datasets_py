"""Tests for typed exception handling in additional prover adapters."""

from __future__ import annotations

import subprocess

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import additional_provers as ap


def test_isabelle_prove_handles_typed_runtime_error(monkeypatch) -> None:
    monkeypatch.setattr(ap.IsabelleProver, "_check_availability", lambda self: True)
    monkeypatch.setattr(ap.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("run fail")))

    prover = ap.IsabelleProver(enable_cache=False)
    result = prover.prove("True", timeout=0.1)

    assert result.is_proved is False
    assert result.timeout is False
    assert result.error_message == "run fail"


def test_vampire_prove_fof_handles_typed_runtime_error(monkeypatch) -> None:
    monkeypatch.setattr(ap.VampireProver, "_check_availability", lambda self: True)
    monkeypatch.setattr(ap.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("run fail")))

    prover = ap.VampireProver(enable_cache=False)
    result = prover.prove_fof("fof(a1,axiom,p(a)).", timeout=0.1)

    assert result.is_proved is False
    assert result.timeout is False
    assert result.error_message == "run fail"


def test_eprover_prove_cnf_timeout_path_still_works(monkeypatch) -> None:
    monkeypatch.setattr(ap.EProver, "_check_availability", lambda self: True)
    monkeypatch.setattr(
        ap.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd="eprover", timeout=0.1)),
    )

    prover = ap.EProver(enable_cache=False)
    result = prover.prove_cnf("cnf(a1,axiom,p(a)).", timeout=0.1)

    assert result.is_proved is False
    assert result.timeout is True
