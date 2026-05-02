"""Tests for decoder slot-grounding audit export records."""

from ipfs_datasets_py.logic.deontic.exports import (
    build_decoder_slot_grounding_audit_record,
    build_decoder_slot_grounding_audit_record_from_ir,
)
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


def test_decoder_slot_grounding_audit_accepts_grounded_required_slots():
    record = {
        "reconstruction_id": "reconstruction:test",
        "source_id": "deontic:test",
        "decoded_text": "The tenant must pay rent monthly.",
        "phrase_provenance": [
            {
                "text": "tenant",
                "source_slot": "actor",
                "spans": [[4, 10]],
                "fixed": False,
            },
            {
                "text": "must",
                "fixed": True,
                "spans": [],
            },
            {
                "text": "pay rent monthly",
                "source_slots": ["action"],
                "spans": [[16, 32]],
                "fixed": False,
            },
        ],
        "proof_ready": True,
        "requires_validation": False,
        "parser_warnings": [],
        "schema_version": "deterministic_deontic_v12",
    }

    audit = build_decoder_slot_grounding_audit_record(record)

    assert audit["decoder_slot_grounding_audit_id"].startswith(
        "decoder-slot-grounding:"
    )
    assert audit["source_id"] == "deontic:test"
    assert audit["required_slots"] == ["actor", "action"]
    assert audit["grounded_slots"] == ["actor", "action"]
    assert audit["missing_slots"] == []
    assert audit["ungrounded_slots"] == []
    assert audit["slot_grounding_complete"] is True
    assert audit["requires_validation"] is False
    assert audit["grounding_blockers"] == []
    assert audit["slot_status"]["actor"] == {
        "present": True,
        "grounded": True,
        "phrase_count": 1,
        "grounded_phrase_count": 1,
    }


def test_decoder_slot_grounding_audit_reports_missing_and_unspanned_slots():
    record = {
        "reconstruction_id": "reconstruction:test",
        "source_id": "deontic:test",
        "decoded_text": "The tenant must pay rent monthly.",
        "phrase_provenance": [
            {
                "text": "tenant",
                "slot": "actor",
                "span": [4, 10],
                "fixed": False,
            },
            {
                "text": "pay rent monthly",
                "slot": "action",
                "spans": [],
                "fixed": False,
            },
        ],
        "proof_ready": True,
        "requires_validation": False,
        "parser_warnings": [],
        "schema_version": "deterministic_deontic_v12",
    }

    audit = build_decoder_slot_grounding_audit_record(
        record,
        required_slots=("actor", "action", "recipient"),
    )

    assert audit["grounded_slots"] == ["actor"]
    assert audit["missing_slots"] == ["recipient"]
    assert audit["ungrounded_slots"] == ["action"]
    assert audit["slot_grounding_complete"] is False
    assert audit["requires_validation"] is True
    assert audit["grounding_blockers"] == [
        "missing_decoded_slot:recipient",
        "ungrounded_decoded_slot:action",
    ]


def test_decoder_slot_grounding_audit_from_ir_preserves_cross_reference_blocker():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    audit = build_decoder_slot_grounding_audit_record_from_ir(norm)

    assert audit["source_id"] == element["source_id"]
    assert audit["required_slots"] == ["actor", "action"]
    assert "cross_reference_requires_resolution" in element["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in element["llm_repair"]["reasons"]
    assert element["llm_repair"]["required"] is True
