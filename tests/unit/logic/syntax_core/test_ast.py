"""Unit tests for typed core AST, binders, sorts, and signatures (LFP-012)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from ipfs_datasets_py.logic.families.namespaces import (
    family_id,
    profile_id,
)
from ipfs_datasets_py.logic.syntax_core.ast import (
    AST_MODULE_VERSION,
    LOGIC_EXTENSION_NODE_INTERFACE,
    TYPED_EXPRESSION_INTERFACE,
    AstError,
    Binder,
    LogicExtensionNode,
    LogicNode,
    NodeKind,
    TypedExpression,
    elaborate,
    mk_and,
    mk_application,
    mk_constant,
    mk_equality,
    mk_exists,
    mk_extension,
    mk_false,
    mk_forall,
    mk_iff,
    mk_implies,
    mk_let,
    mk_not,
    mk_or,
    mk_predicate,
    mk_true,
    mk_variable,
)
from ipfs_datasets_py.logic.syntax_core.signatures import (
    BOOL_SORT,
    INDIVIDUAL_SORT,
    LOGIC_SIGNATURE_INTERFACE,
    SIGNATURES_MODULE_VERSION,
    LogicSignature,
    LogicSort,
    SignatureError,
    SortKind,
    SymbolDeclaration,
    SymbolKind,
    atomic_sort,
    declare_constant,
    declare_function,
    declare_predicate,
    many_sorted_fol_signature,
    parametric_sort,
    propositional_signature,
)


# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------


def _person() -> LogicSort:
    return atomic_sort("Person")


def _fol_signature() -> LogicSignature:
    person = _person()
    return many_sorted_fol_signature(
        "sig:fol:1",
        sorts=(person,),
        constants=(("alice", person), ("bob", person)),
        functions=(("father", (person,), person),),
        predicates=(
            ("Human", (person,)),
            ("Knows", (person, person)),
            ("Rains", ()),
        ),
        family="first_order",
        profile="many_sorted",
    )


def _prop_signature() -> LogicSignature:
    return propositional_signature("sig:prop:1", ("P", "Q", "R"))


# ---------------------------------------------------------------------------
# Module / interface identity
# ---------------------------------------------------------------------------


def test_module_versions_and_interfaces() -> None:
    assert AST_MODULE_VERSION == "1.0.0"
    assert SIGNATURES_MODULE_VERSION == "1.0.0"
    assert LOGIC_SIGNATURE_INTERFACE == "LogicSignature@1"
    assert TYPED_EXPRESSION_INTERFACE == "TypedExpression@1"
    assert LOGIC_EXTENSION_NODE_INTERFACE == "LogicExtensionNode@1"
    assert BOOL_SORT.is_bool
    assert BOOL_SORT.name == "Bool"
    assert BOOL_SORT.kind is SortKind.BOOL


# ---------------------------------------------------------------------------
# Sorts and signatures
# ---------------------------------------------------------------------------


def test_logic_sort_round_trip_and_parametric() -> None:
    index = atomic_sort("Index")
    elem = atomic_sort("Elem")
    array = parametric_sort("Array", index, elem)
    assert array.arity == 2
    assert str(array) == "Array(Index, Elem)"
    restored = LogicSort.from_dict(array.to_dict())
    assert restored == array


def test_signature_injects_bool_and_rejects_duplicates() -> None:
    sig = _fol_signature()
    assert sig.interface == LOGIC_SIGNATURE_INTERFACE
    assert sig.has_sort("Bool")
    assert sig.get_sort("Bool") == BOOL_SORT
    assert sig.get_symbol("alice").kind is SymbolKind.CONSTANT
    assert sig.get_symbol("father").arity == 1
    assert sig.get_symbol("Knows").arity == 2
    assert sig.get_symbol("Rains").arity == 0

    restored = LogicSignature.from_dict(sig.to_dict())
    assert restored.signature_id == sig.signature_id
    assert restored.get_symbol("Human").result_sort == BOOL_SORT

    with pytest.raises(SignatureError, match="unique names"):
        LogicSignature(
            signature_id="sig:dup",
            family="first_order",
            profile="many_sorted",
            sorts=(_person(), _person()),
            symbols=(),
        )


def test_signature_rejects_undeclared_sort_on_symbol() -> None:
    ghost = atomic_sort("Ghost")
    with pytest.raises(SignatureError, match="undeclared sort"):
        LogicSignature(
            signature_id="sig:bad",
            family="first_order",
            profile="many_sorted",
            sorts=(),
            symbols=(declare_constant("c", ghost),),
        )


def test_signature_rejects_function_bool_range_and_constant_arity() -> None:
    person = _person()
    with pytest.raises(SignatureError, match="must not be Bool"):
        declare_function("bad", (person,), BOOL_SORT)
    with pytest.raises(SignatureError, match="nullary"):
        SymbolDeclaration(
            name="c",
            kind=SymbolKind.CONSTANT,
            domain=(person,),
            range=person,
        )
    with pytest.raises(SignatureError, match="non-empty domain"):
        declare_function("f", (), person)


def test_signature_check_application_arity_and_domain() -> None:
    sig = _fol_signature()
    person = _person()
    result = sig.check_application("father", (person,), expected_kind=SymbolKind.FUNCTION)
    assert result == person
    with pytest.raises(SignatureError, match="arity"):
        sig.check_application("father", (person, person))
    with pytest.raises(SignatureError, match="argument 0"):
        sig.check_application("father", (INDIVIDUAL_SORT,))
    with pytest.raises(SignatureError, match="expected 'function'"):
        sig.check_application("Human", (person,), expected_kind=SymbolKind.FUNCTION)


def test_signature_symbol_sort_name_collision() -> None:
    person = _person()
    with pytest.raises(SignatureError, match="collide"):
        LogicSignature(
            signature_id="sig:collide",
            family="first_order",
            profile="many_sorted",
            sorts=(person,),
            symbols=(declare_constant("Person", person),),
        )


def test_signature_is_immutable() -> None:
    sig = _prop_signature()
    with pytest.raises(FrozenInstanceError):
        sig.signature_id = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Core AST nodes — happy path
# ---------------------------------------------------------------------------


def test_propositional_connectives() -> None:
    p = mk_predicate("n:p", "P")
    q = mk_predicate("n:q", "Q")
    formula = mk_implies(
        "n:imp",
        mk_and("n:and", p, q),
        mk_or("n:or", mk_not("n:not", p), q),
    )
    assert formula.is_formula
    assert formula.result_sort == BOOL_SORT
    assert formula.kind is NodeKind.IMPLIES

    sig = _prop_signature()
    elaborated = elaborate(formula, sig)
    expr = TypedExpression(expression_id="expr:prop:1", root=formula, signature=sig)
    assert expr.interface == TYPED_EXPRESSION_INTERFACE
    assert expr.is_formula
    assert expr.content_digest
    assert elaborated.kind is NodeKind.IMPLIES

    restored = TypedExpression.from_dict(expr.to_dict())
    assert restored.expression_id == expr.expression_id
    assert restored.content_digest == expr.content_digest
    assert restored.root.kind is NodeKind.IMPLIES


def test_many_sorted_terms_predicates_equality_quantifiers_let() -> None:
    sig = _fol_signature()
    person = _person()
    alice = mk_constant("n:alice", "alice", person)
    bob = mk_constant("n:bob", "bob", person)
    x = mk_variable("n:x", "x", person)
    father_x = mk_application("n:father", "father", (x,), sort=person)
    human_alice = mk_predicate("n:human", "Human", (alice,))
    knows = mk_predicate("n:knows", "Knows", (alice, bob))
    eq = mk_equality("n:eq", father_x, bob)
    rains = mk_predicate("n:rains", "Rains")

    body = mk_implies("n:body", human_alice, mk_and("n:conj", knows, eq, rains))
    quantified = mk_forall("n:all", (Binder(name="x", sort=person),), body)
    exists = mk_exists(
        "n:ex",
        (Binder(name="y", sort=person),),
        mk_predicate("n:hy", "Human", (mk_variable("n:y", "y", person),)),
    )
    let_node = mk_let(
        "n:let",
        Binder(name="z", sort=person),
        alice,
        mk_predicate("n:hz", "Human", (mk_variable("n:z", "z", person),)),
    )
    root = mk_and("n:root", quantified, exists, let_node, mk_true(), mk_false())

    expr = TypedExpression(expression_id="expr:fol:1", root=root, signature=sig)
    assert expr.root.is_formula
    assert "x" not in expr.root.arguments[0].free_variable_names()
    # free vars of body before quantifier would include nothing from constants
    assert father_x.free_variable_names() == frozenset({"x"})

    # Round-trip preserves structure
    restored = TypedExpression.from_dict(expr.to_dict())
    assert restored.content_digest == expr.content_digest
    assert restored.root.kind is NodeKind.AND


def test_extension_node_declares_family_profile_features() -> None:
    inner = mk_predicate("n:p", "P")
    node = mk_extension(
        "n:box",
        family="modal",
        profile="s5",
        features=("modal.box", "modal.kripke"),
        payload_schema="modal.box/v1",
        payload={"kind": "box", "agent": "a1", "schema_version": "1"},
        children=(inner,),
    )
    assert node.kind is NodeKind.EXTENSION
    assert node.extension is not None
    assert node.extension.interface == LOGIC_EXTENSION_NODE_INTERFACE
    assert node.extension.family == family_id("modal")
    assert node.extension.profile == profile_id("s5")
    assert "modal.box" in node.extension.features

    sig = _prop_signature()
    # Extension over propositional atoms still elaborates children.
    expr = TypedExpression(expression_id="expr:modal:1", root=node, signature=sig)
    assert expr.root.extension is not None
    restored = LogicExtensionNode.from_dict(expr.root.extension.to_dict())
    assert restored.payload_schema == "modal.box/v1"


def test_nodes_are_immutable() -> None:
    node = mk_true("n:t")
    with pytest.raises(FrozenInstanceError):
        node.node_id = "mut"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Construction failures — shape
# ---------------------------------------------------------------------------


def test_connective_arity_failures() -> None:
    p = mk_predicate("n:p", "P")
    with pytest.raises(AstError, match="exactly one"):
        LogicNode(node_id="n:bad", kind=NodeKind.NOT, arguments=())
    with pytest.raises(AstError, match="at least two"):
        LogicNode(node_id="n:bad", kind=NodeKind.AND, arguments=(p,))
    with pytest.raises(AstError, match="exactly two"):
        LogicNode(node_id="n:bad", kind=NodeKind.IMPLIES, arguments=(p,))
    with pytest.raises(AstError, match="exactly two"):
        LogicNode(
            node_id="n:bad",
            kind=NodeKind.EQUALITY,
            arguments=(mk_constant("n:c", "c", _person()),),
        )


def test_quantifier_requires_binders_and_formula_body() -> None:
    person = _person()
    with pytest.raises(AstError, match="at least one binder"):
        LogicNode(
            node_id="n:bad",
            kind=NodeKind.FORALL,
            binders=(),
            arguments=(mk_true(),),
        )
    with pytest.raises(AstError, match="body must be a formula"):
        mk_forall(
            "n:bad",
            (Binder(name="x", sort=person),),
            mk_constant("n:c", "c", person),
        )
    with pytest.raises(AstError, match="Boolean sort"):
        Binder(name="x", sort=BOOL_SORT)


def test_application_requires_term_arguments() -> None:
    with pytest.raises(AstError, match="at least one argument"):
        LogicNode(
            node_id="n:bad",
            kind=NodeKind.APPLICATION,
            symbol="f",
            arguments=(),
            sort=_person(),
        )
    with pytest.raises(AstError, match="must be terms"):
        mk_application(
            "n:bad",
            "f",
            (mk_true(),),
            sort=_person(),
        )


def test_let_sort_mismatch_at_construction() -> None:
    person = _person()
    other = atomic_sort("Other")
    with pytest.raises(AstError, match="does not match"):
        mk_let(
            "n:bad",
            Binder(name="z", sort=person),
            mk_constant("n:c", "c", other),
            mk_variable("n:z", "z", person),
        )


# ---------------------------------------------------------------------------
# Elaboration / signature failures
# ---------------------------------------------------------------------------


def test_elaborate_rejects_unknown_symbol_and_arity() -> None:
    sig = _fol_signature()
    person = _person()
    with pytest.raises(AstError, match="unknown symbol"):
        elaborate(mk_predicate("n:p", "Unknown", (mk_constant("n:a", "alice", person),)), sig)
    with pytest.raises(AstError, match="arity"):
        elaborate(
            mk_predicate(
                "n:p",
                "Human",
                (
                    mk_constant("n:a", "alice", person),
                    mk_constant("n:b", "bob", person),
                ),
            ),
            sig,
        )


def test_elaborate_rejects_sort_mismatch_on_application() -> None:
    sig = _fol_signature()
    # father expects Person; feed Individual-sorted constant not in signature domain
    # Build a bad tree: use bob (Person) is fine; force wrong by declaring a free var
    # of wrong sort as argument.
    wrong = mk_variable("n:v", "v", INDIVIDUAL_SORT)
    with pytest.raises(AstError, match="argument 0|expects sort"):
        elaborate(mk_application("n:f", "father", (wrong,), sort=_person()), sig)


def test_elaborate_rejects_equality_sort_mismatch() -> None:
    person = _person()
    other = atomic_sort("Other")
    sig = many_sorted_fol_signature(
        "sig:eq",
        sorts=(person, other),
        constants=(("a", person), ("b", other)),
        predicates=(),
    )
    with pytest.raises(AstError, match="equality sort mismatch"):
        elaborate(
            mk_equality(
                "n:eq",
                mk_constant("n:a", "a", person),
                mk_constant("n:b", "b", other),
            ),
            sig,
        )


def test_typed_expression_rejects_family_mismatch() -> None:
    sig = _prop_signature()
    root = mk_predicate("n:p", "P")
    with pytest.raises(AstError, match="does not match signature family"):
        TypedExpression(
            expression_id="expr:bad",
            root=root,
            signature=sig,
            family="modal",
        )


def test_typed_expression_rejects_bad_content_digest() -> None:
    sig = _prop_signature()
    root = mk_predicate("n:p", "P")
    with pytest.raises(AstError, match="content_digest"):
        TypedExpression(
            expression_id="expr:bad",
            root=root,
            signature=sig,
            content_digest="0" * 64,
        )


# ---------------------------------------------------------------------------
# Extension node rejection of opaque unversioned payloads
# ---------------------------------------------------------------------------


def test_extension_requires_family_profile_features() -> None:
    with pytest.raises(AstError, match="features must be non-empty"):
        LogicExtensionNode(
            node_id="ext:1",
            family="modal",
            profile="s5",
            features=(),
            payload_schema="modal.box/v1",
            payload={"kind": "box"},
        )
    with pytest.raises(Exception):
        # Wrong namespace for family should fail closed via require_namespace_identity
        LogicExtensionNode(
            node_id="ext:2",
            family=profile_id("s5"),  # profile used as family
            profile="s5",
            features=("modal.box",),
            payload_schema="modal.box/v1",
            payload={"kind": "box"},
        )


def test_extension_rejects_unversioned_payload_schema() -> None:
    with pytest.raises(AstError, match="versioned schema"):
        LogicExtensionNode(
            node_id="ext:3",
            family="modal",
            profile="s5",
            features=("modal.box",),
            payload_schema="modal_box",  # no /vN
            payload={"kind": "box"},
        )
    with pytest.raises(AstError, match="versioned schema"):
        LogicExtensionNode(
            node_id="ext:4",
            family="modal",
            profile="s5",
            features=("modal.box",),
            payload_schema="unversioned",
            payload={"kind": "box"},
        )


def test_extension_rejects_opaque_payloads() -> None:
    with pytest.raises(AstError, match="structured mapping|opaque"):
        LogicExtensionNode(
            node_id="ext:5",
            family="modal",
            profile="s5",
            features=("modal.box",),
            payload_schema="modal.box/v1",
            payload="raw-blob",  # type: ignore[arg-type]
        )
    with pytest.raises(AstError, match="empty|opaque"):
        LogicExtensionNode(
            node_id="ext:6",
            family="modal",
            profile="s5",
            features=("modal.box",),
            payload_schema="modal.box/v1",
            payload={},
        )
    with pytest.raises(AstError, match="opaque"):
        LogicExtensionNode(
            node_id="ext:7",
            family="modal",
            profile="s5",
            features=("modal.box",),
            payload_schema="modal.box/v1",
            payload={"blob": "aaaa"},
        )


def test_extension_accepts_versioned_structured_payload() -> None:
    ext = LogicExtensionNode(
        node_id="ext:ok",
        family="temporal",
        profile="ltl",
        features=("temporal.next",),
        payload_schema="temporal.next/v1",
        payload={"kind": "next", "schema_version": "temporal.next/v1"},
        children=(mk_predicate("n:p", "P"),),
    )
    assert ext.family == family_id("temporal")
    assert ext.to_dict()["payload_schema"] == "temporal.next/v1"


# ---------------------------------------------------------------------------
# Free variables and binder scoping (syntactic)
# ---------------------------------------------------------------------------


def test_free_variables_respect_quantifiers_and_lets() -> None:
    person = _person()
    x = mk_variable("n:x", "x", person)
    y = mk_variable("n:y", "y", person)
    pred = mk_predicate("n:k", "Knows", (x, y))
    assert pred.free_variable_names() == frozenset({"x", "y"})

    forall_x = mk_forall("n:all", (Binder(name="x", sort=person),), pred)
    assert forall_x.free_variable_names() == frozenset({"y"})

    let_y = mk_let(
        "n:let",
        Binder(name="y", sort=person),
        mk_constant("n:a", "alice", person),
        pred,
    )
    # y bound in body; x free; alice is constant (not a variable node in value... value is constant)
    # pred still has free x and y, but y is bound by let in body; value side has no free vars
    assert let_y.free_variable_names() == frozenset({"x"})


def test_iff_and_true_false_elaborate() -> None:
    sig = _prop_signature()
    formula = mk_iff("n:iff", mk_true(), mk_not("n:n", mk_false()))
    elaborated = elaborate(formula, sig)
    assert elaborated.kind is NodeKind.IFF
    expr = TypedExpression(expression_id="expr:tf", root=formula, signature=sig)
    assert expr.result_sort == BOOL_SORT
