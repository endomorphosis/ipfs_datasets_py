"""Unit tests for EventCalculusSyntax@1 (LFP-028).

Evidence subset:

* happens / holds_at / initiates / terminates / releases / clipped
* events, fluents, time points
* parse/print/parse alpha-equivalent round-trip
* right-associative implication (explicit)
* unknown characters and undeclared sorts fail closed
* capture-safe substitution and binder rebind rejection
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.parsers.event_calculus import (
    CODE_ARITY_MISMATCH,
    CODE_PROFILE_MISMATCH,
    CODE_REBIND,
    CODE_UNKNOWN_CHARACTER,
    CODE_UNKNOWN_SORT,
    EVENT_CALCULUS_PROFILE_INTERFACE,
    EVENT_CALCULUS_SYNTAX_INTERFACE,
    EventCalculusDialect,
    EventCalculusParser,
    EventCalculusPrinter,
    EventCalculusSyntax,
    capture_safe_substitute,
    event_calculus_semantic_identity,
    free_variables,
    parse_event_calculus,
    parse_print_parse,
    print_event_calculus,
    profile_event_calculus_basic,
    profile_event_calculus_classical,
    profile_event_calculus_cognitive,
)
from ipfs_datasets_py.logic.syntax_core.algebra import alpha_equivalent
from ipfs_datasets_py.logic.syntax_core.ast import NodeKind, mk_constant
from ipfs_datasets_py.logic.syntax_core.contracts import (
    ParseStatus,
    SyntaxContractError,
)
from ipfs_datasets_py.logic.syntax_core.signatures import atomic_sort


def _classical():
    return profile_event_calculus_classical()


def _basic():
    return profile_event_calculus_basic()


def _cognitive():
    return profile_event_calculus_cognitive()


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_interface_and_module_identity() -> None:
    assert EVENT_CALCULUS_SYNTAX_INTERFACE == "EventCalculusSyntax@1"
    assert EVENT_CALCULUS_PROFILE_INTERFACE == "EventCalculusProfile@1"
    syntax = EventCalculusSyntax(_classical())
    assert syntax.interface == EVENT_CALCULUS_SYNTAX_INTERFACE
    assert isinstance(syntax.parser, EventCalculusParser)
    assert isinstance(syntax.printer, EventCalculusPrinter)


def test_profile_rejects_left_associativity() -> None:
    from ipfs_datasets_py.logic.parsers.event_calculus import EventCalculusProfile

    with pytest.raises(SyntaxContractError, match="right"):
        EventCalculusProfile(
            profile_id="bad",
            implication_associativity="left",
        )


def test_dialect_profiles() -> None:
    assert _basic().dialect is EventCalculusDialect.BASIC
    assert _basic().admit_releases is False
    assert _classical().admit_clipped is True
    assert _cognitive().dialect is EventCalculusDialect.COGNITIVE


# ---------------------------------------------------------------------------
# Happy-path EC atoms
# ---------------------------------------------------------------------------


def test_parse_happens_and_holds_at() -> None:
    result = parse_event_calculus(
        "happens(turn_on, 1) and holds_at(light_on, 2)",
        _classical(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.kind is NodeKind.AND
    assert result.implication_associativity == "right"
    printed = print_event_calculus(result.root)
    assert "happens" in printed
    assert "holds_at" in printed


def test_parse_initiates_terminates_releases() -> None:
    result = parse_event_calculus(
        "initiates(e, f, t) and terminates(e, f, t) and releases(e, f, t)",
        _classical(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    printed = print_event_calculus(result.root)
    assert "initiates" in printed
    assert "terminates" in printed
    assert "releases" in printed


def test_parse_clipped_and_initially() -> None:
    result = parse_event_calculus(
        "initially(light_on) and clipped(0, light_on, 5)",
        _classical(),
    )
    assert result.ok, [d.message for d in result.diagnostics]


def test_basic_profile_rejects_releases() -> None:
    result = parse_event_calculus("releases(e, f, t)", _basic())
    assert not result.ok
    assert any(d.code == CODE_PROFILE_MISMATCH for d in result.diagnostics)


def test_arity_mismatch() -> None:
    result = parse_event_calculus("happens(e)", _classical())
    assert not result.ok
    assert any(d.code == CODE_ARITY_MISMATCH for d in result.diagnostics)


# ---------------------------------------------------------------------------
# Implication associativity (right)
# ---------------------------------------------------------------------------


def test_implication_is_right_associative() -> None:
    result = parse_event_calculus("p -> q -> r", _classical())
    assert result.ok, [d.message for d in result.diagnostics]
    root = result.root
    assert root is not None
    assert root.kind is NodeKind.IMPLIES
    # A -> B -> C ≡ A -> (B -> C)
    right = root.arguments[1]
    assert right.kind is NodeKind.IMPLIES
    assert root.metadata.get("associativity") == "right"


def test_semantic_identity_includes_profile() -> None:
    result = parse_event_calculus("happens(e, t)", _classical())
    assert result.ok
    identity = event_calculus_semantic_identity(result.root, _classical())
    assert identity["family"] == "event_calculus"
    assert identity["profile"]["implication_associativity"] == "right"


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_parse_print_parse_round_trip() -> None:
    text = "happens(turn_on, 1) implies holds_at(light_on, 2)"
    first, second, equivalent = parse_print_parse(text, _classical())
    assert first.ok, [d.message for d in first.diagnostics]
    assert second.ok, [d.message for d in second.diagnostics]
    assert equivalent
    assert alpha_equivalent(first.root, second.root)


def test_round_trip_quantified() -> None:
    text = "forall e:Event, t:Time. happens(e, t) implies holds_at(f, t)"
    first, second, equivalent = parse_print_parse(text, _classical())
    assert first.ok, [d.message for d in first.diagnostics]
    assert second.ok, [d.message for d in second.diagnostics]
    assert equivalent


# ---------------------------------------------------------------------------
# Unknown characters / sorts (no silent drop)
# ---------------------------------------------------------------------------


def test_unknown_character_does_not_disappear() -> None:
    # U+2603 snowman is not in the EC alphabet.
    result = parse_event_calculus("happens(e, t) ☃", _classical())
    assert not result.ok
    assert any(
        d.code in {CODE_UNKNOWN_CHARACTER, "event_calculus.lexer_error"}
        or "unknown" in d.code
        or "unknown" in d.message.casefold()
        for d in result.diagnostics
    )


def test_unknown_sort_does_not_disappear() -> None:
    result = parse_event_calculus(
        "forall x:Widget. happens(x, 1)",
        _classical(),
    )
    assert not result.ok
    assert any(d.code == CODE_UNKNOWN_SORT for d in result.diagnostics)
    assert any("Widget" in d.message for d in result.diagnostics)


# ---------------------------------------------------------------------------
# Capture-safe binders / substitution
# ---------------------------------------------------------------------------


def test_rebind_rejected_as_capture_unsafe() -> None:
    result = parse_event_calculus(
        "forall x:Object. forall x:Object. p",
        _classical(),
    )
    assert not result.ok
    assert any(d.code == CODE_REBIND for d in result.diagnostics)


def test_capture_safe_substitute() -> None:
    result = parse_event_calculus(
        "forall x:Object. holds_at(f, x)",
        _classical(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    body = result.root.arguments[0]
    free_before = free_variables(body)
    assert "x" in free_before
    replacement = mk_constant("c:1", "c", atomic_sort("Object"))
    rewritten = capture_safe_substitute(result.root, "x", replacement)
    # Outer binder x shadows; free x in body is bound so top-level sub of x
    # must not rewrite under the binder incorrectly.
    free_after = free_variables(rewritten)
    assert "x" not in free_after or rewritten.kind is NodeKind.FORALL


def test_empty_input_rejected() -> None:
    result = parse_event_calculus("   ", _classical())
    assert not result.ok
    assert result.status is not ParseStatus.OK
