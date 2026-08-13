"""Unit tests for empirical calibration updates (SCG-016).

Acceptance criteria enforced here:

* Simulated outputs are excluded from live quality.
* Concurrent / replayed inputs are idempotent.
* False exact and stale failures remain explicit counters.
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
from ipfs_datasets_py.logic.software_contracts.semantic_governor.calibration import (
    MERGE_CALIBRATION_PROFILES_INTERFACE,
    UPDATE_CALIBRATION_INTERFACE,
    CalibrationDisposition,
    CalibrationError,
    CalibrationKind,
    CalibrationObservation,
    ComparativeOutcome,
    build_empirical_rate,
    calibration_dispositions,
    calibration_kinds,
    comparative_outcomes,
    merge_calibration_profiles,
    merge_calibration_profiles_interface_id,
    observation_from_outcome,
    update_calibration,
    update_calibration_interface_id,
    wilson_score_interval_bp,
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


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _generator(**overrides: object) -> GeneratorIdentity:
    fields = {
        "generator_id": "calibration_tests",
        "generator_version": "1.0.0",
        "interface_id": "update_calibration@1",
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
        "tool_ids": ("calibration.v1",),
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
        "metadata": {"track": "calibration"},
    }
    fields.update(overrides)
    return GovernorArtifactHeader(**fields)  # type: ignore[arg-type]


def _rate(successes: int, trials: int) -> EmpiricalRate:
    return build_empirical_rate(successes, trials)


def _case(**overrides: object) -> CompressionAuditCase:
    fields: dict[str, object] = {
        "header": _header("compression_audit_case"),
        "case_id": "case_local_bug",
        "task_id": "task_local_bug_001",
        "task_class": "local_bug",
        "risk_class": "low",
        "coverage_manifest_cid": _cid("manifest"),
        "sufficiency_claim_cid": _cid("claim"),
        "decision_cid": _cid("decision"),
        "run_receipt_cid": None,
        "expansion_plan_cid": None,
        "omission_evidence_cid": None,
        "shadow_plan_cid": None,
        "shadow_result_cid": None,
        "differential_report_cid": None,
        "policy_cid": _cid("policy"),
        "benchmark_partition": "calibration",
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return CompressionAuditCase(**fields)  # type: ignore[arg-type]


def _obs(**overrides: object) -> CalibrationObservation:
    fields: dict[str, object] = {
        "observation_id": "obs_local_bug",
        "partition": EvidencePartition.CALIBRATION,
        "capsule_class": "function_capsule",
        "language": "python",
        "symbol_kind": "function",
        "framework": "pytest",
        "analyzer_feature": "callgraph",
        "analyzer_id": "callgraph",
        "analyzer_version": "1.0.0",
        "repository_family": "ipfs_datasets",
        "task_class": "local_bug",
        "risk_class": "low",
        "route_id": "standard_v1",
        "route_tier": "standard",
        "proof_classification": ProofClassification.HEURISTIC,
        "classification_source": ClassificationSource.EMPIRICAL,
        "comparative_outcome": ComparativeOutcome.EQUIVALENT_SUCCESS,
        "compressed_success": True,
        "expanded_success": True,
        "omission_failure": False,
        "stale_failure": False,
        "false_exact_classification": False,
        "unnecessary_raw_fallback": False,
        "review_disagreement": False,
        "escalated": False,
        "retried": False,
        "shadow_sampled": False,
        "token_savings": 100,
        "verification_cost": 10,
        "route_success": True,
        "metadata": {},
    }
    fields.update(overrides)
    return CalibrationObservation(**fields)  # type: ignore[arg-type]


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
        "risk_class": "low",
        "route_tier": "standard",
        "proof_classification": ProofClassification.HEURISTIC,
        "classification_source": ClassificationSource.EMPIRICAL,
        "partition": EvidencePartition.CALIBRATION,
        "revision": 1,
        "use_count": 10,
        "compressed_success_count": 9,
        "expanded_success_count": 10,
        "omission_failure_count": 1,
        "stale_failure_count": 0,
        "false_exact_classification_count": 0,
        "unnecessary_raw_fallback_count": 0,
        "review_disagreement_count": 0,
        "token_savings_total": 1200,
        "verification_cost_total": 40,
        "omission_rate": _rate(1, 10),
        "source_audit_cids": (),
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
        "total_uses": 10,
        "false_exact_classification_count": 0,
        "stale_failure_count": 0,
        "omission_rate": _rate(1, 10),
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
        "profile_id": "task_local_bug",
        "task_class": "local_bug",
        "risk_class": "low",
        "partition": EvidencePartition.CALIBRATION,
        "revision": 1,
        "total_uses": 10,
        "compressed_success_count": 9,
        "expanded_success_count": 10,
        "review_disagreement_count": 0,
        "omission_rate": _rate(1, 10),
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
        "total_uses": 10,
        "escalation_count": 1,
        "retry_count": 0,
        "shadow_sample_count": 1,
        "success_rate": _rate(9, 10),
        "escalation_rate_bp": 1000,
        "retry_rate_bp": 0,
        "shadow_sample_rate_bp": 1000,
        "allows_empirical_exact_upgrade": False,
        "record_cids": (),
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return ModelRouteCalibrationProfile(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Interface and vocabulary pins
# ---------------------------------------------------------------------------


def test_interface_pins_are_stable() -> None:
    assert update_calibration_interface_id() == UPDATE_CALIBRATION_INTERFACE
    assert (
        merge_calibration_profiles_interface_id()
        == MERGE_CALIBRATION_PROFILES_INTERFACE
    )
    assert "capsule" in calibration_kinds()
    assert "applied" in calibration_dispositions()
    assert "equivalent_success" in comparative_outcomes()


def test_wilson_interval_is_integer_basis_points() -> None:
    rate_bp, lower_bp, upper_bp = wilson_score_interval_bp(9, 10)
    assert rate_bp == 9000
    assert isinstance(rate_bp, int)
    assert isinstance(lower_bp, int)
    assert isinstance(upper_bp, int)
    assert 0 <= lower_bp <= rate_bp <= upper_bp <= 10_000
    empty = wilson_score_interval_bp(0, 0)
    assert empty == (0, 0, 0)
    rate = build_empirical_rate(1, 4)
    assert rate.rate_bp == 2500
    assert rate.interval_method == "wilson_score_95"


# ---------------------------------------------------------------------------
# Acceptance: simulated excluded from live quality
# ---------------------------------------------------------------------------


def test_simulated_outputs_excluded_from_live_quality() -> None:
    case = _case(
        header=_header(
            "compression_audit_case",
            provenance=_provenance(execution_mode=ExecutionMode.SIMULATED),
            terminal_status=GovernorTerminalStatus.SIMULATED,
        )
    )
    profile = _capsule()
    before_cid = profile.record_cid
    result = update_calibration(case, profile, observation=_obs())
    assert result.disposition == CalibrationDisposition.SKIPPED_SIMULATED.value
    assert result.applied_to_live_quality is False
    assert result.next_profile_cid == before_cid
    assert result.next_revision == profile.revision
    assert result.profile.use_count == profile.use_count  # type: ignore[union-attr]


def test_live_update_applies_to_capsule_and_keeps_revision_binding() -> None:
    case = _case()
    profile = _capsule()
    obs = _obs(
        comparative_outcome=ComparativeOutcome.COMPRESSED_FAILED_EXPANDED_SUCCEEDED,
        compressed_success=False,
        expanded_success=True,
        omission_failure=True,
        token_savings=50,
        verification_cost=5,
    )
    result = update_calibration(case, profile, observation=obs)
    assert result.disposition == CalibrationDisposition.APPLIED.value
    assert result.applied_to_live_quality is True
    assert result.kind == CalibrationKind.CAPSULE.value
    updated = result.profile
    assert isinstance(updated, CapsuleCalibrationRecord)
    assert updated.revision == profile.revision + 1
    assert updated.use_count == profile.use_count + 1
    assert updated.omission_failure_count == profile.omission_failure_count + 1
    assert updated.compressed_success_count == profile.compressed_success_count
    assert updated.expanded_success_count == profile.expanded_success_count + 1
    assert case.case_cid in updated.source_audit_cids
    assert updated.omission_rate.trials == updated.use_count
    assert updated.omission_rate.successes == updated.omission_failure_count
    assert result.previous_revision == profile.revision
    assert result.next_revision == updated.revision
    assert result.previous_profile_cid == profile.record_cid
    assert result.next_profile_cid == updated.record_cid


# ---------------------------------------------------------------------------
# Acceptance: concurrent/replayed inputs are idempotent
# ---------------------------------------------------------------------------


def test_replayed_audit_case_is_idempotent() -> None:
    case = _case()
    profile = _capsule()
    obs = _obs()
    first = update_calibration(case, profile, observation=obs)
    assert first.disposition == CalibrationDisposition.APPLIED.value
    second = update_calibration(case, first.profile, observation=obs)
    assert second.disposition == CalibrationDisposition.SKIPPED_IDEMPOTENT.value
    assert second.applied_to_live_quality is False
    assert second.next_profile_cid == first.next_profile_cid
    assert second.next_revision == first.next_revision
    third = update_calibration(case, first.profile, observation=obs)
    assert third.update_cid == second.update_cid


def test_concurrent_expected_revision_cas_rejects_stale_writer() -> None:
    case = _case()
    profile = _capsule(revision=5)
    result = update_calibration(
        case,
        profile,
        observation=_obs(),
        expected_revision=4,
    )
    assert result.disposition == CalibrationDisposition.REJECTED_STALE_REVISION.value
    assert result.applied_to_live_quality is False
    assert result.next_profile_cid == profile.record_cid
    assert result.profile.use_count == profile.use_count  # type: ignore[union-attr]


def test_expected_revision_match_allows_apply() -> None:
    case = _case()
    profile = _capsule(revision=5)
    result = update_calibration(
        case,
        profile,
        observation=_obs(),
        expected_revision=5,
    )
    assert result.disposition == CalibrationDisposition.APPLIED.value
    assert result.next_revision == 6


# ---------------------------------------------------------------------------
# Acceptance: false exact and stale failures remain explicit
# ---------------------------------------------------------------------------


def test_false_exact_and_stale_failures_remain_explicit() -> None:
    case = _case(case_id="case_false_exact")
    profile = _capsule(
        false_exact_classification_count=2,
        stale_failure_count=3,
        omission_failure_count=1,
        use_count=10,
        omission_rate=_rate(1, 10),
    )
    obs = _obs(
        observation_id="obs_false_exact",
        false_exact_classification=True,
        stale_failure=True,
        omission_failure=False,
        compressed_success=False,
        expanded_success=False,
        route_success=False,
        comparative_outcome=ComparativeOutcome.BOTH_FAILED_SAME_REASON,
    )
    result = update_calibration(case, profile, observation=obs)
    updated = result.profile
    assert isinstance(updated, CapsuleCalibrationRecord)
    # Explicit counters move independently of omission rate successes.
    assert updated.false_exact_classification_count == 3
    assert updated.stale_failure_count == 4
    assert updated.omission_failure_count == 1
    assert result.false_exact_classification_count == 3
    assert result.stale_failure_count == 4
    assert result.omission_failure_count == 1
    # Omission rate still tracks omission events only, not false-exact/stale.
    assert updated.omission_rate.successes == 1
    assert updated.omission_rate.trials == updated.use_count


def test_analyzer_profile_keeps_false_exact_and_stale_explicit() -> None:
    case = _case(case_id="case_analyzer_stale")
    profile = _analyzer(
        false_exact_classification_count=1,
        stale_failure_count=2,
    )
    obs = _obs(
        observation_id="obs_analyzer_stale",
        false_exact_classification=True,
        stale_failure=True,
        omission_failure=True,
        comparative_outcome=ComparativeOutcome.COMPRESSED_FAILED_EXPANDED_SUCCEEDED,
        compressed_success=False,
        expanded_success=True,
        route_success=False,
    )
    result = update_calibration(case, profile, observation=obs)
    updated = result.profile
    assert isinstance(updated, AnalyzerCalibrationProfile)
    assert updated.false_exact_classification_count == 2
    assert updated.stale_failure_count == 3
    assert updated.omission_rate.successes == 2
    assert result.false_exact_classification_count == 2
    assert result.stale_failure_count == 3


# ---------------------------------------------------------------------------
# Task and route calibration
# ---------------------------------------------------------------------------


def test_task_class_and_route_updates() -> None:
    case = _case(case_id="case_task_route")
    task_result = update_calibration(
        case,
        _task(),
        observation=_obs(
            observation_id="obs_task",
            review_disagreement=True,
        ),
    )
    assert task_result.kind == CalibrationKind.TASK_CLASS.value
    task_profile = task_result.profile
    assert isinstance(task_profile, TaskClassCalibrationProfile)
    assert task_profile.total_uses == 11
    assert task_profile.review_disagreement_count == 1
    # Formal required proof posture is preserved (not empirical-upgraded).
    assert task_profile.required_proof_classification == "conservative"
    assert task_profile.classification_source == "formal"

    route_result = update_calibration(
        case,
        _route(),
        observation=_obs(
            observation_id="obs_route",
            escalated=True,
            retried=True,
            shadow_sampled=True,
            route_success=True,
        ),
    )
    assert route_result.kind == CalibrationKind.MODEL_ROUTE.value
    route_profile = route_result.profile
    assert isinstance(route_profile, ModelRouteCalibrationProfile)
    assert route_profile.total_uses == 11
    assert route_profile.escalation_count == 2
    assert route_profile.retry_count == 1
    assert route_profile.shadow_sample_count == 2
    assert route_profile.allows_empirical_exact_upgrade is False
    assert route_profile.success_rate.successes == 10
    assert route_profile.escalation_rate_bp == ratio_to_basis_points(2, 11)


def test_key_mismatch_is_rejected_without_mutation() -> None:
    case = _case()
    profile = _capsule()
    result = update_calibration(
        case,
        profile,
        observation=_obs(capsule_class="module_capsule"),
    )
    assert result.disposition == CalibrationDisposition.REJECTED_KEY_MISMATCH.value
    assert result.next_profile_cid == profile.record_cid


def test_partition_mismatch_is_skipped() -> None:
    case = _case()
    profile = _capsule(partition=EvidencePartition.CALIBRATION)
    result = update_calibration(
        case,
        profile,
        observation=_obs(partition=EvidencePartition.HELD_OUT),
    )
    assert (
        result.disposition == CalibrationDisposition.SKIPPED_PARTITION_MISMATCH.value
    )
    assert result.applied_to_live_quality is False


# ---------------------------------------------------------------------------
# Merge profiles
# ---------------------------------------------------------------------------


def test_merge_calibration_profiles_sums_counters_and_unions_cids() -> None:
    left = _capsule(
        revision=2,
        use_count=4,
        compressed_success_count=3,
        expanded_success_count=4,
        omission_failure_count=1,
        stale_failure_count=1,
        false_exact_classification_count=1,
        omission_rate=_rate(1, 4),
        source_audit_cids=(_cid("audit-a"),),
        token_savings_total=100,
        verification_cost_total=10,
    )
    right = _capsule(
        revision=5,
        use_count=6,
        compressed_success_count=5,
        expanded_success_count=6,
        omission_failure_count=2,
        stale_failure_count=0,
        false_exact_classification_count=2,
        omission_rate=_rate(2, 6),
        source_audit_cids=(_cid("audit-b"),),
        token_savings_total=200,
        verification_cost_total=20,
    )
    merged = merge_calibration_profiles(left, right)
    profile = merged.profile
    assert isinstance(profile, CapsuleCalibrationRecord)
    assert profile.use_count == 10
    assert profile.omission_failure_count == 3
    assert profile.stale_failure_count == 1
    assert profile.false_exact_classification_count == 3
    assert profile.revision == 6  # max(2, 5) + 1
    assert list(profile.source_audit_cids) == sorted(
        [_cid("audit-a"), _cid("audit-b")]
    )
    assert profile.omission_rate.successes == 3
    assert profile.omission_rate.trials == 10
    assert merged.kind == CalibrationKind.CAPSULE.value


def test_merge_rejects_heterogeneous_kinds_and_partitions() -> None:
    with pytest.raises(CalibrationError, match="heterogeneous"):
        merge_calibration_profiles(_capsule(), _analyzer())
    with pytest.raises(CalibrationError, match="partitions"):
        merge_calibration_profiles(
            _capsule(partition=EvidencePartition.CALIBRATION),
            _capsule(partition=EvidencePartition.HELD_OUT),
        )


def test_merge_route_and_task_profiles() -> None:
    left_route = _route(revision=1, total_uses=5, success_rate=_rate(4, 5))
    right_route = _route(
        revision=2,
        total_uses=5,
        escalation_count=2,
        retry_count=1,
        shadow_sample_count=0,
        success_rate=_rate(5, 5),
        escalation_rate_bp=4000,
        retry_rate_bp=2000,
        shadow_sample_rate_bp=0,
        record_cids=(_cid("route-case"),),
    )
    route_merge = merge_calibration_profiles(left_route, right_route)
    route = route_merge.profile
    assert isinstance(route, ModelRouteCalibrationProfile)
    assert route.total_uses == 10
    assert route.success_rate.successes == 9
    assert route.allows_empirical_exact_upgrade is False

    left_task = _task(
        revision=1,
        total_uses=3,
        compressed_success_count=3,
        expanded_success_count=3,
        omission_rate=_rate(0, 3),
    )
    right_task = _task(
        revision=4,
        total_uses=7,
        compressed_success_count=6,
        expanded_success_count=7,
        review_disagreement_count=1,
        omission_rate=_rate(1, 7),
    )
    task_merge = merge_calibration_profiles(left_task, right_task)
    task = task_merge.profile
    assert isinstance(task, TaskClassCalibrationProfile)
    assert task.total_uses == 10
    assert task.review_disagreement_count == 1
    assert task.required_proof_classification == "conservative"


# ---------------------------------------------------------------------------
# Determinism, observation helpers, mapping inputs
# ---------------------------------------------------------------------------


def test_identical_inputs_yield_identical_update_cids() -> None:
    case = _case(case_id="case_det")
    profile = _capsule()
    obs = _obs(observation_id="obs_det")
    a = update_calibration(case, profile, observation=obs)
    b = update_calibration(case, profile, observation=obs)
    assert a.update_cid == b.update_cid
    assert a.next_profile_cid == b.next_profile_cid


def test_observation_from_outcome_and_mapping_round_trip() -> None:
    obs = observation_from_outcome(
        observation_id="obs_derived",
        partition=EvidencePartition.CALIBRATION,
        comparative_outcome=ComparativeOutcome.COMPRESSED_FAILED_EXPANDED_SUCCEEDED,
        stale_failure=True,
        false_exact_classification=True,
        task_class="local_bug",
        risk_class="low",
    )
    assert obs.omission_failure is True
    assert obs.compressed_success is False
    assert obs.expanded_success is True
    restored = CalibrationObservation.from_dict(
        {k: v for k, v in obs.to_dict().items() if k != "observation_cid"}
    )
    assert restored.observation_cid == obs.observation_cid

    case = _case(case_id="case_mapping")
    result = update_calibration(
        case.to_dict(),
        _analyzer().to_dict(),
        observation=obs.to_dict(),
    )
    # Key match on analyzer_id/version still holds with defaults.
    assert result.disposition == CalibrationDisposition.APPLIED.value


def test_empirical_success_never_upgrades_proof_classification() -> None:
    """Updating counters must leave formal classification fields untouched."""

    case = _case(case_id="case_no_upgrade")
    # Capsule that is already formal-exact must stay formal-exact, not flip source.
    profile = _capsule(
        proof_classification=ProofClassification.EXACT,
        classification_source=ClassificationSource.FORMAL,
    )
    result = update_calibration(
        case,
        profile,
        observation=_obs(
            observation_id="obs_no_upgrade",
            proof_classification=ProofClassification.EXACT,
            classification_source=ClassificationSource.FORMAL,
            compressed_success=True,
            expanded_success=True,
        ),
    )
    updated = result.profile
    assert isinstance(updated, CapsuleCalibrationRecord)
    assert updated.proof_classification == "exact"
    assert updated.classification_source == "formal"
    # Route profile hard-forbids empirical exact upgrade flag.
    route = update_calibration(
        case,
        _route(),
        observation=_obs(observation_id="obs_route_no_upgrade"),
    )
    assert route.profile.allows_empirical_exact_upgrade is False  # type: ignore[union-attr]


def test_result_exposes_explicit_failure_fields_on_skip() -> None:
    case = _case(
        header=_header(
            "compression_audit_case",
            provenance=_provenance(execution_mode=ExecutionMode.SIMULATED),
            terminal_status=GovernorTerminalStatus.SIMULATED,
        )
    )
    profile = _capsule(
        false_exact_classification_count=7,
        stale_failure_count=4,
        omission_failure_count=2,
        omission_rate=_rate(2, 10),
    )
    result = update_calibration(case, profile, observation=_obs())
    assert result.false_exact_classification_count == 7
    assert result.stale_failure_count == 4
    assert result.omission_failure_count == 2
    assert result.applied_to_live_quality is False
