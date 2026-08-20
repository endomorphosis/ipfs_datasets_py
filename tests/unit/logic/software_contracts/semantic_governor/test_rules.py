"""Unit tests for bounded declarative rule proposals (SCG-017).

Acceptance criteria enforced here:

* Arbitrary code cannot execute.
* Full-suite fallback cannot be disabled.
* High-risk assurance cannot be reduced in a normal proposal.
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_governor.audit_contracts import (
    CompressionAuditCase,
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
from ipfs_datasets_py.logic.software_contracts.semantic_governor.calibration_contracts import (
    AnalyzerCalibrationProfile,
    CapsuleCalibrationRecord,
    ClassificationSource,
    EmpiricalRate,
    EvidencePartition,
    ModelRouteCalibrationProfile,
    ProofClassification,
    TaskClassCalibrationProfile,
    ratio_to_basis_points,
)
from ipfs_datasets_py.logic.software_contracts.semantic_governor.policy_contracts import (
    DeclarativeRule,
    PolicyContractError,
    ProtectedThresholds,
    RuleCategory,
    RuleOperation,
    RuleProposal,
)
from ipfs_datasets_py.logic.software_contracts.semantic_governor.rules import (
    PROPOSE_RULE_CHANGE_INTERFACE,
    VALIDATE_RULE_PROPOSAL_INTERFACE,
    AssuranceImpact,
    ProposalMode,
    RuleProposalDisposition,
    RuleProposalError,
    RuleProposalResult,
    ValidationVerdict,
    analyze_rule_assurance_impact,
    is_high_risk_assurance_reduction,
    proposal_modes,
    propose_rule_change,
    propose_rule_change_interface_id,
    rule_proposal_dispositions,
    validate_rule_proposal,
    validate_rule_proposal_interface_id,
    validation_verdicts,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _generator(**overrides: object) -> GeneratorIdentity:
    fields = {
        "generator_id": "rule_tests",
        "generator_version": "1.0.0",
        "interface_id": "propose_rule_change@1",
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
        "tool_ids": ("rules.v1",),
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
                assumption_id="partition_disjoint",
                kind=AssumptionKind.VERIFICATION,
                statement="Held-out partition is disjoint from calibration",
                supporting_cids=(_cid("partition"),),
            ),
        ),
        "metadata": {"track": "rule_proposals"},
    }
    fields.update(overrides)
    return GovernorArtifactHeader(**fields)  # type: ignore[arg-type]


def _rate(successes: int, trials: int) -> EmpiricalRate:
    rate_bp = ratio_to_basis_points(successes, trials) or 0
    return EmpiricalRate(
        successes=successes,
        trials=trials,
        rate_bp=rate_bp,
        interval_lower_bp=max(0, rate_bp - 500),
        interval_upper_bp=min(10_000, rate_bp + 500),
        interval_method="wilson_score_95",
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
        "benchmark_partition": "calibration",
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return CompressionAuditCase(**fields)  # type: ignore[arg-type]


def _capsule(**overrides: object) -> CapsuleCalibrationRecord:
    fields: dict[str, object] = {
        "header": _header("capsule_calibration_record"),
        "record_id": "capsule_py_fn",
        "capsule_class": "function_capsule",
        "language": "python",
        "symbol_kind": "function",
        "framework": "pytest",
        "analyzer_feature": "callgraph",
        "repository_family": "ipfs_datasets",
        "task_class": "local_bug",
        "risk_class": "medium",
        "route_tier": "standard",
        "proof_classification": ProofClassification.HEURISTIC,
        "classification_source": ClassificationSource.EMPIRICAL,
        "partition": EvidencePartition.CALIBRATION,
        "revision": 1,
        "use_count": 20,
        "compressed_success_count": 14,
        "expanded_success_count": 20,
        "omission_failure_count": 4,
        "stale_failure_count": 2,
        "false_exact_classification_count": 1,
        "unnecessary_raw_fallback_count": 3,
        "review_disagreement_count": 1,
        "token_savings_total": 2000,
        "verification_cost_total": 80,
        "omission_rate": _rate(4, 20),
        "source_audit_cids": (_cid("audit-1"),),
        "metadata": {},
    }
    fields.update(overrides)
    return CapsuleCalibrationRecord(**fields)  # type: ignore[arg-type]


def _analyzer(**overrides: object) -> AnalyzerCalibrationProfile:
    fields: dict[str, object] = {
        "header": _header("analyzer_calibration_profile"),
        "profile_id": "analyzer_callgraph",
        "analyzer_id": "callgraph",
        "analyzer_version": "1.0.0",
        "partition": EvidencePartition.CALIBRATION,
        "revision": 2,
        "total_uses": 20,
        "false_exact_classification_count": 1,
        "stale_failure_count": 2,
        "omission_rate": _rate(4, 20),
        "record_cids": (),
        "language_keys": ("python",),
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return AnalyzerCalibrationProfile(**fields)  # type: ignore[arg-type]


def _task(**overrides: object) -> TaskClassCalibrationProfile:
    fields: dict[str, object] = {
        "header": _header("task_class_calibration_profile"),
        "profile_id": "task_local_bug_high",
        "task_class": "local_bug",
        "risk_class": "high",
        "partition": EvidencePartition.CALIBRATION,
        "revision": 1,
        "total_uses": 15,
        "compressed_success_count": 10,
        "expanded_success_count": 15,
        "review_disagreement_count": 2,
        "omission_rate": _rate(3, 15),
        "required_proof_classification": ProofClassification.CONSERVATIVE,
        "classification_source": ClassificationSource.FORMAL,
        "record_cids": (),
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return TaskClassCalibrationProfile(**fields)  # type: ignore[arg-type]


def _route(**overrides: object) -> ModelRouteCalibrationProfile:
    fields: dict[str, object] = {
        "header": _header("model_route_calibration_profile"),
        "profile_id": "route_standard",
        "route_id": "standard_v1",
        "route_tier": "standard",
        "partition": EvidencePartition.CALIBRATION,
        "revision": 3,
        "total_uses": 20,
        "escalation_count": 5,
        "retry_count": 1,
        "shadow_sample_count": 1,
        "success_rate": _rate(15, 20),
        "escalation_rate_bp": 2500,
        "retry_rate_bp": 500,
        "shadow_sample_rate_bp": 50,
        "allows_empirical_exact_upgrade": False,
        "record_cids": (),
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return ModelRouteCalibrationProfile(**fields)  # type: ignore[arg-type]


def _rule(**overrides: object) -> DeclarativeRule:
    fields = {
        "rule_id": "raise_shadow_sample",
        "category": RuleCategory.SHADOW_SAMPLING_RATE,
        "operation": RuleOperation.SET_SAMPLE_RATE,
        "target_key": "shadow_sample_rate_bp",
        "value": 250,
        "scope_token": "python",
    }
    fields.update(overrides)
    return DeclarativeRule(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Interface pins
# ---------------------------------------------------------------------------


def test_interface_pins_are_stable() -> None:
    assert propose_rule_change_interface_id() == PROPOSE_RULE_CHANGE_INTERFACE
    assert validate_rule_proposal_interface_id() == VALIDATE_RULE_PROPOSAL_INTERFACE
    assert "normal" in proposal_modes()
    assert "proposed" in rule_proposal_dispositions()
    assert "accept" in validation_verdicts()


# ---------------------------------------------------------------------------
# Acceptance: arbitrary code cannot execute
# ---------------------------------------------------------------------------


def test_arbitrary_code_cannot_execute_in_draft_rules() -> None:
    profile = _capsule()
    with pytest.raises((RuleProposalError, PolicyContractError)):
        DeclarativeRule(
            rule_id="evil",
            category=RuleCategory.CONTEXT_RANKING,
            operation=RuleOperation.SET_TOKEN,
            target_key="context_rank_key",
            value="eval",
        )
    result = propose_rule_change(
        profile,
        (_case(),),
        draft_rules=(
            {
                "rule_id": "evil_import",
                "category": RuleCategory.CONTEXT_RANKING.value,
                "operation": RuleOperation.SET_TOKEN.value,
                "target_key": "context_rank_key",
                "value": "import",
                "scope_token": "python",
            },
        ),
    )
    assert result.disposition == RuleProposalDisposition.REJECTED.value
    assert result.proposal is None
    assert result.safety.arbitrary_code_rejected or any(
        "expressions" in reason or "import" in reason or "arbitrary" in reason
        for reason in result.blocking_reasons
    )


def test_validate_rejects_executable_templates_in_free_text() -> None:
    proposal = RuleProposal(
        header=_header("rule_proposal"),
        proposal_id="prop_ok",
        current_policy_version="1.0.0",
        current_policy_cid=_cid("policy-v1"),
        proposed_rules=(_rule(),),
        supporting_audit_cids=(_cid("audit-1"),),
        benefit_statement="Raise shadow sampling for opaque modules",
        safety_impact="No assurance reduction; full-suite fallback retained",
        scope_token="python",
        benchmark_cid=_cid("bench-1"),
        rollback_policy_cid=_cid("policy-v1"),
        calibration_profile_cids=(_cid("cal-1"),),
    )
    # Mutate via reconstruction with executable benefit text is blocked at construction.
    with pytest.raises(PolicyContractError, match="expressions|imports|commands|templates"):
        RuleProposal(
            header=_header("rule_proposal"),
            proposal_id="prop_bad",
            current_policy_version="1.0.0",
            current_policy_cid=_cid("policy-v1"),
            proposed_rules=(_rule(),),
            supporting_audit_cids=(_cid("audit-1"),),
            benefit_statement="Use eval to rewrite policy",
            safety_impact="No assurance reduction",
            scope_token="python",
            benchmark_cid=_cid("bench-1"),
            rollback_policy_cid=_cid("policy-v1"),
        )
    report = validate_rule_proposal(proposal)
    assert report.verdict == ValidationVerdict.ACCEPT.value
    assert report.safety.arbitrary_code_rejected is False


def test_validate_rules_reject_provider_keys_and_promotion_authority() -> None:
    report = validate_rule_proposal(
        rules=(
            _rule(
                rule_id="provider_leak",
                category=RuleCategory.CONTEXT_RANKING,
                operation=RuleOperation.SET_TOKEN,
                target_key="context_rank_key",
                value="importance",
            ),
        ),
        source_header=_header("rule_proposal"),
    )
    # Clean rule is fine.
    assert report.verdict == ValidationVerdict.ACCEPT.value

    # Provider IDs / promotion authority in free text fail closed at validation.
    bad = RuleProposal(
        header=_header("rule_proposal"),
        proposal_id="prop_auth",
        current_policy_version="1.0.0",
        current_policy_cid=_cid("policy-v1"),
        proposed_rules=(_rule(),),
        supporting_audit_cids=(_cid("audit-1"),),
        benefit_statement="Self authorize promotion authority for openai provider",
        safety_impact="None",
        scope_token="python",
        benchmark_cid=_cid("bench-1"),
        rollback_policy_cid=_cid("policy-v1"),
    )
    rejected = validate_rule_proposal(bad)
    assert rejected.verdict == ValidationVerdict.REJECT.value
    assert any(
        "provider" in reason.lower()
        or "promotion" in reason.lower()
        or "authority" in reason.lower()
        or "rejects" in reason.lower()
        for reason in rejected.blocking_reasons
    )


# ---------------------------------------------------------------------------
# Acceptance: full-suite fallback cannot be disabled
# ---------------------------------------------------------------------------


def test_full_suite_fallback_cannot_be_disabled_by_dsl() -> None:
    with pytest.raises(PolicyContractError, match="full-suite fallback cannot be disabled"):
        DeclarativeRule(
            rule_id="disable_fallback",
            category=RuleCategory.FULL_SUITE_FALLBACK,
            operation=RuleOperation.SET_BOOL,
            target_key="full_suite_fallback_enabled",
            value=False,
        )


def test_propose_rejects_draft_that_disables_full_suite() -> None:
    result = propose_rule_change(
        _capsule(),
        (_case(),),
        draft_rules=(
            {
                "rule_id": "disable_fallback",
                "category": RuleCategory.FULL_SUITE_FALLBACK.value,
                "operation": RuleOperation.SET_BOOL.value,
                "target_key": "full_suite_fallback_enabled",
                "value": False,
                "scope_token": "python",
            },
        ),
    )
    assert result.disposition == RuleProposalDisposition.REJECTED.value
    assert result.safety.full_suite_fallback_disabled or any(
        "full-suite" in reason for reason in result.blocking_reasons
    )


def test_generated_proposal_retains_full_suite_fallback_enabled() -> None:
    result = propose_rule_change(_capsule(), (_case(),))
    assert result.disposition == RuleProposalDisposition.PROPOSED.value
    assert result.proposal is not None
    assert result.safety.full_suite_fallback_disabled is False
    full_suite_rules = [
        rule
        for rule in result.proposal.proposed_rules
        if rule.target_key == "full_suite_fallback_enabled"
    ]
    assert full_suite_rules
    assert all(rule.value is True for rule in full_suite_rules)


# ---------------------------------------------------------------------------
# Acceptance: high-risk assurance cannot be reduced in a normal proposal
# ---------------------------------------------------------------------------


def test_high_risk_assurance_reduction_detected() -> None:
    reduce_rule = _rule(
        rule_id="drop_shadow",
        category=RuleCategory.SHADOW_SAMPLING_RATE,
        operation=RuleOperation.SET_SAMPLE_RATE,
        target_key="shadow_sample_rate_bp",
        value=0,
    )
    baseline = (_rule(rule_id="base_shadow", value=500),)
    assert is_high_risk_assurance_reduction(reduce_rule, baseline_rules=baseline)
    assert (
        analyze_rule_assurance_impact(reduce_rule, baseline_rules=baseline)
        == AssuranceImpact.REDUCE
    )

    disable_tests = DeclarativeRule(
        rule_id="drop_tests",
        category=RuleCategory.CONTEXT_PACKING,
        operation=RuleOperation.SET_BOOL,
        target_key="require_selected_tests",
        value=False,
    )
    assert is_high_risk_assurance_reduction(disable_tests)


def test_normal_proposal_rejects_assurance_reduction() -> None:
    reduce_rule = DeclarativeRule(
        rule_id="drop_proofs",
        category=RuleCategory.CONTEXT_PACKING,
        operation=RuleOperation.SET_BOOL,
        target_key="require_proofs",
        value=False,
    )
    result = propose_rule_change(
        _capsule(),
        (_case(),),
        draft_rules=(reduce_rule,),
        proposal_mode=ProposalMode.NORMAL,
    )
    assert result.disposition == RuleProposalDisposition.REJECTED.value
    assert result.safety.high_risk_assurance_reduced is True
    assert any("high-risk assurance" in reason for reason in result.blocking_reasons)

    report = validate_rule_proposal(
        rules=(reduce_rule,),
        proposal_mode=ProposalMode.NORMAL,
        source_header=_header("rule_proposal"),
    )
    assert report.verdict == ValidationVerdict.REJECT.value
    assert report.safety.high_risk_assurance_reduced is True


def test_normal_generated_proposals_do_not_reduce_assurance() -> None:
    result = propose_rule_change(_capsule(), (_case(), _case(case_id="case_b")))
    assert result.disposition == RuleProposalDisposition.PROPOSED.value
    assert result.safety.high_risk_assurance_reduced is False
    assert result.safety.assurance_impact != AssuranceImpact.REDUCE.value
    assert result.proposal is not None
    for rule in result.proposal.proposed_rules:
        assert not is_high_risk_assurance_reduction(rule)


# ---------------------------------------------------------------------------
# Evidence-bound generation covers allowlisted categories
# ---------------------------------------------------------------------------


def test_propose_generates_analyzer_invalidation_packing_and_route_categories() -> None:
    result = propose_rule_change(_capsule(), (_case(),))
    assert isinstance(result, RuleProposalResult)
    assert result.disposition == RuleProposalDisposition.PROPOSED.value
    assert result.proposal is not None
    categories = {rule.category for rule in result.proposal.proposed_rules}
    # Evidence on the capsule fixture drives these families.
    assert RuleCategory.INVALIDATION.value in categories
    assert RuleCategory.DEPENDENCY_EXTRACTION.value in categories
    assert RuleCategory.CAPSULE_COMPLETENESS.value in categories
    assert RuleCategory.RAW_SOURCE_INCLUSION.value in categories
    assert RuleCategory.CONTEXT_RANKING.value in categories
    assert RuleCategory.CONTEXT_PACKING.value in categories
    assert RuleCategory.FULL_SUITE_FALLBACK.value in categories
    # Budget and/or route and/or shadow depending on thresholds.
    assert categories & {
        RuleCategory.CONTEXT_BUDGET_THRESHOLD.value,
        RuleCategory.MODEL_ROUTE_THRESHOLD.value,
        RuleCategory.SHADOW_SAMPLING_RATE.value,
    }

    # Proposal carries version, benefit, safety, scope, benchmark, rollback.
    prop = result.proposal
    assert prop.current_policy_version
    assert prop.benefit_statement
    assert prop.safety_impact
    assert prop.scope_token
    assert prop.benchmark_cid
    assert prop.rollback_policy_cid
    assert prop.calibration_profile_cids
    assert list(prop.supporting_audit_cids) == sorted(prop.supporting_audit_cids)


def test_propose_from_analyzer_and_route_profiles() -> None:
    analyzer_result = propose_rule_change(_analyzer(), (_case(),))
    assert analyzer_result.disposition == RuleProposalDisposition.PROPOSED.value
    assert analyzer_result.proposal is not None
    cats = {rule.category for rule in analyzer_result.proposal.proposed_rules}
    assert RuleCategory.INVALIDATION.value in cats
    assert RuleCategory.DEPENDENCY_EXTRACTION.value in cats

    route_result = propose_rule_change(_route(), (_case(),))
    assert route_result.disposition == RuleProposalDisposition.PROPOSED.value
    assert route_result.proposal is not None
    route_cats = {rule.category for rule in route_result.proposal.proposed_rules}
    assert (
        RuleCategory.SHADOW_SAMPLING_RATE.value in route_cats
        or RuleCategory.MODEL_ROUTE_THRESHOLD.value in route_cats
    )


def test_propose_from_high_risk_task_class() -> None:
    result = propose_rule_change(_task(), (_case(risk_class="high"),))
    assert result.disposition == RuleProposalDisposition.PROPOSED.value
    assert result.proposal is not None
    cats = {rule.category for rule in result.proposal.proposed_rules}
    assert RuleCategory.MODEL_ROUTE_THRESHOLD.value in cats
    assert RuleCategory.FULL_SUITE_FALLBACK.value in cats


def test_held_out_partition_cannot_generate_proposals() -> None:
    profile = _capsule(partition=EvidencePartition.HELD_OUT)
    result = propose_rule_change(profile, (_case(),))
    assert result.disposition == RuleProposalDisposition.REJECTED.value
    assert any("held-out" in reason for reason in result.blocking_reasons)


def test_identical_inputs_yield_identical_result_cids() -> None:
    profile = _capsule()
    cases = (_case(),)
    a = propose_rule_change(profile, cases)
    b = propose_rule_change(profile, cases)
    assert a.result_cid == b.result_cid
    assert a.proposal is not None and b.proposal is not None
    assert a.proposal.proposal_cid == b.proposal.proposal_cid


def test_proposal_result_round_trip() -> None:
    result = propose_rule_change(_capsule(), (_case(),))
    restored = RuleProposalResult.from_dict(result.to_dict())
    assert restored.result_cid == result.result_cid
    assert restored.disposition == result.disposition


def test_validate_accepts_safe_sealed_proposal() -> None:
    result = propose_rule_change(_capsule(), (_case(),))
    assert result.proposal is not None
    report = validate_rule_proposal(result.proposal)
    assert report.verdict == ValidationVerdict.ACCEPT.value
    assert report.proposal_cid == result.proposal.proposal_cid
    restored = type(report).from_dict(report.to_dict())
    assert restored.report_cid == report.report_cid


def test_return_result_false_returns_proposal_or_raises() -> None:
    proposal = propose_rule_change(
        _capsule(),
        (_case(),),
        return_result=False,
    )
    assert isinstance(proposal, RuleProposal)
    with pytest.raises(RuleProposalError):
        propose_rule_change(
            _capsule(partition=EvidencePartition.HELD_OUT),
            (_case(),),
            return_result=False,
        )


def test_thresholds_must_keep_full_suite_required() -> None:
    # ProtectedThresholds construction forbids nothing on require_full_suite alone,
    # but validation rejects thresholds that disable the requirement.
    thresholds = ProtectedThresholds.default_production()
    assert thresholds.require_full_suite_fallback is True
    # Direct construction with False is allowed on the dataclass but blocked by
    # validation when used as protected_thresholds input for proposals.
    weakened = ProtectedThresholds(
        min_critical_omission_detection_bp=9_500,
        max_critical_omission_accepted=0,
        min_median_context_reduction_bp=5_000,
        max_accepted_regression_bp=0,
        min_shadow_sample_rate_bp=100,
        require_full_suite_fallback=False,
        allow_heuristic_as_exact=False,
        allow_assurance_reduction=False,
    )
    report = validate_rule_proposal(
        rules=(_rule(),),
        protected_thresholds=weakened,
        source_header=_header("rule_proposal"),
    )
    assert report.verdict == ValidationVerdict.REJECT.value
    assert report.safety.full_suite_fallback_disabled is True
