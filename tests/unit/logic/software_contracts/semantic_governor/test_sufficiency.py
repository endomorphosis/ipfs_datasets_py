"""Unit tests for conservative pre-execution sufficiency evaluation (SCG-012).

Acceptance criteria enforced here:

* Opaque critical and stale capsules force expansion / raw regeneration.
* Absent/unknown task-class mapping or missing required
  selected/full/static/type/proof/review checks fail closed.
* Policy boundaries and conflicting evidence require human review.
* Complete-but-hard work can request frontier.
* Verification pass alone cannot establish sufficiency.
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_governor.audit_contracts import (
    ContextCoverageManifest,
    CoverageGap,
    CoverageGapKind,
    CoveredArtifactKind,
    DecisionAction,
    ExcludedArtifactRecord,
    ExclusionReason,
    GraphPath,
    IncludedArtifactRecord,
    InclusionKind,
    RouteTier,
    SourceSpan,
    SufficiencyEvidenceBasis,
)
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
from ipfs_datasets_py.logic.software_contracts.semantic_governor.policy_contracts import (
    TaskClassAcceptanceRequirements,
)
from ipfs_datasets_py.logic.software_contracts.semantic_governor.sufficiency import (
    EVALUATE_CONTEXT_SUFFICIENCY_INTERFACE,
    CalibrationProfileView,
    ContextPackView,
    RepositoryStateView,
    SufficiencyEvaluationView,
    SufficiencyEvaluatorError,
    VerificationPolicyView,
    evaluate_context_sufficiency,
    planned_check_fields,
    recommended_decision_action,
    required_check_matrix_fields,
    sufficiency_evaluator_interface_id,
    sufficiency_state_precedence,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _path(*nodes: str) -> GraphPath:
    return GraphPath(nodes=nodes or ("target_fn", "helper_fn"), edge_relation="calls")


def _span(path: str = "pkg/module.py", start: int = 1, end: int = 10) -> SourceSpan:
    return SourceSpan(path=path, start_line=start, end_line=end, start_col=1, end_col=1)


def _generator(**overrides: object) -> GeneratorIdentity:
    fields = {
        "generator_id": "coverage_builder",
        "generator_version": "1.0.0",
        "interface_id": "build_context_coverage_manifest@1",
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


def _header(artifact_kind: str = "context_coverage_manifest", **overrides: object) -> GovernorArtifactHeader:
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
                statement="Coverage inventory is complete for the verified view",
                supporting_cids=(_cid("view"),),
            ),
        ),
        "metadata": {},
    }
    fields.update(overrides)
    return GovernorArtifactHeader(**fields)  # type: ignore[arg-type]


def _inclusion(**overrides: object) -> IncludedArtifactRecord:
    fields: dict[str, object] = {
        "artifact_id": "inc_target",
        "artifact_kind": CoveredArtifactKind.SYMBOL,
        "inclusion_kind": InclusionKind.RAW_SOURCE,
        "token_cost": 100,
        "symbol_id": "target_fn",
        "path": "pkg/module.py",
        "artifact_cid": _cid("inc-target"),
        "confidence_bp": 10_000,
        "dependency_path": _path("target_fn"),
        "source_span": _span(),
        "notes": None,
    }
    fields.update(overrides)
    return IncludedArtifactRecord(**fields)  # type: ignore[arg-type]


def _exclusion(**overrides: object) -> ExcludedArtifactRecord:
    fields: dict[str, object] = {
        "artifact_id": "exc_helper",
        "artifact_kind": CoveredArtifactKind.SYMBOL,
        "exclusion_reason": ExclusionReason.EXACT_CAPSULE_SUBSTITUTED.value,
        "token_cost": 40,
        "confidence_bp": 10_000,
        "symbol_id": "helper_fn",
        "path": "pkg/helper.py",
        "artifact_cid": _cid("exc-helper"),
        "dependency_path": _path("target_fn", "helper_fn"),
        "source_span": _span("pkg/helper.py", 1, 5),
        "repository_state_cid": _cid("repo-state"),
        "substituted_by_artifact_id": "inc_capsule_helper",
        "critical": False,
        "notes": None,
    }
    fields.update(overrides)
    return ExcludedArtifactRecord(**fields)  # type: ignore[arg-type]


def _manifest(**overrides: object) -> ContextCoverageManifest:
    inclusions = overrides.pop("inclusions", None)
    exclusions = overrides.pop("exclusions", None)
    known_gaps = overrides.pop("known_gaps", None)
    if inclusions is None:
        inclusions = (
            _inclusion(),
            _inclusion(
                artifact_id="inc_capsule_helper",
                inclusion_kind=InclusionKind.EXACT_CAPSULE,
                token_cost=20,
                symbol_id="helper_fn",
                path="pkg/helper.py",
                artifact_cid=_cid("capsule-helper"),
                confidence_bp=10_000,
                dependency_path=_path("target_fn", "helper_fn"),
                source_span=_span("pkg/helper.py", 1, 5),
            ),
        )
    if exclusions is None:
        exclusions = (_exclusion(),)
    if known_gaps is None:
        known_gaps = ()
    raw_count = sum(
        1 for item in inclusions if item.inclusion_kind == InclusionKind.RAW_SOURCE.value
        or item.inclusion_kind == "raw_source"
    )
    capsule_count = sum(
        1
        for item in inclusions
        if (
            item.inclusion_kind
            in {
                InclusionKind.EXACT_CAPSULE.value,
                InclusionKind.CONSERVATIVE_CAPSULE.value,
                "exact_capsule",
                "conservative_capsule",
            }
        )
    )
    fields: dict[str, object] = {
        "header": _header(),
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
        "known_gaps": known_gaps,
        "opaque_dependency_ids": (),
        "dependency_paths": (_path("target_fn", "helper_fn"),),
        "policy_cid": _cid("policy"),
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return ContextCoverageManifest(**fields)  # type: ignore[arg-type]


def _acceptance(**overrides: object) -> TaskClassAcceptanceRequirements:
    fields = {
        "task_class": "local_bug",
        "risk_class": "low",
        "require_selected_tests": True,
        "require_full_suite_fallback": True,
        "require_static_checks": True,
        "require_type_checks": True,
        "require_proofs": False,
        "require_human_review": False,
    }
    fields.update(overrides)
    return TaskClassAcceptanceRequirements(**fields)  # type: ignore[arg-type]


def _policy_all_present(**overrides: object) -> VerificationPolicyView:
    fields: dict[str, object] = {
        "selected_tests": True,
        "full_suite": True,
        "static_checks": True,
        "type_checks": True,
        "proofs": False,
        "human_review": False,
        "acceptance_requirements": _acceptance(),
        "verification_passed": False,
    }
    fields.update(overrides)
    return VerificationPolicyView(**fields)  # type: ignore[arg-type]


def _repo(**overrides: object) -> RepositoryStateView:
    fields: dict[str, object] = {
        "repository_state_cid": _cid("repo-state"),
        "stale_capsule_ids": (),
        "unresolved_invalidation_ids": (),
        "opaque_critical_dependency_ids": (),
        "conflicting_evidence": False,
        "policy_boundary": False,
        "disclosure_overflow": False,
    }
    fields.update(overrides)
    return RepositoryStateView(**fields)  # type: ignore[arg-type]


def _pack(**overrides: object) -> ContextPackView:
    fields: dict[str, object] = {
        "context_pack_cid": _cid("context-pack"),
        "coverage_manifest": _manifest(),
        "task_class": "local_bug",
        "risk_class": "low",
        "route_tier": RouteTier.SMALL,
    }
    fields.update(overrides)
    return ContextPackView(**fields)  # type: ignore[arg-type]


def _calibration(**overrides: object) -> CalibrationProfileView:
    fields: dict[str, object] = {
        "profile_cid": _cid("calibration"),
        "task_class": "local_bug",
        "risk_class": "low",
        "total_uses": 0,
        "omission_rate_bp": 0,
        "complexity_bp": 0,
        "request_frontier": False,
        "review_disagreement_count": 0,
    }
    fields.update(overrides)
    return CalibrationProfileView(**fields)  # type: ignore[arg-type]


def _evaluate(**overrides: object):
    pack = overrides.pop("context_pack", None)
    repo = overrides.pop("repository_state", None)
    policy = overrides.pop("verification_policy", None)
    calibration = overrides.pop("calibration_profile", None)
    if pack is None:
        pack = _pack()
    if repo is None:
        repo = _repo()
    if policy is None:
        policy = _policy_all_present()
    if calibration is None:
        calibration = _calibration()
    return evaluate_context_sufficiency(
        pack,
        repo,
        policy,
        calibration,
        **overrides,
    )


# ---------------------------------------------------------------------------
# Interface surface
# ---------------------------------------------------------------------------


def test_interface_pin() -> None:
    assert sufficiency_evaluator_interface_id() == EVALUATE_CONTEXT_SUFFICIENCY_INTERFACE
    assert EVALUATE_CONTEXT_SUFFICIENCY_INTERFACE.endswith("@1")
    assert required_check_matrix_fields() == (
        "require_selected_tests",
        "require_full_suite_fallback",
        "require_static_checks",
        "require_type_checks",
        "require_proofs",
        "require_human_review",
    )
    assert planned_check_fields() == (
        "selected_tests",
        "full_suite",
        "static_checks",
        "type_checks",
        "proofs",
        "human_review",
    )
    precedence = sufficiency_state_precedence()
    assert len(precedence) == 9
    assert precedence[0] == ContextSufficiencyState.EVALUATION_FAILED.value
    assert precedence[-1] == ContextSufficiencyState.SUFFICIENT.value


def test_recommended_action_mapping() -> None:
    assert (
        recommended_decision_action(ContextSufficiencyState.EXPANSION_REQUIRED)
        == DecisionAction.REQUIRE_EXPANSION.value
    )
    assert (
        recommended_decision_action(ContextSufficiencyState.FRONTIER_ESCALATION_REQUIRED)
        == DecisionAction.ESCALATE_FRONTIER.value
    )
    assert (
        recommended_decision_action(ContextSufficiencyState.STALE)
        == DecisionAction.MARK_STALE.value
    )
    assert (
        recommended_decision_action(ContextSufficiencyState.HUMAN_REVIEW_REQUIRED)
        == DecisionAction.REQUIRE_HUMAN_REVIEW.value
    )


# ---------------------------------------------------------------------------
# Happy path: sufficient with structural evidence
# ---------------------------------------------------------------------------


def test_complete_context_is_sufficient() -> None:
    claim = _evaluate()
    assert claim.sufficiency_state == ContextSufficiencyState.SUFFICIENT.value
    assert claim.blocking_reason_codes == ()
    assert SufficiencyEvidenceBasis.COVERAGE_MANIFEST.value in claim.evidence_bases
    assert SufficiencyEvidenceBasis.DEPENDENCY_GRAPH.value in claim.evidence_bases
    assert SufficiencyEvidenceBasis.ACCEPTANCE_MATRIX.value in claim.evidence_bases
    assert claim.metadata["recommended_action"] == DecisionAction.ACCEPT_COMPRESSED.value
    # verification_pass not required and not sole authority
    assert claim.verification_passed is False


def test_verification_pass_does_not_solely_authorize() -> None:
    """Even with verification_passed=True, structural bases are required."""
    claim = _evaluate(
        verification_policy=_policy_all_present(verification_passed=True),
    )
    assert claim.sufficiency_state == ContextSufficiencyState.SUFFICIENT.value
    assert claim.verification_passed is True
    assert SufficiencyEvidenceBasis.VERIFICATION_PASS.value in claim.evidence_bases
    # Structural bases always present for positive claims.
    assert SufficiencyEvidenceBasis.COVERAGE_MANIFEST.value in claim.evidence_bases
    assert claim.evidence_bases != (SufficiencyEvidenceBasis.VERIFICATION_PASS.value,)


def test_deterministic_claim_identity() -> None:
    a = _evaluate(claim_id="claim_fixed")
    b = _evaluate(claim_id="claim_fixed")
    assert a.claim_cid == b.claim_cid
    assert a.to_dict()["claim_cid"] == a.claim_cid


def test_four_arg_plan_signature() -> None:
    claim = evaluate_context_sufficiency(
        _pack(),
        _repo(),
        _policy_all_present(),
        _calibration(),
    )
    assert claim.sufficiency_state == ContextSufficiencyState.SUFFICIENT.value


def test_joined_view_argument() -> None:
    view = SufficiencyEvaluationView(
        context_pack=_pack(),
        repository_state=_repo(),
        verification_policy=_policy_all_present(),
        calibration_profile=_calibration(),
    )
    claim = evaluate_context_sufficiency(view)
    assert claim.sufficiency_state == ContextSufficiencyState.SUFFICIENT.value
    assert claim.metadata["view_cid"] == view.view_cid


# ---------------------------------------------------------------------------
# Acceptance: opaque critical forces expansion
# ---------------------------------------------------------------------------


def test_opaque_critical_dependency_forces_expansion() -> None:
    gap = CoverageGap(
        gap_id="opaque_dyn_import",
        gap_kind=CoverageGapKind.OPAQUE_DEPENDENCY,
        description="Critical opaque dynamic import remains unresolved",
        artifact_id="dyn_loader",
        critical=True,
    )
    claim = _evaluate(
        context_pack=_pack(
            coverage_manifest=_manifest(
                known_gaps=(gap,),
                opaque_dependency_ids=("dyn_loader",),
            )
        ),
        repository_state=_repo(opaque_critical_dependency_ids=("dyn_loader",)),
    )
    assert claim.sufficiency_state == ContextSufficiencyState.EXPANSION_REQUIRED.value
    assert "opaque_critical_dependency" in claim.blocking_reason_codes or any(
        "opaque" in code for code in claim.blocking_reason_codes
    )
    assert claim.metadata["recommended_action"] == DecisionAction.REQUIRE_EXPANSION.value
    assert SufficiencyEvidenceBasis.OPAQUE_DEPENDENCY_CHECK.value in claim.evidence_bases


def test_opaque_critical_gap_alone_forces_expansion() -> None:
    gap = CoverageGap(
        gap_id="opaque_native",
        gap_kind=CoverageGapKind.OPAQUE_DEPENDENCY,
        description="Opaque native surface is critical",
        artifact_id="native_hash",
        critical=True,
    )
    claim = _evaluate(
        context_pack=_pack(coverage_manifest=_manifest(known_gaps=(gap,))),
    )
    assert claim.sufficiency_state == ContextSufficiencyState.EXPANSION_REQUIRED.value
    assert "opaque_native" in claim.known_gap_ids


def test_critical_missing_proof_gap_forces_expansion() -> None:
    gap = CoverageGap(
        gap_id="missing_proof_invariant",
        gap_kind=CoverageGapKind.MISSING_PROOF,
        description="Required proof obligation not represented",
        critical=True,
    )
    claim = _evaluate(
        context_pack=_pack(coverage_manifest=_manifest(known_gaps=(gap,))),
        verification_policy=_policy_all_present(
            proofs=True,
            acceptance_requirements=_acceptance(require_proofs=True),
        ),
    )
    assert claim.sufficiency_state == ContextSufficiencyState.EXPANSION_REQUIRED.value
    assert any("missing_proof" in code for code in claim.blocking_reason_codes)


# ---------------------------------------------------------------------------
# Acceptance: stale capsules force raw regeneration
# ---------------------------------------------------------------------------


def test_stale_capsule_ids_force_stale_state() -> None:
    claim = _evaluate(
        repository_state=_repo(stale_capsule_ids=("inc_capsule_helper",)),
    )
    assert claim.sufficiency_state == ContextSufficiencyState.STALE.value
    assert "stale_capsule_requires_raw_regeneration" in claim.blocking_reason_codes
    assert claim.metadata["recommended_action"] == DecisionAction.MARK_STALE.value
    assert SufficiencyEvidenceBasis.FRESHNESS.value in claim.evidence_bases


def test_stale_capsule_gap_forces_stale_state() -> None:
    gap = CoverageGap(
        gap_id="stale_helper_capsule",
        gap_kind=CoverageGapKind.STALE_CAPSULE,
        description="Capsule is stale relative to repository state",
        artifact_id="inc_capsule_helper",
        critical=True,
    )
    claim = _evaluate(
        context_pack=_pack(coverage_manifest=_manifest(known_gaps=(gap,))),
    )
    assert claim.sufficiency_state == ContextSufficiencyState.STALE.value
    assert "stale_helper_capsule" in claim.known_gap_ids


def test_stale_takes_precedence_over_opaque_expansion() -> None:
    gap_stale = CoverageGap(
        gap_id="stale_a",
        gap_kind=CoverageGapKind.STALE_CAPSULE,
        description="Stale",
        critical=True,
    )
    gap_opaque = CoverageGap(
        gap_id="opaque_b",
        gap_kind=CoverageGapKind.OPAQUE_DEPENDENCY,
        description="Opaque",
        critical=True,
    )
    claim = _evaluate(
        context_pack=_pack(
            coverage_manifest=_manifest(known_gaps=(gap_stale, gap_opaque))
        ),
        repository_state=_repo(
            stale_capsule_ids=("inc_capsule_helper",),
            opaque_critical_dependency_ids=("dyn",),
        ),
    )
    assert claim.sufficiency_state == ContextSufficiencyState.STALE.value


# ---------------------------------------------------------------------------
# Acceptance: absent/unknown task-class mapping fails closed
# ---------------------------------------------------------------------------


def test_absent_task_class_mapping_fails_closed() -> None:
    claim = _evaluate(
        verification_policy=VerificationPolicyView(
            selected_tests=True,
            full_suite=True,
            static_checks=True,
            type_checks=True,
            acceptance_requirements=None,
            compression_policy=None,
        )
    )
    assert claim.sufficiency_state == ContextSufficiencyState.INVALID.value
    assert "absent_or_unknown_task_class_mapping" in claim.blocking_reason_codes
    assert claim.metadata["recommended_action"] == DecisionAction.MARK_INVALID.value


def test_mismatched_task_class_mapping_fails_closed() -> None:
    claim = _evaluate(
        context_pack=_pack(task_class="api_migration"),
        verification_policy=_policy_all_present(
            acceptance_requirements=_acceptance(
                task_class="local_bug", risk_class="low"
            )
        ),
    )
    assert claim.sufficiency_state == ContextSufficiencyState.INVALID.value
    assert "absent_or_unknown_task_class_mapping" in claim.blocking_reason_codes


# ---------------------------------------------------------------------------
# Acceptance: missing required checks fail closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "missing_field,planned_kw",
    [
        ("selected_tests", {"selected_tests": False}),
        ("full_suite", {"full_suite": False}),
        ("static_checks", {"static_checks": False}),
        ("type_checks", {"type_checks": False}),
        (
            "proofs",
            {
                "proofs": False,
                "acceptance_requirements": _acceptance(require_proofs=True),
            },
        ),
        (
            "human_review",
            {
                "human_review": False,
                "acceptance_requirements": _acceptance(require_human_review=True),
            },
        ),
    ],
)
def test_missing_required_check_fails_closed(
    missing_field: str, planned_kw: dict
) -> None:
    claim = _evaluate(verification_policy=_policy_all_present(**planned_kw))
    assert claim.sufficiency_state == ContextSufficiencyState.INVALID.value
    assert f"missing_required_{missing_field}" in claim.blocking_reason_codes


def test_all_required_checks_present_with_proofs() -> None:
    claim = _evaluate(
        verification_policy=_policy_all_present(
            proofs=True,
            acceptance_requirements=_acceptance(require_proofs=True),
        )
    )
    assert claim.sufficiency_state == ContextSufficiencyState.SUFFICIENT.value


# ---------------------------------------------------------------------------
# Acceptance: policy boundaries and conflicting evidence → human review
# ---------------------------------------------------------------------------


def test_conflicting_evidence_requires_human_review() -> None:
    claim = _evaluate(repository_state=_repo(conflicting_evidence=True))
    assert claim.sufficiency_state == ContextSufficiencyState.HUMAN_REVIEW_REQUIRED.value
    assert "conflicting_evidence" in claim.blocking_reason_codes
    assert (
        claim.metadata["recommended_action"]
        == DecisionAction.REQUIRE_HUMAN_REVIEW.value
    )
    assert SufficiencyEvidenceBasis.HUMAN_REVIEW.value in claim.evidence_bases


def test_policy_boundary_requires_human_review() -> None:
    claim = _evaluate(repository_state=_repo(policy_boundary=True))
    assert claim.sufficiency_state == ContextSufficiencyState.HUMAN_REVIEW_REQUIRED.value
    assert "policy_boundary" in claim.blocking_reason_codes


def test_disclosure_overflow_requires_human_review() -> None:
    claim = _evaluate(repository_state=_repo(disclosure_overflow=True))
    assert claim.sufficiency_state == ContextSufficiencyState.HUMAN_REVIEW_REQUIRED.value
    assert "disclosure_or_budget_overflow" in claim.blocking_reason_codes


def test_task_class_require_human_review_with_planned_check() -> None:
    """Matrix requires review; planned check present → human review state."""
    claim = _evaluate(
        verification_policy=_policy_all_present(
            human_review=True,
            acceptance_requirements=_acceptance(require_human_review=True),
        )
    )
    assert claim.sufficiency_state == ContextSufficiencyState.HUMAN_REVIEW_REQUIRED.value
    assert "task_class_requires_human_review" in claim.blocking_reason_codes


def test_human_review_precedes_expansion() -> None:
    gap = CoverageGap(
        gap_id="opaque_x",
        gap_kind=CoverageGapKind.OPAQUE_DEPENDENCY,
        description="Opaque critical",
        critical=True,
    )
    claim = _evaluate(
        context_pack=_pack(coverage_manifest=_manifest(known_gaps=(gap,))),
        repository_state=_repo(conflicting_evidence=True),
    )
    assert claim.sufficiency_state == ContextSufficiencyState.HUMAN_REVIEW_REQUIRED.value


# ---------------------------------------------------------------------------
# Acceptance: complete-but-hard work can request frontier
# ---------------------------------------------------------------------------


def test_complete_but_hard_request_frontier() -> None:
    claim = _evaluate(
        calibration_profile=_calibration(request_frontier=True, total_uses=10),
    )
    assert (
        claim.sufficiency_state
        == ContextSufficiencyState.FRONTIER_ESCALATION_REQUIRED.value
    )
    assert "complete_but_hard_request_frontier" in claim.blocking_reason_codes
    assert claim.metadata["recommended_action"] == DecisionAction.ESCALATE_FRONTIER.value
    assert claim.metadata["coverage_complete"] is True


def test_complete_high_complexity_requests_frontier() -> None:
    claim = _evaluate(
        calibration_profile=_calibration(complexity_bp=9_000, total_uses=3),
    )
    assert (
        claim.sufficiency_state
        == ContextSufficiencyState.FRONTIER_ESCALATION_REQUIRED.value
    )
    assert "complete_but_high_complexity" in claim.blocking_reason_codes


def test_complete_high_historical_omission_requests_frontier() -> None:
    claim = _evaluate(
        calibration_profile=_calibration(
            total_uses=20,
            omission_rate_bp=4_000,
        ),
    )
    assert (
        claim.sufficiency_state
        == ContextSufficiencyState.FRONTIER_ESCALATION_REQUIRED.value
    )
    assert "complete_but_high_historical_omission" in claim.blocking_reason_codes


def test_frontier_not_requested_when_expansion_needed() -> None:
    """Incomplete coverage must expand first; frontier is for complete-but-hard."""
    gap = CoverageGap(
        gap_id="opaque_y",
        gap_kind=CoverageGapKind.OPAQUE_DEPENDENCY,
        description="Opaque",
        critical=True,
    )
    claim = _evaluate(
        context_pack=_pack(coverage_manifest=_manifest(known_gaps=(gap,))),
        calibration_profile=_calibration(request_frontier=True),
    )
    assert claim.sufficiency_state == ContextSufficiencyState.EXPANSION_REQUIRED.value


# ---------------------------------------------------------------------------
# Caveats, inconclusive, unresolved invalidation
# ---------------------------------------------------------------------------


def test_noncritical_gap_yields_sufficient_with_caveats() -> None:
    gap = CoverageGap(
        gap_id="optional_fixture",
        gap_kind=CoverageGapKind.MISSING_FIXTURE,
        description="Optional fixture not represented",
        critical=False,
    )
    claim = _evaluate(
        context_pack=_pack(coverage_manifest=_manifest(known_gaps=(gap,))),
    )
    assert (
        claim.sufficiency_state
        == ContextSufficiencyState.SUFFICIENT_WITH_CAVEATS.value
    )
    assert "optional_fixture" in claim.known_gap_ids


def test_unresolved_invalidation_forces_expansion() -> None:
    claim = _evaluate(
        repository_state=_repo(
            unresolved_invalidation_ids=("inv_symbol_target_fn",)
        ),
    )
    assert claim.sufficiency_state == ContextSufficiencyState.EXPANSION_REQUIRED.value
    assert "unresolved_invalidation_obligations" in claim.blocking_reason_codes


def test_critical_budget_exclusion_forces_expansion() -> None:
    claim = _evaluate(
        context_pack=_pack(
            coverage_manifest=_manifest(
                exclusions=(
                    _exclusion(
                        artifact_id="exc_budget",
                        exclusion_reason=(
                            ExclusionReason.BUDGET_EXCEEDED_ESCALATION_REQUIRED.value
                        ),
                        critical=True,
                        substituted_by_artifact_id=None,
                    ),
                )
            )
        )
    )
    assert claim.sufficiency_state == ContextSufficiencyState.EXPANSION_REQUIRED.value
    assert "critical_budget_exceeded_expansion_required" in claim.blocking_reason_codes


def test_low_confidence_capsule_forces_expansion() -> None:
    claim = _evaluate(
        context_pack=_pack(
            coverage_manifest=_manifest(
                inclusions=(
                    _inclusion(),
                    _inclusion(
                        artifact_id="inc_heur_capsule",
                        inclusion_kind=InclusionKind.CONSERVATIVE_CAPSULE,
                        token_cost=20,
                        confidence_bp=4_000,
                        symbol_id="helper_fn",
                        path="pkg/helper.py",
                        artifact_cid=_cid("heur-capsule"),
                    ),
                )
            )
        )
    )
    assert claim.sufficiency_state == ContextSufficiencyState.EXPANSION_REQUIRED.value
    assert "low_confidence_capsule_requires_expansion" in claim.blocking_reason_codes


# ---------------------------------------------------------------------------
# Input validation / fail closed on malformed inputs
# ---------------------------------------------------------------------------


def test_repository_state_cid_mismatch_raises() -> None:
    with pytest.raises(SufficiencyEvaluatorError, match="repository_state_cid"):
        evaluate_context_sufficiency(
            _pack(),
            _repo(repository_state_cid=_cid("other-repo")),
            _policy_all_present(),
            _calibration(),
        )


def test_missing_repository_state_raises() -> None:
    with pytest.raises(SufficiencyEvaluatorError, match="repository_state"):
        evaluate_context_sufficiency(_pack())


def test_claim_round_trip() -> None:
    claim = _evaluate(claim_id="claim_roundtrip")
    restored = type(claim).from_dict(claim.to_dict())
    assert restored.claim_cid == claim.claim_cid
    assert restored.sufficiency_state == claim.sufficiency_state
