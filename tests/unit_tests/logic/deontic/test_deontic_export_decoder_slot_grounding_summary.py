"""Tests for decoder slot-grounding batch export summaries."""

from ipfs_datasets_py.logic.deontic.exports import (
    build_decoder_slot_grounding_audit_record,
    build_decoder_slot_grounding_audit_records_from_irs,
    summarize_decoder_slot_grounding_audit_records,
)
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


def test_decoder_slot_grounding_summary_counts_missing_and_ungrounded_slots():
    complete = build_decoder_slot_grounding_audit_record(
        {
            "source_id": "deontic:complete",
            "reconstruction_id": "reconstruction:complete",
            "decoded_text": "Director shall issue a permit.",
            "phrase_provenance": [
                {"text": "Director", "slots": ["actor"], "spans": [[4, 12]]},
                {"text": "shall", "fixed": True},
                {"text": "issue a permit", "slots": ["action"], "spans": [[19, 33]]},
            ],
            "proof_ready": True,
            "requires_validation": False,
            "schema_version": "deterministic_deontic_v12",
        }
    )
    missing_action = build_decoder_slot_grounding_audit_record(
        {
            "source_id": "deontic:missing",
            "reconstruction_id": "reconstruction:missing",
            "decoded_text": "Director shall.",
            "phrase_provenance": [
                {"text": "Director", "slots": ["actor"], "spans": [[4, 12]]},
                {"text": "shall", "fixed": True},
            ],
            "proof_ready": False,
            "requires_validation": True,
            "schema_version": "deterministic_deontic_v12",
        }
    )
    ungrounded_actor = build_decoder_slot_grounding_audit_record(
        {
            "source_id": "deontic:ungrounded",
            "reconstruction_id": "reconstruction:ungrounded",
            "decoded_text": "Director shall issue a permit.",
            "phrase_provenance": [
                {"text": "Director", "slots": ["actor"], "spans": []},
                {"text": "shall", "fixed": True},
                {"text": "issue a permit", "slots": ["action"], "spans": [[19, 33]]},
            ],
            "proof_ready": True,
            "requires_validation": False,
            "schema_version": "deterministic_deontic_v12",
        }
    )

    summary = summarize_decoder_slot_grounding_audit_records(
        [complete, missing_action, ungrounded_actor]
    )

    assert summary["record_count"] == 3
    assert summary["proof_ready_count"] == 2
    assert summary["slot_grounding_complete_count"] == 1
    assert summary["requires_validation_count"] == 2
    assert summary["required_slots"] == ["actor", "action"]
    assert summary["grounded_slot_distribution"] == {"actor": 2, "action": 2}
    assert summary["missing_slot_distribution"] == {"action": 1}
    assert summary["ungrounded_slot_distribution"] == {"actor": 1}
    assert summary["grounding_blocker_distribution"] == {
        "missing_decoded_slot:action": 1,
        "ungrounded_decoded_slot:actor": 1,
    }
    assert summary["slot_grounding_complete_rate"] == 1 / 3
    assert summary["grounded_required_slot_rate"] == 4 / 6


def test_decoder_slot_grounding_audit_records_from_irs_preserve_source_grounding():
    elements = [
        extract_normative_elements("The tenant must pay rent monthly.")[0],
        extract_normative_elements("The permittee may appeal the decision.")[0],
    ]
    norms = [LegalNormIR.from_parser_element(element) for element in elements]

    records = build_decoder_slot_grounding_audit_records_from_irs(norms)
    summary = summarize_decoder_slot_grounding_audit_records(records)

    assert [record["source_id"] for record in records] == [
        element["source_id"] for element in elements
    ]
    assert all(record["reconstruction_id"].startswith("reconstruction:") for record in records)
    assert all(record["required_slots"] == ["actor", "action"] for record in records)
    assert all(record["slot_grounding_complete"] is True for record in records)
    assert all(record["requires_validation"] is False for record in records)
    assert summary["record_count"] == 2
    assert summary["slot_grounding_complete_count"] == 2
    assert summary["slot_grounding_complete_rate"] == 1.0
    assert summary["grounded_required_slot_rate"] == 1.0

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]
