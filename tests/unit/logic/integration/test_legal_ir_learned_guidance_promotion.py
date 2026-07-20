"""Promotion tests for learned autoencoder features and deterministic LegalIR."""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.logic.integration.reasoning.legal_ir_learned_guidance import (
    LEGAL_IR_LEARNED_GUIDANCE_SCHEMA_VERSION,
    evaluate_fixed_canary_evidence,
    promote_learned_autoencoder_guidance,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    LEGAL_IR_STABLE_FEATURE_EXPORT_SCHEMA_VERSION,
    AdaptiveModalAutoencoder,
    ModalAutoencoderTrainingState,
)


def _stable_export() -> dict:
    return {
        "contract_feature_atoms": [],
        "export_id": "lir-feature-export-test",
        "model_state_id": "modal-autoencoder-state-test",
        "repair_lane_feature_atoms": [],
        "sample_count": 8,
        "sample_memory_included": False,
        "schema_version": LEGAL_IR_STABLE_FEATURE_EXPORT_SCHEMA_VERSION,
        "stable_features": [
            {
                "feature": "compiler-contract:force-polarity:obligation:negative_scope",
                "feature_group": "compiler_contract",
                "feature_id": "lir-feature-compiler",
                "stable": True,
                "support_ratio": 0.875,
                "weight": 0.8,
            },
            {
                "feature": "decompiler-surface:negation-placement:pre-action",
                "feature_group": "decompiler_surface_template",
                "feature_id": "lir-feature-decompiler",
                "stable": True,
                "support_ratio": 0.75,
                "weight": 0.7,
            },
            {
                "feature": "cycle-consistency:force-operator-cycle:prohibition:f",
                "feature_group": "cycle_consistency",
                "feature_id": "lir-feature-cycle",
                "stable": True,
                "support_ratio": 1.0,
                "weight": 0.6,
            },
        ],
        "view_family_weights": {"decompiler": 0.4, "deontic": 0.6},
    }


def _canary(*, copy: float = 0.0, symbolic: float = 1.0) -> dict:
    return {
        "canary_id": "fixed-canary-2026-07",
        "canary_sample_ids": ["canary-a", "canary-b"],
        "view_family_metrics": {
            family: {
                "hammer_proof_success_rate": 1.0,
                "source_copy_penalty": copy,
                "symbolic_validity_success_rate": symbolic,
            }
            for family in ("deontic", "decompiler")
        },
    }


def test_stable_autoencoder_export_excludes_memory_and_source_features() -> None:
    state = ModalAutoencoderTrainingState(
        decoded_embeddings={"sample-secret": [0.1, 0.2]},
        family_logits={"sample-secret": {"deontic": 5.0}},
        feature_embedding_weights={
            "compiler-contract:force-polarity:obligation:negative_scope": [0.5, -0.2],
            "token:verbatim_source_word": [100.0, 100.0],
        },
        legal_ir_view_logits={"deontic.ir": 2.0, "modal.ir_decompiler": 1.0},
    )
    autoencoder = AdaptiveModalAutoencoder(state=state)

    first = autoencoder.export_stable_legal_ir_features().to_dict()
    state.decoded_embeddings["different-secret"] = [9.0, 9.0]
    state.family_logits["different-secret"] = {"frame": 9.0}
    second = autoencoder.export_stable_legal_ir_features().to_dict()

    assert first == second
    assert first["sample_memory_included"] is False
    assert first["feature_count"] == 1
    assert first["stable_features"][0]["feature"].startswith("compiler-contract:")
    serialized = json.dumps(first, sort_keys=True)
    assert "sample-secret" not in serialized
    assert "different-secret" not in serialized
    assert "verbatim_source_word" not in serialized
    assert "decoded_embeddings" not in first
    assert "decoded_embedding" not in first


def test_promotion_emits_deterministic_contract_guidance_and_rollback() -> None:
    export = _stable_export()
    baseline = _canary(copy=0.05, symbolic=0.98)
    candidate = _canary(copy=0.01, symbolic=1.0)

    first = promote_learned_autoencoder_guidance(
        export,
        baseline_canary_metrics=baseline,
        candidate_canary_metrics=candidate,
        fixed_canary_id="fixed-canary-2026-07",
        previous_promotion_id="lir-guidance-promotion-previous",
    )
    second = promote_learned_autoencoder_guidance(
        {**export, "stable_features": list(reversed(export["stable_features"]))},
        baseline_canary_metrics=baseline,
        candidate_canary_metrics=candidate,
        fixed_canary_id="fixed-canary-2026-07",
        previous_promotion_id="lir-guidance-promotion-previous",
    )

    assert first.promoted is True
    assert first.promotion_id == second.promotion_id
    assert [record.guidance_id for record in first.records] == [
        record.guidance_id for record in second.records
    ]
    assert {record.view_family for record in first.records} == {
        "decompiler",
        "deontic",
    }
    for record in first.records:
        payload = record.to_dict()
        assert payload["schema_version"] == LEGAL_IR_LEARNED_GUIDANCE_SCHEMA_VERSION
        assert payload["contract_id"].startswith("legal-ir-view/")
        assert payload["repair_lane_suggestions"]
        assert payload["repair_lane_records"][0]["allowed_paths"]
        assert payload["repair_lane_records"][0]["validation_commands"]
        assert 0.0 < payload["confidence"] <= 1.0
        assert payload["canary_metric_evidence"]["guardrails_passed"] is True
        assert payload["rollback_metadata"]["restore_mode"] == "canary_only"
        assert payload["rollback_metadata"]["previous_promotion_id"] == (
            "lir-guidance-promotion-previous"
        )
        assert payload["source"] == "stable_autoencoder_feature_promotion"


@pytest.mark.parametrize(
    ("candidate", "reason", "evidence_field"),
    [
        (_canary(copy=0.2, symbolic=1.0), "source_copy_guardrail_regression", "source_copy_regressions"),
        (_canary(copy=0.0, symbolic=0.8), "symbolic_validity_guardrail_regression", "symbolic_validity_regressions"),
    ],
)
def test_promotion_blocks_hard_guardrail_regressions(
    candidate: dict,
    reason: str,
    evidence_field: str,
) -> None:
    result = promote_learned_autoencoder_guidance(
        _stable_export(),
        baseline_canary_metrics=_canary(copy=0.0, symbolic=1.0),
        candidate_canary_metrics=candidate,
        fixed_canary_id="fixed-canary-2026-07",
    )

    assert result.promoted is False
    assert result.records == ()
    assert result.candidate_record_count == 2
    assert reason in result.block_reasons
    assert result.canary_evidence[evidence_field]
    assert result.rollback_metadata["activation_allowed"] is False


def test_promotion_requires_fixed_complete_canary_and_rejects_unsafe_features() -> None:
    export = _stable_export()
    export["sample_memory_included"] = True
    export["stable_features"].append(
        {
            "feature": "token:copied_source_span",
            "feature_group": "compiler_contract",
            "stable": True,
            "support_ratio": 1.0,
            "weight": 99.0,
        }
    )
    baseline = _canary()
    candidate = _canary()
    candidate["canary_id"] = "different-canary"
    del candidate["view_family_metrics"]["deontic"][
        "symbolic_validity_success_rate"
    ]

    result = promote_learned_autoencoder_guidance(
        export,
        baseline_canary_metrics=baseline,
        candidate_canary_metrics=candidate,
    )

    assert result.promoted is False
    assert "sample_memory_features_present" in result.block_reasons
    assert "unsafe_or_unstable_features_present" in result.block_reasons
    assert "fixed_canary_identity_missing_or_mismatched" in result.block_reasons
    assert "fixed_canary_guardrail_evidence_incomplete" in result.block_reasons


def test_fixed_canary_evidence_reports_directional_deltas() -> None:
    evidence = evaluate_fixed_canary_evidence(
        _canary(copy=0.1, symbolic=0.9),
        _canary(copy=0.0, symbolic=1.0),
        fixed_canary_id="fixed-canary-2026-07",
        required_families=("deontic",),
    )

    family = evidence.family_metrics["deontic"]
    assert evidence.guardrails_passed is True
    assert family["deltas"]["source_copy_penalty"] == pytest.approx(0.1)
    assert family["deltas"]["symbolic_validity_success_rate"] == pytest.approx(0.1)
