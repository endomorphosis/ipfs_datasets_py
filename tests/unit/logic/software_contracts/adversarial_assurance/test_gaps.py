"""Unit vectors for predicted-versus-observed gap classification (AAE-028)."""

from __future__ import annotations

from typing import Sequence

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
    DetectionFailureKind,
    GapSeverity,
    MinimizedEvidenceBinding,
    SourceSpan,
    SurvivorRiskClass,
    verify_gap_identity,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.execution_contracts import (
    DetectorClassification,
    DetectorKind,
    DetectorPrediction,
    DetectorStrength,
    EquivalenceAssessmentStatus,
    ExpectedDetectionSet,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.gaps import (
    CLASSIFY_ASSURANCE_GAP_INTERFACE,
    COMPARE_DETECTION_SETS_INTERFACE,
    GENERATOR_ID,
    AssuranceGapCause,
    DetectionComparisonResult,
    DetectorObservation,
    GapClassificationError,
    GapClassificationSubject,
    assurance_gap_causes,
    cause_to_gap_class,
    classify_assurance_gap,
    compare_detection_sets,
    verify_detection_comparison_result_identity,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


REPO_ID = "repository:sha256:test-repo-identity"
REPO_STATE = _cid("repo-state")
CANDIDATE_ID = "cand_control_flow_invert_0"
CANDIDATE_CID = _cid("candidate")


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


def _header(artifact_kind: str = "expected_detection_set", **overrides: object) -> AssuranceArtifactHeader:
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


def _prediction(
    detector_id: str = "unit.test_branch",
    *,
    kind: DetectorKind = DetectorKind.UNIT_TEST,
    path: tuple[str, ...] | None = None,
) -> DetectorPrediction:
    return DetectorPrediction(
        detector_id=detector_id,
        detector_kind=kind,
        violated_claim="branch invariant must hold",
        observation_rationale="detector should observe the inverted branch",
        dependency_path=path or ("mod.fn", detector_id),
        strength=DetectorStrength.REQUIRED,
        expected_terminal_status=AssuranceTerminalStatus.COMPLETE,
    )


def _expected(
    *predictions: DetectorPrediction,
    **overrides: object,
) -> ExpectedDetectionSet:
    dets = predictions or (_prediction(),)
    fields = {
        "header": _header("expected_detection_set"),
        "detection_set_id": "eds_1",
        "candidate_id": CANDIDATE_ID,
        "candidate_cid": CANDIDATE_CID,
        "predicted_detectors": dets,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return ExpectedDetectionSet(**fields)  # type: ignore[arg-type]


def _classification(
    *,
    predicted: Sequence[str] | None = None,
    selected: Sequence[str] = (),
    executed: Sequence[str] = (),
    observed: Sequence[str] = (),
) -> DetectorClassification:
    predicted_ids = tuple(predicted) if predicted is not None else ("unit.test_branch",)
    return DetectorClassification(
        predicted_detector_ids=predicted_ids,
        selected_detector_ids=selected,
        executed_detector_ids=executed,
        observed_detector_ids=observed,
    )


def _subject(**overrides: object) -> GapClassificationSubject:
    fields = {
        "candidate_id": CANDIDATE_ID,
        "candidate_cid": CANDIDATE_CID,
        "risk_class": SurvivorRiskClass.AUTHORIZATION,
        "violated_or_missing_property": "authorization check must remain present",
        "symbol_ids": ("mod.fn",),
        "source_spans": (_span(),),
        "dependency_path": ("mod.fn", "authz.check"),
        "minimized_evidence": _evidence(),
        "header": _header("surviving_mutant_report"),
        "gap_id": "gap.authz.1",
        "survivor_report_cid": None,
        "equivalence_status": None,
        "intentionally_unconstrained": False,
        "specification_ambiguous": False,
        "observation_complete": True,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return GapClassificationSubject(**fields)  # type: ignore[arg-type]


def _compare(
    expected: ExpectedDetectionSet | None = None,
    classification: DetectorClassification | None = None,
    **kwargs: object,
) -> DetectionComparisonResult:
    exp = expected if expected is not None else _expected()
    if classification is None:
        classification = _classification(
            predicted=exp.predicted_detector_ids,
            selected=(),
            executed=(),
            observed=(),
        )
    return compare_detection_sets(
        exp,
        classification,
        header=_header(),
        minimized_evidence=_evidence(),
        **kwargs,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Closed taxonomy
# ---------------------------------------------------------------------------


def test_closed_gap_cause_taxonomy_matches_acceptance() -> None:
    causes = assurance_gap_causes()
    assert causes == (
        "not_selected",
        "not_executed",
        "path_unobserved",
        "weak_property",
        "dependency_omission",
        "capsule_omission",
        "unspecified",
        "intentional",
        "equivalence",
        "unknown",
    )
    # Reject open-world values (enum and mapping helper).
    with pytest.raises(ValueError):
        AssuranceGapCause("maybe_selected")
    with pytest.raises(GapClassificationError):
        cause_to_gap_class("maybe_selected")


def test_cause_to_gap_class_mapping() -> None:
    assert (
        cause_to_gap_class(AssuranceGapCause.NOT_SELECTED)
        == AssuranceGapClass.TEST_SELECTION_FAILURE.value
    )
    assert (
        cause_to_gap_class(AssuranceGapCause.NOT_EXECUTED)
        == AssuranceGapClass.MISSING_TEST.value
    )
    assert (
        cause_to_gap_class(
            AssuranceGapCause.NOT_EXECUTED,
            detector_kind=DetectorKind.FORMAL_OBLIGATION,
        )
        == AssuranceGapClass.MISSING_PROOF_OBLIGATION.value
    )
    assert (
        cause_to_gap_class(
            AssuranceGapCause.NOT_EXECUTED,
            detector_kind=DetectorKind.POLICY_RULE,
        )
        == AssuranceGapClass.MISSING_POLICY_CONSTRAINT.value
    )
    assert (
        cause_to_gap_class(AssuranceGapCause.PATH_UNOBSERVED)
        == AssuranceGapClass.MISSING_TEST.value
    )
    assert (
        cause_to_gap_class(AssuranceGapCause.WEAK_PROPERTY)
        == AssuranceGapClass.WEAK_ASSERTION.value
    )
    assert (
        cause_to_gap_class(AssuranceGapCause.DEPENDENCY_OMISSION)
        == AssuranceGapClass.STALE_OR_INCOMPLETE_DEPENDENCY_EDGE.value
    )
    assert (
        cause_to_gap_class(AssuranceGapCause.CAPSULE_OMISSION)
        == AssuranceGapClass.CAPSULE_COMPLETENESS_FAILURE.value
    )
    assert (
        cause_to_gap_class(AssuranceGapCause.UNSPECIFIED)
        == AssuranceGapClass.SPECIFICATION_AMBIGUITY.value
    )
    assert (
        cause_to_gap_class(AssuranceGapCause.INTENTIONAL)
        == AssuranceGapClass.INTENTIONALLY_UNCONSTRAINED.value
    )
    assert (
        cause_to_gap_class(AssuranceGapCause.EQUIVALENCE)
        == AssuranceGapClass.PROBABLY_EQUIVALENT.value
    )
    assert cause_to_gap_class(AssuranceGapCause.UNKNOWN) == AssuranceGapClass.UNKNOWN.value


# ---------------------------------------------------------------------------
# compare_detection_sets — role separation
# ---------------------------------------------------------------------------


def test_compare_not_selected() -> None:
    result = _compare(
        classification=_classification(
            predicted=("unit.test_branch",),
            selected=(),
            executed=(),
            observed=(),
        )
    )
    assert result.interface_id == COMPARE_DETECTION_SETS_INTERFACE
    assert result.primary_cause == AssuranceGapCause.NOT_SELECTED.value
    assert result.not_selected_detector_ids == ("unit.test_branch",)
    assert result.not_executed_detector_ids == ()
    assert result.path_unobserved_detector_ids == ()
    assert len(result.failures) == 1
    failure = result.failures[0]
    assert failure.failure_kind == DetectionFailureKind.SELECTION_MISS.value
    assert failure.predicted is True
    assert failure.selected is False
    verify_detection_comparison_result_identity(result)
    restored = DetectionComparisonResult.from_dict(result.to_dict())
    assert restored.result_cid == result.result_cid


def test_compare_not_executed() -> None:
    result = _compare(
        classification=_classification(
            predicted=("unit.test_branch",),
            selected=("unit.test_branch",),
            executed=(),
            observed=(),
        )
    )
    assert result.primary_cause == AssuranceGapCause.NOT_EXECUTED.value
    assert result.not_executed_detector_ids == ("unit.test_branch",)
    assert result.failures[0].failure_kind == DetectionFailureKind.EXECUTION_MISS.value
    assert result.failures[0].selected is True
    assert result.failures[0].executed is False


def test_compare_path_unobserved_default() -> None:
    result = _compare(
        classification=_classification(
            predicted=("unit.test_branch",),
            selected=("unit.test_branch",),
            executed=("unit.test_branch",),
            observed=(),
        )
    )
    assert result.primary_cause == AssuranceGapCause.PATH_UNOBSERVED.value
    assert result.path_unobserved_detector_ids == ("unit.test_branch",)
    assert result.failures[0].failure_kind == DetectionFailureKind.OBSERVATION_MISS.value
    assert result.failures[0].executed is True
    assert result.failures[0].observed is False


def test_compare_path_unobserved_explicit_annotation() -> None:
    result = _compare(
        classification=_classification(
            predicted=("unit.test_branch",),
            selected=("unit.test_branch",),
            executed=("unit.test_branch",),
            observed=(),
        ),
        detector_observations=(
            DetectorObservation(
                detector_id="unit.test_branch",
                path_observed=False,
            ),
        ),
    )
    assert result.primary_cause == AssuranceGapCause.PATH_UNOBSERVED.value
    assert result.failures[0].failure_kind == DetectionFailureKind.PATH_MISS.value


def test_compare_weak_property() -> None:
    result = _compare(
        classification=_classification(
            predicted=("unit.test_branch",),
            selected=("unit.test_branch",),
            executed=("unit.test_branch",),
            observed=(),
        ),
        detector_observations=(
            DetectorObservation(
                detector_id="unit.test_branch",
                assertion_strength_adequate=False,
            ),
        ),
    )
    assert result.primary_cause == AssuranceGapCause.WEAK_PROPERTY.value
    assert result.weak_property_detector_ids == ("unit.test_branch",)
    assert (
        result.failures[0].failure_kind
        == DetectionFailureKind.ASSERTION_STRENGTH_FAILURE.value
    )


def test_compare_dependency_omission() -> None:
    result = _compare(
        classification=_classification(
            predicted=("unit.test_branch",),
            selected=("unit.test_branch",),
            executed=("unit.test_branch",),
            observed=(),
        ),
        detector_observations=(
            DetectorObservation(
                detector_id="unit.test_branch",
                dependency_edge_present=False,
            ),
        ),
    )
    assert result.primary_cause == AssuranceGapCause.DEPENDENCY_OMISSION.value
    assert result.dependency_omission_detector_ids == ("unit.test_branch",)
    assert result.failures[0].failure_kind == DetectionFailureKind.PATH_MISS.value


def test_compare_capsule_omission() -> None:
    result = _compare(
        classification=_classification(
            predicted=("unit.test_branch",),
            selected=("unit.test_branch",),
            executed=("unit.test_branch",),
            observed=(),
        ),
        detector_observations=(
            DetectorObservation(
                detector_id="unit.test_branch",
                capsule_complete=False,
            ),
        ),
    )
    assert result.primary_cause == AssuranceGapCause.CAPSULE_OMISSION.value
    assert result.capsule_omission_detector_ids == ("unit.test_branch",)


def test_compare_observed_as_predicted_and_unexpected() -> None:
    expected = _expected(
        _prediction("unit.test_a"),
        _prediction("unit.test_b"),
    )
    result = _compare(
        expected=expected,
        classification=_classification(
            predicted=("unit.test_a", "unit.test_b"),
            selected=("unit.test_a", "unit.test_b", "unit.extra"),
            executed=("unit.test_a", "unit.test_b", "unit.extra"),
            observed=("unit.test_a", "unit.extra"),
        ),
    )
    assert result.observed_as_predicted_detector_ids == ("unit.test_a",)
    assert result.unexpected_detector_ids == ("unit.extra",)
    # unit.test_b executed but not observed → path_unobserved dominates.
    assert result.primary_cause == AssuranceGapCause.PATH_UNOBSERVED.value
    assert result.path_unobserved_detector_ids == ("unit.test_b",)
    unexpected_failures = [
        item
        for item in result.failures
        if item.failure_kind == DetectionFailureKind.UNEXPECTED_OBSERVED.value
    ]
    assert len(unexpected_failures) == 1
    assert unexpected_failures[0].predicted is False
    assert unexpected_failures[0].observed is True


def test_compare_priority_dependency_over_selection() -> None:
    """When multiple miss classes exist, primary prefers structural omissions."""

    expected = _expected(
        _prediction("unit.selected_miss"),
        _prediction("unit.dep_miss"),
    )
    result = _compare(
        expected=expected,
        classification=_classification(
            predicted=("unit.dep_miss", "unit.selected_miss"),
            selected=("unit.dep_miss",),
            executed=("unit.dep_miss",),
            observed=(),
        ),
        detector_observations=(
            DetectorObservation(
                detector_id="unit.dep_miss",
                dependency_edge_present=False,
            ),
        ),
    )
    assert result.not_selected_detector_ids == ("unit.selected_miss",)
    assert result.dependency_omission_detector_ids == ("unit.dep_miss",)
    assert result.primary_cause == AssuranceGapCause.DEPENDENCY_OMISSION.value


def test_compare_rejects_predicted_set_drift() -> None:
    with pytest.raises(GapClassificationError, match="predicted_detector_ids"):
        compare_detection_sets(
            _expected(_prediction("unit.a")),
            _classification(predicted=("unit.b",)),
            header=_header(),
            minimized_evidence=_evidence(),
        )


def test_compare_rejects_duplicate_observation_ids() -> None:
    with pytest.raises(GapClassificationError, match="unique"):
        compare_detection_sets(
            _expected(),
            _classification(
                predicted=("unit.test_branch",),
                selected=("unit.test_branch",),
                executed=("unit.test_branch",),
                observed=(),
            ),
            header=_header(),
            minimized_evidence=_evidence(),
            detector_observations=(
                DetectorObservation(detector_id="unit.test_branch"),
                DetectorObservation(detector_id="unit.test_branch"),
            ),
        )


def test_compare_is_deterministic() -> None:
    expected = _expected(
        _prediction("unit.z"),
        _prediction("unit.a"),
    )
    classification = _classification(
        predicted=("unit.a", "unit.z"),
        selected=("unit.a",),
        executed=(),
        observed=(),
    )
    first = compare_detection_sets(
        expected,
        classification,
        header=_header(),
        minimized_evidence=_evidence(),
    )
    second = compare_detection_sets(
        expected,
        classification,
        header=_header(),
        minimized_evidence=_evidence(),
    )
    assert first.result_cid == second.result_cid
    assert first.to_dict() == second.to_dict()


# ---------------------------------------------------------------------------
# classify_assurance_gap
# ---------------------------------------------------------------------------


def test_classify_not_selected_maps_to_test_selection_failure() -> None:
    comparison = _compare(
        classification=_classification(
            predicted=("unit.test_branch",),
            selected=(),
            executed=(),
            observed=(),
        )
    )
    gap = classify_assurance_gap(_subject(gap_id="gap.not_selected.1"), comparison)
    assert gap.gap_class == AssuranceGapClass.TEST_SELECTION_FAILURE.value
    assert gap.severity == GapSeverity.CRITICAL.value
    assert gap.requires_human_review is False
    assert gap.detection_failure_cids
    assert gap.metadata["cause"] == AssuranceGapCause.NOT_SELECTED.value
    assert gap.header.versions.generator.generator_id == GENERATOR_ID
    assert (
        gap.header.versions.generator.interface_id
        == CLASSIFY_ASSURANCE_GAP_INTERFACE
    )
    verify_gap_identity(gap)


def test_classify_not_executed_maps_to_missing_test() -> None:
    comparison = _compare(
        classification=_classification(
            predicted=("unit.test_branch",),
            selected=("unit.test_branch",),
            executed=(),
            observed=(),
        )
    )
    gap = classify_assurance_gap(_subject(gap_id="gap.not_executed.1"), comparison)
    assert gap.gap_class == AssuranceGapClass.MISSING_TEST.value
    assert gap.metadata["cause"] == AssuranceGapCause.NOT_EXECUTED.value


def test_classify_not_executed_formal_maps_to_missing_proof() -> None:
    expected = _expected(
        _prediction("proof.obligation", kind=DetectorKind.FORMAL_OBLIGATION)
    )
    comparison = _compare(
        expected=expected,
        classification=_classification(
            predicted=("proof.obligation",),
            selected=("proof.obligation",),
            executed=(),
            observed=(),
        ),
    )
    gap = classify_assurance_gap(_subject(gap_id="gap.proof.1"), comparison)
    assert gap.gap_class == AssuranceGapClass.MISSING_PROOF_OBLIGATION.value


def test_classify_path_unobserved() -> None:
    comparison = _compare(
        classification=_classification(
            predicted=("unit.test_branch",),
            selected=("unit.test_branch",),
            executed=("unit.test_branch",),
            observed=(),
        )
    )
    gap = classify_assurance_gap(_subject(gap_id="gap.path.1"), comparison)
    assert gap.metadata["cause"] == AssuranceGapCause.PATH_UNOBSERVED.value
    assert gap.gap_class == AssuranceGapClass.MISSING_TEST.value


def test_classify_weak_property() -> None:
    comparison = _compare(
        classification=_classification(
            predicted=("unit.test_branch",),
            selected=("unit.test_branch",),
            executed=("unit.test_branch",),
            observed=(),
        ),
        detector_observations=(
            DetectorObservation(
                detector_id="unit.test_branch",
                assertion_strength_adequate=False,
            ),
        ),
    )
    gap = classify_assurance_gap(_subject(gap_id="gap.weak.1"), comparison)
    assert gap.gap_class == AssuranceGapClass.WEAK_ASSERTION.value
    assert gap.metadata["cause"] == AssuranceGapCause.WEAK_PROPERTY.value


def test_classify_dependency_and_capsule_omission() -> None:
    dep = _compare(
        classification=_classification(
            predicted=("unit.test_branch",),
            selected=("unit.test_branch",),
            executed=("unit.test_branch",),
            observed=(),
        ),
        detector_observations=(
            DetectorObservation(
                detector_id="unit.test_branch",
                dependency_edge_present=False,
            ),
        ),
    )
    gap_dep = classify_assurance_gap(_subject(gap_id="gap.dep.1"), dep)
    assert (
        gap_dep.gap_class
        == AssuranceGapClass.STALE_OR_INCOMPLETE_DEPENDENCY_EDGE.value
    )

    cap = _compare(
        classification=_classification(
            predicted=("unit.test_branch",),
            selected=("unit.test_branch",),
            executed=("unit.test_branch",),
            observed=(),
        ),
        detector_observations=(
            DetectorObservation(
                detector_id="unit.test_branch",
                capsule_complete=False,
            ),
        ),
    )
    gap_cap = classify_assurance_gap(_subject(gap_id="gap.cap.1"), cap)
    assert gap_cap.gap_class == AssuranceGapClass.CAPSULE_COMPLETENESS_FAILURE.value


def test_classify_unspecified_and_intentional_and_equivalence() -> None:
    # Equivalence wins over detector misses.
    comparison = _compare(
        classification=_classification(
            predicted=("unit.test_branch",),
            selected=(),
            executed=(),
            observed=(),
        )
    )
    gap_eq = classify_assurance_gap(
        _subject(
            gap_id="gap.eq.1",
            equivalence_status=EquivalenceAssessmentStatus.PROBABLY_EQUIVALENT,
        ),
        comparison,
    )
    assert gap_eq.gap_class == AssuranceGapClass.PROBABLY_EQUIVALENT.value
    assert gap_eq.requires_human_review is True
    assert gap_eq.severity == GapSeverity.INFORMATIONAL.value
    assert gap_eq.metadata["cause"] == AssuranceGapCause.EQUIVALENCE.value

    gap_int = classify_assurance_gap(
        _subject(gap_id="gap.int.1", intentionally_unconstrained=True),
        comparison,
    )
    assert gap_int.gap_class == AssuranceGapClass.INTENTIONALLY_UNCONSTRAINED.value
    assert gap_int.requires_human_review is True
    assert gap_int.metadata["cause"] == AssuranceGapCause.INTENTIONAL.value

    gap_unspec = classify_assurance_gap(
        _subject(gap_id="gap.unspec.1", specification_ambiguous=True),
        comparison,
    )
    assert gap_unspec.gap_class == AssuranceGapClass.SPECIFICATION_AMBIGUITY.value
    assert gap_unspec.requires_human_review is True
    assert gap_unspec.metadata["cause"] == AssuranceGapCause.UNSPECIFIED.value


def test_classify_unknown_requires_human_review() -> None:
    # Fully observed predicted detectors → residual unknown without other signals.
    comparison = _compare(
        classification=_classification(
            predicted=("unit.test_branch",),
            selected=("unit.test_branch",),
            executed=("unit.test_branch",),
            observed=("unit.test_branch",),
        )
    )
    gap = classify_assurance_gap(_subject(gap_id="gap.unknown.1"), comparison)
    assert gap.gap_class == AssuranceGapClass.UNKNOWN.value
    assert gap.requires_human_review is True
    assert gap.metadata["cause"] == AssuranceGapCause.UNKNOWN.value


def test_classify_fails_closed_on_incomplete_observation() -> None:
    with pytest.raises(GapClassificationError, match="observation_complete"):
        classify_assurance_gap(
            _subject(observation_complete=False),
            _compare(),
        )


def test_classify_fails_closed_on_candidate_mismatch() -> None:
    comparison = _compare()
    with pytest.raises(GapClassificationError, match="candidate_id"):
        classify_assurance_gap(
            _subject(candidate_id="cand_other_0"),
            comparison,
        )


def test_classify_without_comparison_is_unknown() -> None:
    gap = classify_assurance_gap(_subject(gap_id="gap.solo.1"), None)
    assert gap.gap_class == AssuranceGapClass.UNKNOWN.value
    assert gap.requires_human_review is True
    assert gap.detection_failure_cids == ()


def test_equivalence_never_inferred_from_misses_alone() -> None:
    """Missed detectors alone must not become probably_equivalent."""

    comparison = _compare(
        classification=_classification(
            predicted=("unit.test_branch",),
            selected=("unit.test_branch",),
            executed=("unit.test_branch",),
            observed=(),
        )
    )
    gap = classify_assurance_gap(_subject(gap_id="gap.no_eq.1"), comparison)
    assert gap.gap_class != AssuranceGapClass.PROBABLY_EQUIVALENT.value
    assert gap.metadata["cause"] != AssuranceGapCause.EQUIVALENCE.value


def test_round_trip_subject_and_observation_identity() -> None:
    subject = _subject(gap_id="gap.roundtrip.1")
    restored = GapClassificationSubject.from_dict(subject.to_dict())
    assert restored.subject_cid == subject.subject_cid

    obs = DetectorObservation(
        detector_id="unit.test_branch",
        path_observed=False,
        assertion_strength_adequate=True,
    )
    restored_obs = DetectorObservation.from_dict(obs.to_dict())
    assert restored_obs.observation_cid == obs.observation_cid
