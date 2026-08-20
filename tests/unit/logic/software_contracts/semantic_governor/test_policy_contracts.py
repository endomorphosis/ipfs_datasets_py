"""Contract vectors for calibration profiles and policy/rule DSL (SCG-009)."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_governor.base import (
    AssumptionKind,
    ArtifactProvenance,
    AuthoritySource,
    ExecutionMode,
    GeneratorIdentity,
    GovernorArtifactHeader,
    GovernorAssumption,
    GovernorTerminalStatus,
    SemanticGovernorBaseError,
)
from ipfs_datasets_py.logic.software_contracts.semantic_governor.calibration_contracts import (
    AnalyzerCalibrationProfile,
    CalibrationContractError,
    CapsuleCalibrationRecord,
    ClassificationSource,
    EmpiricalRate,
    EvidencePartition,
    ModelRouteCalibrationProfile,
    ProofClassification,
    TaskClassCalibrationProfile,
    assert_proof_classification_allowed,
    classification_sources,
    evidence_partitions,
    proof_classifications,
    ratio_to_basis_points,
)
from ipfs_datasets_py.logic.software_contracts.semantic_governor.policy_contracts import (
    CompressionPolicy,
    CompressionPolicyCandidate,
    CompressionPolicyPromotionReceipt,
    DeclarativeRule,
    EvaluationVerdict,
    PolicyContractError,
    ProtectedThresholds,
    RuleCategory,
    RuleEvaluationReport,
    RuleOperation,
    RuleProposal,
    TaskClassAcceptanceRequirements,
    assert_protected_threshold_change_authorized,
    protected_threshold_reductions,
    rule_categories,
    rule_operations,
    validate_rule_dsl,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _generator(**overrides: object) -> GeneratorIdentity:
    fields = {
        "generator_id": "policy_contracts",
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
        "tool_ids": ("calibrator.v1",),
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
        "metadata": {"track": "contracts_policy"},
    }
    fields.update(overrides)
    return GovernorArtifactHeader(**fields)  # type: ignore[arg-type]


def _rate(
    successes: int = 9,
    trials: int = 10,
    **overrides: object,
) -> EmpiricalRate:
    rate_bp = ratio_to_basis_points(successes, trials) or 0
    fields = {
        "successes": successes,
        "trials": trials,
        "rate_bp": rate_bp,
        "interval_lower_bp": max(0, rate_bp - 500),
        "interval_upper_bp": min(10_000, rate_bp + 500),
        "interval_method": "wilson_score_95",
    }
    fields.update(overrides)
    return EmpiricalRate(**fields)  # type: ignore[arg-type]


def _thresholds(**overrides: object) -> ProtectedThresholds:
    fields = ProtectedThresholds.default_production().to_dict()
    fields.pop("schema")
    fields.update(overrides)
    return ProtectedThresholds(**fields)  # type: ignore[arg-type]


def _acceptance(
    task_class: str = "local_bug",
    risk_class: str = "low",
    **overrides: object,
) -> TaskClassAcceptanceRequirements:
    fields = {
        "task_class": task_class,
        "risk_class": risk_class,
        "require_selected_tests": True,
        "require_full_suite_fallback": True,
        "require_static_checks": True,
        "require_type_checks": True,
        "require_proofs": False,
        "require_human_review": False,
    }
    fields.update(overrides)
    return TaskClassAcceptanceRequirements(**fields)  # type: ignore[arg-type]


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
# Closed vocabularies
# ---------------------------------------------------------------------------


def test_closed_evidence_partitions() -> None:
    assert evidence_partitions() == ("calibration", "development", "held_out")


def test_closed_proof_classifications_and_sources() -> None:
    assert "exact" in proof_classifications()
    assert "heuristic" in proof_classifications()
    assert "empirical" in classification_sources()
    assert "formal" in classification_sources()
    with pytest.raises(ValueError):
        ProofClassification("model_exact")


def test_closed_rule_dsl_vocabularies() -> None:
    cats = rule_categories()
    ops = rule_operations()
    assert "full_suite_fallback" in cats
    assert "dependency_extraction" in cats
    assert "set_bool" in ops
    assert "set_sample_rate" in ops
    with pytest.raises(ValueError):
        RuleCategory("execute_shell")
    with pytest.raises(ValueError):
        RuleOperation("eval_expression")


# ---------------------------------------------------------------------------
# Acceptance: empirical cannot set proof classification to exact
# ---------------------------------------------------------------------------


def test_empirical_cannot_set_proof_classification_to_exact() -> None:
    with pytest.raises(
        CalibrationContractError,
        match="empirical results cannot set proof classification to exact",
    ):
        assert_proof_classification_allowed(
            ProofClassification.EXACT,
            ClassificationSource.EMPIRICAL,
        )


def test_capsule_record_rejects_empirical_exact() -> None:
    with pytest.raises(
        CalibrationContractError,
        match="empirical results cannot set proof classification to exact",
    ):
        CapsuleCalibrationRecord(
            header=_header("capsule_calibration_record"),
            record_id="capsule_py_fn",
            capsule_class="function_capsule",
            language="python",
            symbol_kind="function",
            framework="pytest",
            analyzer_feature="callgraph",
            repository_family="ipfs_datasets",
            task_class="local_bug",
            risk_class="low",
            route_tier="standard",
            proof_classification=ProofClassification.EXACT,
            classification_source=ClassificationSource.EMPIRICAL,
            partition=EvidencePartition.CALIBRATION,
            revision=1,
            use_count=10,
            compressed_success_count=9,
            expanded_success_count=10,
            omission_failure_count=1,
            stale_failure_count=0,
            false_exact_classification_count=0,
            unnecessary_raw_fallback_count=0,
            review_disagreement_count=0,
            token_savings_total=1200,
            verification_cost_total=40,
            omission_rate=_rate(1, 10),
            source_audit_cids=(_cid("audit-1"),),
        )


def test_formal_exact_classification_is_allowed() -> None:
    record = CapsuleCalibrationRecord(
        header=_header("capsule_calibration_record"),
        record_id="capsule_py_fn",
        capsule_class="function_capsule",
        language="python",
        symbol_kind="function",
        framework="pytest",
        analyzer_feature="callgraph",
        repository_family="ipfs_datasets",
        task_class="local_bug",
        risk_class="low",
        route_tier="standard",
        proof_classification=ProofClassification.EXACT,
        classification_source=ClassificationSource.FORMAL,
        partition=EvidencePartition.CALIBRATION,
        revision=1,
        use_count=10,
        compressed_success_count=9,
        expanded_success_count=10,
        omission_failure_count=1,
        stale_failure_count=0,
        false_exact_classification_count=0,
        unnecessary_raw_fallback_count=0,
        review_disagreement_count=0,
        token_savings_total=1200,
        verification_cost_total=40,
        omission_rate=_rate(1, 10),
        source_audit_cids=(_cid("audit-1"),),
    )
    assert record.proof_classification == "exact"
    restored = CapsuleCalibrationRecord.from_dict(record.to_dict())
    assert restored.record_cid == record.record_cid


def test_model_route_profile_forbids_empirical_exact_upgrade() -> None:
    with pytest.raises(
        CalibrationContractError,
        match="allows_empirical_exact_upgrade must be false",
    ):
        ModelRouteCalibrationProfile(
            header=_header("model_route_calibration_profile"),
            profile_id="route_standard",
            route_id="standard_v1",
            route_tier="standard",
            partition=EvidencePartition.CALIBRATION,
            revision=3,
            total_uses=100,
            escalation_count=5,
            retry_count=2,
            shadow_sample_count=10,
            success_rate=_rate(90, 100),
            escalation_rate_bp=500,
            retry_rate_bp=200,
            shadow_sample_rate_bp=1000,
            allows_empirical_exact_upgrade=True,
        )


def test_task_class_profile_rejects_empirical_required_exact() -> None:
    with pytest.raises(
        CalibrationContractError,
        match="empirical results cannot set proof classification to exact",
    ):
        TaskClassCalibrationProfile(
            header=_header("task_class_calibration_profile"),
            profile_id="task_local_bug",
            task_class="local_bug",
            risk_class="low",
            partition=EvidencePartition.CALIBRATION,
            revision=1,
            total_uses=20,
            compressed_success_count=18,
            expanded_success_count=20,
            review_disagreement_count=1,
            omission_rate=_rate(2, 20),
            required_proof_classification=ProofClassification.EXACT,
            classification_source=ClassificationSource.EMPIRICAL,
        )


def test_protected_thresholds_reject_heuristic_as_exact() -> None:
    with pytest.raises(PolicyContractError, match="allow_heuristic_as_exact must be false"):
        _thresholds(allow_heuristic_as_exact=True)


# ---------------------------------------------------------------------------
# Calibration identity and aggregates
# ---------------------------------------------------------------------------


def test_empirical_rate_uses_integer_basis_points_only() -> None:
    rate = EmpiricalRate.from_counts(1, 4)
    assert rate.rate_bp == 2500
    assert isinstance(rate.rate_bp, int)
    with pytest.raises(CalibrationContractError, match="basis-point"):
        EmpiricalRate(
            successes=1,
            trials=2,
            rate_bp=5000,
            interval_lower_bp=0,
            interval_upper_bp=10_001,
            interval_method="wilson_score_95",
        )
    with pytest.raises(CalibrationContractError, match="rate_bp must equal"):
        EmpiricalRate(
            successes=1,
            trials=2,
            rate_bp=4999,
            interval_lower_bp=0,
            interval_upper_bp=10_000,
            interval_method="wilson_score_95",
        )


def test_analyzer_calibration_profile_round_trip() -> None:
    profile = AnalyzerCalibrationProfile(
        header=_header("analyzer_calibration_profile"),
        profile_id="analyzer_callgraph",
        analyzer_id="callgraph",
        analyzer_version="2.1.0",
        partition=EvidencePartition.CALIBRATION,
        revision=4,
        total_uses=50,
        false_exact_classification_count=1,
        stale_failure_count=2,
        omission_rate=_rate(3, 50),
        record_cids=(_cid("rec-b"), _cid("rec-a")),
        language_keys=("python", "typescript"),
    )
    assert list(profile.record_cids) == sorted(profile.record_cids)
    restored = AnalyzerCalibrationProfile.from_dict(profile.to_dict())
    assert restored.profile_cid == profile.profile_cid


def test_model_route_calibration_profile_round_trip() -> None:
    profile = ModelRouteCalibrationProfile(
        header=_header("model_route_calibration_profile"),
        profile_id="route_standard",
        route_id="standard_v1",
        route_tier="standard",
        partition=EvidencePartition.CALIBRATION,
        revision=3,
        total_uses=100,
        escalation_count=5,
        retry_count=2,
        shadow_sample_count=10,
        success_rate=_rate(90, 100),
        escalation_rate_bp=500,
        retry_rate_bp=200,
        shadow_sample_rate_bp=1000,
        allows_empirical_exact_upgrade=False,
    )
    restored = ModelRouteCalibrationProfile.from_dict(profile.to_dict())
    assert restored == profile


# ---------------------------------------------------------------------------
# Bounded declarative rule DSL
# ---------------------------------------------------------------------------


def test_rule_dsl_rejects_unknown_operation_and_target() -> None:
    with pytest.raises(PolicyContractError, match="unsupported value"):
        DeclarativeRule(
            rule_id="bad_op",
            category=RuleCategory.CONTEXT_RANKING,
            operation="eval_expression",
            target_key="context_rank_key",
            value="importance",
        )
    with pytest.raises(PolicyContractError, match="not in the declarative rule allowlist"):
        _rule(target_key="shell_command")


def test_rule_dsl_rejects_imports_commands_and_templates() -> None:
    # Token-shaped values that still encode forbidden executable semantics.
    for value in ("import", "eval", "subprocess", "compile"):
        with pytest.raises(
            PolicyContractError,
            match="expressions, imports, commands, or templates",
        ):
            _rule(
                rule_id="bad_value",
                category=RuleCategory.CONTEXT_RANKING,
                operation=RuleOperation.SET_TOKEN,
                target_key="context_rank_key",
                value=value,
            )
    # Non-token executable / template strings also fail closed (token shape).
    for value in ("import os", "{{model}}", "${PATH}", "os.system('rm')"):
        with pytest.raises(PolicyContractError):
            _rule(
                rule_id="bad_value",
                category=RuleCategory.CONTEXT_RANKING,
                operation=RuleOperation.SET_TOKEN,
                target_key="context_rank_key",
                value=value,
            )


def test_rule_dsl_rejects_disabling_full_suite_fallback() -> None:
    with pytest.raises(
        PolicyContractError,
        match="full-suite fallback cannot be disabled",
    ):
        DeclarativeRule(
            rule_id="disable_fallback",
            category=RuleCategory.FULL_SUITE_FALLBACK,
            operation=RuleOperation.SET_BOOL,
            target_key="full_suite_fallback_enabled",
            value=False,
        )


def test_validate_rule_dsl_normalizes_and_sorts() -> None:
    rules = validate_rule_dsl(
        [
            _rule(rule_id="b_rule", value=300),
            _rule(rule_id="a_rule", value=200),
        ]
    )
    assert [rule.rule_id for rule in rules] == ["a_rule", "b_rule"]


def test_rule_proposal_round_trip() -> None:
    proposal = RuleProposal(
        header=_header("rule_proposal"),
        proposal_id="prop_shadow_up",
        current_policy_version="1.0.0",
        current_policy_cid=_cid("policy-v1"),
        proposed_rules=(_rule(),),
        supporting_audit_cids=(_cid("audit-2"), _cid("audit-1")),
        benefit_statement="Increase shadow sampling for opaque modules",
        safety_impact="No assurance reduction; full-suite fallback retained",
        scope_token="python",
        benchmark_cid=_cid("bench-1"),
        rollback_policy_cid=_cid("policy-v1"),
        calibration_profile_cids=(_cid("cal-1"),),
    )
    restored = RuleProposal.from_dict(proposal.to_dict())
    assert restored.proposal_cid == proposal.proposal_cid
    assert list(restored.supporting_audit_cids) == sorted(restored.supporting_audit_cids)


# ---------------------------------------------------------------------------
# Acceptance: candidates cannot self-authorize / reduce protected thresholds
# ---------------------------------------------------------------------------


def test_protected_threshold_reductions_detected() -> None:
    baseline = _thresholds()
    proposed = _thresholds(
        min_critical_omission_detection_bp=9_000,
        require_full_suite_fallback=False,
        max_critical_omission_accepted=1,
    )
    reduced = protected_threshold_reductions(baseline, proposed)
    assert "min_critical_omission_detection_bp" in reduced
    assert "require_full_suite_fallback" in reduced
    assert "max_critical_omission_accepted" in reduced


def test_threshold_reduction_without_authorization_fails() -> None:
    baseline = _thresholds()
    proposed = _thresholds(min_shadow_sample_rate_bp=0)
    with pytest.raises(
        PolicyContractError,
        match="cannot reduce protected thresholds without distinct authorization",
    ):
        assert_protected_threshold_change_authorized(
            baseline, proposed, authorization_cid=None
        )


def test_threshold_reduction_with_self_authorization_fails() -> None:
    baseline = _thresholds()
    proposed = _thresholds(min_shadow_sample_rate_bp=0)
    self_cid = _cid("candidate-self")
    with pytest.raises(
        PolicyContractError,
        match="cannot self-authorize|distinct authorization",
    ):
        assert_protected_threshold_change_authorized(
            baseline,
            proposed,
            authorization_cid=self_cid,
            forbidden_self_cids=(self_cid, _cid("proposal")),
        )


def test_candidate_rejects_unprotected_threshold_reduction() -> None:
    baseline = _thresholds()
    proposed = _thresholds(min_critical_omission_detection_bp=1_000)
    with pytest.raises(
        PolicyContractError,
        match="cannot reduce protected thresholds without distinct authorization",
    ):
        CompressionPolicyCandidate(
            header=_header("compression_policy_candidate"),
            candidate_id="cand_reduce",
            base_policy_cid=_cid("policy-v1"),
            base_policy_version="1.0.0",
            proposal_cid=_cid("proposal-1"),
            proposed_policy_cid=_cid("policy-v2"),
            proposed_protected_thresholds=proposed,
            baseline_protected_thresholds=baseline,
            evaluation_partition=EvidencePartition.HELD_OUT,
            external_authorization_cid=None,
        )


def test_candidate_rejects_using_proposal_as_authorization() -> None:
    baseline = _thresholds()
    proposed = _thresholds(min_critical_omission_detection_bp=1_000)
    proposal = _cid("proposal-1")
    with pytest.raises(
        PolicyContractError,
        match="self-authorize|distinct authorization",
    ):
        CompressionPolicyCandidate(
            header=_header("compression_policy_candidate"),
            candidate_id="cand_self_auth",
            base_policy_cid=_cid("policy-v1"),
            base_policy_version="1.0.0",
            proposal_cid=proposal,
            proposed_policy_cid=_cid("policy-v2"),
            proposed_protected_thresholds=proposed,
            baseline_protected_thresholds=baseline,
            evaluation_partition=EvidencePartition.HELD_OUT,
            external_authorization_cid=proposal,
        )


def test_candidate_accepts_distinct_external_authorization_for_reduction() -> None:
    baseline = _thresholds()
    proposed = _thresholds(min_shadow_sample_rate_bp=50)
    candidate = CompressionPolicyCandidate(
        header=_header("compression_policy_candidate"),
        candidate_id="cand_authorized",
        base_policy_cid=_cid("policy-v1"),
        base_policy_version="1.0.0",
        proposal_cid=_cid("proposal-1"),
        proposed_policy_cid=_cid("policy-v2"),
        proposed_protected_thresholds=proposed,
        baseline_protected_thresholds=baseline,
        evaluation_partition=EvidencePartition.HELD_OUT,
        external_authorization_cid=_cid("human-auth-1"),
    )
    restored = CompressionPolicyCandidate.from_dict(candidate.to_dict())
    assert restored.candidate_cid == candidate.candidate_cid


def test_candidate_without_threshold_reduction_needs_no_authorization() -> None:
    thresholds = _thresholds()
    candidate = CompressionPolicyCandidate(
        header=_header("compression_policy_candidate"),
        candidate_id="cand_safe",
        base_policy_cid=_cid("policy-v1"),
        base_policy_version="1.0.0",
        proposal_cid=_cid("proposal-1"),
        proposed_policy_cid=_cid("policy-v2"),
        proposed_protected_thresholds=thresholds,
        baseline_protected_thresholds=thresholds,
        evaluation_partition=EvidencePartition.HELD_OUT,
        external_authorization_cid=None,
    )
    assert candidate.external_authorization_cid is None


def test_promotion_receipt_rejects_self_authorization() -> None:
    candidate = _cid("candidate-1")
    with pytest.raises(PolicyContractError, match="cannot self-authorize"):
        CompressionPolicyPromotionReceipt(
            header=_header("compression_policy_promotion_receipt"),
            receipt_id="promo_1",
            candidate_cid=candidate,
            evaluation_report_cid=_cid("eval-1"),
            authorization_cid=candidate,
            proposal_cid=_cid("proposal-1"),
            previous_policy_cid=_cid("policy-v1"),
            previous_policy_version="1.0.0",
            promoted_policy_cid=_cid("policy-v2"),
            promoted_policy_version="1.1.0",
            rollback_policy_cid=_cid("policy-v1"),
            cas_expected_version="1.0.0",
        )


def test_promotion_receipt_rejects_evaluation_as_authorization() -> None:
    evaluation = _cid("eval-1")
    with pytest.raises(PolicyContractError, match="cannot self-authorize"):
        CompressionPolicyPromotionReceipt(
            header=_header("compression_policy_promotion_receipt"),
            receipt_id="promo_2",
            candidate_cid=_cid("candidate-1"),
            evaluation_report_cid=evaluation,
            authorization_cid=evaluation,
            proposal_cid=_cid("proposal-1"),
            previous_policy_cid=_cid("policy-v1"),
            previous_policy_version="1.0.0",
            promoted_policy_cid=_cid("policy-v2"),
            promoted_policy_version="1.1.0",
            rollback_policy_cid=_cid("policy-v1"),
            cas_expected_version="1.0.0",
        )


def test_promotion_receipt_round_trip_with_distinct_authorization() -> None:
    receipt = CompressionPolicyPromotionReceipt(
        header=_header("compression_policy_promotion_receipt"),
        receipt_id="promo_ok",
        candidate_cid=_cid("candidate-1"),
        evaluation_report_cid=_cid("eval-1"),
        authorization_cid=_cid("human-auth-board"),
        proposal_cid=_cid("proposal-1"),
        previous_policy_cid=_cid("policy-v1"),
        previous_policy_version="1.0.0",
        promoted_policy_cid=_cid("policy-v2"),
        promoted_policy_version="1.1.0",
        rollback_policy_cid=_cid("policy-v1"),
        cas_expected_version="1.0.0",
    )
    restored = CompressionPolicyPromotionReceipt.from_dict(receipt.to_dict())
    assert restored.receipt_cid == receipt.receipt_cid


# ---------------------------------------------------------------------------
# CompressionPolicy and evaluation report
# ---------------------------------------------------------------------------


def test_compression_policy_requires_nonempty_acceptance_matrix() -> None:
    with pytest.raises(PolicyContractError, match="must not be empty"):
        CompressionPolicy(
            header=_header("compression_policy"),
            policy_id="default",
            policy_version="1.0.0",
            task_class_acceptance_matrix=(),
            protected_thresholds=_thresholds(),
        )


def test_compression_policy_requires_full_suite_fallback() -> None:
    with pytest.raises(
        PolicyContractError, match="require_full_suite_fallback must be true"
    ):
        # Construct thresholds via from_dict would also fail on allow flags;
        # force by temporarily building a valid object then replacing is hard.
        # Direct construction with require_full_suite_fallback=False:
        bad = ProtectedThresholds(
            min_critical_omission_detection_bp=9_500,
            max_critical_omission_accepted=0,
            min_median_context_reduction_bp=5_000,
            max_accepted_regression_bp=0,
            min_shadow_sample_rate_bp=100,
            require_full_suite_fallback=False,
            allow_heuristic_as_exact=False,
            allow_assurance_reduction=False,
        )
        CompressionPolicy(
            header=_header("compression_policy"),
            policy_id="default",
            policy_version="1.0.0",
            task_class_acceptance_matrix=(_acceptance(),),
            protected_thresholds=bad,
        )


def test_compression_policy_acceptance_lookup_and_round_trip() -> None:
    policy = CompressionPolicy(
        header=_header("compression_policy"),
        policy_id="default",
        policy_version="1.0.0",
        task_class_acceptance_matrix=(
            _acceptance("schema_migration", "high", require_human_review=True, require_proofs=True),
            _acceptance("local_bug", "low"),
        ),
        protected_thresholds=_thresholds(),
        rules=(_rule(),),
        calibration_profile_cids=(_cid("cal-1"),),
    )
    assert policy.acceptance_for("local_bug", "low") is not None
    assert policy.acceptance_for("unknown_task", "low") is None
    # Sorted by task/risk
    assert [row.task_class for row in policy.task_class_acceptance_matrix] == [
        "local_bug",
        "schema_migration",
    ]
    restored = CompressionPolicy.from_dict(policy.to_dict())
    assert restored.policy_cid == policy.policy_cid


def test_evaluation_report_requires_held_out_partition() -> None:
    with pytest.raises(PolicyContractError, match="must be held_out"):
        RuleEvaluationReport(
            header=_header("rule_evaluation_report"),
            report_id="eval_1",
            candidate_cid=_cid("cand-1"),
            held_out_benchmark_cid=_cid("bench-1"),
            baseline_policy_cid=_cid("policy-v1"),
            partition=EvidencePartition.CALIBRATION,
            verdict=EvaluationVerdict.PASS,
            critical_omission_detection_bp=9_600,
            stale_rejection_rate_bp=10_000,
            accepted_regression_bp=0,
            high_risk_assurance_reduced=False,
            declared_thresholds_applied=True,
        )


def test_evaluation_report_pass_cannot_reduce_assurance() -> None:
    with pytest.raises(
        PolicyContractError, match="high_risk_assurance_reduced"
    ):
        RuleEvaluationReport(
            header=_header("rule_evaluation_report"),
            report_id="eval_2",
            candidate_cid=_cid("cand-1"),
            held_out_benchmark_cid=_cid("bench-1"),
            baseline_policy_cid=_cid("policy-v1"),
            partition=EvidencePartition.HELD_OUT,
            verdict=EvaluationVerdict.PASS,
            critical_omission_detection_bp=9_600,
            stale_rejection_rate_bp=10_000,
            accepted_regression_bp=0,
            high_risk_assurance_reduced=True,
            declared_thresholds_applied=True,
        )


def test_evaluation_report_round_trip() -> None:
    report = RuleEvaluationReport(
        header=_header("rule_evaluation_report"),
        report_id="eval_ok",
        candidate_cid=_cid("cand-1"),
        held_out_benchmark_cid=_cid("bench-1"),
        baseline_policy_cid=_cid("policy-v1"),
        partition=EvidencePartition.HELD_OUT,
        verdict=EvaluationVerdict.PASS,
        critical_omission_detection_bp=9_600,
        stale_rejection_rate_bp=10_000,
        accepted_regression_bp=0,
        high_risk_assurance_reduced=False,
        declared_thresholds_applied=True,
    )
    restored = RuleEvaluationReport.from_dict(report.to_dict())
    assert restored.report_cid == report.report_cid


# ---------------------------------------------------------------------------
# Fail-closed identity / private data / floats
# ---------------------------------------------------------------------------


def test_unknown_fields_fail_closed_on_policy() -> None:
    policy = CompressionPolicy(
        header=_header("compression_policy"),
        policy_id="default",
        policy_version="1.0.0",
        task_class_acceptance_matrix=(_acceptance(),),
        protected_thresholds=_thresholds(),
    )
    payload = policy.to_dict()
    payload["extra"] = True
    with pytest.raises(PolicyContractError, match="fields must be exactly"):
        CompressionPolicy.from_dict(payload)


def test_forged_policy_cid_fails_closed() -> None:
    policy = CompressionPolicy(
        header=_header("compression_policy"),
        policy_id="default",
        policy_version="1.0.0",
        task_class_acceptance_matrix=(_acceptance(),),
        protected_thresholds=_thresholds(),
    )
    payload = policy.to_dict()
    payload["policy_cid"] = _cid("forged")
    with pytest.raises(PolicyContractError, match="does not verify"):
        CompressionPolicy.from_dict(payload)


def test_floats_fail_closed_in_metadata() -> None:
    with pytest.raises(SemanticGovernorBaseError, match="float|DAG-JSON"):
        CompressionPolicy(
            header=_header("compression_policy", metadata={"score": 0.5}),
            policy_id="default",
            policy_version="1.0.0",
            task_class_acceptance_matrix=(_acceptance(),),
            protected_thresholds=_thresholds(),
        )


def test_private_and_model_authority_fail_closed() -> None:
    with pytest.raises(SemanticGovernorBaseError, match="private data|model-written"):
        CompressionPolicy(
            header=_header("compression_policy", metadata={"api_key": "secret"}),
            policy_id="default",
            policy_version="1.0.0",
            task_class_acceptance_matrix=(_acceptance(),),
            protected_thresholds=_thresholds(),
        )
    with pytest.raises(SemanticGovernorBaseError, match="model-written|authority"):
        RuleProposal(
            header=_header("rule_proposal", metadata={"self_authorized": True}),
            proposal_id="prop_bad",
            current_policy_version="1.0.0",
            current_policy_cid=_cid("policy-v1"),
            proposed_rules=(_rule(),),
            supporting_audit_cids=(_cid("audit-1"),),
            benefit_statement="x",
            safety_impact="y",
            scope_token="python",
            benchmark_cid=_cid("bench-1"),
            rollback_policy_cid=_cid("policy-v1"),
        )


def test_candidate_rejects_non_held_out_partition() -> None:
    thresholds = _thresholds()
    with pytest.raises(PolicyContractError, match="must be held_out"):
        CompressionPolicyCandidate(
            header=_header("compression_policy_candidate"),
            candidate_id="cand_dev",
            base_policy_cid=_cid("policy-v1"),
            base_policy_version="1.0.0",
            proposal_cid=_cid("proposal-1"),
            proposed_policy_cid=_cid("policy-v2"),
            proposed_protected_thresholds=thresholds,
            baseline_protected_thresholds=thresholds,
            evaluation_partition=EvidencePartition.DEVELOPMENT,
        )
