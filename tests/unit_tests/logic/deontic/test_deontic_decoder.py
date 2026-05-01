"""Tests for deterministic LegalNormIR reconstruction."""

from dataclasses import replace

from ipfs_datasets_py.logic.deontic.decoder import decode_legal_norm_ir
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


def _decode(text: str):
    element = extract_normative_elements(text)[0]
    norm = LegalNormIR.from_parser_element(element)
    return element, norm, decode_legal_norm_ir(norm)


def test_decoder_reconstructs_simple_obligation_without_temporal_duplication():
    element, norm, decoded = _decode("The tenant must pay rent monthly.")

    assert decoded.text == "Tenant shall pay rent monthly."
    assert decoded.source_id == element["source_id"]
    assert decoded.support_span == element["support_span"]
    assert decoded.parser_warnings == []
    assert decoded.missing_slots == []
    assert [phrase.slot for phrase in decoded.phrases] == ["actor", "modality", "action"]
    assert decoded.phrases[0].spans
    assert decoded.phrases[1].slot == "modality"
    assert decoded.phrases[2].text == norm.action


def test_decoder_reconstructs_separate_temporal_deadline_once():
    element, norm, decoded = _decode(
        "The Director shall issue a permit within 10 days after application."
    )

    assert decoded.text == "Director shall issue a permit within 10 days after application."
    assert decoded.text.count("within 10 days after application") == 1
    assert decoded.text.count("issue a permit") == 1

    temporal_phrase = next(
        phrase for phrase in decoded.phrases if phrase.slot == "temporal_constraints"
    )
    assert temporal_phrase.text == "within 10 days after application"
    assert temporal_phrase.spans == [element["temporal_constraint_details"][0]["span"]]
    assert norm.temporal_constraints[0]["value"] == "10 days after application"


def test_decoder_preserves_unresolved_reference_exception_without_clearing_repair():
    element, norm, decoded = _decode(
        "The Secretary shall publish the notice except as provided in section 552."
    )

    assert decoded.text == (
        "Secretary shall publish the notice except as provided in section 552."
    )
    assert "cross_reference_requires_resolution" in decoded.parser_warnings
    assert "exception_requires_scope_review" in decoded.parser_warnings
    assert norm.proof_ready is False
    assert "cross_reference_requires_resolution" in norm.blockers
    assert element["llm_repair"]["required"] is True

    exception_phrase = next(phrase for phrase in decoded.phrases if phrase.slot == "exceptions")
    assert exception_phrase.text == "as provided in section 552"
    assert exception_phrase.spans == [element["exception_details"][0]["span"]]


def test_decoder_makes_lossy_temporal_ir_visible():
    _, norm, decoded = _decode(
        "The Director shall issue a permit within 10 days after application."
    )

    lossy_norm = replace(norm, temporal_constraints=[])
    lossy_decoded = decode_legal_norm_ir(lossy_norm)

    assert decoded.text == "Director shall issue a permit within 10 days after application."
    assert lossy_decoded.text == "Director shall issue a permit."
    assert decoded.text != lossy_decoded.text
    assert all(phrase.slot != "temporal_constraints" for phrase in lossy_decoded.phrases)


def test_decoder_renders_scope_and_lifecycle_norm_types_from_ir_slots():
    _, applicability, applicability_decoded = _decode("This section applies to food carts.")
    _, exemption, exemption_decoded = _decode("A permit is not required for emergency work.")
    _, lifecycle, lifecycle_decoded = _decode("The license is valid for 30 days.")

    assert applicability_decoded.text == "This section applies to food carts."
    assert applicability.modality == "APP"
    assert [phrase.slot for phrase in applicability_decoded.phrases] == [
        "actor",
        "applicability_connector",
        "action",
    ]
    assert applicability_decoded.phrases[1].fixed is True

    assert exemption_decoded.text == "Emergency work is exempt from permit."
    assert exemption.modality == "EXEMPT"

    assert lifecycle_decoded.text == "License is valid for 30 days."
    assert lifecycle.modality == "LIFE"
