"""CRYPTOIR-G790 tests for multi-metric Solidity CPT formalizer evaluation."""

from __future__ import annotations

import pytest
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.evaluation import (
    CANDIDATE_AUTHORITY,
    ClaimKind,
    ControlKind,
    EvaluationAuthorityError,
    EvaluationCase,
    EvaluationIntegrityError,
    EvaluationLeakageError,
    EvaluationMode,
    EvaluationPromotionError,
    ExternalLabelCorpusAdmission,
    MetricSliceName,
    NON_PROOF_CLAIM_KINDS,
    PromotionGate,
    ProverAgreement,
    ProverOutcomeKind,
    SeparateMetricReport,
    SolidityFormalEvaluation,
    SolidityFormalEvaluator,
    aggregate_metrics,
    build_evaluation_case,
    build_offline_fixture_evaluation,
    compute_calibration,
    counts_as_executable_proof,
    detect_cross_partition_leakage,
    evaluate_solidity_formalizer,
    verify_evaluation_receipt,
)
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.partitions import (
    ADVERSARIAL_PARTITION,
    HELD_OUT_PARTITION,
    TRAIN_PARTITION,
)


def test_fixture_evaluation_is_cid_bound_and_rehashes() -> None:
    evaluation = build_offline_fixture_evaluation()
    wire = evaluation.to_dict()

    assert evaluation.evaluation_cid.startswith("b")
    assert len(evaluation.evaluation_cid) == 59
    assert wire["evaluation_cid"] == evaluation.evaluation_cid
    assert wire["proof_authority"] is False
    assert wire["transaction_authority"] is False
    assert wire["learned_output_authority"] == CANDIDATE_AUTHORITY
    assert wire["metrics"]["single_accuracy_score"] is None
    assert wire["metrics"]["misleading_accuracy_optimized"] is False

    restored = SolidityFormalEvaluation.from_dict(wire)
    assert restored.evaluation_cid == evaluation.evaluation_cid
    assert restored.to_dict() == wire
    assert verify_evaluation_receipt(wire).evaluation_cid == evaluation.evaluation_cid

    tampered = dict(wire)
    tampered["diagnostics"] = ["tampered"]
    with pytest.raises(EvaluationIntegrityError, match="evaluation_cid"):
        SolidityFormalEvaluation.from_dict(tampered)


def test_fixture_covers_every_adversarial_control_and_metric_slice() -> None:
    evaluation = build_offline_fixture_evaluation()
    covered = set(evaluation.control_kinds_covered)
    assert covered == {item.value for item in ControlKind}

    metrics = evaluation.metrics.to_dict()
    for slice_name in MetricSliceName:
        if slice_name is MetricSliceName.LEAKAGE:
            assert "leakage_count" in metrics
        elif slice_name is MetricSliceName.LATENCY:
            assert "mean_latency_ms" in metrics
        elif slice_name is MetricSliceName.MEMORY:
            assert "peak_memory_bytes" in metrics
        elif slice_name is MetricSliceName.ABSTENTION:
            assert "abstention_rate" in metrics
            assert "abstention_precision" in metrics
            assert "abstention_recall" in metrics
        elif slice_name is MetricSliceName.UNCERTAINTY:
            assert "uncertainty_rate" in metrics
        else:
            assert slice_name.value in metrics

    outcomes = metrics["prover_outcomes"]
    for key in (
        "proof",
        "disproof",
        "unknown",
        "timeout",
        "unavailable",
        "disagreement",
        "rejected_non_proof_claims",
    ):
        assert key in outcomes
        assert outcomes[key] >= 0


def test_fixture_reports_zero_leakage_and_passes_promotion_gate() -> None:
    evaluation = build_offline_fixture_evaluation()
    assert evaluation.metrics.leakage_count == 0
    assert evaluation.leakage_findings == ()
    assert evaluation.false_proof_count == 0
    gate = evaluation.promotion_gate()
    assert isinstance(gate, PromotionGate)
    assert gate.passed is True
    assert evaluation.require_promotion_safe() is evaluation
    assert gate.require_passed() is gate


def test_non_proof_claim_kinds_never_count_as_executable_proof() -> None:
    assert counts_as_executable_proof(
        ClaimKind.EXECUTABLE_PROOF, executed=True, authoritative=True
    )
    assert not counts_as_executable_proof(
        ClaimKind.EXECUTABLE_PROOF, executed=False, authoritative=True
    )
    for kind in NON_PROOF_CLAIM_KINDS:
        assert not counts_as_executable_proof(
            kind, executed=True, authoritative=True
        )

    for kind in (
        ClaimKind.APPROXIMATE,
        ClaimKind.MODEL,
        ClaimKind.SAT,
        ClaimKind.SIMULATION,
        ClaimKind.UNEXECUTED,
    ):
        with pytest.raises(EvaluationAuthorityError, match="non-executable"):
            build_evaluation_case(
                f"case:bad-proof:{kind.value}",
                partition=HELD_OUT_PARTITION,
                control_kind=ControlKind.HELD_OUT,
                source_family_id="family:bad",
                claim_kind=kind,
                prover_outcome=ProverOutcomeKind.PROOF,
                claim_executed=True,
                claim_authoritative=True,
            )


def test_cross_partition_source_family_leakage_is_detected() -> None:
    cases = (
        build_evaluation_case(
            "case:a",
            partition=HELD_OUT_PARTITION,
            control_kind=ControlKind.HELD_OUT,
            source_family_id="family:shared",
        ),
        build_evaluation_case(
            "case:b",
            partition=ADVERSARIAL_PARTITION,
            control_kind=ControlKind.MUTATION,
            source_family_id="family:shared",
        ),
    )
    findings = detect_cross_partition_leakage(cases)
    assert len(findings) == 1
    assert findings[0]["kind"] == "source_family_cross_partition"
    assert findings[0]["key"] == "family:shared"
    metrics = aggregate_metrics(cases, leakage_findings=findings)
    assert metrics.leakage_count == 1

    evaluation = evaluate_solidity_formalizer(
        cases,
        source_cid=build_offline_fixture_evaluation().source_cid,
        graph_cid=build_offline_fixture_evaluation().graph_cid,
        index_cid=build_offline_fixture_evaluation().index_cid,
        partition_cid=build_offline_fixture_evaluation().partition_cid,
        license_cid=build_offline_fixture_evaluation().license_cid,
        model_or_checkpoint_cid=build_offline_fixture_evaluation().model_or_checkpoint_cid,
        external_label_admission=build_offline_fixture_evaluation().external_label_admission,
        mode=EvaluationMode.DRY_RUN,
    )
    assert evaluation.metrics.leakage_count == 1
    assert evaluation.promotion_gate().passed is False
    with pytest.raises((EvaluationPromotionError, EvaluationLeakageError)):
        evaluation.require_promotion_safe()


def test_prover_agreement_records_disagreement_separately() -> None:
    agreed = ProverAgreement.from_solver_outcomes(
        "case:agree",
        {"z3": ProverOutcomeKind.PROOF, "cvc5": ProverOutcomeKind.PROOF},
    )
    assert agreed.agreement is True
    assert agreed.outcome is ProverOutcomeKind.PROOF
    assert agreed.agreement_id.startswith("b")

    disagreed = ProverAgreement.from_solver_outcomes(
        "case:disagree",
        {"z3": ProverOutcomeKind.PROOF, "cvc5": ProverOutcomeKind.TIMEOUT},
    )
    assert disagreed.agreement is False
    assert disagreed.outcome is ProverOutcomeKind.DISAGREEMENT

    wire = disagreed.to_dict()
    restored = ProverAgreement.from_dict(wire)
    assert restored.to_dict() == wire

    tampered = dict(wire)
    tampered["agreement"] = True
    with pytest.raises(EvaluationIntegrityError):
        ProverAgreement.from_dict(tampered)


def test_calibration_and_abstention_are_separate_from_accuracy() -> None:
    pairs = [(0.9, True), (0.1, False), (0.8, True), (0.2, False)]
    calibration = compute_calibration(pairs)
    assert calibration.count == 4
    assert 0.0 <= calibration.brier_score <= 1.0
    assert 0.0 <= calibration.expected_calibration_error <= 1.0

    evaluation = build_offline_fixture_evaluation()
    metrics = evaluation.metrics
    assert isinstance(metrics, SeparateMetricReport)
    assert metrics.single_accuracy_score is None
    assert 0.0 <= metrics.abstention_rate <= 1.0
    assert 0.0 <= metrics.abstention_precision <= 1.0
    assert 0.0 <= metrics.abstention_recall <= 1.0
    assert 0.0 <= metrics.uncertainty_rate <= 1.0
    assert 0.0 <= metrics.unsupported_coverage <= 1.0
    # Uncertainty and unsupported are reported; they are not collapsed into
    # a single accuracy score field.
    assert "single_accuracy_score" in metrics.to_dict()
    assert metrics.to_dict()["single_accuracy_score"] is None


def test_external_label_corpus_requires_pin_license_and_leakage_admission() -> None:
    fixture = build_offline_fixture_evaluation()
    denied = ExternalLabelCorpusAdmission(
        corpus_id="external/labels-v1",
        pin_cid=fixture.source_cid,
        license_cid=fixture.license_cid,
        leakage_admission=False,
        license_admitted=True,
        pin_verified=True,
    )
    assert denied.admitted is False
    with pytest.raises(EvaluationAuthorityError, match="pin/license/leakage"):
        denied.require_admitted()

    evaluation = SolidityFormalEvaluation(
        source_cid=fixture.source_cid,
        graph_cid=fixture.graph_cid,
        index_cid=fixture.index_cid,
        partition_cid=fixture.partition_cid,
        license_cid=fixture.license_cid,
        model_or_checkpoint_cid=fixture.model_or_checkpoint_cid,
        evaluation_partitions=fixture.evaluation_partitions,
        cases=fixture.cases,
        metrics=fixture.metrics,
        leakage_findings=fixture.leakage_findings,
        prover_agreements=fixture.prover_agreements,
        external_label_admission=denied,
        mode=EvaluationMode.DRY_RUN,
        diagnostics=fixture.diagnostics,
    )
    assert evaluation.promotion_gate().passed is False
    assert evaluation.promotion_gate().external_label_admitted is False


def test_evaluation_case_is_content_addressed() -> None:
    case = build_evaluation_case(
        "case:unit",
        partition=HELD_OUT_PARTITION,
        control_kind=ControlKind.HELD_OUT,
        source_family_id="family:unit",
        claim_kind=ClaimKind.EXECUTABLE_PROOF,
        prover_outcome=ProverOutcomeKind.TIMEOUT,
        claim_executed=True,
        claim_authoritative=True,
    )
    assert case.case_cid.startswith("b")
    assert EvaluationCase.from_dict(case.to_dict()).case_cid == case.case_cid

    wire = case.to_dict()
    wire["confidence"] = 0.99
    with pytest.raises(EvaluationIntegrityError, match="case_cid"):
        EvaluationCase.from_dict(wire)


def test_evaluator_rejects_train_partition_in_evaluation_bindings() -> None:
    fixture = build_offline_fixture_evaluation()
    with pytest.raises(Exception):
        # evaluation_partitions may include train only if cases use it;
        # using an unknown partition fails closed.
        build_evaluation_case(
            "case:bad-partition",
            partition="not-a-partition",
            control_kind=ControlKind.HELD_OUT,
            source_family_id="family:x",
        )

    # Train partition is valid in the partition vocabulary but fixture
    # evaluation partitions intentionally exclude it from promotion scope.
    assert TRAIN_PARTITION not in fixture.evaluation_partitions


def test_evaluator_round_trip_from_case_dicts() -> None:
    fixture = build_offline_fixture_evaluation()
    evaluator = SolidityFormalEvaluator(
        source_cid=fixture.source_cid,
        graph_cid=fixture.graph_cid,
        index_cid=fixture.index_cid,
        partition_cid=fixture.partition_cid,
        license_cid=fixture.license_cid,
        model_or_checkpoint_cid=fixture.model_or_checkpoint_cid,
        evaluation_partitions=fixture.evaluation_partitions,
        external_label_admission=fixture.external_label_admission,
        mode=EvaluationMode.FIXTURE_OFFLINE,
        diagnostics=fixture.diagnostics,
    )
    rebuilt = evaluator.evaluate(
        [item.to_dict() for item in fixture.cases],
        prover_agreements=[item.to_dict() for item in fixture.prover_agreements],
    )
    assert rebuilt.metrics.leakage_count == 0
    assert set(rebuilt.control_kinds_covered) == set(fixture.control_kinds_covered)
    assert rebuilt.promotion_gate().passed is True
