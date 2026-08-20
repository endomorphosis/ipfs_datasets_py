"""Contract vectors for coverage, audit, omission, expansion, decisions (SCG-007).

Acceptance criteria enforced here:

* Missing exclusion reasons reject.
* Unbounded paths / spans / steps reject.
* Inconsistent totals reject.
* Verification-pass-only sufficiency claims reject.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_governor.base import (
    AssumptionKind,
    ArtifactProvenance,
    AuthoritySource,
    ContextSufficiencyState,
    ExecutionMode,
    GeneratorIdentity,
    GovernorArtifactHeader,
    GovernorAssumption,
    GovernorTerminalStatus,
)
from ipfs_datasets_py.logic.software_contracts.semantic_governor.audit_contracts import (
    MAX_EXPANSION_STEPS,
    MAX_PATH_NODES,
    AuditContractError,
    CompressionAuditCase,
    ContextCoverageManifest,
    ContextExpansionPlan,
    ContextExpansionStep,
    ContextSufficiencyClaim,
    CoverageGap,
    CoveredArtifactKind,
    DecisionAction,
    ExcludedArtifactRecord,
    ExclusionReason,
    ExpansionAction,
    ExpansionStepStatus,
    GovernorDecision,
    GovernorRunReceipt,
    GraphPath,
    HypothesisCause,
    IncludedArtifactRecord,
    InclusionKind,
    OmissionEvidence,
    OmissionEvidenceKind,
    OmissionHypothesis,
    RouteTier,
    SourceSpan,
    SufficiencyEvidenceBasis,
    assert_sufficiency_not_verification_only,
    decision_actions,
    exclusion_reasons,
    expansion_actions,
    hypothesis_causes,
    inclusion_kinds,
    route_tiers,
    sufficiency_evidence_bases,
)

jsonschema = pytest.importorskip("jsonschema")

SCHEMA_PATH = (
    Path(__file__).resolve().parents[5]
    / "ipfs_datasets_py"
    / "logic"
    / "software_contracts"
    / "semantic_governor"
    / "schemas"
    / "audit.schema.json"
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _generator(**overrides: object) -> GeneratorIdentity:
    fields = {
        "generator_id": "audit_contracts",
        "generator_version": "1.0.0",
        "interface_id": "evaluate_context_sufficiency@1",
    }
    fields.update(overrides)
    return GeneratorIdentity(**fields)  # type: ignore[arg-type]


def _provenance(**overrides: object) -> ArtifactProvenance:
    fields = {
        "producer_id": "semantic_governor",
        "producer_version": "1",
        "execution_mode": ExecutionMode.LIVE,
        "authority_source": AuthoritySource.DETERMINISTIC,
        "input_cids": (_cid("input-a"),),
        "tool_ids": ("coverage.v1",),
        "policy_cid": _cid("policy"),
        "notes": None,
    }
    fields.update(overrides)
    return ArtifactProvenance(**fields)  # type: ignore[arg-type]


def _header(artifact_kind: str, **overrides: object) -> GovernorArtifactHeader:
    fields = {
        "artifact_kind": artifact_kind,
        "repository_state_cid": _cid("repo-state"),
        "context_pack_cid": _cid("context-pack"),
        "verification_bundle_cid": _cid("verification-bundle"),
        "generator": _generator(),
        "provenance": _provenance(),
        "terminal_status": GovernorTerminalStatus.COMPLETE,
        "assumptions": (
            GovernorAssumption(
                assumption_id="coverage_closed",
                kind=AssumptionKind.COVERAGE,
                statement="Coverage inventory is complete for the target cone",
                supporting_cids=(_cid("coverage"),),
            ),
        ),
        "metadata": {"track": "contracts_analysis"},
    }
    fields.update(overrides)
    return GovernorArtifactHeader(**fields)  # type: ignore[arg-type]


def _path() -> GraphPath:
    return GraphPath(nodes=("target_fn", "helper_fn"), edge_relation="calls")


def _span() -> SourceSpan:
    return SourceSpan(
        path="pkg/module.py",
        start_line=10,
        end_line=20,
        start_col=1,
        end_col=8,
    )


def _inclusion(**overrides: object) -> IncludedArtifactRecord:
    fields = {
        "artifact_id": "inc_target",
        "artifact_kind": CoveredArtifactKind.SYMBOL,
        "inclusion_kind": InclusionKind.RAW_SOURCE,
        "token_cost": 100,
        "symbol_id": "target_fn",
        "path": "pkg/module.py",
        "artifact_cid": _cid("inc-target"),
        "confidence_bp": 10_000,
        "dependency_path": _path(),
        "source_span": _span(),
        "notes": None,
    }
    fields.update(overrides)
    return IncludedArtifactRecord(**fields)  # type: ignore[arg-type]


def _exclusion(**overrides: object) -> ExcludedArtifactRecord:
    fields = {
        "artifact_id": "exc_helper",
        "artifact_kind": CoveredArtifactKind.SYMBOL,
        "exclusion_reason": ExclusionReason.EXACT_CAPSULE_SUBSTITUTED,
        "token_cost": 40,
        "confidence_bp": 9_500,
        "symbol_id": "helper_fn",
        "path": "pkg/helper.py",
        "artifact_cid": _cid("exc-helper"),
        "dependency_path": _path(),
        "source_span": SourceSpan(
            path="pkg/helper.py", start_line=1, end_line=5, start_col=1, end_col=1
        ),
        "repository_state_cid": _cid("repo-state"),
        "substituted_by_artifact_id": "capsule_helper",
        "critical": False,
        "notes": None,
    }
    fields.update(overrides)
    return ExcludedArtifactRecord(**fields)  # type: ignore[arg-type]


def _manifest(**overrides: object) -> ContextCoverageManifest:
    inclusions = overrides.pop("inclusions", None)
    exclusions = overrides.pop("exclusions", None)
    if inclusions is None:
        inclusions = (
            _inclusion(),
            _inclusion(
                artifact_id="inc_capsule",
                inclusion_kind=InclusionKind.EXACT_CAPSULE,
                token_cost=20,
                symbol_id="helper_fn",
                path="pkg/helper.py",
            ),
        )
    if exclusions is None:
        exclusions = (_exclusion(),)
    raw_count = 0
    capsule_count = 0
    for item in inclusions:
        kind = (
            item.inclusion_kind.value
            if isinstance(item.inclusion_kind, InclusionKind)
            else str(item.inclusion_kind)
        )
        if kind == "raw_source":
            raw_count += 1
        if kind in {"exact_capsule", "conservative_capsule"}:
            capsule_count += 1
    fields = {
        "header": _header("context_coverage_manifest"),
        "manifest_id": "manifest_local_bug",
        "target_symbol_ids": ("target_fn",),
        "inclusions": inclusions,
        "exclusions": exclusions,
        "context_budget_tokens": 500,
        "minimum_safe_tokens": 80,
        "total_included_tokens": sum(item.token_cost for item in inclusions),
        "total_excluded_tokens": sum(item.token_cost for item in exclusions),
        "raw_inclusion_count": raw_count,
        "capsule_inclusion_count": capsule_count,
        "exclusion_count": len(exclusions),
        "known_gaps": (),
        "opaque_dependency_ids": (),
        "dependency_paths": (_path(),),
        "policy_cid": _cid("policy"),
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return ContextCoverageManifest(**fields)  # type: ignore[arg-type]


def _claim(**overrides: object) -> ContextSufficiencyClaim:
    fields = {
        "header": _header("context_sufficiency_claim"),
        "claim_id": "claim_ok",
        "sufficiency_state": ContextSufficiencyState.SUFFICIENT,
        "evidence_bases": (
            SufficiencyEvidenceBasis.COVERAGE_MANIFEST,
            SufficiencyEvidenceBasis.DEPENDENCY_GRAPH,
            SufficiencyEvidenceBasis.VERIFICATION_PASS,
        ),
        "coverage_manifest_cid": _cid("manifest"),
        "route_tier": RouteTier.SMALL,
        "task_class": "local_bug",
        "risk_class": "low",
        "confidence_bp": 9_000,
        "verification_passed": True,
        "blocking_reason_codes": (),
        "known_gap_ids": (),
        "policy_cid": _cid("policy"),
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return ContextSufficiencyClaim(**fields)  # type: ignore[arg-type]


def _hypothesis(**overrides: object) -> OmissionHypothesis:
    fields = {
        "header": _header("omission_hypothesis"),
        "hypothesis_id": "hyp_helper",
        "cause": HypothesisCause.OMISSION,
        "subject_artifact_id": "exc_helper",
        "subject_kind": CoveredArtifactKind.SYMBOL,
        "rank": 0,
        "expected_relevance_bp": 8_000,
        "inclusion_cost_tokens": 40,
        "confidence_bp": 7_500,
        "expansion_action": ExpansionAction.INCLUDE_RAW_SOURCE,
        "exclusion_reason": ExclusionReason.EXACT_CAPSULE_SUBSTITUTED,
        "capsule_class": "function_capsule",
        "path": "pkg/helper.py",
        "source_span": SourceSpan(
            path="pkg/helper.py", start_line=1, end_line=5, start_col=1, end_col=1
        ),
        "dependency_path": _path(),
        "supporting_evidence_cids": (_cid("counterexample"),),
        "proposed_rule_change": None,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return OmissionHypothesis(**fields)  # type: ignore[arg-type]


def _step(**overrides: object) -> ContextExpansionStep:
    fields = {
        "header": _header("context_expansion_step"),
        "step_id": "step_0",
        "step_index": 0,
        "action": ExpansionAction.INCLUDE_RAW_SOURCE,
        "status": ExpansionStepStatus.PLANNED,
        "token_increase": 40,
        "artifact_ids_added": ("exc_helper",),
        "hypothesis_cid": _cid("hyp"),
        "reason_code": "omission_repair",
        "prior_result_cid": None,
        "new_result_cid": None,
        "changed_assumption_ids": ("coverage_closed",),
        "hypothesis_supported": None,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return ContextExpansionStep(**fields)  # type: ignore[arg-type]


def _plan(**overrides: object) -> ContextExpansionPlan:
    steps = overrides.pop("steps", None)
    if steps is None:
        steps = (_step(),)
    fields = {
        "header": _header("context_expansion_plan"),
        "plan_id": "plan_expand_helper",
        "audit_case_cid": _cid("audit-case"),
        "steps": steps,
        "max_steps": 8,
        "max_token_growth": 200,
        "total_token_increase": sum(step.token_increase for step in steps),
        "step_count": len(steps),
        "omission_evidence_cid": _cid("omission-evidence"),
        "max_retries": 3,
        "max_escalations": 1,
        "max_wall_time_ms": 60_000,
        "max_spend_micros": 0,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return ContextExpansionPlan(**fields)  # type: ignore[arg-type]


def _decision(**overrides: object) -> GovernorDecision:
    fields = {
        "header": _header("governor_decision"),
        "decision_id": "decision_expand",
        "action": DecisionAction.REQUIRE_EXPANSION,
        "sufficiency_state": ContextSufficiencyState.EXPANSION_REQUIRED,
        "route_tier": RouteTier.SMALL,
        "task_class": "local_bug",
        "risk_class": "low",
        "reason_codes": ("coverage_gap", "omission_suspected"),
        "coverage_manifest_cid": _cid("manifest"),
        "sufficiency_claim_cid": _cid("claim"),
        "expansion_plan_cid": _cid("plan"),
        "omission_evidence_cid": _cid("omission"),
        "policy_cid": _cid("policy"),
        "requires_human_review": False,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return GovernorDecision(**fields)  # type: ignore[arg-type]


def _receipt(**overrides: object) -> GovernorRunReceipt:
    fields = {
        "header": _header("governor_run_receipt"),
        "receipt_id": "run_receipt_1",
        "task_id": "SCG-007",
        "decision_cid": _cid("decision"),
        "route_tier": RouteTier.SMALL,
        "input_tokens": 120,
        "output_tokens": 40,
        "verification_cost_tokens": 10,
        "wall_time_ms": 2500,
        "spend_micros": 0,
        "coverage_manifest_cid": _cid("manifest"),
        "sufficiency_claim_cid": _cid("claim"),
        "expansion_plan_cid": None,
        "omission_evidence_cid": None,
        "shadow_result_cid": None,
        "differential_report_cid": None,
        "policy_cid": _cid("policy"),
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return GovernorRunReceipt(**fields)  # type: ignore[arg-type]


def _case(**overrides: object) -> CompressionAuditCase:
    fields = {
        "header": _header("compression_audit_case"),
        "case_id": "audit_case_1",
        "task_id": "SCG-007",
        "task_class": "local_bug",
        "risk_class": "low",
        "coverage_manifest_cid": _cid("manifest"),
        "sufficiency_claim_cid": _cid("claim"),
        "decision_cid": _cid("decision"),
        "run_receipt_cid": _cid("receipt"),
        "expansion_plan_cid": None,
        "omission_evidence_cid": None,
        "shadow_plan_cid": None,
        "shadow_result_cid": None,
        "differential_report_cid": None,
        "policy_cid": _cid("policy"),
        "benchmark_partition": "development",
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return CompressionAuditCase(**fields)  # type: ignore[arg-type]


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------


def test_closed_exclusion_reasons() -> None:
    expected = (
        "exact_capsule_substituted",
        "conservative_capsule_substituted",
        "proven_unrelated_by_dependency_graph",
        "outside_affected_invalidation_cone",
        "generated_from_included_authoritative_schema",
        "verified_immutable_dependency",
        "duplicate_representation",
        "budget_exceeded_escalation_required",
    )
    assert exclusion_reasons() == expected
    with pytest.raises(ValueError):
        ExclusionReason("heuristic_irrelevance")


def test_closed_supporting_vocabularies() -> None:
    assert "raw_source" in inclusion_kinds()
    assert "coverage_manifest" in sufficiency_evidence_bases()
    assert "include_raw_source" in expansion_actions()
    assert "accept_compressed" in decision_actions()
    assert "omission" in hypothesis_causes()
    assert "frontier" in route_tiers()
    with pytest.raises(ValueError):
        DecisionAction("accept_by_model")
    with pytest.raises(ValueError):
        SufficiencyEvidenceBasis("vibes")


# ---------------------------------------------------------------------------
# Acceptance: missing exclusion reasons reject
# ---------------------------------------------------------------------------


def test_exclusion_requires_closed_reason() -> None:
    with pytest.raises(AuditContractError, match="exclusion_reason"):
        ExcludedArtifactRecord(
            artifact_id="exc_x",
            artifact_kind=CoveredArtifactKind.FILE,
            exclusion_reason="",  # type: ignore[arg-type]
            token_cost=1,
            confidence_bp=100,
            dependency_path=_path(),
        )


def test_exclusion_rejects_unknown_reason() -> None:
    with pytest.raises(AuditContractError, match="exclusion_reason"):
        _exclusion(exclusion_reason="looks_irrelevant")


def test_manifest_rejects_exclusion_mapping_without_reason() -> None:
    bad_exclusion = {
        "artifact_id": "exc_missing",
        "artifact_kind": "file",
        "token_cost": 10,
        "confidence_bp": 1000,
        "dependency_path": _path().to_dict(),
    }
    with pytest.raises(AuditContractError, match="exclusion_reason"):
        ContextCoverageManifest(
            header=_header("context_coverage_manifest"),
            manifest_id="manifest_bad",
            target_symbol_ids=("target_fn",),
            inclusions=(_inclusion(),),
            exclusions=[bad_exclusion],  # type: ignore[list-item]
            context_budget_tokens=500,
            minimum_safe_tokens=80,
            total_included_tokens=100,
            total_excluded_tokens=10,
            raw_inclusion_count=1,
            capsule_inclusion_count=0,
            exclusion_count=1,
        )


def test_exclusion_must_be_graph_or_state_bound() -> None:
    with pytest.raises(AuditContractError, match="graph/state bound"):
        ExcludedArtifactRecord(
            artifact_id="exc_unbound",
            artifact_kind=CoveredArtifactKind.SYMBOL,
            exclusion_reason=ExclusionReason.DUPLICATE_REPRESENTATION,
            token_cost=5,
            confidence_bp=9_000,
            dependency_path=None,
            repository_state_cid=None,
        )


# ---------------------------------------------------------------------------
# Acceptance: unbounded paths / spans / steps reject
# ---------------------------------------------------------------------------


def test_unbounded_absolute_path_rejects() -> None:
    with pytest.raises(AuditContractError, match="relative repository path"):
        SourceSpan(path="/etc/passwd", start_line=1, end_line=1)


def test_parent_traversal_path_rejects() -> None:
    with pytest.raises(AuditContractError, match="parent traversal"):
        SourceSpan(path="../outside_repo.py", start_line=1, end_line=1)


def test_unbounded_span_line_rejects() -> None:
    with pytest.raises(AuditContractError, match="maximum bound"):
        SourceSpan(path="a.py", start_line=1, end_line=10_000_001)


def test_inverted_span_rejects() -> None:
    with pytest.raises(AuditContractError, match="end_line"):
        SourceSpan(path="a.py", start_line=10, end_line=5)


def test_unbounded_graph_path_rejects() -> None:
    nodes = tuple(f"n{i}" for i in range(MAX_PATH_NODES + 1))
    with pytest.raises(AuditContractError, match="maximum bound"):
        GraphPath(nodes=nodes)


def test_empty_graph_path_rejects() -> None:
    with pytest.raises(AuditContractError, match="must not be empty"):
        GraphPath(nodes=())


def test_unbounded_expansion_step_index_rejects() -> None:
    with pytest.raises(AuditContractError, match="bounded expansion"):
        _step(step_index=MAX_EXPANSION_STEPS)


def test_plan_rejects_steps_beyond_max_steps() -> None:
    steps = []
    for i in range(3):
        steps.append(
            _step(
                step_id=f"step_{i}",
                step_index=i,
                token_increase=1,
            )
        )
    with pytest.raises(AuditContractError, match="max_steps"):
        _plan(steps=tuple(steps), max_steps=2, step_count=3, total_token_increase=3)


def test_plan_rejects_max_steps_above_absolute_bound() -> None:
    with pytest.raises(AuditContractError, match="max_steps"):
        _plan(max_steps=MAX_EXPANSION_STEPS + 1)


# ---------------------------------------------------------------------------
# Acceptance: inconsistent totals reject
# ---------------------------------------------------------------------------


def test_manifest_rejects_inconsistent_included_token_total() -> None:
    with pytest.raises(AuditContractError, match="total_included_tokens"):
        _manifest(total_included_tokens=9999)


def test_manifest_rejects_inconsistent_excluded_token_total() -> None:
    with pytest.raises(AuditContractError, match="total_excluded_tokens"):
        _manifest(total_excluded_tokens=1)


def test_manifest_rejects_inconsistent_exclusion_count() -> None:
    with pytest.raises(AuditContractError, match="exclusion_count"):
        _manifest(exclusion_count=99)


def test_manifest_rejects_inconsistent_raw_count() -> None:
    with pytest.raises(AuditContractError, match="raw_inclusion_count"):
        _manifest(raw_inclusion_count=0)


def test_manifest_rejects_included_over_budget() -> None:
    with pytest.raises(AuditContractError, match="context_budget_tokens"):
        _manifest(context_budget_tokens=10)


def test_plan_rejects_inconsistent_step_count() -> None:
    with pytest.raises(AuditContractError, match="step_count"):
        _plan(step_count=99)


def test_plan_rejects_inconsistent_token_increase() -> None:
    with pytest.raises(AuditContractError, match="total_token_increase"):
        _plan(total_token_increase=1)


def test_plan_rejects_token_growth_over_cap() -> None:
    with pytest.raises(AuditContractError, match="max_token_growth"):
        _plan(max_token_growth=10, total_token_increase=40)


def test_plan_requires_contiguous_step_indices() -> None:
    with pytest.raises(AuditContractError, match="step_index"):
        _plan(
            steps=(
                _step(step_id="step_0", step_index=0, token_increase=10),
                _step(step_id="step_2", step_index=2, token_increase=10),
            ),
            step_count=2,
            total_token_increase=20,
        )


# ---------------------------------------------------------------------------
# Acceptance: verification-pass-only sufficiency claims reject
# ---------------------------------------------------------------------------


def test_verification_pass_only_cannot_establish_sufficient() -> None:
    with pytest.raises(AuditContractError, match="verification pass alone"):
        assert_sufficiency_not_verification_only(
            ContextSufficiencyState.SUFFICIENT,
            (SufficiencyEvidenceBasis.VERIFICATION_PASS,),
        )


def test_claim_rejects_verification_only_evidence() -> None:
    with pytest.raises(AuditContractError, match="verification pass alone"):
        _claim(
            evidence_bases=(SufficiencyEvidenceBasis.VERIFICATION_PASS,),
            verification_passed=True,
        )


def test_claim_rejects_empty_evidence_for_sufficient() -> None:
    with pytest.raises(AuditContractError, match="evidence_bases"):
        _claim(evidence_bases=())


def test_claim_allows_structural_plus_verification() -> None:
    claim = _claim()
    assert claim.sufficiency_state == "sufficient"
    assert "coverage_manifest" in claim.evidence_bases


def test_non_positive_states_may_use_verification_only() -> None:
    claim = _claim(
        sufficiency_state=ContextSufficiencyState.EXPANSION_REQUIRED,
        evidence_bases=(SufficiencyEvidenceBasis.VERIFICATION_PASS,),
        verification_passed=False,
        blocking_reason_codes=("missing_fixture",),
    )
    assert claim.sufficiency_state == "expansion_required"


# ---------------------------------------------------------------------------
# Happy-path round trips and identity
# ---------------------------------------------------------------------------


def test_manifest_round_trip_and_identity() -> None:
    manifest = _manifest()
    restored = ContextCoverageManifest.from_dict(manifest.to_dict())
    assert restored.manifest_cid == manifest.manifest_cid
    assert restored.raw_inclusion_count == 1
    assert restored.capsule_inclusion_count == 1
    assert restored.exclusion_count == 1
    assert restored.total_included_tokens == 120
    assert restored.total_excluded_tokens == 40


def test_claim_decision_receipt_case_round_trip() -> None:
    claim = _claim()
    decision = _decision(
        action=DecisionAction.ACCEPT_COMPRESSED,
        sufficiency_state=ContextSufficiencyState.SUFFICIENT,
        reason_codes=("coverage_complete", "acceptance_matrix"),
        expansion_plan_cid=None,
        omission_evidence_cid=None,
    )
    receipt = _receipt(decision_cid=decision.decision_cid)
    case = _case(
        coverage_manifest_cid=_cid("manifest"),
        sufficiency_claim_cid=claim.claim_cid,
        decision_cid=decision.decision_cid,
        run_receipt_cid=receipt.receipt_cid,
    )
    assert ContextSufficiencyClaim.from_dict(claim.to_dict()).claim_cid == claim.claim_cid
    assert GovernorDecision.from_dict(decision.to_dict()).decision_cid == decision.decision_cid
    assert GovernorRunReceipt.from_dict(receipt.to_dict()).receipt_cid == receipt.receipt_cid
    assert CompressionAuditCase.from_dict(case.to_dict()).case_cid == case.case_cid


def test_omission_and_expansion_round_trip() -> None:
    hyp = _hypothesis()
    evidence = OmissionEvidence(
        header=_header("omission_evidence"),
        evidence_id="evidence_1",
        evidence_kind=OmissionEvidenceKind.COUNTEREXAMPLE,
        audit_case_cid=_cid("audit-case"),
        hypothesis_cids=(hyp.hypothesis_cid,),
        supporting_cids=(_cid("counterexample"),),
        confidence_bp=8_000,
        differential_outcome="compressed_failed_expanded_succeeded",
        counterexample_cid=_cid("counterexample"),
    )
    plan = _plan()
    assert OmissionHypothesis.from_dict(hyp.to_dict()).hypothesis_cid == hyp.hypothesis_cid
    assert OmissionEvidence.from_dict(evidence.to_dict()).evidence_cid == evidence.evidence_cid
    assert ContextExpansionPlan.from_dict(plan.to_dict()).plan_cid == plan.plan_cid
    assert ContextExpansionStep.from_dict(plan.steps[0].to_dict()).step_cid == plan.steps[0].step_cid


def test_omission_cause_requires_exclusion_reason() -> None:
    with pytest.raises(AuditContractError, match="exclusion_reason"):
        _hypothesis(exclusion_reason=None)


def test_model_insufficiency_hypothesis_allows_null_exclusion() -> None:
    hyp = _hypothesis(
        cause=HypothesisCause.MODEL_INSUFFICIENCY,
        exclusion_reason=None,
        expansion_action=ExpansionAction.ESCALATE_ROUTE,
    )
    assert hyp.exclusion_reason is None
    assert hyp.cause == "model_insufficiency"


def test_accept_compressed_requires_sufficient_state() -> None:
    with pytest.raises(AuditContractError, match="accept_compressed"):
        _decision(
            action=DecisionAction.ACCEPT_COMPRESSED,
            sufficiency_state=ContextSufficiencyState.EXPANSION_REQUIRED,
        )


def test_require_human_review_flag_coherence() -> None:
    with pytest.raises(AuditContractError, match="requires_human_review"):
        _decision(
            action=DecisionAction.REQUIRE_HUMAN_REVIEW,
            sufficiency_state=ContextSufficiencyState.HUMAN_REVIEW_REQUIRED,
            requires_human_review=False,
            reason_codes=("policy_boundary",),
        )


def test_coverage_gap_on_manifest() -> None:
    gap = CoverageGap(
        gap_id="opaque_import",
        gap_kind="opaque_dependency",
        description="Dynamic import target unresolved",
        artifact_id="dyn_import",
        path="pkg/plugins.py",
        critical=True,
        supporting_cids=(_cid("edge"),),
    )
    manifest = _manifest(known_gaps=(gap,), opaque_dependency_ids=("dyn_import",))
    assert manifest.known_gaps[0].critical is True
    restored = ContextCoverageManifest.from_dict(manifest.to_dict())
    assert restored.known_gaps[0].gap_id == "opaque_import"


def test_private_metadata_rejected_on_claim() -> None:
    # Keep the private-field value short / non-credential-shaped so the
    # proposal gate does not treat the fixture as concrete secret material.
    with pytest.raises(AuditContractError, match="private"):
        _claim(metadata={"api_key": "x"})


def test_forged_manifest_cid_rejects() -> None:
    manifest = _manifest()
    payload = manifest.to_dict()
    payload["manifest_cid"] = _cid("forged")
    with pytest.raises(AuditContractError, match="manifest_cid"):
        ContextCoverageManifest.from_dict(payload)


def test_schema_validates_manifest_payload() -> None:
    schema = _load_schema()
    validator = jsonschema.Draft202012Validator(schema)
    payload = _manifest().to_dict()
    # Full oneOf validation against header-bearing records; validate via $defs.
    manifest_schema = {
        "$schema": schema["$schema"],
        "$defs": schema["$defs"],
        **schema["$defs"]["contextCoverageManifest"],
    }
    # Header is a nested closed object from base; structural check only requires object.
    errors = sorted(
        jsonschema.Draft202012Validator(manifest_schema).iter_errors(payload),
        key=lambda err: list(err.path),
    )
    assert errors == []
    # Enum surface is present for exclusion reasons.
    assert "exact_capsule_substituted" in schema["$defs"]["exclusionReason"]["enum"]
    assert validator is not None


def test_schema_file_exists_and_lists_all_interfaces() -> None:
    schema = _load_schema()
    defs = schema["$defs"]
    for key in (
        "contextCoverageManifest",
        "contextSufficiencyClaim",
        "excludedArtifactRecord",
        "omissionHypothesis",
        "omissionEvidence",
        "contextExpansionPlan",
        "contextExpansionStep",
        "governorDecision",
        "governorRunReceipt",
        "compressionAuditCase",
    ):
        assert key in defs
