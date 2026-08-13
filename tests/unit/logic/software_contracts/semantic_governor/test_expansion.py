"""Unit tests for bounded context expansion planning (SCG-015).

Acceptance criteria enforced here:

* Expanded context remains bounded (steps, tokens, hard plan limits).
* Impossible/unsafe budget returns human review (not unbounded growth or
  silent model escalation as a substitute for context).
* Omission expansion precedes model escalation where supported.
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_governor.audit_contracts import (
    MAX_EXPANSION_STEPS,
    CompressionAuditCase,
    CoveredArtifactKind,
    ExclusionReason,
    ExpansionAction,
    ExpansionStepStatus,
    GraphPath,
    HypothesisCause,
    OmissionHypothesis,
    SourceSpan,
)
from ipfs_datasets_py.logic.software_contracts.semantic_governor.base import (
    AssumptionKind,
    ArtifactProvenance,
    AuthoritySource,
    ExecutionMode,
    GeneratorIdentity,
    GovernorArtifactHeader,
    GovernorAssumption,
    GovernorTerminalStatus,
)
from ipfs_datasets_py.logic.software_contracts.semantic_governor.expansion import (
    DEFAULT_MAX_STEPS,
    PLAN_CONTEXT_EXPANSION_INTERFACE,
    ExpansionDisposition,
    ExpansionPlanResult,
    ExpansionPlannerError,
    TokenBudgetView,
    context_expansion_actions,
    default_expansion_limits,
    plan_context_expansion,
    plan_context_expansion_interface_id,
    route_escalation_actions,
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
        "metadata": {"track": "expansion"},
    }
    fields.update(overrides)
    return GovernorArtifactHeader(**fields)  # type: ignore[arg-type]


def _path(*nodes: str) -> GraphPath:
    return GraphPath(
        nodes=nodes or ("target_fn", "helper_fn"),
        edge_relation="calls",
    )


def _span(path: str = "pkg/helper.py", start: int = 1, end: int = 5) -> SourceSpan:
    return SourceSpan(
        path=path, start_line=start, end_line=end, start_col=1, end_col=1
    )


def _case(**overrides: object) -> CompressionAuditCase:
    fields: dict[str, object] = {
        "header": _header("compression_audit_case"),
        "case_id": "case_local_bug",
        "task_id": "task_local_bug_001",
        "task_class": "local_bug",
        "risk_class": "medium",
        "coverage_manifest_cid": _cid("manifest"),
        "sufficiency_claim_cid": _cid("claim"),
        "decision_cid": _cid("decision"),
        "run_receipt_cid": None,
        "expansion_plan_cid": None,
        "omission_evidence_cid": _cid("omission-evidence"),
        "shadow_plan_cid": _cid("shadow-plan"),
        "shadow_result_cid": _cid("shadow-result"),
        "differential_report_cid": _cid("differential"),
        "policy_cid": _cid("policy"),
        "benchmark_partition": "development",
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return CompressionAuditCase(**fields)  # type: ignore[arg-type]


def _hyp(**overrides: object) -> OmissionHypothesis:
    fields: dict[str, object] = {
        "header": _header("omission_hypothesis"),
        "hypothesis_id": "hyp_helper",
        "cause": HypothesisCause.OMISSION,
        "subject_artifact_id": "exc_helper",
        "subject_kind": CoveredArtifactKind.SYMBOL,
        "rank": 0,
        "expected_relevance_bp": 9_000,
        "inclusion_cost_tokens": 40,
        "confidence_bp": 8_500,
        "expansion_action": ExpansionAction.INCLUDE_RAW_SOURCE,
        "exclusion_reason": ExclusionReason.EXACT_CAPSULE_SUBSTITUTED,
        "capsule_class": "exact_capsule",
        "path": "pkg/helper.py",
        "source_span": _span(),
        "dependency_path": _path(),
        "supporting_evidence_cids": (_cid("counterexample"),),
        "proposed_rule_change": "prefer_raw_source_for_critical_exact_capsule_subjects",
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return OmissionHypothesis(**fields)  # type: ignore[arg-type]


def _util_hyp(**overrides: object) -> OmissionHypothesis:
    fields: dict[str, object] = {
        "hypothesis_id": "hyp_util",
        "subject_artifact_id": "exc_util",
        "rank": 1,
        "expected_relevance_bp": 7_000,
        "inclusion_cost_tokens": 20,
        "confidence_bp": 7_000,
        "expansion_action": ExpansionAction.STRENGTHEN_CAPSULE,
        "exclusion_reason": ExclusionReason.CONSERVATIVE_CAPSULE_SUBSTITUTED,
        "capsule_class": "conservative_capsule",
        "path": "pkg/util.py",
        "source_span": _span("pkg/util.py", 1, 3),
        "dependency_path": _path("target_fn", "util_fn"),
    }
    fields.update(overrides)
    return _hyp(**fields)


def _escalate_hyp(**overrides: object) -> OmissionHypothesis:
    fields: dict[str, object] = {
        "hypothesis_id": "hyp_model_route",
        "cause": HypothesisCause.MODEL_INSUFFICIENCY,
        "subject_artifact_id": "model_route",
        "subject_kind": CoveredArtifactKind.SYMBOL,
        "rank": 2,
        "expected_relevance_bp": 5_000,
        "inclusion_cost_tokens": 0,
        "confidence_bp": 6_000,
        "expansion_action": ExpansionAction.ESCALATE_ROUTE,
        "exclusion_reason": None,
        "capsule_class": None,
        "path": None,
        "source_span": None,
        "dependency_path": None,
        "supporting_evidence_cids": (_cid("model-insufficiency"),),
        "proposed_rule_change": "escalate_route_after_context_expansion_insufficient",
        "metadata": {"route_hypothesis": True, "formal_evidence": False},
    }
    fields.update(overrides)
    return _hyp(**fields)


def _review_hyp(**overrides: object) -> OmissionHypothesis:
    fields: dict[str, object] = {
        "hypothesis_id": "hyp_stale",
        "cause": HypothesisCause.STALE_ARTIFACT,
        "subject_artifact_id": "exc_stale",
        "rank": 0,
        "expected_relevance_bp": 9_000,
        "inclusion_cost_tokens": 0,
        "confidence_bp": 9_000,
        "expansion_action": ExpansionAction.REQUEST_HUMAN_REVIEW,
        "exclusion_reason": None,
        "capsule_class": None,
        "path": "pkg/stale.py",
        "source_span": None,
        "dependency_path": None,
        "supporting_evidence_cids": (_cid("stale-receipt"),),
        "proposed_rule_change": None,
        "metadata": {},
    }
    fields.update(overrides)
    return _hyp(**fields)


# ---------------------------------------------------------------------------
# Interface surface
# ---------------------------------------------------------------------------


def test_interface_pins() -> None:
    assert plan_context_expansion_interface_id() == PLAN_CONTEXT_EXPANSION_INTERFACE
    assert PLAN_CONTEXT_EXPANSION_INTERFACE.endswith("@1")
    assert ExpansionAction.INCLUDE_RAW_SOURCE.value in context_expansion_actions()
    assert ExpansionAction.STRENGTHEN_CAPSULE.value in context_expansion_actions()
    assert ExpansionAction.ESCALATE_ROUTE.value in route_escalation_actions()
    assert ExpansionAction.ESCALATE_ROUTE.value not in context_expansion_actions()
    limits = default_expansion_limits()
    assert limits["max_steps"] == DEFAULT_MAX_STEPS
    assert limits["max_expansion_steps_absolute"] == MAX_EXPANSION_STEPS
    assert limits["max_steps"] <= limits["max_expansion_steps_absolute"]


# ---------------------------------------------------------------------------
# Acceptance: expanded context remains bounded
# ---------------------------------------------------------------------------


def test_plan_is_bounded_by_token_budget_and_max_steps() -> None:
    hyps = (
        _hyp(inclusion_cost_tokens=40),
        _util_hyp(inclusion_cost_tokens=30),
        _hyp(
            hypothesis_id="hyp_extra",
            subject_artifact_id="exc_extra",
            rank=2,
            inclusion_cost_tokens=25,
            path="pkg/extra.py",
            source_span=_span("pkg/extra.py"),
            dependency_path=_path("target_fn", "extra_fn"),
        ),
    )
    plan = plan_context_expansion(_case(), hyps, token_budget=70, max_steps=2)

    assert plan.step_count <= plan.max_steps
    assert plan.step_count <= 2
    assert plan.total_token_increase <= plan.max_token_growth
    assert plan.total_token_increase <= 70
    assert plan.max_steps == 2
    assert plan.max_token_growth == 70
    assert plan.max_retries >= 0
    assert plan.max_escalations >= 0
    assert plan.max_wall_time_ms >= 0
    assert all(step.status == ExpansionStepStatus.PLANNED.value for step in plan.steps)
    assert all(step.step_index == i for i, step in enumerate(plan.steps))
    # Only ranked subjects — not a repository dump.
    for step in plan.steps:
        assert step.action in context_expansion_actions()
        assert step.artifact_ids_added
        assert all(aid.startswith("exc_") for aid in step.artifact_ids_added)


def test_plan_prefers_rank_order_smallest_cone() -> None:
    hyps = (_hyp(rank=0, inclusion_cost_tokens=40), _util_hyp(rank=1, inclusion_cost_tokens=20))
    plan = plan_context_expansion(_case(), hyps, token_budget=100)

    assert plan.step_count == 2
    assert plan.steps[0].artifact_ids_added == ("exc_helper",)
    assert plan.steps[0].action == ExpansionAction.INCLUDE_RAW_SOURCE.value
    assert plan.steps[1].artifact_ids_added == ("exc_util",)
    assert plan.steps[1].action == ExpansionAction.STRENGTHEN_CAPSULE.value
    assert plan.total_token_increase == 60
    assert plan.header.terminal_status == GovernorTerminalStatus.COMPLETE.value


def test_plan_skips_when_remaining_budget_insufficient_but_stays_bounded() -> None:
    hyps = (
        _hyp(rank=0, inclusion_cost_tokens=40),
        _util_hyp(rank=1, inclusion_cost_tokens=50),  # does not fit after first
        _hyp(
            hypothesis_id="hyp_small",
            subject_artifact_id="exc_small",
            rank=2,
            inclusion_cost_tokens=10,
            path="pkg/small.py",
            source_span=_span("pkg/small.py"),
        ),
    )
    result = plan_context_expansion(
        _case(), hyps, token_budget=55, return_result=True
    )
    assert isinstance(result, ExpansionPlanResult)
    plan = result.plan
    assert plan.total_token_increase <= 55
    assert plan.total_token_increase == 50  # 40 + 10; 50 skipped
    subjects = [s.artifact_ids_added[0] for s in plan.steps if s.artifact_ids_added]
    assert "exc_helper" in subjects
    assert "exc_small" in subjects
    assert "exc_util" not in subjects
    assert _util_hyp().hypothesis_cid in result.skipped_hypothesis_cids or any(
        "token_budget_skip" in code for code in result.reason_codes
    )


def test_empty_hypotheses_yield_empty_bounded_plan() -> None:
    plan = plan_context_expansion(_case(), (), token_budget=100)
    assert plan.step_count == 0
    assert plan.total_token_increase == 0
    assert plan.max_token_growth == 100
    assert plan.steps == ()
    assert plan.header.terminal_status == GovernorTerminalStatus.COMPLETE.value


def test_plan_round_trip_identity() -> None:
    plan = plan_context_expansion(_case(), (_hyp(),), token_budget=100)
    restored = type(plan).from_dict(plan.to_dict())
    assert restored.plan_cid == plan.plan_cid
    assert restored.step_count == plan.step_count


def test_deterministic_plan_cid() -> None:
    case = _case()
    hyps = (_hyp(), _util_hyp())
    a = plan_context_expansion(case, hyps, token_budget=100)
    b = plan_context_expansion(case, hyps, token_budget=100)
    assert a.plan_cid == b.plan_cid
    assert a.step_count == b.step_count


# ---------------------------------------------------------------------------
# Acceptance: impossible/unsafe budget returns human review
# ---------------------------------------------------------------------------


def test_zero_budget_with_omission_returns_human_review() -> None:
    result = plan_context_expansion(
        _case(), (_hyp(inclusion_cost_tokens=40),), token_budget=0, return_result=True
    )
    assert result.requires_human_review is True
    assert result.disposition == ExpansionDisposition.HUMAN_REVIEW.value
    plan = result.plan
    assert plan.header.terminal_status == (
        GovernorTerminalStatus.HUMAN_REVIEW_REQUIRED.value
    )
    assert plan.step_count == 1
    assert plan.steps[0].action == ExpansionAction.REQUEST_HUMAN_REVIEW.value
    assert plan.total_token_increase == 0
    assert plan.total_token_increase <= plan.max_token_growth
    assert "unsafe_zero_budget" in result.reason_codes or any(
        "human_review" in code for code in result.reason_codes
    )


def test_budget_below_best_hypothesis_returns_human_review() -> None:
    result = plan_context_expansion(
        _case(),
        (_hyp(inclusion_cost_tokens=80),),
        token_budget=40,
        return_result=True,
    )
    assert result.requires_human_review is True
    assert result.disposition == ExpansionDisposition.HUMAN_REVIEW.value
    plan = result.plan
    assert plan.steps[0].action == ExpansionAction.REQUEST_HUMAN_REVIEW.value
    assert plan.steps[0].reason_code == "budget_impossible"
    assert plan.total_token_increase == 0
    # Must not invent unbounded raw dump.
    assert all(
        step.action != ExpansionAction.INCLUDE_RAW_SOURCE.value for step in plan.steps
    )


def test_impossible_budget_does_not_escalate_as_substitute() -> None:
    """When omission expansion is supported but budget is impossible, do not
    escalate the model in place of context repair."""
    result = plan_context_expansion(
        _case(),
        (
            _hyp(rank=0, inclusion_cost_tokens=100),
            _escalate_hyp(rank=1),
        ),
        token_budget=10,
        return_result=True,
    )
    assert result.requires_human_review is True
    actions = [step.action for step in result.plan.steps]
    assert ExpansionAction.ESCALATE_ROUTE.value not in actions
    assert ExpansionAction.REQUEST_HUMAN_REVIEW.value in actions
    assert len(result.deferred_escalation_hypothesis_cids) >= 1


def test_disclosure_blocked_raw_source_returns_human_review() -> None:
    result = plan_context_expansion(
        _case(),
        (_hyp(expansion_action=ExpansionAction.INCLUDE_RAW_SOURCE),),
        token_budget=200,
        disclosure_blocked=True,
        return_result=True,
    )
    assert result.requires_human_review is True
    assert result.plan.steps[0].action == ExpansionAction.REQUEST_HUMAN_REVIEW.value
    assert result.plan.steps[0].reason_code == "disclosure_blocked"


def test_stale_review_hypothesis_returns_human_review() -> None:
    result = plan_context_expansion(
        _case(), (_review_hyp(),), token_budget=100, return_result=True
    )
    assert result.requires_human_review is True
    assert result.plan.header.terminal_status == (
        GovernorTerminalStatus.HUMAN_REVIEW_REQUIRED.value
    )
    assert result.plan.steps[0].action == ExpansionAction.REQUEST_HUMAN_REVIEW.value


def test_human_review_plan_still_has_hard_limits() -> None:
    plan = plan_context_expansion(
        _case(),
        (_hyp(inclusion_cost_tokens=500),),
        token_budget=1,
        max_steps=4,
        max_retries=2,
        max_escalations=1,
        max_wall_time_ms=30_000,
    )
    assert plan.max_steps == 4
    assert plan.max_retries == 2
    assert plan.max_escalations == 1
    assert plan.max_wall_time_ms == 30_000
    assert plan.step_count <= plan.max_steps
    assert plan.step_count <= MAX_EXPANSION_STEPS


# ---------------------------------------------------------------------------
# Acceptance: omission expansion precedes model escalation where supported
# ---------------------------------------------------------------------------


def test_omission_expansion_precedes_model_escalation() -> None:
    result = plan_context_expansion(
        _case(),
        (
            _hyp(rank=0, inclusion_cost_tokens=40),
            _util_hyp(rank=1, inclusion_cost_tokens=20),
            _escalate_hyp(rank=2),
        ),
        token_budget=200,
        return_result=True,
    )
    assert result.requires_human_review is False
    assert result.context_before_model_escalation is True
    plan = result.plan
    actions = [step.action for step in plan.steps]
    assert ExpansionAction.INCLUDE_RAW_SOURCE.value in actions
    assert ExpansionAction.ESCALATE_ROUTE.value in actions

    first_context = next(
        i for i, a in enumerate(actions) if a in context_expansion_actions()
    )
    first_escalate = next(
        i for i, a in enumerate(actions) if a == ExpansionAction.ESCALATE_ROUTE.value
    )
    assert first_context < first_escalate
    # All context steps must come before any escalate step.
    for i, action in enumerate(actions):
        if action in context_expansion_actions():
            assert i < first_escalate
    escalate_step = plan.steps[first_escalate]
    assert escalate_step.reason_code == "model_route_after_context"
    assert escalate_step.token_increase == 0


def test_model_insufficiency_only_plans_escalate_without_context() -> None:
    result = plan_context_expansion(
        _case(),
        (_escalate_hyp(rank=0),),
        token_budget=100,
        return_result=True,
    )
    assert result.requires_human_review is False
    assert result.disposition == ExpansionDisposition.ESCALATE_ONLY.value
    plan = result.plan
    assert plan.step_count == 1
    assert plan.steps[0].action == ExpansionAction.ESCALATE_ROUTE.value
    assert plan.steps[0].reason_code == "model_route_only"


def test_max_escalations_bound_defers_extra_route_hypotheses() -> None:
    result = plan_context_expansion(
        _case(),
        (
            _hyp(rank=0, inclusion_cost_tokens=10),
            _escalate_hyp(rank=1, hypothesis_id="hyp_model_a"),
            _escalate_hyp(
                rank=2,
                hypothesis_id="hyp_model_b",
                subject_artifact_id="model_route_b",
            ),
        ),
        token_budget=100,
        max_escalations=1,
        return_result=True,
    )
    escalate_steps = [
        s
        for s in result.plan.steps
        if s.action == ExpansionAction.ESCALATE_ROUTE.value
    ]
    assert len(escalate_steps) == 1
    assert len(result.deferred_escalation_hypothesis_cids) == 1


def test_zero_budget_with_both_omission_and_escalate_prefers_review_not_escalate() -> None:
    plan = plan_context_expansion(
        _case(),
        (_hyp(rank=0, inclusion_cost_tokens=30), _escalate_hyp(rank=1)),
        token_budget=0,
    )
    assert plan.header.terminal_status == (
        GovernorTerminalStatus.HUMAN_REVIEW_REQUIRED.value
    )
    assert all(
        step.action != ExpansionAction.ESCALATE_ROUTE.value for step in plan.steps
    )


# ---------------------------------------------------------------------------
# Fail-closed validation
# ---------------------------------------------------------------------------


def test_negative_token_budget_rejected() -> None:
    with pytest.raises(ExpansionPlannerError, match="nonnegative"):
        plan_context_expansion(_case(), (_hyp(),), token_budget=-1)


def test_max_steps_above_absolute_bound_rejected() -> None:
    with pytest.raises(ExpansionPlannerError, match="max_steps"):
        plan_context_expansion(
            _case(), (_hyp(),), token_budget=100, max_steps=MAX_EXPANSION_STEPS + 1
        )


def test_max_steps_zero_rejected() -> None:
    with pytest.raises(ExpansionPlannerError, match="positive"):
        plan_context_expansion(_case(), (_hyp(),), token_budget=100, max_steps=0)


def test_invalid_audit_case_rejected() -> None:
    with pytest.raises(ExpansionPlannerError):
        plan_context_expansion("not-a-case", (_hyp(),), token_budget=100)  # type: ignore[arg-type]


def test_duplicate_rank_subject_rejected() -> None:
    with pytest.raises(ExpansionPlannerError, match="duplicate"):
        plan_context_expansion(
            _case(),
            (
                _hyp(rank=0, subject_artifact_id="exc_helper"),
                _hyp(
                    hypothesis_id="hyp_dup",
                    rank=0,
                    subject_artifact_id="exc_helper",
                ),
            ),
            token_budget=100,
        )


def test_token_budget_view_identity_stable() -> None:
    a = TokenBudgetView(token_budget=100, max_steps=8)
    b = TokenBudgetView(token_budget=100, max_steps=8)
    assert a.view_cid == b.view_cid
    assert a.token_budget == 100


def test_changed_assumptions_recorded_on_context_steps() -> None:
    plan = plan_context_expansion(_case(), (_hyp(),), token_budget=100)
    step = plan.steps[0]
    assert "expansion_bounded" in step.changed_assumption_ids
    assert "affected_cone_only" in step.changed_assumption_ids
    assert step.hypothesis_cid is not None
    assert step.reason_code == "omission_repair"


def test_strengthen_capsule_reason_code() -> None:
    plan = plan_context_expansion(
        _case(),
        (_util_hyp(rank=0),),
        token_budget=100,
    )
    assert plan.steps[0].action == ExpansionAction.STRENGTHEN_CAPSULE.value
    assert plan.steps[0].reason_code == "strengthen_capsule"


def test_return_result_false_returns_plan_only() -> None:
    out = plan_context_expansion(_case(), (_hyp(),), token_budget=100, return_result=False)
    assert not isinstance(out, ExpansionPlanResult)
    assert out.plan_cid
    assert out.audit_case_cid == _case().case_cid


def test_schema_include_and_proof_actions() -> None:
    schema_hyp = _hyp(
        hypothesis_id="hyp_schema",
        subject_artifact_id="exc_schema",
        subject_kind=CoveredArtifactKind.SCHEMA,
        expansion_action=ExpansionAction.INCLUDE_SCHEMA,
        exclusion_reason=ExclusionReason.BUDGET_EXCEEDED_ESCALATION_REQUIRED,
        capsule_class=None,
        inclusion_cost_tokens=15,
        path="schemas/api.json",
        source_span=None,
    )
    proof_hyp = _hyp(
        hypothesis_id="hyp_proof",
        subject_artifact_id="exc_proof",
        subject_kind=CoveredArtifactKind.PROOF_OBLIGATION,
        expansion_action=ExpansionAction.INCLUDE_PROOF,
        rank=1,
        inclusion_cost_tokens=25,
        path="proofs/inv.lean",
        source_span=None,
        dependency_path=_path("target_fn", "proof_inv"),
    )
    plan = plan_context_expansion(
        _case(), (schema_hyp, proof_hyp), token_budget=100
    )
    assert plan.step_count == 2
    assert plan.steps[0].action == ExpansionAction.INCLUDE_SCHEMA.value
    assert plan.steps[1].action == ExpansionAction.INCLUDE_PROOF.value
    assert plan.total_token_increase == 40
