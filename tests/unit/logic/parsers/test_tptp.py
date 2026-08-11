"""Unit tests for TPTPFrontend@1 and TSTPCandidateFrontend@1 (LFP-019).

Evidence subset:

* CNF / FOF / TFF annotated formulas with roles, symbols, formulas
* annotations (source + useful_info)
* safe includes; path traversal and absolute paths fail
* SZS / TSTP candidate parsing remains untrusted
* explicit unsupported THF
* declared-subset round trips
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.parsers.tptp import (
    CODE_CANDIDATE_AUTHORITY,
    CODE_EMPTY_INPUT,
    CODE_INPUT_LIMIT,
    CODE_MALFORMED_ANNOTATION,
    CODE_PATH_TRAVERSAL,
    CODE_TOKEN_LIMIT,
    CODE_UNSAFE_INCLUDE,
    CODE_UNSUPPORTED_LANGUAGE,
    CODE_UNSUPPORTED_THF,
    CODE_UNKNOWN_ROLE,
    SUPPORTED_LANGUAGES,
    SUPPORTED_ROLES,
    THF_LANGUAGES,
    TPTP_FRONTEND_INTERFACE,
    TPTP_NOTATION_ID,
    TPTP_PROFILE_ID,
    TPTPFormulaKind,
    TPTPFrontend,
    TPTPLanguage,
    TPTPParser,
    TPTPPrinter,
    TPTPRole,
    TSTP_CANDIDATE_FRONTEND_INTERFACE,
    TSTPCandidateFrontend,
    TSTPCandidateProof,
    TSTPError,
    UNSUPPORTED_LANGUAGES,
    documents_semantically_compatible,
    elaborate_tptp,
    parse_print_parse_tptp,
    parse_szs_status,
    parse_tptp,
    parse_tstp_candidate,
    print_tptp,
    validate_include_path,
)
from ipfs_datasets_py.logic.syntax_core.contracts import ParseLimits, ParseStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _frontend() -> TPTPFrontend:
    return TPTPFrontend()


CNF_PROBLEM = """\
% CNF sample
cnf(c1, axiom, p(a) | ~q(X)).
cnf(c2, negated_conjecture, ~p(a)).
"""

FOF_PROBLEM = """\
% FOF sample
fof(ax1, axiom, ! [X] : (p(X) => q(X))).
fof(ax2, axiom, p(a)).
fof(conj, conjecture, q(a)).
"""

TFF_PROBLEM = """\
% TFF typed sample
tff(animal_type, type, animal: $tType).
tff(human_type, type, human: $tType).
tff(alice_type, type, alice: human).
tff(parent_type, type, parent: (human * human) > $o).
tff(ax1, axiom, ! [X: human] : (parent(X, X) => $false)).
tff(conj, conjecture, ~ parent(alice, alice)).
"""

INCLUDE_PROBLEM = """\
include('Axioms/SET001+0.ax').
include('Local/helper.ax', [ax1, ax2]).
fof(local, axiom, p(a)).
"""

TSTP_CANDIDATE = """\
% SZS status Theorem
% SZS output start CNFRefutation
cnf(c_0, plain, p(a), file('problem.p', ax1)).
cnf(c_1, plain, ~p(a), inference(assume, [], [])).
cnf(c_2, plain, $false, inference(resolution, [], [c_0, c_1])).
% SZS output end CNFRefutation
"""


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_interface_and_module_identity() -> None:
    assert TPTP_FRONTEND_INTERFACE == "TPTPFrontend@1"
    assert TSTP_CANDIDATE_FRONTEND_INTERFACE == "TSTPCandidateFrontend@1"
    assert TPTP_NOTATION_ID == "tptp"
    assert TPTP_PROFILE_ID == "fof"
    frontend = _frontend()
    assert frontend.interface == TPTP_FRONTEND_INTERFACE
    assert isinstance(frontend.parser, TPTPParser)
    assert isinstance(frontend.printer, TPTPPrinter)
    assert isinstance(frontend.tstp, TSTPCandidateFrontend)
    assert frontend.tstp.interface == TSTP_CANDIDATE_FRONTEND_INTERFACE
    assert frontend.tstp.authority is ResultAuthority.CANDIDATE


def test_supported_vocabulary_covers_evidence_subset() -> None:
    assert {"cnf", "fof", "tff"} <= SUPPORTED_LANGUAGES
    assert "thf" in UNSUPPORTED_LANGUAGES
    assert "thf" in THF_LANGUAGES
    required_roles = {
        "axiom",
        "hypothesis",
        "conjecture",
        "negated_conjecture",
        "plain",
        "type",
        "definition",
        "lemma",
        "theorem",
    }
    assert required_roles <= SUPPORTED_ROLES


# ---------------------------------------------------------------------------
# Happy-path CNF / FOF / TFF
# ---------------------------------------------------------------------------


def test_parse_cnf_roles_and_literals() -> None:
    result = parse_tptp(CNF_PROBLEM)
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    assert doc.languages == ("cnf",)
    assert doc.formula_names == ("c1", "c2")
    assert doc.roles == ("axiom", "negated_conjecture")
    assert "p" in doc.symbol_names
    assert "q" in doc.symbol_names
    first = doc.formulas[0]
    assert first.language is TPTPLanguage.CNF
    assert first.formula.kind in {TPTPFormulaKind.OR, TPTPFormulaKind.CLAUSE}


def test_parse_fof_quantifiers_and_connectives() -> None:
    result = parse_tptp(FOF_PROBLEM)
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    assert set(doc.languages) == {"fof"}
    ax1 = doc.formulas[0]
    assert ax1.role is TPTPRole.AXIOM
    assert ax1.formula.kind is TPTPFormulaKind.FORALL
    assert ax1.formula.binders[0][0] == "X"
    body = ax1.formula.arguments[0]
    assert body.kind is TPTPFormulaKind.IMPLIES
    conj = doc.formulas[2]
    assert conj.role is TPTPRole.CONJECTURE
    assert conj.formula.kind is TPTPFormulaKind.ATOM
    assert conj.formula.name == "q"


def test_parse_tff_type_declarations_and_typed_quantifiers() -> None:
    result = parse_tptp(TFF_PROBLEM)
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    assert "tff" in doc.languages
    type_names = {decl.name for decl in doc.type_declarations}
    assert {"animal", "human", "alice", "parent"} <= type_names
    parent = next(d for d in doc.type_declarations if d.name == "parent")
    assert "$o" in parent.signature
    assert "*" in parent.signature
    ax1 = next(f for f in doc.formulas if f.name == "ax1")
    assert ax1.formula.kind is TPTPFormulaKind.FORALL
    assert ax1.formula.binders[0] == ("X", "human")
    assert "alice" in doc.symbol_names or "parent" in doc.symbol_names


def test_parse_includes_safe_relative_paths() -> None:
    result = parse_tptp(INCLUDE_PROBLEM)
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    assert len(doc.includes) == 2
    assert doc.includes[0].path == "Axioms/SET001+0.ax"
    assert doc.includes[1].path == "Local/helper.ax"
    assert doc.includes[1].formula_selection == ("ax1", "ax2")
    assert doc.formula_names == ("local",)


def test_annotations_are_preserved() -> None:
    text = (
        "fof(a1, axiom, p(a), "
        "file('problem.p', a1), [description('seed axiom')]).\n"
    )
    result = parse_tptp(text)
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    ann = doc.formulas[0].annotation
    assert ann is not None
    assert "file(" in ann.source
    assert "problem.p" in ann.source
    assert "'" in ann.source  # single-quoted path preserved
    assert any("description" in item for item in ann.useful_info)


def test_annotation_round_trip() -> None:
    text = (
        "fof(a1, axiom, p(a), "
        "file('problem.p', a1), [description('seed axiom')]).\n"
    )
    result = parse_print_parse_tptp(text)
    assert result.ok, (result.printed, [d.message for d in result.diagnostics])
    assert result.document is not None
    first = elaborate_tptp(text)
    assert documents_semantically_compatible(first, result.document)


# ---------------------------------------------------------------------------
# Fail-closed: THF, unsafe includes, malformed annotations
# ---------------------------------------------------------------------------


def test_thf_is_explicitly_unsupported() -> None:
    result = parse_tptp("thf(a, type, p: $o).")
    assert not result.ok
    assert any(item.code == CODE_UNSUPPORTED_THF for item in result.errors)
    assert "THF" in result.errors[0].message or "thf" in result.errors[0].message


@pytest.mark.parametrize("language", sorted(UNSUPPORTED_LANGUAGES))
def test_unsupported_languages_fail_closed(language: str) -> None:
    result = parse_tptp(f"{language}(a, axiom, p).")
    assert not result.ok
    codes = {item.code for item in result.errors}
    assert codes & {CODE_UNSUPPORTED_THF, CODE_UNSUPPORTED_LANGUAGE}


@pytest.mark.parametrize(
    "path",
    [
        "../etc/passwd",
        "../../secret.ax",
        "/etc/passwd",
        "Axioms/../../../etc/passwd",
        "C:\\Windows\\system32",
        "~/.ssh/id_rsa",
        "https://evil.example/a.ax",
        "file://host/a.ax",
        "",
        "bad\x00name.ax",
    ],
)
def test_unsafe_includes_and_path_traversal_fail(path: str) -> None:
    if path == "":
        text = "include('')."
    elif "\x00" in path:
        text = "include('bad\x00name.ax')."
    else:
        escaped = path.replace("\\", "\\\\").replace("'", "\\'")
        text = f"include('{escaped}')."
    result = parse_tptp(text)
    assert not result.ok
    codes = {item.code for item in result.errors}
    assert codes & {CODE_PATH_TRAVERSAL, CODE_UNSAFE_INCLUDE, CODE_MALFORMED_ANNOTATION}


def test_validate_include_path_accepts_safe_relative() -> None:
    assert validate_include_path("Axioms/SET001+0.ax") == "Axioms/SET001+0.ax"
    assert validate_include_path("local.ax") == "local.ax"


def test_validate_include_path_rejects_parent_segments() -> None:
    with pytest.raises(Exception) as excinfo:
        validate_include_path("../x.ax")
    assert getattr(excinfo.value, "code", "") == CODE_PATH_TRAVERSAL


@pytest.mark.parametrize(
    "text",
    [
        "fof(a, axiom, p, ).",
        "fof(a, axiom, p, inference().",
        "fof(a, axiom, p, inference().",
        "fof(a, axiom, p, file('x'.",
        "fof(a, axiom, p, , [info]).",
    ],
)
def test_malformed_annotations_fail(text: str) -> None:
    result = parse_tptp(text)
    assert not result.ok
    # May surface as malformed annotation, unbalanced, or unexpected token.
    assert result.errors
    assert any(
        item.code
        in {
            CODE_MALFORMED_ANNOTATION,
            "tptp.unbalanced_delimiter",
            "tptp.unexpected_token",
            "tptp.malformed_annotated_formula",
            "tptp.malformed_formula",
        }
        for item in result.errors
    )


def test_unknown_role_fails() -> None:
    result = parse_tptp("fof(a, not_a_real_role, p(a)).")
    assert not result.ok
    assert any(item.code == CODE_UNKNOWN_ROLE for item in result.errors)


def test_empty_input_fails() -> None:
    result = parse_tptp("   \n  % only comments\n")
    assert not result.ok
    assert result.status in {ParseStatus.FAILED, ParseStatus.REJECTED}
    assert any(item.code == CODE_EMPTY_INPUT for item in result.errors)


def test_input_byte_limit_rejected() -> None:
    text = "fof(a, axiom, p).\n" * 20
    result = parse_tptp(
        text, limits=ParseLimits(max_input_bytes=32, max_tokens=64, max_depth=16)
    )
    assert not result.ok
    assert any(item.code == CODE_INPUT_LIMIT for item in result.errors)


def test_token_limit_rejected() -> None:
    text = "fof(a, axiom, " + " & ".join(["p"] * 40) + ")."
    result = parse_tptp(
        text, limits=ParseLimits(max_input_bytes=4096, max_tokens=10, max_depth=64)
    )
    assert not result.ok
    assert any(item.code == CODE_TOKEN_LIMIT for item in result.errors)


# ---------------------------------------------------------------------------
# Round-trip: declared subset
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "script",
    [
        CNF_PROBLEM,
        FOF_PROBLEM,
        TFF_PROBLEM,
        INCLUDE_PROBLEM,
    ],
)
def test_parse_print_parse_preserves_structure(script: str) -> None:
    result = parse_print_parse_tptp(script)
    assert result.ok, (result.printed, [d.message for d in result.diagnostics])
    assert result.document is not None
    first = elaborate_tptp(script)
    assert documents_semantically_compatible(first, result.document)


def test_printer_emits_languages_roles_and_includes() -> None:
    doc = elaborate_tptp(INCLUDE_PROBLEM)
    printed = print_tptp(doc)
    assert "include('Axioms/SET001+0.ax')." in printed
    assert "include('Local/helper.ax', [ax1, ax2])." in printed
    assert "fof(local, axiom," in printed
    again = parse_tptp(printed)
    assert again.ok, [d.message for d in again.diagnostics]


def test_frontend_round_trip_helper() -> None:
    frontend = _frontend()
    result = frontend.round_trip(FOF_PROBLEM)
    assert result.ok
    assert result.printed
    assert "fof(ax1, axiom," in result.printed


# ---------------------------------------------------------------------------
# TSTP candidate remains untrusted
# ---------------------------------------------------------------------------


def test_tstp_candidate_parse_and_authority() -> None:
    result = parse_tstp_candidate(TSTP_CANDIDATE)
    assert result.ok, [d.message for d in result.diagnostics]
    candidate = result.candidate
    assert candidate is not None
    assert candidate.authority is ResultAuthority.CANDIDATE
    assert candidate.status is ResultStatus.CANDIDATE
    assert candidate.trusted is False
    assert candidate.is_trusted is False
    assert candidate.szs_status == "Theorem"
    assert candidate.szs_output_form == "CNFRefutation"
    assert len(candidate.steps) == 3
    assert candidate.step_names == ("c_0", "c_1", "c_2")
    # Inference annotation present on derived steps.
    assert candidate.steps[2].annotation is not None
    assert "inference" in candidate.steps[2].annotation.source
    payload = candidate.to_dict()
    assert payload["trusted"] is False
    assert payload["authority"] == "candidate"
    assert payload["interface"] == TSTP_CANDIDATE_FRONTEND_INTERFACE


def test_tstp_candidate_cannot_be_constructed_as_theorem() -> None:
    step_doc = elaborate_tptp("cnf(c0, plain, p(a)).")
    formula = step_doc.formulas[0]
    from ipfs_datasets_py.logic.parsers.tptp import TSTPProofStep

    step = TSTPProofStep(
        language=formula.language.value,
        name=formula.name,
        role=formula.role.value,
        formula=formula.formula,
    )
    with pytest.raises(TSTPError) as excinfo:
        TSTPCandidateProof(
            steps=(step,),
            authority=ResultAuthority.THEOREM,  # type: ignore[arg-type]
            status=ResultStatus.PROVED,  # type: ignore[arg-type]
        )
    assert excinfo.value.code == CODE_CANDIDATE_AUTHORITY


def test_tstp_candidate_trusted_flag_is_forced_false() -> None:
    step_doc = elaborate_tptp("cnf(c0, plain, p(a)).")
    formula = step_doc.formulas[0]
    from ipfs_datasets_py.logic.parsers.tptp import TSTPProofStep

    step = TSTPProofStep(
        language=formula.language.value,
        name=formula.name,
        role=formula.role.value,
        formula=formula.formula,
    )
    candidate = TSTPCandidateProof(steps=(step,), trusted=True)
    assert candidate.trusted is False
    assert candidate.is_trusted is False
    assert candidate.authority is ResultAuthority.CANDIDATE


def test_parse_szs_status_extracts_token() -> None:
    assert parse_szs_status("% SZS status Unsatisfiable\n") == "Unsatisfiable"
    assert parse_szs_status("no status here") is None


def test_tstp_frontend_via_tptp_facade() -> None:
    frontend = _frontend()
    result = frontend.tstp.parse_text(TSTP_CANDIDATE)
    assert result.ok
    assert result.candidate is not None
    assert result.candidate.authority is ResultAuthority.CANDIDATE


def test_equality_and_false_clause() -> None:
    text = """\
fof(eq1, axiom, a = b).
fof(neq1, axiom, a != c).
cnf(empty, plain, $false).
"""
    result = parse_tptp(text)
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    assert doc.formulas[0].formula.kind is TPTPFormulaKind.EQ
    assert doc.formulas[1].formula.kind is TPTPFormulaKind.NEQ
    assert doc.formulas[2].formula.kind is TPTPFormulaKind.FALSE


def test_exists_quantifier() -> None:
    text = "fof(ex, axiom, ? [X, Y] : (p(X) & q(Y))).\n"
    result = parse_tptp(text)
    assert result.ok, [d.message for d in result.diagnostics]
    formula = result.document.formulas[0].formula  # type: ignore[union-attr]
    assert formula.kind is TPTPFormulaKind.EXISTS
    assert len(formula.binders) == 2
    assert formula.arguments[0].kind is TPTPFormulaKind.AND
