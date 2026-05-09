"""Tests for modal prover routing."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_prover_router import (
    ModalProverRouter,
    ModalProverStatus,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import ModalSystem


def test_router_reports_tdfol_tableaux_available_without_formula() -> None:
    result = ModalProverRouter().route(formula=None, system=ModalSystem.S5)

    assert result.status == ModalProverStatus.AVAILABLE
    assert result.backend == "tdfol_modal_tableaux"
    assert result.metadata["logic_type"] == "S5"


def test_router_returns_unavailable_for_kd45_until_adapter_exists() -> None:
    result = ModalProverRouter().route(formula=None, system=ModalSystem.KD45)

    assert result.status == ModalProverStatus.UNAVAILABLE
    assert result.system == "KD45"
    assert "no KD/KD45 tableaux adapter" in result.reason


def test_router_returns_unavailable_for_frame_bm25() -> None:
    result = ModalProverRouter().route(formula=None, system="FRAME_BM25")

    assert result.status == ModalProverStatus.UNAVAILABLE
    assert result.metadata["registered"] is False
