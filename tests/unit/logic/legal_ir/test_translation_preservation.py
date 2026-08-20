"""Closed translation-class and undeclared-authority tests for PGIR-022."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.bridge.translation import (
    CLOSED_DIRECTION_CLASSES,
    CLOSED_EQUALITY_CRITERIA,
    CLOSED_FIDELITY_CLAIMS,
    CLOSED_PRESERVATION_CLASSES,
    CLOSED_RECONSTRUCTION_MODES,
    EqualityCriterion,
    FidelityClaim,
    ReconstructionMode,
    TRANSLATION_DIRECTION_CATALOG_CID,
    TRANSLATION_RECEIPT_INTERFACE,
    TranslationPreservationClass,
    TranslationReceipt,
    catalog_default_receipt,
    issue_translation_receipt,
    recorded_equality_criteria,
    recorded_roundtrip_directions,
    translation_direction,
    translation_direction_catalog,
    translation_direction_catalog_document,
)
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    CanonicalContractError,
    CanonicalRoundTripIR,
    CanonicalRule,
)
from ipfs_datasets_py.utils.cid_utils import cid_for_dag_json


def _ir() -> CanonicalRoundTripIR:
    return CanonicalRoundTripIR(
        (
            CanonicalRule(
                modality="O",
                actor="agency",
                action="publish",
                object="notice",
            ),
        )
    )


def _cid(label: str) -> str:
    return cid_for_dag_json({"fixture": label})


def test_closed_vocabularies_are_exactly_the_required_sets() -> None:
    assert CLOSED_PRESERVATION_CLASSES == (
        "lossless",
        "equisatisfiable",
        "over_approximation",
        "under_approximation",
        "heuristic",
        "unsupported",
    )
    assert CLOSED_RECONSTRUCTION_MODES == (
        "controlled_semantic_reconstruction",
        "structural_review",
        "style_paraphrase",
    )
    assert recorded_equality_criteria() == CLOSED_EQUALITY_CRITERIA
    assert set(CLOSED_DIRECTION_CLASSES) == {
        "source",
        "typed",
        "bridge",
        "family",
        "prover",
        "cnl",
        "trace",
    }
    assert CLOSED_FIDELITY_CLAIMS == ("none", "candidate", "semantic", "proof")


def test_every_required_direction_records_class_and_equality_criteria() -> None:
    catalog = translation_direction_catalog()
    document = translation_direction_catalog_document()
    ids = recorded_roundtrip_directions()

    assert document["catalog_cid"] == TRANSLATION_DIRECTION_CATALOG_CID
    assert document["direction_count"] == len(catalog) == len(ids)
    assert set(ids) >= {
        "A4-TYPED-002",
        "A4-TYPED-004",
        "A4-FAMILY-001",
        "A4-FAMILY-002",
        "A4-FAMILY-003",
        "A4-PROVER-001",
        "A4-PROVER-002",
        "A4-PROVER-003",
        "A4-PROVER-004",
        "A4-CNL-001",
        "A4-CNL-002",
        "A4-CNL-003",
        "A4-CNL-004",
        "PGIR-022-IR-CYCLE",
        "PGIR-022-STRUCTURAL-REVIEW",
    }
    for spec in catalog:
        assert spec.default_preservation_class.value in CLOSED_PRESERVATION_CLASSES
        assert spec.reconstruction_mode.value in CLOSED_RECONSTRUCTION_MODES
        assert spec.equality_criteria
        assert all(item.value in CLOSED_EQUALITY_CRITERIA for item in spec.equality_criteria)
        default = catalog_default_receipt(
            spec.direction_id,
            source_cid=_ir().ir_cid,
            target_cid=_cid(spec.direction_id),
        )
        assert default.direction_id == spec.direction_id
        assert default.authority_increase is False
        assert default.fidelity_claim is not FidelityClaim.PROOF


def test_unknown_direction_is_rejected() -> None:
    with pytest.raises(CanonicalContractError, match="unknown translation direction"):
        translation_direction("A4-UNDECLARED-999")


def test_heuristic_and_paraphrase_cannot_become_proof() -> None:
    with pytest.raises(CanonicalContractError, match="cannot carry proof"):
        issue_translation_receipt(
            direction_id="A4-CNL-001",
            reconstruction_mode=ReconstructionMode.STYLE_PARAPHRASE,
            preservation_class=TranslationPreservationClass.HEURISTIC,
            fidelity_claim=FidelityClaim.PROOF,
            source_cid=_ir().ir_cid,
            target_cid=_cid("t1"),
            declared_loss=("surface_paraphrase",),
        )


def test_paraphrase_cannot_claim_semantic_fidelity_without_recompilation() -> None:
    with pytest.raises(CanonicalContractError, match="recompilation"):
        issue_translation_receipt(
            direction_id="A4-CNL-001",
            reconstruction_mode=ReconstructionMode.STYLE_PARAPHRASE,
            preservation_class=TranslationPreservationClass.LOSSLESS,
            fidelity_claim=FidelityClaim.SEMANTIC,
            source_cid=_ir().ir_cid,
            target_cid=_cid("t1"),
        )


def test_lossless_rejects_undeclared_and_declared_loss() -> None:
    with pytest.raises(CanonicalContractError, match="cannot declare residual loss"):
        issue_translation_receipt(
            direction_id="PGIR-022-STRUCTURAL-REVIEW",
            reconstruction_mode=ReconstructionMode.STRUCTURAL_REVIEW,
            preservation_class=TranslationPreservationClass.LOSSLESS,
            fidelity_claim=FidelityClaim.NONE,
            source_cid=_ir().ir_cid,
            target_cid=_cid("review"),
            declared_loss=("silent_drop",),
        )
    with pytest.raises(CanonicalContractError, match="must declare residual loss"):
        issue_translation_receipt(
            direction_id="A4-FAMILY-001",
            reconstruction_mode=ReconstructionMode.CONTROLLED_SEMANTIC,
            preservation_class=TranslationPreservationClass.HEURISTIC,
            fidelity_claim=FidelityClaim.NONE,
            source_cid=_ir().ir_cid,
            target_cid=_cid("family"),
        )


def test_unsupported_cannot_claim_any_fidelity() -> None:
    with pytest.raises(CanonicalContractError, match="fidelity"):
        issue_translation_receipt(
            direction_id="A4-TYPED-002",
            reconstruction_mode=ReconstructionMode.STRUCTURAL_REVIEW,
            preservation_class=TranslationPreservationClass.UNSUPPORTED,
            fidelity_claim=FidelityClaim.CANDIDATE,
            source_cid=_ir().ir_cid,
            target_cid=_cid("typed-inverse"),
        )


def test_over_and_under_approximations_require_declared_loss() -> None:
    over = issue_translation_receipt(
        direction_id="PGIR-022-IR-CYCLE",
        reconstruction_mode=ReconstructionMode.CONTROLLED_SEMANTIC,
        preservation_class=TranslationPreservationClass.OVER_APPROXIMATION,
        fidelity_claim=FidelityClaim.NONE,
        source_cid=_ir().ir_cid,
        target_cid=_cid("l2-over"),
        declared_loss=("added_rule:agency/inspect/records",),
    )
    under = issue_translation_receipt(
        direction_id="PGIR-022-IR-CYCLE",
        reconstruction_mode=ReconstructionMode.CONTROLLED_SEMANTIC,
        preservation_class=TranslationPreservationClass.UNDER_APPROXIMATION,
        fidelity_claim=FidelityClaim.NONE,
        source_cid=_ir().ir_cid,
        target_cid=_cid("l2-under"),
        declared_loss=("dropped_rule:agency/publish/notice",),
    )
    assert over.preservation_class is TranslationPreservationClass.OVER_APPROXIMATION
    assert under.preservation_class is TranslationPreservationClass.UNDER_APPROXIMATION
    assert over.fidelity_claim is FidelityClaim.NONE
    assert TranslationReceipt.from_dict(over.to_dict()) == over


def test_receipt_is_cid_stable_and_rejects_authority_increase() -> None:
    receipt = issue_translation_receipt(
        direction_id="A4-CNL-001",
        reconstruction_mode=ReconstructionMode.STYLE_PARAPHRASE,
        preservation_class=TranslationPreservationClass.HEURISTIC,
        fidelity_claim=FidelityClaim.NONE,
        source_cid=_ir().ir_cid,
        target_cid=_cid("paraphrase"),
        declared_loss=("controlled_paraphrase_is_not_source_reconstruction",),
    )
    encoded = receipt.to_dict()
    assert encoded["interface"] == TRANSLATION_RECEIPT_INTERFACE
    assert encoded["authority_increase"] is False
    assert encoded["proof_authority"] is False
    assert encoded["receipt_cid"] == cid_for_dag_json(receipt.identity_payload())
    assert EqualityCriterion.SEMANTIC_RECOMPILE in receipt.equality_criteria
    tampered = dict(encoded)
    tampered["authority_increase"] = True
    with pytest.raises(CanonicalContractError, match="cannot increase authority"):
        TranslationReceipt.from_dict(tampered)
