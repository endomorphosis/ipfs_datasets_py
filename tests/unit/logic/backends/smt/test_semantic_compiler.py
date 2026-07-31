"""Executable contract for the shared semantic SMT compiler (LFV-020 / LFV-G040)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from ipfs_datasets_py.logic.backends.smt.compiler import (
    BOOL_SORT,
    INT_SORT,
    SMT_COMPILER_ID,
    SMT_COMPILER_VERSION,
    SOFTWARE_VERIFICATION_SMT_COMPILER_INTERFACE,
    HornClause,
    SmtBinder,
    SmtCapabilityKind,
    SmtCompilation,
    SmtCompilerError,
    SmtDatatypeConstructor,
    SmtDatatypeDecl,
    SmtFeature,
    SmtFunDecl,
    SmtNamedAssertion,
    SmtObligation,
    SmtQueryMode,
    SmtSort,
    SmtTerm,
    SmtTermKind,
    SmtTheory,
    SoftwareVerificationSMTCompiler,
    UnsupportedSmtFeatureError,
    array_sort,
    compile_obligation,
    default_capabilities,
    select_smt_logic,
    smt_sanitize,
    term_and,
    term_apply,
    term_eq,
    term_false,
    term_implies,
    term_int,
    term_not,
    term_symbol,
    term_true,
)
from ipfs_datasets_py.logic.families.models import BoundednessKind, EvidenceAuthority
from ipfs_datasets_py.logic.software_verification.translations import (
    PreservationKind,
    TranslationBound,
)


def _compiler() -> SoftwareVerificationSMTCompiler:
    return SoftwareVerificationSMTCompiler()


def test_interface_and_default_capabilities_cover_acceptance_matrix() -> None:
    compiler = _compiler()
    assert compiler.INTERFACE == SOFTWARE_VERIFICATION_SMT_COMPILER_INTERFACE
    assert compiler.compiler_id == SMT_COMPILER_ID
    assert compiler.compiler_version == SMT_COMPILER_VERSION

    by_feature = {item.feature: item for item in compiler.capabilities}
    for feature in (
        SmtFeature.ARITHMETIC,
        SmtFeature.EQUALITY,
        SmtFeature.ARRAYS,
        SmtFeature.DATATYPES,
        SmtFeature.QUANTIFIERS,
        SmtFeature.HORN_CHC,
        SmtFeature.STATE_TRANSITIONS,
        SmtFeature.VERIFICATION_CONDITIONS,
        SmtFeature.HEAP_RESOURCE,
        SmtFeature.INTERFERENCE,
        SmtFeature.REFINEMENT,
    ):
        assert by_feature[feature].kind is SmtCapabilityKind.NATIVE
        assert compiler.supports(feature)

    assert by_feature[SmtFeature.PDR].kind is SmtCapabilityKind.CAPABILITY_BOUND
    assert by_feature[SmtFeature.IC3].kind is SmtCapabilityKind.CAPABILITY_BOUND
    assert compiler.is_capability_bound(SmtFeature.PDR)
    assert compiler.is_capability_bound(SmtFeature.IC3)

    for feature in (
        SmtFeature.TEMPORAL,
        SmtFeature.SEPARATION_WAND,
        SmtFeature.UNBOUNDED_CONCURRENCY,
        SmtFeature.UNBOUNDED_REFINEMENT,
    ):
        assert by_feature[feature].kind is SmtCapabilityKind.UNSUPPORTED
        assert not compiler.supports(feature)


def test_arithmetic_equality_golden_theorem_by_negation_and_unsat_core() -> None:
    compiler = _compiler()
    x = term_symbol("x")
    goal = SmtTerm(SmtTermKind.GT, arguments=(x, term_int(0)))
    result = compiler.compile_arithmetic_goal(
        obligation_id="obl:arith-positive",
        goal=goal,
        symbols=("x",),
        assumptions=(
            SmtNamedAssertion(
                formula=SmtTerm(SmtTermKind.GE, arguments=(x, term_int(1))),
                name="assume_ge_one",
            ),
        ),
        request_unsat_core=True,
        property_ids=("property:arith-positive",),
    )

    assert result.query_mode is SmtQueryMode.THEOREM_BY_NEGATION
    assert result.INTERFACE == SOFTWARE_VERIFICATION_SMT_COMPILER_INTERFACE
    smtlib = result.smtlib
    assert "(set-logic QF_UFLIA)" in smtlib
    assert "(declare-const x Int)" in smtlib
    assert "(assert (! (>= x 1) :named assume_ge_one))" in smtlib
    assert "(assert (not (> x 0)))" in smtlib
    assert "(check-sat)" in smtlib
    assert "(get-unsat-core)" in smtlib
    assert "(get-model)" not in smtlib
    assert result.receipt.preservation_claim.kind is PreservationKind.EQUISATISFIABLE
    assert any(
        mutation.mutation_id == "mutation:theorem-by-negation"
        for mutation in result.receipt.semantic_mutations
    )
    assert result.receipt.compilers[0].compiler_id == SMT_COMPILER_ID


def test_satisfiability_query_is_explicit_and_can_request_model() -> None:
    compiler = _compiler()
    result = compiler.compile(
        SmtObligation(
            obligation_id="obl:sat-bool",
            query_mode=SmtQueryMode.SATISFIABILITY,
            features=(SmtFeature.EQUALITY,),
            goal=term_eq(term_symbol("p"), term_true()),
            functions=(SmtFunDecl("p", range=BOOL_SORT, is_const=True),),
            request_model=True,
        )
    )
    assert result.query_mode is SmtQueryMode.SATISFIABILITY
    assert result.receipt.preservation_claim.kind is PreservationKind.EXACT
    assert "(assert (= p true))" in result.smtlib
    assert "(assert (not" not in result.smtlib
    assert "(set-option :produce-models true)" in result.smtlib
    assert "(get-model)" in result.smtlib
    assert result.receipt.semantic_mutations == ()


def test_array_map_fragment_golden_smtlib() -> None:
    compiler = _compiler()
    index = term_int(2)
    value = term_int(9)
    stored = SmtTerm(
        SmtTermKind.STORE,
        arguments=(term_symbol("mem"), index, value),
    )
    goal = term_eq(
        SmtTerm(SmtTermKind.SELECT, arguments=(stored, index)),
        value,
    )
    result = compiler.compile_array_goal(
        obligation_id="obl:array-store-select",
        array_name="mem",
        goal=goal,
    )
    smtlib = result.smtlib
    assert SmtFeature.ARRAYS in result.features
    assert "(declare-const mem (Array Int Int))" in smtlib
    assert "(assert (not (= (select (store mem 2 9) 2) 9)))" in smtlib
    assert "QF_A" in result.script.logic or "AUFLIA" in result.script.logic or "AUF" in result.script.logic


def test_datatype_fragment_golden_smtlib() -> None:
    compiler = _compiler()
    datatype = SmtDatatypeDecl(
        "Nat",
        constructors=(
            SmtDatatypeConstructor("zero"),
            SmtDatatypeConstructor("succ", selectors=(("pred", SmtSort("Nat")),)),
        ),
    )
    result = compiler.compile_datatype_goal(
        obligation_id="obl:datatype-nat",
        datatype=datatype,
        goal=term_eq(
            SmtTerm(SmtTermKind.DATATYPE_CONSTRUCTOR, value="zero"),
            SmtTerm(SmtTermKind.DATATYPE_CONSTRUCTOR, value="zero"),
        ),
        functions=(SmtFunDecl("n", range=SmtSort("Nat"), is_const=True),),
        query_mode=SmtQueryMode.SATISFIABILITY,
        request_model=True,
    )
    smtlib = result.smtlib
    assert "(declare-datatypes () ((Nat (zero) (succ (pred Nat)))))" in smtlib
    assert "(declare-const n Nat)" in smtlib
    assert "(assert (= zero zero))" in smtlib
    assert "(get-model)" in smtlib
    assert SmtFeature.DATATYPES in result.features


def test_quantifier_fragment_golden_smtlib() -> None:
    compiler = _compiler()
    body = SmtTerm(
        SmtTermKind.GE,
        arguments=(
            term_symbol("x"),
            SmtTerm(SmtTermKind.NEG, arguments=(term_symbol("x"),)),
        ),
    )
    goal = SmtTerm(
        SmtTermKind.FORALL,
        binders=(SmtBinder("x", INT_SORT),),
        arguments=(body,),
    )
    result = compiler.compile_quantified_goal(
        obligation_id="obl:quant-nonneg-abs",
        goal=goal,
    )
    assert result.query_mode is SmtQueryMode.THEOREM_BY_NEGATION
    assert "(set-logic UFLIA)" in result.smtlib
    assert "(assert (not (forall ((x Int)) (>= x (- x)))))" in result.smtlib
    assert SmtFeature.QUANTIFIERS in result.features


def test_horn_chc_reachability_fixed_point_query_is_explicit() -> None:
    compiler = _compiler()
    inv = SmtFunDecl("Inv", domain=(INT_SORT,), range=BOOL_SORT)
    n = term_symbol("n")
    clauses = (
        HornClause("c:init", head=term_apply("Inv", term_int(0))),
        HornClause(
            "c:step",
            head=term_apply(
                "Inv",
                SmtTerm(SmtTermKind.ADD, arguments=(n, term_int(1))),
            ),
            body=(term_apply("Inv", n),),
        ),
        HornClause(
            "c:query",
            head=term_false(),
            body=(
                term_apply("Inv", n),
                SmtTerm(SmtTermKind.LT, arguments=(n, term_int(0))),
            ),
            is_query=True,
        ),
    )
    result = compiler.compile_horn_reachability(
        obligation_id="obl:horn-reach",
        relations=(inv, SmtFunDecl("n", range=INT_SORT, is_const=True)),
        clauses=clauses,
    )
    assert result.query_mode is SmtQueryMode.FIXED_POINT
    assert result.script.logic == "HORN"
    smtlib = result.smtlib
    assert "(set-logic HORN)" in smtlib
    assert "(declare-fun Inv (Int) Bool)" in smtlib
    assert "(assert (! (Inv 0) :named c_init))" in smtlib
    assert "(assert (! (=> (Inv n) (Inv (+ n 1))) :named c_step))" in smtlib
    assert "(assert (! (=> (and (Inv n) (< n 0)) false) :named c_query))" in smtlib
    assert result.receipt.preservation_claim.kind is PreservationKind.EQUISATISFIABLE
    assert any(
        mutation.mutation_id == "mutation:fixed-point-query"
        for mutation in result.receipt.semantic_mutations
    )


def test_pdr_ic3_claims_are_capability_bound_on_fixed_point_only() -> None:
    compiler = _compiler()
    inv = SmtFunDecl("Reach", domain=(INT_SORT,), range=BOOL_SORT)
    clauses = (
        HornClause("c:base", head=term_apply("Reach", term_int(0))),
        HornClause(
            "c:bad",
            head=term_false(),
            body=(term_apply("Reach", term_int(-1)),),
            is_query=True,
        ),
    )
    result = compiler.compile_horn_reachability(
        obligation_id="obl:horn-pdr",
        relations=(inv,),
        clauses=clauses,
        claim_pdr=True,
        claim_ic3=True,
    )
    kinds = {item.feature: item.kind for item in result.capabilities}
    assert kinds[SmtFeature.PDR] is SmtCapabilityKind.CAPABILITY_BOUND
    assert kinds[SmtFeature.IC3] is SmtCapabilityKind.CAPABILITY_BOUND
    assert any("capability-pdr" in m.mutation_id for m in result.receipt.semantic_mutations)
    assert any("capability-ic3" in m.mutation_id for m in result.receipt.semantic_mutations)

    with pytest.raises(UnsupportedSmtFeatureError, match="fixed_point"):
        compiler.compile(
            SmtObligation(
                obligation_id="obl:pdr-misuse",
                query_mode=SmtQueryMode.THEOREM_BY_NEGATION,
                features=(SmtFeature.PDR, SmtFeature.ARITHMETIC),
                goal=term_true(),
            )
        )


def test_verification_condition_lowering_with_path_assumptions() -> None:
    compiler = _compiler()
    x = term_symbol("x")
    result = compiler.compile_verification_condition(
        obligation_id="obl:vc-post",
        goal=SmtTerm(SmtTermKind.GE, arguments=(x, term_int(0))),
        path_assumptions=(
            SmtTerm(SmtTermKind.GT, arguments=(x, term_int(-1))),
        ),
        symbols=(("x", INT_SORT),),
        request_unsat_core=True,
    )
    assert SmtFeature.VERIFICATION_CONDITIONS in result.features
    assert result.query_mode is SmtQueryMode.THEOREM_BY_NEGATION
    assert "(assert (! (> x (- 1)) :named path_0))" in result.smtlib
    assert "(assert (not (>= x 0)))" in result.smtlib
    assert "(get-unsat-core)" in result.smtlib


def test_state_transition_safety_and_bounded_reachability() -> None:
    compiler = _compiler()
    x = term_symbol("x")
    safety = compiler.compile_state_transition(
        obligation_id="obl:state-safety",
        state_vars=("x",),
        init=term_eq(x, term_int(0)),
        transition=SmtTerm(SmtTermKind.GE, arguments=(x, term_int(0))),
        bad=SmtTerm(SmtTermKind.LT, arguments=(x, term_int(0))),
    )
    assert SmtFeature.STATE_TRANSITIONS in safety.features
    assert safety.query_mode is SmtQueryMode.THEOREM_BY_NEGATION
    assert "(assert (not (=> (and (= x 0) (>= x 0)) (not (< x 0)))))" in safety.smtlib

    bounded = compiler.compile_state_transition(
        obligation_id="obl:state-bounded",
        state_vars=("x",),
        init=term_eq(x, term_int(0)),
        transition=term_true(),
        bad=term_eq(x, term_int(5)),
        bound_steps=5,
    )
    assert bounded.query_mode is SmtQueryMode.SATISFIABILITY
    assert bounded.receipt.preservation_claim.kind is PreservationKind.BOUNDED
    assert bounded.receipt.bounds
    assert bounded.receipt.bounds[0].kind is BoundednessKind.STEP_BOUNDED
    assert "(get-model)" in bounded.smtlib


def test_heap_resource_fragment_points_to_as_array() -> None:
    compiler = _compiler()
    result = compiler.compile_heap_fragment(
        obligation_id="obl:heap-points-to",
        heap_name="heap",
        points_to=((term_int(0), term_int(7)),),
        pure_goal=term_eq(
            SmtTerm(SmtTermKind.SELECT, arguments=(term_symbol("heap"), term_int(0))),
            term_int(7),
        ),
    )
    assert SmtFeature.HEAP_RESOURCE in result.features
    assert "(declare-const heap (Array Int Int))" in result.smtlib
    assert "(assert (! (= (select heap 0) 7) :named points_to_0))" in result.smtlib
    assert any(
        mutation.mutation_id == "mutation:heap-as-array"
        for mutation in result.receipt.semantic_mutations
    )


def test_interference_and_refinement_obligations_with_bounds() -> None:
    compiler = _compiler()
    x = term_symbol("x")
    interference = compiler.compile_interference(
        obligation_id="obl:interference",
        rely=SmtTerm(SmtTermKind.GE, arguments=(x, term_int(0))),
        guarantee=SmtTerm(SmtTermKind.GE, arguments=(x, term_int(0))),
        shared_vars=("x",),
        bound_interleavings=4,
    )
    assert SmtFeature.INTERFERENCE in interference.features
    assert interference.receipt.preservation_claim.kind is PreservationKind.BOUNDED
    assert "(assert (not (=> (>= x 0) (>= x 0))))" in interference.smtlib

    refinement = compiler.compile_refinement(
        obligation_id="obl:refinement",
        simulation=term_eq(term_symbol("a"), term_symbol("c")),
        abstract_step=term_true(),
        concrete_step=term_true(),
        max_matching_steps=2,
    )
    assert SmtFeature.REFINEMENT in refinement.features
    assert refinement.receipt.preservation_claim.kind is PreservationKind.BOUNDED
    assert refinement.receipt.bounds[0].limits.to_dict()["matching_steps"] == 2


def test_unsupported_temporal_heap_concurrency_refinement_cannot_be_native() -> None:
    compiler = _compiler()

    with pytest.raises(UnsupportedSmtFeatureError, match="temporal"):
        compiler.compile_temporal_rejected(obligation_id="obl:temporal")

    with pytest.raises(UnsupportedSmtFeatureError, match="separation_wand"):
        compiler.reject_unsupported(SmtFeature.SEPARATION_WAND)

    with pytest.raises(UnsupportedSmtFeatureError, match="unbounded_concurrency"):
        compiler.compile_interference(
            obligation_id="obl:unbounded-conc",
            rely=term_true(),
            guarantee=term_true(),
        )

    with pytest.raises(UnsupportedSmtFeatureError, match="unbounded_refinement"):
        compiler.compile_refinement(
            obligation_id="obl:unbounded-ref",
            simulation=term_true(),
            abstract_step=term_true(),
            concrete_step=term_true(),
            claims_unbounded=True,
        )

    with pytest.raises(UnsupportedSmtFeatureError, match="uninterpreted native"):
        compiler.compile(
            SmtObligation(
                obligation_id="obl:temporal-feature",
                query_mode=SmtQueryMode.SATISFIABILITY,
                features=(SmtFeature.TEMPORAL, SmtFeature.EQUALITY),
                goal=term_true(),
            )
        )


def test_compilation_is_deterministic_and_receipt_bound() -> None:
    compiler = _compiler()
    obligation = SmtObligation(
        obligation_id="obl:det",
        query_mode=SmtQueryMode.SATISFIABILITY,
        features=(SmtFeature.ARITHMETIC, SmtFeature.EQUALITY),
        goal=SmtTerm(
            SmtTermKind.EQ,
            arguments=(
                SmtTerm(SmtTermKind.ADD, arguments=(term_symbol("a"), term_symbol("b"))),
                SmtTerm(SmtTermKind.ADD, arguments=(term_symbol("b"), term_symbol("a"))),
            ),
        ),
        functions=(
            SmtFunDecl("b", range=INT_SORT, is_const=True),
            SmtFunDecl("a", range=INT_SORT, is_const=True),
        ),
    )
    first = compiler.compile(obligation)
    second = compile_obligation(obligation.to_dict())
    assert first.smtlib == second.smtlib
    assert first.script.digest == second.script.digest
    assert first.compilation_id == second.compilation_id
    assert first.source_identity != first.target_identity
    assert first.receipt.source_identity == first.source_identity
    assert first.receipt.target_identity == first.target_identity
    assert first.receipt.source_family_id != first.receipt.target_family_id
    assert first.receipt.authority_ceiling in {
        EvidenceAuthority.AUTHORITATIVE,
        EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        EvidenceAuthority.BOUNDED,
    }
    # Function declarations are sorted for determinism.
    assert first.smtlib.index("(declare-const a Int)") < first.smtlib.index(
        "(declare-const b Int)"
    )


def test_select_smt_logic_and_sanitize_helpers() -> None:
    assert select_smt_logic((SmtTheory.CORE, SmtTheory.EQUALITY), SmtQueryMode.SATISFIABILITY) == "QF_UF"
    assert (
        select_smt_logic(
            (SmtTheory.CORE, SmtTheory.EQUALITY, SmtTheory.ARITHMETIC),
            SmtQueryMode.THEOREM_BY_NEGATION,
        )
        == "QF_UFLIA"
    )
    assert (
        select_smt_logic(
            (SmtTheory.HORN, SmtTheory.QUANTIFIERS),
            SmtQueryMode.FIXED_POINT,
        )
        == "HORN"
    )
    assert smt_sanitize("x") == "x"
    assert smt_sanitize("123") == "x_123"
    assert smt_sanitize("and") != "and"


def test_obligation_validation_fail_closed() -> None:
    with pytest.raises(SmtCompilerError, match="goal term"):
        SmtObligation(
            obligation_id="obl:missing-goal",
            query_mode=SmtQueryMode.SATISFIABILITY,
            features=(SmtFeature.EQUALITY,),
        )
    with pytest.raises(SmtCompilerError, match="Horn clauses"):
        SmtObligation(
            obligation_id="obl:fp-empty",
            query_mode=SmtQueryMode.FIXED_POINT,
            features=(SmtFeature.HORN_CHC,),
        )
    with pytest.raises(SmtCompilerError, match="query clause"):
        SmtObligation(
            obligation_id="obl:fp-no-query",
            query_mode=SmtQueryMode.FIXED_POINT,
            features=(SmtFeature.HORN_CHC,),
            horn_clauses=(HornClause("c:only", head=term_true()),),
        )
    with pytest.raises(UnsupportedSmtFeatureError):
        SmtObligation(
            obligation_id="obl:hard",
            query_mode=SmtQueryMode.SATISFIABILITY,
            features=(SmtFeature.TEMPORAL,),
            goal=term_true(),
        )


def test_term_shape_validation_and_immutability() -> None:
    with pytest.raises(SmtCompilerError, match="two arguments"):
        SmtTerm(SmtTermKind.EQ, arguments=(term_true(),))
    with pytest.raises(SmtCompilerError, match="binders"):
        SmtTerm(SmtTermKind.FORALL, arguments=(term_true(),))
    term = term_and(term_true(), term_false())
    with pytest.raises(FrozenInstanceError):
        term.kind = SmtTermKind.OR  # type: ignore[misc]


def test_compilation_to_dict_round_trip_surface() -> None:
    compiler = _compiler()
    result = compiler.compile_arithmetic_goal(
        obligation_id="obl:roundtrip",
        goal=SmtTerm(SmtTermKind.EQ, arguments=(term_int(1), term_int(1))),
        symbols=(),
    )
    payload = result.to_dict()
    assert payload["interface"] == SOFTWARE_VERIFICATION_SMT_COMPILER_INTERFACE
    assert payload["query_mode"] == "theorem_by_negation"
    assert payload["smtlib"] == result.smtlib
    assert payload["receipt"]["target_family_id"] == "smt"
    assert "compilation_id" in payload
    assert isinstance(result, SmtCompilation)
    assert result.canonical_bytes()


def test_default_capabilities_are_stable_and_complete() -> None:
    caps = default_capabilities()
    features = [item.feature for item in caps]
    assert features == sorted(features, key=lambda item: item.value)
    assert len(features) == len(set(features))
    assert SmtFeature.PDR in features
    assert SmtFeature.TEMPORAL in features


def test_array_sort_helper() -> None:
    sort = array_sort(INT_SORT, BOOL_SORT)
    assert sort.render() == "(Array Int Bool)"
    assert sort.to_dict()["parameters"] == ["Int", "Bool"]


def test_bounded_translation_bound_record_shape() -> None:
    bound = TranslationBound(
        bound_id="bound:steps-3",
        kind=BoundednessKind.STEP_BOUNDED,
        limits={"steps": 3},
        description="three steps",
    )
    compiler = _compiler()
    result = compiler.compile(
        SmtObligation(
            obligation_id="obl:bound-sat",
            query_mode=SmtQueryMode.SATISFIABILITY,
            features=(SmtFeature.STATE_TRANSITIONS, SmtFeature.EQUALITY),
            goal=term_true(),
            bounds=(bound,),
            request_model=True,
        )
    )
    assert result.receipt.preservation_claim.kind is PreservationKind.BOUNDED
    assert result.receipt.authority_ceiling is EvidenceAuthority.BOUNDED
