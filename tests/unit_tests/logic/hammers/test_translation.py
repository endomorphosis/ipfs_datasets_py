"""Tests for typed translation to TPTP and SMT-LIB (HAMMER-007).

These tests cover:
- The typed intermediate representation (:mod:`translation`): type
  inference, free-variable computation, capture-avoiding substitution.
- Explicit monomorphization of :class:`TypeVarRef` occurrences.
- Lambda elimination (beta-reduction) and lambda lifting (a bare top-level
  lambda becomes a fresh named function symbol plus a defining equation).
- Fail-closed rejection of dependent types, opaque constructs, unresolved
  type variables, higher-order quantification, higher-order argument
  passing, and escaping (un-lifted, un-eliminated) lambdas — every case
  must produce ``TranslationStatus.UNSUPPORTED`` with ``translated_text``
  ``None``, never a silently degraded translation.
- TPTP (TFF) and SMT-LIB2 rendering, including round-trip stability
  (``render(parse(render(t))) == render(t)``) and defensive rendering
  errors for out-of-fragment terms.
- Persistence of the :class:`TranslationMap` and
  :class:`~ipfs_datasets_py.logic.hammers.models.TranslationRecord`
  obligations through :class:`TranslationContext` (including
  ``to_dict``/``from_dict``/``save``/``load``).
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from ipfs_datasets_py.logic.hammers import smtlib, tptp
from ipfs_datasets_py.logic.hammers.models import (
    TranslationRecord,
    TranslationStatus,
    TranslationTarget,
)
from ipfs_datasets_py.logic.hammers.translation import (
    PROP_SORT,
    And,
    App,
    BoolLit,
    Const,
    DependentTypeRef,
    Eq,
    Exists,
    Forall,
    FunctionTypeRef,
    Iff,
    Implies,
    Lambda,
    LambdaLiftedDefinition,
    LambdaParam,
    MalformedTermError,
    Not,
    Opaque,
    Or,
    SortRef,
    TranslationContext,
    TranslationMap,
    TranslationMapEntry,
    TypeVarRef,
    UnsupportedConstructError,
    Var,
    beta_reduce,
    find_dependent_type_issue,
    find_opaque_issue,
    find_structural_issue,
    find_type_var_issue,
    free_term_vars,
    infer_type,
    normalize_construct,
    sanitize_identifier,
    substitute_term,
    substitute_type_vars,
    substitute_type_vars_in_term,
)

NAT = SortRef("nat")
INT_SORT = SortRef("int")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_predicate(name: str, arg_type=NAT) -> Const:
    return Const(name, FunctionTypeRef((arg_type,), PROP_SORT))


def make_binary_fn(name: str, arg_type=NAT, result_type=NAT) -> Const:
    return Const(name, FunctionTypeRef((arg_type, arg_type), result_type))


# ---------------------------------------------------------------------------
# Type inference
# ---------------------------------------------------------------------------


class TestInferType:
    def test_var_and_const_return_their_own_type(self):
        assert infer_type(Var("x", NAT)) == NAT
        assert infer_type(Const("c", NAT)) == NAT

    def test_app_returns_function_result_type(self):
        p = make_predicate("P")
        term = App(p, (Var("x", NAT),))
        assert infer_type(term) == PROP_SORT

    def test_app_arity_mismatch_raises_malformed_term_error(self):
        p = make_predicate("P")
        with pytest.raises(MalformedTermError):
            infer_type(App(p, (Var("x", NAT), Var("y", NAT))))

    def test_app_on_non_function_raises_malformed_term_error(self):
        with pytest.raises(MalformedTermError):
            infer_type(App(Const("c", NAT), (Var("x", NAT),)))

    def test_app_argument_type_mismatch_raises_when_concrete(self):
        p = make_predicate("P", arg_type=NAT)
        with pytest.raises(MalformedTermError):
            infer_type(App(p, (Var("x", INT_SORT),)))

    def test_app_argument_type_mismatch_tolerated_when_polymorphic(self):
        alpha = TypeVarRef("alpha")
        idfn = Const("id", FunctionTypeRef((alpha,), alpha))
        # Not yet monomorphized: comparing TypeVarRef to a concrete sort must
        # not raise, since monomorphization has not run yet.
        infer_type(App(idfn, (Var("x", NAT),)))

    def test_lambda_infers_function_type(self):
        lam = Lambda((LambdaParam("y", NAT),), Var("y", NAT))
        t = infer_type(lam)
        assert isinstance(t, FunctionTypeRef)
        assert t.params == (NAT,)
        assert t.result == NAT

    def test_connectives_and_quantifiers_are_prop(self):
        p = make_predicate("P")
        atom = App(p, (Var("x", NAT),))
        assert infer_type(Not(atom)) == PROP_SORT
        assert infer_type(And(atom, atom)) == PROP_SORT
        assert infer_type(Or(atom, atom)) == PROP_SORT
        assert infer_type(Implies(atom, atom)) == PROP_SORT
        assert infer_type(Iff(atom, atom)) == PROP_SORT
        assert infer_type(Eq(Var("x", NAT), Var("y", NAT))) == PROP_SORT
        assert infer_type(Forall("x", NAT, atom)) == PROP_SORT
        assert infer_type(Exists("x", NAT, atom)) == PROP_SORT
        assert infer_type(BoolLit(True)) == PROP_SORT

    def test_opaque_returns_its_declared_type(self):
        assert infer_type(Opaque("sorry")) is not None


# ---------------------------------------------------------------------------
# Free variables / capture-avoiding substitution
# ---------------------------------------------------------------------------


class TestFreeVarsAndSubstitution:
    def test_free_term_vars_excludes_bound_variables(self):
        p = make_predicate("P")
        term = Forall("x", NAT, App(p, (Var("x", NAT),)))
        assert free_term_vars(term) == frozenset()

    def test_free_term_vars_includes_unbound_variables(self):
        p = make_predicate("P")
        term = App(p, (Var("y", NAT),))
        assert free_term_vars(term) == frozenset({"y"})

    def test_lambda_shadows_its_own_parameter(self):
        lam = Lambda((LambdaParam("x", NAT),), Var("x", NAT))
        assert free_term_vars(lam) == frozenset()

    def test_substitute_term_replaces_free_occurrences(self):
        p = make_predicate("P")
        term = App(p, (Var("x", NAT),))
        replaced = substitute_term(term, "x", Var("y", NAT))
        assert replaced == App(p, (Var("y", NAT),))

    def test_substitute_term_does_not_replace_shadowed_occurrences(self):
        lam = Lambda((LambdaParam("x", NAT),), Var("x", NAT))
        replaced = substitute_term(lam, "x", Var("y", NAT))
        assert replaced == lam  # unchanged: x is shadowed by the lambda's own binder

    def test_substitute_term_avoids_variable_capture(self):
        # (fun y => x) [x := y]  must alpha-rename the binder, never becoming
        # (fun y => y) (which would incorrectly capture the substituted `y`).
        lam = Lambda((LambdaParam("y", NAT),), Var("x", NAT))
        replaced = substitute_term(lam, "x", Var("y", NAT))
        assert isinstance(replaced, Lambda)
        assert replaced.params[0].name != "y"
        assert replaced.body == Var("y", NAT)


# ---------------------------------------------------------------------------
# Type substitution (monomorphization primitives)
# ---------------------------------------------------------------------------


class TestTypeSubstitution:
    def test_substitute_type_vars_replaces_mapped_variable(self):
        alpha = TypeVarRef("alpha")
        assert substitute_type_vars(alpha, {"alpha": NAT}) == NAT

    def test_substitute_type_vars_leaves_unmapped_variable(self):
        alpha = TypeVarRef("alpha")
        assert substitute_type_vars(alpha, {}) == alpha

    def test_substitute_type_vars_recurses_into_function_types(self):
        alpha = TypeVarRef("alpha")
        ft = FunctionTypeRef((alpha, NAT), alpha)
        result = substitute_type_vars(ft, {"alpha": INT_SORT})
        assert result == FunctionTypeRef((INT_SORT, NAT), INT_SORT)

    def test_substitute_type_vars_in_term_updates_every_annotation(self):
        alpha = TypeVarRef("alpha")
        idfn = Const("id", FunctionTypeRef((alpha,), alpha))
        term = App(idfn, (Var("x", alpha),))
        result = substitute_type_vars_in_term(term, {"alpha": NAT})
        assert infer_type(result) == NAT
        assert result.fn.type == FunctionTypeRef((NAT,), NAT)


# ---------------------------------------------------------------------------
# Beta reduction (lambda elimination)
# ---------------------------------------------------------------------------


class TestBetaReduce:
    def test_fully_applied_lambda_is_eliminated(self):
        p = make_predicate("P")
        lam = Lambda((LambdaParam("y", NAT),), App(p, (Var("y", NAT),)))
        applied = App(lam, (Var("a", NAT),))
        reduced, count = beta_reduce(applied)
        assert count == 1
        assert reduced == App(p, (Var("a", NAT),))

    def test_nested_redexes_are_all_eliminated(self):
        p = make_predicate("P")
        inner = Lambda((LambdaParam("y", NAT),), App(p, (Var("y", NAT),)))
        outer = Lambda((LambdaParam("z", NAT),), App(inner, (Var("z", NAT),)))
        applied = App(outer, (Var("a", NAT),))
        reduced, count = beta_reduce(applied)
        assert count == 2
        assert reduced == App(p, (Var("a", NAT),))

    def test_non_applied_lambda_is_left_untouched(self):
        lam = Lambda((LambdaParam("y", NAT),), Var("y", NAT))
        reduced, count = beta_reduce(lam)
        assert count == 0
        assert reduced == lam

    def test_multi_arg_lambda_beta_reduces_with_matching_arity(self):
        f = make_binary_fn("f")
        lam = Lambda(
            (LambdaParam("a", NAT), LambdaParam("b", NAT)),
            App(f, (Var("a", NAT), Var("b", NAT))),
        )
        applied = App(lam, (Var("x", NAT), Var("y", NAT)))
        reduced, count = beta_reduce(applied)
        assert count == 1
        assert reduced == App(f, (Var("x", NAT), Var("y", NAT)))


# ---------------------------------------------------------------------------
# normalize_construct (beta-elimination + top-level lambda lifting)
# ---------------------------------------------------------------------------


class TestNormalizeConstruct:
    def test_top_level_lambda_is_lifted_to_a_named_definition(self):
        p = make_predicate("P")
        lam = Lambda((LambdaParam("n", NAT),), App(p, (Var("n", NAT),)))
        result = normalize_construct(lam, source_construct="my_def", lifted_name="my_def__lifted")
        assert len(result.lifted_definitions) == 1
        lifted = result.lifted_definitions[0]
        assert lifted.name == "my_def__lifted"
        assert lifted.source_construct == "my_def"
        assert any("lambda-lifted" in o for o in result.obligations)
        # The result must be a fully first-order, quantified defining equation.
        assert isinstance(result.term, Forall)

    def test_top_level_lambda_lifting_captures_free_variables_as_leading_params(self):
        f = make_binary_fn("f")
        c = Var("outer", NAT)
        lam = Lambda((LambdaParam("n", NAT),), App(f, (c, Var("n", NAT))))
        result = normalize_construct(lam, source_construct="g", lifted_name="g__lifted")
        lifted = result.lifted_definitions[0]
        assert [p.name for p in lifted.params] == ["outer", "n"]

    def test_beta_eliminated_construct_produces_no_lifted_definition(self):
        p = make_predicate("P")
        lam = Lambda((LambdaParam("y", NAT),), App(p, (Var("y", NAT),)))
        applied = App(lam, (Var("a", NAT),))
        result = normalize_construct(applied, source_construct="c", lifted_name="c__lifted")
        assert result.lifted_definitions == ()
        assert result.term == App(p, (Var("a", NAT),))
        assert any("beta-eliminated" in o for o in result.obligations)

    def test_already_first_order_construct_produces_no_obligations(self):
        p = make_predicate("P")
        term = App(p, (Var("x", NAT),))
        result = normalize_construct(term, source_construct="c", lifted_name="c__lifted")
        assert result.obligations == ()
        assert result.lifted_definitions == ()
        assert result.term == term


# ---------------------------------------------------------------------------
# Fail-closed detection primitives
# ---------------------------------------------------------------------------


class TestFailClosedDetection:
    def test_find_dependent_type_issue_detects_dependent_type(self):
        dep = DependentTypeRef("Vec n")
        term = Eq(Const("v", dep), Const("v", dep))
        issue = find_dependent_type_issue(term)
        assert issue is not None
        assert "dependent type" in issue
        assert "Vec n" in issue

    def test_find_dependent_type_issue_returns_none_for_clean_term(self):
        term = Eq(Var("x", NAT), Var("y", NAT))
        assert find_dependent_type_issue(term) is None

    def test_find_opaque_issue_detects_opaque_node(self):
        term = Eq(Opaque("sorry"), Opaque("sorry"))
        issue = find_opaque_issue(term)
        assert issue is not None
        assert "opaque" in issue

    def test_find_opaque_issue_detects_opaque_const(self):
        c = Const("ax", NAT, opaque=True, opaque_reason="axiom without a body")
        term = Eq(c, c)
        issue = find_opaque_issue(term)
        assert issue is not None
        assert "ax" in issue

    def test_find_opaque_issue_returns_none_for_ordinary_const(self):
        c = Const("f", NAT)
        assert find_opaque_issue(Eq(c, c)) is None

    def test_find_type_var_issue_detects_unresolved_variable(self):
        alpha = TypeVarRef("alpha")
        term = Eq(Var("x", alpha), Var("y", alpha))
        issue = find_type_var_issue(term)
        assert issue is not None
        assert "alpha" in issue

    def test_find_type_var_issue_returns_none_after_substitution(self):
        alpha = TypeVarRef("alpha")
        term = Eq(Var("x", alpha), Var("y", alpha))
        substituted = substitute_type_vars_in_term(term, {"alpha": NAT})
        assert find_type_var_issue(substituted) is None

    def test_find_structural_issue_detects_escaping_lambda(self):
        lam = Lambda((LambdaParam("y", NAT),), BoolLit(True))
        term = Eq(lam, lam)
        issue = find_structural_issue(term)
        assert issue is not None
        assert "higher-order" in issue

    def test_find_structural_issue_detects_quantification_over_function_type(self):
        fty = FunctionTypeRef((NAT,), NAT)
        term = Forall("f", fty, Eq(Var("f", fty), Var("f", fty)))
        issue = find_structural_issue(term)
        assert issue is not None
        assert "quantification" in issue

    def test_find_structural_issue_detects_quantification_over_prop_type(self):
        term = Forall("p", PROP_SORT, Var("p", PROP_SORT))
        issue = find_structural_issue(term)
        assert issue is not None
        assert "propositional" in issue

    def test_find_structural_issue_detects_function_typed_argument(self):
        fty = FunctionTypeRef((NAT,), NAT)
        higher = Const("apply", FunctionTypeRef((fty, NAT), NAT))
        g = Const("g", fty)
        term = Eq(App(higher, (g, Var("x", NAT))), Var("x", NAT))
        issue = find_structural_issue(term)
        assert issue is not None
        assert "higher-order" in issue

    def test_find_structural_issue_detects_boolean_typed_argument(self):
        higher = Const("choose", FunctionTypeRef((PROP_SORT, NAT), NAT))
        term = Eq(App(higher, (BoolLit(True), Var("x", NAT))), Var("x", NAT))
        issue = find_structural_issue(term)
        assert issue is not None
        assert "boolean" in issue or "propositional" in issue

    def test_find_structural_issue_returns_none_for_supported_fragment(self):
        p = make_predicate("P")
        term = Forall("x", NAT, Implies(App(p, (Var("x", NAT),)), App(p, (Var("x", NAT),))))
        assert find_structural_issue(term) is None


# ---------------------------------------------------------------------------
# sanitize_identifier
# ---------------------------------------------------------------------------


class TestSanitizeIdentifier:
    def test_alphanumeric_name_is_preserved(self):
        assert sanitize_identifier("nat") == "nat"

    def test_dots_and_primes_are_replaced(self):
        result = sanitize_identifier("Nat.add_comm'")
        assert all(c.isalnum() or c == "_" for c in result)

    def test_leading_digit_gets_prefixed(self):
        result = sanitize_identifier("123")
        assert not result[0].isdigit()

    def test_empty_name_falls_back_to_prefix(self):
        assert sanitize_identifier("", fallback_prefix="sym") == "sym"


# ---------------------------------------------------------------------------
# TranslationContext: supported / partial cases
# ---------------------------------------------------------------------------


class TestTranslationContextSupported:
    def test_simple_first_order_goal_is_supported_for_tptp(self):
        p = make_predicate("P")
        goal = Forall("x", NAT, Implies(App(p, (Var("x", NAT),)), App(p, (Var("x", NAT),))))
        ctx = TranslationContext(request_id="req-1")
        record = ctx.translate(source_construct="goal", term=goal, target=TranslationTarget.TPTP)
        assert record.status == TranslationStatus.SUPPORTED
        assert record.obligations == []
        assert record.translated_text is not None
        assert record.unsupported_reason is None
        assert "tff(" in record.translated_text

    def test_simple_first_order_goal_is_supported_for_smtlib(self):
        p = make_predicate("P")
        goal = Forall("x", NAT, Implies(App(p, (Var("x", NAT),)), App(p, (Var("x", NAT),))))
        ctx = TranslationContext(request_id="req-1")
        record = ctx.translate(source_construct="goal", term=goal, target=TranslationTarget.SMTLIB)
        assert record.status == TranslationStatus.SUPPORTED
        assert record.obligations == []
        assert "(assert" in record.translated_text

    def test_monomorphization_produces_partial_status_with_obligation(self):
        alpha = TypeVarRef("alpha")
        idfn = Const("id", FunctionTypeRef((alpha,), alpha))
        goal = Forall("x", NAT, Eq(App(idfn, (Var("x", alpha),)), Var("x", alpha)))
        ctx = TranslationContext(request_id="req-2")
        record = ctx.translate(
            source_construct="mono_goal",
            term=goal,
            target=TranslationTarget.TPTP,
            monomorphization={"alpha": NAT},
        )
        assert record.status == TranslationStatus.PARTIAL
        assert any("monomorphized" in o for o in record.obligations)
        assert record.translated_text is not None

    def test_beta_elimination_produces_partial_status_with_obligation(self):
        p = make_predicate("P")
        lam = Lambda((LambdaParam("y", NAT),), App(p, (Var("y", NAT),)))
        goal = Forall("a", NAT, App(lam, (Var("a", NAT),)))
        ctx = TranslationContext(request_id="req-3")
        record = ctx.translate(source_construct="beta_goal", term=goal, target=TranslationTarget.TPTP)
        assert record.status == TranslationStatus.PARTIAL
        assert any("beta-eliminated" in o for o in record.obligations)

    def test_lambda_lifting_produces_partial_status_with_obligation(self):
        p = make_predicate("P")
        lam_def = Lambda((LambdaParam("n", NAT),), App(p, (Var("n", NAT),)))
        ctx = TranslationContext(request_id="req-4")
        record = ctx.translate(
            source_construct="my_def", term=lam_def, target=TranslationTarget.SMTLIB
        )
        assert record.status == TranslationStatus.PARTIAL
        assert any("lambda-lifted" in o for o in record.obligations)
        assert "declare-fun" in record.translated_text

    def test_translation_map_accumulates_entries_across_calls(self):
        p = make_predicate("P")
        goal = Forall("x", NAT, App(p, (Var("x", NAT),)))
        ctx = TranslationContext(request_id="req-5")
        ctx.translate(source_construct="goal", term=goal, target=TranslationTarget.TPTP)
        ctx.translate(source_construct="goal", term=goal, target=TranslationTarget.SMTLIB)
        sources = {e.source_name for e in ctx.translation_map.entries}
        assert "P" in sources
        assert "nat" in sources
        targets = {e.target for e in ctx.translation_map.entries}
        assert TranslationTarget.TPTP in targets
        assert TranslationTarget.SMTLIB in targets

    def test_lifted_definition_recorded_with_lambda_lifted_origin(self):
        p = make_predicate("P")
        lam_def = Lambda((LambdaParam("n", NAT),), App(p, (Var("n", NAT),)))
        ctx = TranslationContext(request_id="req-6")
        ctx.translate(source_construct="my_def", term=lam_def, target=TranslationTarget.TPTP)
        lifted_entries = [e for e in ctx.translation_map.entries if e.origin == "lambda-lifted"]
        assert len(lifted_entries) == 1

    def test_every_record_is_appended_to_context_records(self):
        p = make_predicate("P")
        goal = Forall("x", NAT, App(p, (Var("x", NAT),)))
        ctx = TranslationContext(request_id="req-7")
        r1 = ctx.translate(source_construct="a", term=goal, target=TranslationTarget.TPTP)
        r2 = ctx.translate(source_construct="b", term=goal, target=TranslationTarget.SMTLIB)
        assert ctx.records == [r1, r2]

    def test_translation_ids_are_unique_and_deterministic(self):
        p = make_predicate("P")
        goal = Forall("x", NAT, App(p, (Var("x", NAT),)))
        ctx = TranslationContext(request_id="req-8")
        r1 = ctx.translate(source_construct="a", term=goal, target=TranslationTarget.TPTP)
        r2 = ctx.translate(source_construct="a", term=goal, target=TranslationTarget.TPTP)
        assert r1.translation_id != r2.translation_id
        assert r1.translation_id.startswith("req-8:a:tptp")


# ---------------------------------------------------------------------------
# TranslationContext: negative fixtures — fail-closed behavior
# ---------------------------------------------------------------------------


class TestTranslationContextFailsClosed:
    """Negative fixtures proving unsupported dependent, higher-order, or
    opaque constructs fail closed: every case below must yield
    ``TranslationStatus.UNSUPPORTED`` with ``translated_text=None`` and a
    populated ``unsupported_reason`` — never a partial or silently-dropped
    translation."""

    def _assert_fails_closed(self, record: TranslationRecord, *, reason_contains: str) -> None:
        assert record.status == TranslationStatus.UNSUPPORTED
        assert record.translated_text is None
        assert record.obligations == []
        assert record.unsupported_reason is not None
        assert reason_contains.lower() in record.unsupported_reason.lower()
        # Re-validate independently against the HAMMER-001 trust contract.
        record.validate()

    @pytest.mark.parametrize("target", [TranslationTarget.TPTP, TranslationTarget.SMTLIB])
    def test_dependent_type_fails_closed(self, target):
        dep = DependentTypeRef("Vec n")
        c = Const("v", dep)
        goal = Eq(c, c)
        ctx = TranslationContext(request_id="neg-1")
        record = ctx.translate(source_construct="dependent_goal", term=goal, target=target)
        self._assert_fails_closed(record, reason_contains="dependent type")

    @pytest.mark.parametrize("target", [TranslationTarget.TPTP, TranslationTarget.SMTLIB])
    def test_opaque_node_fails_closed(self, target):
        op = Opaque("incomplete proof: sorry")
        goal = Eq(op, op)
        ctx = TranslationContext(request_id="neg-2")
        record = ctx.translate(source_construct="opaque_goal", term=goal, target=target)
        self._assert_fails_closed(record, reason_contains="opaque")

    def test_opaque_const_fails_closed(self):
        c = Const("ax", NAT, opaque=True, opaque_reason="axiom without a body")
        goal = Eq(c, c)
        ctx = TranslationContext(request_id="neg-3")
        record = ctx.translate(source_construct="opaque_const_goal", term=goal, target=TranslationTarget.TPTP)
        self._assert_fails_closed(record, reason_contains="opaque")

    def test_unresolved_type_variable_fails_closed(self):
        alpha = TypeVarRef("alpha")
        idfn = Const("id", FunctionTypeRef((alpha,), alpha))
        goal = Forall("x", NAT, Eq(App(idfn, (Var("x", alpha),)), Var("x", alpha)))
        ctx = TranslationContext(request_id="neg-4")
        # No monomorphization instance is supplied.
        record = ctx.translate(source_construct="poly_goal", term=goal, target=TranslationTarget.TPTP)
        self._assert_fails_closed(record, reason_contains="unresolved type variable")

    def test_higher_order_quantification_over_function_type_fails_closed(self):
        fty = FunctionTypeRef((NAT,), NAT)
        goal = Forall("f", fty, Eq(App(Var("f", fty), (Var("x", NAT),)), Var("x", NAT)))
        ctx = TranslationContext(request_id="neg-5")
        record = ctx.translate(source_construct="ho_quant_goal", term=goal, target=TranslationTarget.TPTP)
        self._assert_fails_closed(record, reason_contains="higher-order quantification")

    def test_higher_order_quantification_over_prop_type_fails_closed(self):
        goal = Forall("p", PROP_SORT, Var("p", PROP_SORT))
        ctx = TranslationContext(request_id="neg-6")
        record = ctx.translate(source_construct="ho_prop_quant_goal", term=goal, target=TranslationTarget.TPTP)
        self._assert_fails_closed(record, reason_contains="higher-order quantification")

    def test_higher_order_argument_passing_fails_closed(self):
        fty = FunctionTypeRef((NAT,), NAT)
        higher = Const("apply_twice", FunctionTypeRef((fty, NAT), NAT))
        g = Const("g", fty)
        goal = Eq(App(higher, (g, Var("x", NAT))), Var("x", NAT))
        ctx = TranslationContext(request_id="neg-7")
        record = ctx.translate(source_construct="ho_arg_goal", term=goal, target=TranslationTarget.TPTP)
        self._assert_fails_closed(record, reason_contains="higher-order")

    def test_escaping_lambda_fails_closed(self):
        lam1 = Lambda((LambdaParam("y", NAT),), BoolLit(True))
        lam2 = Lambda((LambdaParam("y", NAT),), BoolLit(False))
        goal = Eq(lam1, lam2)
        ctx = TranslationContext(request_id="neg-8")
        record = ctx.translate(source_construct="escaping_lambda_goal", term=goal, target=TranslationTarget.TPTP)
        self._assert_fails_closed(record, reason_contains="higher-order")

    def test_goal_not_a_proposition_fails_closed(self):
        c = Const("c", NAT)
        ctx = TranslationContext(request_id="neg-9")
        record = ctx.translate(source_construct="not_a_prop_goal", term=c, target=TranslationTarget.TPTP)
        self._assert_fails_closed(record, reason_contains="proposition")

    def test_malformed_term_fails_closed_instead_of_raising(self):
        p = make_predicate("P")
        # Deliberately malformed: applying a unary predicate to two arguments.
        bad = App(p, (Var("x", NAT), Var("y", NAT)))
        ctx = TranslationContext(request_id="neg-10")
        record = ctx.translate(source_construct="malformed_goal", term=bad, target=TranslationTarget.TPTP)
        self._assert_fails_closed(record, reason_contains="malformed")

    def test_unsupported_records_are_never_partial_or_supported(self):
        # Sanity check across every negative fixture above: none may report
        # SUPPORTED/PARTIAL, and none may carry obligations or translated
        # text, which would defeat the "fail closed" requirement.
        fixtures = [
            Eq(Const("v", DependentTypeRef("Vec n")), Const("v", DependentTypeRef("Vec n"))),
            Eq(Opaque("sorry"), Opaque("sorry")),
            Forall("p", PROP_SORT, Var("p", PROP_SORT)),
        ]
        ctx = TranslationContext(request_id="neg-11")
        for i, term in enumerate(fixtures):
            record = ctx.translate(
                source_construct=f"fixture-{i}", term=term, target=TranslationTarget.TPTP
            )
            assert record.status == TranslationStatus.UNSUPPORTED
            assert record.translated_text is None
            assert record.obligations == []


# ---------------------------------------------------------------------------
# Persistence: TranslationMap / TranslationContext
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_translation_map_entry_round_trips_through_dict(self):
        entry = TranslationMapEntry(
            source_name="P", target_name="p", target=TranslationTarget.TPTP, kind="function"
        )
        restored = TranslationMapEntry.from_dict(entry.to_dict())
        assert restored == entry

    def test_translation_map_round_trips_through_dict(self):
        tmap = TranslationMap()
        tmap.add(source_name="nat", target_name="nat", target=TranslationTarget.TPTP, kind="sort")
        restored = TranslationMap.from_dict(tmap.to_dict())
        assert restored.entries == tmap.entries

    def test_translation_map_content_digest_is_deterministic(self):
        tmap = TranslationMap()
        tmap.add(source_name="nat", target_name="nat", target=TranslationTarget.TPTP, kind="sort")
        d1 = tmap.content_digest()
        d2 = tmap.content_digest()
        assert d1 == d2
        assert isinstance(d1, str) and d1

    def test_translation_context_round_trips_through_dict(self):
        p = make_predicate("P")
        goal = Forall("x", NAT, App(p, (Var("x", NAT),)))
        ctx = TranslationContext(request_id="persist-1")
        ctx.translate(source_construct="goal", term=goal, target=TranslationTarget.TPTP)
        restored = TranslationContext.from_dict(ctx.to_dict())
        assert restored.request_id == ctx.request_id
        assert len(restored.records) == len(ctx.records)
        assert restored.records[0].translated_text == ctx.records[0].translated_text
        assert restored.translation_map.entries == ctx.translation_map.entries

    def test_translation_context_save_and_load_round_trip(self):
        p = make_predicate("P")
        goal = Forall("x", NAT, App(p, (Var("x", NAT),)))
        ctx = TranslationContext(request_id="persist-2")
        ctx.translate(source_construct="goal", term=goal, target=TranslationTarget.SMTLIB)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "translation_map.json")
            ctx.save(path)
            assert os.path.exists(path)
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            assert raw["request_id"] == "persist-2"
            loaded = TranslationContext.load(path)
        assert loaded.request_id == ctx.request_id
        assert loaded.records[0].translated_text == ctx.records[0].translated_text

    def test_unsupported_records_persist_with_reason_and_no_text(self):
        c = Const("v", DependentTypeRef("Vec n"))
        goal = Eq(c, c)
        ctx = TranslationContext(request_id="persist-3")
        ctx.translate(source_construct="dep_goal", term=goal, target=TranslationTarget.TPTP)
        restored = TranslationContext.from_dict(ctx.to_dict())
        record = restored.records[0]
        assert record.status == TranslationStatus.UNSUPPORTED
        assert record.translated_text is None
        assert record.unsupported_reason is not None


# ---------------------------------------------------------------------------
# TPTP rendering / parsing
# ---------------------------------------------------------------------------


class TestTPTPRendering:
    def test_render_emits_sort_and_symbol_declarations(self):
        p = make_predicate("P")
        goal = Forall("x", NAT, App(p, (Var("x", NAT),)))
        result = tptp.render_tff(goal)
        assert "tff(sort_0, type, nat: $tType)." in result.text
        assert "p: nat > $o" in result.text
        assert "conjecture" in result.text

    def test_render_maps_variables_to_uppercase_names(self):
        p = make_predicate("P")
        goal = Forall("x", NAT, App(p, (Var("x", NAT),)))
        result = tptp.render_tff(goal)
        target_name, kind = result.name_map["x"]
        assert kind == "variable"
        assert target_name[0].isupper()

    def test_render_maps_symbols_to_lowercase_names(self):
        p = make_predicate("Weird.Symbol'")
        goal = Forall("x", NAT, App(p, (Var("x", NAT),)))
        result = tptp.render_tff(goal)
        target_name, kind = result.name_map["Weird.Symbol'"]
        assert kind == "function"
        assert target_name[0].islower()

    def test_nullary_constant_renders_without_parentheses(self):
        c = Const("c", NAT)
        goal = Eq(c, c)
        result = tptp.render_tff(goal)
        assert "c = c" in result.text
        assert "c() = c()" not in result.text

    def test_render_raises_for_unsupported_type(self):
        c = Const("v", DependentTypeRef("Vec n"))
        with pytest.raises(tptp.TPTPRenderError):
            tptp.render_tff(Eq(c, c))

    def test_render_raises_for_escaping_lambda(self):
        lam = Lambda((LambdaParam("y", NAT),), BoolLit(True))
        with pytest.raises(tptp.TPTPRenderError):
            tptp.render_tff(Eq(lam, lam))

    @pytest.mark.parametrize(
        "goal_factory",
        [
            lambda: Forall(
                "x", NAT, Implies(App(make_predicate("P"), (Var("x", NAT),)), App(make_predicate("P"), (Var("x", NAT),)))
            ),
            lambda: Exists("x", NAT, App(make_predicate("Q"), (Var("x", NAT),))),
            lambda: Forall(
                "a",
                NAT,
                Forall(
                    "b",
                    NAT,
                    Eq(
                        App(make_binary_fn("f"), (Var("a", NAT), Var("b", NAT))),
                        App(make_binary_fn("f"), (Var("b", NAT), Var("a", NAT))),
                    ),
                ),
            ),
            lambda: Not(App(make_predicate("P"), (Const("c", NAT),))),
            lambda: And(BoolLit(True), Or(BoolLit(False), Iff(BoolLit(True), BoolLit(True)))),
        ],
    )
    def test_render_parse_round_trip_is_stable(self, goal_factory):
        goal = goal_factory()
        text1 = tptp.render_tff(goal).text
        parsed = tptp.parse_tff(text1)
        text2 = tptp.render_tff(parsed).text
        assert text1 == text2

    def test_parse_rejects_malformed_text(self):
        with pytest.raises(tptp.TPTPParseError):
            tptp.parse_tff("not tptp at all")

    def test_parse_rejects_missing_conjecture_clause(self):
        with pytest.raises(tptp.TPTPParseError):
            tptp.parse_tff("tff(sort_0, type, nat: $tType).")

    def test_parse_rejects_unbalanced_parentheses(self):
        with pytest.raises(tptp.TPTPParseError):
            tptp.parse_tff("tff(goal, conjecture, ($true).")


# ---------------------------------------------------------------------------
# SMT-LIB rendering / parsing
# ---------------------------------------------------------------------------


class TestSMTLIBRendering:
    def test_render_emits_sort_and_function_declarations(self):
        p = make_predicate("P")
        goal = Forall("x", NAT, App(p, (Var("x", NAT),)))
        result = smtlib.render_smtlib(goal)
        assert "(declare-sort nat 0)" in result.text
        assert "(declare-fun P (nat) Bool)" in result.text
        assert "(assert" in result.text

    def test_nullary_constant_renders_bare(self):
        c = Const("c", NAT)
        goal = Eq(c, c)
        result = smtlib.render_smtlib(goal)
        assert "(= c c)" in result.text

    def test_render_raises_for_unsupported_type(self):
        c = Const("v", DependentTypeRef("Vec n"))
        with pytest.raises(smtlib.SMTLIBRenderError):
            smtlib.render_smtlib(Eq(c, c))

    def test_render_raises_for_escaping_lambda(self):
        lam = Lambda((LambdaParam("y", NAT),), BoolLit(True))
        with pytest.raises(smtlib.SMTLIBRenderError):
            smtlib.render_smtlib(Eq(lam, lam))

    @pytest.mark.parametrize(
        "goal_factory",
        [
            lambda: Forall(
                "x", NAT, Implies(App(make_predicate("P"), (Var("x", NAT),)), App(make_predicate("P"), (Var("x", NAT),)))
            ),
            lambda: Exists("x", NAT, App(make_predicate("Q"), (Var("x", NAT),))),
            lambda: Forall(
                "a",
                NAT,
                Forall(
                    "b",
                    NAT,
                    Eq(
                        App(make_binary_fn("f"), (Var("a", NAT), Var("b", NAT))),
                        App(make_binary_fn("f"), (Var("b", NAT), Var("a", NAT))),
                    ),
                ),
            ),
            lambda: Not(App(make_predicate("P"), (Const("c", NAT),))),
            lambda: And(BoolLit(True), Or(BoolLit(False), Iff(BoolLit(True), BoolLit(True)))),
        ],
    )
    def test_render_parse_round_trip_is_stable(self, goal_factory):
        goal = goal_factory()
        text1 = smtlib.render_smtlib(goal).text
        parsed = smtlib.parse_smtlib(text1)
        text2 = smtlib.render_smtlib(parsed).text
        assert text1 == text2

    def test_parse_rejects_missing_assert(self):
        with pytest.raises(smtlib.SMTLIBParseError):
            smtlib.parse_smtlib("(declare-sort nat 0)")

    def test_parse_rejects_unbalanced_parentheses(self):
        with pytest.raises(smtlib.SMTLIBParseError):
            smtlib.parse_smtlib("(assert (not $true)")

    def test_parse_rejects_unknown_command(self):
        with pytest.raises(smtlib.SMTLIBParseError):
            smtlib.parse_smtlib("(check-sat)")


# ---------------------------------------------------------------------------
# Full-pipeline round trip (translation -> render -> parse -> re-render)
# ---------------------------------------------------------------------------


class TestFullPipelineRoundTrip:
    def test_supported_goal_round_trips_through_tptp(self):
        p = make_predicate("P")
        goal = Forall("x", NAT, Implies(App(p, (Var("x", NAT),)), App(p, (Var("x", NAT),))))
        ctx = TranslationContext(request_id="rt-1")
        record = ctx.translate(source_construct="goal", term=goal, target=TranslationTarget.TPTP)
        parsed = tptp.parse_tff(record.translated_text)
        re_rendered = tptp.render_tff(parsed).text
        assert re_rendered == record.translated_text

    def test_supported_goal_round_trips_through_smtlib(self):
        p = make_predicate("P")
        goal = Forall("x", NAT, Implies(App(p, (Var("x", NAT),)), App(p, (Var("x", NAT),))))
        ctx = TranslationContext(request_id="rt-2")
        record = ctx.translate(source_construct="goal", term=goal, target=TranslationTarget.SMTLIB)
        parsed = smtlib.parse_smtlib(record.translated_text)
        re_rendered = smtlib.render_smtlib(parsed).text
        assert re_rendered == record.translated_text

    def test_lambda_lifted_definition_round_trips_through_both_targets(self):
        p = make_predicate("P")
        lam_def = Lambda((LambdaParam("n", NAT),), App(p, (Var("n", NAT),)))

        ctx_tptp = TranslationContext(request_id="rt-3")
        rec_tptp = ctx_tptp.translate(
            source_construct="my_def", term=lam_def, target=TranslationTarget.TPTP
        )
        assert tptp.render_tff(tptp.parse_tff(rec_tptp.translated_text)).text == rec_tptp.translated_text

        ctx_smt = TranslationContext(request_id="rt-4")
        rec_smt = ctx_smt.translate(
            source_construct="my_def", term=lam_def, target=TranslationTarget.SMTLIB
        )
        assert (
            smtlib.render_smtlib(smtlib.parse_smtlib(rec_smt.translated_text)).text
            == rec_smt.translated_text
        )

    def test_monomorphized_goal_round_trips_through_both_targets(self):
        alpha = TypeVarRef("alpha")
        idfn = Const("id", FunctionTypeRef((alpha,), alpha))
        goal = Forall("x", NAT, Eq(App(idfn, (Var("x", alpha),)), Var("x", alpha)))

        ctx_tptp = TranslationContext(request_id="rt-5")
        rec_tptp = ctx_tptp.translate(
            source_construct="mono_goal",
            term=goal,
            target=TranslationTarget.TPTP,
            monomorphization={"alpha": NAT},
        )
        assert tptp.render_tff(tptp.parse_tff(rec_tptp.translated_text)).text == rec_tptp.translated_text

        ctx_smt = TranslationContext(request_id="rt-6")
        rec_smt = ctx_smt.translate(
            source_construct="mono_goal",
            term=goal,
            target=TranslationTarget.SMTLIB,
            monomorphization={"alpha": NAT},
        )
        assert (
            smtlib.render_smtlib(smtlib.parse_smtlib(rec_smt.translated_text)).text
            == rec_smt.translated_text
        )
