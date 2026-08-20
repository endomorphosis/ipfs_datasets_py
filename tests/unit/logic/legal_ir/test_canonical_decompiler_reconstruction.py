"""Reconstruction-mode and adversarial decompilation tests for PGIR-022."""

from __future__ import annotations

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


def test_production_decompiler_still_has_no_benchmark_dependency() -> None:
    from ipfs_datasets_py.logic.legal_ir import canonical_decompiler as module

    source = inspect.getsource(module)
    assert "from benchmarks" not in source
    assert "import benchmarks" not in source


def test_structural_review_rejects_unbound_input() -> None:
    with pytest.raises(CanonicalContractError, match="CanonicalRoundTripIR"):
        decompile_structural_review({"rules": []})  # type: ignore[arg-type]
