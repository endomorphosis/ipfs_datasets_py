"""Unit vectors for deterministic held-out partition and qualification (AAE-033).

Acceptance focus:

* Partitions are deterministic and leakage-resistant.
* Evaluation qualification requires unmutated, diagnosis, development,
  held-out, unrelated, cost, false-positive, overconstraint, regression,
  and safety evidence.
* Candidate-generating mutants never enter held-out.
* One-mutant overfit and mock bypass fail closed.
* No production policy mutation.
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
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.remediation_contracts import (
    EvaluationPartition,
    EvaluationVerdict,
    GapRemediationPlan,
    PartitionEvaluationEvidence,
    RejectionReason,
    RemediationEvaluationReport,
    RemediationPlanStatus,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.held_out import (
    DEFAULT_DEVELOPMENT_RATIO_BP,
    DEFAULT_HELD_OUT_RATIO_BP,
    GENERATOR_ID,
    HELD_OUT_POLICY_EVIDENCE,
    MUTANT_CORPUS_PARTITIONS,
    PARTITION_MUTANTS_INTERFACE,
    QUALIFY_REMEDIATION_EVALUATION_INTERFACE,
    REQUIRED_EVALUATION_PARTITIONS,
    HeldOutPolicyError,
    MutantCorpusPartition,
    MutantPartitionPlan,
    QualificationDisposition,
    RemediationQualificationResult,
    assert_partition_leakage_free,
    mutant_corpus_partitions,
    partition_mutants,
    qualification_dispositions,
    qualify_remediation_evaluation,
    required_evaluation_partitions,
    verify_mutant_partition_plan_identity,
    verify_remediation_qualification_identity,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


REPO_ID = "repository:sha256:test-repo-identity"
REPO_STATE = _cid("repo-state")


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


def _mutant(
    mutant_id: str,
    *,
    operator_id: str = "authz_invert",
    target_id: str = "mod_fn",
    used_for_candidate_generation: bool = False,
) -> dict[str, object]:
    return {
        "mutant_id": mutant_id,
        "candidate_cid": _cid(f"cand-{mutant_id}"),
        "operator_id": operator_id,
        "target_id": target_id,
        "used_for_candidate_generation": used_for_candidate_generation,
    }


def _partition_evidence(
    partition: EvaluationPartition | str,
    *,
    passed: bool = True,
    mutant_ids: tuple[str, ...] = (),
    killed_count: int = 0,
) -> PartitionEvaluationEvidence:
    return PartitionEvaluationEvidence(
        partition=partition,
        passed=passed,
        evidence_cids=(_cid(f"ev-{partition}"),),
        mutant_ids=mutant_ids,
        killed_count=killed_count,
        survived_count=0 if passed else 1,
        notes=None,
    )


def _all_partition_evidence(
    *,
    diagnosis_ids: tuple[str, ...] = ("mut_diag_1",),
    development_ids: tuple[str, ...] = ("mut_dev_1",),
    held_out_ids: tuple[str, ...] = ("mut_hold_1",),
    fail: frozenset[str] | None = None,
) -> tuple[PartitionEvaluationEvidence, ...]:
    fail = fail or frozenset()
    specs = (
        (EvaluationPartition.UNMUTATED, ()),
        (EvaluationPartition.DIAGNOSIS, diagnosis_ids),
        (EvaluationPartition.DEVELOPMENT, development_ids),
        (EvaluationPartition.HELD_OUT, held_out_ids),
        (EvaluationPartition.UNRELATED, ()),
        (EvaluationPartition.PERFORMANCE_COST, ()),
        (EvaluationPartition.FALSE_POSITIVE, ()),
        (EvaluationPartition.OVERCONSTRAINT, ()),
        (EvaluationPartition.REGRESSION, ()),
        (EvaluationPartition.SAFETY, ()),
    )
    evidence: list[PartitionEvaluationEvidence] = []
    for partition, mutant_ids in specs:
        value = partition.value if isinstance(partition, EvaluationPartition) else partition
        passed = value not in fail
        killed = len(mutant_ids) if passed and mutant_ids else 0
        evidence.append(
            _partition_evidence(
                partition,
                passed=passed,
                mutant_ids=mutant_ids,
                killed_count=killed,
            )
        )
    return tuple(evidence)


def _plan_for_eval() -> GapRemediationPlan:
    return GapRemediationPlan(
        header=_header("gap_remediation_plan"),
        plan_id="plan_authz_1",
        plan_status=RemediationPlanStatus.DRAFT,
        summary="add test for inverted authorization guard",
        gap_cids=(_cid("gap-1"),),
        candidate_test_cids=(_cid("cand-test-1"),),
        candidate_proof_cids=(),
        candidate_policy_cids=(),
        candidate_analyzer_cids=(),
        requires_held_out_evaluation=True,
        evaluation_report_cid=None,
        notes=None,
        metadata={},
    )


def _evaluation(**overrides: object) -> RemediationEvaluationReport:
    plan = _plan_for_eval()
    fields: dict[str, object] = {
        "header": _header("remediation_evaluation_report"),
        "report_id": "eval_authz_1",
        "plan_cid": plan.plan_cid,
        "candidate_cids": (_cid("cand-test-1"),),
        "verdict": EvaluationVerdict.QUALIFIED,
        "partition_evidence": _all_partition_evidence(),
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


def _sample_mutants() -> list[dict[str, object]]:
    return [
        _mutant("mut_diag_1"),
        _mutant("mut_dev_1"),
        _mutant("mut_dev_2"),
        _mutant("mut_hold_1"),
        _mutant("mut_hold_2"),
        _mutant("mut_hold_3"),
        _mutant("mut_unrelated_1", operator_id="other_op", target_id="other_tgt"),
        _mutant("mut_gen_1", used_for_candidate_generation=True),
    ]


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


def test_closed_vocabularies_cover_plan_section_10() -> None:
    corpus = mutant_corpus_partitions()
    assert corpus == MUTANT_CORPUS_PARTITIONS
    assert corpus == ("diagnosis", "development", "held_out")
    required = required_evaluation_partitions()
    assert required == REQUIRED_EVALUATION_PARTITIONS
    assert len(required) == 10
    for name in (
        "unmutated",
        "diagnosis",
        "development",
        "held_out",
        "unrelated",
        "performance_cost",
        "false_positive",
        "overconstraint",
        "regression",
        "safety",
    ):
        assert name in required
    assert "qualified" in qualification_dispositions()
    assert "rejected" in qualification_dispositions()


# ---------------------------------------------------------------------------
# partition_mutants — deterministic and leakage-resistant
# ---------------------------------------------------------------------------


def test_partition_mutants_is_deterministic() -> None:
    mutants = _sample_mutants()
    header = _header("mutation_campaign_plan")
    first = partition_mutants(
        mutants,
        ("mut_diag_1",),
        header=header,
        campaign_id="camp_a",
        partition_seed=7,
    )
    second = partition_mutants(
        mutants,
        ("mut_diag_1",),
        header=header,
        campaign_id="camp_a",
        partition_seed=7,
    )
    assert first.plan_cid == second.plan_cid
    assert first.diagnosis_mutant_ids == second.diagnosis_mutant_ids
    assert first.development_mutant_ids == second.development_mutant_ids
    assert first.held_out_mutant_ids == second.held_out_mutant_ids
    assert first.membership() == second.membership()


def test_partition_mutants_changes_with_seed() -> None:
    mutants = [
        _mutant(f"mut_{index:02d}")
        for index in range(20)
    ]
    header = _header("mutation_campaign_plan")
    a = partition_mutants(
        mutants,
        ("mut_00",),
        header=header,
        campaign_id="camp_seed",
        partition_seed=1,
    )
    b = partition_mutants(
        mutants,
        ("mut_00",),
        header=header,
        campaign_id="camp_seed",
        partition_seed=2,
    )
    # With 19 remainder mutants, seeds almost always disagree; assert not identical plans.
    assert a.plan_cid != b.plan_cid or (
        a.development_mutant_ids != b.development_mutant_ids
        or a.held_out_mutant_ids != b.held_out_mutant_ids
    )


def test_partition_mutants_is_leakage_resistant() -> None:
    plan = partition_mutants(
        _sample_mutants(),
        ("mut_diag_1",),
        header=_header("mutation_campaign_plan"),
        campaign_id="camp_leak",
        partition_seed=3,
    )
    assert_partition_leakage_free(plan)
    assert plan.leakage_resistant is True
    diagnosis = set(plan.diagnosis_mutant_ids)
    development = set(plan.development_mutant_ids)
    held_out = set(plan.held_out_mutant_ids)
    assert diagnosis.isdisjoint(development)
    assert diagnosis.isdisjoint(held_out)
    assert development.isdisjoint(held_out)
    assert diagnosis == {"mut_diag_1"}
    # Candidate-generating mutant never enters held-out.
    assert "mut_gen_1" not in held_out
    gen_member = next(item for item in plan.members if item.mutant_id == "mut_gen_1")
    assert gen_member.partition == MutantCorpusPartition.DEVELOPMENT.value
    assert gen_member.used_for_candidate_generation is True


def test_partition_mutants_requires_diagnosis_subset() -> None:
    with pytest.raises(HeldOutPolicyError, match="subset"):
        partition_mutants(
            [_mutant("mut_a")],
            ("mut_missing",),
            header=_header("mutation_campaign_plan"),
        )


def test_partition_mutants_rejects_duplicate_mutant_ids() -> None:
    with pytest.raises(HeldOutPolicyError, match="duplicate"):
        partition_mutants(
            [_mutant("mut_a"), _mutant("mut_a")],
            ("mut_a",),
            header=_header("mutation_campaign_plan"),
            require_held_out=False,
        )


def test_partition_mutants_requires_held_out_when_configured() -> None:
    # All non-diagnosis mutants are candidate-generating → empty held-out.
    mutants = [
        _mutant("mut_diag_1"),
        _mutant("mut_gen_1", used_for_candidate_generation=True),
        _mutant("mut_gen_2", used_for_candidate_generation=True),
    ]
    with pytest.raises(HeldOutPolicyError, match="held_out partition is empty"):
        partition_mutants(
            mutants,
            ("mut_diag_1",),
            header=_header("mutation_campaign_plan"),
            require_held_out=True,
        )


def test_partition_mutants_allows_empty_held_out_when_not_required() -> None:
    plan = partition_mutants(
        [_mutant("mut_diag_1")],
        ("mut_diag_1",),
        header=_header("mutation_campaign_plan"),
        require_held_out=False,
    )
    assert plan.diagnosis_mutant_ids == ("mut_diag_1",)
    assert plan.development_mutant_ids == ()
    assert plan.held_out_mutant_ids == ()


def test_partition_mutants_round_trip_identity() -> None:
    plan = partition_mutants(
        _sample_mutants(),
        ("mut_diag_1",),
        header=_header("mutation_campaign_plan"),
        campaign_id="camp_rt",
        partition_seed=11,
    )
    restored = MutantPartitionPlan.from_dict(plan.to_dict())
    assert restored.plan_cid == plan.plan_cid
    assert verify_mutant_partition_plan_identity(restored) == plan.plan_cid
    assert restored.header.versions.generator.generator_id == GENERATOR_ID
    assert restored.metadata["evidence"] == HELD_OUT_POLICY_EVIDENCE
    assert restored.metadata["production_policy_changed"] is False


def test_partition_ratios_must_sum_to_10000() -> None:
    with pytest.raises(HeldOutPolicyError, match="10000"):
        partition_mutants(
            _sample_mutants(),
            ("mut_diag_1",),
            header=_header("mutation_campaign_plan"),
            development_ratio_bp=2000,
            held_out_ratio_bp=2000,
        )


def test_default_ratios_are_stable() -> None:
    assert DEFAULT_DEVELOPMENT_RATIO_BP + DEFAULT_HELD_OUT_RATIO_BP == 10_000


# ---------------------------------------------------------------------------
# qualify_remediation_evaluation — required evidence set
# ---------------------------------------------------------------------------


def test_qualify_accepts_complete_qualified_evaluation() -> None:
    plan = partition_mutants(
        [
            _mutant("mut_diag_1"),
            _mutant("mut_dev_1"),
            _mutant("mut_hold_1"),
        ],
        ("mut_diag_1",),
        header=_header("mutation_campaign_plan"),
        campaign_id="camp_q",
        partition_seed=0,
        # Force remaining into both partitions via seed-stable corpus of 2.
        development_ratio_bp=5_000,
        held_out_ratio_bp=5_000,
    )
    # Align evaluation mutant ids with plan membership.
    evaluation = _evaluation(
        partition_evidence=_all_partition_evidence(
            diagnosis_ids=plan.diagnosis_mutant_ids,
            development_ids=plan.development_mutant_ids or ("mut_dev_1",),
            held_out_ids=plan.held_out_mutant_ids or ("mut_hold_1",),
        )
    )
    # If plan empty-side happened, rebuild a richer corpus.
    if not plan.development_mutant_ids or not plan.held_out_mutant_ids:
        richer = [
            _mutant("mut_diag_1"),
            *[_mutant(f"mut_x{i:02d}") for i in range(12)],
        ]
        plan = partition_mutants(
            richer,
            ("mut_diag_1",),
            header=_header("mutation_campaign_plan"),
            campaign_id="camp_q2",
            partition_seed=0,
        )
        evaluation = _evaluation(
            partition_evidence=_all_partition_evidence(
                diagnosis_ids=plan.diagnosis_mutant_ids,
                development_ids=plan.development_mutant_ids[:1],
                held_out_ids=plan.held_out_mutant_ids[:1],
            )
        )

    result = qualify_remediation_evaluation(evaluation, partition_plan=plan)
    assert result.disposition == QualificationDisposition.QUALIFIED.value
    assert result.verdict == EvaluationVerdict.QUALIFIED.value
    assert result.required_partitions_present is True
    assert result.unmutated_suite_passed is True
    assert result.diagnosis_killed is True
    assert result.development_killed is True
    assert result.held_out_killed is True
    assert result.unrelated_behavior_preserved is True
    assert result.safety_preserved is True
    assert result.regression_detected is False
    assert result.overconstraint_detected is False
    assert result.false_positive_detected is False
    assert result.cost_within_budget is True
    assert result.partition_leakage_detected is False
    assert result.production_policy_changed is False
    assert result.rejection_reasons == ()
    assert result.missing_partitions == ()
    assert result.failed_partitions == ()
    assert result.metadata["evidence"] == HELD_OUT_POLICY_EVIDENCE
    assert result.header.versions.generator.interface_id == (
        QUALIFY_REMEDIATION_EVALUATION_INTERFACE
    )


def test_qualify_requires_all_ten_partitions() -> None:
    # Drop safety evidence.
    evidence = [
        item
        for item in _all_partition_evidence()
        if item.partition != EvaluationPartition.SAFETY.value
    ]
    # Keep regression and overconstraint (contract-required) and remove safety.
    evaluation = _evaluation(partition_evidence=tuple(evidence))
    result = qualify_remediation_evaluation(evaluation)
    assert result.disposition == QualificationDisposition.REJECTED.value
    assert EvaluationPartition.SAFETY.value in result.missing_partitions
    assert not result.required_partitions_present
    assert RejectionReason.HELD_OUT_FAILURE.value in result.rejection_reasons


def test_qualify_rejects_missing_held_out_kill() -> None:
    evaluation = _evaluation(
        held_out_killed=False,
        verdict=EvaluationVerdict.REJECTED,
        rejection_reasons=(RejectionReason.HELD_OUT_FAILURE,),
        partition_evidence=_all_partition_evidence(
            fail=frozenset({EvaluationPartition.HELD_OUT.value})
        ),
    )
    result = qualify_remediation_evaluation(evaluation)
    assert result.disposition == QualificationDisposition.REJECTED.value
    assert result.held_out_killed is False
    assert RejectionReason.HELD_OUT_FAILURE.value in result.rejection_reasons
    assert (
        RejectionReason.OVERFIT_IMPLEMENTATION_ASSERTION.value
        in result.rejection_reasons
    )


def test_qualify_rejects_regression() -> None:
    evaluation = _evaluation(
        regression_detected=True,
        verdict=EvaluationVerdict.REGRESSION,
        rejection_reasons=(RejectionReason.REGRESSION,),
        partition_evidence=_all_partition_evidence(
            fail=frozenset({EvaluationPartition.REGRESSION.value})
        ),
    )
    result = qualify_remediation_evaluation(evaluation)
    assert result.disposition == QualificationDisposition.REJECTED.value
    assert result.verdict == EvaluationVerdict.REGRESSION.value
    assert result.regression_detected is True
    assert RejectionReason.REGRESSION.value in result.rejection_reasons


def test_qualify_rejects_overconstraint() -> None:
    evaluation = _evaluation(
        overconstraint_detected=True,
        verdict=EvaluationVerdict.OVERCONSTRAINT,
        rejection_reasons=(RejectionReason.OVERCONSTRAINT,),
        partition_evidence=_all_partition_evidence(
            fail=frozenset({EvaluationPartition.OVERCONSTRAINT.value})
        ),
    )
    result = qualify_remediation_evaluation(evaluation)
    assert result.disposition == QualificationDisposition.REJECTED.value
    assert result.verdict == EvaluationVerdict.OVERCONSTRAINT.value
    assert RejectionReason.OVERCONSTRAINT.value in result.rejection_reasons


def test_qualify_rejects_false_positive() -> None:
    evaluation = _evaluation(
        false_positive_detected=True,
        verdict=EvaluationVerdict.REJECTED,
        rejection_reasons=(RejectionReason.FALSE_POSITIVE,),
        partition_evidence=_all_partition_evidence(
            fail=frozenset({EvaluationPartition.FALSE_POSITIVE.value})
        ),
    )
    result = qualify_remediation_evaluation(evaluation)
    assert result.disposition == QualificationDisposition.REJECTED.value
    assert RejectionReason.FALSE_POSITIVE.value in result.rejection_reasons


def test_qualify_rejects_unmutated_failure() -> None:
    evaluation = _evaluation(
        unmutated_suite_passed=False,
        verdict=EvaluationVerdict.REJECTED,
        rejection_reasons=(RejectionReason.UNMUTATED_SUITE_FAILED,),
        partition_evidence=_all_partition_evidence(
            fail=frozenset({EvaluationPartition.UNMUTATED.value})
        ),
    )
    result = qualify_remediation_evaluation(evaluation)
    assert result.disposition == QualificationDisposition.REJECTED.value
    assert RejectionReason.UNMUTATED_SUITE_FAILED.value in result.rejection_reasons


def test_qualify_rejects_diagnosis_not_killed() -> None:
    evaluation = _evaluation(
        diagnosis_killed=False,
        verdict=EvaluationVerdict.REJECTED,
        rejection_reasons=(RejectionReason.DIAGNOSIS_NOT_KILLED,),
        partition_evidence=_all_partition_evidence(
            fail=frozenset({EvaluationPartition.DIAGNOSIS.value})
        ),
    )
    result = qualify_remediation_evaluation(evaluation)
    assert result.disposition == QualificationDisposition.REJECTED.value
    assert RejectionReason.DIAGNOSIS_NOT_KILLED.value in result.rejection_reasons


def test_qualify_rejects_safety_weakening() -> None:
    evaluation = _evaluation(
        safety_preserved=False,
        verdict=EvaluationVerdict.SAFETY_WEAKENED,
        rejection_reasons=(RejectionReason.SAFETY_WEAKENING,),
        partition_evidence=_all_partition_evidence(
            fail=frozenset({EvaluationPartition.SAFETY.value})
        ),
    )
    result = qualify_remediation_evaluation(evaluation)
    assert result.disposition == QualificationDisposition.REJECTED.value
    assert result.verdict == EvaluationVerdict.SAFETY_WEAKENED.value
    assert RejectionReason.SAFETY_WEAKENING.value in result.rejection_reasons


def test_qualify_rejects_unrelated_behavior_breakage() -> None:
    evaluation = _evaluation(
        unrelated_behavior_preserved=False,
        verdict=EvaluationVerdict.REJECTED,
        rejection_reasons=(RejectionReason.UNRELATED_BEHAVIOR_BROKEN,),
        partition_evidence=_all_partition_evidence(
            fail=frozenset({EvaluationPartition.UNRELATED.value})
        ),
    )
    result = qualify_remediation_evaluation(evaluation)
    assert result.disposition == QualificationDisposition.REJECTED.value
    assert RejectionReason.UNRELATED_BEHAVIOR_BROKEN.value in result.rejection_reasons


def test_qualify_rejects_cost_exceeded() -> None:
    evaluation = _evaluation(cost_delta_basis_points=5_000)
    result = qualify_remediation_evaluation(evaluation, max_cost_delta_bp=100)
    assert result.disposition == QualificationDisposition.REJECTED.value
    assert result.cost_within_budget is False
    assert result.verdict == EvaluationVerdict.COST_EXCEEDED.value
    assert RejectionReason.UNAPPROVED_COST_INCREASE.value in result.rejection_reasons


def test_qualify_rejects_mock_bypass_reason() -> None:
    evaluation = _evaluation(
        verdict=EvaluationVerdict.REJECTED,
        rejection_reasons=(RejectionReason.MOCK_BYPASS,),
        # Keep flags green so contract accepts non-qualified with mock reason;
        # diagnosis/held_out still true but verdict rejected.
        diagnosis_killed=True,
        held_out_killed=True,
        unmutated_suite_passed=True,
    )
    # RemediationEvaluationReport requires non-qualified to have reasons and
    # forbids qualified invariants only for qualified verdict — good.
    result = qualify_remediation_evaluation(evaluation)
    assert result.disposition == QualificationDisposition.REJECTED.value
    assert RejectionReason.MOCK_BYPASS.value in result.rejection_reasons


def test_qualify_detects_partition_leakage() -> None:
    plan = partition_mutants(
        [
            _mutant("mut_diag_1"),
            *[_mutant(f"mut_z{i:02d}") for i in range(10)],
        ],
        ("mut_diag_1",),
        header=_header("mutation_campaign_plan"),
        campaign_id="camp_leak_eval",
        partition_seed=5,
    )
    # Put diagnosis mutant into held-out evidence → leakage.
    evaluation = _evaluation(
        partition_evidence=_all_partition_evidence(
            diagnosis_ids=plan.diagnosis_mutant_ids,
            development_ids=plan.development_mutant_ids[:1] or ("mut_z00",),
            held_out_ids=plan.diagnosis_mutant_ids,  # LEAK
        )
    )
    result = qualify_remediation_evaluation(evaluation, partition_plan=plan)
    assert result.disposition == QualificationDisposition.REJECTED.value
    assert result.partition_leakage_detected is True
    assert RejectionReason.HELD_OUT_FAILURE.value in result.rejection_reasons
    assert result.notes is not None
    assert "leaked" in result.notes or "leakage" in result.notes


def test_qualify_round_trip_identity() -> None:
    evaluation = _evaluation()
    result = qualify_remediation_evaluation(evaluation)
    restored = RemediationQualificationResult.from_dict(result.to_dict())
    assert restored.result_cid == result.result_cid
    assert verify_remediation_qualification_identity(restored) == result.result_cid


def test_qualify_never_sets_production_policy_changed() -> None:
    result = qualify_remediation_evaluation(_evaluation())
    assert result.production_policy_changed is False
    assert result.metadata["production_policy_changed"] is False


def test_forged_qualification_identity_rejected() -> None:
    result = qualify_remediation_evaluation(_evaluation())
    payload = result.to_dict()
    payload["result_cid"] = _cid("forged")
    with pytest.raises(HeldOutPolicyError, match="identity"):
        RemediationQualificationResult.from_dict(payload)


def test_interfaces_are_versioned_pins() -> None:
    assert PARTITION_MUTANTS_INTERFACE.endswith("@1")
    assert QUALIFY_REMEDIATION_EVALUATION_INTERFACE.endswith("@1")
    assert "@" in PARTITION_MUTANTS_INTERFACE
    assert len(required_evaluation_partitions()) == 10
