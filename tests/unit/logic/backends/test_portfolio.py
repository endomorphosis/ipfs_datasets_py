"""Unit tests for deterministic property-specific prover portfolios.

Acceptance coverage for LFV-G043 / VerificationPortfolio@1:

* Routing is deterministic and side-effect free.
* Capability gaps are explicit.
* Order cannot change final authority.
* Disagreement quarantines.
* Candidates route to reconstruction.
* Resource and assurance policy bound every plan.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from ipfs_datasets_py.logic.backends.portfolio import (
    DEFAULT_PROPERTY_POLICIES,
    VERIFICATION_PORTFOLIO_INTERFACE,
    AttemptDisposition,
    AttemptFamily,
    CapabilityGap,
    CapabilityStatus,
    PortfolioAttemptOutcome,
    PortfolioAttemptSpec,
    PortfolioCapability,
    PortfolioError,
    PortfolioObligation,
    PortfolioPlan,
    PortfolioResourcePolicy,
    PortfolioRole,
    PortfolioSelection,
    PortfolioVerdict,
    PropertyPortfolioPolicy,
    VerificationPortfolio,
    assurance_satisfies,
    default_required_authority,
    family_default_authority,
    plan_portfolio,
    select_portfolio,
)
from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds
from ipfs_datasets_py.logic.software_verification.properties import PropertyKind


def _obligation(
    property_kind: PropertyKind = PropertyKind.THEOREM,
    *,
    required_assurance: EvidenceAuthority = EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    obligation_id: str = "obl:example",
    statement: str = "forall x. P(x) -> Q(x)",
) -> PortfolioObligation:
    return PortfolioObligation(
        obligation_id=obligation_id,
        property_kind=property_kind,
        statement=statement,
        required_assurance=required_assurance,
    )


def _capability(
    backend_id: str,
    family: AttemptFamily,
    *,
    status: CapabilityStatus = CapabilityStatus.AVAILABLE,
    reconstruction_capable: bool = False,
) -> PortfolioCapability:
    return PortfolioCapability(
        backend_id=backend_id,
        family=family,
        status=status,
        reconstruction_capable=reconstruction_capable,
    )


def _outcome_from_spec(
    spec: PortfolioAttemptSpec,
    status: ResultStatus,
    *,
    conclusive_counterexample: bool = False,
    achieved_assurance: EvidenceAuthority = EvidenceAuthority.BOUNDED,
    detail: str = "",
) -> PortfolioAttemptOutcome:
    return PortfolioAttemptOutcome(
        attempt_id=spec.attempt_id,
        backend_id=spec.backend_id,
        status=status,
        authority=spec.result_authority,
        role=spec.role,
        stage=spec.stage,
        conclusive_counterexample=conclusive_counterexample,
        achieved_assurance=achieved_assurance,
        detail=detail,
    )


def test_interface_identity_and_default_policies_cover_every_property_kind() -> None:
    assert VERIFICATION_PORTFOLIO_INTERFACE == "VerificationPortfolio@1"
    portfolio = VerificationPortfolio()
    assert set(portfolio.policies) == set(PropertyKind)
    assert set(DEFAULT_PROPERTY_POLICIES) == set(PropertyKind)
    for kind in PropertyKind:
        policy = portfolio.policy_for(kind)
        assert policy.property_kind is kind
        assert policy.attempts
        assert isinstance(policy.resource_policy, PortfolioResourcePolicy)


def test_plan_is_deterministic_and_side_effect_free() -> None:
    portfolio = VerificationPortfolio()
    obligation = _obligation(PropertyKind.SATISFIABILITY)
    first = portfolio.plan(obligation)
    second = portfolio.plan(obligation)
    third = plan_portfolio(obligation.to_dict())

    assert first == second
    assert first.digest == second.digest == third.digest
    assert first.interface == VERIFICATION_PORTFOLIO_INTERFACE
    assert first.attempts == tuple(
        sorted(first.attempts, key=lambda item: (item.stage, item.backend_id, item.attempt_id))
    )
    assert {item.family for item in first.attempts} <= {
        AttemptFamily.SOLVER,
        AttemptFamily.ATP,
        AttemptFamily.MODEL_CHECKER,
        AttemptFamily.MONITOR,
        AttemptFamily.POLICY,
        AttemptFamily.PROTOCOL,
        AttemptFamily.HYPERPROPERTY,
        AttemptFamily.KERNEL,
        AttemptFamily.ORCHESTRATOR,
        AttemptFamily.ADVISOR,
    }


def test_plan_covers_all_attempt_families_across_default_policies() -> None:
    portfolio = VerificationPortfolio()
    seen: set[AttemptFamily] = set()
    for kind in PropertyKind:
        plan = portfolio.plan(_obligation(kind, required_assurance=EvidenceAuthority.BOUNDED))
        seen.update(item.family for item in plan.attempts)
    # Core families required by the goal embedding query.
    for required in (
        AttemptFamily.SOLVER,
        AttemptFamily.ATP,
        AttemptFamily.MODEL_CHECKER,
        AttemptFamily.MONITOR,
        AttemptFamily.POLICY,
        AttemptFamily.PROTOCOL,
        AttemptFamily.HYPERPROPERTY,
        AttemptFamily.KERNEL,
    ):
        assert required in seen


def test_resource_and_assurance_policy_bound_every_plan() -> None:
    bounds = ExecutionBounds(
        timeout_ms=12_000,
        max_steps=50,
        max_memory_bytes=1024,
        max_output_bytes=2048,
    )
    resource = PortfolioResourcePolicy(bounds=bounds, max_parallel=2, max_attempts=16)
    portfolio = VerificationPortfolio()
    plan = portfolio.plan(
        _obligation(
            PropertyKind.AUTHORIZATION,
            required_assurance=EvidenceAuthority.ADVISORY,
        ),
        resource_policy=resource,
    )

    assert plan.resource_policy == resource
    assert plan.resource_policy.bounds.timeout_ms == 12_000
    assert plan.required_assurance is EvidenceAuthority.BOUNDED  # policy minimum
    assert plan.required_authority is ResultAuthority.AUTHORIZATION
    assert len(plan.attempts) <= plan.resource_policy.max_attempts


def test_capability_gaps_are_explicit_and_sorted() -> None:
    portfolio = VerificationPortfolio()
    capabilities = (
        _capability("z3", AttemptFamily.SOLVER, status=CapabilityStatus.UNAVAILABLE),
        _capability(
            "cvc5", AttemptFamily.SOLVER, status=CapabilityStatus.QUARANTINED
        ),
    )
    plan = portfolio.plan(
        _obligation(
            PropertyKind.SATISFIABILITY,
            required_assurance=EvidenceAuthority.BOUNDED,
        ),
        capabilities=capabilities,
    )

    assert plan.capability_gaps
    assert all(isinstance(gap, CapabilityGap) for gap in plan.capability_gaps)
    assert plan.capability_gaps == tuple(
        sorted(
            plan.capability_gaps,
            key=lambda item: (item.backend_id, item.family.value, item.reason),
        )
    )
    assert {item.backend_id for item in plan.capability_gaps} == {"cvc5", "z3"}
    assert all(not item.runnable for item in plan.attempts)
    assert all(item.gap_reason for item in plan.attempts)


def test_theorem_candidates_route_to_reconstruction() -> None:
    portfolio = VerificationPortfolio()
    plan = portfolio.plan(
        _obligation(
            PropertyKind.THEOREM,
            required_assurance=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        )
    )

    assert plan.candidate_attempts
    assert plan.reconstruction_attempts
    assert all(
        item.requires_candidate and item.family is AttemptFamily.KERNEL
        for item in plan.reconstruction_attempts
    )
    assert all(
        item.role is PortfolioRole.CANDIDATE for item in plan.candidate_attempts
    )

    # Positive candidates alone never prove.
    candidate = plan.candidate_attempts[0]
    outcomes = [
        _outcome_from_spec(
            candidate,
            ResultStatus.CANDIDATE,
            achieved_assurance=EvidenceAuthority.ADVISORY,
        )
    ]
    selection = portfolio.select(plan, outcomes)
    assert selection.verdict is PortfolioVerdict.INCONCLUSIVE
    assert candidate.attempt_id in selection.candidate_attempt_ids
    assert not selection.authority_attempt_ids
    assert "reconstruction" in selection.reason


def test_reconstruction_promotes_candidates_to_authority() -> None:
    portfolio = VerificationPortfolio()
    plan = portfolio.plan(
        _obligation(
            PropertyKind.THEOREM,
            required_assurance=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        )
    )
    candidate = plan.candidate_attempts[0]
    reconstruction = plan.reconstruction_attempts[0]
    outcomes = [
        _outcome_from_spec(
            candidate,
            ResultStatus.CANDIDATE,
            achieved_assurance=EvidenceAuthority.ADVISORY,
        ),
        _outcome_from_spec(
            reconstruction,
            ResultStatus.RECONSTRUCTED,
            achieved_assurance=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        ),
    ]
    selection = portfolio.select(plan, outcomes)
    assert selection.verdict is PortfolioVerdict.PROVED
    assert reconstruction.attempt_id in selection.authority_attempt_ids
    assert reconstruction.attempt_id in selection.reconstruction_attempt_ids
    assert candidate.attempt_id in selection.candidate_attempt_ids


def test_order_cannot_change_final_authority() -> None:
    portfolio = VerificationPortfolio()
    plan = portfolio.plan(
        _obligation(
            PropertyKind.SATISFIABILITY,
            required_assurance=EvidenceAuthority.BOUNDED,
        )
    )
    z3 = next(item for item in plan.attempts if item.backend_id == "z3")
    cvc5 = next(item for item in plan.attempts if item.backend_id == "cvc5")
    positive = [
        _outcome_from_spec(
            z3,
            ResultStatus.UNSATISFIABLE,
            achieved_assurance=EvidenceAuthority.BOUNDED,
        ),
        _outcome_from_spec(
            cvc5,
            ResultStatus.UNSATISFIABLE,
            achieved_assurance=EvidenceAuthority.BOUNDED,
        ),
    ]
    reversed_outcomes = list(reversed(positive))
    first = portfolio.select(plan, positive)
    second = portfolio.select(plan, reversed_outcomes)
    third = select_portfolio(plan, {"outcomes": [item.to_dict() for item in reversed_outcomes]})

    assert first == second == third
    assert first.digest == second.digest == third.digest
    assert first.authority_attempt_ids == tuple(
        sorted(first.authority_attempt_ids)
    )
    assert first.verdict is PortfolioVerdict.PROVED


def test_disagreement_quarantines() -> None:
    portfolio = VerificationPortfolio()
    plan = portfolio.plan(
        _obligation(
            PropertyKind.SAFETY,
            required_assurance=EvidenceAuthority.BOUNDED,
        )
    )
    tlc = next(item for item in plan.attempts if item.backend_id == "tla_tlc")
    apalache = next(item for item in plan.attempts if item.backend_id == "apalache")
    outcomes = [
        _outcome_from_spec(
            tlc,
            ResultStatus.SATISFIED,
            achieved_assurance=EvidenceAuthority.BOUNDED,
        ),
        _outcome_from_spec(
            apalache,
            ResultStatus.VIOLATED,
            conclusive_counterexample=True,
            achieved_assurance=EvidenceAuthority.BOUNDED,
        ),
    ]
    selection = portfolio.select(plan, outcomes)
    assert selection.verdict is PortfolioVerdict.QUARANTINED
    assert selection.disagreement is True
    assert selection.authority_attempt_ids == ()
    assert selection.counterexample_attempt_id == ""
    assert set(selection.quarantined_attempt_ids) == {
        tlc.attempt_id,
        apalache.attempt_id,
    }
    assert all(
        disposition is AttemptDisposition.QUARANTINED
        for attempt_id, disposition in selection.dispositions
        if attempt_id in selection.quarantined_attempt_ids
    )


def test_disagreement_quarantine_is_order_independent() -> None:
    portfolio = VerificationPortfolio()
    plan = portfolio.plan(
        _obligation(
            PropertyKind.SAFETY,
            required_assurance=EvidenceAuthority.BOUNDED,
        )
    )
    tlc = next(item for item in plan.attempts if item.backend_id == "tla_tlc")
    apalache = next(item for item in plan.attempts if item.backend_id == "apalache")
    a = [
        _outcome_from_spec(tlc, ResultStatus.SATISFIED),
        _outcome_from_spec(
            apalache, ResultStatus.VIOLATED, conclusive_counterexample=True
        ),
    ]
    b = list(reversed(a))
    assert portfolio.select(plan, a) == portfolio.select(plan, b)


def test_conclusive_counterexample_without_positive_authority_disproves() -> None:
    portfolio = VerificationPortfolio()
    plan = portfolio.plan(
        _obligation(
            PropertyKind.SECRECY,
            required_assurance=EvidenceAuthority.BOUNDED,
        )
    )
    tamarin = next(item for item in plan.attempts if item.backend_id == "tamarin")
    selection = portfolio.select(
        plan,
        [
            _outcome_from_spec(
                tamarin,
                ResultStatus.ATTACK_FOUND,
                conclusive_counterexample=True,
            )
        ],
    )
    assert selection.verdict is PortfolioVerdict.DISPROVED
    assert selection.counterexample_attempt_id == tamarin.attempt_id
    assert selection.disagreement is False


def test_insufficient_assurance_is_inconclusive() -> None:
    portfolio = VerificationPortfolio()
    plan = portfolio.plan(
        _obligation(
            PropertyKind.SATISFIABILITY,
            required_assurance=EvidenceAuthority.AUTHORITATIVE,
        )
    )
    z3 = next(item for item in plan.attempts if item.backend_id == "z3")
    selection = portfolio.select(
        plan,
        [
            _outcome_from_spec(
                z3,
                ResultStatus.UNSATISFIABLE,
                achieved_assurance=EvidenceAuthority.BOUNDED,
            )
        ],
    )
    assert selection.verdict is PortfolioVerdict.INCONCLUSIVE
    assert selection.achieved_assurance is EvidenceAuthority.BOUNDED
    assert "required" in selection.reason


def test_gap_only_portfolio_is_unavailable() -> None:
    portfolio = VerificationPortfolio()
    plan = portfolio.plan(
        _obligation(
            PropertyKind.TRACE_CONFORMANCE,
            required_assurance=EvidenceAuthority.BOUNDED,
        ),
        capabilities=(
            _capability(
                "runtime_mtl",
                AttemptFamily.MONITOR,
                status=CapabilityStatus.UNAVAILABLE,
            ),
        ),
    )
    selection = portfolio.select(plan, ())
    assert selection.verdict is PortfolioVerdict.UNAVAILABLE
    assert plan.capability_gaps


def test_kernel_not_reconstruction_capable_is_explicit_gap() -> None:
    portfolio = VerificationPortfolio()
    capabilities = (
        _capability(
            "lean",
            AttemptFamily.KERNEL,
            status=CapabilityStatus.AVAILABLE,
            reconstruction_capable=False,
        ),
        _capability(
            "rocq",
            AttemptFamily.KERNEL,
            status=CapabilityStatus.AVAILABLE,
            reconstruction_capable=True,
        ),
        _capability(
            "isabelle",
            AttemptFamily.KERNEL,
            status=CapabilityStatus.AVAILABLE,
            reconstruction_capable=True,
        ),
        _capability("hammer", AttemptFamily.ORCHESTRATOR),
        _capability("vampire", AttemptFamily.ATP),
        _capability("eprover", AttemptFamily.ATP),
        _capability("z3", AttemptFamily.SOLVER),
    )
    plan = portfolio.plan(
        _obligation(
            PropertyKind.THEOREM,
            required_assurance=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        ),
        capabilities=capabilities,
    )
    lean = next(item for item in plan.attempts if item.backend_id == "lean")
    assert lean.runnable is False
    assert "reconstruction-capable" in lean.gap_reason
    assert any(gap.backend_id == "lean" for gap in plan.capability_gaps)


def test_records_round_trip() -> None:
    portfolio = VerificationPortfolio()
    plan = portfolio.plan(_obligation(PropertyKind.HYPERPROPERTY))
    assert PortfolioPlan.from_dict(plan.to_dict()) == plan
    assert PortfolioObligation.from_dict(plan.obligation.to_dict()) == plan.obligation
    for attempt in plan.attempts:
        assert PortfolioAttemptSpec.from_dict(attempt.to_dict()) == attempt

    outcome = _outcome_from_spec(
        plan.attempts[0],
        ResultStatus.SATISFIED,
        achieved_assurance=EvidenceAuthority.BOUNDED,
    )
    assert PortfolioAttemptOutcome.from_dict(outcome.to_dict()) == outcome
    selection = portfolio.select(plan, [outcome])
    assert PortfolioSelection.from_dict(selection.to_dict()) == selection
    resource = PortfolioResourcePolicy.from_dict(plan.resource_policy.to_dict())
    assert resource == plan.resource_policy


def test_frozen_records_reject_mutation() -> None:
    obligation = _obligation()
    with pytest.raises(FrozenInstanceError):
        obligation.statement = "mutated"  # type: ignore[misc]


def test_default_required_authority_and_family_mapping() -> None:
    assert default_required_authority(PropertyKind.SECRECY) is ResultAuthority.PROTOCOL
    assert default_required_authority(PropertyKind.TRACE_CONFORMANCE) is ResultAuthority.MONITOR
    assert family_default_authority(AttemptFamily.KERNEL) is ResultAuthority.RECONSTRUCTION
    assert family_default_authority("solver") is ResultAuthority.SATISFIABILITY
    assert assurance_satisfies(
        EvidenceAuthority.AUTHORITATIVE, EvidenceAuthority.BOUNDED
    )
    assert not assurance_satisfies(
        EvidenceAuthority.ADVISORY, EvidenceAuthority.BOUNDED
    )


def test_invalid_policy_and_outcome_fail_closed() -> None:
    with pytest.raises(PortfolioError):
        PropertyPortfolioPolicy(
            property_kind=PropertyKind.SAFETY,
            attempts=(),
        )
    portfolio = VerificationPortfolio()
    plan = portfolio.plan(_obligation(PropertyKind.AUTHORIZATION))
    with pytest.raises(PortfolioError, match="not in the plan"):
        portfolio.select(
            plan,
            [
                PortfolioAttemptOutcome(
                    attempt_id="attempt:missing",
                    backend_id="missing",
                    status=ResultStatus.AUTHORIZED,
                    authority=ResultAuthority.AUTHORIZATION,
                    role=PortfolioRole.AUTHORITY,
                )
            ],
        )


def test_plan_and_select_facade() -> None:
    portfolio = VerificationPortfolio()
    obligation = _obligation(
        PropertyKind.AUTHORIZATION,
        required_assurance=EvidenceAuthority.BOUNDED,
    )
    plan = portfolio.plan(obligation)
    authority = plan.attempts[0]
    plan2, selection = portfolio.plan_and_select(
        obligation,
        [
            _outcome_from_spec(
                authority,
                ResultStatus.AUTHORIZED,
                achieved_assurance=EvidenceAuthority.BOUNDED,
            )
        ],
    )
    assert plan2.digest == plan.digest
    assert selection.verdict is PortfolioVerdict.PROVED


def test_custom_policy_registration() -> None:
    custom = PropertyPortfolioPolicy(
        property_kind=PropertyKind.SATISFIABILITY,
        attempts=(
            PortfolioAttemptSpec(
                attempt_id="attempt:only-z3",
                backend_id="z3",
                family=AttemptFamily.SOLVER,
                role=PortfolioRole.AUTHORITY,
                authority_capability="finite_constraint_satisfiability",
                result_authority=ResultAuthority.SATISFIABILITY,
            ),
        ),
        policy_id="custom-sat@1",
    )
    portfolio = VerificationPortfolio({PropertyKind.SATISFIABILITY: custom})
    plan = portfolio.plan(
        _obligation(
            PropertyKind.SATISFIABILITY,
            required_assurance=EvidenceAuthority.BOUNDED,
        )
    )
    assert plan.policy_id == "custom-sat@1"
    assert plan.backend_ids == ("z3",)


def test_import_has_no_process_or_network_side_effects() -> None:
    # Structural guarantee: the portfolio module must remain a pure planner.
    import ipfs_datasets_py.logic.backends.portfolio as mod

    source = open(mod.__file__, encoding="utf-8").read()
    forbidden = (
        "subprocess",
        "shutil.which",
        "socket",
        "urllib",
        "requests",
        "ThreadPoolExecutor",
        "Popen",
    )
    for token in forbidden:
        assert token not in source
