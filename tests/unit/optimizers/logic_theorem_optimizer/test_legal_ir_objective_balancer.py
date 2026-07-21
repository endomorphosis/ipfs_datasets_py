"""Tests for constrained per-family LegalIR objective balancing."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_family_evaluator import (
    LEGAL_IR_EVALUATION_FAMILIES,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_objective_balancer import (
    ANTI_COPY,
    COMPILER_CE,
    DEFAULT_SOFT_WEIGHT_BOUNDS,
    LEARNED_CE,
    LEGAL_IR_OBJECTIVE_BALANCER_SCHEMA_VERSION,
    PROOF_VALIDITY,
    SOFT_OBJECTIVE_METRICS,
    LegalIRObjectiveBalancer,
    LegalIRObjectiveBalancerConfig,
    ObjectiveWeightBounds,
    evaluate_constrained_legal_ir_objective,
)


def _family_metrics(
    *,
    ce: float,
    compiler_ce: float | None = None,
    cosine: float = 0.80,
    compiler_cosine: float = 0.78,
    proof: float = 0.90,
    reconstruction: float = 0.88,
    copy: float = 0.02,
    structural_loss: float = 0.01,
    provenance: float = 1.0,
    hammer_trust: float = 0.95,
) -> dict[str, float | list[str]]:
    return {
        "autoencoder_cosine_similarity": cosine,
        "autoencoder_cross_entropy_loss": ce,
        "hammer_proof_success_rate": proof,
        "hammer_trusted_success_rate": hammer_trust,
        "ir_cosine_similarity": compiler_cosine,
        "ir_cross_entropy_loss": compiler_ce if compiler_ce is not None else ce + 0.04,
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
        "provenance_preservation_success_rate": provenance,
        "reconstruction_success_rate": reconstruction,
        "round_trip_structural_reconstruction_loss": structural_loss,
        "source_copy_penalty": copy,
        "structural_text_reconstruction_loss": structural_loss,
        "symbolic_validity_success_rate": proof,
    }


def _packet(
    *,
    ce: float,
    cosine: float,
    compiler_ce: float | None = None,
    compiler_cosine: float | None = None,
    proof: float = 0.90,
    reconstruction: float = 0.88,
    copy: float = 0.02,
    structural_loss: float = 0.01,
    provenance: float = 1.0,
    hammer_trust: float = 0.95,
    fixed_canary: bool = True,
) -> dict:
    return {
        "fixed_canary_guardrail_passed": fixed_canary,
        "view_family_metrics": {
            family: _family_metrics(
                ce=ce + index * 0.01,
                compiler_ce=(compiler_ce + index * 0.01)
                if compiler_ce is not None
                else None,
                cosine=cosine,
                compiler_cosine=compiler_cosine
                if compiler_cosine is not None
                else max(0.0, cosine - 0.02),
                proof=proof,
                reconstruction=reconstruction,
                copy=copy,
                structural_loss=structural_loss,
                provenance=provenance,
                hammer_trust=hammer_trust,
            )
            for index, family in enumerate(LEGAL_IR_EVALUATION_FAMILIES)
        },
    }


def test_balancer_accepts_complete_improvements_for_every_semantic_family() -> None:
    before = _packet(ce=0.80, compiler_ce=0.86, cosine=0.76, compiler_cosine=0.74)
    after = _packet(
        ce=0.55,
        compiler_ce=0.58,
        cosine=0.86,
        compiler_cosine=0.84,
        proof=0.95,
        reconstruction=0.92,
        copy=0.0,
    )

    report = evaluate_constrained_legal_ir_objective(before, after)
    payload = report.to_dict()

    assert report.accepted is True
    assert report.failed_families == ()
    assert payload["schema_version"] == LEGAL_IR_OBJECTIVE_BALANCER_SCHEMA_VERSION
    assert tuple(payload["families"]) == LEGAL_IR_EVALUATION_FAMILIES
    assert payload["macro_score_available"] is True
    assert report.macro_soft_improvement > 0.0
    assert report.worst_family_improvement > 0.0
    assert all(result.passed for result in report.family_results.values())
    assert set(report.adapted_weights["deontic"]) == set(SOFT_OBJECTIVE_METRICS)


def test_macro_average_cannot_hide_a_failed_family() -> None:
    before = _packet(ce=0.80, compiler_ce=0.82, cosine=0.72, compiler_cosine=0.70)
    after = _packet(ce=0.35, compiler_ce=0.38, cosine=0.90, compiler_cosine=0.88)
    after["view_family_metrics"]["provenance"].update(
        {
            "autoencoder_cosine_similarity": 0.45,
            "autoencoder_cross_entropy_loss": 2.20,
            "ir_cosine_similarity": 0.40,
            "ir_cross_entropy_loss": 2.10,
        }
    )

    report = LegalIRObjectiveBalancer().evaluate(before, after)

    assert report.accepted is False
    assert report.macro_soft_improvement > 0.0
    assert report.family_results["provenance"].objective_improvement < 0.0
    assert report.failed_families == ("provenance",)
    assert "provenance:soft_objective_regressed" in report.block_reasons
    assert report.to_dict()["macro_score_available"] is False


def test_hard_guardrails_block_even_when_soft_objective_improves() -> None:
    before = _packet(ce=0.80, compiler_ce=0.86, cosine=0.76, compiler_cosine=0.74)
    after = _packet(
        ce=0.30,
        compiler_ce=0.32,
        cosine=0.92,
        compiler_cosine=0.91,
        copy=0.20,
        provenance=0.70,
        hammer_trust=0.60,
        fixed_canary=False,
    )
    after["view_family_metrics"]["deontic"]["structural_text_reconstruction_loss"] = 0.25
    current_weights = {
        LEARNED_CE: 1.0,
        "source_copy_penalty": 100.0,
        "hammer_trusted_success_rate": 100.0,
    }

    report = evaluate_constrained_legal_ir_objective(
        before,
        after,
        current_weights=current_weights,
    )
    deontic = report.family_results["deontic"]

    assert report.accepted is False
    assert report.macro_soft_improvement > 0.0
    assert "deontic:hard_guardrail_regressed" in report.block_reasons
    assert any(
        key.startswith("source_copy:") for key in deontic.hard_guardrail_regressions
    )
    assert any(
        key.startswith("hammer_trust:") for key in deontic.hard_guardrail_regressions
    )
    assert any(
        key.startswith("provenance:") for key in deontic.hard_guardrail_regressions
    )
    assert any(
        key.startswith("structural:") for key in deontic.hard_guardrail_regressions
    )
    assert any(
        key.startswith("frozen_canary:") for key in deontic.hard_guardrail_regressions
    )
    assert "source_copy_penalty" in report.ignored_weight_keys
    assert "hammer_trusted_success_rate" in report.ignored_weight_keys
    assert "source_copy_penalty" not in report.adapted_weights["deontic"]
    assert "hammer_trusted_success_rate" not in report.adapted_weights["deontic"]


def test_adapts_soft_weights_inside_configured_bounds_only() -> None:
    config = LegalIRObjectiveBalancerConfig(
        soft_weight_bounds={
            **DEFAULT_SOFT_WEIGHT_BOUNDS,
            PROOF_VALIDITY: ObjectiveWeightBounds(1.5, 1.6, 1.55),
            ANTI_COPY: ObjectiveWeightBounds(0.8, 0.9, 0.85),
        },
        adaptation_rate=10.0,
    )
    before = _packet(ce=0.80, compiler_ce=0.82, cosine=0.78, compiler_cosine=0.76)
    after = _packet(
        ce=0.65,
        compiler_ce=0.66,
        cosine=0.84,
        compiler_cosine=0.82,
        proof=0.10,
        copy=0.40,
    )

    report = LegalIRObjectiveBalancer(config).evaluate(
        before,
        after,
        current_weights={
            "deontic": {
                PROOF_VALIDITY: 999.0,
                ANTI_COPY: -5.0,
                COMPILER_CE: 1.0,
            }
        },
    )
    deontic_weights = report.family_results["deontic"].soft_weights_after

    assert deontic_weights[PROOF_VALIDITY] == pytest.approx(1.6)
    assert deontic_weights[ANTI_COPY] == pytest.approx(0.9)
    for metric, value in deontic_weights.items():
        bounds = config.soft_weight_bounds[metric]
        assert bounds.minimum <= value <= bounds.maximum


def test_aliases_and_missing_required_families_fail_closed() -> None:
    before = _packet(ce=0.80, compiler_ce=0.84, cosine=0.76, compiler_cosine=0.74)
    after = _packet(ce=0.60, compiler_ce=0.62, cosine=0.84, compiler_cosine=0.82)
    before["view_family_metrics"]["kg"] = before["view_family_metrics"].pop(
        "knowledge_graphs"
    )
    after["view_family_metrics"]["kg"] = after["view_family_metrics"].pop(
        "knowledge_graphs"
    )
    after["view_family_metrics"].pop("temporal")

    report = evaluate_constrained_legal_ir_objective(before, after)

    assert "knowledge_graphs" in report.family_results
    assert report.family_results["knowledge_graphs"].passed is True
    assert report.family_results["temporal"].missing_soft_metrics == SOFT_OBJECTIVE_METRICS
    assert report.family_results["temporal"].missing_hard_guardrails == (
        "structural",
        "provenance",
        "source_copy",
        "hammer_trust",
    )
    assert "temporal:soft_metric_evidence_missing" in report.block_reasons
    assert report.accepted is False
