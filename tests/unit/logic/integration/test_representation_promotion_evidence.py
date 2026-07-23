"""Mandatory evidence reports for LegalIR representation promotion."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from scripts.ops.legal_ir.hammer_leanstral_rollout_gate import (
    RolloutGateConfig,
    StagedRolloutConfig,
    rollout_gate,
    staged_rollout_gate,
)
from ipfs_datasets_py.logic.integration.reasoning.legal_ir_learned_guidance import (
    LEGAL_IR_LEARNED_GUIDANCE_PROMOTION_SCHEMA_VERSION,
    promote_learned_autoencoder_guidance,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    LEGAL_IR_STABLE_FEATURE_EXPORT_SCHEMA_VERSION,
)


def _stable_export(*, stable_features: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "contract_feature_atoms": [],
        "export_id": "lir-feature-export-evidence",
        "model_state_id": "modal-autoencoder-state-evidence",
        "repair_lane_feature_atoms": [],
        "sample_count": 8,
        "sample_memory_included": False,
        "schema_version": LEGAL_IR_STABLE_FEATURE_EXPORT_SCHEMA_VERSION,
        "stable_features": stable_features
        if stable_features is not None
        else [
            {
                "feature": "compiler-contract:force-polarity:obligation",
                "feature_group": "compiler_contract",
                "stable": True,
                "support_ratio": 1.0,
                "weight": 0.9,
            }
        ],
        "view_family_weights": {"deontic": 1.0},
    }


def _canary() -> dict[str, Any]:
    return {
        "canary_id": "fixed-canary-evidence",
        "canary_sample_ids": ["canary-a", "canary-b"],
        "view_family_metrics": {
            "deontic": {
                "ir_cross_entropy_loss": 0.2,
                "ir_cosine_similarity": 0.8,
                "autoencoder_cross_entropy_loss": 0.3,
                "autoencoder_cosine_similarity": 0.7,
                "symbolic_validity_success_rate": 1.0,
                "hammer_proof_success_rate": 1.0,
                "reconstruction_success_rate": 1.0,
                "source_copy_penalty": 0.0,
            }
        },
    }


def _proof_receipts() -> list[dict[str, Any]]:
    return [
        {
            "receipt_id": "proof-receipt-evidence",
            "checker": "lean-kernel",
            "trusted": True,
        }
    ]


def _promotion(*, stable_features: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return promote_learned_autoencoder_guidance(
        _stable_export(stable_features=stable_features),
        baseline_canary_metrics=_canary(),
        candidate_canary_metrics=_canary(),
        fixed_canary_id="fixed-canary-evidence",
        compiler_commit="compiler-commit-evidence",
        proof_receipts=_proof_receipts(),
        eligible_snapshot_id="snapshot-evidence",
        report_artifact_path="workspace/rollout/promotion/report.json",
    ).to_dict()


def _summary(report: dict[str, Any] | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "cycles": 2,
        "status": "succeeded",
        "source_export_id": "lir-feature-export-evidence",
        "compiler_commit": "compiler-commit-evidence",
        "fixed_canary_id": "fixed-canary-evidence",
        "snapshot_id": "snapshot-evidence",
        "representation_promotion_report_path": (
            "workspace/rollout/promotion/report.json"
        ),
        "latest_validation_ce_delta": 0.0,
        "latest_validation_cosine_delta": 0.0,
        "latest_compiler_ir_source_copy_reward_hack_penalty": 0.0,
        "latest_daemon_hammer_guidance": {
            "status": "completed",
            "runtime_failure_count": 0,
            "obligation_failure_count": 0,
        },
        "program_synthesis_seeded": 1,
        "program_synthesis_completed": 1,
        "todo_generation_productivity": {
            "baseline": {"completed": 1},
            "candidate": {"completed": 1},
        },
    }
    if report is not None:
        payload["latest_legal_ir_learned_guidance_promotion"] = report
    return payload


def _report_required_config(*, require_success: bool = True) -> RolloutGateConfig:
    return RolloutGateConfig(
        require_representation_promotion=True,
        require_successful_representation_promotion=require_success,
        require_complete_representation_evidence=True,
    )


def test_success_report_binds_all_mandatory_promotion_evidence() -> None:
    report = _promotion()

    assert report["schema_version"] == LEGAL_IR_LEARNED_GUIDANCE_PROMOTION_SCHEMA_VERSION
    assert report["report_outcome"] == "success"
    assert report["learned_export"]["export_id"] == "lir-feature-export-evidence"
    assert report["compiler_commit"] == "compiler-commit-evidence"
    assert report["fixed_canary_binding"]["canary_id"] == "fixed-canary-evidence"
    assert report["proof_receipt_ids"] == ["proof-receipt-evidence"]
    assert report["causal_evidence"]["metric_lineage_complete"] is True
    assert report["source_copy_checks"]["guardrails_passed"] is True
    assert report["activation_state"]["activation_allowed"] is True
    assert report["rollback_metadata"]["activation_key"] == report["promotion_id"]

    result = rollout_gate(_summary(report), _report_required_config())

    assert result.accepted is True
    assert result.failures == []


def test_no_candidate_snapshot_still_emits_complete_non_activation_report() -> None:
    report = _promotion(stable_features=[])

    assert report["promoted"] is False
    assert report["report_outcome"] == "no_candidate"
    assert "no_stable_learned_features" in report["block_reasons"]
    assert report["activation_state"]["activation_allowed"] is False
    assert report["rollback_metadata"]["activation_allowed"] is False

    result = rollout_gate(_summary(report), _report_required_config(require_success=False))

    assert result.accepted is True
    assert result.failures == []


@pytest.mark.parametrize(
    ("mutate", "failure"),
    [
        (
            lambda report: report.pop("learned_export"),
            "representation_learned_export_binding_missing",
        ),
        (
            lambda report: report.update({"compiler_commit": "old-compiler"}),
            "representation_promotion_report_stale:compiler_commit:"
            "old-compiler!=compiler-commit-evidence",
        ),
        (
            lambda report: report.update(
                {"report_artifact_path": "workspace/other/report.json"}
            ),
            "representation_promotion_report_path_mismatch:"
            "workspace/other/report.json!=workspace/rollout/promotion/report.json",
        ),
        (
            lambda report: report.update({"proof_receipts": []}),
            "representation_proof_receipts_missing",
        ),
    ],
)
def test_gate_fails_closed_for_partial_stale_or_path_mismatched_reports(
    mutate: Any,
    failure: str,
) -> None:
    report = _promotion()
    mutate(report)

    result = rollout_gate(_summary(report), _report_required_config())

    assert result.accepted is False
    assert failure in result.failures


def test_eligible_staged_snapshot_requires_one_promotion_report() -> None:
    snapshot = {
        "stage": "short_smoke",
        "duration_seconds": 600,
        "elapsed_seconds": 600,
        "snapshot_complete": True,
        "status": "succeeded",
        "representation_promotion_eligible": True,
        "source_export_id": "lir-feature-export-evidence",
        "compiler_commit": "compiler-commit-evidence",
        "fixed_canary_id": "fixed-canary-evidence",
        "snapshot_id": "snapshot-evidence",
        "managed_processes": [
            {
                "name": "controller",
                "status": "exited",
                "exit_code": 0,
                "orphaned": False,
            }
        ],
        "family_metrics": {},
        "trusted_feedback": {},
        "accepted_patches": 1,
        "wall_clock_seconds": 600,
        "queue_lag": {"p95_seconds": 1.0},
        "rollback_evidence": {
            "artifact_path": "workspace/rollback.json",
            "sha256": "b" * 64,
            "baseline_revision": "baseline",
            "restorable": True,
        },
    }

    missing = staged_rollout_gate(
        [deepcopy(snapshot)],
        StagedRolloutConfig(
            require_all_stages=False,
            require_trusted_feedback=False,
            required_families=(),
        ),
    )
    snapshot["latest_legal_ir_learned_guidance_promotion"] = _promotion()
    present = staged_rollout_gate(
        [snapshot],
        StagedRolloutConfig(
            require_all_stages=False,
            require_trusted_feedback=False,
            required_families=(),
        ),
    )

    assert "missing_representation_promotion_report:short_smoke" in missing.failures
    assert not any(
        failure.startswith("missing_representation_promotion_report")
        for failure in present.failures
    )
