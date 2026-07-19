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


def test_router_uses_sound_weaker_fallback_for_kd45() -> None:
    result = ModalProverRouter().route(formula=None, system=ModalSystem.KD45)

    assert result.status == ModalProverStatus.AVAILABLE
    assert result.system == "KD45"
    assert result.backend == "tdfol_modal_tableaux_fallback"
    assert result.metadata["fallback_system"] == "D"
    assert result.metadata["fallback_sound_when_proved"] is True


def test_router_returns_compile_only_for_frame_bm25() -> None:
    result = ModalProverRouter().route(formula=None, system="FRAME_BM25")

    assert result.status == ModalProverStatus.AVAILABLE
    assert result.backend == "frame_bm25_compile_only"
    assert result.metadata["registered"] is True
    assert result.metadata["validation_mode"] == "compile_only"


def test_router_returns_compile_only_for_ltl() -> None:
    result = ModalProverRouter().route(formula=None, system="LTL")

    assert result.status == ModalProverStatus.AVAILABLE
    assert result.backend == "ltl_compile_only"
    assert result.metadata["registered"] is True
    assert result.metadata["validation_mode"] == "compile_only"
