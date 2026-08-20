"""Unit tests for FixedPointLogicProfiles@1 (LFP2-041).

Evidence subset:

* mu-calculus least/greatest fixed-point binders
* binder positivity and guardedness fail closed
* alternation-depth ceiling is explicit
* controlled CTL-star fragment lowers to mu-calculus; unsupported forms reject
* declaration never implies executable support
* parse/print/parse semantic round-trip
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.parsers.fixed_point import (
    CODE_ALTERNATION_DEPTH,
    CODE_NEGATIVE_OCCURRENCE,
    CODE_UNGUARDED_OCCURRENCE,
    CODE_UNSUPPORTED_CTL_STAR,
    FIXED_POINT_LOGIC_PROFILES_INTERFACE,
    FP_FAMILY_ID,
    FP_NOTATION_ID,
    AuthorityPromotionError,
    EvidenceAuthority,
    EvidenceSource,
    FixedPointEvidenceContract,
    FixedPointLogicProfiles,
    FixedPointLoweringReceipt,
    FixedPointParser,
    FixedPointPrinter,
    LifecyclePosture,
    SurfaceKind,
    alternation_depth,
    bounded_unrolling_evidence_contract,
    check_alternation_depth,
    check_positivity_and_guardedness,
    declaration_evidence_contract,
    extract_binder_signature,
    fixed_point_semantic_identity,
    free_fixed_point_variables,
    is_controlled_ctl_star_supported,
    lower_ctl_star_fragment,
    model_check_evidence_contract,
    parse_fixed_point,
    parse_print_parse,
    print_fixed_point,
    profile_ctl_star_fragment,
    profile_declaration_only,
    profile_mixed_mu_ctl,
    profile_mu_calculus,
    retain_authority_ceiling,
)
from ipfs_datasets_py.logic.syntax_core.algebra import alpha_equivalent
from ipfs_datasets_py.logic.syntax_core.ast import NodeKind
from ipfs_datasets_py.logic.syntax_core.contracts import (
    ParseStatus,
    SyntaxContractError,
)


def _mu():
    return profile_mu_calculus()


def _ctl():
    return profile_ctl_star_fragment()


def _mixed():
    return profile_mixed_mu_ctl()


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_interface_and_module_identity() -> None:
    assert FIXED_POINT_LOGIC_PROFILES_INTERFACE == "FixedPointLogicProfiles@1"
    assert FP_FAMILY_ID == "mu_calculus"
    assert FP_NOTATION_ID == "canonical_mu_calculus"
    logic = FixedPointLogicProfiles(_mu())
    assert logic.interface == FIXED_POINT_LOGIC_PROFILES_INTERFACE
    assert isinstance(logic.parser, FixedPointParser)
    assert isinstance(logic.printer, FixedPointPrinter)


def test_profiles_participate_in_identity() -> None:
    mu = _mu()
    ctl = _ctl()
    assert mu.semantic_identity != ctl.semantic_identity
    assert mu.surface is SurfaceKind.MU_CALCULUS
    assert ctl.admit_ctl_surface is True
    assert mu.executable_support is False
    assert mu.grants_executable_support is False
    decl = profile_declaration_only()
    assert decl.is_declaration_only is True
    assert decl.grants_executable_support is False


def test_declaration_only_cannot_claim_executable() -> None:
    with pytest.raises(SyntaxContractError, match="declaration_only"):
        profile_mu_calculus(
            lifecycle=LifecyclePosture.DECLARATION_ONLY,
            executable_support=True,
        )


# ---------------------------------------------------------------------------
# Happy-path mu-calculus parsing
# ---------------------------------------------------------------------------


def test_parse_least_fixed_point_guarded() -> None:
    result = parse_fixed_point("mu X. diamond X", _mu())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.kind is NodeKind.EXTENSION
    assert result.root.extension is not None
    assert result.root.extension.payload["kind"] == "mu"
    assert result.root.extension.payload["variable"] == "X"
    assert result.guard_report is not None
    assert result.guard_report.positive is True
    assert result.guard_report.guarded is True
    printed = print_fixed_point(result.root)
    assert printed.startswith("mu X.")
    assert "diamond" in printed


def test_parse_greatest_fixed_point() -> None:
    result = parse_fixed_point("nu Y. box (p and Y)", _mu())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root.extension.payload["kind"] == "nu"
    assert free_fixed_point_variables(result.root) == frozenset()
    assert "p" in print_fixed_point(result.root)


def test_parse_nested_same_kind_binders() -> None:
    result = parse_fixed_point(
        "mu X. diamond (mu Y. diamond (X and Y))",
        _mu(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert extract_binder_signature(result.root) == ("mu", "mu")
    assert alternation_depth(result.root) == 0


def test_unicode_binders_and_modals() -> None:
    result = parse_fixed_point("μ X. ◇ X", _mu())
    assert result.ok, [d.message for d in result.diagnostics]
    printed = print_fixed_point(result.root, style="unicode")
    assert "μ" in printed or "mu" in printed


def test_boolean_connectives() -> None:
    result = parse_fixed_point(
        "mu X. diamond (p and q) or box r",
        _mu(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    # Outer structure is OR of binder? Actually: mu binds only diamond (p and q),
    # then or box r — depending on precedence of fixed_point vs or.
    # Grammar: formula ::= fixed_point | iff, and fixed_point is only at the
    # start when mu/nu is present. So "mu X. diamond (p and q) or box r"
    # parses as mu X. (diamond (p and q) or box r).
    printed = print_fixed_point(result.root)
    assert "mu X." in printed
    assert "or" in printed


def test_semantic_identity_includes_profile() -> None:
    result = parse_fixed_point("mu X. diamond X", _mu())
    assert result.ok
    identity = fixed_point_semantic_identity(result.root, _mu())
    assert identity["family"] == "mu_calculus"
    assert identity["profile"]["profile_id"] == "mu_calculus_guarded"
    assert identity["profile"]["executable_support"] is False


# ---------------------------------------------------------------------------
# Positivity / guardedness
# ---------------------------------------------------------------------------


def test_negative_occurrence_rejected() -> None:
    result = parse_fixed_point("mu X. not diamond X", _mu())
    assert not result.ok
    assert any(d.code == CODE_NEGATIVE_OCCURRENCE for d in result.diagnostics)
    assert "X" in result.diagnostics[0].message or any(
        "X" in d.message for d in result.diagnostics
    )


def test_unguarded_occurrence_rejected() -> None:
    result = parse_fixed_point("mu X. X", _mu())
    assert not result.ok
    assert any(d.code == CODE_UNGUARDED_OCCURRENCE for d in result.diagnostics)


def test_unguarded_under_and_rejected() -> None:
    result = parse_fixed_point("mu X. p and X", _mu())
    assert not result.ok
    assert any(d.code == CODE_UNGUARDED_OCCURRENCE for d in result.diagnostics)


def test_positive_guarded_under_box() -> None:
    result = parse_fixed_point("mu X. p or box X", _mu())
    assert result.ok, [d.message for d in result.diagnostics]
    guard = check_positivity_and_guardedness(result.root)
    assert guard.positive is True
    assert guard.guarded is True


def test_iff_with_bound_variable_is_negative() -> None:
    result = parse_fixed_point("mu X. diamond X iff p", _mu())
    assert not result.ok
    assert any(d.code == CODE_NEGATIVE_OCCURRENCE for d in result.diagnostics)


def test_implication_left_is_negative() -> None:
    # X on the left of implication is a negative occurrence.
    result = parse_fixed_point("mu X. diamond X implies p", _mu())
    assert not result.ok
    assert any(d.code == CODE_NEGATIVE_OCCURRENCE for d in result.diagnostics)


# ---------------------------------------------------------------------------
# Alternation depth
# ---------------------------------------------------------------------------


def test_alternation_depth_zero_for_single_binder() -> None:
    result = parse_fixed_point("mu X. diamond X", _mu())
    assert result.ok
    assert alternation_depth(result.root) == 0
    report = check_alternation_depth(result.root, _mu())
    assert report.accepted is True
    assert report.alternation_depth == 0


def test_alternation_depth_one_for_mu_nu() -> None:
    # max_alternation_depth default is 2, so depth 1 is accepted.
    result = parse_fixed_point(
        "mu X. diamond (nu Y. box (X and Y))",
        _mu(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert alternation_depth(result.root) == 1
    assert extract_binder_signature(result.root) == ("mu", "nu")


def test_alternation_depth_exceeded_is_explicit() -> None:
    tight = profile_mu_calculus(max_alternation_depth=0)
    result = parse_fixed_point(
        "mu X. diamond (nu Y. box (X and Y))",
        tight,
    )
    assert not result.ok
    assert any(d.code == CODE_ALTERNATION_DEPTH for d in result.diagnostics)
    diag = next(d for d in result.diagnostics if d.code == CODE_ALTERNATION_DEPTH)
    assert "alternation depth" in diag.message
    assert diag.metadata.get("alternation_depth") == 1
    assert diag.metadata.get("max_alternations") == 0


def test_deeper_alternation_chain() -> None:
    # mu nu mu => depth 2
    text = "mu X. diamond (nu Y. box (mu Z. diamond (X and Y and Z)))"
    result = parse_fixed_point(text, profile_mu_calculus(max_alternation_depth=2))
    assert result.ok, [d.message for d in result.diagnostics]
    assert alternation_depth(result.root) == 2

    tight = profile_mu_calculus(max_alternation_depth=1)
    failed = parse_fixed_point(text, tight)
    assert not failed.ok
    assert any(d.code == CODE_ALTERNATION_DEPTH for d in failed.diagnostics)


# ---------------------------------------------------------------------------
# Controlled CTL-star lowering
# ---------------------------------------------------------------------------


def test_ctl_ag_lowers_to_nu() -> None:
    result = lower_ctl_star_fragment("AG p", _ctl())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root.extension.payload["kind"] == "nu"
    printed = print_fixed_point(result.root)
    assert printed.startswith("nu ")
    assert "box" in printed
    assert "p" in printed


def test_ctl_ef_lowers_to_mu() -> None:
    result = parse_fixed_point("EF p", _ctl())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root.extension.payload["kind"] == "mu"
    printed = print_fixed_point(result.root)
    assert "diamond" in printed


def test_ctl_path_quantifier_words() -> None:
    result = parse_fixed_point("A always p", _ctl())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root.extension.payload["kind"] == "nu"

    result2 = parse_fixed_point("E eventually q", _ctl())
    assert result2.ok, [d.message for d in result2.diagnostics]
    assert result2.root.extension.payload["kind"] == "mu"


def test_ctl_until_lowers() -> None:
    result = parse_fixed_point("A (p until q)", _ctl())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root.extension.payload["kind"] == "mu"
    printed = print_fixed_point(result.root)
    assert "box" in printed
    assert "p" in printed and "q" in printed


def test_ctl_ex_is_diamond() -> None:
    result = parse_fixed_point("EX p", _ctl())
    assert result.ok, [d.message for d in result.diagnostics]
    # EX is a modal, not a binder.
    assert result.root.extension.payload_schema.endswith("modal/v1")
    assert result.root.extension.payload["kind"] == "diamond"


def test_unsupported_ctl_star_path_formula() -> None:
    # Controlled fragment only admits path-quantified until inside parentheses,
    # not arbitrary boolean path matrices (full CTL* is rejected explicitly).
    result = parse_fixed_point("A (p and q)", _ctl())
    assert not result.ok
    assert any(d.code == CODE_UNSUPPORTED_CTL_STAR for d in result.diagnostics)
    diag = next(
        d for d in result.diagnostics if d.code == CODE_UNSUPPORTED_CTL_STAR
    )
    assert diag.metadata.get("supported") is False
    assert "until" in diag.message.lower() or "unsupported" in diag.message.lower()


def test_ctl_surface_rejected_on_pure_mu_profile() -> None:
    result = parse_fixed_point("AG p", _mu())
    assert not result.ok
    assert any(d.code == CODE_UNSUPPORTED_CTL_STAR for d in result.diagnostics)


def test_mixed_profile_admits_both() -> None:
    # Binders are formula-level; nest them under parentheses beside CTL atoms.
    result = parse_fixed_point("AG p and (mu X. diamond X)", _mixed())
    assert result.ok, [d.message for d in result.diagnostics]
    printed = print_fixed_point(result.root)
    assert "nu " in printed
    assert "mu " in printed


def test_controlled_ctl_star_support_table() -> None:
    assert is_controlled_ctl_star_supported("AG")
    assert is_controlled_ctl_star_supported("EF")
    assert is_controlled_ctl_star_supported("A until")
    assert not is_controlled_ctl_star_supported("A F G")
    assert not is_controlled_ctl_star_supported("E G F")


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_parse_print_parse_round_trip_mu() -> None:
    text = "mu X. diamond (p and X) or box q"
    first, second, equivalent = parse_print_parse(text, _mu())
    assert first.ok, [d.message for d in first.diagnostics]
    assert second.ok, [d.message for d in second.diagnostics]
    assert equivalent
    assert alpha_equivalent(first.root, second.root)


def test_parse_print_parse_round_trip_nu() -> None:
    text = "nu Y. box (p or diamond Y)"
    first, second, equivalent = parse_print_parse(text, _mu())
    assert first.ok
    assert second.ok
    assert equivalent


def test_empty_input_rejected() -> None:
    result = parse_fixed_point("   ", _mu())
    assert not result.ok
    assert result.status is not ParseStatus.OK


# ---------------------------------------------------------------------------
# Declaration never implies executable support
# ---------------------------------------------------------------------------


def test_default_profile_has_no_executable_support() -> None:
    profile = _mu()
    assert profile.executable_support is False
    assert profile.grants_executable_support is False
    logic = FixedPointLogicProfiles(profile)
    with pytest.raises(AuthorityPromotionError, match="executable support"):
        logic.require_executable_support()


def test_declaration_evidence_has_no_authority() -> None:
    evidence = declaration_evidence_contract(_mu())
    assert evidence.source is EvidenceSource.DECLARATION
    assert evidence.authority_ceiling is EvidenceAuthority.NONE
    assert evidence.grants_executable_support is False
    assert evidence.may_promote_to_proof is False
    with pytest.raises(AuthorityPromotionError, match="proof"):
        evidence.promote_to_proof()


def test_cannot_construct_declaration_as_executable() -> None:
    with pytest.raises(AuthorityPromotionError, match="executable support"):
        FixedPointEvidenceContract(
            source=EvidenceSource.DECLARATION,
            authority=EvidenceAuthority.NONE,
            grants_executable_support=True,
        )


def test_cannot_construct_model_check_as_proof() -> None:
    with pytest.raises(AuthorityPromotionError, match="proof"):
        FixedPointEvidenceContract(
            source=EvidenceSource.SYMBOLIC_MODEL_CHECK,
            authority=EvidenceAuthority.PROOF,
        )


def test_model_check_requires_explicit_executable_profile() -> None:
    with pytest.raises(AuthorityPromotionError, match="executable support"):
        model_check_evidence_contract(_mu())

    executable = profile_mu_calculus(
        executable_support=True,
        lifecycle=LifecyclePosture.CONTROLLED_EXECUTABLE,
    )
    assert executable.grants_executable_support is True
    evidence = model_check_evidence_contract(executable)
    assert evidence.authority_ceiling is EvidenceAuthority.MODEL_CHECK
    assert evidence.grants_executable_support is True
    with pytest.raises(AuthorityPromotionError, match="proof"):
        evidence.promote_to_proof()


def test_bounded_unrolling_never_proof() -> None:
    evidence = bounded_unrolling_evidence_contract(_mu())
    assert evidence.authority_ceiling is EvidenceAuthority.BOUNDED
    assert evidence.is_proof is False
    retained = retain_authority_ceiling(evidence)
    assert retained["authority_ceiling"] == "bounded"
    assert retained["grants_proof_authority"] is False
    with pytest.raises(AuthorityPromotionError, match="proof"):
        retain_authority_ceiling(
            evidence,
            claimed={"authority": "proof", "grants_proof_authority": True},
        )


def test_lowering_receipt_rejects_declaration_executable() -> None:
    logic = FixedPointLogicProfiles(_mu())
    result = logic.parse_text("mu X. diamond X")
    assert result.ok
    evidence = declaration_evidence_contract(_mu())
    receipt = logic.attach_evidence(result, evidence)
    assert receipt.authorizes_proof is False
    assert receipt.authorizes_executable is False
    assert receipt.positive is True
    assert receipt.guarded is True
    with pytest.raises(AuthorityPromotionError, match="executable"):
        FixedPointLoweringReceipt(
            document_id="doc:1",
            profile_id=result.profile.profile_id,
            source_surface="mu_calculus",
            target_surface="mu_calculus",
            alternation_depth=0,
            guarded=True,
            positive=True,
            evidence={
                "source": "declaration",
                "authority": "none",
                "grants_executable_support": True,
            },
            authorizes_executable=True,
        )


def test_declaration_only_profile_parses_but_not_executable() -> None:
    # max_alternation_depth=0 still allows single binders (depth 0).
    profile = profile_declaration_only()
    result = parse_fixed_point("mu X. diamond X", profile)
    assert result.ok, [d.message for d in result.diagnostics]
    assert profile.grants_executable_support is False
    logic = FixedPointLogicProfiles(profile)
    with pytest.raises(AuthorityPromotionError, match="executable support"):
        logic.require_executable_support()
