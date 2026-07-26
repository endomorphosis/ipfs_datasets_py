"""Executable evidence for bounded conditional-delegation policies."""

from __future__ import annotations

import builtins
from dataclasses import FrozenInstanceError, replace
import math

import pytest

from benchmarks.logic_pipeline import delegation
from benchmarks.logic_pipeline.ablation import ResourceLimits
from benchmarks.logic_pipeline.contracts import CacheMode, Split, StageName


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64


def _provenance() -> delegation.LearnedRouterProvenance:
    return delegation.LearnedRouterProvenance(
        selector_sha256=SHA_A,
        feature_schema_sha256=SHA_B,
        training_manifest_sha256=SHA_C,
        training_splits=(Split.DEVELOPMENT,),
        algorithm="seeded-logistic-router-v1",
        seed=1729,
    )


def _configs(
    *,
    thresholds: delegation.DelegationThresholds = (
        delegation.DelegationThresholds()
    ),
    limits: ResourceLimits = ResourceLimits(),
) -> dict[delegation.DelegationPolicy, delegation.DelegationPolicyConfig]:
    return dict(
        delegation.build_policy_configs(
            _provenance(), thresholds=thresholds, resource_limits=limits
        )
    )


def _signals(
    case_id: str = "case-001",
    *,
    split: Split = Split.PILOT,
    cache_mode: CacheMode = CacheMode.COLD,
    input_sha256: str = SHA_E,
    confidence: float = 0.9,
    ambiguity: bool = False,
    missing: bool = False,
    rejected: bool = False,
    obligation_valid: bool = True,
    family: delegation.ProofFamily = delegation.ProofFamily.FIRST_ORDER,
    hammer: delegation.ProofAttemptOutcome = (
        delegation.ProofAttemptOutcome.NOT_ATTEMPTED
    ),
    leanstral: delegation.ProofAttemptOutcome = (
        delegation.ProofAttemptOutcome.NOT_ATTEMPTED
    ),
    symai_score: float = 0.25,
    lean_score: float = 0.25,
) -> delegation.RoutingSignals:
    return delegation.RoutingSignals(
        case_id=case_id,
        case_manifest_sha256=SHA_D,
        input_sha256=input_sha256,
        split=split,
        cache_mode=cache_mode,
        deterministic_confidence=confidence,
        semantic_ambiguity=ambiguity,
        missing_predicates=missing,
        schema_rejected=rejected,
        obligation_valid=obligation_valid,
        proof_family=family,
        hammer_outcome=hammer,
        leanstral_outcome=leanstral,
        learned_symai_score=symai_score,
        learned_lean_first_score=lean_score,
        feature_vector_sha256=SHA_F,
    )


def _decision(
    policy: delegation.DelegationPolicy,
    signals: delegation.RoutingSignals | None = None,
) -> delegation.DelegationDecision:
    return delegation.route_case(_configs()[policy], signals or _signals())


def _observation(
    decision: delegation.DelegationDecision,
    *,
    verified: bool = False,
    useful: frozenset[StageName] = frozenset(),
    deterministic: bool = False,
    improvable: bool = False,
) -> delegation.DelegationObservation:
    return delegation.DelegationObservation(
        decision=decision,
        result_sha256=decision.digest,
        kernel_verified=verified,
        kernel_receipt_sha256=SHA_A if verified else None,
        useful_components=useful,
        deterministically_resolved=deterministic,
        improvable=improvable,
    )


def test_objective_evidence_and_policy_order_are_stable() -> None:
    assert "P0-P3" in delegation.HSSLEV0533D02()
    assert delegation.POLICY_ORDER == (
        delegation.DelegationPolicy.P0_ALWAYS_ON,
        delegation.DelegationPolicy.P1_DETERMINISTIC_FIRST,
        delegation.DelegationPolicy.P2_PROOF_FAMILY,
        delegation.DelegationPolicy.P3_BOUNDED_LEARNED,
    )
    assert {
        item.value for item in delegation.POLICY_ORDER
    } == {"P0", "P1", "P2", "P3"}


def test_module_import_is_dependency_free_and_side_effect_free(
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
    assert delegation.build_policy_configs(_provenance())


def test_configs_are_immutable_content_addressed_and_strict_round_trips() -> None:
    configs = _configs()
    assert len({item.resource_limits_sha256 for item in configs.values()}) == 1
    assert len({item.thresholds.digest for item in configs.values()}) == 1
    for policy, config in configs.items():
        restored = delegation.DelegationPolicyConfig.from_dict(config.to_dict())
        assert restored == config
        assert restored.digest == config.digest
        assert restored.policy is policy
    with pytest.raises(FrozenInstanceError):
        configs[
            delegation.DelegationPolicy.P1_DETERMINISTIC_FIRST
        ].policy = (  # type: ignore[misc]
            delegation.DelegationPolicy.P0_ALWAYS_ON
        )
    tampered = configs[
        delegation.DelegationPolicy.P1_DETERMINISTIC_FIRST
    ].to_dict()
    tampered["resource_limits_sha256"] = SHA_A
    with pytest.raises(
        delegation.DelegationContractError, match="resource-limits digest"
    ):
        delegation.DelegationPolicyConfig.from_dict(tampered)


@pytest.mark.parametrize("value", [True, -0.1, 1.1, math.nan, math.inf])
def test_thresholds_and_scores_fail_closed(value: object) -> None:
    with pytest.raises(delegation.DelegationContractError, match="finite score"):
        delegation.DelegationThresholds(
            deterministic_confidence_min=value,  # type: ignore[arg-type]
        )
    with pytest.raises(delegation.DelegationContractError, match="finite score"):
        _signals(confidence=value)  # type: ignore[arg-type]


def test_learned_router_requires_development_only_pinned_provenance() -> None:
    with pytest.raises(delegation.DelegationContractError, match="development"):
        replace(_provenance(), training_splits=(Split.HOLDOUT,))
    with pytest.raises(delegation.DelegationContractError, match="development"):
        replace(_provenance(), training_splits=(Split.PILOT, Split.DEVELOPMENT))
    with pytest.raises(delegation.DelegationContractError, match="requires pinned"):
        delegation.DelegationPolicyConfig(
            delegation.DelegationPolicy.P3_BOUNDED_LEARNED
        )
    with pytest.raises(delegation.DelegationContractError, match="cannot carry"):
        delegation.DelegationPolicyConfig(
            delegation.DelegationPolicy.P1_DETERMINISTIC_FIRST,
            learned_provenance=_provenance(),
        )


def test_p0_runs_every_component_once_and_ends_at_kernel() -> None:
    decision = _decision(
        delegation.DelegationPolicy.P0_ALWAYS_ON,
        _signals(obligation_valid=False),
    )
    assert decision.invocation_order == (
        StageName.COMPILER,
        StageName.SPACY,
        StageName.SYMAI,
        StageName.HAMMER,
        StageName.LEANSTRAL,
        StageName.KERNEL,
    )
    assert decision.proof_order == (StageName.HAMMER, StageName.LEANSTRAL)
    assert decision.component_calls == (
        StageName.SYMAI,
        StageName.HAMMER,
        StageName.LEANSTRAL,
    )
    assert decision.model_call_count == 2
    assert decision.solver_process_count == 1
    assert decision.cross_family_fallback_count == 0


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"ambiguity": True}, "semantic_ambiguity"),
        ({"missing": True}, "missing_predicates"),
        ({"rejected": True}, "schema_rejected"),
        ({"confidence": 0.749}, "low_deterministic_confidence"),
    ],
)
def test_p1_symai_gate_has_exact_deterministic_or_semantics(
    kwargs: dict[str, object], reason: str
) -> None:
    decision = _decision(
        delegation.DelegationPolicy.P1_DETERMINISTIC_FIRST,
        _signals(**kwargs),  # type: ignore[arg-type]
    )
    assert StageName.SYMAI in decision.component_calls
    assert reason in decision.reasons
    assert decision.deterministic
    assert decision.learned_provenance_sha256 is None

    boundary = _decision(
        delegation.DelegationPolicy.P1_DETERMINISTIC_FIRST,
        _signals(confidence=0.75),
    )
    assert StageName.SYMAI not in boundary.component_calls
    assert "deterministic_frontend_sufficient" in boundary.reasons


def test_p1_hammer_fallback_is_conditional_and_bounded() -> None:
    initial = _decision(
        delegation.DelegationPolicy.P1_DETERMINISTIC_FIRST,
        _signals(),
    )
    assert initial.proof_order == (StageName.HAMMER,)
    failed = _decision(
        delegation.DelegationPolicy.P1_DETERMINISTIC_FIRST,
        _signals(
            hammer=delegation.ProofAttemptOutcome.RECONSTRUCTION_FAILED
        ),
    )
    assert failed.proof_order == (StageName.HAMMER, StageName.LEANSTRAL)
    assert failed.cross_family_fallback_count == 1
    assert len(set(failed.invocation_order)) == len(failed.invocation_order)

    no_proof = _decision(
        delegation.DelegationPolicy.P1_DETERMINISTIC_FIRST,
        _signals(obligation_valid=False),
    )
    assert not set(no_proof.component_calls) & {
        StageName.HAMMER,
        StageName.LEANSTRAL,
    }


@pytest.mark.parametrize(
    ("family", "expected"),
    [
        (delegation.ProofFamily.FIRST_ORDER, StageName.HAMMER),
        (delegation.ProofFamily.SMT, StageName.HAMMER),
        (delegation.ProofFamily.UNKNOWN, StageName.HAMMER),
        (delegation.ProofFamily.LEAN_NATIVE, StageName.LEANSTRAL),
        (delegation.ProofFamily.DEPENDENT_TYPE, StageName.LEANSTRAL),
        (delegation.ProofFamily.TACTIC_HEAVY, StageName.LEANSTRAL),
    ],
)
def test_p2_routes_by_frozen_proof_family(
    family: delegation.ProofFamily, expected: StageName
) -> None:
    decision = _decision(
        delegation.DelegationPolicy.P2_PROOF_FAMILY,
        _signals(family=family),
    )
    assert decision.proof_order == (expected,)
    # Durable stages remain canonical even for Leanstral-first execution.
    assert decision.canonical_stages == tuple(
        sorted(decision.canonical_stages, key=tuple(StageName).index)
    )


def test_p2_crosses_proof_family_once_and_never_bounces() -> None:
    decision = _decision(
        delegation.DelegationPolicy.P2_PROOF_FAMILY,
        _signals(
            family=delegation.ProofFamily.LEAN_NATIVE,
            leanstral=delegation.ProofAttemptOutcome.FAILED,
            hammer=delegation.ProofAttemptOutcome.FAILED,
        ),
    )
    assert decision.proof_order == (StageName.LEANSTRAL, StageName.HAMMER)
    assert decision.cross_family_fallback_count == 1
    assert decision.invocation_order[-1] is StageName.KERNEL
    assert len(set(decision.invocation_order)) == len(decision.invocation_order)


def test_p3_thresholds_are_inclusive_and_decisions_retain_provenance() -> None:
    configs = _configs()
    config = configs[delegation.DelegationPolicy.P3_BOUNDED_LEARNED]
    below = delegation.route_case(
        config, _signals(symai_score=0.499, lean_score=0.499)
    )
    at = delegation.route_case(
        config, _signals(symai_score=0.5, lean_score=0.5)
    )
    assert StageName.SYMAI not in below.component_calls
    assert below.proof_order == (StageName.HAMMER,)
    assert StageName.SYMAI in at.component_calls
    assert at.proof_order == (StageName.LEANSTRAL,)
    assert not at.deterministic
    assert at.learned_provenance_sha256 == _provenance().digest
    assert at.feature_vector_sha256 == SHA_F
    assert delegation.DelegationDecision.from_dict(at.to_dict()) == at
    replay = delegation.route_case(
        config, _signals(symai_score=0.5, lean_score=0.5)
    )
    assert replay == at


def test_p3_rejects_missing_score_provenance_and_unfrozen_holdout() -> None:
    partial = delegation.RoutingSignals(
        case_id="case-001",
        case_manifest_sha256=SHA_D,
        input_sha256=SHA_E,
        split=Split.PILOT,
        cache_mode=CacheMode.COLD,
        deterministic_confidence=0.9,
    )
    with pytest.raises(delegation.DelegationContractError, match="both learned"):
        delegation.route_case(
            _configs()[delegation.DelegationPolicy.P3_BOUNDED_LEARNED],
            partial,
        )

    thresholds = delegation.DelegationThresholds(
        frozen_before_holdout=False
    )
    config = _configs(thresholds=thresholds)[
        delegation.DelegationPolicy.P3_BOUNDED_LEARNED
    ]
    with pytest.raises(delegation.DelegationContractError, match="holdout"):
        delegation.route_case(config, _signals(split=Split.HOLDOUT))


def test_every_route_obeys_identical_resource_and_verification_limits() -> None:
    limits = ResourceLimits(
        max_workers=1,
        case_timeout_seconds=60,
        max_memory_bytes=1024,
        max_model_calls_per_case=2,
        max_solver_processes_per_case=1,
    )
    configs = _configs(limits=limits)
    decisions = [
        delegation.route_case(
            config,
            _signals(
                ambiguity=True,
                hammer=delegation.ProofAttemptOutcome.INCONCLUSIVE,
                leanstral=delegation.ProofAttemptOutcome.INCONCLUSIVE,
                symai_score=1,
                lean_score=1,
            ),
        )
        for config in configs.values()
    ]
    assert len({item.resource_limits_sha256 for item in decisions}) == 1
    assert all(item.invocation_order[-1] is StageName.KERNEL for item in decisions)
    assert all(item.model_call_count <= 2 for item in decisions)
    assert all(item.solver_process_count <= 1 for item in decisions)
    assert all(len(item.component_calls) <= 3 for item in decisions)
    assert all(item.cross_family_fallback_count <= 1 for item in decisions)

    too_small = _configs(
        limits=replace(limits, max_model_calls_per_case=1)
    )[delegation.DelegationPolicy.P0_ALWAYS_ON]
    with pytest.raises(delegation.DelegationContractError, match="model-call"):
        delegation.route_case(too_small, _signals())


def test_decision_roundtrip_rejects_reentry_and_verification_tampering() -> None:
    decision = _decision(delegation.DelegationPolicy.P0_ALWAYS_ON)
    payload = decision.to_dict()
    payload["verification_authority"] = "model"
    with pytest.raises(delegation.DelegationContractError, match="native kernel"):
        delegation.DelegationDecision.from_dict(payload)

    payload = decision.to_dict()
    payload["invocation_order"] = [
        "compiler",
        "spacy",
        "symai",
        "symai",
        "hammer",
        "leanstral",
        "kernel",
    ]
    with pytest.raises(delegation.DelegationContractError):
        delegation.DelegationDecision.from_dict(payload)


def test_observation_requires_kernel_receipt_and_valid_usefulness_attribution() -> None:
    decision = _decision(delegation.DelegationPolicy.P1_DETERMINISTIC_FIRST)
    with pytest.raises(delegation.DelegationContractError, match="kernel_receipt"):
        delegation.DelegationObservation(
            decision=decision,
            result_sha256=SHA_A,
            kernel_verified=True,
            kernel_receipt_sha256=None,
            useful_components=frozenset(),
            deterministically_resolved=False,
            improvable=False,
        )
    with pytest.raises(delegation.DelegationContractError, match="invoked"):
        _observation(
            decision,
            verified=True,
            useful=frozenset({StageName.LEANSTRAL}),
        )
    with pytest.raises(delegation.DelegationContractError, match="verified gain"):
        _observation(
            decision,
            useful=frozenset({StageName.HAMMER}),
        )


def _paired_observations() -> list[delegation.DelegationObservation]:
    observations: list[delegation.DelegationObservation] = []
    for case_id, deterministic, improvable in (
        ("case-clear", True, False),
        ("case-hard", False, True),
    ):
        signals = _signals(
            case_id,
            ambiguity=not deterministic,
            hammer=(
                delegation.ProofAttemptOutcome.INCONCLUSIVE
                if improvable
                else delegation.ProofAttemptOutcome.NOT_ATTEMPTED
            ),
            symai_score=1.0 if improvable else 0.0,
            lean_score=0.0,
        )
        for policy, config in _configs().items():
            decision = delegation.route_case(config, signals)
            useful = (
                frozenset({decision.component_calls[-1]})
                if improvable and decision.component_calls
                else frozenset()
            )
            observations.append(
                _observation(
                    decision,
                    verified=improvable,
                    useful=useful,
                    deterministic=deterministic,
                    improvable=improvable,
                )
            )
    return observations


def test_paired_comparison_reports_exact_unnecessary_call_accounting() -> None:
    comparison = delegation.compare_delegation_policies(_paired_observations())
    assert comparison.policies == delegation.POLICY_ORDER
    assert len(comparison.case_keys) == 2
    p0 = comparison.summaries[
        delegation.DelegationPolicy.P0_ALWAYS_ON
    ]
    assert p0.case_count == 2
    assert p0.component_call_count == 6
    assert p0.useful_call_count == 1
    assert p0.unnecessary_call_count == 5
    assert p0.unnecessary_call_rate == pytest.approx(5 / 6)
    assert p0.escalation_precision == pytest.approx(1 / 6)
    assert p0.escalation_recall == 1
    assert p0.kernel_verified_rate == 0.5
    assert comparison.observation_sha256s == tuple(
        item.digest
        for item in sorted(
            _paired_observations(),
            key=lambda item: (
                item.decision.case_id,
                delegation.POLICY_ORDER.index(item.decision.policy),
            ),
        )
    )
    assert delegation.DELEGATION_COMPARISON_SCHEMA in comparison.schema
    assert "zero when" in comparison.to_dict()["unnecessary_call_rate_definition"]


def test_zero_call_metric_denominators_are_defined() -> None:
    policy = delegation.DelegationPolicy.P1_DETERMINISTIC_FIRST
    decision = _decision(policy, _signals(obligation_valid=False))
    summary = delegation.summarize_policy_efficiency(
        policy,
        [_observation(decision, deterministic=True, improvable=False)],
    )
    assert summary.component_call_count == 0
    assert summary.unnecessary_call_rate == 0.0
    assert summary.escalation_precision == 0.0
    assert summary.escalation_recall == 0.0


@pytest.mark.parametrize(
    "mutation",
    ["missing-policy", "duplicate-policy", "input", "limits", "labels", "holdout"],
)
def test_comparison_rejects_unpaired_or_mixed_scientific_inputs(
    mutation: str,
) -> None:
    records = _paired_observations()
    if mutation == "missing-policy":
        records.pop()
    elif mutation == "duplicate-policy":
        records.append(records[0])
    elif mutation == "input":
        records[0] = replace(
            records[0],
            decision=replace(records[0].decision, input_sha256=SHA_A),
        )
    elif mutation == "limits":
        different = delegation.route_case(
            _configs(
                limits=replace(
                    ResourceLimits(), case_timeout_seconds=121
                )
            )[records[0].decision.policy],
            _signals(records[0].decision.case_id),
        )
        records[0] = replace(
            records[0],
            decision=different,
        )
    elif mutation == "labels":
        records[0] = replace(records[0], improvable=not records[0].improvable)
    else:
        records[0] = replace(
            records[0],
            decision=replace(records[0].decision, split=Split.HOLDOUT),
        )
    with pytest.raises(delegation.DelegationContractError):
        delegation.compare_delegation_policies(records)
