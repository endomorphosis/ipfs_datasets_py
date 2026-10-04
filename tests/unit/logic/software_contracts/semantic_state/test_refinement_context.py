"""Acceptance tests for evidence-minimizing semantic-state refinement."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.smt.compiler import term_symbol
from ipfs_datasets_py.logic.backends.smt.interpolation import (
    InterpolationStatus,
    ValidatedInterpolantReceipt,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.refinement_context import (
    CegarCheckResult,
    ContextAssertion,
    CounterexampleWitness,
    EvidenceCheck,
    RefinementContextError,
    RefinementDisposition,
    minimize_counterexample_context,
    qualify_craig_interpolant,
    run_cegar_refinement,
)
from ipfs_datasets_py.logic.verification_api import (
    COMPOSITIONAL_VERIFICATION_OPERATIONS,
    REFINEMENT_CONTEXT_INTERFACE,
    REFINEMENT_CONTEXT_OPERATIONS,
    minimize_unsat_core_context as public_minimize_unsat_core_context,
)


def _assertions() -> tuple[ContextAssertion, ...]:
    return (
        ContextAssertion("need", "source:need", "component:a", "evidence:need"),
        ContextAssertion("noise-a", "source:noise-a", "component:b", "evidence:noise-a"),
        ContextAssertion("noise-b", "source:noise-b", "component:b", "evidence:noise-b"),
    )


def _qualified_receipt(symbol: str = "predicate") -> ValidatedInterpolantReceipt:
    return ValidatedInterpolantReceipt(
        status=InterpolationStatus.VALIDATED,
        partition_a_cid="partition-a",
        partition_b_cid="partition-b",
        shared_vocabulary=(symbol,),
        interpolant=term_symbol(symbol),
        interpolant_vocabulary=(symbol,),
        provider="cvc5",
        provider_version="test",
        theory="QF_LIA",
        a_implies_i_receipt="evidence:a-implies-i",
        i_and_b_unsat_receipt="evidence:i-and-b-unsat",
        a_implies_i=True,
        i_and_b_unsat=True,
        shared_vocabulary_ok=True,
        identity_ok=True,
        bounds_ok=True,
        interpolation_api=True,
        independent_validator_version="test",
    )


def test_counterexample_context_is_reproducible_and_subset_minimal() -> None:
    witness = CounterexampleWitness(
        "witness:one", ("need", "noise-a", "noise-b"), "replay:witness:one"
    )

    result = minimize_counterexample_context(
        _assertions(),
        witness,
        lambda context: "need" in {item.assertion_id for item in context},
    )

    assert result.disposition is RefinementDisposition.MINIMIZED
    assert result.assertion_ids == ("need",)
    assert result.seed_verified is True
    assert result.subset_minimal is True
    assert result.reproducible is True
    assert result.receipt_cid.startswith("b")
    assert result.context[0].source_ref == "source:need"


def test_unsat_core_minimization_checks_every_deletion_and_public_facade() -> None:
    def is_unsat(context: tuple[ContextAssertion, ...]) -> bool:
        return {item.assertion_id for item in context} >= {"need", "noise-a"}

    result = public_minimize_unsat_core_context(
        _assertions(), ("need", "noise-a", "noise-b"), is_unsat
    )

    assert result.kind == "unsat_core"
    assert result.assertion_ids == ("need", "noise-a")
    assert result.subset_minimal is True
    assert result.interface == REFINEMENT_CONTEXT_INTERFACE
    assert set(REFINEMENT_CONTEXT_OPERATIONS) <= set(COMPOSITIONAL_VERIFICATION_OPERATIONS)


def test_incomplete_witness_and_unavailable_deletion_report_exact_missing_evidence() -> None:
    incomplete = CounterexampleWitness(
        "witness:missing",
        ("need",),
        "replay:witness:missing",
        complete=False,
        missing_evidence=("trace-step:2", "model:x"),
    )
    missing_trace = minimize_counterexample_context(_assertions(), incomplete, lambda _: True)
    assert missing_trace.disposition is RefinementDisposition.INCOMPLETE
    assert missing_trace.missing_evidence == ("model:x", "trace-step:2")

    witness = CounterexampleWitness("witness:two", ("need", "noise-a"), "replay:witness:two")
    calls = 0

    def unavailable_after_seed(_: tuple[ContextAssertion, ...]) -> EvidenceCheck:
        nonlocal calls
        calls += 1
        return EvidenceCheck(True) if calls == 1 else EvidenceCheck(None, ("replay:deleted-context",))

    unavailable = minimize_counterexample_context(_assertions(), witness, unavailable_after_seed)
    assert unavailable.disposition is RefinementDisposition.INCOMPLETE
    assert unavailable.subset_minimal is False
    assert unavailable.missing_evidence == ("replay:deleted-context",)


def test_nonreproducing_seed_is_rejected_not_reported_as_minimal() -> None:
    witness = CounterexampleWitness("witness:no", ("need",), "replay:witness:no")
    with pytest.raises(RefinementContextError, match="does not reproduce"):
        minimize_counterexample_context(_assertions(), witness, lambda _: False)


def test_only_fully_admitted_craig_interpolants_qualify_for_refinement() -> None:
    valid = qualify_craig_interpolant(_qualified_receipt("shared"))
    assert valid.qualified is True
    assert valid.predicate_ids == ("shared",)
    assert valid.missing_evidence == ()

    fallback = ValidatedInterpolantReceipt(
        status=InterpolationStatus.FALLBACK,
        partition_a_cid="partition-a",
        partition_b_cid="partition-b",
        shared_vocabulary=("shared",),
        interpolant=None,
        interpolant_vocabulary=(),
        provider="z3",
        provider_version="test",
        theory="QF_LIA",
        fallback_kind="validated_unsat_core",
        fallback_core=("partition-a", "partition-b"),
        fallback_receipt="evidence:core",
        fallback_validated=True,
    )
    rejected = qualify_craig_interpolant(fallback)
    assert rejected.qualified is False
    assert "validated-craig-interpolant" in rejected.missing_evidence
    assert "qualified-interpolation-provider:cvc5" in rejected.missing_evidence
    assert "interpolant-term" in rejected.missing_evidence


def test_cegar_converges_and_expands_only_declared_affected_abstraction() -> None:
    receipt = _qualified_receipt("refined-predicate")

    def check(_abstraction: object, iteration: int) -> CegarCheckResult:
        if iteration == 1:
            return CegarCheckResult(safe=False, spurious=True, interpolation=receipt)
        return CegarCheckResult(safe=True)

    result = run_cegar_refinement(
        {"component:a": (), "component:unaffected": ("keep",)},
        ("component:a",),
        check,
        max_iterations=3,
    )

    assert result.disposition is RefinementDisposition.CONVERGED
    assert result.iterations == 2
    assert result.expanded_abstractions == ("component:a",)
    assert result.abstraction["component:a"] == frozenset({"refined-predicate"})
    assert result.abstraction["component:unaffected"] == frozenset({"keep"})
    assert result.interpolation_receipts == (receipt.receipt_cid,)


def test_cegar_bound_and_incomplete_witness_are_never_claimed_converged() -> None:
    bounded = run_cegar_refinement(
        {"component:a": ()},
        ("component:a",),
        lambda _state, _iteration: CegarCheckResult(
            safe=False, spurious=True, interpolation=_qualified_receipt("new-predicate")
        ),
        max_iterations=1,
    )
    assert bounded.disposition is RefinementDisposition.BOUND_EXHAUSTED
    assert bounded.missing_evidence == ("cegar-convergence-within-bound",)

    incomplete_witness = CounterexampleWitness(
        "witness:incomplete",
        ("need",),
        "replay:witness:incomplete",
        complete=False,
        missing_evidence=("trace:end",),
    )
    incomplete = run_cegar_refinement(
        {"component:a": ()},
        ("component:a",),
        lambda _state, _iteration: CegarCheckResult(
            safe=False, counterexample=incomplete_witness
        ),
    )
    assert incomplete.disposition is RefinementDisposition.INCOMPLETE
    assert incomplete.missing_evidence == ("trace:end",)


def test_cegar_refuses_unqualified_interpolation_without_expanding_state() -> None:
    fallback = ValidatedInterpolantReceipt(
        status=InterpolationStatus.FALLBACK,
        partition_a_cid="partition-a",
        partition_b_cid="partition-b",
        shared_vocabulary=("shared",),
        interpolant=None,
        interpolant_vocabulary=(),
        provider="z3",
        provider_version="test",
        theory="QF_LIA",
        fallback_kind="validated_unsat_core",
        fallback_receipt="evidence:core",
        fallback_validated=True,
    )
    result = run_cegar_refinement(
        {"component:a": ("original",)},
        ("component:a",),
        lambda _state, _iteration: CegarCheckResult(
            safe=False, spurious=True, interpolation=fallback
        ),
    )

    assert result.disposition is RefinementDisposition.UNQUALIFIED
    assert result.expanded_abstractions == ()
    assert result.abstraction["component:a"] == frozenset({"original"})
    assert "validated-craig-interpolant" in result.missing_evidence
