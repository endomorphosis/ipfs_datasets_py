"""Unit tests for StatePropertySyntax@1 / ControlledTLAProperty@1 (LFP-025).

Evidence subset:

* variables, init, next, invariant, fairness, stuttering
* bound, source map, TLC, Apalache
* controlled expressions round-trip (parse/print/parse alpha-equivalent)
* full-module constructs are declaration-only or unsupported
* TLC finite-state and Apalache bounded results cannot be promoted to
  unbounded proof
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.parsers.state import (
    CODE_DECLARATION_ONLY,
    CODE_UNSUPPORTED_MODULE,
    CONTROLLED_TLA_PROPERTY_INTERFACE,
    STATE_PROPERTY_SYNTAX_INTERFACE,
    BoundednessKind,
    CheckerEvidenceContract,
    CheckerTool,
    ControlledTLAProperty,
    EvidenceAuthority,
    FiniteBoundContract,
    ModuleConstructDisposition,
    PrintStyle,
    PropertyRole,
    StateParseError,
    StatePropertyParser,
    StatePropertyPrinter,
    StatePropertySyntax,
    apalache_evidence_contract,
    module_construct_disposition,
    parse_print_parse,
    parse_state,
    print_state,
    profile_state_property,
    profile_tla_apalache,
    profile_tla_tlc,
    rewrite_primes_for_lex,
    state_semantic_identity,
    tlc_evidence_contract,
)
from ipfs_datasets_py.logic.syntax_core.algebra import alpha_equivalent
from ipfs_datasets_py.logic.syntax_core.ast import NodeKind
from ipfs_datasets_py.logic.syntax_core.contracts import (
    ParseLimits,
    ParseMode,
    ParseRequest,
    ParseStatus,
    SourceDocument,
    SyntaxContractError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _state() -> object:
    return profile_state_property()


def _tlc() -> object:
    return profile_tla_tlc(max_steps=32)


def _apalache() -> object:
    return profile_tla_apalache(max_steps=8)


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_interface_and_module_identity() -> None:
    assert STATE_PROPERTY_SYNTAX_INTERFACE == "StatePropertySyntax@1"
    assert CONTROLLED_TLA_PROPERTY_INTERFACE == "ControlledTLAProperty@1"
    syntax = StatePropertySyntax(profile_state_property())
    assert syntax.interface == STATE_PROPERTY_SYNTAX_INTERFACE
    assert isinstance(syntax.parser, StatePropertyParser)
    assert isinstance(syntax.printer, StatePropertyPrinter)
    tla = ControlledTLAProperty(profile_tla_tlc())
    assert tla.interface == CONTROLLED_TLA_PROPERTY_INTERFACE


def test_module_construct_disposition_table() -> None:
    assert (
        module_construct_disposition("MODULE")
        is ModuleConstructDisposition.UNSUPPORTED
    )
    assert (
        module_construct_disposition("INSTANCE")
        is ModuleConstructDisposition.UNSUPPORTED
    )
    assert (
        module_construct_disposition("THEOREM")
        is ModuleConstructDisposition.UNSUPPORTED
    )
    assert (
        module_construct_disposition("PROOF")
        is ModuleConstructDisposition.UNSUPPORTED
    )
    assert (
        module_construct_disposition("EXTENDS")
        is ModuleConstructDisposition.DECLARATION_ONLY
    )
    assert (
        module_construct_disposition("VARIABLES")
        is ModuleConstructDisposition.DECLARATION_ONLY
    )
    assert (
        module_construct_disposition("CONSTANTS")
        is ModuleConstructDisposition.DECLARATION_ONLY
    )
    assert (
        module_construct_disposition("always")
        is ModuleConstructDisposition.CONTROLLED
    )


# ---------------------------------------------------------------------------
# Happy-path controlled expressions
# ---------------------------------------------------------------------------


def test_parse_state_predicate_connectives() -> None:
    result = parse_state("pc = idle and ready", profile_state_property())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.kind is NodeKind.AND


def test_parse_primed_next_state() -> None:
    result = parse_state("pc' = busy", profile_state_property())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.extension is not None
    assert result.root.extension.payload["kind"] == "equality"
    left = result.root.extension.children[0]
    assert left.extension is not None
    assert left.extension.payload["kind"] == "prime"
    assert left.extension.payload["variable"] == "pc"


def test_parse_init_style_conjunction() -> None:
    result = parse_state(
        "pc = idle /\\ count = 0",
        profile_state_property(default_role=PropertyRole.INIT),
        print_style=PrintStyle.TLA,
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.kind is NodeKind.AND


def test_parse_invariant_always() -> None:
    result = parse_state(
        "always (count in Domain)",
        profile_state_property(default_role=PropertyRole.INVARIANT),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.extension is not None
    assert result.root.extension.payload["kind"] == "always"


def test_parse_tla_box_diamond() -> None:
    result = parse_state("[]TypeOK", profile_state_property())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.extension is not None
    assert result.root.extension.payload["kind"] == "always"
    ev = parse_state("<>done", profile_state_property())
    assert ev.ok, [d.message for d in ev.diagnostics]
    assert ev.root is not None
    assert ev.root.extension is not None
    assert ev.root.extension.payload["kind"] == "eventually"


def test_parse_stuttering_next() -> None:
    result = parse_state("[Next]_vars", profile_state_property())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.extension is not None
    assert result.root.extension.payload["kind"] == "stuttering"
    assert result.root.extension.payload["variables"] == ["vars"]


def test_parse_spec_with_stuttering_and_fairness() -> None:
    result = parse_state(
        "Init /\\ [][Next]_vars /\\ WF_vars(Next)",
        profile_tla_tlc(),
        print_style=PrintStyle.TLA,
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.kind is NodeKind.AND
    # Source map covers variables / stuttering / fairness.
    kinds = {entry.kind for entry in result.source_map}
    assert "stuttering" in kinds or "variable" in kinds
    assert result.checker_contract is not None
    assert result.checker_contract.tool is CheckerTool.TLC
    assert result.unbounded_proof is False


def test_parse_unchanged() -> None:
    result = parse_state("UNCHANGED <<pc, count>>", profile_state_property())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.extension is not None
    assert result.root.extension.payload["kind"] == "unchanged"
    assert result.root.extension.payload["variables"] == ["pc", "count"]


def test_parse_enabled() -> None:
    result = parse_state("ENABLED Next", profile_state_property())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.extension is not None
    assert result.root.extension.payload["kind"] == "enabled"


def test_parse_weak_and_strong_fairness() -> None:
    weak = parse_state("WF_vars(Next)", profile_tla_tlc())
    assert weak.ok, [d.message for d in weak.diagnostics]
    assert weak.root is not None
    assert weak.root.extension is not None
    assert weak.root.extension.payload["strength"] == "weak"
    strong = parse_state("SF_vars(Inc)", profile_tla_tlc())
    assert strong.ok, [d.message for d in strong.diagnostics]
    assert strong.root is not None
    assert strong.root.extension is not None
    assert strong.root.extension.payload["strength"] == "strong"


def test_apalache_profile_rejects_fairness() -> None:
    result = parse_state("WF_vars(Next)", profile_tla_apalache())
    assert not result.ok
    assert any("fairness" in item.message.lower() for item in result.errors)


def test_logic_parser_protocol_via_parse_request() -> None:
    document = SourceDocument.from_text("doc:req:1", "always safe")
    request = ParseRequest(
        request_id="req:state:1",
        document=document,
        notation_id="canonical_state_property",
        profile_id="state_property_controlled",
        family_id="transition_system",
        mode=ParseMode.STRICT,
        limits=ParseLimits(max_input_bytes=4096, max_tokens=256, max_depth=64),
        metadata={"profile": profile_state_property().to_dict()},
    )
    parser = StatePropertyParser()
    artifact = parser.parse(request)
    assert artifact.status is ParseStatus.OK
    assert artifact.cst is not None
    assert "semantic_identity" in artifact.metadata
    assert artifact.metadata["unbounded_proof"] is False


# ---------------------------------------------------------------------------
# Full-module constructs: declaration-only or unsupported
# ---------------------------------------------------------------------------


def test_module_keyword_is_unsupported() -> None:
    source = "MODULE Foo"
    result = parse_state(source, profile_state_property())
    assert not result.ok
    assert any(item.code == CODE_UNSUPPORTED_MODULE for item in result.errors)
    assert result.module_constructs
    assert (
        result.module_constructs[0].disposition
        is ModuleConstructDisposition.UNSUPPORTED
    )


def test_extends_is_declaration_only() -> None:
    source = "EXTENDS Integers"
    result = parse_state(source, profile_state_property())
    assert not result.ok
    assert any(item.code == CODE_DECLARATION_ONLY for item in result.errors)
    assert result.module_constructs
    assert (
        result.module_constructs[0].disposition
        is ModuleConstructDisposition.DECLARATION_ONLY
    )


def test_variables_declaration_is_declaration_only() -> None:
    result = parse_state("VARIABLES pc, count", profile_state_property())
    assert not result.ok
    assert any(item.code == CODE_DECLARATION_ONLY for item in result.errors)


def test_theorem_and_proof_are_unsupported() -> None:
    for source in ("THEOREM Safe", "PROOF", "INSTANCE Other"):
        result = parse_state(source, profile_state_property())
        assert not result.ok, source
        assert any(
            item.code == CODE_UNSUPPORTED_MODULE for item in result.errors
        ), source


def test_controlled_expression_is_not_full_module() -> None:
    """Controlled fragments parse; full modules never silently succeed."""

    ok = parse_state("Init /\\ [][Next]_vars", profile_tla_tlc())
    assert ok.ok
    bad = parse_state("---- MODULE M ----", profile_tla_tlc())
    # Leading dashes may fail as unexpected tokens or module construct.
    assert not bad.ok


# ---------------------------------------------------------------------------
# TLC / Apalache cannot promote to unbounded proof
# ---------------------------------------------------------------------------


def test_tlc_contract_is_finite_bounded_only() -> None:
    contract = tlc_evidence_contract(max_steps=16, max_states=1000)
    assert contract.tool is CheckerTool.TLC
    assert contract.authority is EvidenceAuthority.BOUNDED
    assert contract.bound.boundedness is BoundednessKind.FINITE_STATE
    assert contract.unbounded_proof is False
    assert contract.may_promote_to_unbounded_proof is False
    with pytest.raises(SyntaxContractError, match="cannot be promoted"):
        contract.promote_to_unbounded_proof()


def test_apalache_contract_is_step_bounded_only() -> None:
    contract = apalache_evidence_contract(max_steps=5)
    assert contract.tool is CheckerTool.APALACHE
    assert contract.bound.boundedness is BoundednessKind.STEP_BOUNDED
    assert contract.unbounded_proof is False
    with pytest.raises(SyntaxContractError, match="cannot be promoted"):
        contract.promote_to_unbounded_proof()


def test_finite_bound_rejects_unboundedness() -> None:
    with pytest.raises(SyntaxContractError, match="unbounded"):
        FiniteBoundContract(boundedness=BoundednessKind.UNBOUNDED)


def test_checker_contract_rejects_non_bounded_authority_for_tlc() -> None:
    with pytest.raises(SyntaxContractError, match="bounded authority"):
        CheckerEvidenceContract(
            tool=CheckerTool.TLC,
            bound=FiniteBoundContract(max_steps=8),
            authority=EvidenceAuthority.NONE,
        )


def test_controlled_tla_promote_always_fails() -> None:
    tla = ControlledTLAProperty(profile_tla_tlc())
    result = tla.parse_text("[]TypeOK")
    assert result.ok
    with pytest.raises(SyntaxContractError, match="cannot be promoted"):
        tla.promote_to_unbounded_proof(result)
    with pytest.raises(SyntaxContractError, match="cannot be promoted"):
        tla.promote_to_unbounded_proof()


def test_lowering_receipt_records_bound_and_forbids_promotion() -> None:
    tla = ControlledTLAProperty(profile_tla_apalache(max_steps=7))
    result = tla.parse_text("always (pc = idle)")
    assert result.ok, [d.message for d in result.diagnostics]
    receipt = tla.lowering_receipt(result)
    assert receipt["unbounded_proof"] is False
    assert receipt["may_promote_to_unbounded_proof"] is False
    assert receipt["bound"]["max_steps"] == 7
    assert receipt["bound"]["boundedness"] == "step_bounded"
    assert "source_map" in receipt
    assert "variables" in receipt


def test_tlc_profile_embeds_checker_in_semantic_identity() -> None:
    profile = profile_tla_tlc(max_steps=4)
    result = parse_state("always safe", profile)
    assert result.ok and result.root is not None
    identity = state_semantic_identity(result.root, profile)
    assert identity["unbounded_proof"] is False
    assert identity["profile"]["checker"]["tool"] == "tlc"
    assert identity["profile"]["checker"]["unbounded_proof"] is False
    assert result.root.extension is not None
    assert result.root.extension.payload["checker"]["unbounded_proof"] is False


# ---------------------------------------------------------------------------
# Parse / print / parse alpha-equivalence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "profile_factory", "style"),
    [
        ("true", _state, PrintStyle.ASCII),
        ("false", _state, PrintStyle.ASCII),
        ("not p", _state, PrintStyle.ASCII),
        ("p and q", _state, PrintStyle.ASCII),
        ("p or q", _state, PrintStyle.ASCII),
        ("p -> q", _state, PrintStyle.ASCII),
        ("p iff q", _state, PrintStyle.ASCII),
        ("p -> q -> r", _state, PrintStyle.ASCII),
        ("pc = idle", _state, PrintStyle.ASCII),
        ("pc' = busy", _state, PrintStyle.ASCII),
        ("count in Domain", _state, PrintStyle.ASCII),
        ("always safe", _state, PrintStyle.ASCII),
        ("eventually done", _state, PrintStyle.ASCII),
        ("[]TypeOK", _state, PrintStyle.ASCII),
        ("<>done", _state, PrintStyle.ASCII),
        ("[Next]_vars", _state, PrintStyle.ASCII),
        ("UNCHANGED pc", _state, PrintStyle.ASCII),
        ("UNCHANGED <<pc, count>>", _state, PrintStyle.ASCII),
        ("ENABLED Next", _state, PrintStyle.ASCII),
        ("WF_vars(Next)", _tlc, PrintStyle.ASCII),
        ("SF_vars(Inc)", _tlc, PrintStyle.ASCII),
        ("Init /\\ [][Next]_vars", _tlc, PrintStyle.TLA),
        ("pc = idle /\\ count = 0", _state, PrintStyle.TLA),
        ("not (p or always q)", _state, PrintStyle.ASCII),
        ("always (p -> eventually q)", _state, PrintStyle.ASCII),
    ],
)
def test_parse_print_parse_is_alpha_equivalent(
    source: str, profile_factory, style: str
) -> None:
    profile = profile_factory()
    first = parse_state(source, profile, print_style=style)
    assert first.ok, (source, [d.message for d in first.diagnostics])
    assert first.root is not None
    printed = print_state(first.root, style=style)
    second = parse_state(printed, profile, document_id="doc:rt", print_style=style)
    assert second.ok, (source, printed, [d.message for d in second.diagnostics])
    assert second.root is not None
    assert alpha_equivalent(first.root, second.root), (source, printed)


def test_parse_print_parse_helper() -> None:
    result = parse_print_parse(
        "always (pc = idle -> eventually done)",
        profile_state_property(),
    )
    assert result.ok
    assert result.printed


def test_prime_rewrite_for_lex() -> None:
    assert " @'" in rewrite_primes_for_lex("pc' = busy")
    assert rewrite_primes_for_lex("pc = idle") == "pc = idle"


def test_tla_print_style_round_trip() -> None:
    profile = profile_tla_tlc()
    first = parse_state("[]TypeOK /\\ WF_vars(Next)", profile, print_style=PrintStyle.TLA)
    assert first.ok and first.root is not None
    printed = print_state(first.root, style=PrintStyle.TLA)
    assert "[]" in printed or "always" in printed
    second = parse_state(printed, profile, document_id="doc:tla-rt")
    assert second.ok and second.root is not None
    assert alpha_equivalent(first.root, second.root)


def test_source_map_entries_present() -> None:
    result = parse_state("pc' = busy and UNCHANGED count", profile_state_property())
    assert result.ok
    assert result.source_map
    kinds = {entry.kind for entry in result.source_map}
    assert "prime" in kinds or "equality" in kinds


# ---------------------------------------------------------------------------
# Raising API / missing profile
# ---------------------------------------------------------------------------


def test_parse_text_or_raise() -> None:
    syntax = StatePropertySyntax(profile_state_property())
    expr = syntax.parse_text_or_raise("always p")
    assert expr.root.kind is NodeKind.EXTENSION

    with pytest.raises(StateParseError) as caught:
        syntax.parse_text_or_raise("MODULE Bad")
    assert caught.value.diagnostics


def test_missing_profile_rejects() -> None:
    document = SourceDocument.from_text("doc:noprof", "always p")
    request = ParseRequest(
        request_id="req:noprof",
        document=document,
        notation_id="canonical_state_property",
        profile_id="state_property_controlled",
        family_id="transition_system",
        mode=ParseMode.STRICT,
        limits=ParseLimits(),
        metadata={},
    )
    parser = StatePropertyParser()
    artifact = parser.parse(request)
    assert artifact.status is ParseStatus.REJECTED


def test_controlled_tla_requires_checker_contract() -> None:
    with pytest.raises(SyntaxContractError, match="checker evidence"):
        ControlledTLAProperty(profile_state_property())


def test_profile_dict_round_trip() -> None:
    profile = profile_tla_tlc(max_steps=9, max_states=100)
    restored = type(profile).from_dict(profile.to_dict())
    assert restored.profile_id == profile.profile_id
    assert restored.checker is not None
    assert restored.checker.bound.max_steps == 9
    assert restored.checker.unbounded_proof is False
