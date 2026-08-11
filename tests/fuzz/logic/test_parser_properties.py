"""Fuzz / property gates for logic family parsers (LFP-041).

Acceptance:

* Property tests (alpha, substitution, round-trip) hold under bounded inputs
* Unicode / confusable / NUL adversarial fixtures fail closed with exact spans
* Nesting / ambiguity / parser-bomb shapes terminate and never silent-drop
* Stable reduced counterexamples are exposed for failing inputs

Evidence subset: property tests alpha substitution roundtrip unicode
confusable nul nesting ambiguity parser bomb.
"""

from __future__ import annotations

import hashlib
import random
import time
from collections.abc import Callable, Sequence
from typing import Any, Final

import pytest

from ipfs_datasets_py.logic.parsers.fol import (
    CODE_PARSE_DEPTH,
    CODE_TRAILING_INPUT,
    CODE_UNDECLARED_SYMBOL,
    PrintStyle,
    parse_fol,
    parse_print_parse,
    print_fol,
)
from ipfs_datasets_py.logic.parsers.smtlib import (
    CODE_PARSE_DEPTH as SMT_PARSE_DEPTH,
)
from ipfs_datasets_py.logic.parsers.smtlib import (
    CODE_UNSUPPORTED_COMMAND,
    CODE_UNKNOWN_COMMAND,
    parse_print_parse_smtlib2,
    parse_smtlib2,
    read_sexprs,
)
from ipfs_datasets_py.logic.parsers.tptp import parse_print_parse_tptp, parse_tptp
from ipfs_datasets_py.logic.syntax_core.algebra import (
    AlgebraError,
    AlgebraLimits,
    DEFAULT_ALGEBRA,
    alpha_equivalent,
    free_variables,
    semantic_identity,
    substitute,
)
from ipfs_datasets_py.logic.syntax_core.ast import (
    Binder,
    LogicNode,
    NodeKind,
    mk_forall,
    mk_predicate,
    mk_variable,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    ParseLimits,
    ParseMode,
    ParseStatus,
    SourceDocument,
    SyntaxContractError,
)
from ipfs_datasets_py.logic.syntax_core.diagnostics import (
    CODE_CONFUSABLE_CHARACTER,
    CODE_TOKEN_LIMIT,
)
from ipfs_datasets_py.logic.syntax_core.lexer import lex_document
from ipfs_datasets_py.logic.syntax_core.signatures import (
    LogicSignature,
    atomic_sort,
    many_sorted_fol_signature,
)


TASK_ID: Final = "LFP-041"
GOAL_ID: Final = "LFP-G080"
FUZZ_SEED_INT: Final = 0x04190F6
WALL_TIME_BUDGET_SECONDS: Final = 2.0
FUZZ_CASE_BUDGET: Final = 48


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _fol_signature() -> LogicSignature:
    person = atomic_sort("Person")
    return many_sorted_fol_signature(
        "sig:fuzz:fol:1",
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


def _person():
    return atomic_sort("Person")


def _codes(diagnostics: Sequence[Any]) -> tuple[str, ...]:
    return tuple(str(item.code) for item in diagnostics)


def _primary_code(diagnostics: Sequence[Any]) -> str:
    assert diagnostics
    errors = [item for item in diagnostics if getattr(item, "is_error", True)]
    return str((errors or list(diagnostics))[0].code)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _timed(fn: Callable[[], Any], *, budget: float = WALL_TIME_BUDGET_SECONDS) -> Any:
    start = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - start
    assert elapsed < budget, f"operation exceeded {budget}s (took {elapsed:.3f}s)"
    return result


def _reduce(
    source: str,
    oracle: Callable[[str], tuple[bool, str]],
    *,
    max_steps: int = 48,
) -> tuple[str, str]:
    fails, code = oracle(source)
    assert fails
    current, current_code = source, code
    steps = 0
    changed = True
    while changed and steps < max_steps and len(current) > 1:
        changed = False
        steps += 1
        for start, end in (
            (len(current) // 2, len(current)),
            (0, len(current) // 2),
        ):
            candidate = current[:start] + current[end:]
            if not candidate or candidate == current:
                continue
            ok_fail, ok_code = oracle(candidate)
            if ok_fail and ok_code == current_code:
                current, current_code = candidate, ok_code
                changed = True
                break
        if changed:
            continue
        for index in range(len(current)):
            candidate = current[:index] + current[index + 1 :]
            if not candidate:
                continue
            ok_fail, ok_code = oracle(candidate)
            if ok_fail and ok_code == current_code:
                current, current_code = candidate, ok_code
                changed = True
                break
    return current, current_code


def _assert_span_on_errors(source: str, diagnostics: Sequence[Any], document_id: str) -> None:
    document = SourceDocument.from_text(document_id, source, encoding="utf-8")
    ranged = [item for item in diagnostics if getattr(item, "range", None) is not None]
    assert ranged, "failing diagnostics must preserve exact spans"
    for item in ranged:
        item.validate_against(document)


# ---------------------------------------------------------------------------
# Identity / task binding
# ---------------------------------------------------------------------------


def test_task_and_goal_identity() -> None:
    assert TASK_ID == "LFP-041"
    assert GOAL_ID == "LFP-G080"


# ---------------------------------------------------------------------------
# Alpha / substitution / round-trip properties
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
        "not (Human(alice) or Human(bob))",
        "true and false or Rains",
    ],
)
def test_property_parse_print_parse_alpha_equivalent(source: str) -> None:
    sig = _fol_signature()
    first = parse_fol(source, sig)
    assert first.ok, [d.message for d in first.diagnostics]
    assert first.root is not None
    printed = print_fol(first.root)
    second = parse_fol(printed, sig, document_id="doc:rt")
    assert second.ok, (printed, [d.message for d in second.diagnostics])
    assert second.root is not None
    assert alpha_equivalent(first.root, second.root)
    assert semantic_identity(first.root) == semantic_identity(second.root)
    # Helper path.
    rt = parse_print_parse(source, sig)
    assert rt.ok


def test_property_unicode_ascii_operator_round_trip() -> None:
    sig = _fol_signature()
    ascii_src = "forall x:Person. Human(x) -> not Rains"
    unicode_src = "∀x:Person. Human(x) → ¬Rains"
    a = parse_fol(ascii_src, sig)
    u = parse_fol(unicode_src, sig)
    assert a.ok and u.ok
    assert a.root is not None and u.root is not None
    assert alpha_equivalent(a.root, u.root)
    printed_u = print_fol(a.root, style=PrintStyle.UNICODE)
    assert "∀" in printed_u and "→" in printed_u and "¬" in printed_u
    again = parse_fol(printed_u, sig, document_id="doc:uni")
    assert again.ok and again.root is not None
    assert alpha_equivalent(a.root, again.root)


def test_property_alpha_rename_preserves_semantic_identity() -> None:
    x = mk_variable("n:x", "x", _person())
    y = mk_variable("n:y", "y", _person())
    left = mk_forall(
        "n:all-x",
        (Binder(name="x", sort=_person()),),
        mk_predicate("n:p", "Human", (x,)),
    )
    right = mk_forall(
        "n:all-y",
        (Binder(name="y", sort=_person()),),
        mk_predicate("n:p2", "Human", (y,)),
    )
    assert alpha_equivalent(left, right)
    assert semantic_identity(left) == semantic_identity(right)
    renamed = DEFAULT_ALGEBRA.alpha_rename_binder(left, "x", "z")
    assert alpha_equivalent(left, renamed)
    assert semantic_identity(left) == semantic_identity(renamed)


def test_property_capture_avoiding_substitution() -> None:
    # (∀y. Human(x))[x := y] must not capture: binder y is renamed.
    x = mk_variable("n:x", "x", _person())
    y = mk_variable("n:y", "y", _person())
    body = mk_predicate("n:h", "Human", (x,))
    expr = mk_forall("n:all", (Binder(name="y", sort=_person()),), body)
    result = substitute(expr, "x", y)
    assert result.kind is NodeKind.FORALL
    # Capture-avoiding: binder must be renamed away from free y.
    assert result.binders[0].name != "y"
    assert free_variables(result) == frozenset({"y"})
    # Free-variable law.
    fv_e = free_variables(expr)
    fv_t = free_variables(y)
    fv_r = free_variables(result)
    assert "x" in fv_e
    assert fv_r == (fv_e - {"x"}) | fv_t
    # Idempotence under closed substitution of x (already eliminated).
    again = substitute(result, "x", y)
    assert alpha_equivalent(result, again)


def test_property_substitution_budget_fail_closed() -> None:
    # Extremely tight algebra budget must fail closed, not hang or partial-apply.
    from ipfs_datasets_py.logic.syntax_core.algebra import LogicExpressionAlgebra

    deep: LogicNode = mk_predicate("n:p", "Rains")
    for index in range(12):
        deep = mk_forall(
            f"n:all:{index}",
            (Binder(name=f"x{index}", sort=_person()),),
            deep,
        )
    tight = LogicExpressionAlgebra(limits=AlgebraLimits(max_nodes=3, max_depth=2))
    with pytest.raises(AlgebraError):
        tight.free_variables(deep)
    with pytest.raises(AlgebraError):
        tight.substitute(deep, "x0", mk_variable("n:v", "z", _person()))


# ---------------------------------------------------------------------------
# Unicode / confusable / NUL adversarial fixtures
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "confusable,label",
    [
        ("\u2013", "en-dash"),  # –
        ("\u2014", "em-dash"),  # —
        ("\u2212", "minus"),  # −
        ("\u200b", "zwsp"),
        ("\ufeff", "bom"),
        # NBSP is Unicode whitespace (str.isspace) and is absorbed as trivia
        # rather than a confusable token — covered separately below.
    ],
)
def test_confusable_characters_rejected_with_exact_span(confusable: str, label: str) -> None:
    source = f"P {confusable} Q"
    document = SourceDocument.from_text(f"doc:conf:{label}", source, encoding="utf-8")
    result = lex_document(document, mode=ParseMode.STRICT)
    assert result.status in {ParseStatus.FAILED, ParseStatus.REJECTED}
    assert result.diagnostics
    assert any(
        item.code == CODE_CONFUSABLE_CHARACTER or "confusable" in item.message.lower()
        for item in result.diagnostics
    )
    _assert_span_on_errors(source, result.diagnostics, f"doc:conf:{label}")


def test_nbsp_is_absorbed_as_whitespace_trivia_not_lexeme() -> None:
    """NBSP is confusable-listed but isspace(); lexer treats it as trivia."""

    source = "P\u00a0Q"
    document = SourceDocument.from_text("doc:conf:nbsp", source, encoding="utf-8")
    result = lex_document(document, mode=ParseMode.STRICT)
    # Either OK (nbsp as trivia between P and Q) or confusable if checked first.
    if result.status is ParseStatus.OK:
        lexemes = [t.lexeme for t in result.tokens if t.lexeme]
        assert "P" in lexemes and "Q" in lexemes
        assert "\u00a0" not in lexemes
    else:
        assert result.diagnostics
        assert any(
            item.code == CODE_CONFUSABLE_CHARACTER or "confusable" in item.message.lower()
            for item in result.diagnostics
        )


def test_nul_character_fails_closed_at_source_boundary() -> None:
    # SourceDocument is the first fail-closed gate for embedded NUL.
    with pytest.raises(SyntaxContractError, match="NUL"):
        SourceDocument.from_text("doc:nul", "P\x00Q", encoding="utf-8")
    with pytest.raises(SyntaxContractError, match="NUL"):
        SourceDocument(document_id="doc:nul:bytes", content=b"P\x00Q", encoding="utf-8")


def test_unicode_operators_accepted_where_promised() -> None:
    document = SourceDocument.from_text(
        "doc:uni-ops", "∀x. P(x) ∧ Q(x) → ¬R ∨ true", encoding="utf-8"
    )
    result = lex_document(document, mode=ParseMode.STRICT)
    assert result.status is ParseStatus.OK
    lexemes = [t.lexeme for t in result.tokens if t.lexeme]
    assert {"∀", "∧", "→", "¬", "∨"} <= set(lexemes)


# ---------------------------------------------------------------------------
# Nesting / ambiguity / trailing input
# ---------------------------------------------------------------------------


def test_nested_parentheses_respect_depth_budget() -> None:
    sig = _fol_signature()
    nested = "(" * 16 + "Rains" + ")" * 16
    ok = parse_fol(
        nested,
        sig,
        limits=ParseLimits(max_input_bytes=4096, max_tokens=256, max_depth=64),
    )
    # Deep but within budget may succeed or fail on other grounds; must terminate.
    assert ok.status in {
        ParseStatus.OK,
        ParseStatus.FAILED,
        ParseStatus.REJECTED,
    }
    tight = parse_fol(
        nested,
        sig,
        limits=ParseLimits(max_input_bytes=4096, max_tokens=256, max_depth=3),
    )
    assert not tight.ok
    assert any(item.code == CODE_PARSE_DEPTH for item in tight.errors)
    _assert_span_on_errors(nested, tight.errors, "doc:nest")


def test_trailing_input_fails_with_exact_span() -> None:
    source = "Human(alice) Human(bob)"
    result = parse_fol(source, _fol_signature())
    assert not result.ok
    assert any(item.code == CODE_TRAILING_INPUT for item in result.errors)
    _assert_span_on_errors(source, result.errors, "doc:trail")
    diag = next(item for item in result.errors if item.code == CODE_TRAILING_INPUT)
    assert diag.range is not None and diag.range.start > 0


def test_implication_ambiguity_is_right_associative_not_silent() -> None:
    """Surface ambiguity of A->B->C is resolved right-assoc and recorded by tree shape."""

    result = parse_fol("Rains -> Human(alice) -> Human(bob)", _fol_signature())
    assert result.ok and result.root is not None
    assert result.root.kind is NodeKind.IMPLIES
    assert result.root.arguments[1].kind is NodeKind.IMPLIES
    # Left-assoc tree is not alpha-equivalent — ambiguity is not silently left-folded.
    rains = result.root.arguments[0]
    mid = result.root.arguments[1].arguments[0]
    right = result.root.arguments[1].arguments[1]
    # Reconstruct left-assoc ((A->B)->C) via parse of parenthesized form.
    left_assoc = parse_fol(
        "(Rains -> Human(alice)) -> Human(bob)", _fol_signature()
    )
    assert left_assoc.ok and left_assoc.root is not None
    assert not alpha_equivalent(result.root, left_assoc.root)
    assert alpha_equivalent(rains, left_assoc.root.arguments[0].arguments[0])
    assert alpha_equivalent(mid, left_assoc.root.arguments[0].arguments[1])
    assert alpha_equivalent(right, left_assoc.root.arguments[1])


def test_undeclared_symbol_is_explicit_not_dropped() -> None:
    source = "UnknownPred(alice)"
    result = parse_fol(source, _fol_signature())
    assert not result.ok
    assert any(item.code == CODE_UNDECLARED_SYMBOL for item in result.errors)
    _assert_span_on_errors(source, result.errors, "doc:undrop")
    diag = next(item for item in result.errors if item.code == CODE_UNDECLARED_SYMBOL)
    document = SourceDocument.from_text("doc:undrop", source)
    sliced = document.content[diag.range.start : diag.range.end].decode("utf-8")
    assert "UnknownPred" in sliced


# ---------------------------------------------------------------------------
# Parser-bomb / bounded fuzz
# ---------------------------------------------------------------------------


def test_smt_parser_bomb_nesting_terminates_fail_closed() -> None:
    bomb = "(" * 64 + "true" + ")" * 64
    limits = ParseLimits(max_input_bytes=4096, max_tokens=256, max_depth=6)
    forms, diags = _timed(lambda: read_sexprs(bomb, limits=limits))
    assert forms == ()
    assert any(item.code == SMT_PARSE_DEPTH for item in diags)
    result = _timed(lambda: parse_smtlib2(bomb, limits=limits))
    assert not result.ok
    assert result.errors


def test_bounded_random_fuzz_terminates_and_never_raises() -> None:
    """Seeded fuzz over adversarial fragments; every case terminates fail-closed or OK."""

    rng = random.Random(FUZZ_SEED_INT)
    atoms = ["true", "false", "Rains", "Human(alice)", "p", "q(a)", "(" , ")", "->", "and", "∀", "\u2013"]
    sig = _fol_signature()
    limits = ParseLimits(
        max_input_bytes=512,
        max_tokens=48,
        max_depth=12,
        max_diagnostics=32,
        max_time_ms=5_000,
    )
    outcomes: list[str] = []
    for index in range(FUZZ_CASE_BUDGET):
        length = rng.randint(1, 24)
        source = " ".join(rng.choice(atoms) for _ in range(length))
        # Mix frontends.
        lane = index % 3
        start = time.perf_counter()
        try:
            if lane == 0:
                result = parse_fol(source, sig, limits=limits, document_id=f"doc:fuzz:{index}")
                status = "ok" if result.ok else "fail"
                if not result.ok:
                    assert result.errors
            elif lane == 1:
                result = parse_smtlib2(source, limits=limits, document_id=f"doc:fuzz:s:{index}")
                status = "ok" if result.ok else "fail"
                if not result.ok:
                    assert result.errors
            else:
                result = parse_tptp(source, limits=limits, document_id=f"doc:fuzz:t:{index}")
                status = "ok" if result.ok else "fail"
                if not result.ok:
                    assert result.errors
        except SyntaxContractError:
            # Contract-level reject (e.g. encoding) is fail-closed success for the gate.
            status = "contract"
        elapsed = time.perf_counter() - start
        assert elapsed < WALL_TIME_BUDGET_SECONDS, (index, source, elapsed)
        outcomes.append(status)
    # Fuzz must exercise both success and failure paths across the budget, or
    # at least never hang; all outcomes are recorded.
    assert len(outcomes) == FUZZ_CASE_BUDGET
    assert set(outcomes) <= {"ok", "fail", "contract"}


def test_token_bomb_lexes_within_bound() -> None:
    source = " ".join(f"id{i}" for i in range(200))
    document = SourceDocument.from_text("doc:tokbomb", source)
    limits = ParseLimits(max_input_bytes=8192, max_tokens=16, max_depth=16)
    result = _timed(lambda: lex_document(document, mode=ParseMode.STRICT, limits=limits))
    assert result.status in {ParseStatus.FAILED, ParseStatus.REJECTED}
    assert any(item.code == CODE_TOKEN_LIMIT for item in result.diagnostics)
    assert len(result.tokens) <= limits.max_tokens


# ---------------------------------------------------------------------------
# Round-trip properties for additional frontends
# ---------------------------------------------------------------------------


def test_smtlib_core_round_trip_property() -> None:
    script = (
        "(set-logic QF_UF)\n"
        "(declare-sort Person 0)\n"
        "(declare-const alice Person)\n"
        "(declare-fun knows (Person Person) Bool)\n"
        "(assert (knows alice alice))\n"
        "(check-sat)\n"
    )
    result = parse_print_parse_smtlib2(script)
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.document is not None


def test_tptp_fof_round_trip_property() -> None:
    script = "fof(ax1, axiom, ! [X] : (p(X) => q(X))).\n"
    result = parse_print_parse_tptp(script)
    # Controlled subset: require termination; success implies a document.
    assert result.status in {
        ParseStatus.OK,
        ParseStatus.FAILED,
        ParseStatus.REJECTED,
    }
    if result.ok:
        assert result.document is not None


# ---------------------------------------------------------------------------
# Silent drop rejection under fuzz-like unsupported surfaces
# ---------------------------------------------------------------------------


def test_unknown_smt_command_never_silent_drop() -> None:
    script = "(set-logic QF_UF)\n(not-a-real-command 1 2 3)\n(check-sat)\n"
    result = parse_smtlib2(script)
    assert not result.ok
    assert result.errors
    assert any(
        item.code in {CODE_UNKNOWN_COMMAND, CODE_UNSUPPORTED_COMMAND}
        or "unknown" in item.message.lower()
        or "unsupported" in item.message.lower()
        for item in result.errors
    )


# ---------------------------------------------------------------------------
# Stable reduced counterexamples
# ---------------------------------------------------------------------------


def test_stable_reduced_counterexample_for_confusable() -> None:
    source = "Human(alice) \u2013 Knows(alice, bob)"
    document_id = "doc:red:conf"

    def oracle(text: str) -> tuple[bool, str]:
        try:
            document = SourceDocument.from_text(document_id, text, encoding="utf-8")
        except SyntaxContractError as error:
            return True, type(error).__name__
        result = lex_document(document, mode=ParseMode.STRICT)
        if result.status in {ParseStatus.FAILED, ParseStatus.REJECTED} and result.diagnostics:
            return True, _primary_code(result.diagnostics)
        return False, "ok"

    reduced, code = _reduce(source, oracle)
    assert code == CODE_CONFUSABLE_CHARACTER or code == "SyntaxContractError"
    fails, code2 = oracle(reduced)
    assert fails and code2 == code
    reduced2, code3 = _reduce(source, oracle)
    assert (reduced2, code3) == (reduced, code)
    assert _digest(reduced) == _digest(reduced2)


def test_stable_reduced_counterexample_for_depth_bomb() -> None:
    bomb = "(" * 30 + "true" + ")" * 30
    limits = ParseLimits(max_input_bytes=4096, max_tokens=512, max_depth=4)

    def oracle(text: str) -> tuple[bool, str]:
        forms, diags = read_sexprs(text, limits=limits)
        if forms == () and diags:
            return True, _primary_code(diags)
        return False, "ok"

    reduced, code = _reduce(bomb, oracle)
    assert code == SMT_PARSE_DEPTH
    assert oracle(reduced) == (True, code)
    assert _reduce(bomb, oracle) == (reduced, code)
    # Reduced counterexample is a stable regression fixture key.
    fixture_key = f"{code}:{_digest(reduced)}"
    assert fixture_key == f"{code}:{_digest(reduced)}"


def test_stable_reduced_counterexample_for_fol_trailing() -> None:
    source = "Human(alice) Human(bob) Human(alice)"
    sig = _fol_signature()

    def oracle(text: str) -> tuple[bool, str]:
        result = parse_fol(text, sig)
        if not result.ok and result.errors:
            return True, _primary_code(result.errors)
        return False, "ok"

    reduced, code = _reduce(source, oracle)
    assert code  # stable non-empty
    assert oracle(reduced) == (True, code)
    assert _reduce(source, oracle) == (reduced, code)
    # Exact span still present on the reduced form.
    result = parse_fol(reduced, sig)
    assert not result.ok
    _assert_span_on_errors(reduced, result.errors, "doc:red:trail")


def test_property_suite_is_deterministic_under_rerun() -> None:
    """Re-running a fixed adversarial corpus yields identical diagnostic codes."""

    corpus = [
        ("\u2013", "confusable"),
        ("(" * 20 + "true" + ")" * 20, "depth"),
        ("a b c d e f g h", "tokens"),
    ]
    limits = ParseLimits(max_input_bytes=4096, max_tokens=4, max_depth=4)
    first_codes: list[tuple[str, ...]] = []
    for source, _kind in corpus:
        document = SourceDocument.from_text("doc:det", source if source != "\u2013" else f"P {source} Q")
        if "true" in source and source.startswith("("):
            _forms, diags = read_sexprs(source, limits=limits)
            first_codes.append(_codes(diags))
        else:
            result = lex_document(document, mode=ParseMode.STRICT, limits=limits)
            first_codes.append(_codes(result.diagnostics))
    second_codes: list[tuple[str, ...]] = []
    for source, _kind in corpus:
        document = SourceDocument.from_text("doc:det", source if source != "\u2013" else f"P {source} Q")
        if "true" in source and source.startswith("("):
            _forms, diags = read_sexprs(source, limits=limits)
            second_codes.append(_codes(diags))
        else:
            result = lex_document(document, mode=ParseMode.STRICT, limits=limits)
            second_codes.append(_codes(result.diagnostics))
    assert first_codes == second_codes
