"""Unit tests for ModalSyntax@1 / NormativeProfile@1 / CognitiveProfile@1 (LFP-023).

Evidence subset:

* profile-free overloaded symbols fail
* parse/print preserves binding and source maps
* unsupported dyadic or defeasible constructs retain typed diagnostics and
  cannot masquerade as classical equivalence
* K/D/T/S4/S5, deontic O/P/F, epistemic/doxastic/intention modalities
* operator precedence, agent index, norm polarity, frame axioms
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.parsers.modal import (
    CODE_AGENT_REQUIRED,
    CODE_OPERATOR_FORBIDDEN,
    CODE_OVERLOADED_SYMBOL,
    CODE_PROFILE_REQUIRED,
    CODE_UNSUPPORTED_DEFEASIBLE,
    CODE_UNSUPPORTED_DYADIC,
    COGNITIVE_PROFILE_INTERFACE,
    MODAL_SYNTAX_INTERFACE,
    NORMATIVE_PROFILE_INTERFACE,
    CognitiveAttitudeKind,
    CognitiveProfile,
    KripkeFrameKind,
    ModalFamilyKind,
    ModalParser,
    ModalPrinter,
    ModalSemanticsProfile,
    ModalSyntax,
    NormFormKind,
    NormativeProfile,
    PermissionStrengthKind,
    modal_semantic_identity,
    parse_modal,
    parse_print_parse,
    print_modal,
    profile_d,
    profile_deontic,
    profile_doxastic,
    profile_epistemic,
    profile_intention,
    profile_k,
    profile_s4,
    profile_s5,
    profile_t,
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


def _k() -> ModalSemanticsProfile:
    return profile_k()


def _d() -> ModalSemanticsProfile:
    return profile_d()


def _t() -> ModalSemanticsProfile:
    return profile_t()


def _s4() -> ModalSemanticsProfile:
    return profile_s4()


def _s5() -> ModalSemanticsProfile:
    return profile_s5()


def _deontic() -> ModalSemanticsProfile:
    return profile_deontic()


def _deontic_letters() -> ModalSemanticsProfile:
    return profile_deontic(admit_classic_letters=True)


def _epistemic() -> ModalSemanticsProfile:
    return profile_epistemic()


def _doxastic() -> ModalSemanticsProfile:
    return profile_doxastic()


def _intention() -> ModalSemanticsProfile:
    return profile_intention()


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_interface_and_module_identity() -> None:
    assert MODAL_SYNTAX_INTERFACE == "ModalSyntax@1"
    assert NORMATIVE_PROFILE_INTERFACE == "NormativeProfile@1"
    assert COGNITIVE_PROFILE_INTERFACE == "CognitiveProfile@1"
    syntax = ModalSyntax(_k())
    assert syntax.interface == MODAL_SYNTAX_INTERFACE
    assert isinstance(syntax.parser, ModalParser)
    assert isinstance(syntax.printer, ModalPrinter)


def test_normative_profile_rejects_dyadic_and_defeasible_flags() -> None:
    with pytest.raises(SyntaxContractError, match="dyadic"):
        NormativeProfile(
            profile_id="bad",
            form=NormFormKind.DYADIC,
        )
    with pytest.raises(SyntaxContractError, match="dyadic"):
        NormativeProfile(
            profile_id="bad",
            form=NormFormKind.MONADIC,
            allow_dyadic=True,
        )
    with pytest.raises(SyntaxContractError, match="defeasible"):
        NormativeProfile(
            profile_id="bad",
            form=NormFormKind.MONADIC,
            allow_defeasible=True,
        )
    with pytest.raises(SyntaxContractError, match="defeasible|priority|exception"):
        NormativeProfile(
            profile_id="bad",
            form=NormFormKind.MONADIC,
            priorities=True,
        )


def test_modal_semantics_profile_rejects_contradictions() -> None:
    with pytest.raises(SyntaxContractError, match="frame"):
        ModalSemanticsProfile(
            profile_id="bad_k",
            family=ModalFamilyKind.KRIPKE,
            frame=None,
        )
    with pytest.raises(SyntaxContractError, match="NormativeProfile"):
        ModalSemanticsProfile(
            profile_id="bad_d",
            family=ModalFamilyKind.DEONTIC,
        )
    with pytest.raises(SyntaxContractError, match="CognitiveProfile"):
        ModalSemanticsProfile(
            profile_id="bad_e",
            family=ModalFamilyKind.EPISTEMIC,
        )
    with pytest.raises(SyntaxContractError, match="attitude"):
        ModalSemanticsProfile(
            profile_id="bad_mix",
            family=ModalFamilyKind.EPISTEMIC,
            cognitive=CognitiveProfile(
                profile_id="c",
                attitude=CognitiveAttitudeKind.DOXASTIC,
            ),
        )


def test_frame_axioms_for_k_through_s5() -> None:
    assert profile_k().frame_axioms == {
        "serial": False,
        "reflexive": False,
        "transitive": False,
        "euclidean": False,
        "symmetric": False,
    }
    assert profile_d().frame_axioms["serial"] is True
    assert profile_t().frame_axioms["reflexive"] is True
    assert profile_s4().frame_axioms["transitive"] is True
    s5 = profile_s5().frame_axioms
    assert s5 is not None
    assert s5["euclidean"] is True
    assert s5["symmetric"] is True


# ---------------------------------------------------------------------------
# Happy-path parsing across families
# ---------------------------------------------------------------------------


def test_parse_kripke_box_diamond() -> None:
    result = parse_modal("box (p -> diamond q)", _k())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.kind is NodeKind.EXTENSION
    assert result.root.extension is not None
    assert result.root.extension.payload["kind"] == "box"
    assert result.root.extension.payload["frame"] == "k"
    assert result.root.extension.payload["family"] == "kripke"


def test_parse_unicode_box_diamond() -> None:
    result = parse_modal("□ (p -> ◇ q)", _s5())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.extension is not None
    assert result.root.extension.payload["frame"] == "s5"


def test_parse_bracket_box_diamond_under_kripke() -> None:
    result = parse_modal("[] p", _k())
    assert result.ok, [d.message for d in result.diagnostics]
    result2 = parse_modal("<> q", _k())
    assert result2.ok, [d.message for d in result2.diagnostics]


def test_parse_s4_and_s5_frame_in_payload() -> None:
    s4 = parse_modal("box p", _s4())
    s5 = parse_modal("box p", _s5())
    assert s4.ok and s5.ok
    assert s4.root is not None and s5.root is not None
    assert s4.root.extension is not None and s5.root.extension is not None
    assert s4.root.extension.payload["frame"] == "s4"
    assert s5.root.extension.payload["frame"] == "s5"
    assert s4.root.extension.payload["frame_axioms"]["transitive"] is True
    assert s5.root.extension.payload["frame_axioms"]["euclidean"] is True
    assert not alpha_equivalent(s4.root, s5.root)


def test_parse_deontic_monadic_words() -> None:
    result = parse_modal(
        "obligated (p -> permitted q) and forbidden r",
        _deontic(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.profile is not None
    assert result.profile.family is ModalFamilyKind.DEONTIC
    assert result.profile.normative is not None
    assert result.profile.normative.form is NormFormKind.MONADIC
    assert result.profile.normative.permission is PermissionStrengthKind.STRONG


def test_parse_deontic_classic_letters_when_admitted() -> None:
    result = parse_modal("O (p -> P q)", _deontic_letters())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.extension is not None
    assert result.root.extension.payload["kind"] == "obligation"
    assert result.root.extension.payload["norm_form"] == "monadic"


def test_parse_epistemic_with_agent() -> None:
    result = parse_modal("knows[alice] p", _epistemic())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.extension is not None
    assert result.root.extension.payload["kind"] == "knows"
    assert result.root.extension.payload["agent"] == "alice"
    assert result.root.extension.payload["attitude"] == "epistemic"


def test_parse_doxastic_with_agent() -> None:
    result = parse_modal("believes[bob] (p or q)", _doxastic())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.extension is not None
    assert result.root.extension.payload["kind"] == "believes"
    assert result.root.extension.payload["agent"] == "bob"


def test_parse_intention_with_agent() -> None:
    result = parse_modal("intends[carol] p", _intention())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.extension is not None
    assert result.root.extension.payload["kind"] == "intends"
    assert result.root.extension.payload["agent"] == "carol"
    assert result.root.extension.payload["family"] == "intention_agency"


def test_epistemic_requires_agent() -> None:
    result = parse_modal("knows p", _epistemic())
    assert not result.ok
    assert any(item.code == CODE_AGENT_REQUIRED for item in result.errors)


def test_classic_cognitive_letters_when_admitted() -> None:
    profile = profile_epistemic(admit_classic_letters=True)
    result = parse_modal("K[alice] p", profile)
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.extension is not None
    assert result.root.extension.payload["kind"] == "knows"


def test_parse_connectives_and_implication_right_assoc() -> None:
    result = parse_modal("p -> q -> r", _k())
    assert result.ok and result.root is not None
    assert result.root.kind is NodeKind.IMPLIES
    assert result.root.arguments[1].kind is NodeKind.IMPLIES


def test_parse_unicode_connectives() -> None:
    result = parse_modal("box (p → q ∧ ¬r)", _k())
    assert result.ok, [d.message for d in result.diagnostics]


def test_logic_parser_protocol_via_parse_request() -> None:
    document = SourceDocument.from_text("doc:req:1", "box p")
    request = ParseRequest(
        request_id="req:modal:1",
        document=document,
        notation_id="canonical_modal",
        profile_id="kripke_k",
        family_id="modal",
        mode=ParseMode.STRICT,
        limits=ParseLimits(max_input_bytes=4096, max_tokens=256, max_depth=64),
        metadata={"profile": _k().to_dict()},
    )
    parser = ModalParser()
    artifact = parser.parse(request)
    assert artifact.status is ParseStatus.OK
    assert artifact.cst is not None
    assert "semantic_identity" in artifact.metadata
    artifact.validate_against(document, limits=request.limits)


# ---------------------------------------------------------------------------
# Profile-free overloaded symbols fail
# ---------------------------------------------------------------------------


def test_profile_free_parse_fails() -> None:
    parser = ModalParser()  # no profile
    document = SourceDocument.from_text("doc:pf", "box p")
    result = parser.parse_document(document)
    assert not result.ok
    assert any(item.code == CODE_PROFILE_REQUIRED for item in result.errors)


def test_overloaded_o_without_deontic_profile_fails() -> None:
    source = "O p"
    result = parse_modal(source, _k())
    assert not result.ok
    assert any(item.code == CODE_OVERLOADED_SYMBOL for item in result.errors)
    diag = next(item for item in result.errors if item.code == CODE_OVERLOADED_SYMBOL)
    assert diag.range is not None
    document = SourceDocument.from_text("doc:o", source)
    sliced = document.content[diag.range.start : diag.range.end].decode("utf-8")
    assert sliced == "O"
    diag.validate_against(document)


def test_overloaded_p_and_f_without_admission_fail() -> None:
    for letter, source in (("P", "P q"), ("F", "F r")):
        result = parse_modal(source, _deontic())  # letters not admitted
        assert not result.ok, letter
        assert any(item.code == CODE_OVERLOADED_SYMBOL for item in result.errors)


def test_overloaded_k_without_epistemic_profile_fails() -> None:
    source = "K[alice] p"
    result = parse_modal(source, _k())
    assert not result.ok
    assert any(item.code == CODE_OVERLOADED_SYMBOL for item in result.errors)
    diag = next(item for item in result.errors if item.code == CODE_OVERLOADED_SYMBOL)
    assert diag.range is not None
    document = SourceDocument.from_text("doc:k", source)
    assert document.content[diag.range.start : diag.range.end].decode("utf-8") == "K"


def test_deontic_words_forbidden_under_kripke() -> None:
    result = parse_modal("obligated p", _k())
    assert not result.ok
    assert any(item.code == CODE_OPERATOR_FORBIDDEN for item in result.errors)


def test_alethic_words_forbidden_under_deontic() -> None:
    result = parse_modal("box p", _deontic())
    assert not result.ok
    assert any(item.code == CODE_OPERATOR_FORBIDDEN for item in result.errors)


def test_bracket_box_under_deontic_is_overloaded_fail() -> None:
    result = parse_modal("[] p", _deontic())
    assert not result.ok
    assert any(item.code == CODE_OVERLOADED_SYMBOL for item in result.errors)


def test_bare_o_as_atom_is_allowed_without_classic_letters() -> None:
    """A lone identifier O is a proposition, not an overloaded operator."""
    result = parse_modal("O", _k())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.kind is NodeKind.PREDICATE
    assert result.root.symbol == "O"


# ---------------------------------------------------------------------------
# Unsupported dyadic / defeasible — typed diagnostics, not classical equivalence
# ---------------------------------------------------------------------------


def test_dyadic_o_pipe_fails_with_typed_diagnostic() -> None:
    source = "O(p | q)"
    result = parse_modal(source, _deontic_letters())
    assert not result.ok
    assert any(item.code == CODE_UNSUPPORTED_DYADIC for item in result.errors)
    diag = next(item for item in result.errors if item.code == CODE_UNSUPPORTED_DYADIC)
    assert diag.range is not None
    assert diag.metadata.get("classical_equivalence") is False
    assert diag.metadata.get("norm_form") == "dyadic"
    document = SourceDocument.from_text("doc:dyadic", source)
    diag.validate_against(document)
    # Must not succeed as classical O(p) or p iff q etc.
    assert result.root is None


def test_dyadic_obligated_slash_fails() -> None:
    source = "obligated(p / q)"
    result = parse_modal(source, _deontic())
    assert not result.ok
    assert any(item.code == CODE_UNSUPPORTED_DYADIC for item in result.errors)
    diag = next(item for item in result.errors if item.code == CODE_UNSUPPORTED_DYADIC)
    assert diag.metadata.get("classical_equivalence") is False


def test_dyadic_given_separator_fails() -> None:
    source = "permitted(p given q)"
    result = parse_modal(source, _deontic())
    assert not result.ok
    assert any(item.code == CODE_UNSUPPORTED_DYADIC for item in result.errors)


def test_grouped_pipe_cannot_masquerade_as_classical_or() -> None:
    """Bare (p | q) is dyadic, not classical disjunction."""
    source = "(p | q)"
    result = parse_modal(source, _k())
    assert not result.ok
    assert any(item.code == CODE_UNSUPPORTED_DYADIC for item in result.errors)
    diag = next(item for item in result.errors if item.code == CODE_UNSUPPORTED_DYADIC)
    assert diag.metadata.get("classical_equivalence") is False
    # Classical 'or' still works.
    classical = parse_modal("(p or q)", _k())
    assert classical.ok, [d.message for d in classical.diagnostics]
    assert classical.root is not None
    assert classical.root.kind is NodeKind.OR


def test_defeasible_normally_fails_with_typed_diagnostic() -> None:
    source = "normally p"
    result = parse_modal(source, _deontic())
    assert not result.ok
    assert any(item.code == CODE_UNSUPPORTED_DEFEASIBLE for item in result.errors)
    diag = next(
        item for item in result.errors if item.code == CODE_UNSUPPORTED_DEFEASIBLE
    )
    assert diag.range is not None
    assert diag.metadata.get("classical_equivalence") is False
    assert diag.metadata.get("supported") is False
    document = SourceDocument.from_text("doc:def", source)
    sliced = document.content[diag.range.start : diag.range.end].decode("utf-8")
    assert sliced == "normally"
    diag.validate_against(document)


@pytest.mark.parametrize(
    "source",
    [
        "unless p",
        "typically q",
        "by_default r",
        "defeasibly obligated p",
        "exception p",
        "priority p",
        "contrary_to_duty p",
        "override p",
    ],
)
def test_defeasible_keywords_fail_closed(source: str) -> None:
    result = parse_modal(source, _deontic())
    assert not result.ok
    assert any(item.code == CODE_UNSUPPORTED_DEFEASIBLE for item in result.errors)
    # Never silently becomes classical atom / connective.
    assert result.root is None


def test_dyadic_does_not_become_classical_iff() -> None:
    """O(p | q) must not parse as obligated (p iff q) or similar."""
    dyadic = parse_modal("O(p | q)", _deontic_letters())
    assert not dyadic.ok
    # A genuine monadic formula with classical iff is fine.
    classical = parse_modal("O (p iff q)", _deontic_letters())
    assert classical.ok, [d.message for d in classical.diagnostics]
    assert classical.root is not None
    assert classical.root.extension is not None
    body = classical.root.extension.children[0]
    assert body.kind is NodeKind.IFF


# ---------------------------------------------------------------------------
# Profile / frame / agent enter semantic identity
# ---------------------------------------------------------------------------


def test_profile_and_frame_enter_semantic_identity() -> None:
    k = parse_modal("box p", _k())
    s5 = parse_modal("box p", _s5())
    assert k.ok and s5.ok
    assert k.root is not None and s5.root is not None
    id_k = modal_semantic_identity(k.root, _k())
    id_s5 = modal_semantic_identity(s5.root, _s5())
    assert id_k["profile"]["frame"] == "k"
    assert id_s5["profile"]["frame"] == "s5"
    assert id_k["profile"]["profile_id"] == "kripke_k"
    assert not alpha_equivalent(k.root, s5.root)
    assert k.artifact is not None
    assert k.artifact.metadata["semantic_identity"]["profile"]["frame"] == "k"


def test_agent_index_enters_extension_payload() -> None:
    a = parse_modal("knows[alice] p", _epistemic())
    b = parse_modal("knows[bob] p", _epistemic())
    assert a.ok and b.ok
    assert a.root is not None and b.root is not None
    assert a.root.extension is not None and b.root.extension is not None
    assert a.root.extension.payload["agent"] == "alice"
    assert b.root.extension.payload["agent"] == "bob"
    assert not alpha_equivalent(a.root, b.root)


def test_norm_polarity_enters_payload() -> None:
    strong = profile_deontic(permission=PermissionStrengthKind.STRONG)
    weak = profile_deontic(
        profile_id="deontic_monadic_weak",
        permission=PermissionStrengthKind.WEAK,
    )
    a = parse_modal("permitted p", strong)
    b = parse_modal("permitted p", weak)
    assert a.ok and b.ok
    assert a.root is not None and b.root is not None
    assert a.root.extension is not None and b.root.extension is not None
    assert a.root.extension.payload["permission"] == "strong"
    assert b.root.extension.payload["permission"] == "weak"
    assert not alpha_equivalent(a.root, b.root)


# ---------------------------------------------------------------------------
# Source maps preserved
# ---------------------------------------------------------------------------


def test_source_maps_on_extension_nodes() -> None:
    source = "box (p -> diamond q)"
    result = parse_modal(source, _k())
    assert result.ok and result.root is not None
    assert result.root.range is not None
    document = SourceDocument.from_text("doc:map", source)
    # Root covers the whole formula.
    assert result.root.range.start == 0
    assert result.root.range.end == len(source.encode("utf-8"))
    # Artifact surface AST carries ranges.
    assert result.artifact is not None
    assert result.artifact.surface_ast
    for ref in result.artifact.surface_ast:
        assert ref.range is not None
        assert 0 <= ref.range.start <= ref.range.end <= document.byte_length
    # Nested diamond has its own span inside the source.
    assert result.root.extension is not None
    body = result.root.extension.children[0]
    assert body.kind is NodeKind.IMPLIES
    diamond = body.arguments[1]
    assert diamond.kind is NodeKind.EXTENSION
    assert diamond.range is not None
    sliced = document.content[diamond.range.start : diamond.range.end].decode("utf-8")
    assert "diamond" in sliced
    assert "q" in sliced


def test_diagnostic_spans_stable_for_overloaded_f() -> None:
    source = "F p"
    result = parse_modal(source, _deontic())
    assert not result.ok
    diag = next(item for item in result.errors if item.code == CODE_OVERLOADED_SYMBOL)
    document = SourceDocument.from_text("doc:f", source)
    assert document.content[diag.range.start : diag.range.end].decode("utf-8") == "F"
    diag.validate_against(document)


# ---------------------------------------------------------------------------
# Parse / print / parse alpha-equivalence (binding preserved)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "profile_factory"),
    [
        ("p", _k),
        ("not p", _k),
        ("p and q", _k),
        ("p or q", _k),
        ("p -> q", _k),
        ("p iff q", _k),
        ("p -> q -> r", _k),
        ("box p", _k),
        ("diamond q", _k),
        ("box (p -> diamond q)", _k),
        ("box p", _d),
        ("box p", _t),
        ("box p", _s4),
        ("box p", _s5),
        ("□ p", _s5),
        ("obligated p", _deontic),
        ("permitted q", _deontic),
        ("forbidden r", _deontic),
        ("obligated (p -> permitted q)", _deontic),
        ("O p", _deontic_letters),
        ("O (p -> P q)", _deontic_letters),
        ("knows[alice] p", _epistemic),
        ("knows[alice] (p and q)", _epistemic),
        ("believes[bob] p", _doxastic),
        ("intends[carol] (p -> q)", _intention),
        ("not (p or box q)", _k),
        ("true and false or p", _k),
    ],
)
def test_parse_print_parse_is_alpha_equivalent(source: str, profile_factory) -> None:
    profile = profile_factory()
    first = parse_modal(source, profile)
    assert first.ok, (source, [d.message for d in first.diagnostics])
    assert first.root is not None
    printed = print_modal(first.root)
    second = parse_modal(printed, profile, document_id="doc:rt")
    assert second.ok, (source, printed, [d.message for d in second.diagnostics])
    assert second.root is not None
    assert alpha_equivalent(first.root, second.root), (source, printed)


def test_parse_print_parse_helper() -> None:
    result = parse_print_parse("box (p -> diamond q)", _s4())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.printed


def test_binding_preserved_under_nested_modals() -> None:
    source = "box (diamond p and box (q -> r))"
    first = parse_modal(source, _k())
    assert first.ok and first.root is not None
    printed = print_modal(first.root)
    second = parse_modal(printed, _k())
    assert second.ok and second.root is not None
    assert alpha_equivalent(first.root, second.root)
    # Nested structure: outer box, body is and, right is box.
    assert first.root.extension is not None
    body = first.root.extension.children[0]
    assert body.kind is NodeKind.AND
    assert body.arguments[1].kind is NodeKind.EXTENSION
    assert body.arguments[1].extension is not None
    assert body.arguments[1].extension.payload["kind"] == "box"


def test_profile_round_trip_dict() -> None:
    for factory in (_k, _s5, _deontic, _epistemic, _doxastic, _intention):
        profile = factory()
        restored = ModalSemanticsProfile.from_dict(profile.to_dict())
        assert restored.profile_id == profile.profile_id
        assert restored.family == profile.family
        assert restored.to_dict() == profile.to_dict()
