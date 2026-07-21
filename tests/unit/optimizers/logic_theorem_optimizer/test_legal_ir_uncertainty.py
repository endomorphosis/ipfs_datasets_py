"""Tests for LegalIR learned-guidance uncertainty and abstention gates."""

from __future__ import annotations

import json
from argparse import Namespace

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_uncertainty import (
    LEGAL_IR_UNCERTAINTY_SCHEMA_VERSION,
    ROUTE_CODEX_TODO,
    ROUTE_HAMMER_LEANSTRAL_AUDIT,
    LegalIRUncertaintyConfig,
    evaluate_legal_ir_uncertainty,
    legal_ir_uncertainty_promotion_gate,
    route_learned_guidance_by_uncertainty,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_todo_daemon import (
    ModalTodoQueue,
    ModalTodoSupervisor,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner import (
    project_verified_leanstral_guidance_artifacts_into_queue,
)


def _learned_guidance(
    guidance_id: str,
    *,
    family: str = "deontic",
    confidence: float = 0.92,
    calibration_error: float = 0.02,
    ood: bool = False,
) -> dict:
    return {
        "calibration_error": calibration_error,
        "confidence": confidence,
        "guidance_id": guidance_id,
        "legal_ir_family": family,
        "legal_ir_predicted_view_distribution": {
            "deontic.ir": confidence,
            "TDFOL.prover": max(0.0, 1.0 - confidence),
        },
        "out_of_distribution": ood,
        "schema_version": "legal-ir-leanstral-draft-guidance-v1",
        "source": "learned_legal_ir_guidance",
        "target_component": "deontic.ir",
    }


def test_reports_confidence_entropy_abstention_and_ood_by_family() -> None:
    report = evaluate_legal_ir_uncertainty(
        [
            _learned_guidance("safe", confidence=0.94, calibration_error=0.02),
            _learned_guidance(
                "shifted",
                family="TDFOL.prover",
                confidence=0.51,
                calibration_error=0.01,
                ood=True,
            ),
        ],
        config=LegalIRUncertaintyConfig(
            families=("deontic", "tdfol"),
            max_ood_rate={"tdfol": 1.0},
        ),
    )
    payload = report.to_dict()

    assert payload["schema_version"] == LEGAL_IR_UNCERTAINTY_SCHEMA_VERSION
    assert payload["family_results"]["deontic"]["calibrated_confidence"] == 0.92
    assert payload["family_results"]["deontic"]["normalized_entropy"] < 0.35
    assert payload["family_results"]["deontic"]["abstention_rate"] == 0.0
    assert payload["family_results"]["tdfol"]["ood_rate"] == 1.0
    assert payload["family_results"]["tdfol"]["hammer_leanstral_audit_count"] == 1


def test_low_confidence_learned_guidance_routes_to_audit_not_codex() -> None:
    routed = route_learned_guidance_by_uncertainty(
        [
            _learned_guidance("codex-ok", confidence=0.96, calibration_error=0.01),
            _learned_guidance("audit-low", confidence=0.45, calibration_error=0.03),
        ],
        config=LegalIRUncertaintyConfig(families=("deontic",)),
    )

    assert [item["guidance_id"] for item in routed["codex_guidance_items"]] == [
        "codex-ok"
    ]
    assert [item["guidance_id"] for item in routed["audit_guidance_items"]] == [
        "audit-low"
    ]
    assert routed["codex_guidance_items"][0]["uncertainty_route"] == ROUTE_CODEX_TODO
    assert (
        routed["audit_guidance_items"][0]["uncertainty_route"]
        == ROUTE_HAMMER_LEANSTRAL_AUDIT
    )


def test_promotion_gate_blocks_calibration_error_by_configured_family_threshold() -> None:
    gate = legal_ir_uncertainty_promotion_gate(
        [_learned_guidance("bad-calibration", calibration_error=0.22)],
        config=LegalIRUncertaintyConfig(
            families=("deontic",),
            max_calibration_error={"deontic": 0.05},
        ),
    )

    assert gate["accepted"] is False
    assert gate["hard_promotion_gate"] is True
    assert gate["failed_families"] == ["deontic"]
    assert "deontic:calibration_error_above_threshold" in gate["block_reasons"]


def test_unsupported_family_abstains_and_blocks_promotion() -> None:
    gate = legal_ir_uncertainty_promotion_gate(
        [
            _learned_guidance(
                "unsupported",
                family="invented_logic",
                confidence=0.99,
                calibration_error=0.0,
            )
        ],
        config=LegalIRUncertaintyConfig(families=("deontic",)),
    )

    assert gate["accepted"] is False
    assert gate["family_results"]["unsupported"]["unsupported_family_rate"] == 1.0
    assert (
        gate["family_results"]["unsupported"]["unsupported_abstention_rate"] == 1.0
    )
    assert "unsupported:unsupported_family_signal" in gate["block_reasons"]
    assert gate["unsupported_guidance_ids"] == ["unsupported"]


def test_configured_family_threshold_blocks_unsupported_abstention() -> None:
    guidance = _learned_guidance(
        "unsupported-deontic",
        family="deontic",
        confidence=0.96,
        calibration_error=0.01,
    )
    guidance["unsupported_family_signal"] = True

    gate = legal_ir_uncertainty_promotion_gate(
        [guidance],
        config=LegalIRUncertaintyConfig(
            families=("deontic",),
            max_unsupported_abstention_rate={"deontic": 0.0},
        ),
    )

    assert gate["accepted"] is False
    assert (
        gate["family_results"]["deontic"]["unsupported_abstention_rate"] == 1.0
    )
    assert (
        "deontic:unsupported_abstention_above_threshold"
        in gate["block_reasons"]
    )


def test_runner_reports_uncertain_learned_guidance_as_audit_only(tmp_path) -> None:
    artifact_path = tmp_path / "learned-guidance.json"
    artifact_path.write_text(
        json.dumps(
            {
                "guidance_items": [
                    _learned_guidance(
                        "audit-only",
                        confidence=0.41,
                        calibration_error=0.04,
                    )
                ]
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    queue_path = tmp_path / "queue.jsonl"
    supervisor = ModalTodoSupervisor(queue=ModalTodoQueue())
    args = Namespace(
        autoencoder_max_audits_per_cycle=0,
        autoencoder_max_todos_per_cycle=5,
        autoencoder_target_scope_filters="",
        leanstral_direct_guidance_max_todos_per_scope=2,
        leanstral_direct_guidance_path=str(artifact_path),
        leanstral_direct_guidance_projection_enabled=True,
        leanstral_direct_guidance_require_executor_available=False,
        leanstral_direct_guidance_train_autoencoder=False,
        leanstral_rule_gap_max_todos_per_scope=2,
        max_program_synthesis_pending=512,
    )

    result = project_verified_leanstral_guidance_artifacts_into_queue(
        args=args,
        queue_path=queue_path,
        root=tmp_path,
        supervisor=supervisor,
    )

    assert result["status"] == "projected"
    assert result["uncertainty_routing"]["audit_guidance_count"] == 1
    assert result["uncertainty_routing"]["codex_guidance_count"] == 0
    assert result["seeded_count"] == 0
    assert ModalTodoQueue.load_jsonl(queue_path).all() == []
