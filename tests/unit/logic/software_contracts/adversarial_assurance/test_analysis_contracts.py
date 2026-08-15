"""Contract vectors for survivor, gap, vacuity, detection-failure, and adequacy models (AAE-010)."""

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
    AdequacyVerdict,
    AnalysisContractError,
    AssuranceGap,
    AssuranceGapClass,
    CapsuleAdequacyGapClass,
    CapsuleAdequacyProfile,
    DetectionFailure,
    DetectionFailureKind,
    GapSeverity,
    MinimizedEvidenceBinding,
    PolicyAdequacyGapClass,
    PolicyAdequacyProfile,
    ProofAdequacyGapClass,
    ProofAdequacyProfile,
    SourceSpan,
    SurvivingMutantReport,
    SurvivorRiskClass,
    TestAdequacyGapClass,
    TestAdequacyProfile,
    VacuityFamily,
    VacuityFinding,
    VacuityKind,
    adequacy_verdicts,
    assurance_gap_classes,
    capsule_adequacy_gap_classes,
    detection_failure_kinds,
    gap_severities,
    policy_adequacy_gap_classes,
    proof_adequacy_gap_classes,
    survivor_risk_classes,
    test_adequacy_gap_classes,
    vacuity_families,
    vacuity_kinds,
    vacuity_kinds_for_family,
    verify_detection_failure_identity,
    verify_gap_identity,
    verify_survivor_report_identity,
    verify_vacuity_finding_identity,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _generator(**overrides: object) -> GeneratorIdentity:
    fields = {
        "generator_id": "gap_diagnosis",
        "generator_version": "1.0.0",
        "interface_id": "diagnose_assurance_gap@1",
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


def _header(artifact_kind: str, **overrides: object) -> AssuranceArtifactHeader:
    fields = {
        "artifact_kind": artifact_kind,
        "repository_id": "repository:sha256:test-repo-identity",
        "repository_state_cid": _cid("repo-state"),
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
        "metadata": {"risk_class": "authorization"},
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


def _survivor(**overrides: object) -> SurvivingMutantReport:
    fields = {
        "header": _header("surviving_mutant_report"),
        "report_id": "survivor_1",
        "candidate_id": "cand_control_flow_invert_0",
        "candidate_cid": _cid("candidate"),
        "outcome_cid": _cid("outcome"),
        "risk_class": SurvivorRiskClass.AUTHORIZATION,
        "symbol_ids": ("mod.fn",),
        "violated_or_missing_property": "authorization check must remain present",
        "detectors_run": ("unit.test_branch",),
        "detectors_omitted": ("static.authz_rule",),
        "expected_behavior": "reject unauthorized caller",
        "observed_behavior": "unauthorized caller accepted",
        "source_spans": (_span(),),
        "dependency_path": ("mod.fn", "authz.check"),
        "reproduction_command": "pytest -q tests/test_authz.py::test_reject",
        "minimized_evidence": _evidence(),
        "proof_cids": (_cid("proof-a"),),
        "receipt_cids": (_cid("receipt-a"),),
        "equivalence_assessment_cid": None,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return SurvivingMutantReport(**fields)  # type: ignore[arg-type]


def _gap(**overrides: object) -> AssuranceGap:
    survivor = _survivor()
    fields = {
        "header": _header("assurance_gap"),
        "gap_id": "gap_1",
        "gap_class": AssuranceGapClass.MISSING_TEST,
        "severity": GapSeverity.HIGH,
        "risk_class": SurvivorRiskClass.AUTHORIZATION,
        "summary": "missing test for inverted authorization guard",
        "candidate_id": "cand_control_flow_invert_0",
        "candidate_cid": _cid("candidate"),
        "survivor_report_cid": survivor.report_cid,
        "violated_or_missing_property": "authorization check must remain present",
        "symbol_ids": ("mod.fn",),
        "source_spans": (_span(),),
        "dependency_path": ("mod.fn", "authz.check"),
        "minimized_evidence": _evidence(),
        "requires_human_review": False,
        "detection_failure_cids": (),
        "vacuity_finding_cids": (),
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return AssuranceGap(**fields)  # type: ignore[arg-type]


def _vacuity(**overrides: object) -> VacuityFinding:
    fields = {
        "header": _header("vacuity_finding"),
        "finding_id": "vacuity_1",
        "vacuity_family": VacuityFamily.TEST,
        "vacuity_kind": VacuityKind.TAUTOLOGY,
        "subject_id": "unit.test_always_true",
        "subject_cid": _cid("test-subject"),
        "vacuous_claim": "test proves branch invariant",
        "what_remains_proven": "test suite completes without raising",
        "what_is_not_proven": "branch predicate preserves authorization invariant",
        "symbol_ids": ("mod.fn",),
        "source_spans": (_span(),),
        "dependency_path": ("mod.fn", "unit.test_always_true"),
        "minimized_evidence": _evidence(),
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return VacuityFinding(**fields)  # type: ignore[arg-type]


def _detection_failure(**overrides: object) -> DetectionFailure:
    fields = {
        "header": _header("detection_failure"),
        "failure_id": "detfail_1",
        "failure_kind": DetectionFailureKind.OBSERVATION_MISS,
        "candidate_id": "cand_control_flow_invert_0",
        "candidate_cid": _cid("candidate"),
        "detector_id": "unit.test_branch",
        "predicted": True,
        "selected": True,
        "executed": True,
        "observed": False,
        "summary": "predicted unit test executed but did not observe the mutant",
        "dependency_path": ("mod.fn", "unit.test_branch"),
        "minimized_evidence": _evidence(),
        "expected_detection_set_cid": _cid("eds"),
        "outcome_cid": _cid("outcome"),
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return DetectionFailure(**fields)  # type: ignore[arg-type]


def _test_profile(**overrides: object) -> TestAdequacyProfile:
    fields = {
        "header": _header("test_adequacy_profile"),
        "profile_id": "test_adeq_1",
        "target_symbol_ids": ("mod.fn",),
        "verdict": AdequacyVerdict.INADEQUATE,
        "gap_classes": (TestAdequacyGapClass.WEAK_ASSERTION,),
        "covered_detector_ids": ("unit.smoke",),
        "missing_detector_ids": ("unit.authz",),
        "minimized_evidence": _evidence(),
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return TestAdequacyProfile(**fields)  # type: ignore[arg-type]


def _proof_profile(**overrides: object) -> ProofAdequacyProfile:
    fields = {
        "header": _header("proof_adequacy_profile"),
        "profile_id": "proof_adeq_1",
        "target_symbol_ids": ("mod.fn",),
        "verdict": AdequacyVerdict.PARTIAL,
        "gap_classes": (ProofAdequacyGapClass.MISSING_OBLIGATION,),
        "proof_unit_cids": (_cid("proof-unit-a"),),
        "missing_obligation_ids": ("authz.preserves_tenant",),
        "minimized_evidence": _evidence(),
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return ProofAdequacyProfile(**fields)  # type: ignore[arg-type]


def _policy_profile(**overrides: object) -> PolicyAdequacyProfile:
    fields = {
        "header": _header("policy_adequacy_profile"),
        "profile_id": "policy_adeq_1",
        "target_symbol_ids": ("mod.fn",),
        "verdict": AdequacyVerdict.INADEQUATE,
        "gap_classes": (PolicyAdequacyGapClass.MISSING_CONSTRAINT,),
        "policy_cids": (_cid("policy"),),
        "missing_constraint_ids": ("deny_default",),
        "minimized_evidence": _evidence(),
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return PolicyAdequacyProfile(**fields)  # type: ignore[arg-type]


def _capsule_profile(**overrides: object) -> CapsuleAdequacyProfile:
    fields = {
        "header": _header("capsule_adequacy_profile"),
        "profile_id": "capsule_adeq_1",
        "target_symbol_ids": ("mod.fn",),
        "verdict": AdequacyVerdict.PARTIAL,
        "gap_classes": (CapsuleAdequacyGapClass.OMITTED_DEPENDENCY,),
        "capsule_cids": (_cid("capsule-a"),),
        "omitted_edge_ids": ("edge.config",),
        "minimized_evidence": _evidence(),
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return CapsuleAdequacyProfile(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Closed vocabularies — acceptance: taxonomies are closed
# ---------------------------------------------------------------------------


def test_assurance_gap_taxonomy_matches_plan_closed_set() -> None:
    expected = (
        "missing_test",
        "weak_assertion",
        "missing_proof_obligation",
        "vacuous_proof",
        "missing_policy_constraint",
        "stale_or_incomplete_dependency_edge",
        "capsule_completeness_failure",
        "test_selection_failure",
        "unmodeled_side_effect",
        "missing_state_transition_constraint",
        "missing_environment_binding",
        "receipt_authenticity_gap",
        "specification_ambiguity",
        "intentionally_unconstrained",
        "probably_equivalent",
        "unknown",
    )
    assert assurance_gap_classes() == expected
    with pytest.raises(ValueError):
        AssuranceGapClass("maybe_missing_test")
    with pytest.raises(AnalysisContractError, match="unsupported value"):
        _gap(gap_class="invented_gap")


def test_adequacy_taxonomies_are_closed() -> None:
    assert adequacy_verdicts() == (
        "adequate",
        "inadequate",
        "partial",
        "unknown",
        "inconclusive",
    )
    assert "weak_assertion" in test_adequacy_gap_classes()
    assert "none" in test_adequacy_gap_classes()
    assert "vacuous_proof" in proof_adequacy_gap_classes()
    assert "missing_constraint" in policy_adequacy_gap_classes()
    assert "omitted_dependency" in capsule_adequacy_gap_classes()
    assert "heuristic_as_exact" in capsule_adequacy_gap_classes()
    with pytest.raises(ValueError):
        TestAdequacyGapClass("maybe_ok")
    with pytest.raises(ValueError):
        AdequacyVerdict("good_enough")
    with pytest.raises(AnalysisContractError, match="unsupported value"):
        _test_profile(gap_classes=("invented",))


def test_vacuity_and_detection_vocabularies_are_closed() -> None:
    assert vacuity_families() == (
        "formal_proof",
        "policy",
        "test",
        "zk_receipt",
    )
    assert VacuityKind.TAUTOLOGY.value in vacuity_kinds()
    assert VacuityKind.UNSATISFIABLE_ANTECEDENT.value in vacuity_kinds()
    assert VacuityKind.CALLER_SELECTED_VERIFICATION_KEY.value in vacuity_kinds()
    formal = vacuity_kinds_for_family(VacuityFamily.FORMAL_PROOF)
    assert "unsatisfiable_antecedent" in formal
    assert "tautology" not in formal
    assert DetectionFailureKind.OBSERVATION_MISS.value in detection_failure_kinds()
    assert gap_severities() == (
        "critical",
        "high",
        "medium",
        "low",
        "informational",
    )
    assert SurvivorRiskClass.CRITICAL_SECURITY.value in survivor_risk_classes()
    with pytest.raises(ValueError):
        VacuityFamily("runtime_guess")
    with pytest.raises(ValueError):
        DetectionFailureKind("detector_maybe")


# ---------------------------------------------------------------------------
# Minimized evidence binding
# ---------------------------------------------------------------------------


def test_minimized_evidence_requires_cids_or_explicit_failure() -> None:
    evidence = _evidence()
    restored = MinimizedEvidenceBinding.from_dict(evidence.to_dict())
    assert restored.binding_cid == evidence.binding_cid
    assert restored.minimized is True

    failed = MinimizedEvidenceBinding(
        evidence_cids=(),
        minimized=False,
        minimization_failed=True,
        notes="counterexample minimizer exhausted budget",
    )
    assert failed.minimization_failed is True

    with pytest.raises(AnalysisContractError, match="must not be empty"):
        MinimizedEvidenceBinding(
            evidence_cids=(),
            minimized=True,
            minimization_failed=False,
        )
    with pytest.raises(AnalysisContractError, match="minimization_failed"):
        MinimizedEvidenceBinding(
            evidence_cids=(_cid("x"),),
            minimized=True,
            minimization_failed=True,
        )
    with pytest.raises(AnalysisContractError, match="minimization_failed"):
        MinimizedEvidenceBinding(
            evidence_cids=(_cid("x"),),
            minimized=False,
            minimization_failed=False,
        )


# ---------------------------------------------------------------------------
# SurvivingMutantReport — binds minimized evidence
# ---------------------------------------------------------------------------


def test_survivor_report_round_trip_binds_minimized_evidence() -> None:
    report = _survivor()
    restored = SurvivingMutantReport.from_dict(report.to_dict())
    assert restored.report_cid == report.report_cid
    assert restored.minimized_evidence.minimized is True
    assert restored.minimized_evidence.evidence_cids
    assert restored.detectors_run == ("unit.test_branch",)
    assert restored.detectors_omitted == ("static.authz_rule",)
    assert restored.source_spans[0].path == "src/mod.py"
    assert verify_survivor_report_identity(report) == report.report_cid

    with pytest.raises(AnalysisContractError, match="surviving_mutant_report"):
        _survivor(header=_header("assurance_gap"))
    with pytest.raises(AnalysisContractError, match="disjoint"):
        _survivor(
            detectors_run=("unit.test_branch",),
            detectors_omitted=("unit.test_branch",),
        )
    with pytest.raises(AnalysisContractError, match="source_spans"):
        _survivor(source_spans=())
    with pytest.raises(AnalysisContractError, match="symbol_ids"):
        _survivor(symbol_ids=())
    with pytest.raises(AnalysisContractError, match="dependency_path"):
        _survivor(dependency_path=())


def test_survivor_report_rejects_absolute_and_parent_paths() -> None:
    with pytest.raises(AnalysisContractError, match="absolute"):
        _span(path="/etc/passwd")
    with pytest.raises(AnalysisContractError, match="parent-directory"):
        _span(path="../escape.py")
    with pytest.raises(AnalysisContractError, match="end_line"):
        _span(start_line=20, end_line=5)


def test_survivor_report_forged_cid_fails_closed() -> None:
    report = _survivor()
    payload = report.to_dict()
    payload["report_cid"] = _cid("forged")
    with pytest.raises(AnalysisContractError, match="identity mismatch"):
        SurvivingMutantReport.from_dict(payload)


# ---------------------------------------------------------------------------
# AssuranceGap
# ---------------------------------------------------------------------------


def test_assurance_gap_round_trip_and_unknown_requires_review() -> None:
    gap = _gap()
    restored = AssuranceGap.from_dict(gap.to_dict())
    assert restored.gap_cid == gap.gap_cid
    assert restored.gap_class == AssuranceGapClass.MISSING_TEST.value
    assert restored.minimized_evidence.minimized is True
    assert verify_gap_identity(gap) == gap.gap_cid

    unknown = _gap(
        gap_class=AssuranceGapClass.UNKNOWN,
        requires_human_review=True,
        summary="unclassified high-risk survivor",
    )
    assert unknown.requires_human_review is True

    with pytest.raises(AnalysisContractError, match="requires_human_review"):
        _gap(gap_class=AssuranceGapClass.UNKNOWN, requires_human_review=False)
    with pytest.raises(AnalysisContractError, match="both be set"):
        _gap(candidate_id="cand_x", candidate_cid=None)
    with pytest.raises(AnalysisContractError, match="assurance_gap"):
        _gap(header=_header("surviving_mutant_report"))


def test_all_plan_gap_classes_constructible() -> None:
    for gap_class in AssuranceGapClass:
        requires_review = gap_class == AssuranceGapClass.UNKNOWN
        gap = _gap(
            gap_id=f"gap_{gap_class.value}",
            gap_class=gap_class,
            requires_human_review=requires_review,
            summary=f"gap {gap_class.value}",
        )
        assert gap.gap_class == gap_class.value


# ---------------------------------------------------------------------------
# VacuityFinding — every record states what remains proven
# ---------------------------------------------------------------------------


def test_vacuity_finding_states_what_remains_proven() -> None:
    finding = _vacuity()
    assert finding.what_remains_proven
    assert finding.what_is_not_proven
    assert finding.what_remains_proven != finding.what_is_not_proven
    restored = VacuityFinding.from_dict(finding.to_dict())
    assert restored.finding_cid == finding.finding_cid
    assert restored.what_remains_proven == finding.what_remains_proven
    assert verify_vacuity_finding_identity(finding) == finding.finding_cid

    with pytest.raises(AnalysisContractError, match="nonempty string"):
        _vacuity(what_remains_proven="")
    with pytest.raises(AnalysisContractError, match="differ"):
        _vacuity(
            what_remains_proven="same claim",
            what_is_not_proven="same claim",
        )
    with pytest.raises(AnalysisContractError, match="not admitted"):
        _vacuity(
            vacuity_family=VacuityFamily.FORMAL_PROOF,
            vacuity_kind=VacuityKind.TAUTOLOGY,
        )


def test_vacuity_family_kind_matrix() -> None:
    cases = (
        (VacuityFamily.FORMAL_PROOF, VacuityKind.UNSATISFIABLE_ANTECEDENT),
        (VacuityFamily.POLICY, VacuityKind.SHADOWED_PROHIBITION),
        (VacuityFamily.TEST, VacuityKind.SUCCESS_BEFORE_EFFECT_OBSERVATION),
        (VacuityFamily.ZK_RECEIPT, VacuityKind.INCLUSION_WITHOUT_COMPLETENESS),
    )
    for family, kind in cases:
        finding = _vacuity(
            finding_id=f"vac_{kind.value}",
            vacuity_family=family,
            vacuity_kind=kind,
            subject_id=f"subj_{kind.value}",
            what_remains_proven=f"remains under {kind.value}",
            what_is_not_proven=f"not proven under {kind.value}",
        )
        assert finding.vacuity_family == family.value
        assert finding.vacuity_kind == kind.value
        assert finding.what_remains_proven.startswith("remains")


# ---------------------------------------------------------------------------
# DetectionFailure
# ---------------------------------------------------------------------------


def test_detection_failure_role_invariants() -> None:
    failure = _detection_failure()
    restored = DetectionFailure.from_dict(failure.to_dict())
    assert restored.failure_cid == failure.failure_cid
    assert verify_detection_failure_identity(failure) == failure.failure_cid

    selection = _detection_failure(
        failure_id="sel_miss",
        failure_kind=DetectionFailureKind.SELECTION_MISS,
        predicted=True,
        selected=False,
        executed=False,
        observed=False,
        summary="predicted detector not selected",
    )
    assert selection.failure_kind == DetectionFailureKind.SELECTION_MISS.value

    unexpected = _detection_failure(
        failure_id="unexp",
        failure_kind=DetectionFailureKind.UNEXPECTED_OBSERVED,
        predicted=False,
        selected=True,
        executed=True,
        observed=True,
        summary="unpredicted detector observed the mutant",
    )
    assert unexpected.observed is True

    with pytest.raises(AnalysisContractError, match="executed detectors"):
        _detection_failure(selected=False, executed=True, observed=False)
    with pytest.raises(AnalysisContractError, match="observation_miss"):
        _detection_failure(observed=True)
    with pytest.raises(AnalysisContractError, match="selection_miss"):
        _detection_failure(
            failure_kind=DetectionFailureKind.SELECTION_MISS,
            predicted=True,
            selected=True,
            executed=False,
            observed=False,
        )
    with pytest.raises(AnalysisContractError, match="detection_failure"):
        _detection_failure(header=_header("assurance_gap"))


# ---------------------------------------------------------------------------
# Adequacy profiles
# ---------------------------------------------------------------------------


def test_test_adequacy_profile_verdict_gap_consistency() -> None:
    profile = _test_profile()
    restored = TestAdequacyProfile.from_dict(profile.to_dict())
    assert restored.profile_cid == profile.profile_cid
    assert restored.verdict == AdequacyVerdict.INADEQUATE.value

    adequate = _test_profile(
        profile_id="test_ok",
        verdict=AdequacyVerdict.ADEQUATE,
        gap_classes=(TestAdequacyGapClass.NONE,),
        missing_detector_ids=(),
    )
    assert adequate.gap_classes == ("none",)

    with pytest.raises(AnalysisContractError, match="exactly \\['none'\\]"):
        _test_profile(
            verdict=AdequacyVerdict.ADEQUATE,
            gap_classes=(TestAdequacyGapClass.WEAK_ASSERTION,),
        )
    with pytest.raises(AnalysisContractError, match="non-none"):
        _test_profile(
            verdict=AdequacyVerdict.INADEQUATE,
            gap_classes=(TestAdequacyGapClass.NONE,),
        )
    with pytest.raises(AnalysisContractError, match="cannot combine"):
        _test_profile(
            gap_classes=(
                TestAdequacyGapClass.NONE,
                TestAdequacyGapClass.WEAK_ASSERTION,
            ),
        )
    with pytest.raises(AnalysisContractError, match="disjoint"):
        _test_profile(
            covered_detector_ids=("unit.smoke",),
            missing_detector_ids=("unit.smoke",),
        )


def test_proof_policy_capsule_adequacy_profiles_round_trip() -> None:
    proof = _proof_profile()
    policy = _policy_profile()
    capsule = _capsule_profile()
    assert ProofAdequacyProfile.from_dict(proof.to_dict()).profile_cid == (
        proof.profile_cid
    )
    assert PolicyAdequacyProfile.from_dict(policy.to_dict()).profile_cid == (
        policy.profile_cid
    )
    assert CapsuleAdequacyProfile.from_dict(capsule.to_dict()).profile_cid == (
        capsule.profile_cid
    )
    assert all(
        profile.minimized_evidence.minimized
        for profile in (proof, policy, capsule)
    )

    with pytest.raises(AnalysisContractError, match="proof_adequacy_profile"):
        _proof_profile(header=_header("test_adequacy_profile"))
    with pytest.raises(AnalysisContractError, match="policy_adequacy_profile"):
        _policy_profile(header=_header("test_adequacy_profile"))
    with pytest.raises(AnalysisContractError, match="capsule_adequacy_profile"):
        _capsule_profile(header=_header("test_adequacy_profile"))


def test_adequate_profiles_across_surfaces() -> None:
    for builder, none_class, kind in (
        (_test_profile, TestAdequacyGapClass.NONE, "test"),
        (_proof_profile, ProofAdequacyGapClass.NONE, "proof"),
        (_policy_profile, PolicyAdequacyGapClass.NONE, "policy"),
        (_capsule_profile, CapsuleAdequacyGapClass.NONE, "capsule"),
    ):
        profile = builder(
            profile_id=f"{kind}_ok",
            verdict=AdequacyVerdict.ADEQUATE,
            gap_classes=(none_class,),
            **(
                {"missing_detector_ids": ()}
                if kind == "test"
                else (
                    {"missing_obligation_ids": ()}
                    if kind == "proof"
                    else (
                        {"missing_constraint_ids": ()}
                        if kind == "policy"
                        else {"omitted_edge_ids": ()}
                    )
                )
            ),
        )
        assert profile.verdict == AdequacyVerdict.ADEQUATE.value
        assert list(profile.gap_classes) == ["none"]


# ---------------------------------------------------------------------------
# Fail-closed private / model authority / host fallbacks
# ---------------------------------------------------------------------------


def test_rejects_private_and_model_authority_metadata() -> None:
    with pytest.raises(AnalysisContractError, match="private"):
        _survivor(metadata={"api_key": "secret"})
    with pytest.raises(AnalysisContractError, match="model-written authority"):
        _gap(metadata={"model_authority": True})
    with pytest.raises(AnalysisContractError, match="host fallback"):
        _vacuity(metadata={"host_env": "prod"})


def test_closed_fields_reject_unknown_keys() -> None:
    report = _survivor()
    payload = report.to_dict()
    payload["extra_field"] = "nope"
    with pytest.raises(AnalysisContractError, match="fields must be exactly"):
        SurvivingMutantReport.from_dict(payload)

    gap_payload = _gap().to_dict()
    gap_payload["extra"] = 1
    with pytest.raises(AnalysisContractError, match="fields must be exactly"):
        AssuranceGap.from_dict(gap_payload)
