"""Unit tests for FLogicFrontend@1 and ErgoAIControlledSource@1 (LFP-021).

Evidence subset:

* frame terms, inheritance, signatures, methods, rules, queries
* source maps / diagnostics
* deterministic normalization and parse/print/parse
* unsupported ErgoAI constructs retained and diagnosed
* execution remains lazy; advisor/candidate authority is explicit
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.backends.toolchain_roles import (
    ToolRole,
    ToolchainAuthorityCeiling,
    role_can_satisfy_certified_authority,
)
from ipfs_datasets_py.logic.parsers.flogic import (
    CODE_AUTHORITY,
    CODE_EMPTY_INPUT,
    CODE_INPUT_LIMIT,
    CODE_LAZY_EXECUTION,
    CODE_TOKEN_LIMIT,
    CODE_UNSUPPORTED_CONSTRUCT,
    ERGOAI_CONTROLLED_SOURCE_INTERFACE,
    FLOGIC_FAMILY_ID,
    FLOGIC_FRONTEND_INTERFACE,
    FLOGIC_NOTATION_ID,
    FLOGIC_PROFILE_ID,
    FLOGIC_PROVIDER_ID,
    ErgoAIAuthorityError,
    ErgoAIControlledSource,
    FLogicError,
    FLogicFrontend,
    FLogicItemRole,
    FLogicParser,
    FLogicPrinter,
    FLogicSpecKind,
    FLogicStatementKind,
    FLogicTermKind,
    controlled_source_from_text,
    documents_semantically_compatible,
    elaborate_flogic,
    normalize_flogic,
    parse_flogic,
    parse_print_parse_flogic,
    print_flogic,
    tokenize_flogic,
)
from ipfs_datasets_py.logic.syntax_core.contracts import ParseLimits, ParseStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _frontend() -> FLogicFrontend:
    return FLogicFrontend()


SAMPLE_ONTOLOGY = """\
% Animals ontology
Animal.
Dog :: Animal.
Cat :: Animal.
Person[name => string, age => integer, friends =>> Person].
rex[name -> "Rex", age -> 5] : Dog.
whiskers[name -> "Whiskers"] : Cat.
proj1[member ->> {alice, bob}] : Project.
?X[mammal -> true] :- ?X : Animal.
?- ?X : Dog.
"""

FRAME_UNORDERED = """\
rex[age -> 5, name -> "Rex", tags ->> {b, a}] : Dog.
"""

FRAME_ORDERED_EQUIV = """\
rex[name -> "Rex", age -> 5, tags ->> {a, b}] : Dog.
"""


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_interface_and_module_identity() -> None:
    assert FLOGIC_FRONTEND_INTERFACE == "FLogicFrontend@1"
    assert ERGOAI_CONTROLLED_SOURCE_INTERFACE == "ErgoAIControlledSource@1"
    assert FLOGIC_NOTATION_ID == "flogic"
    assert FLOGIC_PROFILE_ID == "frame_core"
    assert FLOGIC_FAMILY_ID == "frame_logic"
    assert FLOGIC_PROVIDER_ID == "ergoai"
    frontend = _frontend()
    assert frontend.interface == FLOGIC_FRONTEND_INTERFACE
    assert isinstance(frontend.parser, FLogicParser)
    assert isinstance(frontend.printer, FLogicPrinter)
    assert frontend.authority is ResultAuthority.CANDIDATE
    assert frontend.role is ToolRole.ADVISOR
    assert frontend.authority_ceiling is ToolchainAuthorityCeiling.ADVISORY
    assert not role_can_satisfy_certified_authority(
        frontend.role, frontend.authority_ceiling
    )


# ---------------------------------------------------------------------------
# Happy-path: frames, classes, inheritance, signatures, rules, queries
# ---------------------------------------------------------------------------


def test_parse_class_inheritance_and_signatures() -> None:
    result = parse_flogic(
        "Dog :: Animal.\nPerson[name => string, friends =>> Person].\n"
    )
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    assert len(doc.facts) == 2
    inherit = doc.facts[0]
    assert inherit.role is FLogicItemRole.INHERITANCE
    assert inherit.head is not None
    assert inherit.head.object.name == "Dog"
    assert inherit.head.subclass_of is not None
    assert inherit.head.subclass_of.name == "Animal"
    sig = doc.facts[1]
    assert sig.role is FLogicItemRole.SIGNATURE
    assert sig.head is not None
    kinds = {spec.kind for spec in sig.head.specs}
    assert FLogicSpecKind.SCALAR_SIGNATURE in kinds
    assert FLogicSpecKind.SET_SIGNATURE in kinds
    assert "Person" in doc.class_names
    assert "name" in doc.method_names
    assert "friends" in doc.method_names


def test_parse_frame_membership_and_set_methods() -> None:
    result = parse_flogic(
        'rex[name -> "Rex", age -> 5] : Dog.\n'
        "proj1[member ->> {alice, bob}] : Project.\n"
    )
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    assert "rex" in doc.frame_object_ids
    assert "proj1" in doc.frame_object_ids
    frame = doc.facts[0]
    assert frame.role is FLogicItemRole.FRAME
    assert frame.head is not None
    assert frame.head.isa is not None
    assert frame.head.isa.name == "Dog"
    specs = {s.method_name: s for s in frame.head.specs}
    assert specs["name"].kind is FLogicSpecKind.SCALAR_VALUE
    assert specs["name"].values[0].kind is FLogicTermKind.STRING
    assert specs["name"].values[0].name == "Rex"
    assert specs["age"].values[0].kind is FLogicTermKind.NUMBER
    set_frame = doc.facts[1]
    assert set_frame.head is not None
    member = next(s for s in set_frame.head.specs if s.method_name == "member")
    assert member.kind is FLogicSpecKind.SET_VALUE
    assert {v.name for v in member.values} == {"alice", "bob"}


def test_parse_rule_and_query() -> None:
    result = parse_flogic(
        "?X[mammal -> true] :- ?X : Animal, warm_blooded(?X).\n"
        "?- ?X : Dog, ?X[name -> ?N].\n"
    )
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    assert len(doc.rules) == 1
    assert len(doc.queries) == 1
    rule = doc.rules[0]
    assert rule.role is FLogicItemRole.RULE
    assert rule.head is not None
    assert rule.head.object.kind is FLogicTermKind.VARIABLE
    assert rule.head.object.name == "?X"
    assert len(rule.body) == 2
    assert rule.body[0].isa is not None
    assert rule.body[0].isa.name == "Animal"
    assert rule.body[1].object.kind is FLogicTermKind.APPLICATION
    query = doc.queries[0]
    assert query.role is FLogicItemRole.QUERY
    assert query.head is not None
    assert query.head.object.name == "?X"
    assert len(query.body) == 1


def test_parse_simple_atom_fact() -> None:
    result = parse_flogic("happy(rex).\n")
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    fact = doc.facts[0]
    assert fact.role is FLogicItemRole.ATOM
    assert fact.head is not None
    assert fact.head.object.kind is FLogicTermKind.APPLICATION
    assert fact.head.object.name == "happy"
    assert fact.head.object.arguments[0].name == "rex"


def test_parse_full_ontology_evidence_subset() -> None:
    result = parse_flogic(SAMPLE_ONTOLOGY)
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    roles = set(doc.roles)
    assert "inheritance" in roles
    assert "signature" in roles
    assert "frame" in roles
    assert "rule" in roles
    assert "query" in roles
    assert doc.queries
    assert doc.rules
    assert "rex" in doc.frame_object_ids
    assert "Dog" in doc.class_names or "Animal" in doc.class_names


# ---------------------------------------------------------------------------
# Deterministic normalization and round-trip
# ---------------------------------------------------------------------------


def test_normalization_sorts_methods_and_set_values() -> None:
    result = parse_flogic(FRAME_UNORDERED)
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    normalized = normalize_flogic(doc)
    again = normalize_flogic(normalized)
    assert normalized.structural_key() == again.structural_key()
    frame = normalized.facts[0]
    assert frame.head is not None
    method_names = [s.method_name for s in frame.head.specs]
    assert method_names == sorted(method_names)
    tags = next(s for s in frame.head.specs if s.method_name == "tags")
    assert [v.name for v in tags.values] == ["a", "b"]


def test_normalization_equates_reordered_frames() -> None:
    left = elaborate_flogic(FRAME_UNORDERED)
    right = elaborate_flogic(FRAME_ORDERED_EQUIV)
    assert documents_semantically_compatible(left, right)


def test_parse_print_parse_preserves_structure() -> None:
    result = parse_print_parse_flogic(SAMPLE_ONTOLOGY)
    assert result.ok, (result.printed, [d.message for d in result.diagnostics])
    assert result.document is not None
    first = elaborate_flogic(SAMPLE_ONTOLOGY)
    assert documents_semantically_compatible(first, result.document)
    assert result.printed
    assert "Dog :: Animal." in result.printed
    assert "?- " in result.printed


def test_printer_emits_frames_signatures_rules_queries() -> None:
    doc = elaborate_flogic(SAMPLE_ONTOLOGY)
    printed = print_flogic(doc)
    assert "interface: FLogicFrontend@1" in printed
    assert "authority: advisor/candidate" in printed
    assert "Person[" in printed
    assert "=>" in printed
    assert "->>" in printed
    assert ":-" in printed
    again = parse_flogic(printed)
    assert again.ok, [d.message for d in again.diagnostics]


def test_frontend_round_trip_helper() -> None:
    frontend = _frontend()
    result = frontend.round_trip('rex[name -> "Rex"] : Dog.\n')
    assert result.ok
    assert result.printed
    assert "rex[" in result.printed


# ---------------------------------------------------------------------------
# Unsupported ErgoAI constructs: retained + diagnosed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,fragment",
    [
        ("p@mod.\n", "@"),
        ("!- cut_goal.\n", "!"),
        (":- use_module(lists).\n", "use_module"),
        (":- export p/1.\n", "export"),
        ("avg{X | p(X)}.\n", "avg"),
        ("p ~> q.\n", "~>"),
        ("\\neg p.\n", "\\neg"),
        ("%- transaction.\n", "%-"),
        ("${reify}.\n", "${"),
    ],
)
def test_unsupported_constructs_retained_and_diagnosed(
    text: str, fragment: str
) -> None:
    result = parse_flogic(text)
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    assert doc.has_unsupported
    assert len(doc.unsupported) >= 1
    unsupported = doc.unsupported[0]
    assert unsupported.kind is FLogicStatementKind.UNSUPPORTED
    assert unsupported.role is FLogicItemRole.UNSUPPORTED
    assert unsupported.raw
    assert any(item.code == CODE_UNSUPPORTED_CONSTRUCT for item in result.warnings)
    assert any(fragment in item.message or fragment in unsupported.raw for item in result.diagnostics)


def test_unsupported_mixed_with_supported_preserves_both() -> None:
    text = (
        "Dog :: Animal.\n"
        ":- use_module(lists).\n"
        'rex[name -> "Rex"] : Dog.\n'
        "?- ?X : Dog.\n"
    )
    result = parse_flogic(text)
    assert result.ok, [d.message for d in result.diagnostics]
    doc = result.document
    assert doc is not None
    assert len(doc.unsupported) == 1
    assert any(s.role is FLogicItemRole.INHERITANCE for s in doc.facts)
    assert any(s.role is FLogicItemRole.FRAME for s in doc.facts)
    assert doc.queries
    # Round-trip retains unsupported raw text.
    printed = print_flogic(doc)
    assert "use_module" in printed
    again = parse_flogic(printed)
    assert again.ok
    assert again.document is not None
    assert again.document.has_unsupported


# ---------------------------------------------------------------------------
# Fail-closed: empty input, limits
# ---------------------------------------------------------------------------


def test_empty_input_fails() -> None:
    result = parse_flogic("   \n  % only comments\n")
    assert not result.ok
    assert result.status in {ParseStatus.FAILED, ParseStatus.REJECTED}
    assert any(item.code == CODE_EMPTY_INPUT for item in result.errors)


def test_input_byte_limit_rejected() -> None:
    text = "Dog :: Animal.\n" * 20
    result = parse_flogic(
        text, limits=ParseLimits(max_input_bytes=32, max_tokens=64, max_depth=16)
    )
    assert not result.ok
    assert any(item.code == CODE_INPUT_LIMIT for item in result.errors)


def test_token_limit_rejected() -> None:
    text = "a" + "".join(f", b{i}" for i in range(40)) + "."
    # Use a frame with many methods to generate tokens.
    text = "obj[" + ", ".join(f"m{i} -> v{i}" for i in range(30)) + "]."
    result = parse_flogic(
        text, limits=ParseLimits(max_input_bytes=4096, max_tokens=10, max_depth=64)
    )
    assert not result.ok
    assert any(item.code == CODE_TOKEN_LIMIT for item in result.errors)


def test_malformed_frame_fails() -> None:
    result = parse_flogic("rex[name .\n")
    assert not result.ok
    assert result.errors


# ---------------------------------------------------------------------------
# Authority: advisor/candidate explicit; never theorem; lazy execution
# ---------------------------------------------------------------------------


def test_controlled_source_authority_is_advisor_candidate() -> None:
    source = controlled_source_from_text('rex[name -> "Rex"] : Dog.\n')
    assert source.interface == ERGOAI_CONTROLLED_SOURCE_INTERFACE
    assert source.authority is ResultAuthority.CANDIDATE
    assert source.status is ResultStatus.CANDIDATE
    assert source.role is ToolRole.ADVISOR
    assert source.authority_ceiling is ToolchainAuthorityCeiling.ADVISORY
    assert source.trusted is False
    assert source.is_trusted is False
    assert source.can_certify is False
    assert not role_can_satisfy_certified_authority(
        source.role, source.authority_ceiling
    )
    payload = source.to_dict()
    assert payload["trusted"] is False
    assert payload["authority"] == "candidate"
    assert payload["role"] == "advisor"
    assert payload["can_certify"] is False
    assert payload["interface"] == ERGOAI_CONTROLLED_SOURCE_INTERFACE


def test_controlled_source_rejects_theorem_authority() -> None:
    doc = elaborate_flogic("Dog :: Animal.\n")
    with pytest.raises(ErgoAIAuthorityError) as excinfo:
        ErgoAIControlledSource(
            document=doc,
            authority=ResultAuthority.THEOREM,  # type: ignore[arg-type]
            status=ResultStatus.PROVED,  # type: ignore[arg-type]
        )
    assert excinfo.value.code == CODE_AUTHORITY


def test_controlled_source_rejects_authority_role() -> None:
    doc = elaborate_flogic("Dog :: Animal.\n")
    with pytest.raises(ErgoAIAuthorityError) as excinfo:
        ErgoAIControlledSource(
            document=doc,
            role=ToolRole.AUTHORITY,  # type: ignore[arg-type]
        )
    assert excinfo.value.code == CODE_AUTHORITY


def test_frontend_and_source_never_execute_ergoai() -> None:
    frontend = _frontend()
    with pytest.raises(FLogicError) as excinfo:
        frontend.execute("?- ?X : Dog.")
    assert excinfo.value.code == CODE_LAZY_EXECUTION

    source = frontend.as_controlled_source(elaborate_flogic("Dog :: Animal.\n"))
    with pytest.raises(FLogicError) as excinfo2:
        source.execute()
    assert excinfo2.value.code == CODE_LAZY_EXECUTION


def test_parser_module_does_not_import_ergoai_runtime() -> None:
    """Importing the frontend must not load the ErgoAI wrapper package."""

    import ipfs_datasets_py.logic.parsers.flogic as flogic_mod
    import sys

    # The parser module itself must not pull the executable wrapper.
    assert "ipfs_datasets_py.logic.flogic.ergoai_wrapper" not in sys.modules
    # And the module source must not reference an ErgoAI install/import path.
    source = open(flogic_mod.__file__, encoding="utf-8").read()
    assert "ergoai_wrapper" not in source
    assert "runErgo" not in source
    assert "subprocess" not in source


def test_tokenize_variables() -> None:
    tokens, diags = tokenize_flogic("?- ?X : Dog.")
    assert not diags
    kinds = [t.kind.value for t in tokens if t.kind.value != "eof"]
    assert "query" in kinds
    assert "variable" in kinds
    assert any(t.value == "?X" for t in tokens)


def test_document_metadata_records_lazy_advisor_lane() -> None:
    doc = elaborate_flogic("Dog :: Animal.\n")
    meta = doc.metadata.to_dict()
    assert meta.get("lazy") is True
    assert meta.get("role") == "advisor"
    assert meta.get("provider_id") == "ergoai"
    assert meta.get("authority_ceiling") == "advisory"


def test_normalize_is_idempotent_on_document_api() -> None:
    doc = elaborate_flogic(FRAME_UNORDERED)
    once = doc.normalized()
    twice = once.normalized()
    assert once.structural_key() == twice.structural_key()
    assert documents_semantically_compatible(once, twice)
