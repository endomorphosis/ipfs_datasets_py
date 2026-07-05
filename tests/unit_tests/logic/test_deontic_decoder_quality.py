from types import SimpleNamespace

from ipfs_datasets_py.logic.bridge.deontic_norms import DeonticNormsBridgeAdapter
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


def test_bridge_hydrates_decoder_rows_from_standalone_legal_norm_ir() -> None:
    source_text = "The Secretary shall publish notice."
    norm = LegalNormIR.from_parser_element(
        {
            "schema_version": "test",
            "source_id": "deontic:test-standalone-ir",
            "text": source_text,
            "support_text": source_text,
            "support_span": [0, len(source_text)],
            "subject": ["Secretary"],
            "deontic_operator": "O",
            "action": ["publish notice"],
            "field_spans": {
                "subject": [4, 13],
                "deontic_operator": [14, 19],
                "action": [20, 34],
            },
        }
    )

    class NormOnlyConverter:
        def convert(self, text):
            return SimpleNamespace(
                success=True,
                metadata={"legal_norm_irs": [norm.to_dict()]},
            )

    report = DeonticNormsBridgeAdapter(converter=NormOnlyConverter()).evaluate(
        source_text
    )

    decoder_records = report.ir_document.views[
        "deontic_decoder_reconstructions"
    ].payload["records"]
    slot_loss = report.ir_document.views[
        "deontic_reconstruction_slot_loss"
    ].payload

    assert len(decoder_records) == 1
    assert decoder_records[0]["decoded_text"] == "Secretary shall publish notice."
    assert decoder_records[0]["requires_validation"] is False
    assert slot_loss["summary"]["grounded_required_slot_rate"] == 1.0
    assert slot_loss["records"][0]["requires_validation"] is False
    assert (
        report.round_trip.extra_losses["deontic_decoder_slot_loss"]
        == 0.0
    )
