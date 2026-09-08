"""Focused tests for the bounded interpolation/core-driven CEGAR loop."""

from __future__ import annotations

from typing import Any

import pytest
from ipfs_datasets_py.logic.backends.smt.compiler import (
    SmtTerm,
    SmtTermKind,
    term_int,
    term_symbol,
    term_true,
)
from ipfs_datasets_py.logic.backends.smt.incremental import SmtCheckStatus
from ipfs_datasets_py.logic.backends.smt.interpolation import (
    InterpolationStatus,
    ValidatedInterpolantReceipt,
)
from ipfs_datasets_py.logic.software_verification.cegar import (
    CEGAR_INTERFACE,
    CEGAR_RECEIPT_SCHEMA,
    CegarAssignment,
    CegarBudget,
    CegarDisposition,
    CegarError,
    CegarPredicate,
    CegarQueryKind,
    CegarRunReceipt,
    CegarSolverObservation,
    CegarTrace,
    CegarTraceStep,
    CegarTransition,
    CegarTransitionSystem,
    IncrementalSmtCegarSolver,
    LocalConjunctionSolver,
    PredicateOrigin,
    RefinementAuthority,
    ScriptedCegarSolver,
    TraceClassification,
    reviewed_predicate,
    run_cegar,
)


def _lt(name: str, value: int) -> SmtTerm:
    return SmtTerm(SmtTermKind.LT, arguments=(term_symbol(name), term_int(value)))


def _ge(name: str, value: int) -> SmtTerm:
    return SmtTerm(SmtTermKind.GE, arguments=(term_symbol(name), term_int(value)))


def _system(
    *,
    system_id: str,
    assigned: int,
    extra_identities: dict[str, str] | None = None,
) -> CegarTransitionSystem:
    identities = {
        "program_cid": f"bprogram{system_id.replace(':', '')}",
        "property_cid": "bpropertysafety",
    }
    if extra_identities:
        identities.update(extra_identities)
    return CegarTransitionSystem(
        system_id=system_id,
        variables=("x",),
        locations=("loc0", "loc1", "err"),
        initial_location="loc0",
        error_locations=("err",),
        initial_condition=term_true(),
        transitions=(
            CegarTransition(
                "set-x",
                "loc0",
                "loc1",
                assignments=(CegarAssignment("x", term_int(assigned)),),
                source_ref="stmt:set-x",
            ),
            CegarTransition(
                "to-error",
                "loc1",
                "err",
                guard=_lt("x", 0),
                source_ref="stmt:to-error",
            ),
        ),
        source_identities=identities,
    )


def _spurious_system() -> CegarTransitionSystem:
    return _system(system_id="spurious-nonneg", assigned=0)


def _real_system() -> CegarTransitionSystem:
    return _system(system_id="real-negative", assigned=-1)


def _safe_cfg() -> CegarTransitionSystem:
    return CegarTransitionSystem(
        system_id="safe-disconnected",
        variables=("x",),
        locations=("loc0", "err"),
        initial_location="loc0",
        error_locations=("err",),
        initial_condition=term_true(),
        transitions=(
            CegarTransition(
                "stay",
                "loc0",
                "loc0",
                assignments=(CegarAssignment("x", term_int(0)),),
            ),
        ),
        source_identities={"program_cid": "bprogramsafe", "property_cid": "bpropertysafety"},
    )


def _validated_interpolant(formula: SmtTerm) -> ValidatedInterpolantReceipt:
    return ValidatedInterpolantReceipt(
        status=InterpolationStatus.VALIDATED,
        partition_a_cid="bpartitionaaaaaaaa",
        partition_b_cid="bpartitionbbbbbbbb",
        shared_vocabulary=("x",),
        interpolant=formula,
        interpolant_vocabulary=("x",),
        provider="cvc5",
        provider_version="1.3.3",
        theory="QF_LIA",
        interpolant_cid="binterpolantvalidated",
        a_implies_i=True,
        i_and_b_unsat=True,
        shared_vocabulary_ok=True,
        identity_ok=True,
        bounds_ok=True,
        interpolation_api=True,
    )


def _unavailable_interpolant() -> ValidatedInterpolantReceipt:
    return ValidatedInterpolantReceipt(
        status=InterpolationStatus.UNAVAILABLE,
        partition_a_cid="bpartitionaaaaaaaa",
        partition_b_cid="bpartitionbbbbbbbb",
        shared_vocabulary=("x",),
        interpolant=None,
        interpolant_vocabulary=(),
        provider="cvc5",
        provider_version="unavailable",
        theory="QF_LIA",
        reason="interpolation unavailable in test double",
    )


class _FixedInterpolator:
    def __init__(self, receipt: ValidatedInterpolantReceipt) -> None:
        self.receipt = receipt
        self.calls = 0

    def interpolate(self, partition_a: SmtTerm, partition_b: SmtTerm, **_kwargs: Any) -> ValidatedInterpolantReceipt:
        self.calls += 1
        assert isinstance(partition_a, SmtTerm)
        assert isinstance(partition_b, SmtTerm)
        return self.receipt


class _KindSolver:
    def __init__(self, overrides: dict[CegarQueryKind, CegarSolverObservation]) -> None:
        self.overrides = overrides
        self.inner = LocalConjunctionSolver()

    def check(self, query: Any) -> CegarSolverObservation:
        kind = query.kind if isinstance(query.kind, CegarQueryKind) else CegarQueryKind(query.kind)
        if kind in self.overrides:
            return self.overrides[kind]
        return self.inner.check(query)


def _run_spurious(**kwargs: Any) -> CegarRunReceipt:
    return run_cegar(
        _spurious_system(),
        solver=kwargs.pop("solver", LocalConjunctionSolver()),
        **kwargs,
    )


def test_closed_dispositions_are_exactly_the_required_terminals() -> None:
    assert {item.value for item in CegarDisposition} == {
        "proved",
        "disproved",
        "unknown",
        "timeout",
        "unavailable",
        "budget-exhausted",
    }


def test_safe_cfg_is_proved_without_refinement() -> None:
    receipt = run_cegar(_safe_cfg(), solver=LocalConjunctionSolver())
    assert receipt.disposition is CegarDisposition.PROVED
    assert receipt.counterexamples == ()
    assert receipt.spurious_traces == ()
    assert receipt.refinements == ()
    assert receipt.schema == CEGAR_RECEIPT_SCHEMA
    assert receipt.interface == CEGAR_INTERFACE
    assert receipt.receipt_cid.startswith("b")
    assert receipt.source_identities["program_cid"] == "bprogramsafe"
    assert receipt.iterations
    assert receipt.iterations[-1].search_complete is True
    assert receipt.iterations[-1].trace is None


def test_spurious_trace_refines_with_validated_interpolant() -> None:
    interpolator = _FixedInterpolator(_validated_interpolant(_lt("x", 0)))
    receipt = _run_spurious(
        interpolator=interpolator,
        budget=CegarBudget(allow_unsat_core=False, allow_weakest_precondition=False),
    )
    assert receipt.disposition is CegarDisposition.PROVED
    assert interpolator.calls >= 1
    assert receipt.spurious_traces
    assert all(item.classification is TraceClassification.SPURIOUS for item in receipt.spurious_traces)
    assert receipt.counterexamples == ()
    assert receipt.iterations[-1].search_complete is True
    assert receipt.refinements
    refinement = receipt.refinements[0]
    assert refinement.authority is RefinementAuthority.VALIDATED_INTERPOLANT
    assert refinement.interpolant_status == InterpolationStatus.VALIDATED.value
    assert refinement.interpolant_cid == "binterpolantvalidated"
    assert refinement.partition_a_cid.startswith("b")
    assert refinement.partition_b_cid.startswith("b")
    assert all(isinstance(item, str) for item in refinement.shared_vocabulary)
    assert not refinement.shared_vocabulary or any(
        item == "x" or item.startswith("x@") for item in refinement.shared_vocabulary
    )
    assert refinement.theory == "QF_LIA"
    assert refinement.provider == "cvc5"
    assert refinement.bounds.theory == "QF_LIA"
    assert refinement.source_identities["program_cid"].startswith("bprogram")
    assert any(item.origin is PredicateOrigin.INTERPOLANT for item in refinement.predicates)


def test_spurious_trace_refines_with_validated_unsat_core() -> None:
    receipt = _run_spurious(
        interpolator=_FixedInterpolator(_unavailable_interpolant()),
        budget=CegarBudget(
            allow_interpolation=True,
            allow_unsat_core=True,
            allow_weakest_precondition=False,
            allow_reviewed_predicates=False,
        ),
    )
    assert receipt.disposition is CegarDisposition.PROVED
    assert receipt.spurious_traces
    assert receipt.counterexamples == ()
    assert receipt.refinements
    refinement = receipt.refinements[0]
    assert refinement.authority is RefinementAuthority.VALIDATED_UNSAT_CORE
    assert refinement.interpolant_cid == ""
    assert refinement.fallback_kind == "validated_unsat_core"
    assert refinement.fallback_core
    assert refinement.fallback_receipt
    assert refinement.theory == "QF_LIA"
    assert refinement.source_identities["property_cid"] == "bpropertysafety"


def test_spurious_trace_refines_with_weakest_precondition() -> None:
    receipt = _run_spurious(
        interpolator=_FixedInterpolator(_unavailable_interpolant()),
        budget=CegarBudget(
            allow_interpolation=False,
            allow_unsat_core=False,
            allow_weakest_precondition=True,
            allow_reviewed_predicates=False,
        ),
    )
    assert receipt.disposition is CegarDisposition.PROVED
    refinement = receipt.refinements[0]
    assert refinement.authority is RefinementAuthority.WEAKEST_PRECONDITION
    assert refinement.interpolant_cid == ""
    assert any(item.origin is PredicateOrigin.WEAKEST_PRECONDITION for item in refinement.predicates)


def test_spurious_trace_refines_with_reviewed_predicate() -> None:
    predicate = reviewed_predicate(
        "neg-x",
        _lt("x", 0),
        reviewer="reviewer:lgcvf-061",
        review_ref="review:neg-x",
    )
    receipt = _run_spurious(
        interpolator=_FixedInterpolator(_unavailable_interpolant()),
        reviewed_predicates=(predicate,),
        budget=CegarBudget(
            allow_interpolation=False,
            allow_unsat_core=False,
            allow_weakest_precondition=False,
            allow_reviewed_predicates=True,
        ),
    )
    assert receipt.disposition is CegarDisposition.PROVED
    refinement = receipt.refinements[0]
    assert refinement.authority is RefinementAuthority.REVIEWED_PREDICATE
    assert refinement.predicates[0].predicate_id == "neg-x"
    assert refinement.predicates[0].reviewed is True
    assert refinement.interpolant_cid == ""
    assert refinement.provider == "reviewed-predicate"


def test_unreviewed_predicate_is_rejected() -> None:
    with pytest.raises(CegarError, match="reviewed"):
        CegarPredicate(
            predicate_id="raw",
            formula=_lt("x", 0),
            origin=PredicateOrigin.REVIEWED,
            reviewed=False,
        )
    with pytest.raises(CegarError, match="reviewed"):
        run_cegar(
            _spurious_system(),
            reviewed_predicates=(
                CegarPredicate(
                    predicate_id="wp-like",
                    formula=_lt("x", 0),
                    origin=PredicateOrigin.WEAKEST_PRECONDITION,
                ),
            ),
            solver=LocalConjunctionSolver(),
        )


def test_real_trace_remains_counterexample() -> None:
    receipt = run_cegar(
        _real_system(),
        solver=LocalConjunctionSolver(),
        interpolator=_FixedInterpolator(_validated_interpolant(_lt("x", 0))),
        reviewed_predicates=(
            reviewed_predicate(
                "neg-x",
                _lt("x", 0),
                reviewer="reviewer:lgcvf-061",
                review_ref="review:neg-x",
            ),
        ),
    )
    assert receipt.disposition is CegarDisposition.DISPROVED
    assert receipt.refinements == ()
    assert receipt.spurious_traces == ()
    assert len(receipt.counterexamples) == 1
    trace = receipt.counterexamples[0]
    assert trace.classification is TraceClassification.REAL
    assert trace.locations == ("loc0", "loc1", "err")
    assert trace.transition_ids == ("set-x", "to-error")
    assert trace.model
    assert trace.trace_cid.startswith("b")
    replay = run_cegar(_real_system(), solver=LocalConjunctionSolver())
    assert replay.disposition is CegarDisposition.DISPROVED
    assert replay.counterexamples[0].trace_cid == trace.trace_cid
    assert replay.counterexamples[0].locations == trace.locations


def test_real_trace_is_not_refined_away() -> None:
    first = run_cegar(_real_system(), solver=LocalConjunctionSolver())
    second = run_cegar(
        _real_system(),
        solver=LocalConjunctionSolver(),
        budget=CegarBudget(max_iterations=8, max_predicates=8),
        reviewed_predicates=(
            reviewed_predicate(
                "ge-zero",
                _ge("x", 0),
                reviewer="reviewer:lgcvf-061",
                review_ref="review:ge-zero",
            ),
        ),
    )
    assert first.disposition is CegarDisposition.DISPROVED
    assert second.disposition is CegarDisposition.DISPROVED
    assert first.counterexamples[0].trace_cid == second.counterexamples[0].trace_cid
    assert second.refinements == ()


def test_iteration_budget_exhausts_on_remaining_spurious_trace() -> None:
    receipt = _run_spurious(
        interpolator=_FixedInterpolator(_unavailable_interpolant()),
        budget=CegarBudget(max_iterations=1),
    )
    assert receipt.disposition is CegarDisposition.BUDGET_EXHAUSTED
    assert receipt.spurious_traces
    assert receipt.counterexamples == ()
    assert "max_iterations" in receipt.reason
    truncated = run_cegar(
        _real_system(),
        solver=LocalConjunctionSolver(),
        budget=CegarBudget(max_trace_length=1),
    )
    assert truncated.disposition is CegarDisposition.BUDGET_EXHAUSTED
    assert truncated.counterexamples == ()
    assert truncated.spurious_traces == ()
    assert "max_trace_length" in truncated.reason
    states = run_cegar(
        _real_system(),
        solver=LocalConjunctionSolver(),
        budget=CegarBudget(max_abstract_states=1),
    )
    assert states.disposition is CegarDisposition.BUDGET_EXHAUSTED
    assert states.counterexamples == ()
    assert "abstract state" in states.reason


def test_predicate_budget_exhausts_when_refinement_cannot_grow() -> None:
    receipt = _run_spurious(
        interpolator=_FixedInterpolator(_validated_interpolant(_ge("x", -1000))),
        budget=CegarBudget(
            max_predicates=1,
            allow_unsat_core=False,
            allow_weakest_precondition=False,
            allow_reviewed_predicates=False,
        ),
    )
    assert receipt.disposition is CegarDisposition.BUDGET_EXHAUSTED
    assert receipt.spurious_traces
    assert "max_predicates" in receipt.reason


def test_timeout_terminates() -> None:
    ticks = {"n": 0}

    def _clock() -> float:
        ticks["n"] += 1
        return 0.0 if ticks["n"] <= 2 else 10.0

    receipt = run_cegar(
        _spurious_system(),
        solver=LocalConjunctionSolver(),
        budget=CegarBudget(timeout_ms=5),
        clock=_clock,
    )
    assert receipt.disposition is CegarDisposition.TIMEOUT
    assert receipt.counterexamples == ()
    assert "timeout" in receipt.reason


def test_path_timeout_terminates() -> None:
    receipt = run_cegar(
        _spurious_system(),
        solver=_KindSolver(
            {
                CegarQueryKind.PATH: CegarSolverObservation(
                    status=SmtCheckStatus.TIMEOUT,
                    reason="scripted path timeout",
                    provider="script",
                    provider_version="1",
                )
            }
        ),
    )
    assert receipt.disposition is CegarDisposition.TIMEOUT
    assert "timeout" in receipt.reason


def test_unavailable_solver_terminates() -> None:
    receipt = run_cegar(
        _spurious_system(),
        solver=_KindSolver(
            {
                CegarQueryKind.ABSTRACT_INIT: CegarSolverObservation(
                    status=SmtCheckStatus.UNAVAILABLE,
                    reason="z3 Python API is not installed",
                    provider="z3",
                    provider_version="unavailable",
                )
            }
        ),
    )
    assert receipt.disposition is CegarDisposition.UNAVAILABLE
    assert "not installed" in receipt.reason
    assert receipt.provider == "z3"


def test_unknown_path_check_terminates() -> None:
    receipt = run_cegar(
        _spurious_system(),
        solver=_KindSolver(
            {
                CegarQueryKind.PATH: CegarSolverObservation(
                    status=SmtCheckStatus.UNKNOWN,
                    reason="scripted unknown",
                    provider="script",
                    provider_version="1",
                )
            }
        ),
    )
    assert receipt.disposition is CegarDisposition.UNKNOWN
    assert "unknown" in receipt.reason


def test_unknown_when_no_refinement_authority_applies() -> None:
    receipt = _run_spurious(
        interpolator=_FixedInterpolator(_unavailable_interpolant()),
        budget=CegarBudget(
            allow_interpolation=False,
            allow_unsat_core=False,
            allow_weakest_precondition=False,
            allow_reviewed_predicates=False,
        ),
    )
    assert receipt.disposition is CegarDisposition.UNKNOWN
    assert receipt.spurious_traces
    assert receipt.refinements == ()
    assert "reviewed predicate" in receipt.reason


def test_every_run_has_exactly_one_closed_disposition() -> None:
    cases = [
        test_safe_cfg_is_proved_without_refinement,
        test_real_trace_remains_counterexample,
        test_iteration_budget_exhausts_on_remaining_spurious_trace,
        test_timeout_terminates,
        test_unavailable_solver_terminates,
        test_unknown_path_check_terminates,
    ]
    for case in cases:
        case()


def test_refinement_binds_partitions_vocabulary_theory_provider_bounds_and_identities() -> None:
    receipt = _run_spurious(
        interpolator=_FixedInterpolator(_validated_interpolant(_ge("x", 0))),
        budget=CegarBudget(allow_unsat_core=False, allow_weakest_precondition=False),
    )
    refinement = receipt.refinements[0]
    payload = refinement.to_dict()
    for key in (
        "partition_a_cid",
        "partition_b_cid",
        "shared_vocabulary",
        "theory",
        "provider",
        "provider_version",
        "bounds",
        "source_identities",
    ):
        assert key in payload
    assert payload["bounds"]["timeout_ms"] > 0
    assert payload["source_identities"]["program_cid"]
    assert payload["theory"] == "QF_LIA"
    assert refinement.refinement_cid.startswith("b")


def test_non_interpolant_refinement_does_not_fabricate_an_interpolant() -> None:
    core = _run_spurious(
        interpolator=_FixedInterpolator(_unavailable_interpolant()),
        budget=CegarBudget(allow_weakest_precondition=False, allow_reviewed_predicates=False),
    )
    wp = _run_spurious(
        interpolator=_FixedInterpolator(_unavailable_interpolant()),
        budget=CegarBudget(allow_interpolation=False, allow_unsat_core=False),
    )
    for receipt in (core, wp):
        assert receipt.disposition is CegarDisposition.PROVED
        for refinement in receipt.refinements:
            assert refinement.interpolant_cid == ""
            assert refinement.authority is not RefinementAuthority.VALIDATED_INTERPOLANT


def test_receipt_identity_is_stable_for_identical_runs() -> None:
    first = run_cegar(_real_system(), solver=LocalConjunctionSolver())
    second = run_cegar(_real_system(), solver=LocalConjunctionSolver())
    assert first.receipt_cid == second.receipt_cid
    assert first.counterexamples[0].trace_cid == second.counterexamples[0].trace_cid


def test_malformed_system_is_rejected() -> None:
    with pytest.raises(CegarError, match="source identities"):
        CegarTransitionSystem(
            system_id="missing-ids",
            variables=("x",),
            locations=("loc0", "err"),
            initial_location="loc0",
            error_locations=("err",),
            initial_condition=term_true(),
            transitions=(),
            source_identities={},
        )
    with pytest.raises(CegarError, match="undeclared variables"):
        CegarTransitionSystem(
            system_id="bad-var",
            variables=("x",),
            locations=("loc0", "err"),
            initial_location="loc0",
            error_locations=("err",),
            initial_condition=term_true(),
            transitions=(CegarTransition("go", "loc0", "err", guard=_lt("y", 0)),),
            source_identities={"program_cid": "bprogram"},
        )
    with pytest.raises(CegarError, match="positive"):
        CegarBudget(max_iterations=0)


def test_disproved_receipt_requires_a_real_counterexample() -> None:
    with pytest.raises(CegarError, match="real counterexample"):
        CegarRunReceipt(
            disposition=CegarDisposition.DISPROVED,
            system_cid="bsystem",
            theory="QF_LIA",
            provider="local",
            provider_version="1",
            bounds=CegarBudget(),
            source_identities={"program_cid": "bprogram"},
            predicates=(),
            refinements=(),
            counterexamples=(),
            spurious_traces=(),
            iterations=(),
        )
    with pytest.raises(CegarError, match="incomplete search"):
        CegarRunReceipt(
            disposition=CegarDisposition.PROVED,
            system_cid="bsystem",
            theory="QF_LIA",
            provider="local",
            provider_version="1",
            bounds=CegarBudget(),
            source_identities={"program_cid": "bprogram"},
            predicates=(),
            refinements=(),
            counterexamples=(),
            spurious_traces=(),
            iterations=(),
        )


def test_spurious_list_cannot_hold_a_real_trace() -> None:
    real = CegarTrace(
        locations=("loc0", "err"),
        steps=(CegarTraceStep("go", "loc0", "err"),),
        classification=TraceClassification.REAL,
    )
    with pytest.raises(CegarError, match="spurious_traces"):
        CegarRunReceipt(
            disposition=CegarDisposition.UNKNOWN,
            system_cid="bsystem",
            theory="QF_LIA",
            provider="local",
            provider_version="1",
            bounds=CegarBudget(),
            source_identities={"program_cid": "bprogram"},
            predicates=(),
            refinements=(),
            counterexamples=(),
            spurious_traces=(real,),
            iterations=(),
        )


def test_scripted_solver_can_answer_by_query_id() -> None:
    solver = ScriptedCegarSolver(
        {
            "cegar-abs-init-1": CegarSolverObservation(
                status=SmtCheckStatus.UNAVAILABLE,
                reason="scripted by query id",
                provider="script",
                provider_version="1",
            )
        },
        fallback=LocalConjunctionSolver(),
    )
    receipt = run_cegar(_spurious_system(), solver=solver)
    assert receipt.disposition is CegarDisposition.UNAVAILABLE
    assert "scripted by query id" in receipt.reason


def test_live_incremental_smt_real_trace_stays_a_counterexample() -> None:
    receipt = run_cegar(
        _real_system(),
        solver=IncrementalSmtCegarSolver(),
        interpolator=_FixedInterpolator(_unavailable_interpolant()),
    )
    assert receipt.disposition in {
        CegarDisposition.DISPROVED,
        CegarDisposition.UNAVAILABLE,
        CegarDisposition.TIMEOUT,
        CegarDisposition.UNKNOWN,
    }
    if receipt.disposition is CegarDisposition.DISPROVED:
        assert receipt.counterexamples[0].classification is TraceClassification.REAL
        assert receipt.refinements == ()
        assert receipt.provider == "z3"
    else:
        assert receipt.counterexamples == ()


def test_live_incremental_smt_spurious_trace_is_refined_or_typed() -> None:
    receipt = run_cegar(
        _spurious_system(),
        solver=IncrementalSmtCegarSolver(),
        interpolator=_FixedInterpolator(_unavailable_interpolant()),
        budget=CegarBudget(allow_reviewed_predicates=False),
    )
    assert receipt.disposition in set(CegarDisposition)
    if receipt.disposition is CegarDisposition.PROVED:
        assert receipt.spurious_traces
        assert receipt.counterexamples == ()
        assert receipt.refinements
        assert receipt.refinements[0].interpolant_cid == ""
        assert receipt.refinements[0].authority in {
            RefinementAuthority.VALIDATED_UNSAT_CORE,
            RefinementAuthority.WEAKEST_PRECONDITION,
        }
    elif receipt.disposition is CegarDisposition.DISPROVED:
        raise AssertionError("infeasible x:=0; x<0 path must not become a real counterexample")
    else:
        assert receipt.disposition in {
            CegarDisposition.UNKNOWN,
            CegarDisposition.TIMEOUT,
            CegarDisposition.UNAVAILABLE,
            CegarDisposition.BUDGET_EXHAUSTED,
        }


def test_default_backends_never_fabricate_an_interpolant_on_the_spurious_example() -> None:
    receipt = run_cegar(_spurious_system())
    assert receipt.disposition in set(CegarDisposition)
    for refinement in receipt.refinements:
        if refinement.authority is RefinementAuthority.VALIDATED_INTERPOLANT:
            assert refinement.interpolant_status == InterpolationStatus.VALIDATED.value
            assert refinement.interpolant_cid
        else:
            assert refinement.interpolant_cid == ""
    if receipt.disposition is CegarDisposition.DISPROVED:
        raise AssertionError("spurious x:=0; assume x<0 must not be reported as a real counterexample")
