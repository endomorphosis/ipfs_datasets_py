"""Causal ablation tests for trusted Hammer/Leanstral proof feedback."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ipfs_datasets_py.logic.integration.reasoning.legal_ir_proof_feedback import (
    ProofFeedbackVersions,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    build_us_code_sample,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder,
    LEGAL_IR_VIEW_FAMILIES,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_feedback_ablation import (
    HAMMER_ONLY_ARM,
    NO_FEEDBACK_ARM,
    PROOF_FEEDBACK_ABLATION_ARMS,
    PROOF_FEEDBACK_ABLATION_REPORT_SCHEMA_VERSION,
    SHUFFLED_LABEL_CONTROL_ARM,
    VERIFIED_LEANSTRAL_HAMMER_ARM,
    ProofFeedbackAblationConfig,
    run_proof_feedback_ablation,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.trusted_feedback_trainer import (
    TrustedFeedbackTrainer,
    TrustedFeedbackTrainerConfig,
)


def _versions() -> ProofFeedbackVersions:
    return ProofFeedbackVersions(
        compiler_version="ablation-compiler-v1",
        solver_toolchain_version="z3-ablation-v1",
        lean_toolchain_version="lean-ablation-v1",
        theorem_registry_version="theorems-ablation-v1",
    )


def _samples():
    train = build_us_code_sample(
        title="5",
        section="ablation-train",
        text="The agency shall publish notice unless a verified exception applies.",
    )
    holdout = build_us_code_sample(
        title="5",
        section="ablation-holdout",
        text="An officer may inspect a record after receiving approval.",
    )
    return train, holdout


def _hammer(sample_id: str, versions: ProofFeedbackVersions) -> Mapping[str, Any]:
    return {
        "accepted": True,
        "backend_statuses": {"z3": "proved"},
        "guidance_id": "hammer-ablation-feedback",
        "legal_ir_view": "deontic.ir",
        "partition": "train",
        "proof_checked": True,
        "proof_feedback_version_fingerprint": versions.fingerprint,
        "proved": True,
        "reconstruction_status": "verified",
        "sample_id": sample_id,
        "schema_version": "legal-ir-hammer-guidance-v1",
        "source": "hammer_verified_guidance",
        "target_component": "deontic.ir",
        "trusted": True,
    }


def _leanstral(sample_id: str, versions: ProofFeedbackVersions) -> Mapping[str, Any]:
    return {
        "accepted": True,
        "guidance_id": "leanstral-ablation-feedback",
        "leanstral_verified": True,
        "legal_ir_view": "deontic.ir",
        "partition": "train",
        "proof_feedback_version_fingerprint": versions.fingerprint,
        "sample_id": sample_id,
        "source": "leanstral_shadow_proof",
        "target_component": "deontic.ir",
        "trusted": True,
    }


def _evaluator(
    _autoencoder: AdaptiveModalAutoencoder,
    _holdout: Sequence[Any],
    arm: str,
    repeat_index: int,
) -> Mapping[str, Any]:
    ce_by_arm = {
        NO_FEEDBACK_ARM: 0.82 + repeat_index * 0.01,
        HAMMER_ONLY_ARM: 0.74 + repeat_index * 0.01,
        VERIFIED_LEANSTRAL_HAMMER_ARM: 0.55 + repeat_index * 0.01,
        SHUFFLED_LABEL_CONTROL_ARM: 0.78 + repeat_index * 0.01,
    }
    ce = ce_by_arm[arm]
    family_metrics = {}
    for offset, family in enumerate(LEGAL_IR_VIEW_FAMILIES):
        family_ce = ce + offset * 0.001
        family_metrics[family] = {
            "artifact_count": 1,
            "autoencoder_cosine_similarity": max(0.0, 1.0 - family_ce / 2.0),
            "autoencoder_cross_entropy_loss": family_ce,
            "hammer_proof_success_rate": 0.7 if arm == VERIFIED_LEANSTRAL_HAMMER_ARM else 0.5,
            "ir_cosine_similarity": max(0.0, 1.0 - family_ce / 2.5),
            "ir_cross_entropy_loss": family_ce + 0.04,
            "observed_metrics": [
                "autoencoder_cosine_similarity",
                "autoencoder_cross_entropy_loss",
                "hammer_proof_success_rate",
                "ir_cosine_similarity",
                "ir_cross_entropy_loss",
                "reconstruction_success_rate",
                "source_copy_penalty",
                "symbolic_validity_success_rate",
            ],
            "reconstruction_success_rate": 0.95,
            "sample_count": 1,
            "source_copy_penalty": 0.0,
            "symbolic_validity_success_rate": 1.0,
        }
    return {
        "autoencoder_cross_entropy_loss": ce,
        "legal_ir_view_cross_entropy_loss": ce,
        "reconstruction_loss": 0.05,
        "source_copy_penalty": 0.0,
        "symbolic_validity_success_rate": 1.0,
        "view_family_metrics": family_metrics,
    }


def test_ablation_runs_all_matched_arms_and_gates_trainer_writes() -> None:
    train, holdout = _samples()
    versions = _versions()
    autoencoder = AdaptiveModalAutoencoder()

    report = run_proof_feedback_ablation(
        autoencoder,
        [train],
        [holdout],
        hammer_feedback=[_hammer(train.sample_id, versions)],
        leanstral_feedback=[_leanstral(train.sample_id, versions)],
        expected_versions=versions,
        config=ProofFeedbackAblationConfig(
            holdout_id="fixed-proof-feedback-holdout",
            minimum_improvement=0.02,
            repeat_count=2,
        ),
        metric_evaluator=_evaluator,
    )

    payload = report.to_dict()
    assert report.report_schema_version == PROOF_FEEDBACK_ABLATION_REPORT_SCHEMA_VERSION
    assert payload["schema_version"] == "legal-ir-trusted-feedback-ablation-v1"
    assert payload["arms"] == list(PROOF_FEEDBACK_ABLATION_ARMS)
    assert report.production_weight_writes_allowed is True
    assert report.heldout_improvement > 0.02
    assert {result.arm for result in report.arm_results} == set(PROOF_FEEDBACK_ABLATION_ARMS)
    assert all(result.training_sample_ids == (train.sample_id,) for result in report.arm_results)
    assert all(result.heldout_sample_ids == (holdout.sample_id,) for result in report.arm_results)
    assert train.sample_id not in report.heldout_sample_ids
    assert report.per_family_deltas[VERIFIED_LEANSTRAL_HAMMER_ARM]["deontic"][
        "learned_ir"
    ]["score_delta"] > 0.0
    assert set(
        report.per_family_deltas[VERIFIED_LEANSTRAL_HAMMER_ARM]["deontic"]
    ) == {"anti_copy", "compiler_ir", "learned_ir", "proof", "reconstruction"}
    assert report.repeat_control_margins[0][
        f"{VERIFIED_LEANSTRAL_HAMMER_ARM}_vs_{HAMMER_ONLY_ARM}"
    ] > 0.02
    assert report.repeat_control_margins[0][
        f"{VERIFIED_LEANSTRAL_HAMMER_ARM}_vs_{SHUFFLED_LABEL_CONTROL_ARM}"
    ] > 0.02

    trainer = TrustedFeedbackTrainer(
        AdaptiveModalAutoencoder(),
        expected_versions=versions,
        config=TrustedFeedbackTrainerConfig(production_weight_writes_enabled=True),
    )
    update = trainer.train(
        [_hammer(train.sample_id, versions), _leanstral(train.sample_id, versions)],
        {train.sample_id: train},
        ablation_evidence=report,
    )

    assert update.applied_count == 2
    assert update.write_to_autoencoder_weights is True
    assert update.block_reasons == {}


def test_ablation_blocks_when_correct_labels_do_not_beat_shuffled_control() -> None:
    train, holdout = _samples()
    versions = _versions()

    def tied_shuffled_evaluator(
        autoencoder: AdaptiveModalAutoencoder,
        holdout_samples: Sequence[Any],
        arm: str,
        repeat_index: int,
    ) -> Mapping[str, Any]:
        metrics = dict(_evaluator(autoencoder, holdout_samples, arm, repeat_index))
        if arm == SHUFFLED_LABEL_CONTROL_ARM:
            metrics["legal_ir_view_cross_entropy_loss"] = 0.54 + repeat_index * 0.01
            metrics["autoencoder_cross_entropy_loss"] = metrics[
                "legal_ir_view_cross_entropy_loss"
            ]
        return metrics

    report = run_proof_feedback_ablation(
        AdaptiveModalAutoencoder(),
        [train],
        [holdout],
        hammer_feedback=[_hammer(train.sample_id, versions)],
        leanstral_feedback=[_leanstral(train.sample_id, versions)],
        expected_versions=versions,
        config=ProofFeedbackAblationConfig(
            holdout_id="fixed-proof-feedback-holdout",
            minimum_improvement=0.02,
            repeat_count=2,
        ),
        metric_evaluator=tied_shuffled_evaluator,
    )

    assert report.production_weight_writes_allowed is False
    assert "verified_feedback_not_better_than_shuffled_control" in report.block_reasons
