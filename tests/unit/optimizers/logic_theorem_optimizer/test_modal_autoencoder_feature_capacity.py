"""Contracts for per-group, evidence-aware sparse-tail capacity."""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    ModalAutoencoderTrainingState,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_feature_capacity import (
    ACCEPTED_STATE_V2,
    DEFAULT_FEATURE_CAPACITY_BUDGETS,
    EVIDENCE_AWARE_SPARSE_TAIL_V1,
    CapacityEvidence,
    FeatureCapacityFamily,
    FeatureCapacityPolicy,
    UnknownCapacityGroupError,
    apply_modal_autoencoder_feature_capacity,
    select_sparse_tail,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_feature_transfer import (
    LegacyFeatureTransferConfig,
    MODAL_AUTOENCODER_EVIDENCE_AWARE_FEATURE_TRANSFER_SCHEMA_VERSION,
    transfer_legacy_autoencoder_features,
)


def _strong(**overrides: object) -> CapacityEvidence:
    values = {
        "activation_frequency": 1.0,
        "recency": 1.0,
        "held_out_loss_contribution": 1.0,
        "trusted_proof_impact": 1.0,
        "migration_confidence": 1.0,
    }
    values.update(overrides)
    return CapacityEvidence(**values)


def test_required_capacity_families_have_distinct_explicit_budgets() -> None:
    assert set(DEFAULT_FEATURE_CAPACITY_BUDGETS) == {
        family.value for family in FeatureCapacityFamily
    }
    assert len(set(DEFAULT_FEATURE_CAPACITY_BUDGETS.values())) > 1
    assert all(value >= 0 for value in DEFAULT_FEATURE_CAPACITY_BUDGETS.values())

    policy = FeatureCapacityPolicy.evidence_aware(
        group_budgets={
            "feature": 3,
            FeatureCapacityFamily.PROOF_FEEDBACK.value: 7,
        }
    )
    assert policy.budget_for("feature") == 3
    assert policy.budget_for("proof_feedback") == 7
    assert policy.budget_for(FeatureCapacityFamily.PROOF_FEEDBACK) == 7
    assert policy.mode == EVIDENCE_AWARE_SPARSE_TAIL_V1


def test_evidence_score_is_bounded_combined_and_ties_are_reproducible() -> None:
    policy = FeatureCapacityPolicy.evidence_aware(
        group_budgets={"feature": 2}
    )
    evidence = {
        "alpha": CapacityEvidence(
            activation_frequency=99.0,
            recency=1.0,
            held_out_loss_contribution=1.0,
            trusted_proof_impact=1.0,
            migration_confidence=1.0,
            semantic_family="deontic",
        ),
        "bravo": _strong(semantic_family="frame_logic"),
        "charlie": _strong(semantic_family="deontic"),
    }

    first = select_sparse_tail(
        "feature", evidence, evidence=evidence, policy=policy
    )
    second = select_sparse_tail(
        "feature", reversed(tuple(evidence)), evidence=evidence, policy=policy
    )

    assert first.retained_keys == ("alpha", "bravo")
    assert second.retained_keys == first.retained_keys
    assert first.report == second.report
    assert first.report["boundary_tie"] is True
    assert first.report["tie_break_count"] == 2
    assert first.report["family_reports"]["deontic"] == {
        "candidate_count": 2,
        "evicted_count": 1,
        "retained_count": 1,
    }
    assert all(
        value <= len(first.retained_keys)
        for value in first.report["retained_component_totals"].values()
    )


def test_unsafe_signal_can_never_win_or_leak_into_the_report() -> None:
    policy = FeatureCapacityPolicy.evidence_aware(
        group_budgets={
            "proof_feedback": 1,
            "compiler_guidance": 1,
            "embeddings": 1,
        }
    )
    rejected = select_sparse_tail(
        "proof_feedback",
        ("trusted-proof", "rejected-secret-proof"),
        evidence={
            "trusted-proof": _strong(),
            "rejected-secret-proof": _strong(rejected_proof_output=True),
        },
        policy=policy,
    )
    unsigned = select_sparse_tail(
        "compiler_guidance",
        ("signed", "unsigned-secret-guidance"),
        evidence={
            "signed": _strong(guidance_signed=True),
            "unsigned-secret-guidance": _strong(guidance_signed=False),
        },
        policy=policy,
    )
    source = select_sparse_tail(
        "embeddings",
        ("semantic-feature", "raw source text that must not survive"),
        evidence={
            "semantic-feature": _strong(),
            "raw source text that must not survive": _strong(),
        },
        policy=policy,
    )

    assert rejected.retained_keys == ("trusted-proof",)
    assert unsigned.retained_keys == ("signed",)
    assert source.retained_keys == ("semantic-feature",)
    assert rejected.report["exclusions"] == {"rejected_proof_output": 1}
    assert unsigned.report["exclusions"] == {"unsigned_guidance": 1}
    assert source.report["exclusions"] == {"source_text_memorization": 1}
    serialized = json.dumps(
        [rejected.report, unsigned.report, source.report], sort_keys=True
    )
    assert "secret" not in serialized


def test_coupled_state_rows_are_retained_or_evicted_atomically() -> None:
    state = ModalAutoencoderTrainingState(
        feature_embedding_weights={
            "alpha": [1.0],
            "bravo": [2.0],
            "charlie": [3.0],
        },
        feature_family_logits={
            "alpha": {"deontic": 1.0},
            "bravo": {"deontic": 2.0},
            "charlie": {"deontic": 3.0},
        },
        feature_legal_ir_view_logits={
            "alpha": {"deontic.ir": 1.0},
            "bravo": {"deontic.ir": 2.0},
            "charlie": {"deontic.ir": 3.0},
        },
    )
    policy = FeatureCapacityPolicy.evidence_aware(
        group_budgets={"feature": 2},
        preserve_accepted_keys=False,
    )
    evidence = {
        "feature": {
            "alpha": CapacityEvidence(activation_frequency=0.1),
            "bravo": CapacityEvidence(activation_frequency=0.8),
            "charlie": CapacityEvidence(activation_frequency=0.9),
        }
    }

    result = apply_modal_autoencoder_feature_capacity(
        state,
        policy=policy,
        evidence_by_group=evidence,
    )

    expected = {"bravo", "charlie"}
    assert set(result.state.feature_embedding_weights) == expected
    assert set(result.state.feature_family_logits) == expected
    assert set(result.state.feature_legal_ir_view_logits) == expected
    assert set(state.feature_embedding_weights) == {
        "alpha",
        "bravo",
        "charlie",
    }
    assert result.report["groups"]["feature"]["evicted_count"] == 1
    assert result.report["family_reports"]["embeddings"]["evicted_count"] == 1


def test_accepted_state_v2_is_an_explicit_exact_zero_risk_baseline() -> None:
    source = ModalAutoencoderTrainingState(
        feature_family_logits={
            "legacy": {"deontic": 100.0},
            "accepted": {"deontic": 100.0},
        }
    )
    accepted = ModalAutoencoderTrainingState(
        feature_family_logits={"accepted": {"temporal": 0.25}}
    )

    result = transfer_legacy_autoencoder_features(
        source,
        accepted,
        config=LegacyFeatureTransferConfig(
            max_entries_per_group=1,
            minimum_source_signal_coverage=1.0,
        ),
        capacity_policy=FeatureCapacityPolicy(
            mode=ACCEPTED_STATE_V2,
            group_budgets={"feature": 0},
        ),
        capacity_evidence={"feature": {"legacy": _strong()}},
    )

    assert result.accepted is True
    assert result.state.to_dict() == accepted.generalizable_copy().to_dict()
    assert result.report["policy"] == ACCEPTED_STATE_V2
    assert result.report["schema_version"] == (
        MODAL_AUTOENCODER_EVIDENCE_AWARE_FEATURE_TRANSFER_SCHEMA_VERSION
    )
    assert result.report["zero_risk_baseline"] is True
    selection = result.report["capacity_decisions"]["feature"]
    assert selection["budget_enforced"] is False
    assert selection["zero_risk_baseline"] is True


def test_transfer_imports_only_evidence_backed_tail_and_preserves_coupling() -> None:
    source = ModalAutoencoderTrainingState(
        predicate_argument_embedding_weights={
            "useful": [2.0],
            "stale": [9.0],
        },
        predicate_argument_family_logits={
            "useful": {"deontic": 2.0},
            "stale": {"deontic": 9.0},
        },
        predicate_argument_legal_ir_view_logits={
            "useful": {"kg": 2.0},
            "stale": {"kg": 9.0},
        },
    )
    target = ModalAutoencoderTrainingState(
        predicate_argument_embedding_weights={"accepted": [0.5]},
        predicate_argument_family_logits={
            "accepted": {"deontic": 0.5}
        },
        predicate_argument_legal_ir_view_logits={
            "accepted": {"kg": 0.5}
        },
    )
    policy = FeatureCapacityPolicy.evidence_aware(
        group_budgets={"predicate_argument": 2}
    )

    result = transfer_legacy_autoencoder_features(
        source,
        target,
        config=LegacyFeatureTransferConfig(
            max_entries_per_group=99,
            minimum_source_signal_coverage=0.0,
            transfer_source_embedding_weights=True,
        ),
        capacity_policy=policy,
        capacity_evidence={
            "predicate_argument": {
                "useful": _strong(),
                # A larger raw tensor cannot substitute for promotion evidence.
                "stale": CapacityEvidence(),
            }
        },
    )

    expected = {"accepted", "useful"}
    assert set(result.state.predicate_argument_embedding_weights) == expected
    assert set(result.state.predicate_argument_family_logits) == expected
    assert (
        set(result.state.predicate_argument_legal_ir_view_logits) == expected
    )
    selection = result.report["capacity_decisions"]["predicate_argument"]
    assert selection["exclusions"] == {"missing_positive_evidence": 1}
    assert selection["budget"] == 2


def test_unknown_groups_and_invalid_pinned_budgets_fail_closed() -> None:
    with pytest.raises(UnknownCapacityGroupError, match="unknown"):
        FeatureCapacityPolicy.evidence_aware(
            group_budgets={"mystery_parameters": 1}
        )
    with pytest.raises(UnknownCapacityGroupError, match="unknown"):
        select_sparse_tail("mystery_parameters", (), policy=FeatureCapacityPolicy())

    policy = FeatureCapacityPolicy.evidence_aware(
        group_budgets={"feature": 1},
        preserve_accepted_keys=True,
    )
    with pytest.raises(ValueError, match="pinned accepted"):
        select_sparse_tail(
            "feature",
            ("one", "two"),
            accepted_keys=("one", "two"),
            policy=policy,
        )
