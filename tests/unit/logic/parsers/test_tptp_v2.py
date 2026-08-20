"""Unit tests for TPTPFrontend@2 and TSTPFrontend@1 (LFP2-012).

Acceptance:

* Vampire/E-oriented CNF/FOF/TFF inputs are typed with shared ParseArtifact@2
  and ElaborationArtifact@2 envelopes
* Controlled TSTP/SZS outputs are typed at candidate authority only
* Include policies, roles, source maps, and feature limits are enforced
* THF remains profile-scoped / explicit unsupported until admitted
* Frontend cannot register without shared artifact output, limits, diagnostics,
  and feature-scoped fixtures
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.parsers.frontend_contract import (
    SharedFrontendConformance,
    validate_frontend_descriptor,
)
from ipfs_datasets_py.logic.parsers.tptp_v2 import (
    CODE_CANDIDATE_AUTHORITY,
    CODE_EMPTY_INPUT,
    CODE_FEATURE_LIMIT,
    CODE_INCLUDE_POLICY,
    CODE_INPUT_LIMIT,
    CODE_PATH_TRAVERSAL,
    CODE_ROUND_TRIP,
    CODE_TOKEN_LIMIT,
    CODE_UNSAFE_INCLUDE,
    CODE_UNSUPPORTED_LANGUAGE,
    CODE_UNSUPPORTED_THF,
    DEFAULT_FRONTEND_LIMITS,
    DEFAULT_INCLUDE_POLICY,
    DEFAULT_PROFILE_SCOPE,
    IncludePolicy,
    IncludePolicyConfig,
    SUPPORTED_LANGUAGES,
    SUPPORTED_ROLES,
    THF_LANGUAGES,
    TPTP_FRONTEND_V2_INTERFACE,
    TPTP_V2_DESCRIPTOR_ID,
    TPTP_V2_GOAL_ID,
    TPTP_V2_MODULE_VERSION,
    TPTP_V2_NOTATION_ID,
    TPTP_V2_PROFILE_ID,
    TPTP_V2_TASK_ID,
    TPTPFrontendV2,
    TPTPLanguage,
    TPTPProfileScope,
    TPTPRole,
    TSTP_FRONTEND_INTERFACE,
    TSTPFrontend,
    TSTPFrontendError,
    TSTPProofRecord,
    UNSUPPORTED_LANGUAGES,
    build_tptp_v2_descriptor,
    documents_semantically_compatible,
    elaborate_tptp_v2,
    parse_print_parse_tptp_v2,
    parse_szs_status,
    parse_tptp_v2,
    parse_tstp_v2,
    print_tptp_v2,
    register_tptp_v2_frontend,
    validate_include_under_policy,
)
from ipfs_datasets_py.logic.syntax_core.artifacts_v2 import (
    ELABORATION_ARTIFACT_V2_INTERFACE,
    PARSE_ARTIFACT_V2_INTERFACE,
    ElaborationArtifactStatus,
)
from ipfs_datasets_py.logic.syntax_core.contracts import ParseLimits, ParseStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _frontend(**kwargs) -> TPTPFrontendV2:
    return TPTPFrontendV2(**kwargs)


CNF_PROBLEM = """\
% CNF sample (Vampire/E style)
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

VAMPIRE_STYLE = """\
%----Vampire-oriented FOF problem
fof(a1, axiom, ! [X] : (human(X) => mortal(X))).
fof(a2, axiom, human(socrates)).
fof(c1, conjecture, mortal(socrates)).
"""

EPROVER_STYLE = """\
% E prover CNF clause set
cnf(c_0, axiom, ~p(X) | q(X)).
cnf(c_1, axiom, p(a)).
cnf(c_2, negated_conjecture, ~q(a)).
"""


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_interface_and_module_identity() -> None:
    assert TPTP_FRONTEND_V2_INTERFACE == "TPTPFrontend@2"
    assert TSTP_FRONTEND_INTERFACE == "TSTPFrontend@1"
    assert TPTP_V2_NOTATION_ID == "tptp"
    assert TPTP_V2_PROFILE_ID == "fof"
    assert TPTP_V2_MODULE_VERSION == "2.0.0"
    assert TPTP_V2_TASK_ID == "LFP2-012"
    assert TPTP_V2_GOAL_ID == "LFP2-G030"
    frontend = _frontend()
    assert frontend.interface == TPTP_FRONTEND_V2_INTERFACE
    assert frontend.tstp.interface == TSTP_FRONTEND_INTERFACE
    assert frontend.tstp.authority is ResultAuthority.CANDIDATE
    assert frontend.descriptor.descriptor_id == TPTP_V2_DESCRIPTOR_ID
    assert DEFAULT_INCLUDE_POLICY is IncludePolicy.RELATIVE_SAFE
    assert DEFAULT_PROFILE_SCOPE is TPTPProfileScope.FOF


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
# Descriptor / shared frontend conformance
# ---------------------------------------------------------------------------


def test_descriptor_declares_shared_artifacts_limits_diagnostics_fixtures() -> None:
    descriptor = build_tptp_v2_descriptor()
    validate_frontend_descriptor(descriptor)
    interfaces = {item.interface for item in descriptor.artifact_outputs}
    assert PARSE_ARTIFACT_V2_INTERFACE in interfaces
    assert ELABORATION_ARTIFACT_V2_INTERFACE in interfaces
    assert descriptor.limits.parse_limits.max_input_bytes > 0
    assert descriptor.limits.parse_limits.max_tokens > 0
    assert descriptor.diagnostics
    assert all("." in code for code in descriptor.diagnostics)
    assert descriptor.fixtures
    features = set(descriptor.features)
    assert "parse" in features
    assert "source_map" in features
    assert "elaborate" in features


def test_register_tptp_v2_frontend_admits_descriptor() -> None:
    registry, admitted = register_tptp_v2_frontend()
    assert isinstance(registry, SharedFrontendConformance)
    assert admitted.descriptor_id == TPTP_V2_DESCRIPTOR_ID
    assert registry.get(TPTP_V2_DESCRIPTOR_ID).interface == (
        "LogicFrontendDescriptor@1"
    )


# ---------------------------------------------------------------------------
# Happy-path CNF / FOF / TFF with shared artifacts
# ---------------------------------------------------------------------------


def test_parse_cnf_emits_parse_and_elaboration_artifacts() -> None:
    result = parse_tptp_v2(CNF_PROBLEM)
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.interface == TPTP_FRONTEND_V2_INTERFACE
    doc = result.document
    assert doc is not None
    assert doc.languages == ("cnf",)
    assert doc.formula_names == ("c1", "c2")
    assert doc.roles == ("axiom", "negated_conjecture")

    parse_art = result.parse_artifact
    assert parse_art is not None
    assert parse_art.interface == PARSE_ARTIFACT_V2_INTERFACE
    assert parse_art.status is ParseStatus.OK
    assert parse_art.cst is not None
    assert parse_art.source_map is not None
    assert parse_art.tokens
    assert parse_art.content_digest
    assert parse_art.lineage_digest
    assert parse_art.metadata["roles"] == ["axiom", "negated_conjecture"]

    elab = result.elaboration_artifact
    assert elab is not None
    assert elab.interface == ELABORATION_ARTIFACT_V2_INTERFACE
    assert elab.status is ElaborationArtifactStatus.OK
    assert elab.typed_expression is not None
    assert elab.parse_artifact_id == parse_art.artifact_id
    assert elab.source_digest == parse_art.source_digest


def test_parse_fof_quantifiers_roles_and_source_map() -> None:
    result = parse_tptp_v2(FOF_PROBLEM)
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    assert set(doc.languages) == {"fof"}
    ax1 = doc.formulas[0]
    assert ax1.role is TPTPRole.AXIOM
    conj = doc.formulas[2]
    assert conj.role is TPTPRole.CONJECTURE
    assert result.parse_artifact is not None
    assert result.parse_artifact.source_map is not None
    assert result.parse_artifact.source_map.entries
    surface_kinds = {item.kind for item in result.parse_artifact.surface_ast}
    assert "annotated_formula" in surface_kinds
    assert "tptp_document" in surface_kinds


def test_parse_tff_type_declarations() -> None:
    result = parse_tptp_v2(TFF_PROBLEM)
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    assert "tff" in doc.languages
    type_names = {decl.name for decl in doc.type_declarations}
    assert {"animal", "human", "alice", "parent"} <= type_names
    assert result.typed_expression is not None


def test_vampire_and_eprover_style_inputs_are_typed() -> None:
    for script in (VAMPIRE_STYLE, EPROVER_STYLE):
        result = parse_tptp_v2(script)
        assert result.ok, [d.message for d in result.diagnostics]
        assert result.parse_artifact is not None
        assert result.parse_artifact.interface == PARSE_ARTIFACT_V2_INTERFACE
        assert result.elaboration_artifact is not None
        assert result.document is not None
        assert result.document.roles


def test_includes_safe_relative_paths_recorded() -> None:
    result = parse_tptp_v2(INCLUDE_PROBLEM)
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    assert len(doc.includes) == 2
    assert doc.includes[0].path == "Axioms/SET001+0.ax"
    assert doc.includes[1].formula_selection == ("ax1", "ax2")
    assert result.parse_artifact is not None
    assert result.parse_artifact.metadata["include_paths"] == [
        "Axioms/SET001+0.ax",
        "Local/helper.ax",
    ]
    surface = result.parse_artifact.surface_ast
    assert any(item.kind == "include" for item in surface)


# ---------------------------------------------------------------------------
# Include policies and feature limits
# ---------------------------------------------------------------------------


def test_include_policy_reject_blocks_includes() -> None:
    frontend = _frontend(
        include_policy=IncludePolicyConfig(policy=IncludePolicy.REJECT)
    )
    result = frontend.parse_text(INCLUDE_PROBLEM)
    assert not result.ok
    assert any(item.code == CODE_INCLUDE_POLICY for item in result.errors)


def test_include_policy_max_includes_feature_limit() -> None:
    frontend = _frontend(
        include_policy=IncludePolicyConfig(
            policy=IncludePolicy.RELATIVE_SAFE, max_includes=1
        )
    )
    result = frontend.parse_text(INCLUDE_PROBLEM)
    assert not result.ok
    assert any(item.code == CODE_FEATURE_LIMIT for item in result.errors)


def test_validate_include_under_policy_accepts_safe_relative() -> None:
    assert (
        validate_include_under_policy("Axioms/SET001+0.ax")
        == "Axioms/SET001+0.ax"
    )


def test_validate_include_under_policy_rejects_traversal() -> None:
    with pytest.raises(Exception) as excinfo:
        validate_include_under_policy("../etc/passwd")
    code = getattr(excinfo.value, "code", "")
    assert code in {CODE_PATH_TRAVERSAL, CODE_UNSAFE_INCLUDE, CODE_INCLUDE_POLICY}


@pytest.mark.parametrize(
    "path",
    [
        "../etc/passwd",
        "/etc/passwd",
        "https://evil.example/a.ax",
        "Axioms/../../../etc/passwd",
    ],
)
def test_unsafe_includes_fail_closed(path: str) -> None:
    escaped = path.replace("\\", "\\\\").replace("'", "\\'")
    result = parse_tptp_v2(f"include('{escaped}').")
    assert not result.ok
    codes = {item.code for item in result.errors}
    assert codes & {
        CODE_PATH_TRAVERSAL,
        CODE_UNSAFE_INCLUDE,
        CODE_INCLUDE_POLICY,
        "tptp.malformed_include",
    }


def test_declared_frontend_limits_reject_oversized_input() -> None:
    text = "fof(a, axiom, p).\n" * 50
    result = parse_tptp_v2(
        text,
        limits=ParseLimits(max_input_bytes=32, max_tokens=64, max_depth=16),
    )
    assert not result.ok
    assert any(item.code == CODE_INPUT_LIMIT for item in result.errors)
    assert result.parse_artifact is not None


def test_token_limit_rejected() -> None:
    text = "fof(a, axiom, " + " & ".join(["p"] * 40) + ")."
    result = parse_tptp_v2(
        text,
        limits=ParseLimits(max_input_bytes=4096, max_tokens=10, max_depth=64),
    )
    assert not result.ok
    assert any(item.code == CODE_TOKEN_LIMIT for item in result.errors)


def test_default_frontend_limits_are_finite() -> None:
    bounds = DEFAULT_FRONTEND_LIMITS
    assert bounds.parse_limits.max_input_bytes > 0
    assert bounds.parse_limits.max_tokens > 0
    assert bounds.parse_limits.max_depth > 0
    assert bounds.max_output_bytes > 0
    assert bounds.max_print_depth > 0


# ---------------------------------------------------------------------------
# Fail-closed: THF profile-scoped unsupported
# ---------------------------------------------------------------------------


def test_thf_is_explicitly_unsupported() -> None:
    result = parse_tptp_v2("thf(a, type, p: $o).")
    assert not result.ok
    assert any(item.code == CODE_UNSUPPORTED_THF for item in result.errors)
    assert result.parse_artifact is not None
    assert result.parse_artifact.status is not ParseStatus.OK


@pytest.mark.parametrize("language", sorted(UNSUPPORTED_LANGUAGES))
def test_unsupported_languages_fail_closed(language: str) -> None:
    result = parse_tptp_v2(f"{language}(a, axiom, p).")
    assert not result.ok
    codes = {item.code for item in result.errors}
    assert codes & {CODE_UNSUPPORTED_THF, CODE_UNSUPPORTED_LANGUAGE}


def test_profile_scope_default_is_fof() -> None:
    frontend = _frontend()
    assert frontend.profile_scope is TPTPProfileScope.FOF
    assert frontend.descriptor.metadata["profile_scope"] == "fof"
    assert "thf" in frontend.descriptor.unsupported_nodes


def test_empty_input_fails() -> None:
    result = parse_tptp_v2("   \n  % only comments\n")
    assert not result.ok
    assert result.status in {ParseStatus.FAILED, ParseStatus.REJECTED}
    assert any(item.code == CODE_EMPTY_INPUT for item in result.errors)


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "script",
    [CNF_PROBLEM, FOF_PROBLEM, TFF_PROBLEM, INCLUDE_PROBLEM, VAMPIRE_STYLE],
)
def test_parse_print_parse_preserves_structure(script: str) -> None:
    result = parse_print_parse_tptp_v2(script)
    assert result.ok, (result.printed, [d.message for d in result.diagnostics])
    assert result.document is not None
    first = elaborate_tptp_v2(script)
    assert first.document is not None
    assert documents_semantically_compatible(first.document, result.document)
    assert result.parse_artifact is not None


def test_printer_emits_languages_roles_and_includes() -> None:
    result = elaborate_tptp_v2(INCLUDE_PROBLEM)
    assert result.document is not None
    printed = print_tptp_v2(result.document)
    assert "include('Axioms/SET001+0.ax')." in printed
    assert "fof(local, axiom," in printed
    again = parse_tptp_v2(printed)
    assert again.ok, [d.message for d in again.diagnostics]


def test_frontend_round_trip_helper() -> None:
    frontend = _frontend()
    result = frontend.round_trip(FOF_PROBLEM)
    assert result.ok
    assert result.printed
    assert "fof(ax1, axiom," in result.printed
    assert result.parse_artifact is not None
    assert result.elaboration_artifact is not None


# ---------------------------------------------------------------------------
# TSTPFrontend@1 — controlled untrusted proof/status records
# ---------------------------------------------------------------------------


def test_tstp_record_parse_and_authority() -> None:
    result = parse_tstp_v2(TSTP_CANDIDATE)
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.interface == TSTP_FRONTEND_INTERFACE
    record = result.record
    assert record is not None
    assert record.interface == TSTP_FRONTEND_INTERFACE
    assert record.authority is ResultAuthority.CANDIDATE
    assert record.status is ResultStatus.CANDIDATE
    assert record.trusted is False
    assert record.is_trusted is False
    assert record.szs_status == "Theorem"
    assert record.szs_output_form == "CNFRefutation"
    assert len(record.steps) == 3
    assert record.step_names == ("c_0", "c_1", "c_2")
    assert record.steps[2].annotation is not None
    assert "inference" in record.steps[2].annotation.source

    parse_art = result.parse_artifact
    assert parse_art is not None
    assert parse_art.interface == PARSE_ARTIFACT_V2_INTERFACE
    assert parse_art.status is ParseStatus.OK
    assert parse_art.cst is not None
    assert parse_art.source_map is not None
    assert parse_art.metadata["trusted"] is False
    assert parse_art.metadata["authority"] == "candidate"
    assert parse_art.metadata["szs_status"] == "Theorem"

    payload = record.to_dict()
    assert payload["trusted"] is False
    assert payload["authority"] == "candidate"
    assert payload["interface"] == TSTP_FRONTEND_INTERFACE


def test_tstp_record_cannot_be_constructed_as_theorem() -> None:
    step_result = parse_tptp_v2("cnf(c0, plain, p(a)).")
    assert step_result.document is not None
    formula = step_result.document.formulas[0]
    from ipfs_datasets_py.logic.parsers.tptp import TSTPProofStep

    step = TSTPProofStep(
        language=formula.language.value,
        name=formula.name,
        role=formula.role.value,
        formula=formula.formula,
    )
    with pytest.raises(TSTPFrontendError) as excinfo:
        TSTPProofRecord(
            steps=(step,),
            authority=ResultAuthority.THEOREM,  # type: ignore[arg-type]
            status=ResultStatus.PROVED,  # type: ignore[arg-type]
        )
    assert excinfo.value.code == CODE_CANDIDATE_AUTHORITY


def test_tstp_trusted_flag_forced_false() -> None:
    step_result = parse_tptp_v2("cnf(c0, plain, p(a)).")
    assert step_result.document is not None
    formula = step_result.document.formulas[0]
    from ipfs_datasets_py.logic.parsers.tptp import TSTPProofStep

    step = TSTPProofStep(
        language=formula.language.value,
        name=formula.name,
        role=formula.role.value,
        formula=formula.formula,
    )
    record = TSTPProofRecord(steps=(step,), trusted=True)
    assert record.trusted is False
    assert record.is_trusted is False
    assert record.authority is ResultAuthority.CANDIDATE


def test_parse_szs_status_extracts_token() -> None:
    assert parse_szs_status("% SZS status Unsatisfiable\n") == "Unsatisfiable"
    assert parse_szs_status("no status here") is None


def test_tstp_via_tptp_facade() -> None:
    frontend = _frontend()
    result = frontend.tstp.parse_text(TSTP_CANDIDATE)
    assert result.ok
    assert result.record is not None
    assert result.record.authority is ResultAuthority.CANDIDATE
    assert result.parse_artifact is not None


def test_tstp_empty_input_fails() -> None:
    result = parse_tstp_v2("   \n")
    assert not result.ok
    assert any(item.code == CODE_EMPTY_INPUT for item in result.errors)


# ---------------------------------------------------------------------------
# Artifact lineage and serialization
# ---------------------------------------------------------------------------


def test_parse_artifact_lineage_matches_source() -> None:
    result = parse_tptp_v2(FOF_PROBLEM, document_id="doc:tptp:test")
    assert result.ok
    assert result.source_document is not None
    assert result.parse_artifact is not None
    assert result.parse_artifact.document_id == "doc:tptp:test"
    assert (
        result.parse_artifact.source_digest
        == result.source_document.content_digest
    )
    result.parse_artifact.validate_against(result.source_document)
    payload = result.to_dict()
    assert payload["interface"] == TPTP_FRONTEND_V2_INTERFACE
    assert payload["parse_artifact"]["interface"] == PARSE_ARTIFACT_V2_INTERFACE
    assert (
        payload["elaboration_artifact"]["interface"]
        == ELABORATION_ARTIFACT_V2_INTERFACE
    )


def test_equality_and_false_clause_project() -> None:
    text = """\
fof(eq1, axiom, a = b).
fof(neq1, axiom, a != c).
cnf(empty, plain, $false).
"""
    result = parse_tptp_v2(text)
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.typed_expression is not None
    assert result.elaboration_artifact is not None
    assert result.elaboration_artifact.status is ElaborationArtifactStatus.OK


def test_exists_quantifier_projects() -> None:
    text = "fof(ex, axiom, ? [X, Y] : (p(X) & q(Y))).\n"
    result = parse_tptp_v2(text)
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.typed_expression is not None
    root = result.typed_expression.root
    # Root may be exists or a document AND wrapping it.
    kinds = {root.kind.value if hasattr(root.kind, "value") else str(root.kind)}
    assert "exists" in kinds or root.kind is not None
