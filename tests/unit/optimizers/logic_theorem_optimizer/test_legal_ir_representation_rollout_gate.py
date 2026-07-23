"""Supervised rollout gates for learned LegalIR representation promotion."""

from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.ops.legal_ir.hammer_leanstral_rollout_gate import (
    LEGAL_IR_REPRESENTATION_METRICS,
    LEGAL_IR_VIEW_FAMILIES,
    RolloutGateConfig,
    rollout_gate,
)


def _metrics() -> dict[str, float]:
    return {
        "ir_cross_entropy_loss": 0.20,
        "ir_cosine_similarity": 0.80,
        "autoencoder_cross_entropy_loss": 0.30,
        "autoencoder_cosine_similarity": 0.70,
        "symbolic_validity_success_rate": 0.90,
        "hammer_proof_success_rate": 0.80,
        "reconstruction_success_rate": 0.70,
        "source_copy_penalty": 0.10,
    }


def _promotion() -> dict[str, object]:
    family_metrics = {
        family: {
            "baseline": _metrics(),
            "candidate": _metrics(),
            "deltas": {metric: 0.0 for metric in LEGAL_IR_REPRESENTATION_METRICS},
            "guardrails_passed": True,
            "regressions": [],
        }
        for family in LEGAL_IR_VIEW_FAMILIES
    }
    return {
        "schema_version": "legal-ir-learned-guidance-promotion-v1",
        "status": "promoted",
        "promoted": True,
        "promotion_allowed": True,
        "promotion_id": "lir-guidance-promotion-test",
        "block_reasons": [],
        "compiler_commit": "compiler-commit-test",
        "learned_export_id": "lir-feature-export-test",
        "source_export_id": "lir-feature-export-test",
        "learned_export_sha256": "a" * 64,
        "learned_export": {
            "export_id": "lir-feature-export-test",
            "model_state_id": "state-test",
            "sample_count": 8,
            "feature_count": 2,
            "sample_memory_included": False,
            "schema_version": "legal-ir-stable-autoencoder-feature-export-v1",
            "sha256": "a" * 64,
        },
        "proof_receipt_ids": ["proof-receipt-test"],
        "proof_receipts": [
            {
                "receipt_id": "proof-receipt-test",
                "trusted": True,
                "checker": "lean-kernel",
            }
        ],
        "causal_evidence": {
            "fixed_canary_evidence_id": "lir-canary-evidence-test",
            "learned_path_responsive": True,
            "metric_lineage_complete": True,
        },
        "source_copy_checks": {
            "guardrails_passed": True,
            "sample_memory_included": False,
            "unsafe_feature_count": 0,
            "source_copy_regressions": [],
        },
        "activation_state": {
            "activation_allowed": True,
            "active": True,
            "active_promotion_id": "lir-guidance-promotion-test",
            "state": "activated",
        },
        "fixed_canary_binding": {
            "canary_id": "fixed-canary-test",
            "evidence_id": "lir-canary-evidence-test",
            "fixed_sample_set": True,
            "guardrails_passed": True,
        },
        "rollback_metadata": {
            "activation_allowed": True,
            "activation_key": "lir-guidance-promotion-test",
            "canary_evidence_id": "lir-canary-evidence-test",
            "rollback_id": "lir-guidance-rollback-test",
            "schema_version": "legal-ir-learned-guidance-rollback-v1",
            "source_export_id": "lir-feature-export-test",
        },
        "guidance_records": [
            {"view_family": family, "target_component": f"test.{family}"}
            for family in LEGAL_IR_VIEW_FAMILIES
        ],
        "canary_evidence": {
            "canary_id": "fixed-canary-test",
            "evidence_id": "lir-canary-evidence-test",
            "fixed_sample_set": True,
            "guardrails_passed": True,
            "missing_guardrail_evidence": [],
            "metric_regressions": [],
            "source_copy_regressions": [],
            "symbolic_validity_regressions": [],
            "family_metrics": family_metrics,
        },
        "todo_generation_productivity": {
            "baseline": {"seeded": 2, "deduped": 1, "completed": 1},
            "candidate": {"seeded": 2, "deduped": 1, "completed": 1},
        },
    }


def _summary(promotion: dict[str, object] | None = None) -> dict[str, object]:
    summary: dict[str, object] = {
        "cycles": 2,
        "status": "succeeded",
        "latest_validation_ce_delta": 0.0,
        "latest_validation_cosine_delta": 0.0,
        "compiler_ir_validation_last_delta": {
            "compiler_ir_cross_entropy_loss": 0.0,
            "compiler_ir_cosine_similarity": 0.0,
        },
        "latest_compiler_ir_source_copy_reward_hack_penalty": 0.01,
        "latest_daemon_hammer_guidance": {
            "status": "completed",
            "runtime_failure_count": 0,
            "obligation_failure_count": 0,
            "hammer_metrics": {"hammer_backend_unavailable_ratio": 0.0},
        },
        "program_synthesis_seeded": 1,
        "program_synthesis_completed": 1,
    }
    if promotion is not None:
        summary["latest_legal_ir_learned_guidance_promotion"] = promotion
    return summary


def _strict_config(**overrides: object) -> RolloutGateConfig:
    values: dict[str, object] = {
        "require_representation_promotion": True,
        "require_successful_representation_promotion": True,
        "require_complete_representation_evidence": True,
    }
    values.update(overrides)
    return RolloutGateConfig(**values)


def test_supervised_gate_accepts_complete_fixed_canary_promotion() -> None:
    result = rollout_gate(_summary(_promotion()), _strict_config())

    assert result.accepted is True
    assert result.failures == []
    assert result.metrics["representation_promotion_allowed"] is True
    assert result.metrics["representation_fixed_canary_id"] == "fixed-canary-test"
    assert result.metrics["representation_view_families"] == list(LEGAL_IR_VIEW_FAMILIES)
    assert result.metrics["representation_todo_productivity"]["improvement"] == 0.0


@pytest.mark.parametrize(
    ("metric_name", "candidate", "failure_prefix"),
    [
        ("ir_cross_entropy_loss", 0.21, "representation_per_view_ir_metric_regression"),
        ("ir_cosine_similarity", 0.79, "representation_per_view_ir_metric_regression"),
        (
            "autoencoder_cross_entropy_loss",
            0.31,
            "representation_per_view_ir_metric_regression",
        ),
        (
            "autoencoder_cosine_similarity",
            0.69,
            "representation_per_view_ir_metric_regression",
        ),
        (
            "symbolic_validity_success_rate",
            0.89,
            "representation_symbolic_validity_regression",
        ),
        (
            "hammer_proof_success_rate",
            0.79,
            "representation_hammer_proof_rate_regression",
        ),
        (
            "reconstruction_success_rate",
            0.69,
            "representation_reconstruction_rate_regression",
        ),
        (
            "source_copy_penalty",
            0.11,
            "representation_source_copy_penalty_regression",
        ),
    ],
)
def test_gate_recomputes_each_directional_metric_regression(
    metric_name: str,
    candidate: float,
    failure_prefix: str,
) -> None:
    promotion = _promotion()
    family = promotion["canary_evidence"]["family_metrics"]["deontic"]
    family["candidate"][metric_name] = candidate
    # A promoted=True report cannot bypass a recomputed rollout regression.
    family["guardrails_passed"] = True
    family["regressions"] = []

    result = rollout_gate(_summary(promotion), _strict_config())

    assert result.accepted is False
    assert any(item.startswith(failure_prefix) for item in result.failures)


def test_gate_applies_metric_specific_tolerances() -> None:
    promotion = _promotion()
    candidate = promotion["canary_evidence"]["family_metrics"]["deontic"]["candidate"]
    candidate.update(
        {
            "ir_cross_entropy_loss": 0.205,
            "symbolic_validity_success_rate": 0.895,
            "hammer_proof_success_rate": 0.795,
            "reconstruction_success_rate": 0.695,
            "source_copy_penalty": 0.105,
        }
    )

    result = rollout_gate(
        _summary(promotion),
        _strict_config(
            max_per_view_ir_metric_regression=0.005,
            max_symbolic_validity_regression=0.005,
            max_hammer_proof_rate_regression=0.005,
            max_reconstruction_rate_regression=0.005,
            max_source_copy_penalty_regression=0.005,
        ),
    )

    assert result.accepted is True


@pytest.mark.parametrize(
    ("mutate", "failure"),
    [
        (
            lambda value: value["canary_evidence"].update({"canary_id": ""}),
            "representation_fixed_canary_identity_missing",
        ),
        (
            lambda value: value["canary_evidence"].update(
                {"fixed_sample_set": False}
            ),
            "representation_fixed_canary_sample_set_invalid",
        ),
        (
            lambda value: value["canary_evidence"]["family_metrics"]["deontic"][
                "candidate"
            ].pop("hammer_proof_success_rate"),
            "representation_canary_evidence_incomplete:deontic:hammer_proof_success_rate",
        ),
        (
            lambda value: value.pop("todo_generation_productivity"),
            "representation_todo_productivity_evidence_missing",
        ),
    ],
)
def test_promoted_candidate_requires_complete_supervision(
    mutate: object, failure: str
) -> None:
    promotion = _promotion()
    mutate(promotion)

    result = rollout_gate(_summary(promotion), _strict_config())

    assert result.accepted is False
    assert failure in result.failures


def test_gate_rejects_todo_generation_productivity_regression() -> None:
    promotion = _promotion()
    promotion["todo_generation_productivity"] = {
        "baseline": {"seeded": 4, "deduped": 2},
        "candidate": {"seeded": 3, "deduped": 1},
    }

    result = rollout_gate(_summary(promotion), _strict_config())

    assert result.accepted is False
    assert any(
        item.startswith("representation_todo_productivity_regression")
        for item in result.failures
    )


def test_blocked_regressing_promotion_still_fails_without_strict_activation() -> None:
    promotion = _promotion()
    promotion.update(
        {
            "status": "blocked",
            "promoted": False,
            "promotion_allowed": False,
            "block_reasons": ["hammer_proof_rate_regression"],
        }
    )
    promotion["canary_evidence"]["family_metrics"]["deontic"]["candidate"][
        "hammer_proof_success_rate"
    ] = 0.70

    result = rollout_gate(_summary(promotion))

    assert result.accepted is False
    assert any(
        item.startswith("representation_hammer_proof_rate_regression")
        for item in result.failures
    )
    assert "representation_promotion_not_activated" in result.warnings


def test_gate_accepts_reconstruction_and_source_copy_aliases() -> None:
    promotion = _promotion()
    for family in LEGAL_IR_VIEW_FAMILIES:
        evidence = promotion["canary_evidence"]["family_metrics"][family]
        for side in ("baseline", "candidate"):
            values = evidence[side]
            values["hammer_reconstruction_success_rate"] = values.pop(
                "reconstruction_success_rate"
            )
            values["source_copy_reward_hack_penalty"] = values.pop(
                "source_copy_penalty"
            )

    result = rollout_gate(_summary(promotion), _strict_config())

    assert result.accepted is True


def test_absent_report_is_backward_compatible_but_strict_mode_fails_closed() -> None:
    legacy = rollout_gate(_summary())
    strict = rollout_gate(_summary(), _strict_config())

    assert legacy.accepted is True
    assert strict.accepted is False
    assert "missing_representation_promotion_report" in strict.failures


def test_promoted_payload_cannot_lie_about_declared_regressions() -> None:
    promotion = deepcopy(_promotion())
    promotion["canary_evidence"]["metric_regressions"] = [
        "deontic:hammer_proof_success_rate"
    ]

    result = rollout_gate(_summary(promotion), _strict_config())

    assert result.accepted is False
    assert (
        "representation_declared_metric_regression:deontic:hammer_proof_success_rate"
        in result.failures
    )
