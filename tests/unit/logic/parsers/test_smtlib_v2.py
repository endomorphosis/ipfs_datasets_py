"""Unit tests for SMTLIBFrontend@2 shared artifact pipeline (LFP2-011).

Acceptance:

* Supported constructs round-trip semantically
* Unsupported vendor/theory features and duplicate declarations fail with
  exact spans
* Emits ParseArtifact@2 and ElaborationArtifact@2
* Registers under SharedFrontendConformance@1
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.smt.compiler import SmtFeature, SmtTermKind
from ipfs_datasets_py.logic.parsers.frontend_contract import (
    REQUIRED_ELABORATION_ARTIFACT_INTERFACE,
    REQUIRED_PARSE_ARTIFACT_INTERFACE,
    SharedFrontendConformance,
    validate_frontend_descriptor,
)
from ipfs_datasets_py.logic.parsers.smtlib_v2 import (
    CODE_DUPLICATE_SORT,
    CODE_DUPLICATE_SYMBOL,
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
    ELABORATION_ARTIFACT_V2_INTERFACE,
    PARSE_ARTIFACT_V2_INTERFACE,
    SMTLIB_DESCRIPTOR_ID,
    SMTLIB_FAMILY_ID,
    SMTLIB_FRONTEND_INTERFACE,
    SMTLIB_NOTATION_ID,
    SMTLIB_NOTATION_VERSION,
    SMTLIB_PROFILE_ID,
    SMTLIB_V2_TASK_ID,
    SMTLIBFrontend,
    SUPPORTED_COMMANDS,
    UNSUPPORTED_COMMANDS,
    build_smtlib_frontend_descriptor,
    documents_semantically_compatible,
    elaborate_smtlib_v2,
    parse_print_parse_smtlib_v2,
    parse_smtlib_v2,
    print_smtlib_v2,
    register_smtlib_frontend,
)
from ipfs_datasets_py.logic.syntax_core.artifacts_v2 import (
    ElaborationArtifactStatus,
    ElaborationArtifactV2,
    ParseArtifactV2,
)
from ipfs_datasets_py.logic.syntax_core.contracts import ParseLimits, ParseStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _frontend() -> SMTLIBFrontend:
    return SMTLIBFrontend()


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

ROUND_TRIP_SCRIPTS = (
    CORE_SCRIPT,
    ARITH_SCRIPT,
    ARRAY_SCRIPT,
    BV_SCRIPT,
    QUANT_SCRIPT,
    STRING_SCRIPT,
    DATATYPE_SCRIPT,
    LET_SCRIPT,
)


# ---------------------------------------------------------------------------
# Interface / descriptor
# ---------------------------------------------------------------------------


def test_interface_identities() -> None:
    assert SMTLIB_FRONTEND_INTERFACE == "SMTLIBFrontend@2"
    assert PARSE_ARTIFACT_V2_INTERFACE == "ParseArtifact@2"
    assert ELABORATION_ARTIFACT_V2_INTERFACE == "ElaborationArtifact@2"
    assert SMTLIB_V2_TASK_ID == "LFP2-011"
    frontend = _frontend()
    assert frontend.interface == SMTLIB_FRONTEND_INTERFACE
    assert frontend.notation_id == SMTLIB_NOTATION_ID
    assert frontend.notation_version == SMTLIB_NOTATION_VERSION
    assert frontend.profile_id == SMTLIB_PROFILE_ID
    assert frontend.family_id == SMTLIB_FAMILY_ID


def test_descriptor_admits_under_shared_conformance() -> None:
    descriptor = build_smtlib_frontend_descriptor()
    validate_frontend_descriptor(descriptor)
    assert descriptor.descriptor_id == SMTLIB_DESCRIPTOR_ID
    assert REQUIRED_PARSE_ARTIFACT_INTERFACE in descriptor.artifact_interfaces()
    assert REQUIRED_ELABORATION_ARTIFACT_INTERFACE in descriptor.artifact_interfaces()
    assert descriptor.has_feature("parse")
    assert descriptor.has_feature("elaborate")
    assert descriptor.has_feature("print")
    assert descriptor.has_feature("source_map")

    registry, admitted = register_smtlib_frontend()
    assert admitted.descriptor_id == descriptor.descriptor_id
    assert len(registry) == 1
    resolved = registry.resolve(
        SMTLIB_NOTATION_ID, SMTLIB_NOTATION_VERSION, SMTLIB_PROFILE_ID
    )
    assert resolved.descriptor_id == SMTLIB_DESCRIPTOR_ID


def test_descriptor_round_trip() -> None:
    descriptor = build_smtlib_frontend_descriptor()
    payload = descriptor.to_dict()
    from ipfs_datasets_py.logic.parsers.frontend_contract import (
        LogicFrontendDescriptor,
    )

    restored = LogicFrontendDescriptor.from_dict(payload)
    assert restored.to_dict() == payload


# ---------------------------------------------------------------------------
# Happy-path parse → shared artifacts
# ---------------------------------------------------------------------------


def test_parse_emits_parse_and_elaboration_artifacts() -> None:
    result = parse_smtlib_v2(CORE_SCRIPT)
    assert result.ok, [d.message for d in result.diagnostics]
    assert isinstance(result.parse_artifact, ParseArtifactV2)
    assert isinstance(result.elaboration_artifact, ElaborationArtifactV2)
    assert result.parse_artifact.interface == "ParseArtifact@2"
    assert result.elaboration_artifact.interface == "ElaborationArtifact@2"
    assert result.parse_artifact.status is ParseStatus.OK
    assert result.elaboration_artifact.status is ElaborationArtifactStatus.OK
    assert result.expression is not None
    assert result.root is not None
    assert result.document is not None
    assert result.document.logic == "QF_UF"
    assert "Person" in result.document.sort_names
    assert "alice" in result.document.symbol_names
    assert "knows" in result.document.symbol_names

    # Lineage: elaboration is bound to parse/source digests.
    result.elaboration_artifact.validate_lineage(
        parse_artifact=result.parse_artifact,
        document=result.source_document,
    )
    assert result.parse_artifact.cst is not None
    assert result.parse_artifact.source_map is not None
    assert result.parse_artifact.typed_roots
    assert result.elaboration_artifact.typed_expression is not None
    assert result.elaboration_artifact.backend_ready


def test_parse_arithmetic_named_assertion_and_unsat_core() -> None:
    result = parse_smtlib_v2(ARITH_SCRIPT)
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    assert doc.request_unsat_core is True
    assert doc.assertions[0].name == "assume_ge_one"
    assert doc.assertions[0].formula.kind is SmtTermKind.GE
    assert SmtFeature.ARITHMETIC in doc.feature_tags()


def test_parse_arrays_select_store_and_model_request() -> None:
    result = parse_smtlib_v2(ARRAY_SCRIPT)
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    assert doc.request_model is True
    assert doc.assertions[0].formula.kind is SmtTermKind.EQ
    assert SmtFeature.ARRAYS in doc.feature_tags()


def test_parse_bitvectors_common_fragment() -> None:
    result = parse_smtlib_v2(BV_SCRIPT)
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    x = next(item for item in doc.functions if item.name == "x")
    assert x.range.name == "BitVec"
    assert x.range.parameters == ("8",)


def test_parse_quantifiers_and_datatypes() -> None:
    quant = parse_smtlib_v2(QUANT_SCRIPT)
    assert quant.ok, [d.message for d in quant.diagnostics]
    formula = quant.document.assertions[0].formula  # type: ignore[union-attr]
    assert formula.kind is SmtTermKind.FORALL
    assert formula.binders[0].name == "x"
    assert SmtFeature.QUANTIFIERS in quant.document.feature_tags()  # type: ignore[union-attr]

    dt = parse_smtlib_v2(DATATYPE_SCRIPT)
    assert dt.ok, [d.message for d in dt.diagnostics]
    assert dt.document is not None
    assert dt.document.datatypes[0].name == "Nat"
    assert "zero" in dt.document.symbol_names
    assert "succ" in dt.document.symbol_names


def test_parse_let_is_substituted() -> None:
    result = parse_smtlib_v2(LET_SCRIPT)
    assert result.ok, [d.message for d in result.diagnostics]
    formula = result.document.assertions[0].formula  # type: ignore[union-attr]
    assert formula.kind is SmtTermKind.GT
    assert formula.arguments[0].kind is SmtTermKind.ADD


def test_typed_expression_carries_script_payload() -> None:
    result = parse_smtlib_v2(CORE_SCRIPT)
    assert result.ok
    root = result.root
    assert root is not None
    assert root.extension is not None
    payload = root.extension.payload
    assert payload["kind"] == "script"
    assert payload["logic"] == "QF_UF"
    assert "Person" in payload["sort_names"]
    assert "knows" in payload["symbol_names"]
    assert root.extension.payload_schema == "smtlib.script/v1"


# ---------------------------------------------------------------------------
# Fail-closed unsupported / duplicates with exact spans
# ---------------------------------------------------------------------------


def test_unknown_command_fails_with_exact_span() -> None:
    script = "(set-logic QF_UF)\n(frobnicate 1)\n"
    result = parse_smtlib_v2(script)
    assert not result.ok
    assert any(item.code == CODE_UNKNOWN_COMMAND for item in result.errors)
    err = next(item for item in result.errors if item.code == CODE_UNKNOWN_COMMAND)
    assert err.range is not None
    assert err.range.start >= 0
    assert err.range.end > err.range.start
    # Span covers the bad command form.
    snippet = script[err.range.start : err.range.end]
    assert "frobnicate" in snippet
    assert result.parse_artifact is not None
    assert result.elaboration_artifact is not None
    assert result.elaboration_artifact.status is ElaborationArtifactStatus.FAILED


def test_unsupported_command_fails_with_exact_span() -> None:
    assert "get-value" in UNSUPPORTED_COMMANDS
    script = "(set-logic QF_UF)\n(get-value (x))\n"
    result = parse_smtlib_v2(script)
    assert not result.ok
    err = next(item for item in result.errors if item.code == CODE_UNSUPPORTED_COMMAND)
    assert err.range is not None
    assert "get-value" in script[err.range.start : err.range.end]


@pytest.mark.parametrize("command", sorted(UNSUPPORTED_COMMANDS)[:8])
def test_unsupported_command_table_is_fail_closed(command: str) -> None:
    result = parse_smtlib_v2(f"(set-logic QF_UF)\n({command})\n")
    assert not result.ok
    assert any(item.code == CODE_UNSUPPORTED_COMMAND for item in result.errors)
    err = next(item for item in result.errors if item.code == CODE_UNSUPPORTED_COMMAND)
    assert err.range is not None


def test_unknown_logic_fails_with_exact_span() -> None:
    script = "(set-logic QF_IMAGINARY)\n"
    result = parse_smtlib_v2(script)
    assert not result.ok
    err = next(item for item in result.errors if item.code == CODE_UNKNOWN_THEORY)
    assert err.range is not None
    assert "QF_IMAGINARY" in script[err.range.start : err.range.end]


def test_unsupported_theory_via_set_info_fails_with_exact_span() -> None:
    script = "(set-logic QF_UF)\n(set-info :theory SepLogic)\n"
    result = parse_smtlib_v2(script)
    assert not result.ok
    err = next(item for item in result.errors if item.code == CODE_UNSUPPORTED_THEORY)
    assert err.range is not None
    assert "SepLogic" in script[err.range.start : err.range.end]


def test_duplicate_sort_fails_with_exact_span() -> None:
    script = (
        "(set-logic QF_UF)\n"
        "(declare-sort Person 0)\n"
        "(declare-sort Person 0)\n"
    )
    result = parse_smtlib_v2(script)
    assert not result.ok
    err = next(item for item in result.errors if item.code == CODE_DUPLICATE_SORT)
    assert err.range is not None
    # Span points at the duplicate name (second Person).
    assert script[err.range.start : err.range.end] == "Person"
    assert err.range.start == script.rfind("Person")


def test_duplicate_symbol_fails_with_exact_span() -> None:
    script = (
        "(set-logic QF_UF)\n"
        "(declare-const x Bool)\n"
        "(declare-const x Bool)\n"
    )
    result = parse_smtlib_v2(script)
    assert not result.ok
    err = next(item for item in result.errors if item.code == CODE_DUPLICATE_SYMBOL)
    assert err.range is not None
    assert script[err.range.start : err.range.end] == "x"
    assert err.range.start == script.rfind("x")


def test_undeclared_symbol_and_sort_fail() -> None:
    bad_sym = parse_smtlib_v2(
        "(set-logic QF_UF)\n(declare-const p Bool)\n(assert (unknown_pred p))\n"
    )
    assert not bad_sym.ok
    assert any(item.code == CODE_UNDECLARED_SYMBOL for item in bad_sym.errors)
    assert bad_sym.errors[0].range is not None

    bad_sort = parse_smtlib_v2(
        "(set-logic QF_UF)\n(declare-const x MissingSort)\n"
    )
    assert not bad_sort.ok
    assert any(item.code == CODE_UNDECLARED_SORT for item in bad_sort.errors)
    assert bad_sort.errors[0].range is not None


def test_reader_resource_limits_and_unbalanced() -> None:
    unbalanced = parse_smtlib_v2("(assert (and true")
    assert not unbalanced.ok
    assert any(item.code == CODE_UNBALANCED for item in unbalanced.errors)

    empty = parse_smtlib_v2("   \n  ; only comments\n")
    assert not empty.ok
    assert any(item.code == CODE_EMPTY_INPUT for item in empty.errors)

    limits = ParseLimits(
        max_input_bytes=32,
        max_tokens=64,
        max_depth=16,
        max_diagnostics=32,
        max_time_ms=1000,
        max_memory_bytes=1_048_576,
    )
    oversize = parse_smtlib_v2("(assert true)\n" * 50, limits=limits)
    assert not oversize.ok
    assert any(item.code == CODE_INPUT_LIMIT for item in oversize.errors)

    token_limits = ParseLimits(
        max_input_bytes=4096,
        max_tokens=10,
        max_depth=64,
        max_diagnostics=32,
        max_time_ms=1000,
        max_memory_bytes=1_048_576,
    )
    too_many = parse_smtlib_v2(
        "(assert " + " ".join(["true"] * 40) + ")",
        limits=token_limits,
    )
    assert not too_many.ok
    assert any(item.code == CODE_TOKEN_LIMIT for item in too_many.errors)

    depth_limits = ParseLimits(
        max_input_bytes=4096,
        max_tokens=256,
        max_depth=5,
        max_diagnostics=32,
        max_time_ms=1000,
        max_memory_bytes=1_048_576,
    )
    deep = parse_smtlib_v2("(" * 20 + "true" + ")" * 20, limits=depth_limits)
    assert not deep.ok
    assert any(item.code == CODE_PARSE_DEPTH for item in deep.errors)


# ---------------------------------------------------------------------------
# Semantic round-trip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("script", ROUND_TRIP_SCRIPTS)
def test_parse_print_parse_preserves_semantics(script: str) -> None:
    result = parse_print_parse_smtlib_v2(script)
    assert result.ok, (result.printed, [d.message for d in result.diagnostics])
    assert result.document is not None
    assert result.parse_artifact is not None
    assert result.elaboration_artifact is not None
    first = elaborate_smtlib_v2(script)
    assert documents_semantically_compatible(first, result.document)


def test_printer_emits_declarations_and_requests() -> None:
    doc = elaborate_smtlib_v2(ARRAY_SCRIPT)
    printed = print_smtlib_v2(doc)
    assert "(set-logic QF_AUFLIA)" in printed
    assert "(check-sat)" in printed
    assert "(get-model)" in printed
    again = parse_smtlib_v2(printed)
    assert again.ok, [d.message for d in again.diagnostics]


def test_frontend_round_trip_helper() -> None:
    result = _frontend().round_trip(CORE_SCRIPT)
    assert result.ok
    assert result.printed
    assert result.elaboration_artifact is not None
    assert result.elaboration_artifact.status is ElaborationArtifactStatus.OK


def test_bv_sort_round_trip_print_form() -> None:
    doc = elaborate_smtlib_v2(BV_SCRIPT)
    printed = print_smtlib_v2(doc)
    assert "(_ BitVec 8)" in printed
    again = elaborate_smtlib_v2(printed)
    x = next(item for item in again.functions if item.name == "x")
    assert x.range.parameters == ("8",)


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


def test_source_map_entries_cover_commands() -> None:
    result = parse_smtlib_v2(CORE_SCRIPT)
    assert result.ok
    assert result.source_map is not None
    assert result.source_map.entries
    heads = {
        entry.metadata.get("head")
        for entry in result.source_map.entries
        if entry.metadata.get("head")
    }
    assert "set-logic" in heads
    assert "assert" in heads
    assert "check-sat" in heads


def test_parse_artifact_validate_against_source() -> None:
    result = parse_smtlib_v2(CORE_SCRIPT)
    assert result.ok
    assert result.parse_artifact is not None
    assert result.source_document is not None
    result.parse_artifact.validate_against(result.source_document)
    # Tokens carry document identity.
    assert result.tokens
    assert all(tok.document_id == result.source_document.document_id for tok in result.tokens)
