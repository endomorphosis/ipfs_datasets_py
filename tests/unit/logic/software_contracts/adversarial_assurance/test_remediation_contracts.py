"""Contract vectors for candidate remediation and evaluation models (AAE-011)."""

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
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.remediation_contracts import (
    CandidateAnalyzerRule,
    CandidateDraftStatus,
    CandidateKind,
    CandidatePolicyConstraint,
    CandidateProofObligation,
    CandidateTestSpecification,
    EvaluationPartition,
    EvaluationVerdict,
    GapRemediationPlan,
    MutationClassToken,
    NonvacuityCondition,
    PartitionEvaluationEvidence,
    RejectionReason,
    RemediationContractError,
    RemediationEvaluationReport,
    RemediationPlanStatus,
    RemediationRiskClass,
    RequirementProvenance,
    candidate_draft_statuses,
    candidate_kinds,
    evaluation_partitions,
    evaluation_verdicts,
    mutation_class_tokens,
    rejection_reasons,
    remediation_plan_statuses,
    remediation_risk_classes,
    verify_candidate_analyzer_identity,
    verify_candidate_policy_identity,
    verify_candidate_proof_identity,
    verify_candidate_test_identity,
    verify_evaluation_report_identity,
    verify_plan_identity,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _generator(**overrides: object) -> GeneratorIdentity:
    fields = {
        "generator_id": "remediation_spec",
        "generator_version": "1.0.0",
        "interface_id": "propose_gap_remediation@1",
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
        "tool_ids": ("remediation.v1",),
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


BEHAVIOR = "reject unauthorized caller for protected action"


def _req(**overrides: object) -> RequirementProvenance:
    fields = {
        "requirement_id": "req_authz_reject",
        "intended_behavior": BEHAVIOR,
        "source_id": "spec_authz_v1",
        "requirement_cid": _cid("req-doc"),
        "source_path": "docs/requirements/authz.md",
        "notes": None,
    }
    fields.update(overrides)
    return RequirementProvenance(**fields)  # type: ignore[arg-type]


def _nonvacuity(**overrides: object) -> NonvacuityCondition:
    fields = {
        "condition_id": "nv_authz_reachable",
        "statement": "there exists an unauthorized caller that can invoke the action",
        "assumes_satisfiable": True,
        "excludes_unsatisfiable_antecedent": True,
        "notes": None,
    }
    fields.update(overrides)
    return NonvacuityCondition(**fields)  # type: ignore[arg-type]


def _partition(
    partition: EvaluationPartition | str,
    *,
    passed: bool = True,
    **overrides: object,
) -> PartitionEvaluationEvidence:
    fields = {
        "partition": partition,
        "passed": passed,
        "evidence_cids": (_cid(f"ev-{partition}"),),
        "mutant_ids": (),
        "killed_count": 0,
        "survived_count": 0,
        "notes": None,
    }
    fields.update(overrides)
    return PartitionEvaluationEvidence(**fields)  # type: ignore[arg-type]


def _candidate_test(**overrides: object) -> CandidateTestSpecification:
    fields = {
        "header": _header("candidate_test_specification"),
        "candidate_id": "cand_test_authz_1",
        "candidate_kind": CandidateKind.ADDITIONAL_TEST,
        "draft_status": CandidateDraftStatus.HEURISTIC_CANDIDATE,
        "intended_behavior": BEHAVIOR,
        "symbol_ids": ("mod.fn",),
        "setup_description": "install tenant policy and unauthorized principal",
        "observation_description": "observe authorization rejection receipt",
        "killed_mutation_classes": (MutationClassToken.AUTHORIZATION_POLICY,),
        "requirement_provenances": (_req(),),
        "risk_class": RemediationRiskClass.AUTHORIZATION,
        "freezes_implementation": False,
        "input_cid": _cid("test-input"),
        "fixture_ids": ("fx_unauth_caller",),
        "observation_points": ("authz.decision",),
        "source_path": "tests/test_authz.py",
        "gap_cids": (_cid("gap-1"),),
        "survivor_report_cids": (_cid("survivor-1"),),
        "evaluation_report_cid": None,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return CandidateTestSpecification(**fields)  # type: ignore[arg-type]


def _candidate_proof(**overrides: object) -> CandidateProofObligation:
    fields = {
        "header": _header("candidate_proof_obligation"),
        "candidate_id": "cand_proof_authz_1",
        "draft_status": CandidateDraftStatus.HEURISTIC_CANDIDATE,
        "proposition": "unauthorized callers are rejected before side effects",
        "assumptions": (
            "policy surface is default-deny",
            "caller principal is modeled",
        ),
        "modeled_state_ids": ("state.authz_checked",),
        "excluded_state_ids": ("state.authz_bypassed",),
        "source_connection": "mod.fn authorization guard at entry",
        "interface_connection": "AuthzGate.check@1",
        "prover_id": "lean.kernel.v1",
        "expected_counterexample": "unauthorized principal accepted with effect",
        "nonvacuity_condition": _nonvacuity(),
        "risk_class": RemediationRiskClass.AUTHORIZATION,
        "requirement_provenances": (_req(),),
        "symbol_ids": ("mod.fn",),
        "gap_cids": (_cid("gap-1"),),
        "evaluation_report_cid": None,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return CandidateProofObligation(**fields)  # type: ignore[arg-type]


def _candidate_policy(**overrides: object) -> CandidatePolicyConstraint:
    fields = {
        "header": _header("candidate_policy_constraint"),
        "candidate_id": "cand_policy_deny_1",
        "draft_status": CandidateDraftStatus.HEURISTIC_CANDIDATE,
        "constraint_statement": "missing policy must deny protected actions",
        "policy_surface_id": "authz.default_deny",
        "symbol_ids": ("mod.fn",),
        "requirement_provenances": (_req(),),
        "risk_class": RemediationRiskClass.AUTHORIZATION,
        "default_deny": True,
        "gap_cids": (_cid("gap-1"),),
        "evaluation_report_cid": None,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return CandidatePolicyConstraint(**fields)  # type: ignore[arg-type]


def _candidate_analyzer(**overrides: object) -> CandidateAnalyzerRule:
    fields = {
        "header": _header("candidate_analyzer_rule"),
        "candidate_id": "cand_analyzer_authz_1",
        "draft_status": CandidateDraftStatus.HEURISTIC_CANDIDATE,
        "rule_statement": "flag inverted or removed authorization guards",
        "analyzer_id": "static.authz_guard",
        "symbol_ids": ("mod.fn",),
        "killed_mutation_classes": (MutationClassToken.AUTHORIZATION_POLICY,),
        "requirement_provenances": (_req(),),
        "risk_class": RemediationRiskClass.AUTHORIZATION,
        "gap_cids": (_cid("gap-1"),),
        "evaluation_report_cid": None,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return CandidateAnalyzerRule(**fields)  # type: ignore[arg-type]


def _plan(**overrides: object) -> GapRemediationPlan:
    test = _candidate_test()
    proof = _candidate_proof()
    fields = {
        "header": _header("gap_remediation_plan"),
        "plan_id": "plan_authz_1",
        "plan_status": RemediationPlanStatus.DRAFT,
        "summary": "add test and proof for inverted authorization guard",
        "gap_cids": (_cid("gap-1"),),
        "candidate_test_cids": (test.candidate_cid,),
        "candidate_proof_cids": (proof.candidate_cid,),
        "candidate_policy_cids": (),
        "candidate_analyzer_cids": (),
        "requires_held_out_evaluation": True,
        "evaluation_report_cid": None,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return GapRemediationPlan(**fields)  # type: ignore[arg-type]


def _qualified_partitions() -> tuple[PartitionEvaluationEvidence, ...]:
    return (
        _partition(EvaluationPartition.UNMUTATED, passed=True),
        _partition(
            EvaluationPartition.DIAGNOSIS,
            passed=True,
            mutant_ids=("mut_diag_1",),
            killed_count=1,
        ),
        _partition(
            EvaluationPartition.DEVELOPMENT,
            passed=True,
            mutant_ids=("mut_dev_1",),
            killed_count=1,
        ),
        _partition(
            EvaluationPartition.HELD_OUT,
            passed=True,
            mutant_ids=("mut_hold_1",),
            killed_count=1,
        ),
        _partition(EvaluationPartition.UNRELATED, passed=True),
        _partition(EvaluationPartition.PERFORMANCE_COST, passed=True),
        _partition(EvaluationPartition.FALSE_POSITIVE, passed=True),
        _partition(EvaluationPartition.OVERCONSTRAINT, passed=True),
        _partition(EvaluationPartition.REGRESSION, passed=True),
        _partition(EvaluationPartition.SAFETY, passed=True),
    )


def _evaluation(**overrides: object) -> RemediationEvaluationReport:
    plan = _plan()
    test = _candidate_test()
    fields = {
        "header": _header("remediation_evaluation_report"),
        "report_id": "eval_authz_1",
        "plan_cid": plan.plan_cid,
        "candidate_cids": (test.candidate_cid,),
        "verdict": EvaluationVerdict.QUALIFIED,
        "partition_evidence": _qualified_partitions(),
        "regression_detected": False,
        "overconstraint_detected": False,
        "false_positive_detected": False,
        "unmutated_suite_passed": True,
        "diagnosis_killed": True,
        "development_killed": True,
        "held_out_killed": True,
        "unrelated_behavior_preserved": True,
        "safety_preserved": True,
        "cost_delta_basis_points": 50,
        "rejection_reasons": (),
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return RemediationEvaluationReport(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------


def test_closed_candidate_and_draft_vocabularies() -> None:
    kinds = candidate_kinds()
    assert "additional_test" in kinds
    assert "proof_obligation" in kinds
    assert "policy_constraint" in kinds
    assert "full_suite_fallback" in kinds
    assert candidate_draft_statuses()[0] == "heuristic_candidate"
    assert "promotion_ready" in candidate_draft_statuses()
    assert RemediationRiskClass.AUTHORIZATION.value in remediation_risk_classes()
    assert MutationClassToken.AUTHORIZATION_POLICY.value in mutation_class_tokens()
    assert "draft" in remediation_plan_statuses()
    assert "held_out" in evaluation_partitions()
    assert "regression" in evaluation_partitions()
    assert "overconstraint" in evaluation_partitions()
    assert "qualified" in evaluation_verdicts()
    assert "regression" in rejection_reasons()
    assert "overconstraint" in rejection_reasons()
    with pytest.raises(ValueError):
        CandidateDraftStatus("model_promoted")
    with pytest.raises(ValueError):
        CandidateKind("guess_test")
    with pytest.raises(ValueError):
        EvaluationVerdict("looks_good")


# ---------------------------------------------------------------------------
# Requirement provenance and nonvacuity nested records
# ---------------------------------------------------------------------------


def test_requirement_provenance_round_trip() -> None:
    req = _req()
    restored = RequirementProvenance.from_dict(req.to_dict())
    assert restored.provenance_cid == req.provenance_cid
    assert restored.intended_behavior == BEHAVIOR
    assert restored.requirement_id == "req_authz_reject"

    with pytest.raises(RemediationContractError, match="absolute"):
        _req(source_path="/etc/passwd")
    with pytest.raises(RemediationContractError, match="parent-directory"):
        _req(source_path="../escape.md")
    with pytest.raises(RemediationContractError, match="identity mismatch"):
        payload = req.to_dict()
        payload["provenance_cid"] = _cid("forged")
        RequirementProvenance.from_dict(payload)


def test_nonvacuity_condition_requires_satisfiable_assumptions() -> None:
    nv = _nonvacuity()
    restored = NonvacuityCondition.from_dict(nv.to_dict())
    assert restored.condition_cid == nv.condition_cid
    assert restored.assumes_satisfiable is True
    assert restored.excludes_unsatisfiable_antecedent is True

    with pytest.raises(RemediationContractError, match="assume_satisfiable"):
        _nonvacuity(assumes_satisfiable=False)
    with pytest.raises(RemediationContractError, match="unsatisfiable"):
        _nonvacuity(excludes_unsatisfiable_antecedent=False)


# ---------------------------------------------------------------------------
# CandidateTestSpecification — binds requirement provenance
# ---------------------------------------------------------------------------


def test_candidate_test_binds_requirement_provenance_and_starts_heuristic() -> None:
    candidate = _candidate_test()
    assert candidate.is_model_draft() is True
    assert candidate.draft_status == CandidateDraftStatus.HEURISTIC_CANDIDATE.value
    assert candidate.requirement_provenances
    assert (
        candidate.requirement_provenances[0].intended_behavior
        == candidate.intended_behavior
    )
    assert candidate.freezes_implementation is False
    assert MutationClassToken.AUTHORIZATION_POLICY.value in (
        candidate.killed_mutation_classes
    )
    restored = CandidateTestSpecification.from_dict(candidate.to_dict())
    assert restored.candidate_cid == candidate.candidate_cid
    assert verify_candidate_test_identity(candidate) == candidate.candidate_cid


def test_candidate_test_rejects_missing_provenance_and_implementation_freeze() -> None:
    with pytest.raises(RemediationContractError, match="requirement provenance"):
        _candidate_test(requirement_provenances=())
    with pytest.raises(RemediationContractError, match="freeze"):
        _candidate_test(freezes_implementation=True)
    with pytest.raises(RemediationContractError, match="must match"):
        _candidate_test(intended_behavior="some other behavior")
    with pytest.raises(RemediationContractError, match="killed_mutation_classes"):
        _candidate_test(killed_mutation_classes=())
    with pytest.raises(RemediationContractError, match="not a test candidate"):
        _candidate_test(candidate_kind=CandidateKind.PROOF_OBLIGATION)
    with pytest.raises(RemediationContractError, match="candidate_test_specification"):
        _candidate_test(header=_header("candidate_proof_obligation"))


def test_candidate_test_model_drafts_cannot_self_promote() -> None:
    with pytest.raises(RemediationContractError, match="self-promote|evaluation_report"):
        _candidate_test(
            draft_status=CandidateDraftStatus.PROMOTION_READY,
            evaluation_report_cid=None,
        )
    with pytest.raises(RemediationContractError, match="self-promote|evaluation_report"):
        _candidate_test(
            draft_status=CandidateDraftStatus.EVALUATION_QUALIFIED,
            evaluation_report_cid=None,
        )
    advanced = _candidate_test(
        draft_status=CandidateDraftStatus.EVALUATION_QUALIFIED,
        evaluation_report_cid=_cid("eval-report"),
    )
    assert advanced.is_model_draft() is False
    assert advanced.evaluation_report_cid == _cid("eval-report")

    with pytest.raises(RemediationContractError, match="must not claim evaluation"):
        _candidate_test(
            draft_status=CandidateDraftStatus.HEURISTIC_CANDIDATE,
            evaluation_report_cid=_cid("eval-report"),
        )


def test_candidate_test_forged_cid_and_unknown_fields_fail_closed() -> None:
    candidate = _candidate_test()
    payload = candidate.to_dict()
    payload["candidate_cid"] = _cid("forged")
    with pytest.raises(RemediationContractError, match="identity mismatch"):
        CandidateTestSpecification.from_dict(payload)

    payload = candidate.to_dict()
    payload["extra_field"] = "nope"
    with pytest.raises(RemediationContractError, match="fields must be exactly"):
        CandidateTestSpecification.from_dict(payload)


# ---------------------------------------------------------------------------
# CandidateProofObligation — assumptions, source connection, nonvacuity
# ---------------------------------------------------------------------------


def test_candidate_proof_includes_assumptions_source_connection_nonvacuity() -> None:
    proof = _candidate_proof()
    assert proof.is_model_draft() is True
    assert proof.draft_status == CandidateDraftStatus.HEURISTIC_CANDIDATE.value
    assert proof.assumptions
    assert proof.source_connection
    assert proof.interface_connection
    assert proof.nonvacuity_condition.assumes_satisfiable is True
    assert proof.nonvacuity_condition.excludes_unsatisfiable_antecedent is True
    restored = CandidateProofObligation.from_dict(proof.to_dict())
    assert restored.candidate_cid == proof.candidate_cid
    assert verify_candidate_proof_identity(proof) == proof.candidate_cid


def test_candidate_proof_rejects_empty_assumptions_and_overlapping_states() -> None:
    with pytest.raises(RemediationContractError, match="assumptions"):
        _candidate_proof(assumptions=())
    with pytest.raises(RemediationContractError, match="source_connection"):
        _candidate_proof(source_connection="")
    with pytest.raises(RemediationContractError, match="disjoint"):
        _candidate_proof(
            modeled_state_ids=("state.shared",),
            excluded_state_ids=("state.shared",),
        )
    with pytest.raises(RemediationContractError, match="assume_satisfiable"):
        _candidate_proof(
            nonvacuity_condition=_nonvacuity(assumes_satisfiable=False)
        )
    with pytest.raises(RemediationContractError, match="self-promote|evaluation_report"):
        _candidate_proof(
            draft_status=CandidateDraftStatus.PROMOTION_READY,
            evaluation_report_cid=None,
        )


# ---------------------------------------------------------------------------
# CandidatePolicyConstraint and CandidateAnalyzerRule
# ---------------------------------------------------------------------------


def test_candidate_policy_and_analyzer_round_trip_heuristic() -> None:
    policy = _candidate_policy()
    assert policy.is_model_draft() is True
    assert policy.default_deny is True
    restored_p = CandidatePolicyConstraint.from_dict(policy.to_dict())
    assert restored_p.candidate_cid == policy.candidate_cid
    assert verify_candidate_policy_identity(policy) == policy.candidate_cid

    analyzer = _candidate_analyzer()
    assert analyzer.is_model_draft() is True
    restored_a = CandidateAnalyzerRule.from_dict(analyzer.to_dict())
    assert restored_a.candidate_cid == analyzer.candidate_cid
    assert verify_candidate_analyzer_identity(analyzer) == analyzer.candidate_cid

    with pytest.raises(RemediationContractError, match="requirement provenance"):
        _candidate_policy(requirement_provenances=())
    with pytest.raises(RemediationContractError, match="killed_mutation_classes"):
        _candidate_analyzer(killed_mutation_classes=())
    with pytest.raises(RemediationContractError, match="self-promote|evaluation_report"):
        _candidate_policy(
            draft_status=CandidateDraftStatus.REQUIREMENT_GROUNDED,
            evaluation_report_cid=None,
        )


# ---------------------------------------------------------------------------
# GapRemediationPlan
# ---------------------------------------------------------------------------


def test_gap_remediation_plan_round_trip_requires_candidates_and_held_out() -> None:
    plan = _plan()
    assert plan.requires_held_out_evaluation is True
    assert plan.gap_cids
    assert plan.candidate_test_cids or plan.candidate_proof_cids
    restored = GapRemediationPlan.from_dict(plan.to_dict())
    assert restored.plan_cid == plan.plan_cid
    assert verify_plan_identity(plan) == plan.plan_cid

    with pytest.raises(RemediationContractError, match="gap_cids"):
        _plan(gap_cids=())
    with pytest.raises(RemediationContractError, match="at least one candidate"):
        _plan(
            candidate_test_cids=(),
            candidate_proof_cids=(),
            candidate_policy_cids=(),
            candidate_analyzer_cids=(),
        )
    with pytest.raises(RemediationContractError, match="held_out"):
        _plan(requires_held_out_evaluation=False)
    with pytest.raises(RemediationContractError, match="evaluation_report_cid"):
        _plan(
            plan_status=RemediationPlanStatus.EVALUATED,
            evaluation_report_cid=None,
        )
    evaluated = _plan(
        plan_status=RemediationPlanStatus.EVALUATED,
        evaluation_report_cid=_cid("eval-1"),
    )
    assert evaluated.plan_status == RemediationPlanStatus.EVALUATED.value


# ---------------------------------------------------------------------------
# RemediationEvaluationReport — regression and overconstraint
# ---------------------------------------------------------------------------


def test_evaluation_report_encodes_regression_and_overconstraint() -> None:
    report = _evaluation()
    partitions = {item.partition for item in report.partition_evidence}
    assert EvaluationPartition.REGRESSION.value in partitions
    assert EvaluationPartition.OVERCONSTRAINT.value in partitions
    assert report.regression_detected is False
    assert report.overconstraint_detected is False
    assert report.verdict == EvaluationVerdict.QUALIFIED.value
    restored = RemediationEvaluationReport.from_dict(report.to_dict())
    assert restored.report_cid == report.report_cid
    assert verify_evaluation_report_identity(report) == report.report_cid


def test_evaluation_report_rejects_missing_regression_overconstraint_partitions() -> None:
    with pytest.raises(RemediationContractError, match="regression and overconstraint"):
        _evaluation(
            partition_evidence=(
                _partition(EvaluationPartition.UNMUTATED),
                _partition(EvaluationPartition.HELD_OUT),
            )
        )
    with pytest.raises(RemediationContractError, match="regression and overconstraint"):
        _evaluation(
            partition_evidence=(
                _partition(EvaluationPartition.REGRESSION),
                # missing overconstraint
            )
        )


def test_evaluation_report_regression_and_overconstraint_rejection_paths() -> None:
    regression = _evaluation(
        verdict=EvaluationVerdict.REGRESSION,
        regression_detected=True,
        overconstraint_detected=False,
        unmutated_suite_passed=False,
        diagnosis_killed=True,
        development_killed=False,
        held_out_killed=False,
        unrelated_behavior_preserved=True,
        safety_preserved=True,
        rejection_reasons=(RejectionReason.REGRESSION,),
        partition_evidence=(
            _partition(EvaluationPartition.REGRESSION, passed=False),
            _partition(EvaluationPartition.OVERCONSTRAINT, passed=True),
            _partition(EvaluationPartition.UNMUTATED, passed=False),
        ),
    )
    assert regression.regression_detected is True
    assert RejectionReason.REGRESSION.value in regression.rejection_reasons

    overconstraint = _evaluation(
        verdict=EvaluationVerdict.OVERCONSTRAINT,
        regression_detected=False,
        overconstraint_detected=True,
        unmutated_suite_passed=True,
        diagnosis_killed=True,
        development_killed=True,
        held_out_killed=True,
        unrelated_behavior_preserved=False,
        safety_preserved=True,
        rejection_reasons=(
            RejectionReason.OVERCONSTRAINT,
            RejectionReason.UNRELATED_BEHAVIOR_BROKEN,
        ),
        partition_evidence=(
            _partition(EvaluationPartition.REGRESSION, passed=True),
            _partition(EvaluationPartition.OVERCONSTRAINT, passed=False),
            _partition(EvaluationPartition.UNRELATED, passed=False),
        ),
    )
    assert overconstraint.overconstraint_detected is True
    assert RejectionReason.OVERCONSTRAINT.value in overconstraint.rejection_reasons

    with pytest.raises(RemediationContractError, match="forbids regression"):
        _evaluation(regression_detected=True)
    with pytest.raises(RemediationContractError, match="forbids overconstraint"):
        _evaluation(overconstraint_detected=True)
    with pytest.raises(RemediationContractError, match="rejection_reasons"):
        _evaluation(
            verdict=EvaluationVerdict.REJECTED,
            rejection_reasons=(),
            regression_detected=False,
            overconstraint_detected=False,
            unmutated_suite_passed=True,
            diagnosis_killed=False,
            held_out_killed=False,
        )
    with pytest.raises(RemediationContractError, match="include regression"):
        _evaluation(
            verdict=EvaluationVerdict.REJECTED,
            regression_detected=True,
            overconstraint_detected=False,
            unmutated_suite_passed=False,
            diagnosis_killed=True,
            held_out_killed=False,
            rejection_reasons=(RejectionReason.HELD_OUT_FAILURE,),
            partition_evidence=(
                _partition(EvaluationPartition.REGRESSION, passed=False),
                _partition(EvaluationPartition.OVERCONSTRAINT, passed=True),
            ),
        )


def test_evaluation_report_forged_cid_fails_closed() -> None:
    report = _evaluation()
    payload = report.to_dict()
    payload["report_cid"] = _cid("forged")
    with pytest.raises(RemediationContractError, match="identity mismatch"):
        RemediationEvaluationReport.from_dict(payload)


# ---------------------------------------------------------------------------
# Fail-closed: private / model authority / host fallbacks / floats
# ---------------------------------------------------------------------------


def test_rejects_private_model_authority_and_host_fallback_metadata() -> None:
    with pytest.raises(RemediationContractError, match="private"):
        _candidate_test(metadata={"api_key": "secret"})
    with pytest.raises(RemediationContractError, match="model-written authority"):
        _candidate_proof(metadata={"model_authority": True})
    with pytest.raises(RemediationContractError, match="host fallback"):
        _plan(metadata={"host_env": "prod"})
    with pytest.raises(RemediationContractError, match="DAG-JSON|float"):
        _evaluation(metadata={"score": 0.5})


def test_closed_fields_reject_unknown_keys_on_all_top_level_models() -> None:
    models = (
        (_candidate_test(), CandidateTestSpecification),
        (_candidate_proof(), CandidateProofObligation),
        (_candidate_policy(), CandidatePolicyConstraint),
        (_candidate_analyzer(), CandidateAnalyzerRule),
        (_plan(), GapRemediationPlan),
        (_evaluation(), RemediationEvaluationReport),
    )
    for instance, cls in models:
        payload = instance.to_dict()
        payload["unexpected"] = True
        with pytest.raises(RemediationContractError, match="fields must be exactly"):
            cls.from_dict(payload)


def test_all_test_candidate_kinds_constructible() -> None:
    for kind in (
        CandidateKind.ADDITIONAL_TEST,
        CandidateKind.STRONGER_TEST,
        CandidateKind.PROPERTY_TEST,
    ):
        candidate = _candidate_test(
            candidate_id=f"cand_{kind.value}",
            candidate_kind=kind,
        )
        assert candidate.candidate_kind == kind.value
        assert candidate.draft_status == "heuristic_candidate"
