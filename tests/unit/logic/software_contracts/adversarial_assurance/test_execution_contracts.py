"""Contract vectors for expected-detection, execution, receipt, outcome, and equivalence models (AAE-009)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.common import (
    ArtifactProvenance,
    AssuranceArtifactHeader,
    AssuranceTerminalStatus,
    AuthoritySource,
    ExecutionMode,
    GeneratorIdentity,
    VersionBinding,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.execution_contracts import (
    CostMeasurement,
    DetectorClassification,
    DetectorKind,
    DetectorPrediction,
    DetectorRole,
    DetectorStrength,
    EquivalenceAssessmentStatus,
    EquivalenceMethod,
    ExecutionContractError,
    ExpectedDetectionSet,
    MutationEquivalenceAssessment,
    MutationExecutionPlan,
    MutationExecutionReceipt,
    MutationOutcome,
    MutationOutcomeStatus,
    assert_outcome_never_false_kill,
    counts_as_killed,
    detector_kinds,
    detector_roles,
    detector_strengths,
    equivalence_assessment_statuses,
    equivalence_methods,
    killed_outcome_statuses,
    mutation_outcome_statuses,
    never_counted_as_killed_statuses,
    verify_detection_set_identity,
    verify_outcome_identity,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _generator(**overrides: object) -> GeneratorIdentity:
    fields = {
        "generator_id": "mutation_campaign",
        "generator_version": "1.0.0",
        "interface_id": "execute_mutation@1",
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
        "tool_ids": ("executor.v1",),
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
        "metadata": {"risk_class": "local_bug"},
    }
    fields.update(overrides)
    return AssuranceArtifactHeader(**fields)  # type: ignore[arg-type]


def _prediction(**overrides: object) -> DetectorPrediction:
    fields = {
        "detector_id": "unit.test_branch",
        "detector_kind": DetectorKind.UNIT_TEST,
        "violated_claim": "branch predicate must preserve control invariant",
        "observation_rationale": "test asserts inverted branch is rejected",
        "dependency_path": ("mod.fn", "tests.test_branch"),
        "strength": DetectorStrength.REQUIRED,
        "expected_terminal_status": AssuranceTerminalStatus.COMPLETE,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return DetectorPrediction(**fields)  # type: ignore[arg-type]


def _static_prediction(**overrides: object) -> DetectorPrediction:
    fields = {
        "detector_id": "static.authz_rule",
        "detector_kind": DetectorKind.STATIC_RULE,
        "violated_claim": "authorization check must remain present",
        "observation_rationale": "static rule flags removed guard",
        "dependency_path": ("mod.fn", "static.authz"),
        "strength": DetectorStrength.REQUIRED,
        "expected_terminal_status": AssuranceTerminalStatus.COMPLETE,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return DetectorPrediction(**fields)  # type: ignore[arg-type]


def _detection_set(**overrides: object) -> ExpectedDetectionSet:
    fields = {
        "header": _header("expected_detection_set"),
        "detection_set_id": "eds_cand_1",
        "candidate_id": "cand_control_flow_invert_0",
        "candidate_cid": _cid("candidate"),
        "predicted_detectors": (_prediction(), _static_prediction()),
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return ExpectedDetectionSet(**fields)  # type: ignore[arg-type]


def _classification(**overrides: object) -> DetectorClassification:
    fields = {
        "predicted_detector_ids": ("static.authz_rule", "unit.test_branch"),
        "selected_detector_ids": ("static.authz_rule", "unit.test_branch"),
        "executed_detector_ids": ("static.authz_rule", "unit.test_branch"),
        "observed_detector_ids": ("unit.test_branch",),
    }
    fields.update(overrides)
    return DetectorClassification(**fields)  # type: ignore[arg-type]


def _cost(**overrides: object) -> CostMeasurement:
    fields = {
        "incremental_cost_units": 12,
        "full_suite_counterfactual_cost_units": 400,
        "execution_seconds": 3,
        "notes": None,
    }
    fields.update(overrides)
    return CostMeasurement(**fields)  # type: ignore[arg-type]


def _execution_plan(**overrides: object) -> MutationExecutionPlan:
    eds = _detection_set()
    fields = {
        "header": _header("mutation_execution_plan"),
        "execution_plan_id": "exec_plan_1",
        "candidate_id": "cand_control_flow_invert_0",
        "candidate_cid": _cid("candidate"),
        "expected_detection_set_cid": eds.detection_set_cid,
        "selected_detector_ids": eds.predicted_detector_ids,
        "predicted_detector_ids": eds.predicted_detector_ids,
        "require_disposable_worktree": True,
        "require_network_disabled": True,
        "full_suite_fallback_enabled": False,
        "timeout_seconds": 600,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return MutationExecutionPlan(**fields)  # type: ignore[arg-type]


def _receipt(**overrides: object) -> MutationExecutionReceipt:
    plan = _execution_plan()
    fields = {
        "header": _header("mutation_execution_receipt"),
        "receipt_id": "receipt_exec_1",
        "candidate_id": "cand_control_flow_invert_0",
        "candidate_cid": _cid("candidate"),
        "execution_plan_cid": plan.execution_plan_cid,
        "expected_detection_set_cid": plan.expected_detection_set_cid,
        "detector_classification": _classification(),
        "cost": _cost(),
        "mutant_identity_cid": _cid("mutant-identity"),
        "infrastructure_ok": True,
        "timed_out": False,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return MutationExecutionReceipt(**fields)  # type: ignore[arg-type]


def _outcome(**overrides: object) -> MutationOutcome:
    receipt = _receipt()
    fields = {
        "header": _header("mutation_outcome"),
        "outcome_id": "outcome_1",
        "candidate_id": "cand_control_flow_invert_0",
        "candidate_cid": _cid("candidate"),
        "receipt_cid": receipt.receipt_cid,
        "expected_detection_set_cid": receipt.expected_detection_set_cid,
        "outcome_status": MutationOutcomeStatus.KILLED_BY_TEST,
        "detector_classification": _classification(),
        "killing_detector_id": "unit.test_branch",
        "killing_detector_kind": DetectorKind.UNIT_TEST,
        "equivalence_assessment_cid": None,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return MutationOutcome(**fields)  # type: ignore[arg-type]


def _equivalence(**overrides: object) -> MutationEquivalenceAssessment:
    fields = {
        "header": _header("mutation_equivalence_assessment"),
        "assessment_id": "eq_1",
        "candidate_id": "cand_control_flow_invert_0",
        "candidate_cid": _cid("candidate"),
        "assessment_status": EquivalenceAssessmentStatus.NOT_EQUIVALENT,
        "methods": (
            EquivalenceMethod.AST_COMPARISON,
            EquivalenceMethod.BOUNDED_PUBLIC_BEHAVIOR,
        ),
        "evidence_cids": (_cid("eq-evidence"),),
        "difficulty_to_kill_not_evidence": True,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return MutationEquivalenceAssessment(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------


def test_outcome_statuses_match_plan_closed_set() -> None:
    expected = (
        "killed_by_static_analysis",
        "killed_by_type_check",
        "killed_by_test",
        "killed_by_formal_proof",
        "killed_by_policy",
        "killed_by_runtime_invariant",
        "killed_by_full_suite",
        "survived_selected_verification",
        "survived_full_verification",
        "equivalent",
        "probably_equivalent",
        "invalid_mutant",
        "uncompilable",
        "infrastructure_failure",
        "timeout",
        "inconclusive",
        "human_review_required",
    )
    assert mutation_outcome_statuses() == expected
    with pytest.raises(ValueError):
        MutationOutcomeStatus("maybe_killed")


def test_detector_and_equivalence_vocabularies_are_closed() -> None:
    kinds = detector_kinds()
    assert "static_rule" in kinds
    assert "type_check" in kinds
    assert "unit_test" in kinds
    assert "integration_test" in kinds
    assert "property_test" in kinds
    assert "formal_obligation" in kinds
    assert "policy_rule" in kinds
    assert "runtime_invariant" in kinds
    assert "full_suite" in kinds
    assert "incremental_seal" in kinds
    assert "human_review" in kinds
    assert detector_roles() == (
        "predicted",
        "selected",
        "executed",
        "observed",
        "missed",
        "unexpected",
    )
    assert detector_strengths() == ("required", "optional")
    assert equivalence_assessment_statuses() == (
        "equivalent",
        "probably_equivalent",
        "not_equivalent",
        "unknown",
    )
    assert EquivalenceMethod.AST_COMPARISON.value in equivalence_methods()
    with pytest.raises(ValueError):
        DetectorKind("model_guess")
    with pytest.raises(ValueError):
        EquivalenceAssessmentStatus("likely_same")


# ---------------------------------------------------------------------------
# Kill counting — acceptance core
# ---------------------------------------------------------------------------


def test_counts_as_killed_only_for_genuine_kill_statuses() -> None:
    for status in killed_outcome_statuses():
        assert counts_as_killed(status) is True
    never = never_counted_as_killed_statuses()
    for status in (
        "invalid_mutant",
        "uncompilable",
        "infrastructure_failure",
        "timeout",
        "inconclusive",
        "equivalent",
        "probably_equivalent",
    ):
        assert status in never
        assert counts_as_killed(status) is False
    assert counts_as_killed("survived_selected_verification") is False
    assert counts_as_killed("survived_full_verification") is False
    assert counts_as_killed("human_review_required") is False
    with pytest.raises(ExecutionContractError, match="unsupported value"):
        counts_as_killed("almost_killed")


def test_killed_outcome_counts_and_requires_killing_detector() -> None:
    outcome = _outcome()
    assert outcome.counts_as_killed is True
    assert outcome.outcome_status == MutationOutcomeStatus.KILLED_BY_TEST.value
    assert_outcome_never_false_kill(outcome)
    assert verify_outcome_identity(outcome) == outcome.outcome_cid

    with pytest.raises(ExecutionContractError, match="killing_detector_id"):
        _outcome(killing_detector_id=None)
    with pytest.raises(ExecutionContractError, match="observed_detector_ids"):
        _outcome(killing_detector_id="static.authz_rule")
    with pytest.raises(ExecutionContractError, match="inconsistent"):
        _outcome(killing_detector_kind=DetectorKind.STATIC_RULE)


def test_non_kill_statuses_never_count_as_killed() -> None:
    classification = _classification(
        observed_detector_ids=(),
        executed_detector_ids=("unit.test_branch",),
        selected_detector_ids=("unit.test_branch",),
        predicted_detector_ids=("unit.test_branch",),
    )
    cases = (
        MutationOutcomeStatus.INVALID_MUTANT,
        MutationOutcomeStatus.UNCOMPILABLE,
        MutationOutcomeStatus.INFRASTRUCTURE_FAILURE,
        MutationOutcomeStatus.TIMEOUT,
        MutationOutcomeStatus.INCONCLUSIVE,
        MutationOutcomeStatus.SURVIVED_SELECTED_VERIFICATION,
        MutationOutcomeStatus.SURVIVED_FULL_VERIFICATION,
        MutationOutcomeStatus.HUMAN_REVIEW_REQUIRED,
    )
    for status in cases:
        outcome = _outcome(
            outcome_status=status,
            detector_classification=classification,
            killing_detector_id=None,
            killing_detector_kind=None,
        )
        assert outcome.counts_as_killed is False
        assert_outcome_never_false_kill(outcome)

    eq = _equivalence(assessment_status=EquivalenceAssessmentStatus.EQUIVALENT)
    for status in (
        MutationOutcomeStatus.EQUIVALENT,
        MutationOutcomeStatus.PROBABLY_EQUIVALENT,
    ):
        outcome = _outcome(
            outcome_status=status,
            detector_classification=classification,
            killing_detector_id=None,
            killing_detector_kind=None,
            equivalence_assessment_cid=eq.assessment_cid,
        )
        assert outcome.counts_as_killed is False

    with pytest.raises(ExecutionContractError, match="must not set killing"):
        _outcome(
            outcome_status=MutationOutcomeStatus.TIMEOUT,
            detector_classification=classification,
            killing_detector_id="unit.test_branch",
            killing_detector_kind=DetectorKind.UNIT_TEST,
        )


def test_forged_counts_as_killed_on_round_trip_fails_closed() -> None:
    classification = _classification(
        observed_detector_ids=(),
        executed_detector_ids=(),
        selected_detector_ids=("unit.test_branch",),
        predicted_detector_ids=("unit.test_branch",),
    )
    outcome = _outcome(
        outcome_status=MutationOutcomeStatus.INVALID_MUTANT,
        detector_classification=classification,
        killing_detector_id=None,
        killing_detector_kind=None,
    )
    payload = outcome.to_dict()
    assert payload["counts_as_killed"] is False
    payload["counts_as_killed"] = True
    # Identity will also mismatch, but the explicit kill rule is what we assert.
    with pytest.raises(
        ExecutionContractError,
        match="counts_as_killed must match|never count as killed|identity mismatch",
    ):
        MutationOutcome.from_dict(payload)


# ---------------------------------------------------------------------------
# Detector prediction and expected detection set
# ---------------------------------------------------------------------------


def test_detector_prediction_requires_claim_rationale_dependency_strength() -> None:
    prediction = _prediction()
    restored = DetectorPrediction.from_dict(prediction.to_dict())
    assert restored == prediction
    assert restored.prediction_cid == prediction.prediction_cid
    with pytest.raises(ExecutionContractError, match="dependency_path"):
        _prediction(dependency_path=())
    with pytest.raises(ExecutionContractError, match="unsupported value"):
        _prediction(detector_kind="magic")
    with pytest.raises(ExecutionContractError, match="unsupported value"):
        _prediction(strength="maybe")
    with pytest.raises(ExecutionContractError, match="nonempty string"):
        _prediction(violated_claim="")


def test_expected_detection_set_round_trip_and_kinds() -> None:
    eds = _detection_set()
    restored = ExpectedDetectionSet.from_dict(eds.to_dict())
    assert restored.detection_set_cid == eds.detection_set_cid
    assert set(restored.predicted_detector_ids) == {
        "static.authz_rule",
        "unit.test_branch",
    }
    assert restored.detector_by_id("unit.test_branch").detector_kind == (
        DetectorKind.UNIT_TEST.value
    )
    assert verify_detection_set_identity(eds) == eds.detection_set_cid
    with pytest.raises(ExecutionContractError, match="expected_detection_set"):
        _detection_set(header=_header("mutation_outcome"))
    with pytest.raises(ExecutionContractError, match="must not be empty"):
        _detection_set(predicted_detectors=())
    with pytest.raises(ExecutionContractError, match="unique"):
        _detection_set(predicted_detectors=(_prediction(), _prediction()))


def test_expected_detection_set_accepts_all_plan_detector_kinds() -> None:
    detectors = []
    for kind in DetectorKind:
        detectors.append(
            _prediction(
                detector_id=f"det.{kind.value}",
                detector_kind=kind,
                dependency_path=(f"path.{kind.value}",),
            )
        )
    eds = _detection_set(predicted_detectors=detectors)
    assert len(eds.predicted_detectors) == len(DetectorKind)


# ---------------------------------------------------------------------------
# Detector classification roles
# ---------------------------------------------------------------------------


def test_classification_separates_predicted_selected_executed_observed() -> None:
    classification = _classification()
    assert classification.predicted_detector_ids == (
        "static.authz_rule",
        "unit.test_branch",
    )
    assert classification.selected_detector_ids == (
        "static.authz_rule",
        "unit.test_branch",
    )
    assert classification.executed_detector_ids == (
        "static.authz_rule",
        "unit.test_branch",
    )
    assert classification.observed_detector_ids == ("unit.test_branch",)
    assert classification.missed_detector_ids == ("static.authz_rule",)
    assert classification.unexpected_detector_ids == ()
    assert DetectorRole.PREDICTED.value in classification.role_for("unit.test_branch")
    assert DetectorRole.OBSERVED.value in classification.role_for("unit.test_branch")
    assert DetectorRole.MISSED.value in classification.role_for("static.authz_rule")

    unexpected = DetectorClassification(
        predicted_detector_ids=("unit.test_branch",),
        selected_detector_ids=("unit.test_branch", "full_suite"),
        executed_detector_ids=("unit.test_branch", "full_suite"),
        observed_detector_ids=("full_suite",),
    )
    assert unexpected.unexpected_detector_ids == ("full_suite",)
    assert unexpected.missed_detector_ids == ("unit.test_branch",)

    restored = DetectorClassification.from_dict(classification.to_dict())
    assert restored.classification_cid == classification.classification_cid


def test_classification_enforces_role_nesting() -> None:
    with pytest.raises(ExecutionContractError, match="executed_detector_ids"):
        DetectorClassification(
            predicted_detector_ids=("a",),
            selected_detector_ids=("a",),
            executed_detector_ids=("b",),
            observed_detector_ids=(),
        )
    with pytest.raises(ExecutionContractError, match="observed_detector_ids"):
        DetectorClassification(
            predicted_detector_ids=("a",),
            selected_detector_ids=("a",),
            executed_detector_ids=("a",),
            observed_detector_ids=("b",),
        )
    payload = _classification().to_dict()
    payload["missed_detector_ids"] = ["unit.test_branch"]
    with pytest.raises(ExecutionContractError, match="missed_detector_ids"):
        DetectorClassification.from_dict(payload)


# ---------------------------------------------------------------------------
# Execution plan and receipt
# ---------------------------------------------------------------------------


def test_execution_plan_round_trip_and_safety_flags() -> None:
    plan = _execution_plan()
    restored = MutationExecutionPlan.from_dict(plan.to_dict())
    assert restored.execution_plan_cid == plan.execution_plan_cid
    assert restored.require_disposable_worktree is True
    assert restored.require_network_disabled is True
    with pytest.raises(ExecutionContractError, match="require_disposable_worktree"):
        _execution_plan(require_disposable_worktree=False)
    with pytest.raises(ExecutionContractError, match="require_network_disabled"):
        _execution_plan(require_network_disabled=False)
    with pytest.raises(ExecutionContractError, match="subset of predicted"):
        _execution_plan(
            selected_detector_ids=("full_suite",),
            full_suite_fallback_enabled=False,
        )
    expanded = _execution_plan(
        selected_detector_ids=("static.authz_rule", "unit.test_branch", "full_suite"),
        full_suite_fallback_enabled=True,
    )
    assert "full_suite" in expanded.selected_detector_ids
    with pytest.raises(ExecutionContractError, match="full-suite expansion"):
        _execution_plan(
            selected_detector_ids=("unit.test_branch", "rogue.detector"),
            full_suite_fallback_enabled=True,
        )
    with pytest.raises(ExecutionContractError, match="mutation_execution_plan"):
        _execution_plan(header=_header("mutation_outcome"))


def test_execution_receipt_exposes_detector_roles_and_cost() -> None:
    receipt = _receipt()
    restored = MutationExecutionReceipt.from_dict(receipt.to_dict())
    assert restored.receipt_cid == receipt.receipt_cid
    assert restored.predicted_detector_ids
    assert restored.selected_detector_ids
    assert restored.executed_detector_ids
    assert restored.observed_detector_ids == ("unit.test_branch",)
    assert restored.missed_detector_ids == ("static.authz_rule",)
    assert restored.cost.incremental_cost_units == 12
    assert restored.cost.full_suite_counterfactual_cost_units == 400
    with pytest.raises(ExecutionContractError, match="mutation_execution_receipt"):
        _receipt(header=_header("expected_detection_set"))
    with pytest.raises(ExecutionContractError, match="nonnegative integer"):
        _cost(incremental_cost_units=-1)


# ---------------------------------------------------------------------------
# Outcome and equivalence round-trips
# ---------------------------------------------------------------------------


def test_outcome_round_trip_and_header_kind() -> None:
    outcome = _outcome()
    restored = MutationOutcome.from_dict(outcome.to_dict())
    assert restored == outcome
    assert restored.counts_as_killed is True
    with pytest.raises(ExecutionContractError, match="mutation_outcome"):
        _outcome(header=_header("mutation_execution_receipt"))


def test_equivalence_assessment_round_trip_and_difficulty_rule() -> None:
    assessment = _equivalence()
    restored = MutationEquivalenceAssessment.from_dict(assessment.to_dict())
    assert restored.assessment_cid == assessment.assessment_cid
    assert restored.difficulty_to_kill_not_evidence is True
    with pytest.raises(ExecutionContractError, match="difficulty_to_kill"):
        _equivalence(difficulty_to_kill_not_evidence=False)
    with pytest.raises(ExecutionContractError, match="methods must not be empty"):
        _equivalence(methods=())
    with pytest.raises(ExecutionContractError, match="unsupported value"):
        _equivalence(assessment_status="looks_equal")
    with pytest.raises(
        ExecutionContractError, match="mutation_equivalence_assessment"
    ):
        _equivalence(header=_header("mutation_outcome"))


def test_equivalent_outcome_requires_assessment_cid() -> None:
    classification = _classification(
        observed_detector_ids=(),
        executed_detector_ids=("unit.test_branch",),
        selected_detector_ids=("unit.test_branch",),
        predicted_detector_ids=("unit.test_branch",),
    )
    with pytest.raises(ExecutionContractError, match="equivalence_assessment_cid"):
        _outcome(
            outcome_status=MutationOutcomeStatus.EQUIVALENT,
            detector_classification=classification,
            killing_detector_id=None,
            killing_detector_kind=None,
            equivalence_assessment_cid=None,
        )
    eq = _equivalence()
    outcome = _outcome(
        outcome_status=MutationOutcomeStatus.EQUIVALENT,
        detector_classification=classification,
        killing_detector_id=None,
        killing_detector_kind=None,
        equivalence_assessment_cid=eq.assessment_cid,
    )
    assert outcome.counts_as_killed is False


def test_all_kill_statuses_map_to_consistent_detector_kinds() -> None:
    kind_by_status = {
        MutationOutcomeStatus.KILLED_BY_STATIC_ANALYSIS: DetectorKind.STATIC_RULE,
        MutationOutcomeStatus.KILLED_BY_TYPE_CHECK: DetectorKind.TYPE_CHECK,
        MutationOutcomeStatus.KILLED_BY_TEST: DetectorKind.UNIT_TEST,
        MutationOutcomeStatus.KILLED_BY_FORMAL_PROOF: DetectorKind.FORMAL_OBLIGATION,
        MutationOutcomeStatus.KILLED_BY_POLICY: DetectorKind.POLICY_RULE,
        MutationOutcomeStatus.KILLED_BY_RUNTIME_INVARIANT: DetectorKind.RUNTIME_INVARIANT,
        MutationOutcomeStatus.KILLED_BY_FULL_SUITE: DetectorKind.FULL_SUITE,
    }
    for status, kind in kind_by_status.items():
        classification = DetectorClassification(
            predicted_detector_ids=("killer",),
            selected_detector_ids=("killer",),
            executed_detector_ids=("killer",),
            observed_detector_ids=("killer",),
        )
        outcome = _outcome(
            outcome_status=status,
            detector_classification=classification,
            killing_detector_id="killer",
            killing_detector_kind=kind,
        )
        assert outcome.counts_as_killed is True


# ---------------------------------------------------------------------------
# Fail-closed: identity, schema, private, floats
# ---------------------------------------------------------------------------


def test_unknown_fields_fail_closed_across_models() -> None:
    for factory in (
        lambda: _prediction().to_dict(),
        lambda: _detection_set().to_dict(),
        lambda: _execution_plan().to_dict(),
        lambda: _receipt().to_dict(),
        lambda: _outcome().to_dict(),
        lambda: _equivalence().to_dict(),
        lambda: _classification().to_dict(),
        lambda: _cost().to_dict(),
    ):
        payload = factory()
        payload["extra_field"] = "nope"
        with pytest.raises(ExecutionContractError, match="fields must be exactly"):
            if "detection_set_cid" in payload and "interface_id" in payload:
                ExpectedDetectionSet.from_dict(payload)
            elif "execution_plan_cid" in payload:
                MutationExecutionPlan.from_dict(payload)
            elif "receipt_cid" in payload and "mutant_identity_cid" in payload:
                MutationExecutionReceipt.from_dict(payload)
            elif "outcome_cid" in payload:
                MutationOutcome.from_dict(payload)
            elif "assessment_cid" in payload:
                MutationEquivalenceAssessment.from_dict(payload)
            elif "classification_cid" in payload:
                DetectorClassification.from_dict(payload)
            elif "cost_cid" in payload:
                CostMeasurement.from_dict(payload)
            else:
                DetectorPrediction.from_dict(payload)


def test_forged_identity_cids_fail_closed() -> None:
    eds = _detection_set()
    payload = eds.to_dict()
    payload["detection_set_cid"] = _cid("forged")
    with pytest.raises(ExecutionContractError, match="identity mismatch"):
        ExpectedDetectionSet.from_dict(payload)

    outcome = _outcome()
    payload = outcome.to_dict()
    payload["outcome_cid"] = _cid("forged")
    with pytest.raises(ExecutionContractError, match="identity mismatch"):
        MutationOutcome.from_dict(payload)


def test_unsupported_schema_and_interface_fail_closed() -> None:
    eds = _detection_set()
    payload = eds.to_dict()
    payload["schema"] = "wrong@1"
    with pytest.raises(ExecutionContractError, match="schema version"):
        ExpectedDetectionSet.from_dict(payload)
    payload = eds.to_dict()
    payload["interface_id"] = "ExpectedDetectionSet@99"
    # Changing interface changes identity payload; from_dict checks interface first
    # after pop order — both schema path and interface path are fail-closed.
    with pytest.raises(ExecutionContractError):
        ExpectedDetectionSet.from_dict(payload)


def test_floats_private_and_model_authority_fail_closed() -> None:
    with pytest.raises(ExecutionContractError, match="DAG-JSON|private|authority"):
        _prediction(metadata={"score": 1.5})
    with pytest.raises(ExecutionContractError, match="private"):
        _prediction(metadata={"api_key": "secret"})
    with pytest.raises(ExecutionContractError, match="model-written authority"):
        _outcome(metadata={"model_authority": True})
    with pytest.raises(ExecutionContractError, match="host fallback"):
        _receipt(metadata={"host_path": "/tmp"})


def test_list_order_normalized_for_identity() -> None:
    left = _detection_set(
        predicted_detectors=(_prediction(), _static_prediction()),
    )
    right = _detection_set(
        predicted_detectors=(_static_prediction(), _prediction()),
    )
    assert left.detection_set_cid == right.detection_set_cid
    assert left.predicted_detector_ids == right.predicted_detector_ids


def test_identity_payload_matches_content_profile() -> None:
    for model in (
        _prediction(),
        _detection_set(),
        _execution_plan(),
        _receipt(),
        _outcome(),
        _equivalence(),
        _classification(),
        _cost(),
    ):
        payload = model.identity_payload()
        recomputed = cid_for_structured(payload)
        cid_attr = (
            "prediction_cid"
            if isinstance(model, DetectorPrediction)
            else "detection_set_cid"
            if isinstance(model, ExpectedDetectionSet)
            else "execution_plan_cid"
            if isinstance(model, MutationExecutionPlan)
            else "receipt_cid"
            if isinstance(model, MutationExecutionReceipt)
            else "outcome_cid"
            if isinstance(model, MutationOutcome)
            else "assessment_cid"
            if isinstance(model, MutationEquivalenceAssessment)
            else "classification_cid"
            if isinstance(model, DetectorClassification)
            else "cost_cid"
        )
        assert recomputed == getattr(model, cid_attr)


def test_module_path_is_declared_output() -> None:
    root = Path(__file__).resolve()
    # tests/unit/logic/software_contracts/adversarial_assurance/test_*.py
    module = (
        root.parents[5]
        / "ipfs_datasets_py"
        / "logic"
        / "software_contracts"
        / "adversarial_assurance"
        / "execution_contracts.py"
    )
    # parents: 0=dir, 1=adversarial, 2=software_contracts, 3=logic, 4=unit,
    # 5=tests, 6=ipfs_datasets_py package root package? Let's locate robustly.
    candidates = list(
        Path(__file__).resolve().parents[6].rglob(
            "logic/software_contracts/adversarial_assurance/execution_contracts.py"
        )
    )
    assert candidates, "execution_contracts.py must exist as declared output"
    assert any(path.is_file() for path in candidates)
