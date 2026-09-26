"""Bridge-off last-run files are not legal-IR lift."""
from __future__ import annotations

import importlib.util
from pathlib import Path


def _review():
    path = (
        Path(__file__).resolve().parents[3]
        / "scripts"
        / "ops"
        / "logic"
        / "review_autoencoder_weight_runs.py"
    )
    spec = importlib.util.spec_from_file_location("review_autoencoder_weight_runs_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_zero_legal_ir_targets_are_not_lift() -> None:
    review = _review()
    payload = {
        "stopped_reason": "no_claimed_todos",
        "final_evaluation": {
            "cross_entropy_loss": 1.5322956228684563,
            "embedding_cosine_similarity": 0.2308001343615965,
            "legal_ir_losses": {},
            "legal_ir_target_count": 0,
        },
        "steps": [{
            "improved": False,
            "validation_cross_entropy_delta": 0.0,
            "validation_cosine_similarity_delta": 0.0,
        }],
    }
    lift = review.lift_from_last_run(payload)
    assert lift["legal_ir_target_count"] == 0
    assert lift["status"] == "bridge_off"
    assert lift["improved"] is False
    assert lift["usable_for_legal_ir"] is False
    assert lift["validation_cross_entropy_delta"] == 0.0


def test_reconstruction_improved_with_bridge_off_is_not_legal_ir_lift() -> None:
    review = _review()
    payload = {
        "stopped_reason": "max_iterations",
        "final_evaluation": {
            "legal_ir_losses": {},
            "legal_ir_target_count": 0,
        },
        "steps": [{
            "improved": True,
            "bridge_loss_signal_count": 0,
            "validation_cross_entropy_delta": 0.016,
            "validation_cosine_similarity_delta": 0.011,
        }],
    }
    lift = review.lift_from_last_run(payload)
    assert lift["status"] == "bridge_off"
    assert lift["usable_for_legal_ir"] is False


def test_bridge_on_without_ir_delta_is_measured_no_lift() -> None:
    review = _review()
    payload = {
        "bridge_names": ["deontic_norms", "fol_tdfol"],
        "final_evaluation": {
            "legal_ir_losses": {"legal_ir_view_cross_entropy_loss": 0.4},
            "legal_ir_target_count": 2,
        },
        "steps": [{
            "improved": True,
            "validation_cosine_similarity_delta": 0.2,
        }],
    }
    lift = review.lift_from_last_run(payload)
    assert lift["status"] == "measured_no_lift"
    assert lift["usable_for_legal_ir"] is False


def test_ir_cosine_delta_is_measured_lift() -> None:
    review = _review()
    payload = {
        "legal_ir_bridge_names": ["deontic_norms"],
        "final_evaluation": {
            "legal_ir_losses": {"legal_ir_view_cross_entropy_loss": 0.4},
            "legal_ir_target_count": 1,
        },
        "steps": [{
            "validation_ir_cross_entropy_delta": 0.01,
            "validation_ir_cosine_delta": 0.02,
        }],
    }
    lift = review.lift_from_last_run(payload)
    assert lift["status"] == "measured_lift"
    assert lift["usable_for_legal_ir"] is True
