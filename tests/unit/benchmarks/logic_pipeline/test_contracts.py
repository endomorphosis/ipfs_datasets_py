"""Executable evidence for the frozen logic-pipeline benchmark protocol."""

from __future__ import annotations

import builtins
from dataclasses import FrozenInstanceError, replace
import json
import math
from pathlib import Path

import pytest

from benchmarks.logic_pipeline import contracts


SHA_A = "a" * 64
SHA_B = "b" * 64


def _run_contract(
    *,
    variant: str = "A1",
    effective_variant: str | None = None,
    split: contracts.Split = contracts.Split.PILOT,
    mode: contracts.CacheMode = contracts.CacheMode.COLD,
    tuning_permitted: bool = True,
    all_frozen: bool = False,
    access_log: str | None = None,
) -> contracts.RunContract:
    digest = contracts.DEFAULT_PROTOCOL_SHA256
    scope = contracts.CacheScope("run-001", digest, variant, split, mode)
    return contracts.RunContract(
        schema=contracts.RUN_CONTRACT_SCHEMA,
        protocol_sha256=digest,
        run_id="run-001",
        requested_variant_id=variant,
        effective_variant_id=effective_variant or variant,
        split=split,
        cache_mode=mode,
        cache_namespace=scope.namespace,
        case_manifest_sha256=SHA_A,
        configuration_sha256=SHA_B,
        prompts_frozen=all_frozen,
        policy_frozen=all_frozen,
        model_identities_frozen=all_frozen,
        thresholds_frozen=all_frozen,
        tuning_permitted=tuning_permitted,
        holdout_access_log_id=access_log,
    )


def _outcome(
    *,
    variant: str = "A0",
    status: contracts.OutcomeStatus = contracts.OutcomeStatus.NOT_VERIFIED,
    invalid_control: bool = False,
    authority: contracts.VerificationAuthority = (
        contracts.VerificationAuthority.NONE
    ),
    kernel_accepted: bool = False,
    receipt: str | None = None,
    failure_code: contracts.FailureCode | None = None,
    failure_detail: str | None = None,
) -> contracts.OutcomeRecord:
    return contracts.OutcomeRecord(
        schema=contracts.OUTCOME_RECORD_SCHEMA,
        protocol_sha256=contracts.DEFAULT_PROTOCOL_SHA256,
        run_id="run-001",
        case_id="case-001",
        case_manifest_sha256=SHA_A,
        variant_id=variant,
        split=contracts.Split.PILOT,
        cache_mode=contracts.CacheMode.COLD,
        status=status,
        invalid_control=invalid_control,
        verification_authority=authority,
        kernel_accepted=kernel_accepted,
        kernel_receipt_sha256=receipt,
        failure_code=failure_code,
        failure_detail=failure_detail,
    )


def test_objective_evidence_and_public_default_are_stable() -> None:
    assert (
        contracts.HSSLEV0103C72()
        == "preregistered benchmark protocol and safety invariants"
    )
    assert contracts.DEFAULT_PROTOCOL.schema == contracts.PROTOCOL_SCHEMA
    assert contracts.DEFAULT_PROTOCOL.protocol_version == 1
    assert contracts.DEFAULT_PROTOCOL.frozen is True
    assert contracts.DEFAULT_PROTOCOL.pilot_results_inspected is False
    assert (
        contracts.DEFAULT_PROTOCOL_SHA256
        == "a12067c4239b9628fde065db3fe10e623148c95a55891a642306e0c90dee8fa3"
    )


def test_normative_readme_binds_the_frozen_protocol_digest() -> None:
    readme = Path(contracts.__file__).with_name("README.md").read_text(
        encoding="utf-8"
    )
    assert contracts.DEFAULT_PROTOCOL_SHA256 in readme
    assert "Only an accepted receipt from the independent native kernel" in readme
    assert "tolerance is exactly zero" in readme


def test_import_remains_dependency_free_and_side_effect_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbidden = {
        "hammer",
        "leanstral",
        "spacy",
        "symai",
        "symbolicai",
        "ipfs_datasets_py",
    }
    real_import = builtins.__import__

    def guarded(name: str, *args: object, **kwargs: object) -> object:
        if name.partition(".")[0] in forbidden:
            raise AssertionError(f"unexpected optional import: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    assert contracts.build_default_protocol() == contracts.DEFAULT_PROTOCOL


def test_protocol_preregisters_complete_hypotheses_variants_and_metrics() -> None:
    protocol = contracts.DEFAULT_PROTOCOL
    assert {item.hypothesis_id for item in protocol.hypotheses} == {
        f"H{i}" for i in range(1, 8)
    }
    assert all(item.null_statement for item in protocol.hypotheses)
    assert {item.variant_id for item in protocol.variants} == {
        *(f"A{i}" for i in range(13)),
        "S1",
    }
    assert protocol.variant_map["A0"].paired_against is None
    assert all(
        item.paired_against == "A0"
        for item in protocol.variants
        if item.variant_id != "A0"
    )
    assert protocol.variant_map["S1"].safety_diagnostic_only
    assert not protocol.variant_map["S1"].primary_candidate
    assert "V00" not in protocol.variant_map

    primary = {
        item.metric_id
        for item in protocol.metrics
        if item.category is contracts.MetricCategory.PRIMARY
    }
    assert primary >= {
        "kernel_verified_completion_rate",
        "invalid_control_kernel_false_positive_rate",
        "normalized_ir_exact_match",
        "deterministic_semantic_equivalence",
        "paired_verified_delta_vs_a0",
    }
    assert any(
        item.category is contracts.MetricCategory.RESOURCE
        for item in protocol.metrics
    )
    assert any(
        item.category is contracts.MetricCategory.ROUTING
        for item in protocol.metrics
    )


def test_thresholds_freeze_all_materiality_decisions() -> None:
    thresholds = contracts.DEFAULT_PROTOCOL.thresholds
    assert thresholds.invalid_control_verified_max == 0
    assert thresholds.confidence_level == 0.95
    assert thresholds.paired_regression_floor == -0.01
    assert thresholds.hard_case_verified_gain_min == 0.05
    assert thresholds.near_best_quality_margin_max == 0.01
    assert thresholds.efficiency_reduction_min == 0.20
    assert thresholds.baseline_solved_regression_rate_max == 0.01
    assert thresholds.unexplained_baseline_regressions_max == 0
    assert thresholds.shortlist_candidate_max == 4


@pytest.mark.parametrize("bad", [True, math.nan, math.inf, -math.inf])
def test_thresholds_reject_boolean_and_nonfinite_numbers(bad: object) -> None:
    with pytest.raises(contracts.ProtocolContractError, match="finite number"):
        contracts.MaterialityThresholds(confidence_level=bad)  # type: ignore[arg-type]


def test_safety_and_holdout_invariants_cannot_be_relaxed() -> None:
    with pytest.raises(contracts.ProtocolContractError, match="cannot be relaxed"):
        contracts.SafetyInvariants(kernel_only_verification=False)
    with pytest.raises(contracts.ProtocolContractError, match="cannot be relaxed"):
        contracts.HoldoutRules(tuning_after_access_forbidden=False)
    with pytest.raises(contracts.ProtocolContractError, match="permanently zero"):
        contracts.MaterialityThresholds(invalid_control_verified_max=1)


def test_protocol_is_deeply_immutable_and_lookup_is_read_only() -> None:
    protocol = contracts.DEFAULT_PROTOCOL
    with pytest.raises(FrozenInstanceError):
        protocol.frozen = False  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        protocol.variants[0].purpose = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        protocol.variant_map["A0"] = protocol.variants[0]  # type: ignore[index]


def test_protocol_record_round_trip_and_canonical_digest() -> None:
    record = contracts.ProtocolRecord.create(contracts.DEFAULT_PROTOCOL)
    encoded = contracts.canonical_json(record.to_dict())
    restored = contracts.ProtocolRecord.from_dict(json.loads(encoded))

    assert restored == record
    assert contracts.canonical_protocol_json(restored.protocol) == (
        contracts.canonical_protocol_json(contracts.DEFAULT_PROTOCOL)
    )
    reordered = dict(reversed(list(record.to_dict().items())))
    assert contracts.canonical_json(reordered) == encoded


def test_protocol_records_fail_closed_on_schema_unknown_fields_and_tampering() -> None:
    payload = contracts.ProtocolRecord.create(
        contracts.DEFAULT_PROTOCOL
    ).to_dict()

    bad_schema = json.loads(json.dumps(payload))
    bad_schema["protocol"]["schema"] = "protocol.v2"
    with pytest.raises(contracts.ProtocolContractError, match="unsupported"):
        contracts.ProtocolRecord.from_dict(bad_schema)

    unknown = json.loads(json.dumps(payload))
    unknown["protocol"]["post_pilot_edit"] = True
    with pytest.raises(contracts.ProtocolContractError, match="unknown"):
        contracts.ProtocolRecord.from_dict(unknown)

    tampered = json.loads(json.dumps(payload))
    tampered["protocol"]["hypotheses"][0]["statement"] = "post-pilot change"
    with pytest.raises(
        contracts.ProtocolContractError, match="frozen|digest"
    ):
        contracts.ProtocolRecord.from_dict(tampered)


def test_protocol_revision_cannot_be_amended_under_a_new_digest() -> None:
    with pytest.raises(contracts.ProtocolContractError, match="new schema"):
        replace(
            contracts.DEFAULT_PROTOCOL,
            thresholds=contracts.MaterialityThresholds(confidence_level=0.90),
        )


def test_duplicate_or_missing_registered_ids_are_rejected() -> None:
    protocol = contracts.DEFAULT_PROTOCOL
    with pytest.raises(contracts.ProtocolContractError, match="duplicate"):
        replace(protocol, hypotheses=protocol.hypotheses + (protocol.hypotheses[0],))
    with pytest.raises(contracts.ProtocolContractError, match="exactly A0-A12"):
        replace(protocol, variants=protocol.variants[:-1])


def test_only_accepted_native_kernel_receipt_can_set_verified() -> None:
    for authority in (
        contracts.VerificationAuthority.NONE,
        contracts.VerificationAuthority.MODEL,
        contracts.VerificationAuthority.EXTERNAL_SOLVER,
        contracts.VerificationAuthority.LEGACY_ROUTER,
    ):
        with pytest.raises(
            contracts.ProtocolContractError, match="native-kernel"
        ):
            _outcome(
                status=contracts.OutcomeStatus.VERIFIED,
                authority=authority,
                kernel_accepted=True,
                receipt=SHA_B,
            )

    verified = _outcome(
        status=contracts.OutcomeStatus.VERIFIED,
        authority=contracts.VerificationAuthority.NATIVE_KERNEL,
        kernel_accepted=True,
        receipt=SHA_B,
    )
    assert verified.status is contracts.OutcomeStatus.VERIFIED


def test_invalid_control_verification_is_recorded_as_fatal_safety_evidence() -> None:
    incident = _outcome(
        status=contracts.OutcomeStatus.VERIFIED,
        invalid_control=True,
        authority=contracts.VerificationAuthority.NATIVE_KERNEL,
        kernel_accepted=True,
        receipt=SHA_B,
    )
    assert incident.safety_violations == (
        contracts.FailureCode.INVALID_CONTROL_VERIFIED,
    )
    assert contracts.DEFAULT_PROTOCOL.stop_required(
        contracts.FailureCode.INVALID_CONTROL_VERIFIED
    )
    with pytest.raises(contracts.ProtocolContractError, match="fatal"):
        contracts.validate_paired_outcomes(
            _outcome(variant="A0"),
            replace(incident, variant_id="A4"),
            protocol=contracts.DEFAULT_PROTOCOL,
        )


def test_outcome_round_trip_is_strict_and_unknown_enums_fail() -> None:
    outcome = _outcome(
        status=contracts.OutcomeStatus.REJECTED,
        failure_code=contracts.FailureCode.KERNEL_REJECTION,
        failure_detail="kernel rejected candidate",
    )
    assert contracts.OutcomeRecord.from_dict(outcome.to_dict()) == outcome

    payload = outcome.to_dict()
    payload["status"] = "proved_by_model"
    with pytest.raises(contracts.ProtocolContractError, match="unsupported status"):
        contracts.OutcomeRecord.from_dict(payload)


def test_infrastructure_failures_are_neither_logical_failures_nor_eligible() -> None:
    outcome = _outcome(
        status=contracts.OutcomeStatus.INFRASTRUCTURE_FAILURE,
        failure_code=contracts.FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE,
        failure_detail="scheduler unavailable",
    )
    assert not outcome.eligible_for_paired_statistics

    with pytest.raises(contracts.ProtocolContractError, match="infrastructure code"):
        _outcome(
            status=contracts.OutcomeStatus.INFRASTRUCTURE_FAILURE,
            failure_code=contracts.FailureCode.KERNEL_REJECTION,
            failure_detail="wrong class",
        )


def test_poor_answers_cannot_be_excluded_and_capability_gaps_are_explicit() -> None:
    with pytest.raises(contracts.ProtocolContractError, match="preregistered code"):
        _outcome(
            status=contracts.OutcomeStatus.EXCLUDED,
            failure_code=contracts.FailureCode.KERNEL_REJECTION,
            failure_detail="poor result",
        )

    unavailable = _outcome(
        variant="A8",
        status=contracts.OutcomeStatus.UNAVAILABLE,
        failure_code=contracts.FailureCode.CAPABILITY_UNAVAILABLE,
        failure_detail="requested full model is absent",
    )
    assert not unavailable.eligible_for_paired_statistics
    assert unavailable.variant_id == "A8"


def test_cache_scope_binds_every_isolation_dimension_without_collisions() -> None:
    digest = contracts.DEFAULT_PROTOCOL_SHA256
    scopes = {
        contracts.CacheScope(run, digest, variant, split, mode).namespace
        for run, variant, split, mode in (
            ("run-1", "A1", contracts.Split.PILOT, contracts.CacheMode.COLD),
            ("run-2", "A1", contracts.Split.PILOT, contracts.CacheMode.COLD),
            ("run-1", "A2", contracts.Split.PILOT, contracts.CacheMode.COLD),
            ("run-1", "A1", contracts.Split.DEVELOPMENT, contracts.CacheMode.COLD),
            ("run-1", "A1", contracts.Split.PILOT, contracts.CacheMode.WARM),
        )
    }
    assert len(scopes) == 5
    namespace = contracts.CacheScope(
        "run-1", digest, "A1", contracts.Split.PILOT, contracts.CacheMode.COLD
    ).namespace
    assert all(
        part in namespace
        for part in ("run-1", digest, "A1", "pilot", "cold")
    )
    with pytest.raises(contracts.ProtocolContractError, match="not registered"):
        contracts.CacheScope(
            "run-1",
            digest,
            "unknown",
            contracts.Split.PILOT,
            contracts.CacheMode.COLD,
        )


@pytest.mark.parametrize("run_id", ["", ".", "..", "../x", "a/b", "has space"])
def test_cache_scope_rejects_unsafe_ids(run_id: str) -> None:
    with pytest.raises(contracts.ProtocolContractError):
        contracts.CacheScope(
            run_id,
            contracts.DEFAULT_PROTOCOL_SHA256,
            "A1",
            contracts.Split.PILOT,
            contracts.CacheMode.COLD,
        )


def test_run_contract_rejects_silent_variant_fallback_and_namespace_reuse() -> None:
    with pytest.raises(contracts.ProtocolContractError, match="silently"):
        _run_contract(variant="A1", effective_variant="A8")

    valid = _run_contract()
    with pytest.raises(contracts.ProtocolContractError, match="cache_namespace"):
        replace(valid, cache_namespace=valid.cache_namespace.replace("A1", "A2"))
    with pytest.raises(contracts.ProtocolContractError, match="frozen protocol"):
        replace(valid, protocol_sha256=SHA_A)


def test_holdout_requires_frozen_inputs_audit_and_no_tuning() -> None:
    holdout = _run_contract(
        split=contracts.Split.HOLDOUT,
        tuning_permitted=False,
        all_frozen=True,
        access_log="holdout-access-001",
    )
    assert contracts.RunContract.from_dict(holdout.to_dict()) == holdout

    with pytest.raises(contracts.ProtocolContractError, match="tuning"):
        _run_contract(
            split=contracts.Split.HOLDOUT,
            tuning_permitted=True,
            all_frozen=True,
            access_log="holdout-access-001",
        )
    with pytest.raises(contracts.ProtocolContractError, match="selection inputs"):
        _run_contract(
            split=contracts.Split.HOLDOUT,
            tuning_permitted=False,
            all_frozen=False,
            access_log="holdout-access-001",
        )
    with pytest.raises(contracts.ProtocolContractError, match="holdout_access_log"):
        _run_contract(
            split=contracts.Split.HOLDOUT,
            tuning_permitted=False,
            all_frozen=True,
        )


def test_paired_outcomes_require_same_identity_and_complete_pair() -> None:
    baseline = _outcome(variant="A0")
    candidate = _outcome(variant="A4")
    contracts.validate_paired_outcomes(
        baseline, candidate, protocol=contracts.DEFAULT_PROTOCOL
    )

    with pytest.raises(contracts.ProtocolContractError, match="share run"):
        contracts.validate_paired_outcomes(
            baseline,
            replace(candidate, case_id="case-002"),
            protocol=contracts.DEFAULT_PROTOCOL,
        )
    with pytest.raises(contracts.ProtocolContractError, match="cannot enter"):
        contracts.validate_paired_outcomes(
            baseline,
            replace(candidate, variant_id="S1"),
            protocol=contracts.DEFAULT_PROTOCOL,
        )
    unavailable = _outcome(
        variant="A4",
        status=contracts.OutcomeStatus.UNAVAILABLE,
        failure_code=contracts.FailureCode.CAPABILITY_UNAVAILABLE,
        failure_detail="missing backend",
    )
    with pytest.raises(contracts.ProtocolContractError, match="incomplete pair"):
        contracts.validate_paired_outcomes(
            baseline, unavailable, protocol=contracts.DEFAULT_PROTOCOL
        )


def test_candidate_gate_accepts_quality_or_efficiency_and_rejects_safety() -> None:
    passing = contracts.CandidateGateObservation(
        invalid_control_verified_count=0,
        paired_interval_low=-0.005,
        hard_case_verified_gain=0.05,
        quality_gap_from_best=0.02,
        p95_latency_reduction=0,
        model_usage_reduction=0,
        baseline_solved_regression_rate=0.01,
        unexplained_baseline_regressions=0,
        all_successes_kernel_bound_and_replayable=True,
    )
    assert contracts.evaluate_candidate_gate(
        passing, protocol=contracts.DEFAULT_PROTOCOL
    ).status is contracts.GateStatus.PASSED

    efficient = replace(
        passing,
        hard_case_verified_gain=0.01,
        quality_gap_from_best=0.01,
        model_usage_reduction=0.20,
    )
    assert contracts.evaluate_candidate_gate(
        efficient, protocol=contracts.DEFAULT_PROTOCOL
    ).status is contracts.GateStatus.PASSED

    unsafe = replace(passing, invalid_control_verified_count=1)
    decision = contracts.evaluate_candidate_gate(
        unsafe, protocol=contracts.DEFAULT_PROTOCOL
    )
    assert decision.status is contracts.GateStatus.FAILED
    assert any("invalid-control" in reason for reason in decision.reasons)


def test_infrastructure_failure_makes_gate_incomplete_not_failed() -> None:
    observation = contracts.CandidateGateObservation(
        invalid_control_verified_count=0,
        paired_interval_low=0,
        hard_case_verified_gain=0.10,
        quality_gap_from_best=0,
        p95_latency_reduction=0,
        model_usage_reduction=0,
        baseline_solved_regression_rate=0,
        unexplained_baseline_regressions=0,
        all_successes_kernel_bound_and_replayable=True,
        infrastructure_failure_count=1,
    )
    decision = contracts.evaluate_candidate_gate(
        observation, protocol=contracts.DEFAULT_PROTOCOL
    )
    assert decision.status is contracts.GateStatus.INCOMPLETE


def test_stop_thresholds_are_explicit_and_bounded() -> None:
    protocol = contracts.DEFAULT_PROTOCOL
    assert not protocol.stop_required(
        contracts.FailureCode.OUT_OF_MEMORY, consecutive_occurrences=1
    )
    assert protocol.stop_required(
        contracts.FailureCode.OUT_OF_MEMORY, consecutive_occurrences=2
    )
    assert not protocol.stop_required(
        contracts.FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE,
        consecutive_occurrences=2,
    )
    assert protocol.stop_required(
        contracts.FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE,
        consecutive_occurrences=3,
    )
    for code in contracts.IMMEDIATE_STOP_CODES:
        assert protocol.stop_required(code)
