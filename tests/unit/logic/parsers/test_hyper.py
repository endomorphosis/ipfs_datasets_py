"""Unit tests for HyperpropertySyntax@1 / HyperLTLAdapter@1 (LFP-027).

Evidence subset:

* forall / exists prenex trace prefix
* alternation with exact unsupported cause
* indexed propositions
* tool fragment ceilings (EAHyper / AutoHyper / MCHyper)
* bound + authority ceiling retained on model-check / self-composition
* noninterference template lowering
* capture-safe scoped trace variables
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.parsers.hyper import (
    CODE_EMPTY_PREFIX,
    CODE_FREE_TRACE_VAR,
    CODE_INVALID_NI,
    CODE_NESTED_QUANTIFIER,
    CODE_REBIND_TRACE_VAR,
    CODE_UNSUPPORTED_ALTERNATION,
    HYPERLTL_ADAPTER_INTERFACE,
    HYPERPROPERTY_SYNTAX_INTERFACE,
    BoundednessKind,
    EvidenceAuthority,
    HyperLTLAdapter,
    HyperParseError,
    HyperToolKind,
    HyperPrinter,
    HyperpropertyParser,
    HyperpropertySyntax,
    PrintStyle,
    ToolFragmentCeiling,
    check_quantifier_fragment,
    extract_matrix,
    extract_quantifier_prefix,
    fragment_autohyper,
    fragment_eahyper,
    fragment_mchyper,
    free_trace_variables,
    hyper_semantic_identity,
    lower_hyperltl,
    model_check_evidence_contract,
    parse_hyper,
    parse_print_parse,
    print_hyper,
    profile_hyperltl,
    profile_noninterference,
    quantifier_alternation_count,
)
from ipfs_datasets_py.logic.software_verification.hyperproperties import (
    AuthorityPromotionError,
    EvidenceAuthorityCeiling,
    HyperpropertyEvidenceKind,
    HyperpropertyEvaluation,
    HyperpropertyKind,
    HyperpropertyVerdict,
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


def _generic():
    return profile_hyperltl(tool=HyperToolKind.GENERIC)


def _eahyper():
    return profile_hyperltl(tool=HyperToolKind.EAHYPER)


def _autohyper():
    return profile_hyperltl(tool=HyperToolKind.AUTOHYPER)


def _mchyper():
    return profile_hyperltl(tool=HyperToolKind.MCHYPER)


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_interface_and_module_identity() -> None:
    assert HYPERPROPERTY_SYNTAX_INTERFACE == "HyperpropertySyntax@1"
    assert HYPERLTL_ADAPTER_INTERFACE == "HyperLTLAdapter@1"
    syntax = HyperpropertySyntax(_generic())
    assert syntax.interface == HYPERPROPERTY_SYNTAX_INTERFACE
    assert isinstance(syntax.parser, HyperpropertyParser)
    assert isinstance(syntax.printer, HyperPrinter)
    adapter = HyperLTLAdapter(_generic())
    assert adapter.interface == HYPERLTL_ADAPTER_INTERFACE


def test_tool_fragment_ceilings() -> None:
    ea = fragment_eahyper()
    assert ea.tool is HyperToolKind.EAHYPER
    assert ea.max_quantifier_alternations == 1
    auto = fragment_autohyper()
    assert auto.max_quantifier_alternations == 2
    mc = fragment_mchyper()
    assert mc.max_trace_variables == 4


# ---------------------------------------------------------------------------
# Happy-path parsing
# ---------------------------------------------------------------------------


def test_parse_forall_exists_indexed_proposition() -> None:
    result = parse_hyper(
        "forall pi1. exists pi2. always (p[pi1] -> q[pi2])",
        _generic(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.kind is NodeKind.FORALL
    assert result.quantifier_signature == ("forall", "exists")
    prefix = extract_quantifier_prefix(result.root)
    assert prefix == (("forall", "pi1"), ("exists", "pi2"))
    assert free_trace_variables(result.root) == frozenset()


def test_parse_underscore_indexed_proposition() -> None:
    result = parse_hyper(
        "forall pi1. forall pi2. eventually p_pi1",
        _generic(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    printed = print_hyper(result.root)
    assert "p[pi1]" in printed


def test_parse_relational_equal() -> None:
    result = parse_hyper(
        "forall pi1. forall pi2. always equal(pi1, pi2, status)",
        _generic(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert "equal(pi1, pi2, status)" in print_hyper(result.root)


def test_parse_noninterference_template() -> None:
    result = parse_hyper(
        "forall pi1. forall pi2. noninterference "
        "low=[user_id] high=[secret] obs=[status]",
        profile_noninterference(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    printed = print_hyper(result.root)
    assert "noninterference" in printed
    assert "user_id" in printed


def test_parse_print_parse_alpha_equivalent() -> None:
    text = "forall pi1. exists pi2. always (p[pi1] and q[pi2])"
    first, second, equivalent = parse_print_parse(text, _generic())
    assert first.ok and second.ok
    assert equivalent
    assert alpha_equivalent(first.root, second.root)


def test_unicode_quantifiers_round_trip() -> None:
    result = parse_hyper("∀ pi1. ∃ pi2. G p[pi1]", _generic())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.quantifier_signature == ("forall", "exists")


# ---------------------------------------------------------------------------
# Capture-safe scoping
# ---------------------------------------------------------------------------


def test_free_trace_variable_rejected_with_exact_scope() -> None:
    result = parse_hyper(
        "forall pi1. always p[pi2]",
        _generic(),
    )
    assert not result.ok
    assert any(d.code == CODE_FREE_TRACE_VAR for d in result.diagnostics)
    diag = next(d for d in result.diagnostics if d.code == CODE_FREE_TRACE_VAR)
    assert "pi2" in diag.message
    assert "pi1" in diag.message
    assert diag.metadata.get("variable") == "pi2"
    assert "pi1" in diag.metadata.get("bound", [])


def test_underscore_free_trace_variable_rejected() -> None:
    result = parse_hyper("forall pi1. p_pi2", _generic())
    assert not result.ok
    assert any(d.code == CODE_FREE_TRACE_VAR for d in result.diagnostics)


def test_trace_variable_rebind_rejected() -> None:
    result = parse_hyper(
        "forall pi1. exists pi1. always p[pi1]",
        _generic(),
    )
    assert not result.ok
    assert any(d.code == CODE_REBIND_TRACE_VAR for d in result.diagnostics)
    diag = next(d for d in result.diagnostics if d.code == CODE_REBIND_TRACE_VAR)
    assert "pi1" in diag.message
    assert "capture-unsafe" in diag.message


def test_nested_quantifier_in_matrix_rejected() -> None:
    result = parse_hyper(
        "forall pi1. (exists pi2. p[pi1])",
        _generic(),
    )
    assert not result.ok
    assert any(d.code == CODE_NESTED_QUANTIFIER for d in result.diagnostics)


def test_empty_prefix_rejected() -> None:
    result = parse_hyper("always p[pi1]", _generic())
    assert not result.ok
    assert any(d.code == CODE_EMPTY_PREFIX for d in result.diagnostics)


def test_free_trace_variables_helper_is_capture_safe() -> None:
    result = parse_hyper(
        "forall pi1. exists pi2. always (p[pi1] -> q[pi2])",
        _generic(),
    )
    assert result.ok
    assert free_trace_variables(result.root) == frozenset()
    # Matrix alone would expose free vars if binders were stripped incorrectly.
    matrix = extract_matrix(result.root)
    free = free_trace_variables(matrix)
    assert free == frozenset({"pi1", "pi2"})


# ---------------------------------------------------------------------------
# Unsupported alternation reports exact cause
# ---------------------------------------------------------------------------


def test_alternation_count() -> None:
    assert quantifier_alternation_count(()) == 0
    assert quantifier_alternation_count(("forall", "forall")) == 0
    assert quantifier_alternation_count(("forall", "exists")) == 1
    assert quantifier_alternation_count(("forall", "exists", "forall")) == 2


def test_eahyper_rejects_two_alternations_with_exact_cause() -> None:
    # forall exists forall → 2 alternations; EAHyper max is 1.
    result = parse_hyper(
        "forall pi1. exists pi2. forall pi3. always p[pi1]",
        _eahyper(),
    )
    assert not result.ok
    assert any(d.code == CODE_UNSUPPORTED_ALTERNATION for d in result.diagnostics)
    diag = next(
        d for d in result.diagnostics if d.code == CODE_UNSUPPORTED_ALTERNATION
    )
    assert "eahyper" in diag.message
    assert "at most 1 quantifier alternations" in diag.message
    assert "got 2" in diag.message
    assert "forall exists forall" in diag.message
    assert result.alternation_report is not None
    assert result.alternation_report.supported is False
    assert result.alternation_report.alternation_count == 2
    assert result.alternation_report.quantifier_signature == (
        "forall",
        "exists",
        "forall",
    )


def test_autohyper_accepts_one_alternation() -> None:
    result = parse_hyper(
        "forall pi1. exists pi2. always p[pi1]",
        _autohyper(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.alternation_report is not None
    assert result.alternation_report.supported is True
    assert result.alternation_report.alternation_count == 1


def test_mchyper_rejects_too_many_trace_variables() -> None:
    # MCHyper max_trace_variables = 4
    text = (
        "forall pi1. forall pi2. forall pi3. forall pi4. forall pi5. "
        "always p[pi1]"
    )
    result = parse_hyper(text, _mchyper())
    assert not result.ok
    diag = next(
        d for d in result.diagnostics if d.code == CODE_UNSUPPORTED_ALTERNATION
    )
    assert "mchyper" in diag.message
    assert "at most 4 trace variables" in diag.message
    assert "got 5" in diag.message


def test_check_quantifier_fragment_exists_forall_disabled() -> None:
    # Force-disable exists-forall shape.
    restricted = ToolFragmentCeiling(
        tool=HyperToolKind.EAHYPER,
        max_quantifier_alternations=1,
        max_trace_variables=8,
        supports_exists_forall=False,
        supports_forall_exists=True,
    )
    report = check_quantifier_fragment(("exists", "forall"), restricted)
    assert report.supported is False
    assert "does not support exists-forall" in report.cause
    assert report.quantifier_signature == ("exists", "forall")


# ---------------------------------------------------------------------------
# Authority ceiling retained
# ---------------------------------------------------------------------------


def test_model_check_evidence_contract_retains_bounded_ceiling() -> None:
    contract = model_check_evidence_contract(tool=HyperToolKind.MCHYPER, max_steps=16)
    assert contract.authority is EvidenceAuthority.BOUNDED
    assert contract.authority_ceiling is EvidenceAuthority.BOUNDED
    assert contract.bound.boundedness is BoundednessKind.MODEL_CHECK
    assert contract.unbounded_proof is False
    assert contract.may_promote_to_unbounded_proof is False
    payload = contract.to_dict()
    assert payload["authority_ceiling"] == "bounded"
    assert payload["unbounded_proof"] is False
    with pytest.raises(SyntaxContractError, match="cannot be promoted"):
        contract.promote_to_unbounded_proof()


def test_self_composition_evidence_rejects_unbounded_bound() -> None:
    from ipfs_datasets_py.logic.parsers.hyper import HyperBoundContract

    with pytest.raises(SyntaxContractError, match="unboundedness"):
        HyperBoundContract(boundedness=BoundednessKind.UNBOUNDED)


def test_lower_noninterference_retains_authority_ceiling() -> None:
    text = (
        "forall pi1. forall pi2. noninterference "
        "low=[user_id] high=[secret] obs=[status]"
    )
    lowered = lower_hyperltl(text, profile_noninterference())
    assert lowered.receipt.authority_ceiling == "bounded"
    assert lowered.receipt.authorizes_universal_proof is False
    assert lowered.document.formula.kind is HyperpropertyKind.NONINTERFERENCE
    assert lowered.document.formula.quantifier_signature == ("forall", "forall")
    assert lowered.authority_ceiling == "bounded"
    receipt = lowered.receipt.to_dict()
    assert receipt["authority_ceiling"] == "bounded"
    assert receipt["authorizes_universal_proof"] is False
    assert receipt["bound"]["unbounded_proof"] is False


def test_lower_general_hyperltl_formula() -> None:
    text = "forall pi1. exists pi2. always equal(pi1, pi2, status)"
    lowered = lower_hyperltl(text, _generic())
    assert lowered.document.formula.kind is HyperpropertyKind.GENERAL
    assert lowered.document.formula.quantifier_signature == ("forall", "exists")
    assert lowered.receipt.alternation_count == 1
    assert lowered.receipt.fragment_supported is True
    assert lowered.receipt.authority_ceiling == "bounded"


def test_adapter_rejects_unsupported_alternation_on_lower() -> None:
    adapter = HyperLTLAdapter(_eahyper())
    with pytest.raises(HyperParseError, match="at most 1 quantifier alternations") as exc:
        adapter.lower_text(
            "forall pi1. exists pi2. forall pi3. always p[pi1]"
        )
    assert exc.value.code == CODE_UNSUPPORTED_ALTERNATION


def test_retain_authority_ceiling_on_evaluation() -> None:
    adapter = HyperLTLAdapter(_mchyper())
    evaluation = HyperpropertyEvaluation(
        verdict=HyperpropertyVerdict.HOLDS,
        evidence_kind=HyperpropertyEvidenceKind.BOUNDED_SELF_COMPOSITION,
        authority_ceiling=EvidenceAuthorityCeiling.BOUNDED,
        formula_id="formula:hyperltl",
        policy_id="policy:hyper:1",
        reason="bounded model-check sample under declared steps",
        bounded=True,
        authorizes_universal_proof=False,
        explored_traces=2,
        explored_pairs=1,
        maximum_pairs=8,
        bound_hit=False,
    )
    retained = adapter.retain_authority_ceiling(evaluation)
    assert retained["authority_ceiling"] == "bounded"
    assert retained["authorizes_universal_proof"] is False
    assert retained["bounded"] is True
    assert retained["evidence_contract"]["authority_ceiling"] == "bounded"


def test_retain_authority_ceiling_rejects_universal_proof_claim() -> None:
    adapter = HyperLTLAdapter(_generic())
    with pytest.raises(AuthorityPromotionError, match="universal proof"):
        adapter.retain_authority_ceiling(
            {
                "verdict": "holds",
                "authority_ceiling": "bounded",
                "authorizes_universal_proof": True,
            }
        )


def test_adapter_promote_to_unbounded_proof_fails_closed() -> None:
    adapter = HyperLTLAdapter(_mchyper())
    with pytest.raises(SyntaxContractError, match="cannot be promoted"):
        adapter.promote_to_unbounded_proof()


def test_parse_result_metadata_carries_authority_ceiling() -> None:
    result = parse_hyper(
        "forall pi1. forall pi2. always p[pi1]",
        _mchyper(),
    )
    assert result.ok
    assert result.artifact is not None
    assert result.artifact.metadata["authority_ceiling"] == "bounded"


# ---------------------------------------------------------------------------
# Noninterference validation
# ---------------------------------------------------------------------------


def test_noninterference_requires_forall_forall() -> None:
    result = parse_hyper(
        "forall pi1. exists pi2. noninterference "
        "low=[user_id] high=[secret] obs=[status]",
        _generic(),
    )
    assert not result.ok
    assert any(d.code == CODE_INVALID_NI for d in result.diagnostics)


def test_noninterference_rejects_overlapping_low_high() -> None:
    result = parse_hyper(
        "forall pi1. forall pi2. noninterference "
        "low=[x] high=[x] obs=[y]",
        profile_noninterference(),
    )
    assert not result.ok
    assert any(d.code == CODE_INVALID_NI for d in result.diagnostics)


# ---------------------------------------------------------------------------
# Parse request / limits / profiles
# ---------------------------------------------------------------------------


def test_parser_via_parse_request() -> None:
    parser = HyperpropertyParser(_generic())
    document = SourceDocument.from_text("doc:t1", "forall pi1. always p[pi1]")
    request = ParseRequest(
        request_id="req:t1",
        document=document,
        notation_id="canonical_hyperltl",
        profile_id="hyperltl:generic",
        family_id="hyperproperty",
        mode=ParseMode.STRICT,
        limits=ParseLimits(),
        metadata={"profile": _generic().to_dict()},
    )
    artifact = parser.parse(request)
    assert artifact.status is ParseStatus.OK
    assert artifact.cst is not None
    assert "expression" in artifact.metadata
    assert artifact.metadata["authority_ceiling"] == "bounded"


def test_semantic_identity_includes_profile_and_prefix() -> None:
    result = parse_hyper(
        "forall pi1. exists pi2. p[pi1]",
        _generic(),
    )
    assert result.ok
    identity = hyper_semantic_identity(result.root, result.profile)
    assert identity["quantifier_prefix"] == [
        {"quantifier": "forall", "variable": "pi1"},
        {"quantifier": "exists", "variable": "pi2"},
    ]
    assert identity["free_trace_variables"] == []
    assert identity["profile"]["profile_id"] == result.profile.profile_id


def test_print_style_unicode() -> None:
    result = parse_hyper(
        "forall pi1. not p[pi1]",
        _generic(),
    )
    assert result.ok
    text = print_hyper(result.root, style=PrintStyle.UNICODE)
    assert "∀" in text
    assert "¬" in text


def test_syntax_parse_text_or_raise() -> None:
    syntax = HyperpropertySyntax(_generic())
    expr = syntax.parse_text_or_raise("forall pi1. always p[pi1]")
    assert expr.root.kind is NodeKind.FORALL
    with pytest.raises(HyperParseError):
        syntax.parse_text_or_raise("always p[pi1]")
