"""Unit vectors for requirement-grounded gap remediation proposals (AAE-032).

Acceptance focus:

* Allowed candidate types bind intended behavior and requirement provenance.
* Candidate tests do not merely encode implementation snapshots.
* Proof candidates include practical nonvacuity.
* Model output remains ``heuristic_candidate`` (no self-promotion).
"""

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
    AssuranceGap,
    AssuranceGapClass,
    GapSeverity,
    MinimizedEvidenceBinding,
    SourceSpan,
    SurvivingMutantReport,
    SurvivorRiskClass,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.remediation_contracts import (
    CandidateDraftStatus,
    CandidateKind,
    RemediationPlanStatus,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.remediation import (
    GENERATOR_ID,
    GENERATOR_VERSION,
    PROPOSE_GAP_REMEDIATION_INTERFACE,
    GapRemediationProposal,
    RemediationError,
    allowed_candidate_kinds,
    non_remediable_gap_classes,
    primary_kinds_for_gap_class,
    propose_gap_remediation,
    remediable_gap_classes,
    verify_gap_remediation_proposal_identity,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


REPO_ID = "repository:sha256:test-repo-identity"
REPO_STATE = _cid("repo-state")
CANDIDATE_ID = "cand_authz_invert_0"
CANDIDATE_CID = _cid("candidate")
OUTCOME_CID = _cid("outcome")
PROPERTY = "authorization check must reject unauthorized callers"
EXPECTED = "reject unauthorized caller for protected action"
OBSERVED = "unauthorized caller accepted and side effect applied"


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


def _header(artifact_kind: str, **overrides: object) -> AssuranceArtifactHeader:
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


def _survivor(**overrides: object) -> SurvivingMutantReport:
    fields = {
        "header": _header("surviving_mutant_report"),
        "report_id": "survivor_authz_1",
        "candidate_id": CANDIDATE_ID,
        "candidate_cid": CANDIDATE_CID,
        "outcome_cid": OUTCOME_CID,
        "risk_class": SurvivorRiskClass.AUTHORIZATION,
        "symbol_ids": ("mod.fn",),
        "violated_or_missing_property": PROPERTY,
        "detectors_run": ("unit.test_branch",),
        "detectors_omitted": ("static.authz_rule",),
        "expected_behavior": EXPECTED,
        "observed_behavior": OBSERVED,
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


def _gap(
    gap_class: AssuranceGapClass | str = AssuranceGapClass.MISSING_TEST,
    **overrides: object,
) -> AssuranceGap:
    survivor = overrides.pop("survivor", None)
    if survivor is None:
        survivor = _survivor()
    requires_review = gap_class in {
        AssuranceGapClass.UNKNOWN.value,
        AssuranceGapClass.UNKNOWN,
        AssuranceGapClass.SPECIFICATION_AMBIGUITY.value,
        AssuranceGapClass.SPECIFICATION_AMBIGUITY,
        AssuranceGapClass.INTENTIONALLY_UNCONSTRAINED.value,
        AssuranceGapClass.INTENTIONALLY_UNCONSTRAINED,
        AssuranceGapClass.PROBABLY_EQUIVALENT.value,
        AssuranceGapClass.PROBABLY_EQUIVALENT,
    }
    fields = {
        "header": _header("assurance_gap"),
        "gap_id": "gap_authz_missing_test",
        "gap_class": gap_class,
        "severity": GapSeverity.CRITICAL,
        "risk_class": survivor.risk_class,
        "summary": f"assurance gap {gap_class} for {PROPERTY}",
        "candidate_id": survivor.candidate_id,
        "candidate_cid": survivor.candidate_cid,
        "survivor_report_cid": survivor.report_cid,
        "violated_or_missing_property": PROPERTY,
        "symbol_ids": survivor.symbol_ids,
        "source_spans": survivor.source_spans,
        "dependency_path": survivor.dependency_path,
        "minimized_evidence": survivor.minimized_evidence,
        "requires_human_review": requires_review,
        "detection_failure_cids": (),
        "vacuity_finding_cids": (),
        "notes": None,
        "metadata": {
            "requirement_id": "req_authz_reject",
            "requirement_source_id": "spec_authz_v1",
            "requirement_cid": _cid("req-doc"),
            "requirement_source_path": "docs/requirements/authz.md",
        },
    }
    fields.update(overrides)
    return AssuranceGap(**fields)  # type: ignore[arg-type]


def _propose(
    gap_class: AssuranceGapClass | str = AssuranceGapClass.MISSING_TEST,
    **overrides: object,
) -> GapRemediationProposal:
    survivor = overrides.pop("survivor", _survivor())
    gap = overrides.pop("gap", _gap(gap_class, survivor=survivor))
    return propose_gap_remediation(survivor, gap, **overrides)


# ---------------------------------------------------------------------------
# Closed vocabulary and gap-class mapping
# ---------------------------------------------------------------------------


def test_closed_candidate_kinds_include_plan_section_10_types() -> None:
    kinds = allowed_candidate_kinds()
    assert "additional_test" in kinds
    assert "stronger_test" in kinds
    assert "property_test" in kinds
    assert "proof_obligation" in kinds
    assert "policy_constraint" in kinds
    assert "dependency_edge" in kinds
    assert "capsule_field" in kinds
    assert "full_suite_fallback" in kinds
    assert "manifest_requirement" in kinds
    with pytest.raises(ValueError):
        CandidateKind("guess_test")


def test_remediable_and_non_remediable_gap_partitions_are_disjoint() -> None:
    remediable = set(remediable_gap_classes())
    blocked = set(non_remediable_gap_classes())
    assert remediable.isdisjoint(blocked)
    assert AssuranceGapClass.MISSING_TEST.value in remediable
    assert AssuranceGapClass.UNKNOWN.value in blocked
    assert AssuranceGapClass.PROBABLY_EQUIVALENT.value in blocked


def test_primary_kinds_bind_gap_class_to_allowed_candidate_types() -> None:
    assert primary_kinds_for_gap_class(AssuranceGapClass.MISSING_TEST) == (
        CandidateKind.ADDITIONAL_TEST.value,
    )
    assert primary_kinds_for_gap_class(AssuranceGapClass.WEAK_ASSERTION) == (
        CandidateKind.STRONGER_TEST.value,
    )
    assert primary_kinds_for_gap_class(
        AssuranceGapClass.MISSING_PROOF_OBLIGATION
    ) == (CandidateKind.PROOF_OBLIGATION.value,)
    assert primary_kinds_for_gap_class(
        AssuranceGapClass.MISSING_POLICY_CONSTRAINT
    ) == (CandidateKind.POLICY_CONSTRAINT.value,)
    assert CandidateKind.DEPENDENCY_EDGE.value in primary_kinds_for_gap_class(
        AssuranceGapClass.STALE_OR_INCOMPLETE_DEPENDENCY_EDGE
    )
    with pytest.raises(RemediationError, match="non-remediable"):
        primary_kinds_for_gap_class(AssuranceGapClass.UNKNOWN)


# ---------------------------------------------------------------------------
# propose_gap_remediation — acceptance criteria
# ---------------------------------------------------------------------------


def test_missing_test_proposes_additional_test_with_provenance() -> None:
    proposal = _propose(AssuranceGapClass.MISSING_TEST)

    assert proposal.interface_id == PROPOSE_GAP_REMEDIATION_INTERFACE
    assert proposal.all_heuristic is True
    assert proposal.candidate_kinds == (CandidateKind.ADDITIONAL_TEST.value,)
    assert len(proposal.candidate_tests) == 1
    assert proposal.candidate_proofs == ()
    test = proposal.candidate_tests[0]

    # Intended behavior and provenance, not implementation snapshot.
    assert test.intended_behavior == EXPECTED
    assert test.freezes_implementation is False
    assert test.requirement_provenances
    assert test.requirement_provenances[0].intended_behavior == EXPECTED
    assert test.requirement_provenances[0].requirement_id == "req_authz_reject"
    assert test.draft_status == CandidateDraftStatus.HEURISTIC_CANDIDATE.value
    assert test.is_model_draft() is True
    assert test.evaluation_report_cid is None
    assert proposal.gap_cid in test.gap_cids
    assert proposal.survivor_report_cid in test.survivor_report_cids

    # Observation must not merely encode observed survivor output.
    assert OBSERVED not in test.intended_behavior
    assert "do not assert current observed output" in test.observation_description

    plan = proposal.gap_remediation_plan()
    assert plan.plan_status == RemediationPlanStatus.DRAFT.value
    assert plan.requires_held_out_evaluation is True
    assert test.candidate_cid in plan.candidate_test_cids
    assert plan.header.versions.generator.generator_id == GENERATOR_ID
    assert plan.header.versions.generator.generator_version == GENERATOR_VERSION
    assert plan.header.versions.generator.interface_id == (
        PROPOSE_GAP_REMEDIATION_INTERFACE
    )


def test_weak_assertion_proposes_stronger_test_not_implementation_freeze() -> None:
    proposal = _propose(AssuranceGapClass.WEAK_ASSERTION)
    assert proposal.candidate_kinds == (CandidateKind.STRONGER_TEST.value,)
    test = proposal.candidate_tests[0]
    assert test.candidate_kind == CandidateKind.STRONGER_TEST.value
    assert test.freezes_implementation is False
    assert test.intended_behavior == EXPECTED
    assert test.draft_status == "heuristic_candidate"
    # Stronger tests still bind killed mutation classes and symbols.
    assert test.killed_mutation_classes
    assert "mod.fn" in test.symbol_ids


def test_proof_candidates_include_nonvacuity_and_remain_heuristic() -> None:
    proposal = _propose(AssuranceGapClass.MISSING_PROOF_OBLIGATION)
    assert proposal.candidate_kinds == (CandidateKind.PROOF_OBLIGATION.value,)
    assert len(proposal.candidate_proofs) == 1
    proof = proposal.candidate_proofs[0]
    assert proof.draft_status == CandidateDraftStatus.HEURISTIC_CANDIDATE.value
    assert proof.is_model_draft() is True
    assert proof.assumptions
    assert proof.source_connection
    assert proof.interface_connection
    nv = proof.nonvacuity_condition
    assert nv.assumes_satisfiable is True
    assert nv.excludes_unsatisfiable_antecedent is True
    assert proof.requirement_provenances[0].intended_behavior == EXPECTED
    assert proof.metadata["includes_nonvacuity"] is True


def test_vacuous_proof_strengthens_nonvacuity_condition() -> None:
    proposal = _propose(AssuranceGapClass.VACUOUS_PROOF)
    proof = proposal.candidate_proofs[0]
    assert proof.nonvacuity_condition.assumes_satisfiable is True
    assert "unsatisfiable" in proof.nonvacuity_condition.statement
    assert proof.draft_status == "heuristic_candidate"
    assert "vacuous" in proof.excluded_state_ids[0]


def test_policy_and_analyzer_candidates_bind_provenance_and_heuristic() -> None:
    policy_proposal = _propose(AssuranceGapClass.MISSING_POLICY_CONSTRAINT)
    assert len(policy_proposal.candidate_policies) == 1
    policy = policy_proposal.candidate_policies[0]
    assert policy.draft_status == "heuristic_candidate"
    assert policy.requirement_provenances
    assert policy.default_deny is True
    assert policy.metadata["candidate_kind"] == CandidateKind.POLICY_CONSTRAINT.value

    dep_proposal = _propose(
        AssuranceGapClass.STALE_OR_INCOMPLETE_DEPENDENCY_EDGE
    )
    assert len(dep_proposal.candidate_analyzers) == 1
    analyzer = dep_proposal.candidate_analyzers[0]
    assert analyzer.draft_status == "heuristic_candidate"
    assert analyzer.requirement_provenances
    assert analyzer.metadata["candidate_kind"] == CandidateKind.DEPENDENCY_EDGE.value
    assert analyzer.killed_mutation_classes


def test_test_selection_failure_proposes_full_suite_fallback_and_test() -> None:
    proposal = _propose(AssuranceGapClass.TEST_SELECTION_FAILURE)
    kinds = set(proposal.candidate_kinds)
    assert CandidateKind.FULL_SUITE_FALLBACK.value in kinds
    assert CandidateKind.ADDITIONAL_TEST.value in kinds
    assert proposal.candidate_analyzers
    assert proposal.candidate_tests
    for item in (
        *proposal.candidate_tests,
        *proposal.candidate_analyzers,
    ):
        assert item.draft_status == "heuristic_candidate"


def test_unmodeled_side_effect_proposes_property_test_and_proof() -> None:
    proposal = _propose(AssuranceGapClass.UNMODELED_SIDE_EFFECT)
    assert CandidateKind.PROPERTY_TEST.value in proposal.candidate_kinds
    assert CandidateKind.PROOF_OBLIGATION.value in proposal.candidate_kinds
    assert proposal.candidate_tests[0].candidate_kind == (
        CandidateKind.PROPERTY_TEST.value
    )
    assert proposal.candidate_proofs[0].nonvacuity_condition.assumes_satisfiable


def test_proposal_is_deterministic_and_identity_stable() -> None:
    first = _propose(AssuranceGapClass.MISSING_TEST)
    second = _propose(AssuranceGapClass.MISSING_TEST)
    assert first.result_cid == second.result_cid
    assert first.plan.plan_cid == second.plan.plan_cid
    assert first.candidate_tests[0].candidate_cid == (
        second.candidate_tests[0].candidate_cid
    )
    restored = GapRemediationProposal.from_dict(first.to_dict())
    assert restored.result_cid == first.result_cid
    assert verify_gap_remediation_proposal_identity(first) == first.result_cid


def test_mapping_inputs_are_accepted() -> None:
    survivor = _survivor()
    gap = _gap(AssuranceGapClass.MISSING_TEST, survivor=survivor)
    proposal = propose_gap_remediation(survivor.to_dict(), gap.to_dict())
    assert proposal.gap_cid == gap.gap_cid
    assert proposal.survivor_report_cid == survivor.report_cid


# ---------------------------------------------------------------------------
# Fail-closed paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "gap_class",
    [
        AssuranceGapClass.UNKNOWN,
        AssuranceGapClass.SPECIFICATION_AMBIGUITY,
        AssuranceGapClass.INTENTIONALLY_UNCONSTRAINED,
        AssuranceGapClass.PROBABLY_EQUIVALENT,
    ],
)
def test_non_remediable_gap_classes_fail_closed(
    gap_class: AssuranceGapClass,
) -> None:
    with pytest.raises(RemediationError, match="non-remediable|human review"):
        _propose(gap_class)


def test_rejects_survivor_gap_identity_mismatch() -> None:
    survivor = _survivor()
    gap = _gap(
        AssuranceGapClass.MISSING_TEST,
        survivor=survivor,
        candidate_id="other_candidate",
        candidate_cid=_cid("other-candidate"),
    )
    with pytest.raises(RemediationError, match="candidate_id"):
        propose_gap_remediation(survivor, gap)


def test_rejects_survivor_report_cid_mismatch() -> None:
    survivor = _survivor()
    gap = _gap(
        AssuranceGapClass.MISSING_TEST,
        survivor=survivor,
        survivor_report_cid=_cid("different-report"),
    )
    with pytest.raises(RemediationError, match="survivor_report_cid"):
        propose_gap_remediation(survivor, gap)


def test_rejects_symbol_non_overlap() -> None:
    survivor = _survivor(symbol_ids=("mod.fn",))
    gap = _gap(
        AssuranceGapClass.MISSING_TEST,
        survivor=survivor,
        symbol_ids=("other.module",),
        source_spans=(_span(path="src/other.py"),),
    )
    with pytest.raises(RemediationError, match="symbol_ids"):
        propose_gap_remediation(survivor, gap)


def test_rejects_repository_state_drift() -> None:
    survivor = _survivor()
    gap = _gap(
        AssuranceGapClass.MISSING_TEST,
        survivor=survivor,
        header=_header(
            "assurance_gap",
            repository_state_cid=_cid("other-state"),
        ),
    )
    with pytest.raises(RemediationError, match="repository_state_cid"):
        propose_gap_remediation(survivor, gap)


def test_rejects_forged_proposal_result_cid() -> None:
    proposal = _propose(AssuranceGapClass.MISSING_TEST)
    payload = proposal.to_dict()
    payload["result_cid"] = _cid("forged")
    with pytest.raises(RemediationError, match="identity mismatch"):
        GapRemediationProposal.from_dict(payload)


def test_rejects_private_or_model_authority_metadata() -> None:
    with pytest.raises(Exception):
        _propose(
            AssuranceGapClass.MISSING_TEST,
            metadata={"private_key": "secret"},
        )


def test_proposal_plan_requires_held_out_and_stays_draft() -> None:
    proposal = _propose(AssuranceGapClass.RECEIPT_AUTHENTICITY_GAP)
    plan = proposal.plan
    assert plan.plan_status == "draft"
    assert plan.requires_held_out_evaluation is True
    assert plan.evaluation_report_cid is None
    # Receipt authenticity maps to analyzer invalidation + proof.
    assert proposal.candidate_analyzers or proposal.candidate_proofs
    for proof in proposal.candidate_proofs:
        assert proof.nonvacuity_condition.assumes_satisfiable is True
        assert proof.draft_status == "heuristic_candidate"


def test_all_remediable_gap_classes_produce_heuristic_candidates() -> None:
    """Behavioral coverage across the remediable taxonomy, not implementation echo."""

    for gap_class in remediable_gap_classes():
        proposal = _propose(gap_class)
        assert proposal.all_heuristic is True
        assert proposal.candidate_kinds
        total = (
            len(proposal.candidate_tests)
            + len(proposal.candidate_proofs)
            + len(proposal.candidate_policies)
            + len(proposal.candidate_analyzers)
        )
        assert total >= 1
        for test in proposal.candidate_tests:
            assert test.freezes_implementation is False
            assert test.intended_behavior == EXPECTED
            assert test.draft_status == "heuristic_candidate"
            assert test.requirement_provenances
        for proof in proposal.candidate_proofs:
            assert proof.nonvacuity_condition.assumes_satisfiable is True
            assert (
                proof.nonvacuity_condition.excludes_unsatisfiable_antecedent
                is True
            )
            assert proof.draft_status == "heuristic_candidate"
        for policy in proposal.candidate_policies:
            assert policy.draft_status == "heuristic_candidate"
            assert policy.requirement_provenances
        for analyzer in proposal.candidate_analyzers:
            assert analyzer.draft_status == "heuristic_candidate"
            assert analyzer.requirement_provenances


def test_production_policy_not_changed_in_proposal_metadata() -> None:
    proposal = _propose(AssuranceGapClass.MISSING_TEST)
    assert proposal.metadata["production_policy_changed"] is False
    assert proposal.metadata["freezes_implementation"] is False
    assert proposal.metadata["generator_id"] == GENERATOR_ID
