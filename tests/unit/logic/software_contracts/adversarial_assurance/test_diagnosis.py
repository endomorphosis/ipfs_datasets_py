"""Unit vectors for surviving-mutant diagnosis (AAE-030)."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.common import (
    ArtifactProvenance,
    AssuranceArtifactHeader,
    AssuranceTerminalStatus,
    AuthoritySource,
    ExecutionMode,
    GeneratorIdentity,
    VersionBinding,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.analysis_contracts import (
    AssuranceGapClass,
    GapSeverity,
    MinimizedEvidenceBinding,
    SourceSpan,
    SurvivorRiskClass,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.execution_contracts import (
    DetectorClassification,
    DetectorKind,
    DetectorPrediction,
    DetectorStrength,
    EquivalenceAssessmentStatus,
    ExpectedDetectionSet,
    MutationOutcomeStatus,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.gaps import (
    DetectorObservation,
    compare_detection_sets,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.diagnosis import (
    DIAGNOSE_SURVIVING_MUTANT_INTERFACE,
    DIAGNOSIS_STEP_ORDER,
    GENERATOR_ID,
    DiagnosisDisposition,
    DiagnosisError,
    DiagnosisMutationBinding,
    DiagnosisOutcomeBinding,
    DiagnosisSignals,
    DiagnosisStepId,
    DiagnosisStepVerdict,
    SurvivorDiagnosis,
    diagnose_surviving_mutant,
    diagnosis_dispositions,
    diagnosis_step_ids,
    diagnosis_step_verdicts,
    verify_survivor_diagnosis_identity,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


REPO_ID = "repository:sha256:test-repo-identity"
REPO_STATE = _cid("repo-state")
CANDIDATE_ID = "cand_control_flow_invert_0"
CANDIDATE_CID = _cid("candidate")
OUTCOME_CID = _cid("outcome")


def _generator(**overrides: object) -> GeneratorIdentity:
    fields = {
        "generator_id": "mutation_campaign",
        "generator_version": "1.0.0",
        "interface_id": "generate_mutation_candidates@1",
    }
    fields.update(overrides)
    return GeneratorIdentity(**fields)  # type: ignore[arg-type]


def _versions(**overrides: object) -> VersionBinding:
    fields = {
        "operator_id": "control_flow_invert",
        "operator_version": "1",
        "campaign_policy_id": "default_campaign",
        "campaign_policy_version": "1.0.0",
        "generator": _generator(),
    }
    fields.update(overrides)
    return VersionBinding(**fields)  # type: ignore[arg-type]


def _provenance(**overrides: object) -> ArtifactProvenance:
    fields = {
        "producer_id": "adversarial_assurance",
        "producer_version": "1",
        "execution_mode": ExecutionMode.LIVE,
        "authority_source": AuthoritySource.OBSERVED,
        "input_cids": (_cid("input-a"),),
        "tool_ids": ("analyzer.v1",),
        "policy_cid": _cid("policy"),
        "notes": None,
    }
    fields.update(overrides)
    return ArtifactProvenance(**fields)  # type: ignore[arg-type]


def _header(artifact_kind: str = "mutation_candidate", **overrides: object) -> AssuranceArtifactHeader:
    fields = {
        "artifact_kind": artifact_kind,
        "repository_id": REPO_ID,
        "repository_state_cid": REPO_STATE,
        "target_symbol_ids": ("mod.fn",),
        "target_artifact_cids": (_cid("artifact-a"),),
        "capsule_cids": (_cid("capsule-a"),),
        "proof_unit_cids": (_cid("proof-unit-a"),),
        "environment_cid": _cid("environment"),
        "dependency_lock_cid": _cid("dependency-lock"),
        "versions": _versions(),
        "provenance": _provenance(),
        "terminal_status": AssuranceTerminalStatus.COMPLETE,
        "receipt_cids": (_cid("receipt-a"),),
        "proof_cids": (_cid("proof-a"),),
        "metadata": {},
    }
    fields.update(overrides)
    return AssuranceArtifactHeader(**fields)  # type: ignore[arg-type]


def _span(**overrides: object) -> SourceSpan:
    fields = {
        "path": "src/mod.py",
        "start_line": 10,
        "end_line": 12,
        "start_col": 0,
        "end_col": 40,
    }
    fields.update(overrides)
    return SourceSpan(**fields)  # type: ignore[arg-type]


def _evidence(**overrides: object) -> MinimizedEvidenceBinding:
    fields = {
        "evidence_cids": (_cid("min-evidence-1"),),
        "minimized": True,
        "minimization_failed": False,
        "reproduction_input_cid": _cid("repro-input"),
        "notes": None,
    }
    fields.update(overrides)
    return MinimizedEvidenceBinding(**fields)  # type: ignore[arg-type]


def _mutation(**overrides: object) -> DiagnosisMutationBinding:
    fields = {
        "candidate_id": CANDIDATE_ID,
        "candidate_cid": CANDIDATE_CID,
        "risk_class": SurvivorRiskClass.CRITICAL_SECURITY,
        "symbol_ids": ("mod.fn",),
        "violated_or_missing_property": "authz.must_deny_cross_tenant",
        "source_spans": (_span(),),
        "dependency_path": ("mod.fn", "authz.check"),
        "header": _header(),
        "transformation_summary": "invert tenant guard",
        "likely_equivalent": False,
    }
    fields.update(overrides)
    return DiagnosisMutationBinding(**fields)  # type: ignore[arg-type]


def _outcome(**overrides: object) -> DiagnosisOutcomeBinding:
    fields = {
        "outcome_id": f"{CANDIDATE_ID}.outcome",
        "outcome_cid": OUTCOME_CID,
        "outcome_status": MutationOutcomeStatus.SURVIVED_SELECTED_VERIFICATION,
        "candidate_id": CANDIDATE_ID,
        "candidate_cid": CANDIDATE_CID,
        "expected_detection_set_cid": _cid("expected-detection"),
    }
    fields.update(overrides)
    return DiagnosisOutcomeBinding(**fields)  # type: ignore[arg-type]


def _signals(**overrides: object) -> DiagnosisSignals:
    fields = {
        "observation_complete": True,
        "minimized_evidence": _evidence(),
    }
    fields.update(overrides)
    return DiagnosisSignals(**fields)  # type: ignore[arg-type]


def _diagnose(**overrides: object) -> SurvivorDiagnosis:
    mutation = overrides.pop("mutation", _mutation())
    outcome = overrides.pop("outcome", _outcome())
    repository_state = overrides.pop("repository_state", REPO_STATE)
    signals = overrides.pop("signals", _signals())
    comparison = overrides.pop("comparison", None)
    return diagnose_surviving_mutant(
        mutation,
        outcome,
        repository_state,
        signals=signals,
        comparison=comparison,
        **overrides,  # type: ignore[arg-type]
    )


def _prediction(
    detector_id: str = "unit.test_branch",
    *,
    kind: DetectorKind = DetectorKind.UNIT_TEST,
) -> DetectorPrediction:
    return DetectorPrediction(
        detector_id=detector_id,
        detector_kind=kind,
        violated_claim="branch invariant must hold",
        observation_rationale="detector should observe the inverted branch",
        dependency_path=("mod.fn", detector_id),
        strength=DetectorStrength.REQUIRED,
        expected_terminal_status=AssuranceTerminalStatus.COMPLETE,
    )


def _expected(*predictions: DetectorPrediction) -> ExpectedDetectionSet:
    preds = predictions or (_prediction(),)
    return ExpectedDetectionSet(
        header=_header(artifact_kind="expected_detection_set"),
        detection_set_id="eds_1",
        candidate_id=CANDIDATE_ID,
        candidate_cid=CANDIDATE_CID,
        predicted_detectors=preds,
    )


def _classification(
    *,
    predicted: tuple[str, ...] = ("unit.test_branch",),
    selected: tuple[str, ...] = (),
    executed: tuple[str, ...] = (),
    observed: tuple[str, ...] = (),
) -> DetectorClassification:
    return DetectorClassification(
        predicted_detector_ids=predicted,
        selected_detector_ids=selected,
        executed_detector_ids=executed,
        observed_detector_ids=observed,
    )


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


def test_nine_step_order_is_exactly_nine() -> None:
    steps = diagnosis_step_ids()
    assert len(steps) == 9
    assert steps == DIAGNOSIS_STEP_ORDER
    assert steps == (
        DiagnosisStepId.EQUIVALENCE.value,
        DiagnosisStepId.DETECTOR_SELECTION.value,
        DiagnosisStepId.DETECTOR_EXECUTION.value,
        DiagnosisStepId.PATH_OBSERVATION.value,
        DiagnosisStepId.ASSERTION_STRENGTH.value,
        DiagnosisStepId.DEPENDENCY_OMISSION.value,
        DiagnosisStepId.CAPSULE_OMISSION.value,
        DiagnosisStepId.UNSPECIFIED_OR_INTENTIONAL.value,
        DiagnosisStepId.HUMAN_JUDGMENT.value,
    )
    assert DiagnosisDisposition.PRODUCT_DEFECT.value in diagnosis_dispositions()
    assert DiagnosisDisposition.ASSURANCE_GAP.value in diagnosis_dispositions()
    assert DiagnosisStepVerdict.TRIGGERED.value in diagnosis_step_verdicts()


# ---------------------------------------------------------------------------
# Core decision path
# ---------------------------------------------------------------------------


def test_diagnose_records_all_nine_steps_in_order() -> None:
    result = _diagnose(
        signals=_signals(
            not_selected_detector_ids=("unit.test_branch",),
            equivalence_status=EquivalenceAssessmentStatus.NOT_EQUIVALENT,
        )
    )
    assert len(result.steps) == 9
    assert tuple(step.step_id for step in result.steps) == DIAGNOSIS_STEP_ORDER
    assert tuple(step.step_index for step in result.steps) == tuple(range(1, 10))
    assert result.header.versions.generator.generator_id == GENERATOR_ID
    assert (
        result.header.versions.generator.interface_id
        == DIAGNOSE_SURVIVING_MUTANT_INTERFACE
    )
    assert result.header.artifact_kind == "survivor_diagnosis"
    assert result.difficulty_to_kill_not_evidence is True
    assert result.survivor_not_automatically_product_defect is True
    verify_survivor_diagnosis_identity(result)


def test_assurance_gap_not_selected() -> None:
    result = _diagnose(
        signals=_signals(
            not_selected_detector_ids=("unit.test_branch",),
            equivalence_status=EquivalenceAssessmentStatus.NOT_EQUIVALENT,
        )
    )
    assert result.disposition == DiagnosisDisposition.ASSURANCE_GAP.value
    assert result.deciding_step_id == DiagnosisStepId.DETECTOR_SELECTION.value
    assert result.gap_cause == "not_selected"
    assert result.gap_class == AssuranceGapClass.TEST_SELECTION_FAILURE.value
    assert result.severity == GapSeverity.CRITICAL.value
    assert result.requires_human_review is False
    assert "product defect" in result.summary.lower() or "not classified as product" in result.summary
    selection = result.steps[1]
    assert selection.triggered is True
    assert selection.related_detector_ids == ("unit.test_branch",)


def test_assurance_gap_not_executed() -> None:
    result = _diagnose(
        signals=_signals(
            not_executed_detector_ids=("unit.test_branch",),
            equivalence_status=EquivalenceAssessmentStatus.NOT_EQUIVALENT,
        )
    )
    assert result.disposition == DiagnosisDisposition.ASSURANCE_GAP.value
    assert result.deciding_step_id == DiagnosisStepId.DETECTOR_EXECUTION.value
    assert result.gap_class == AssuranceGapClass.MISSING_TEST.value


def test_assurance_gap_path_observation() -> None:
    result = _diagnose(
        signals=_signals(
            path_unobserved_detector_ids=("unit.test_branch",),
            equivalence_status=EquivalenceAssessmentStatus.NOT_EQUIVALENT,
        )
    )
    assert result.disposition == DiagnosisDisposition.ASSURANCE_GAP.value
    assert result.deciding_step_id == DiagnosisStepId.PATH_OBSERVATION.value
    assert result.gap_cause == "path_unobserved"


def test_assurance_gap_assertion_strength() -> None:
    result = _diagnose(
        signals=_signals(
            weak_property_detector_ids=("unit.test_branch",),
            equivalence_status=EquivalenceAssessmentStatus.NOT_EQUIVALENT,
        )
    )
    assert result.disposition == DiagnosisDisposition.ASSURANCE_GAP.value
    assert result.deciding_step_id == DiagnosisStepId.ASSERTION_STRENGTH.value
    assert result.gap_class == AssuranceGapClass.WEAK_ASSERTION.value


def test_assurance_gap_dependency_and_capsule() -> None:
    dep = _diagnose(
        signals=_signals(
            dependency_omission_detector_ids=("unit.test_branch",),
            not_selected_detector_ids=("unit.other",),
            equivalence_status=EquivalenceAssessmentStatus.NOT_EQUIVALENT,
        )
    )
    # Dependency omission outranks selection for primary disposition.
    assert dep.disposition == DiagnosisDisposition.ASSURANCE_GAP.value
    assert dep.deciding_step_id == DiagnosisStepId.DEPENDENCY_OMISSION.value
    assert (
        dep.gap_class
        == AssuranceGapClass.STALE_OR_INCOMPLETE_DEPENDENCY_EDGE.value
    )

    cap = _diagnose(
        signals=_signals(
            capsule_omission_detector_ids=("unit.test_branch",),
            equivalence_status=EquivalenceAssessmentStatus.NOT_EQUIVALENT,
        )
    )
    assert cap.deciding_step_id == DiagnosisStepId.CAPSULE_OMISSION.value
    assert cap.gap_class == AssuranceGapClass.CAPSULE_COMPLETENESS_FAILURE.value


def test_equivalence_disposition_not_product_defect() -> None:
    result = _diagnose(
        outcome=_outcome(
            outcome_status=MutationOutcomeStatus.EQUIVALENT,
            equivalence_assessment_cid=_cid("eq-assessment"),
        ),
        signals=_signals(
            equivalence_status=EquivalenceAssessmentStatus.EQUIVALENT,
            # Even with detector misses, equivalence wins.
            not_selected_detector_ids=("unit.test_branch",),
            difficulty_to_kill=True,
        ),
    )
    assert result.disposition == DiagnosisDisposition.EQUIVALENT.value
    assert result.deciding_step_id == DiagnosisStepId.EQUIVALENCE.value
    assert result.disposition != DiagnosisDisposition.PRODUCT_DEFECT.value
    assert result.requires_human_review is False
    eq_step = result.steps[0]
    assert eq_step.triggered is True
    assert eq_step.metadata["difficulty_to_kill_ignored"] is True


def test_probably_equivalent_requires_human_review() -> None:
    result = _diagnose(
        outcome=_outcome(
            outcome_status=MutationOutcomeStatus.PROBABLY_EQUIVALENT,
            equivalence_assessment_cid=_cid("eq-assessment"),
        ),
        signals=_signals(
            equivalence_status=EquivalenceAssessmentStatus.PROBABLY_EQUIVALENT,
            difficulty_to_kill=True,
        ),
    )
    assert result.disposition == DiagnosisDisposition.PROBABLY_EQUIVALENT.value
    assert result.requires_human_review is True
    assert result.severity == GapSeverity.INFORMATIONAL.value


def test_difficulty_to_kill_never_implies_equivalence() -> None:
    """Difficult survivors must not become equivalent without assessment."""

    result = _diagnose(
        signals=_signals(
            difficulty_to_kill=True,
            # no equivalence_status
            not_executed_detector_ids=("unit.test_branch",),
        )
    )
    assert result.disposition != DiagnosisDisposition.EQUIVALENT.value
    assert result.disposition != DiagnosisDisposition.PROBABLY_EQUIVALENT.value
    assert result.disposition == DiagnosisDisposition.ASSURANCE_GAP.value
    assert result.difficulty_to_kill_not_evidence is True
    assert result.metadata["difficulty_to_kill_ignored"] is True
    eq_step = result.steps[0]
    assert eq_step.triggered is False
    assert eq_step.metadata["difficulty_to_kill_ignored"] is True


def test_likely_equivalent_flag_never_drives_equivalence() -> None:
    result = _diagnose(
        mutation=_mutation(likely_equivalent=True),
        signals=_signals(
            not_selected_detector_ids=("unit.test_branch",),
        ),
    )
    assert result.disposition == DiagnosisDisposition.ASSURANCE_GAP.value
    assert result.metadata["likely_equivalent_ignored"] is True


def test_intentionally_unconstrained() -> None:
    result = _diagnose(
        signals=_signals(
            intentionally_unconstrained=True,
            not_selected_detector_ids=("unit.test_branch",),
        )
    )
    assert (
        result.disposition
        == DiagnosisDisposition.INTENTIONALLY_UNCONSTRAINED.value
    )
    assert result.requires_human_review is True
    assert result.gap_class == AssuranceGapClass.INTENTIONALLY_UNCONSTRAINED.value
    assert result.deciding_step_id == (
        DiagnosisStepId.UNSPECIFIED_OR_INTENTIONAL.value
    )


def test_specification_ambiguity() -> None:
    result = _diagnose(
        signals=_signals(specification_ambiguous=True)
    )
    assert (
        result.disposition == DiagnosisDisposition.SPECIFICATION_AMBIGUITY.value
    )
    assert result.requires_human_review is True
    assert result.gap_class == AssuranceGapClass.SPECIFICATION_AMBIGUITY.value


def test_unknown_residual_requires_human_review() -> None:
    result = _diagnose(signals=_signals())
    assert result.disposition == DiagnosisDisposition.UNKNOWN.value
    assert result.requires_human_review is True
    assert result.deciding_step_id == DiagnosisStepId.HUMAN_JUDGMENT.value
    assert result.steps[-1].triggered is True


# ---------------------------------------------------------------------------
# Product versus assurance distinctions
# ---------------------------------------------------------------------------


def test_survival_is_never_automatically_product_defect() -> None:
    """Default survivor paths must not land on product_defect."""

    cases = [
        _signals(
            not_selected_detector_ids=("unit.a",),
            equivalence_status=EquivalenceAssessmentStatus.NOT_EQUIVALENT,
        ),
        _signals(
            not_executed_detector_ids=("unit.a",),
            equivalence_status=EquivalenceAssessmentStatus.NOT_EQUIVALENT,
        ),
        _signals(
            path_unobserved_detector_ids=("unit.a",),
            equivalence_status=EquivalenceAssessmentStatus.NOT_EQUIVALENT,
        ),
        _signals(
            weak_property_detector_ids=("unit.a",),
            equivalence_status=EquivalenceAssessmentStatus.NOT_EQUIVALENT,
        ),
        _signals(
            dependency_omission_detector_ids=("unit.a",),
            equivalence_status=EquivalenceAssessmentStatus.NOT_EQUIVALENT,
        ),
        _signals(
            capsule_omission_detector_ids=("unit.a",),
            equivalence_status=EquivalenceAssessmentStatus.NOT_EQUIVALENT,
        ),
        _signals(),  # residual unknown
        _signals(
            difficulty_to_kill=True,
            not_selected_detector_ids=("unit.a",),
            equivalence_status=EquivalenceAssessmentStatus.NOT_EQUIVALENT,
        ),
    ]
    dispositions: list[str] = []
    for signals in cases:
        result = _diagnose(signals=signals)
        dispositions.append(result.disposition)
        assert result.disposition != DiagnosisDisposition.PRODUCT_DEFECT.value
        assert result.survivor_not_automatically_product_defect is True

    assert DiagnosisDisposition.PRODUCT_DEFECT.value not in dispositions
    assert DiagnosisDisposition.ASSURANCE_GAP.value in dispositions


def test_product_defect_requires_explicit_evidence() -> None:
    # Without evidence flags → not product defect.
    no_product = _diagnose(
        signals=_signals(
            equivalence_status=EquivalenceAssessmentStatus.NOT_EQUIVALENT,
        )
    )
    assert no_product.disposition != DiagnosisDisposition.PRODUCT_DEFECT.value

    # With full explicit evidence → product defect.
    product = _diagnose(
        signals=_signals(
            equivalence_status=EquivalenceAssessmentStatus.NOT_EQUIVALENT,
            product_defect_evidence=True,
            original_behavior_violates_required_property=True,
            product_defect_evidence_cids=(_cid("product-evidence-1"),),
        )
    )
    assert product.disposition == DiagnosisDisposition.PRODUCT_DEFECT.value
    assert product.product_defect_evidence_cids == (_cid("product-evidence-1"),)
    assert product.requires_human_review is True
    assert product.gap_class is None


def test_product_defect_evidence_without_not_equivalent_is_not_product() -> None:
    result = _diagnose(
        signals=_signals(
            product_defect_evidence=True,
            original_behavior_violates_required_property=True,
            product_defect_evidence_cids=(_cid("product-evidence-1"),),
            not_selected_detector_ids=("unit.test_branch",),
            # equivalence_status omitted / unknown → cannot be product_defect
        )
    )
    assert result.disposition != DiagnosisDisposition.PRODUCT_DEFECT.value
    assert result.disposition == DiagnosisDisposition.ASSURANCE_GAP.value


def test_product_defect_signals_fail_closed_without_cids() -> None:
    with pytest.raises(DiagnosisError, match="product_defect_evidence_cids"):
        DiagnosisSignals(
            product_defect_evidence=True,
            original_behavior_violates_required_property=True,
        )


def test_product_defect_signals_fail_closed_without_original_violation() -> None:
    with pytest.raises(
        DiagnosisError, match="original_behavior_violates_required_property"
    ):
        DiagnosisSignals(
            product_defect_evidence=True,
            product_defect_evidence_cids=(_cid("product-evidence-1"),),
        )


# ---------------------------------------------------------------------------
# Fail-closed / identity / comparison integration
# ---------------------------------------------------------------------------


def test_fails_closed_on_incomplete_observation() -> None:
    with pytest.raises(DiagnosisError, match="observation_complete"):
        _diagnose(signals=_signals(observation_complete=False))


def test_fails_closed_on_candidate_mismatch() -> None:
    with pytest.raises(DiagnosisError, match="candidate_id"):
        diagnose_surviving_mutant(
            _mutation(candidate_id="cand_other_0"),
            _outcome(),
            REPO_STATE,
            signals=_signals(),
        )


def test_non_survivor_outcome_is_explicit() -> None:
    result = _diagnose(
        outcome=_outcome(
            outcome_status=MutationOutcomeStatus.KILLED_BY_TEST,
            # killed outcomes normally need killing detector; binding is lighter.
        ),
        signals=_signals(
            not_selected_detector_ids=("unit.test_branch",),
        ),
    )
    assert result.disposition == DiagnosisDisposition.NON_SURVIVOR.value
    assert result.requires_human_review is True
    assert result.gap_class is None


def test_comparison_integration_feeds_detector_partitions() -> None:
    expected = _expected(_prediction("unit.test_branch"))
    classification = _classification(
        predicted=("unit.test_branch",),
        selected=(),
        executed=(),
        observed=(),
    )
    comparison = compare_detection_sets(
        expected,
        classification,
        header=_header(artifact_kind="expected_detection_set"),
        minimized_evidence=_evidence(),
    )
    result = diagnose_surviving_mutant(
        _mutation(),
        _outcome(),
        REPO_STATE,
        signals=_signals(
            equivalence_status=EquivalenceAssessmentStatus.NOT_EQUIVALENT,
        ),
        comparison=comparison,
    )
    assert result.disposition == DiagnosisDisposition.ASSURANCE_GAP.value
    assert result.deciding_step_id == DiagnosisStepId.DETECTOR_SELECTION.value
    assert result.comparison_result_cid == comparison.result_cid
    assert result.steps[1].related_detector_ids == ("unit.test_branch",)


def test_comparison_path_and_weak_property() -> None:
    expected = _expected(_prediction("unit.test_branch"))
    comparison = compare_detection_sets(
        expected,
        _classification(
            predicted=("unit.test_branch",),
            selected=("unit.test_branch",),
            executed=("unit.test_branch",),
            observed=(),
        ),
        header=_header(artifact_kind="expected_detection_set"),
        minimized_evidence=_evidence(),
        detector_observations=(
            DetectorObservation(
                detector_id="unit.test_branch",
                assertion_strength_adequate=False,
            ),
        ),
    )
    result = diagnose_surviving_mutant(
        _mutation(),
        _outcome(),
        REPO_STATE,
        signals=_signals(
            equivalence_status=EquivalenceAssessmentStatus.NOT_EQUIVALENT,
        ),
        comparison=comparison,
    )
    assert result.deciding_step_id == DiagnosisStepId.ASSERTION_STRENGTH.value
    assert result.gap_class == AssuranceGapClass.WEAK_ASSERTION.value


def test_repository_state_mapping_accepted() -> None:
    result = _diagnose(
        repository_state={"repository_state_cid": REPO_STATE},
        signals=_signals(
            not_selected_detector_ids=("unit.test_branch",),
            equivalence_status=EquivalenceAssessmentStatus.NOT_EQUIVALENT,
        ),
    )
    assert result.repository_state_cid == REPO_STATE


def test_mapping_inputs_and_round_trip_identity() -> None:
    mutation = _mutation()
    outcome = _outcome()
    signals = _signals(
        not_executed_detector_ids=("unit.test_branch",),
        equivalence_status=EquivalenceAssessmentStatus.NOT_EQUIVALENT,
    )
    result = diagnose_surviving_mutant(
        mutation.to_dict(),
        outcome.to_dict(),
        REPO_STATE,
        signals=signals.to_dict(),
    )
    restored = SurvivorDiagnosis.from_dict(result.to_dict())
    assert restored.diagnosis_cid == result.diagnosis_cid
    assert verify_survivor_diagnosis_identity(restored) == result.diagnosis_cid


def test_diagnose_is_deterministic() -> None:
    first = _diagnose(
        signals=_signals(
            not_selected_detector_ids=("unit.z", "unit.a"),
            equivalence_status=EquivalenceAssessmentStatus.NOT_EQUIVALENT,
        )
    )
    second = _diagnose(
        signals=_signals(
            not_selected_detector_ids=("unit.z", "unit.a"),
            equivalence_status=EquivalenceAssessmentStatus.NOT_EQUIVALENT,
        )
    )
    assert first.diagnosis_cid == second.diagnosis_cid
    assert first.to_dict() == second.to_dict()


def test_unknown_equivalence_never_becomes_equivalent() -> None:
    result = _diagnose(
        signals=_signals(
            equivalence_status=EquivalenceAssessmentStatus.UNKNOWN,
            difficulty_to_kill=True,
        )
    )
    assert result.disposition != DiagnosisDisposition.EQUIVALENT.value
    assert result.disposition == DiagnosisDisposition.UNKNOWN.value
    assert result.steps[0].verdict == DiagnosisStepVerdict.INCONCLUSIVE.value


def test_forged_diagnosis_cid_rejected() -> None:
    result = _diagnose(
        signals=_signals(
            not_selected_detector_ids=("unit.test_branch",),
            equivalence_status=EquivalenceAssessmentStatus.NOT_EQUIVALENT,
        )
    )
    payload = result.to_dict()
    payload["diagnosis_cid"] = _cid("forged")
    with pytest.raises(DiagnosisError, match="identity mismatch"):
        SurvivorDiagnosis.from_dict(payload)
