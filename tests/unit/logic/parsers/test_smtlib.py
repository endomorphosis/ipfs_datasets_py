"""Unit tests for SMTLIB2Frontend@1 (LFP-018).

Evidence subset:

* bounded S-expression reading
* declarations (sort / fun / const / datatypes)
* lets and quantifiers
* bit-vectors, arrays, arithmetic, strings
* model and unsat-core request commands
* explicit unknown / unsupported commands and theories
* Z3/cvc5 common-fragment round trips preserve symbol/sort semantics
* SMT bridge reuses the typed semantic compiler
"""

from __future__ import annotations

import shutil

import pytest

from ipfs_datasets_py.logic.backends.smt.compiler import (
    SmtFeature,
    SmtQueryMode,
    SmtTermKind,
    SmtTheory,
)
from ipfs_datasets_py.logic.parsers.smtlib import (
    CODE_EMPTY_INPUT,
    CODE_INPUT_LIMIT,
    CODE_PARSE_DEPTH,
    CODE_TOKEN_LIMIT,
    CODE_UNBALANCED,
    CODE_UNDECLARED_SORT,
    CODE_UNDECLARED_SYMBOL,
    CODE_UNKNOWN_COMMAND,
    CODE_UNKNOWN_THEORY,
    CODE_UNSUPPORTED_COMMAND,
    CODE_UNSUPPORTED_THEORY,
    SMTLIB2_FRONTEND_INTERFACE,
    SMTLIB2_NOTATION_ID,
    SMTLIB2_PROFILE_ID,
    SMTLIB2Frontend,
    SMTLIB2Parser,
    SMTLIB2Printer,
    SMTBridge,
    SUPPORTED_COMMANDS,
    UNSUPPORTED_COMMANDS,
    bridge_smtlib2_to_obligation,
    documents_semantically_compatible,
    elaborate_smtlib2,
    parse_print_parse_smtlib2,
    parse_smtlib2,
    print_smtlib2,
    read_sexprs,
)
from ipfs_datasets_py.logic.syntax_core.contracts import ParseLimits, ParseStatus


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _frontend() -> SMTLIB2Frontend:
    return SMTLIB2Frontend()


CORE_SCRIPT = """\
; core equality fragment
(set-logic QF_UF)
(declare-sort Person 0)
(declare-const alice Person)
(declare-fun knows (Person Person) Bool)
(assert (knows alice alice))
(check-sat)
"""

ARITH_SCRIPT = """\
(set-logic QF_LIA)
(declare-const x Int)
(declare-const y Int)
(assert (! (>= x 1) :named assume_ge_one))
(assert (> (+ x y) 0))
(check-sat)
(get-unsat-core)
"""

ARRAY_SCRIPT = """\
(set-logic QF_AUFLIA)
(declare-const a (Array Int Int))
(declare-const i Int)
(declare-const v Int)
(assert (= (select (store a i v) i) v))
(check-sat)
(get-model)
"""

BV_SCRIPT = """\
(set-logic QF_BV)
(declare-const x (_ BitVec 8))
(declare-const y (_ BitVec 8))
(assert (= (bvand x y) x))
(check-sat)
"""

QUANT_SCRIPT = """\
(set-logic UFLIA)
(declare-sort U 0)
(declare-fun P (U) Bool)
(assert (forall ((x U)) (=> (P x) (P x))))
(check-sat)
"""

LET_SCRIPT = """\
(set-logic QF_LIA)
(declare-const a Int)
(assert (let ((x (+ a 1))) (> x a)))
(check-sat)
"""

STRING_SCRIPT = """\
(set-logic QF_S)
(declare-const s String)
(assert (= (str.len s) 0))
(check-sat)
"""

DATATYPE_SCRIPT = """\
(set-logic QF_UFDT)
(declare-datatypes () ((Nat (zero) (succ (pred Nat)))))
(declare-const n Nat)
(assert (= n (succ zero)))
(check-sat)
"""


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_interface_and_module_identity() -> None:
    assert SMTLIB2_FRONTEND_INTERFACE == "SMTLIB2Frontend@1"
    assert SMTLIB2_NOTATION_ID == "smtlib2"
    assert SMTLIB2_PROFILE_ID == "smt_core"
    frontend = _frontend()
    assert frontend.interface == SMTLIB2_FRONTEND_INTERFACE
    assert isinstance(frontend.parser, SMTLIB2Parser)
    assert isinstance(frontend.printer, SMTLIB2Printer)
    assert isinstance(frontend.bridge, SMTBridge)


# ---------------------------------------------------------------------------
# S-expression reader (bounded)
# ---------------------------------------------------------------------------


def test_read_sexprs_parses_nested_lists_and_comments() -> None:
    forms, diags = read_sexprs(
        "; comment\n(set-logic QF_UF)\n(assert (and true (not false)))\n"
    )
    assert not any(item.is_error for item in diags)
    assert len(forms) == 2
    assert forms[0].head_symbol() == "set-logic"
    assert forms[1].head_symbol() == "assert"


def test_read_sexprs_handles_strings_and_quoted_symbols() -> None:
    forms, diags = read_sexprs('(set-info :source "hello ""world""")\n(|weird name| true)')
    assert not any(item.is_error for item in diags)
    assert len(forms) == 2
    info = forms[0]
    assert info[2].kind == "string"
    assert info[2].value == 'hello "world"'
    assert forms[1][0].kind == "quoted"
    assert forms[1][0].value == "weird name"


def test_read_sexprs_handles_bv_literals() -> None:
    forms, diags = read_sexprs("(#b1010 #xFF)")
    assert not any(item.is_error for item in diags)
    assert forms[0][0].kind == "bv"
    assert forms[0][0].value == "#b1010"
    assert forms[0][1].value == "#xFF"


def test_reader_rejects_unbalanced_parens() -> None:
    forms, diags = read_sexprs("(assert (and true")
    assert forms == ()
    assert any(item.code == CODE_UNBALANCED for item in diags)


def test_reader_enforces_input_byte_limit() -> None:
    text = "(assert true)\n" * 50
    forms, diags = read_sexprs(text, limits=ParseLimits(max_input_bytes=32, max_tokens=64, max_depth=16))
    assert forms == ()
    assert any(item.code == CODE_INPUT_LIMIT for item in diags)


def test_reader_enforces_token_limit() -> None:
    text = "(assert " + " ".join(["true"] * 40) + ")"
    forms, diags = read_sexprs(
        text, limits=ParseLimits(max_input_bytes=4096, max_tokens=10, max_depth=64)
    )
    assert forms == ()
    assert any(item.code == CODE_TOKEN_LIMIT for item in diags)


def test_reader_enforces_depth_limit() -> None:
    text = "(" * 20 + "true" + ")" * 20
    forms, diags = read_sexprs(
        text, limits=ParseLimits(max_input_bytes=4096, max_tokens=256, max_depth=5)
    )
    assert forms == ()
    assert any(item.code == CODE_PARSE_DEPTH for item in diags)


def test_empty_input_fails() -> None:
    result = parse_smtlib2("   \n  ; only comments\n")
    assert not result.ok
    assert result.status in {ParseStatus.FAILED, ParseStatus.REJECTED}
    assert any(item.code == CODE_EMPTY_INPUT for item in result.errors)


# ---------------------------------------------------------------------------
# Happy-path elaboration
# ---------------------------------------------------------------------------


def test_parse_core_declarations_and_assert() -> None:
    result = parse_smtlib2(CORE_SCRIPT)
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    assert doc.logic == "QF_UF"
    assert "Person" in doc.sort_names
    assert "alice" in doc.symbol_names
    assert "knows" in doc.symbol_names
    assert len(doc.assertions) == 1
    assert doc.check_sat is True
    knows = next(item for item in doc.functions if item.name == "knows")
    assert len(knows.domain) == 2
    assert knows.range.name == "Bool"


def test_parse_arithmetic_named_assertion_and_unsat_core() -> None:
    result = parse_smtlib2(ARITH_SCRIPT)
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    assert doc.request_unsat_core is True
    assert doc.assertions[0].name == "assume_ge_one"
    assert doc.assertions[0].formula.kind is SmtTermKind.GE
    assert doc.assertions[1].formula.kind is SmtTermKind.GT
    assert SmtFeature.ARITHMETIC in doc.feature_tags()


def test_parse_arrays_select_store_and_model_request() -> None:
    result = parse_smtlib2(ARRAY_SCRIPT)
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    assert doc.request_model is True
    assert doc.assertions[0].formula.kind is SmtTermKind.EQ
    store = doc.assertions[0].formula.arguments[0]
    # (= (select (store a i v) i) v)
    assert store.kind is SmtTermKind.SELECT
    assert store.arguments[0].kind is SmtTermKind.STORE
    assert SmtFeature.ARRAYS in doc.feature_tags()


def test_parse_bitvectors_common_fragment() -> None:
    result = parse_smtlib2(BV_SCRIPT)
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    x = next(item for item in doc.functions if item.name == "x")
    assert x.range.name == "BitVec"
    assert x.range.parameters == ("8",)
    assert "FixedSizeBitVectors" in doc.theories or "bitvectors" in doc.theories


def test_parse_quantifiers() -> None:
    result = parse_smtlib2(QUANT_SCRIPT)
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    formula = doc.assertions[0].formula
    assert formula.kind is SmtTermKind.FORALL
    assert formula.binders[0].name == "x"
    assert formula.binders[0].sort.name == "U"
    assert SmtFeature.QUANTIFIERS in doc.feature_tags()


def test_parse_let_is_substituted() -> None:
    result = parse_smtlib2(LET_SCRIPT)
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    # (let ((x (+ a 1))) (> x a)) → (> (+ a 1) a)
    formula = doc.assertions[0].formula
    assert formula.kind is SmtTermKind.GT
    assert formula.arguments[0].kind is SmtTermKind.ADD
    assert formula.arguments[1].kind is SmtTermKind.SYMBOL
    assert formula.arguments[1].value == "a"


def test_parse_strings_common_fragment() -> None:
    result = parse_smtlib2(STRING_SCRIPT)
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    formula = doc.assertions[0].formula
    assert formula.kind is SmtTermKind.EQ
    assert formula.arguments[0].kind is SmtTermKind.APPLY
    assert formula.arguments[0].value == "str.len"
    assert "Strings" in doc.theories or "strings" in doc.theories


def test_parse_datatypes() -> None:
    result = parse_smtlib2(DATATYPE_SCRIPT)
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    assert len(doc.datatypes) == 1
    assert doc.datatypes[0].name == "Nat"
    ctor_names = {ctor.name for ctor in doc.datatypes[0].constructors}
    assert ctor_names == {"zero", "succ"}
    assert "zero" in doc.symbol_names
    assert "succ" in doc.symbol_names
    assert "pred" in doc.symbol_names


def test_set_option_produce_models() -> None:
    script = """\
(set-logic QF_UF)
(set-option :produce-models true)
(declare-const p Bool)
(assert p)
(check-sat)
(get-model)
"""
    doc = elaborate_smtlib2(script)
    assert doc.request_model is True
    assert doc.options.to_dict().get(":produce-models") is True


# ---------------------------------------------------------------------------
# Fail-closed unknown / unsupported commands and theories
# ---------------------------------------------------------------------------


def test_unknown_command_is_explicit() -> None:
    result = parse_smtlib2("(set-logic QF_UF)\n(frobnicate 1)\n")
    assert not result.ok
    assert any(item.code == CODE_UNKNOWN_COMMAND for item in result.errors)
    assert "frobnicate" in result.errors[0].message


def test_unsupported_command_is_explicit() -> None:
    assert "get-value" in UNSUPPORTED_COMMANDS
    result = parse_smtlib2("(set-logic QF_UF)\n(get-value (x))\n")
    assert not result.ok
    assert any(item.code == CODE_UNSUPPORTED_COMMAND for item in result.errors)


@pytest.mark.parametrize("command", sorted(UNSUPPORTED_COMMANDS)[:8])
def test_unsupported_command_table_is_fail_closed(command: str) -> None:
    result = parse_smtlib2(f"(set-logic QF_UF)\n({command})\n")
    assert not result.ok
    assert any(item.code == CODE_UNSUPPORTED_COMMAND for item in result.errors)


def test_unknown_logic_is_explicit() -> None:
    result = parse_smtlib2("(set-logic QF_IMAGINARY)\n")
    assert not result.ok
    assert any(item.code == CODE_UNKNOWN_THEORY for item in result.errors)


def test_unsupported_theory_via_set_info_is_explicit() -> None:
    result = parse_smtlib2("(set-logic QF_UF)\n(set-info :theory SepLogic)\n")
    assert not result.ok
    assert any(item.code == CODE_UNSUPPORTED_THEORY for item in result.errors)


def test_undeclared_symbol_fails() -> None:
    result = parse_smtlib2(
        "(set-logic QF_UF)\n(declare-const p Bool)\n(assert (unknown_pred p))\n"
    )
    assert not result.ok
    assert any(item.code == CODE_UNDECLARED_SYMBOL for item in result.errors)


def test_undeclared_sort_fails() -> None:
    result = parse_smtlib2("(set-logic QF_UF)\n(declare-const x MissingSort)\n")
    assert not result.ok
    assert any(item.code == CODE_UNDECLARED_SORT for item in result.errors)


def test_supported_commands_cover_evidence_subset() -> None:
    required = {
        "set-logic",
        "declare-sort",
        "declare-fun",
        "declare-const",
        "assert",
        "check-sat",
        "get-model",
        "get-unsat-core",
        "define-fun",
        "declare-datatypes",
    }
    assert required <= SUPPORTED_COMMANDS


# ---------------------------------------------------------------------------
# Round-trip: symbol/sort semantics preserved (Z3/cvc5 common fragment)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "script",
    [
        CORE_SCRIPT,
        ARITH_SCRIPT,
        ARRAY_SCRIPT,
        BV_SCRIPT,
        QUANT_SCRIPT,
        STRING_SCRIPT,
        DATATYPE_SCRIPT,
    ],
)
def test_parse_print_parse_preserves_symbol_and_sort_semantics(script: str) -> None:
    result = parse_print_parse_smtlib2(script)
    assert result.ok, (result.printed, [d.message for d in result.diagnostics])
    assert result.document is not None
    first = elaborate_smtlib2(script)
    assert documents_semantically_compatible(first, result.document)


def test_printer_emits_declarations_and_requests() -> None:
    doc = elaborate_smtlib2(ARRAY_SCRIPT)
    printed = print_smtlib2(doc)
    assert "(set-logic QF_AUFLIA)" in printed
    assert "(declare-const a (Array Int Int))" in printed or "(declare-const a" in printed
    assert "(check-sat)" in printed
    assert "(get-model)" in printed
    # Re-parse printed script.
    again = parse_smtlib2(printed)
    assert again.ok, [d.message for d in again.diagnostics]


def test_bv_sort_round_trip_print_form() -> None:
    doc = elaborate_smtlib2(BV_SCRIPT)
    printed = print_smtlib2(doc)
    assert "(_ BitVec 8)" in printed
    again = elaborate_smtlib2(printed)
    x = next(item for item in again.functions if item.name == "x")
    assert x.range.parameters == ("8",)


def test_frontend_round_trip_helper() -> None:
    result = _frontend().round_trip(CORE_SCRIPT)
    assert result.ok
    assert result.printed


# ---------------------------------------------------------------------------
# SMT bridge → typed semantic compiler
# ---------------------------------------------------------------------------


def test_bridge_to_obligation_preserves_symbols_and_sorts() -> None:
    doc = elaborate_smtlib2(ARITH_SCRIPT)
    obligation = bridge_smtlib2_to_obligation(
        ARITH_SCRIPT,
        obligation_id="obl:arith-test",
        query_mode=SmtQueryMode.SATISFIABILITY,
    )
    assert obligation.obligation_id == "obl:arith-test"
    assert obligation.logic == "QF_LIA"
    names = {item.name for item in obligation.functions}
    assert {"x", "y"} <= names
    assert obligation.request_unsat_core is True
    assert SmtTheory.ARITHMETIC in obligation.theories
    assert SmtFeature.ARITHMETIC in obligation.features
    assert obligation.goal is not None


def test_bridge_compile_emits_smtlib_with_declared_profile() -> None:
    frontend = _frontend()
    doc = frontend.parse_text_or_raise(CORE_SCRIPT)
    bridge_result = frontend.compile(
        doc,
        obligation_id="obl:core",
        query_mode=SmtQueryMode.SATISFIABILITY,
    )
    assert bridge_result.compilation is not None
    smtlib = bridge_result.compilation.smtlib
    assert "(set-logic" in smtlib
    assert "(declare-sort Person 0)" in smtlib
    assert "(declare-const alice Person)" in smtlib or "alice" in smtlib
    assert "(check-sat)" in smtlib
    # Bridge attributes carry notation/profile.
    assert bridge_result.obligation.attributes.to_dict()["profile_id"] == SMTLIB2_PROFILE_ID
    assert (
        bridge_result.obligation.attributes.to_dict()["source_interface"]
        == SMTLIB2_FRONTEND_INTERFACE
    )


def test_bridge_from_obligation_round_trip_symbols() -> None:
    frontend = _frontend()
    doc = frontend.parse_text_or_raise(CORE_SCRIPT)
    obligation = frontend.to_obligation(doc, obligation_id="obl:lift")
    lifted = frontend.bridge.from_obligation(obligation)
    assert set(lifted.symbol_names) == set(doc.symbol_names)
    assert set(lifted.sort_names) == set(doc.sort_names)


def test_common_fragment_scripts_bridge_without_semantic_loss_flags() -> None:
    """Z3/cvc5 common-fragment scripts lower without unsupported features."""

    for script in (CORE_SCRIPT, ARITH_SCRIPT, ARRAY_SCRIPT, QUANT_SCRIPT):
        obligation = bridge_smtlib2_to_obligation(script, obligation_id="obl:frag")
        assert obligation.unsupported_constructs == ()
        assert obligation.goal is not None or obligation.assumptions


# ---------------------------------------------------------------------------
# Optional external solver availability (capability gap, not usability claim)
# ---------------------------------------------------------------------------


def test_external_solver_availability_is_reported_not_assumed() -> None:
    """Do not claim Z3/cvc5 usability; only report PATH presence.

    The authoritative validation PATH is sealed and may lack provers.  This
    test records availability without requiring execution.
    """

    z3 = shutil.which("z3")
    cvc5 = shutil.which("cvc5")
    # Structural common-fragment round trips do not depend on either binary.
    result = parse_print_parse_smtlib2(CORE_SCRIPT)
    assert result.ok
    # Explicit capability gap note when tools are absent (not a failure).
    if z3 is None and cvc5 is None:
        pytest.skip(
            "dependency/capability gap: neither z3 nor cvc5 on sealed PATH; "
            "structural common-fragment round trips still pass"
        )
