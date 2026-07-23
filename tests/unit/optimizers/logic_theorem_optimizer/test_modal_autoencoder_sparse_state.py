"""Sparse-state compatibility checks used by capacity-policy validation."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    ModalAutoencoderTrainingState,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_feature_capacity import (
    CapacityEvidence,
    FeatureCapacityPolicy,
)


def test_state_compaction_accepts_per_group_policy_without_changing_old_api() -> None:
    state = ModalAutoencoderTrainingState(
        feature_family_logits={
            "alpha": {"deontic": 1.0},
            "bravo": {"deontic": 2.0},
        },
        legal_ir_view_logits={
            "deontic": 1.0,
            "frame": 2.0,
        },
    )
    policy = FeatureCapacityPolicy.evidence_aware(
        group_budgets={"feature": 1, "legal_ir_view": 2}
    )

    assert state.generalizable_capacity_exceeded(
        capacity_policy=policy
    ) is True
    report = state.compact_generalizable_capacity(
        capacity_policy=policy,
        capacity_evidence={
            "feature": {
                "alpha": CapacityEvidence(activation_frequency=0.1),
                "bravo": CapacityEvidence(activation_frequency=0.9),
            },
            "legal_ir_view": {
                "deontic": CapacityEvidence(activation_frequency=0.5),
                "frame": CapacityEvidence(activation_frequency=0.5),
            },
        },
    )

    assert set(state.feature_family_logits) == {"bravo"}
    assert set(state.legal_ir_view_logits) == {"deontic", "frame"}
    assert report["groups"]["feature"]["budget"] == 1
    assert report["groups"]["legal_ir_view"]["budget"] == 2
    assert state.generalizable_capacity_exceeded(
        capacity_policy=policy
    ) is False


def test_zero_risk_sparse_state_policy_is_non_mutating() -> None:
    state = ModalAutoencoderTrainingState(
        semantic_slot_family_logits={
            "actor": {"deontic": 0.5},
            "action": {"deontic": 0.75},
        }
    )
    before = state.to_dict()
    baseline_policy = FeatureCapacityPolicy(
        mode="accepted_state_v2",
        group_budgets={"semantic_slot": 0},
    )

    report = state.compact_generalizable_capacity(
        capacity_policy=baseline_policy
    )

    assert state.to_dict() == before
    assert state.generalizable_capacity_exceeded(
        capacity_policy=baseline_policy
    ) is False
    assert report["compacted"] is False
    assert report["policy"]["mode"] == "accepted_state_v2"
