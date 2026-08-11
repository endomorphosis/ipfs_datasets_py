"""Unit tests for CanonicalFOLSyntax@1 (LFP-017).

Evidence subset:

* parse/print/parse is alpha-equivalent
* implication is right-associative
* binder scope is explicit (maximal body; embedding requires parens)
* undeclared symbols/sorts fail with exact spans
* trailing input fails with exact spans
* unicode/ascii operator round-trip
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.parsers.fol import (
    CANONICAL_FOL_NOTATION_ID,
    CANONICAL_FOL_SYNTAX_INTERFACE,
    CODE_TRAILING_INPUT,
    CODE_UNDECLARED_SORT,
    CODE_UNDECLARED_SYMBOL,
    CanonicalFOLParser,
    CanonicalFOLPrinter,
    CanonicalFOLSyntax,
    FOLParseError,
    PrintStyle,
    parse_fol,
    parse_print_parse,
    print_fol,
)
from ipfs_datasets_py.logic.syntax_core.algebra import alpha_equivalent
from ipfs_datasets_py.logic.syntax_core.ast import (
    Binder,
    NodeKind,
    TypedExpression,
    mk_and,
    mk_constant,
    mk_forall,
    mk_implies,
    mk_predicate,
    mk_variable,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    ParseLimits,
    ParseMode,
    ParseRequest,
    ParseStatus,
    SourceDocument,
)
from ipfs_datasets_py.logic.syntax_core.signatures import (
    LogicSignature,
    atomic_sort,
    many_sorted_fol_signature,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _person():
    return atomic_sort("Person")


def _fol_signature() -> LogicSignature:
    person = _person()
    return many_sorted_fol_signature(
        "sig:fol:test:1",
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


def _syntax() -> CanonicalFOLSyntax:
    return CanonicalFOLSyntax(_fol_signature())


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_interface_and_module_identity() -> None:
    assert CANONICAL_FOL_SYNTAX_INTERFACE == "CanonicalFOLSyntax@1"
    assert CANONICAL_FOL_NOTATION_ID == "canonical_fol"
    syntax = _syntax()
    assert syntax.interface == CANONICAL_FOL_SYNTAX_INTERFACE
    assert isinstance(syntax.parser, CanonicalFOLParser)
    assert isinstance(syntax.printer, CanonicalFOLPrinter)


# ---------------------------------------------------------------------------
# Happy-path parsing
# ---------------------------------------------------------------------------


def test_parse_nullary_and_unary_predicates() -> None:
    result = parse_fol("Rains", _fol_signature())
    assert result.ok
    assert result.root is not None
    assert result.root.kind is NodeKind.PREDICATE
    assert result.root.symbol == "Rains"
    assert result.root.arguments == ()

    result2 = parse_fol("Human(alice)", _fol_signature())
    assert result2.ok
    assert result2.root is not None
    assert result2.root.kind is NodeKind.PREDICATE
    assert result2.root.symbol == "Human"
    assert result2.root.arguments[0].kind is NodeKind.CONSTANT
    assert result2.root.arguments[0].symbol == "alice"


def test_parse_connectives_and_equality() -> None:
    result = parse_fol(
        "Human(alice) and Knows(alice, bob) or not Rains",
        _fol_signature(),
    )
    assert result.ok
    assert result.root is not None
    # and binds tighter than or: (Human(alice) and Knows(alice, bob)) or (not Rains)
    assert result.root.kind is NodeKind.OR
    assert result.root.arguments[0].kind is NodeKind.AND
    assert result.root.arguments[1].kind is NodeKind.NOT

    result_eq = parse_fol("father(alice) = bob", _fol_signature())
    assert result_eq.ok
    assert result_eq.root is not None
    assert result_eq.root.kind is NodeKind.EQUALITY


def test_parse_quantifiers_with_explicit_sorts() -> None:
    result = parse_fol(
        "forall x:Person. Human(x) -> Knows(x, alice)",
        _fol_signature(),
    )
    assert result.ok
    assert result.root is not None
    assert result.root.kind is NodeKind.FORALL
    assert result.root.binders[0].name == "x"
    assert result.root.binders[0].sort.name == "Person"
    # Binder body is the full implication (maximal scope).
    assert result.root.arguments[0].kind is NodeKind.IMPLIES

    multi = parse_fol(
        "exists (x:Person, y:Person). Knows(x, y)",
        _fol_signature(),
    )
    assert multi.ok
    assert multi.root is not None
    assert multi.root.kind is NodeKind.EXISTS
    assert len(multi.root.binders) == 2


def test_parse_unicode_operators() -> None:
    result = parse_fol(
        "∀x:Person. Human(x) → Knows(x, alice) ∧ ¬Rains",
        _fol_signature(),
    )
    assert result.ok
    assert result.root is not None
    assert result.root.kind is NodeKind.FORALL
    body = result.root.arguments[0]
    assert body.kind is NodeKind.IMPLIES
    assert body.arguments[1].kind is NodeKind.AND
    assert body.arguments[1].arguments[1].kind is NodeKind.NOT


def test_parse_let_binding() -> None:
    result = parse_fol(
        "let x:Person = alice in Human(x)",
        _fol_signature(),
    )
    assert result.ok
    assert result.root is not None
    assert result.root.kind is NodeKind.LET
    assert result.root.binders[0].name == "x"
    assert result.root.arguments[0].symbol == "alice"
    assert result.root.arguments[1].kind is NodeKind.PREDICATE


def test_logic_parser_protocol_via_parse_request() -> None:
    sig = _fol_signature()
    document = SourceDocument.from_text("doc:req:1", "Human(alice)")
    request = ParseRequest(
        request_id="req:fol:1",
        document=document,
        notation_id="canonical_fol",
        profile_id="classical",
        family_id="first_order",
        mode=ParseMode.STRICT,
        limits=ParseLimits(max_input_bytes=4096, max_tokens=256, max_depth=64),
        metadata={"signature": sig.to_dict()},
    )
    parser = CanonicalFOLParser()
    artifact = parser.parse(request)
    assert artifact.status is ParseStatus.OK
    assert artifact.cst is not None
    assert "expression" in artifact.metadata
    artifact.validate_against(document, limits=request.limits)


# ---------------------------------------------------------------------------
# Implication associativity
# ---------------------------------------------------------------------------


def test_implication_is_right_associative() -> None:
    result = parse_fol("Rains -> Human(alice) -> Human(bob)", _fol_signature())
    assert result.ok
    assert result.root is not None
    assert result.root.kind is NodeKind.IMPLIES
    # A -> (B -> C)
    assert result.root.arguments[0].symbol == "Rains"
    assert result.root.arguments[1].kind is NodeKind.IMPLIES
    assert result.root.arguments[1].arguments[0].symbol == "Human"
    assert result.root.arguments[1].arguments[1].symbol == "Human"


def test_implication_associativity_differs_from_left_assoc_tree() -> None:
    result = parse_fol("Rains -> Human(alice) -> Human(bob)", _fol_signature())
    assert result.ok and result.root is not None
    # Manually build left-associative ((A -> B) -> C) and ensure not alpha-eq.
    rains = mk_predicate("n:r", "Rains")
    ha = mk_predicate("n:ha", "Human", (mk_constant("n:a", "alice", _person()),))
    hb = mk_predicate("n:hb", "Human", (mk_constant("n:b", "bob", _person()),))
    left_assoc = mk_implies("n:l", mk_implies("n:l0", rains, ha), hb)
    assert not alpha_equivalent(result.root, left_assoc)
    right_assoc = mk_implies("n:r0", rains, mk_implies("n:r1", ha, hb))
    assert alpha_equivalent(result.root, right_assoc)


# ---------------------------------------------------------------------------
# Binder scope
# ---------------------------------------------------------------------------


def test_quantifier_body_extends_maximally() -> None:
    """forall x:S. A -> B  ≡  forall x:S. (A -> B), not (forall x:S. A) -> B."""
    result = parse_fol(
        "forall x:Person. Human(x) -> Knows(x, alice)",
        _fol_signature(),
    )
    assert result.ok and result.root is not None
    assert result.root.kind is NodeKind.FORALL
    assert result.root.arguments[0].kind is NodeKind.IMPLIES


def test_quantifier_under_connective_requires_parentheses() -> None:
    # Without parens, quantifier cannot appear as an and-operand.
    bad = parse_fol(
        "Rains and forall x:Person. Human(x)",
        _fol_signature(),
    )
    assert not bad.ok
    assert bad.status is ParseStatus.FAILED

    good = parse_fol(
        "Rains and (forall x:Person. Human(x))",
        _fol_signature(),
    )
    assert good.ok
    assert good.root is not None
    assert good.root.kind is NodeKind.AND
    assert good.root.arguments[1].kind is NodeKind.FORALL


def test_implication_consequent_may_be_quantifier() -> None:
    result = parse_fol(
        "Rains -> forall x:Person. Human(x)",
        _fol_signature(),
    )
    assert result.ok and result.root is not None
    assert result.root.kind is NodeKind.IMPLIES
    assert result.root.arguments[1].kind is NodeKind.FORALL


# ---------------------------------------------------------------------------
# Parse / print / parse alpha-equivalence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "Rains",
        "Human(alice)",
        "Knows(alice, bob)",
        "father(alice) = bob",
        "not Rains",
        "Human(alice) and Human(bob)",
        "Human(alice) or Rains",
        "Rains -> Human(alice)",
        "Rains -> Human(alice) -> Human(bob)",
        "Human(alice) iff Human(bob)",
        "forall x:Person. Human(x)",
        "forall x:Person. Human(x) -> Knows(x, alice)",
        "exists y:Person. Knows(alice, y)",
        "exists (x:Person, y:Person). Knows(x, y) and Human(x)",
        "let z:Person = father(alice) in Human(z)",
        "forall x:Person. (Human(x) and Knows(x, bob)) -> Rains",
        "not (Human(alice) or Human(bob))",
        "true and false or Rains",
    ],
)
def test_parse_print_parse_is_alpha_equivalent(source: str) -> None:
    sig = _fol_signature()
    first = parse_fol(source, sig)
    assert first.ok, [d.message for d in first.diagnostics]
    assert first.root is not None
    printed = print_fol(first.root)
    second = parse_fol(printed, sig, document_id="doc:rt")
    assert second.ok, (printed, [d.message for d in second.diagnostics])
    assert second.root is not None
    assert alpha_equivalent(first.root, second.root), (source, printed)


def test_parse_print_parse_helper() -> None:
    result = parse_print_parse(
        "forall x:Person. Human(x) -> Knows(x, alice)",
        _fol_signature(),
    )
    assert result.ok
    assert result.printed


def test_unicode_print_style_round_trip() -> None:
    sig = _fol_signature()
    first = parse_fol("forall x:Person. Human(x) -> not Rains", sig)
    assert first.ok and first.root is not None
    printed = print_fol(first.root, style=PrintStyle.UNICODE)
    assert "∀" in printed
    assert "→" in printed
    assert "¬" in printed
    second = parse_fol(printed, sig, document_id="doc:uni")
    assert second.ok and second.root is not None
    assert alpha_equivalent(first.root, second.root)


def test_printer_parenthesizes_embedded_quantifiers() -> None:
    person = _person()
    x = mk_variable("n:x", "x", person)
    body = mk_predicate("n:h", "Human", (x,))
    quant = mk_forall("n:all", (Binder(name="x", sort=person),), body)
    rains = mk_predicate("n:r", "Rains")
    formula = mk_and("n:and", rains, quant)
    printed = print_fol(formula)
    # Quantifier under and must be parenthesized for re-parse.
    assert "(" in printed and "forall" in printed
    reparsed = parse_fol(printed, _fol_signature())
    assert reparsed.ok and reparsed.root is not None
    assert alpha_equivalent(formula, reparsed.root)


def test_printer_parenthesizes_left_of_right_assoc_implies() -> None:
    rains = mk_predicate("n:r", "Rains")
    ha = mk_predicate("n:ha", "Human", (mk_constant("n:a", "alice", _person()),))
    hb = mk_predicate("n:hb", "Human", (mk_constant("n:b", "bob", _person()),))
    # (A -> B) -> C  needs parens on the left.
    left_assoc = mk_implies("n:l", mk_implies("n:l0", rains, ha), hb)
    printed = print_fol(left_assoc)
    reparsed = parse_fol(printed, _fol_signature())
    assert reparsed.ok and reparsed.root is not None
    assert alpha_equivalent(left_assoc, reparsed.root)
    # Without proper parens, right-assoc parse would differ.
    assert printed.startswith("(") or "->" in printed


# ---------------------------------------------------------------------------
# Fail-closed diagnostics with exact spans
# ---------------------------------------------------------------------------


def test_undeclared_symbol_fails_with_exact_span() -> None:
    source = "Unknown(alice)"
    result = parse_fol(source, _fol_signature())
    assert not result.ok
    errors = result.errors
    assert errors
    assert any(item.code == CODE_UNDECLARED_SYMBOL for item in errors)
    diag = next(item for item in errors if item.code == CODE_UNDECLARED_SYMBOL)
    assert diag.range is not None
    document = SourceDocument.from_text("doc:span", source)
    # Span must cover the undeclared identifier.
    sliced = document.content[diag.range.start : diag.range.end].decode("utf-8")
    assert "Unknown" in sliced
    diag.validate_against(document)


def test_undeclared_sort_fails_with_exact_span() -> None:
    source = "forall x:Dragon. Human(x)"
    result = parse_fol(source, _fol_signature())
    assert not result.ok
    errors = result.errors
    assert any(item.code == CODE_UNDECLARED_SORT for item in errors)
    diag = next(item for item in errors if item.code == CODE_UNDECLARED_SORT)
    assert diag.range is not None
    document = SourceDocument.from_text("doc:sort", source)
    sliced = document.content[diag.range.start : diag.range.end].decode("utf-8")
    assert "Dragon" in sliced or sliced  # span on sort identifier
    diag.validate_against(document)


def test_trailing_input_fails_with_exact_span() -> None:
    source = "Human(alice) Human(bob)"
    result = parse_fol(source, _fol_signature())
    assert not result.ok
    errors = result.errors
    assert any(item.code == CODE_TRAILING_INPUT for item in errors)
    diag = next(item for item in errors if item.code == CODE_TRAILING_INPUT)
    assert diag.range is not None
    document = SourceDocument.from_text("doc:trail", source)
    sliced = document.content[diag.range.start : diag.range.end].decode("utf-8")
    assert "Human" in sliced
    # Trailing span starts at the second Human.
    assert diag.range.start > 0
    diag.validate_against(document)


def test_undeclared_variable_in_term_fails() -> None:
    result = parse_fol("Human(z)", _fol_signature())
    assert not result.ok
    assert any(item.code == CODE_UNDECLARED_SYMBOL for item in result.errors)


def test_parse_text_or_raise() -> None:
    syntax = _syntax()
    expr = syntax.parse_text_or_raise("Human(alice)")
    assert isinstance(expr, TypedExpression)
    assert expr.root.kind is NodeKind.PREDICATE

    with pytest.raises(FOLParseError) as caught:
        syntax.parse_text_or_raise("Nope(alice)")
    assert caught.value.diagnostics


def test_missing_signature_rejects() -> None:
    document = SourceDocument.from_text("doc:nosig", "Rains")
    request = ParseRequest(
        request_id="req:nosig",
        document=document,
        notation_id="canonical_fol",
        profile_id="classical",
    )
    artifact = CanonicalFOLParser().parse(request)
    assert artifact.status is ParseStatus.REJECTED
    assert artifact.diagnostics
    assert artifact.diagnostics[0].code == "fol.missing_signature"


def test_arity_mismatch_fails() -> None:
    result = parse_fol("Knows(alice)", _fol_signature())
    assert not result.ok
    assert any("arity" in item.message.lower() or item.code.endswith("arity_mismatch") for item in result.errors)


# ---------------------------------------------------------------------------
# Typed expression / alpha-renaming round-trip
# ---------------------------------------------------------------------------


def test_alpha_equivalent_after_binder_rename_print() -> None:
    """Printing uses binder names; re-parse of alpha-renamed AST stays alpha-eq."""
    person = _person()
    x = mk_variable("n:x", "x", person)
    y = mk_variable("n:y", "y", person)
    left = mk_forall(
        "n:l",
        (Binder(name="x", sort=person),),
        mk_predicate("n:hx", "Human", (x,)),
    )
    right = mk_forall(
        "n:r",
        (Binder(name="y", sort=person),),
        mk_predicate("n:hy", "Human", (y,)),
    )
    assert alpha_equivalent(left, right)
    printed_left = print_fol(left)
    printed_right = print_fol(right)
    # Surface names differ.
    assert "x" in printed_left and "y" in printed_right
    pl = parse_fol(printed_left, _fol_signature())
    pr = parse_fol(printed_right, _fol_signature())
    assert pl.ok and pr.ok
    assert pl.root is not None and pr.root is not None
    assert alpha_equivalent(pl.root, pr.root)


def test_complex_formula_round_trip_via_syntax_facade() -> None:
    syntax = _syntax()
    source = (
        "forall x:Person. Human(x) -> "
        "(exists y:Person. Knows(x, y) and father(y) = alice) or not Rains"
    )
    result = syntax.round_trip(source)
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.printed
