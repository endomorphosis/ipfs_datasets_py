from ipfs_datasets_py.logic.deontic.ir import (
    LegalNormIR,
    legal_norm_ir_slot_provenance,
)


def test_modal_clause_inferred_modality_keeps_source_span_grounded():
    text = (
        "Sec. 1731. Assistance for adaptive sports programs. "
        "The Secretary is authorized and directed to make grants to eligible entities."
    )
    modal_start = text.index("is authorized and directed to")
    element = {
        "schema_version": "legal-norm-ir/v1",
        "source_id": "us-code-38-1731-test",
        "text": text,
        "support_text": text,
        "source_span": [0, len(text)],
        "support_span": [0, len(text)],
        "subject": ["Assistance for adaptive sports programs The Secretary"],
        "action": ["make grants to eligible entities"],
        "field_spans": {
            "action": [
                text.index("make grants"),
                text.index("eligible entities") + len("eligible entities"),
            ],
        },
    }

    norm = LegalNormIR.from_parser_element(element)

    assert norm.modality == "O"
    assert norm.actor == "The Secretary"
    assert norm.field_spans["modality"] == [
        modal_start,
        modal_start + len("is authorized and directed to"),
    ]
    assert norm.field_spans["deontic_operator"] == norm.field_spans["modality"]

    provenance = legal_norm_ir_slot_provenance(
        norm,
        slots=("actor", "modality", "action"),
    )
    assert provenance["missing_slots"] == []
    assert provenance["ungrounded_slots"] == []
    assert provenance["grounded_slots"] == ["actor", "modality", "action"]
