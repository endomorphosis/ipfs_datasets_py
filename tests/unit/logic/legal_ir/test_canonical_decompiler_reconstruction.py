"""Reconstruction-mode and adversarial decompilation tests for PGIR-022."""

from __future__ import annotations

from collections import Counter
import inspect

import pytest

from ipfs_datasets_py.logic.bridge.translation import (
    FidelityClaim,
    ReconstructionMode,
    TranslationPreservationClass,
)
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    CanonicalContractError,
    CanonicalRoundTripIR,
    CanonicalRule,
    DecompilerRequest,
    OperationStatus,
)
from ipfs_datasets_py.logic.bridge.decompiler import (
    CANONICAL_DECOMPILER_IDENTITY_CID,
    DOMAIN_NEUTRAL_DECOMPILER_INTERFACE,
    DomainNeutralCanonicalDecompiler,
    adversarial_decompilation_fixtures,
    decompile_structural_review,
    decompile_with_preservation,
    decompiler_identity_payload,
    detect_surface_semantic_differences,
    evaluate_adversarial_decompilation,
    paraphrase_translation_receipt,
    structural_review_payload,
)
from ipfs_datasets_py.logic.legal_ir.canonical_decompiler import (
    SourceWithheldCanonicalDecompiler,
    decompile_rule,
)
from ipfs_datasets_py.utils.cid_utils import cid_for_dag_json


def _rule() -> CanonicalRule:
    return CanonicalRule(
        modality="O",
        actor="company_a",
        action="file",
        object="annual_report",
        conditions=("public_interest",),
        exceptions=("emergency",),
        temporal=("within_10_days",),
    )


def _request() -> DecompilerRequest:
    return DecompilerRequest(
        canonical_ir=CanonicalRoundTripIR((_rule(),)),
        request_id="reconstruction",
    )


def test_decompiler_identity_is_frozen_and_model_free() -> None:
    payload = decompiler_identity_payload()
    assert cid_for_dag_json(payload) == CANONICAL_DECOMPILER_IDENTITY_CID
    assert payload["source_withheld"] is True
    assert payload["deterministic"] is True
    assert payload["learned_stages"] == []
    assert "style_paraphrase" in payload["reconstruction_modes"]
    assert "lossless" in payload["preservation_classes"]


def test_structural_review_is_not_prose_and_is_lossless_inventory() -> None:
    ir = _request().canonical_ir
    review = decompile_structural_review(ir)
    payload = review.to_dict()

    assert review.review_cid == cid_for_dag_json(structural_review_payload(ir))
    assert payload["reconstruction_mode"] == ReconstructionMode.STRUCTURAL_REVIEW.value
    assert payload["preservation_class"] == TranslationPreservationClass.LOSSLESS.value
    assert payload["fidelity_claim"] == FidelityClaim.NONE.value
    assert payload["rules"][0]["modality"] == "O"
    assert payload["rules"][0]["conditions"] == ["public_interest"]
    assert "must" not in str(payload["rules"])
    receipt = review.receipt()
    assert receipt.fidelity_claim is FidelityClaim.NONE
    assert receipt.preservation_class is TranslationPreservationClass.LOSSLESS


def test_style_paraphrase_receipt_does_not_claim_fidelity() -> None:
    request = _request()
    result, receipt, review = decompile_with_preservation(
        request, mode=ReconstructionMode.STYLE_PARAPHRASE
    )

    assert result.status is OperationStatus.SUCCESS
    assert review is None
    assert receipt is not None
    assert receipt.reconstruction_mode is ReconstructionMode.STYLE_PARAPHRASE
    assert receipt.preservation_class is TranslationPreservationClass.HEURISTIC
    assert receipt.fidelity_claim is FidelityClaim.NONE
    assert "recompilation" in " ".join(receipt.declared_loss)
    assert paraphrase_translation_receipt(request, result).receipt_cid == receipt.receipt_cid


def test_controlled_reconstruction_is_a_candidate_until_the_gate() -> None:
    result, receipt, _review = decompile_with_preservation(
        _request(), mode=ReconstructionMode.CONTROLLED_SEMANTIC
    )
    assert result.status is OperationStatus.SUCCESS
    assert receipt is not None
    assert receipt.reconstruction_mode is ReconstructionMode.CONTROLLED_SEMANTIC
    assert receipt.fidelity_claim is FidelityClaim.CANDIDATE
    assert receipt.preservation_class is TranslationPreservationClass.HEURISTIC
    assert receipt.recompilation_cid is None


def test_measured_decompile_path_is_unchanged() -> None:
    request = _request()
    text = SourceWithheldCanonicalDecompiler().decompile(request).text
    assert text == (
        "Company a must file annual report within 10 days "
        "if public interest unless emergency."
    )


def test_domain_neutral_inverse_separates_modes_and_retains_unsupported() -> None:
    inverse = DomainNeutralCanonicalDecompiler()
    ir = _request().canonical_ir
    review = inverse.invert_canonical_ir(ir, mode=ReconstructionMode.STRUCTURAL_REVIEW)
    paraphrase = inverse.invert_canonical_ir(ir, mode=ReconstructionMode.STYLE_PARAPHRASE)
    controlled = inverse.invert_canonical_ir(ir, mode=ReconstructionMode.CONTROLLED_SEMANTIC)
    unsupported = inverse.invert_unsupported(
        kind="typed.legal_norm_ir",
        source_cid=ir.ir_cid,
        reason="no reviewed typed inverse of CanonicalRoundTripIR",
    )

    assert inverse.identity == DOMAIN_NEUTRAL_DECOMPILER_INTERFACE
    assert inverse.uses_model is False
    assert review.reconstruction_mode is ReconstructionMode.STRUCTURAL_REVIEW
    assert paraphrase.fidelity_claim is FidelityClaim.NONE
    assert controlled.fidelity_claim is FidelityClaim.CANDIDATE
    assert unsupported.preservation_class is TranslationPreservationClass.UNSUPPORTED
    assert unsupported.receipt is not None
    assert unsupported.receipt.fidelity_claim is FidelityClaim.NONE


def test_adversarial_fixtures_reject_undeclared_fidelity() -> None:
    fixtures = adversarial_decompilation_fixtures()
    assert {item.fixture_id for item in fixtures} >= {
        "polarity_flip_obligation_to_prohibition",
        "dropped_condition_and_exception",
        "permission_as_obligation",
        "prohibition_weakened_to_permission",
        "plausible_prose_as_fidelity",
    }
    for fixture in fixtures:
        verdict = evaluate_adversarial_decompilation(fixture)
        assert verdict.admitted is True, (fixture.fixture_id, verdict.to_dict())
        assert fixture.kind in verdict.difference_kinds or any(
            kind in verdict.difference_kinds for kind in fixture.expected_difference_kinds
        )
        assert any(claim.startswith("preservation:") for claim in verdict.rejected_claims)
        assert any(claim.startswith("fidelity:") for claim in verdict.rejected_claims)


def test_surface_detector_finds_polarity_and_dropped_facets() -> None:
    ir = CanonicalRoundTripIR((_rule(),))
    flipped = detect_surface_semantic_differences(
        ir,
        "Company a must not file annual report within 10 days if public interest unless emergency.",
    )
    dropped = detect_surface_semantic_differences(ir, "Company a must file annual report.")
    kinds_flipped = {item["kind"] for item in flipped}
    kinds_dropped = {item["kind"] for item in dropped}
    assert "changed_polarity" in kinds_flipped
    assert "dropped_facet" in kinds_dropped


def _association_ir() -> CanonicalRoundTripIR:
    return CanonicalRoundTripIR((
        CanonicalRule("O", "agency", "file", "notice", conditions=("consent",),
                      exceptions=("emergency",), temporal=("within_5_days",)),
        CanonicalRule("O", "court", "publish", "report", conditions=("review",),
                      exceptions=("appeal",), temporal=("within_7_days",)),
    ))


def _render_association_ir(ir: CanonicalRoundTripIR) -> str:
    result = SourceWithheldCanonicalDecompiler().decompile(
        DecompilerRequest(canonical_ir=ir, request_id="surface-association-control")
    )
    assert result.status is OperationStatus.SUCCESS
    return result.text


def _unresolved_association(ir: CanonicalRoundTripIR, text: str) -> dict[str, object]:
    differences = detect_surface_semantic_differences(ir, text)
    unresolved = [item for item in differences if item["kind"] == "unresolved_rule_association"]
    assert len(unresolved) == 1, differences
    assert unresolved[0]["scope"] == "frozen_surface_heuristic"
    return unresolved[0]


@pytest.mark.parametrize("changed", [
    "Court must file notice within 5 days if consent unless emergency. "
    "Agency must publish report within 7 days if review unless appeal.",
    "Agency must file notice within 5 days if consent unless appeal. "
    "Court must publish report within 7 days if review unless emergency.",
    "Agency must file notice within 5 days if review unless emergency. "
    "Court must publish report within 7 days if consent unless appeal.",
], ids=("actor", "exception", "condition"))
def test_surface_detector_reports_unresolved_cross_rule_associations(changed: str) -> None:
    ir = _association_ir()
    clean = _render_association_ir(ir)
    assert Counter(clean.casefold().split()) == Counter(changed.casefold().split())
    assert changed != clean
    unresolved = _unresolved_association(ir, changed)
    assert unresolved["unmatched_rule_indices"] == [0, 1]
    assert unresolved["unmatched_unit_indices"] == [0, 1]


@pytest.mark.parametrize("reverse", (False, True))
def test_known_whole_rule_surfaces_allow_permutation_and_case_whitespace(reverse: bool) -> None:
    ir = _association_ir()
    units = [decompile_rule(rule) for rule in ir.rules]
    if reverse:
        units.reverse()
    text = "\n  ".join(units).swapcase()
    assert detect_surface_semantic_differences(ir, text) == ()


def test_surface_association_counts_duplicate_occurrences() -> None:
    first = CanonicalRule("O", "agency", "file", "notice")
    second = CanonicalRule("O", "court", "publish", "report")
    ir = CanonicalRoundTripIR((first, first, second))
    assert len(ir.rules) == 3
    assert detect_surface_semantic_differences(ir,
        " ".join(decompile_rule(rule) for rule in (second, first, first))) == ()
    changed = " ".join(decompile_rule(rule) for rule in (first, second, second))
    unresolved = _unresolved_association(ir, changed)
    assert len(unresolved["unmatched_rule_indices"]) == 1
    assert len(unresolved["unmatched_unit_indices"]) == 1


@pytest.mark.parametrize("tail", ("", " if alpha consents", " unless alpha objects"))
def test_foreign_actor_mentions_cannot_satisfy_the_subject(tail: str) -> None:
    ir = CanonicalRoundTripIR((CanonicalRule("O", "alpha", "notify", "beta"),))
    changed = "Beta must notify alpha" + tail + "."
    assert all(word in changed.casefold() for word in ("alpha", "notify", "beta"))
    _unresolved_association(ir, changed)


@pytest.mark.parametrize("changed", (
    "Subagency must file notice if consent unless flood.",
    "Agency must profile notice if consent unless flood.",
    "Agency must file notice if nonconsent unless flood.",
    "Agency must file notice if consent unless flooding.",
))
def test_facet_substrings_do_not_establish_frozen_rule_association(changed: str) -> None:
    ir = CanonicalRoundTripIR((CanonicalRule("O", "agency", "file", "notice",
        conditions=("consent",), exceptions=("flood",)),))
    _unresolved_association(ir, changed)


def test_condition_and_exception_mentions_cannot_exchange_positions() -> None:
    ir = CanonicalRoundTripIR((CanonicalRule("O", "agency", "file", "notice",
        conditions=("licensed",), exceptions=("flood",)),))
    _unresolved_association(ir, "Agency must file notice if flood unless licensed.")


def test_repeated_actor_and_action_allow_whole_rules_but_not_object_guard_exchange() -> None:
    first = CanonicalRule("O", "agency", "file", "audit", conditions=("licensed",))
    second = CanonicalRule("O", "agency", "file", "ledger", conditions=("reviewed",))
    ir = CanonicalRoundTripIR((first, second))
    assert detect_surface_semantic_differences(ir,
        decompile_rule(second) + " " + decompile_rule(first)) == ()
    _unresolved_association(ir,
        "Agency must file audit if reviewed. Agency must file ledger if licensed.")


@pytest.mark.parametrize("facets", (
    {"actor": "agency_a.b"},
    {"action": "file_v.2"},
    {"object": "u.s._code_notice"},
    {"conditions": ("within_1.5_days",)},
    {"exceptions": ("supervisor_must_not_approve",)},
    {"conditions": ("supervisor_may_approve",)},
    {"object": "memo_that_must_not_circulate"},
))
def test_exact_canonical_atoms_with_periods_or_modal_words_remain_positive(facets) -> None:
    fields = {"modality": "P", "actor": "clerk", "action": "file", "object": "notice"}
    fields.update(facets)
    ir = CanonicalRoundTripIR((CanonicalRule(**fields),))
    assert detect_surface_semantic_differences(ir, _render_association_ir(ir)) == ()


def test_interior_period_reordering_is_unresolved_without_guessing_sentence_boundaries() -> None:
    ir = CanonicalRoundTripIR((
        CanonicalRule("O", "agency", "file", "u.s._code_notice"),
        CanonicalRule("P", "court", "review", "notice"),
    ))
    assert detect_surface_semantic_differences(ir, _render_association_ir(ir)) == ()
    reordered = " ".join(decompile_rule(rule) for rule in reversed(ir.rules))
    differences = detect_surface_semantic_differences(ir, reordered)
    assert differences == ({"kind": "unresolved_rule_association",
        "reason": "ambiguous_period_boundaries", "expected_rule_count": 2,
        "scope": "frozen_surface_heuristic"},)


def test_missing_rule_explanations_use_empty_surface_not_the_remaining_paragraph() -> None:
    first = CanonicalRule("O", "agency", "file", "notice")
    second = CanonicalRule("O", "agency", "file", "report", exceptions=("emergency",))
    ir = CanonicalRoundTripIR((first, second))
    differences = detect_surface_semantic_differences(ir, decompile_rule(first))
    missing = [item for item in differences if item["kind"] == "dropped_facet"]
    assert {item["facet"] for item in missing} == {"actor", "action", "object", "exception"}
    assert all(item["association_unresolved"] is True for item in missing)
    assert all(item["rule_cid"] == second.rule_cid for item in missing)


@pytest.mark.parametrize("text", ("Agency must file notice..", "Agency must file notice"))
def test_unrecognized_separators_do_not_become_a_known_frozen_surface(text: str) -> None:
    ir = CanonicalRoundTripIR((CanonicalRule("O", "agency", "file", "notice"),))
    unresolved = _unresolved_association(ir, text)
    assert unresolved["reason"] == "noncanonical_rule_separators"


def test_single_rule_negative_explanations_keep_existing_kinds_and_heuristic_scope() -> None:
    differences = detect_surface_semantic_differences(
        CanonicalRoundTripIR((_rule(),)), "Company a must not file annual report."
    )
    assert {item["kind"] for item in differences} >= {
        "changed_polarity", "dropped_facet", "unresolved_rule_association"}
    assert all(item["association_unresolved"] is True for item in differences
               if item["kind"] in {"changed_polarity", "dropped_facet"})


@pytest.mark.parametrize("replace_one", (False, True))
def test_surface_association_handles_existing_ten_thousand_rule_bound(replace_one: bool) -> None:
    first = CanonicalRule("O", "agency", "file", "notice")
    second = CanonicalRule("O", "court", "publish", "report")
    ir = CanonicalRoundTripIR((first,) * 5000 + (second,) * 5000)
    first_count = 4999 if replace_one else 5000
    units = [decompile_rule(second)] * (10000 - first_count) + [decompile_rule(first)] * first_count
    text = " ".join(units)
    assert len(ir.rules) == len(units) == 10000
    if replace_one:
        unresolved = _unresolved_association(ir, text)
        assert len(unresolved["unmatched_rule_indices"]) == 1
        assert len(unresolved["unmatched_unit_indices"]) == 1
    else:
        assert detect_surface_semantic_differences(ir, text) == ()


def test_production_decompiler_still_has_no_benchmark_dependency() -> None:
    from ipfs_datasets_py.logic.legal_ir import canonical_decompiler as module

    source = inspect.getsource(module)
    assert "from benchmarks" not in source
    assert "import benchmarks" not in source


def test_structural_review_rejects_unbound_input() -> None:
    with pytest.raises(CanonicalContractError, match="CanonicalRoundTripIR"):
        decompile_structural_review({"rules": []})  # type: ignore[arg-type]


@pytest.mark.parametrize("actor,changed_actor", [("Maße", "Masse"), ("oﬃce", "office")],
    ids=("sharp_s_actor", "ligature_actor"))
def test_unicode_casefold_collisions_do_not_satisfy_distinct_opaque_actor(actor, changed_actor):
    original = CanonicalRule(modality="O", actor=actor, action="file", object="notice")
    changed = CanonicalRule(modality="O", actor=changed_actor, action="file", object="notice")
    ir = CanonicalRoundTripIR((original,))
    surface = decompile_rule(changed)
    assert surface != decompile_rule(original)
    differences = detect_surface_semantic_differences(ir, surface)
    assert differences, "changed opaque actor cannot become a known frozen surface"
    assert any(item.get("kind") == "dropped_facet" and item.get("facet") == "actor"
        and item.get("value") == actor for item in differences)
