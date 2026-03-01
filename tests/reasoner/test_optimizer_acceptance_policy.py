from __future__ import annotations

from ipfs_datasets_py.processors.legal_data.reasoner.optimizer_policy import build_optimizer_acceptance_decision


def _report(global_mean: float, deontic: float, fol: float) -> dict:
    return {
        "summary": {
            "semantic_similarity_final_decoded_mean": global_mean,
            "semantic_similarity_by_modality": {
                "deontic": deontic,
                "fol": fol,
            },
            "semantic_similarity_floors": {
                "deontic": 0.90,
                "fol": 0.90,
            },
        }
    }


def test_optimizer_policy_accepts_when_gain_and_floors_pass() -> None:
    baseline = _report(0.93, 0.92, 0.91)
    candidate = _report(0.95, 0.94, 0.92)

    out = build_optimizer_acceptance_decision(
        baseline,
        candidate,
        min_gain_threshold=0.01,
        max_modality_regression=0.0,
    )

    assert out["summary"]["accepted"] is True
    assert out["summary"]["failure_count"] == 0


def test_optimizer_policy_rejects_on_floor_or_regression_failure() -> None:
    baseline = _report(0.95, 0.94, 0.93)
    candidate = _report(0.94, 0.89, 0.92)

    out = build_optimizer_acceptance_decision(
        baseline,
        candidate,
        min_gain_threshold=0.0,
        max_modality_regression=0.0,
    )

    assert out["summary"]["accepted"] is False
    assert out["summary"]["failure_count"] >= 1
    assert out["audit_record"]["decision"] == "rejected"
