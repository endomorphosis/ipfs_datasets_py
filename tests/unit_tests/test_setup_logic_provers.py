"""Setup-level coverage for managed theorem-prover portfolios."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_INSTALL_PATH = Path(__file__).resolve().parents[2] / "scripts" / "setup" / "install.py"
_SPEC = importlib.util.spec_from_file_location("ipfs_setup_install", _INSTALL_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_INSTALL = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_INSTALL)
_LOGIC_PROVER_ENV_FLAGS = _INSTALL._LOGIC_PROVER_ENV_FLAGS
_logic_prover_install_args = _INSTALL._logic_prover_install_args


def _clear_prover_setup_env(monkeypatch) -> None:
    names = {
        "IPFS_DATASETS_PY_ALLOW_SUDO_FOR_PROVERS",
        "IPFS_DATASETS_PY_AUTO_INSTALL_ALL_PROVERS",
        "IPFS_DATASETS_PY_AUTO_INSTALL_PROVER_PORTFOLIO",
        "IPFS_DATASETS_PY_AUTO_INSTALL_PROVER_PORTFOLIOS",
        "IPFS_DATASETS_PY_PROVER_INSTALL_STRICT",
        *(item[0] for item in _LOGIC_PROVER_ENV_FLAGS),
    }
    for name in names:
        monkeypatch.delenv(name, raising=False)


def test_default_explicit_setup_uses_complete_managed_portfolio(monkeypatch) -> None:
    _clear_prover_setup_env(monkeypatch)

    args, portfolios = _logic_prover_install_args()

    assert portfolios == ("legal_ir_full",)
    assert args[args.index("--portfolio") + 1] == "legal_ir_full"
    assert "--symbolicai" in args


def test_explicit_generation_profile_can_add_and_exclude_solvers(
    monkeypatch,
) -> None:
    _clear_prover_setup_env(monkeypatch)
    monkeypatch.setenv(
        "IPFS_DATASETS_PY_AUTO_INSTALL_PROVER_PORTFOLIOS",
        "legal_ir_generation",
    )
    monkeypatch.setenv("IPFS_DATASETS_PY_AUTO_INSTALL_APALACHE", "1")
    monkeypatch.setenv("IPFS_DATASETS_PY_AUTO_INSTALL_CVC5", "0")
    monkeypatch.setenv("IPFS_DATASETS_PY_PROVER_INSTALL_STRICT", "1")

    args, portfolios = _logic_prover_install_args()

    assert portfolios == ("legal_ir_generation",)
    assert "--apalache" in args
    exclude_index = args.index("--exclude")
    assert args[exclude_index + 1] == "cvc5"
    assert "--symbolicai" not in args
    assert "--strict" in args


def test_unknown_setup_portfolio_fails_before_starting_installer(
    monkeypatch,
) -> None:
    _clear_prover_setup_env(monkeypatch)
    monkeypatch.setenv(
        "IPFS_DATASETS_PY_AUTO_INSTALL_PROVER_PORTFOLIOS",
        "legal_ir_generation,not_a_portfolio",
    )

    with pytest.raises(ValueError, match="not_a_portfolio"):
        _logic_prover_install_args()
