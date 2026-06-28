from ipfs_datasets_py.logic.deontic.exports import (
    build_decoder_record_from_ir,
    build_reconstruction_slot_loss_record,
)
from ipfs_datasets_py.logic.deontic.ir import (
    LegalNormIR,
    legal_norm_ir_slot_provenance,
)


def test_reduced_structured_condition_text_is_grounded_for_decoder_quality() -> None:
    source_text = "Applicant shall file report if application is complete"
    norm = LegalNormIR.from_parser_element(
        {
            "schema_version": "test",
            "source_id": "deontic:test-reduced-condition",
            "text": source_text,
            "support_text": source_text,
            "support_span": [0, len(source_text)],
            "subject": ["Applicant"],
            "deontic_operator": "O",
            "action": ["file report"],
            "condition_details": [
                {
                    "type": "condition",
                    "clause_type": "if",
                    "normalized_text": "application is complete",
                }
            ],
        }
    )

    decoder_record = build_decoder_record_from_ir(norm)
    condition_phrases = [
        phrase
        for phrase in decoder_record["phrase_provenance"]
        if phrase["slot"] == "conditions"
    ]
    assert condition_phrases
    assert condition_phrases[0]["spans"] == [[31, 54]]

    slot_loss = build_reconstruction_slot_loss_record(
        norm.source_id,
        [decoder_record],
        required_slots=("actor", "modality", "action", "conditions"),
    )
    assert slot_loss["requires_validation"] is False
    assert "conditions" in slot_loss["coverage_summary"]["grounded_required_slots"]

    provenance = legal_norm_ir_slot_provenance(
        norm,
        slots=("actor", "modality", "action", "conditions"),
    )
    assert "conditions" in provenance["grounded_slots"]
    assert "conditions" not in provenance["ungrounded_slots"]
