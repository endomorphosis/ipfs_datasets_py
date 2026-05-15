"""Regression tests for theorem prover installer wiring."""

from __future__ import annotations

import subprocess
import importlib.util
from pathlib import Path

import pytest


def test_packaged_installer_detects_user_local_bins(monkeypatch, tmp_path) -> None:
    from ipfs_datasets_py.logic.integration.bridges import prover_installer

    binary = tmp_path / "lean"
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o755)
    monkeypatch.setattr(prover_installer, "_common_bin_dirs", lambda: [tmp_path])
    monkeypatch.setattr(prover_installer.shutil, "which", lambda _: None)

    assert prover_installer._which("lean") == str(binary)


def test_packaged_pip_install_retries_user_install_after_system_failure(monkeypatch) -> None:
    from ipfs_datasets_py.logic.integration.bridges import prover_installer

    calls: list[list[str]] = []

    def fake_run(cmd, capture_output, text):
        calls.append(list(cmd))
        if "--user" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 1, "", "externally-managed-environment")

    monkeypatch.setattr(prover_installer.subprocess, "run", fake_run)
    monkeypatch.setattr(prover_installer.sys, "prefix", "/usr")
    monkeypatch.setattr(prover_installer.sys, "base_prefix", "/usr")

    assert prover_installer._pip_install("z3-solver>=4.12.0,<5.0.0", strict=False) is True
    assert calls[0][-1] == "z3-solver>=4.12.0,<5.0.0"
    assert "--user" in calls[1]


def test_setup_installer_accepts_symbolicai_flag(monkeypatch) -> None:
    installer_path = (
        Path(__file__).resolve().parents[4]
        / "scripts"
        / "setup"
        / "ipfs_prover_installer.py"
    )
    spec = importlib.util.spec_from_file_location("ipfs_prover_installer_test", installer_path)
    assert spec is not None and spec.loader is not None
    ipfs_prover_installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ipfs_prover_installer)

    called: list[str] = []
    monkeypatch.setattr(
        ipfs_prover_installer,
        "ensure_symbolicai",
        lambda **kwargs: called.append("symbolicai") or True,
    )

    assert ipfs_prover_installer.main(["--symbolicai", "--yes"]) == 0
    assert called == ["symbolicai"]


def test_proof_execution_engine_uses_common_user_bin_dirs(monkeypatch, tmp_path) -> None:
    from ipfs_datasets_py.logic.integration.reasoning.proof_execution_engine import (
        ProofExecutionEngine,
    )

    binary = tmp_path / "z3"
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o755)
    engine = ProofExecutionEngine.__new__(ProofExecutionEngine)
    engine.prover_binaries = {}
    monkeypatch.setattr(engine, "_common_bin_dirs", lambda: [tmp_path])
    monkeypatch.setattr("shutil.which", lambda _: None)

    assert engine._prover_cmd("z3") == str(binary)


def test_lazy_installer_is_opt_in(monkeypatch) -> None:
    from ipfs_datasets_py.logic.external_provers import lazy_installer

    lazy_installer.reset_lazy_install_attempts()
    monkeypatch.delenv("IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS", raising=False)
    monkeypatch.delenv("IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS", raising=False)
    monkeypatch.delenv("IPFS_DATASETS_PY_MINIMAL_IMPORTS", raising=False)
    monkeypatch.delenv("IPFS_DATASETS_PY_BENCHMARK", raising=False)

    assert lazy_installer.lazy_installs_enabled() is False
    assert lazy_installer.prover_lazy_install_enabled("z3") is False


def test_lazy_installer_calls_packaged_installer_once(monkeypatch) -> None:
    from ipfs_datasets_py.logic.external_provers import lazy_installer
    from ipfs_datasets_py.logic.integration.bridges import prover_installer

    calls: list[dict[str, object]] = []
    lazy_installer.reset_lazy_install_attempts()
    monkeypatch.setenv("IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS", "1")
    monkeypatch.delenv("IPFS_DATASETS_PY_MINIMAL_IMPORTS", raising=False)
    monkeypatch.delenv("IPFS_DATASETS_PY_BENCHMARK", raising=False)
    monkeypatch.setattr(
        prover_installer,
        "ensure_z3",
        lambda **kwargs: calls.append(dict(kwargs)) or True,
    )

    assert lazy_installer.lazy_install_prover("z3") is True
    assert lazy_installer.lazy_install_prover("z3") is False
    assert calls == [{"yes": True, "strict": False}]


def test_lazy_installer_keeps_coq_conservative_by_default(monkeypatch) -> None:
    from ipfs_datasets_py.logic.external_provers import lazy_installer

    monkeypatch.setenv("IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS", "1")
    monkeypatch.delenv("IPFS_DATASETS_PY_LAZY_INSTALL_COQ", raising=False)
    monkeypatch.delenv("IPFS_DATASETS_PY_AUTO_INSTALL_COQ", raising=False)
    monkeypatch.delenv("IPFS_DATASETS_PY_MINIMAL_IMPORTS", raising=False)
    monkeypatch.delenv("IPFS_DATASETS_PY_BENCHMARK", raising=False)

    assert lazy_installer.prover_lazy_install_enabled("coq") is False
    monkeypatch.setenv("IPFS_DATASETS_PY_LAZY_INSTALL_COQ", "1")
    assert lazy_installer.prover_lazy_install_enabled("coq") is True


def test_z3_bridge_reimports_after_lazy_install(monkeypatch) -> None:
    from ipfs_datasets_py.logic.external_provers import lazy_installer
    from ipfs_datasets_py.logic.external_provers.smt import z3_prover_bridge

    class FakeZ3:
        pass

    imports: list[str] = []
    installs: list[str] = []

    def fake_import_module(module_name: str):
        imports.append(module_name)
        if len(imports) == 1:
            raise ImportError(module_name)
        return FakeZ3()

    monkeypatch.setattr(z3_prover_bridge, "Z3_AVAILABLE", False)
    monkeypatch.setattr(z3_prover_bridge, "z3", None)
    monkeypatch.setattr(z3_prover_bridge.importlib, "import_module", fake_import_module)
    monkeypatch.setattr(
        lazy_installer,
        "lazy_install_prover",
        lambda prover, **kwargs: installs.append(prover) or True,
    )

    assert z3_prover_bridge._ensure_z3_available() is True
    assert imports == ["z3", "z3"]
    assert installs == ["z3"]


def test_z3_bridge_lazy_install_strict_errors_propagate(monkeypatch) -> None:
    from ipfs_datasets_py.logic.external_provers import lazy_installer
    from ipfs_datasets_py.logic.external_provers.smt import z3_prover_bridge

    monkeypatch.setattr(z3_prover_bridge, "Z3_AVAILABLE", False)
    monkeypatch.setattr(z3_prover_bridge, "z3", None)
    monkeypatch.setattr(
        z3_prover_bridge.importlib,
        "import_module",
        lambda module_name: (_ for _ in ()).throw(ImportError(module_name)),
    )
    monkeypatch.setattr(lazy_installer, "lazy_install_strict", lambda: True)
    monkeypatch.setattr(
        lazy_installer,
        "lazy_install_prover",
        lambda prover, **kwargs: (_ for _ in ()).throw(RuntimeError("install failed")),
    )

    with pytest.raises(RuntimeError, match="install failed"):
        z3_prover_bridge._ensure_z3_available()


def test_router_calls_bridge_availability_recheck(monkeypatch) -> None:
    from ipfs_datasets_py.logic.external_provers import prover_router
    from ipfs_datasets_py.logic.external_provers.smt import z3_prover_bridge

    calls: list[str] = []
    monkeypatch.setattr(
        z3_prover_bridge,
        "_ensure_z3_available",
        lambda: calls.append("z3") or False,
    )

    router = prover_router.ProverRouter(
        enable_z3=True,
        enable_cvc5=False,
        enable_native=False,
        enable_cache=False,
    )

    assert calls == ["z3"]
    assert "z3" not in router.provers
