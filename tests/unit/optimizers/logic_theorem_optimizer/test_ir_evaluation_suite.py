"""Golden contracts for ``IREvaluationSuite@1``."""

from __future__ import annotations

import pytest

from benchmarks.semantic_roundtrip.ir_evaluation_suite import (
    COMPILER_SURFACE,
    DECOMPILER_SURFACE,
    IR_EVALUATION_MEASURE_IDS,
    METRIC_STATUS_UNSUPPORTED,
    N1_TOKEN_CROSS_ENTROPY,
    N2_LATENT_SEPARATION,
    N5_SEMANTIC_EQUIVALENCE,
    N6_PROOF_REPLAY_RATE,
    N7_READABILITY_SCORE,
    N8_CALIBRATION_ERROR,
    N8_OOD_ACCEPTANCE,
    EvaluationObservation,
    EvaluationSuiteConfig,
    FalseNeighborEvidence,
    IREvaluationSuite,
    IREvaluationSuiteError,
    TokenizerIdentity,
)


def _config(*required: str, surfaces: tuple[str, ...] = (COMPILER_SURFACE,)) -> EvaluationSuiteConfig:
    return EvaluationSuiteConfig(
        bootstrap_samples=128,
        seed=71,
        minimum_paired_cases=3,
        required_metric_ids=required,
        required_surfaces=surfaces,
    )


def _paired(
    metric_id: str,
    baseline: float,
    candidate: float,
    *,
    surface: str = COMPILER_SURFACE,
    count: int = 5,
    tokenizer: tuple[TokenizerIdentity | None, TokenizerIdentity | None] = (None, None),
    proof_receipts: tuple[tuple[str, ...], tuple[str, ...]] = ((), ()),
    strata: dict[str, str] | None = None,
) -> list[EvaluationObservation]:
    rows: list[EvaluationObservation] = []
    for index in range(count):
        sample_id = f"case-{index}"
        rows.extend(
            (
                EvaluationObservation(
                    "baseline",
                    sample_id,
                    surface,
                    metric_id,
                    baseline,
                    denominator=index + 1,
                    strata=strata or {"split": "test", "family": "deontic"},
                    tokenizer_identity=tokenizer[0],
                    proof_receipt_ids=proof_receipts[0],
                ),
                EvaluationObservation(
                    "candidate",
                    sample_id,
                    surface,
                    metric_id,
                    candidate,
                    denominator=index + 1,
                    strata=strata or {"split": "test", "family": "deontic"},
                    tokenizer_identity=tokenizer[1],
                    proof_receipt_ids=proof_receipts[1],
                ),
            )
        )
    return rows


def test_report_has_separate_n_cells_denominators_strata_and_false_neighbor_evidence() -> None:
    rows = _paired(N2_LATENT_SEPARATION, 0.6, 0.8)
    rows.append(
        EvaluationObservation(
            "candidate",
            "latent-extra",
            COMPILER_SURFACE,
            N2_LATENT_SEPARATION,
            0.8,
            strata={"split": "test", "family": "temporal"},
            false_neighbors=(
                FalseNeighborEvidence(
                    "latent-extra",
                    "nearby-wrong-case",
                    "different_proof_obligation",
                    similarity=0.99,
                    strata={"family": "temporal"},
                ),
            ),
            false_neighbor_analysis_performed=True,
        )
    )
    rows.extend(
        _paired(
            N8_CALIBRATION_ERROR,
            0.10,
            0.08,
            strata={"split": "calibration", "jurisdiction": "federal"},
        )
    )
    rows.extend(
        _paired(
            N8_OOD_ACCEPTANCE,
            0.50,
            0.60,
            strata={"split": "ood", "jurisdiction": "state"},
        )
    )

    report = IREvaluationSuite(config=_config(N2_LATENT_SEPARATION)).evaluate(
        rows,
        baseline_id="baseline",
        candidate_ids=("candidate",),
    )
    payload = report.to_dict()
    latent = report.metric_summary("candidate", COMPILER_SURFACE, N2_LATENT_SEPARATION)

    assert set(report.metric_summaries["candidate"]) == {
        COMPILER_SURFACE,
        DECOMPILER_SURFACE,
    }
    assert set(report.metric_summaries["candidate"][COMPILER_SURFACE]) == set(
        IR_EVALUATION_MEASURE_IDS
    )
    assert latent.denominator == 16
    assert latent.confidence_interval is not None
    assert latent.false_neighbor_analysis["status"] == "measured"
    assert latent.false_neighbor_analysis["false_neighbor_count"] == 1
    assert latent.false_neighbor_analysis["records"][0]["neighbor_id"] == "nearby-wrong-case"
    assert "split=calibration|jurisdiction=federal" not in latent.strata
    assert report.metric_summary("candidate", DECOMPILER_SURFACE, N5_SEMANTIC_EQUIVALENCE).status == (
        METRIC_STATUS_UNSUPPORTED
    )
    assert payload["n_metric_reports"]["candidate"][COMPILER_SURFACE]["N8"][
        N8_OOD_ACCEPTANCE
    ]["strata"]["jurisdiction=state|split=ood"]["denominator"] == 15


def test_incomparable_tokenizers_never_produces_a_cross_entropy_claim() -> None:
    tokenizer_a = TokenizerIdentity("canonical", "1", "vocab-a", "norm-a", "special-a")
    tokenizer_b = TokenizerIdentity("canonical", "2", "vocab-b", "norm-a", "special-a")
    report = IREvaluationSuite(config=_config(N1_TOKEN_CROSS_ENTROPY)).evaluate(
        _paired(
            N1_TOKEN_CROSS_ENTROPY,
            0.50,
            0.20,
            tokenizer=(tokenizer_a, tokenizer_b),
        ),
        baseline_id="baseline",
        candidate_ids=("candidate",),
    )

    comparison = report.comparison("candidate", COMPILER_SURFACE, N1_TOKEN_CROSS_ENTROPY)
    assert comparison.status == METRIC_STATUS_UNSUPPORTED
    assert "incomparable_tokenizers" in comparison.reason
    assert comparison.candidate_minus_baseline is None
    assert report.tokenizer_comparability["candidate"][COMPILER_SURFACE]["comparable"] is False
    assert report.promotion_gates["candidate"].accepted is False


def test_readability_improvement_cannot_override_semantic_regression() -> None:
    rows = _paired(N5_SEMANTIC_EQUIVALENCE, 1.0, 0.60)
    rows.extend(_paired(N7_READABILITY_SCORE, 0.20, 0.95))
    report = IREvaluationSuite(config=_config(N5_SEMANTIC_EQUIVALENCE)).evaluate(
        rows,
        baseline_id="baseline",
        candidate_ids=("candidate",),
    )

    semantic = report.comparison("candidate", COMPILER_SURFACE, N5_SEMANTIC_EQUIVALENCE)
    readability = report.comparison("candidate", COMPILER_SURFACE, N7_READABILITY_SCORE)
    gate = report.promotion_gates["candidate"]

    assert semantic.noninferiority_passed is False
    assert readability.significant_improvement is True
    assert gate.accepted is False
    assert any("semantic_noninferiority_failed" in reason for reason in gate.block_reasons)
    assert gate.readability_informational_only is True


def test_lower_is_better_noninferiority_uses_correct_ci_orientation_and_holm_adjustment() -> None:
    report = IREvaluationSuite(config=_config(N8_CALIBRATION_ERROR)).evaluate(
        _paired(N8_CALIBRATION_ERROR, 0.10, 0.12),
        baseline_id="baseline",
        candidate_ids=("candidate",),
    )
    comparison = report.comparison("candidate", COMPILER_SURFACE, N8_CALIBRATION_ERROR)

    assert comparison.candidate_minus_baseline == pytest.approx(0.02)
    assert comparison.quality_delta == pytest.approx(-0.02)
    assert comparison.quality_confidence_interval is not None
    assert comparison.quality_confidence_interval.low == pytest.approx(-0.02)
    assert comparison.noninferiority_passed is False
    assert comparison.adjusted_p_value is not None
    assert comparison.significance_correction == "holm"


def test_required_proof_metric_needs_independent_receipts_even_when_score_is_noninferior() -> None:
    report = IREvaluationSuite(config=_config(N6_PROOF_REPLAY_RATE)).evaluate(
        _paired(N6_PROOF_REPLAY_RATE, 1.0, 1.0),
        baseline_id="baseline",
        candidate_ids=("candidate",),
    )

    comparison = report.comparison("candidate", COMPILER_SURFACE, N6_PROOF_REPLAY_RATE)
    gate = report.promotion_gates["candidate"]
    assert comparison.noninferiority_passed is True
    assert gate.accepted is False
    assert any("independent_proof_receipts_missing" in reason for reason in gate.block_reasons)


def test_duplicate_case_metric_evidence_is_rejected_before_bootstrap() -> None:
    rows = _paired(N5_SEMANTIC_EQUIVALENCE, 1.0, 1.0)
    rows.append(rows[0])
    with pytest.raises(IREvaluationSuiteError, match="must be unique"):
        IREvaluationSuite(config=_config(N5_SEMANTIC_EQUIVALENCE)).evaluate(
            rows,
            baseline_id="baseline",
            candidate_ids=("candidate",),
        )
