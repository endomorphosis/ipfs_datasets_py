"""Tests for source-grounded LegalNormIR slot provenance audits."""

from ipfs_datasets_py.logic.deontic.ir import (
    LegalNormIR,
    legal_norm_ir_slot_provenance,
)
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


def test_ir_slot_provenance_reports_grounded_flat_and_nested_slots():
    element = extract_normative_elements(
        "The Director shall issue a permit within 10 days after application unless approval is denied."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    audit = legal_norm_ir_slot_provenance(norm)

    assert audit["source_id"] == element["source_id"]
    assert audit["support_span"] == element["support_span"]
    assert "actor" in audit["grounded_slots"]
    assert "modality" in audit["grounded_slots"]
    assert "action" in audit["grounded_slots"]
    assert "temporal_constraints" in audit["grounded_slots"]
    assert "exceptions" in audit["grounded_slots"]
    assert "cross_references" in audit["missing_slots"]
    assert "cross_references" not in audit["ungrounded_slots"]

    records = {record["slot"]: record for record in audit["slot_grounding"]}
    assert records["actor"]["status"] == "grounded"
    assert records["actor"]["spans"] == [element["field_spans"]["subject"]]
    assert records["action"]["spans"] == [element["field_spans"]["action"]]
    assert records["temporal_constraints"]["spans"]
    assert records["exceptions"]["spans"]
    assert records["cross_references"]["status"] == "missing"


def test_ir_slot_provenance_distinguishes_ungrounded_populated_slots():
    element = dict(extract_normative_elements("The tenant must pay rent monthly.")[0])
    element["mental_state"] = "knowingly"
    element["field_spans"] = dict(element["field_spans"])
    element["field_spans"].pop("mental_state", None)
    norm = LegalNormIR.from_parser_element(element)

    audit = legal_norm_ir_slot_provenance(norm, slots=("actor", "mental_state", "recipient"))

    records = {record["slot"]: record for record in audit["slot_grounding"]}
    assert records["actor"]["status"] == "grounded"
    assert records["mental_state"] == {
        "slot": "mental_state",
        "status": "ungrounded",
        "present": True,
        "grounded": False,
        "missing": False,
        "ungrounded": True,
        "spans": [],
        "value": "knowingly",
    }
    assert records["recipient"]["status"] == "missing"
    assert audit["ungrounded_slots"] == ["mental_state"]
    assert audit["missing_slots"] == ["recipient"]


def test_ir_slot_provenance_keeps_unresolved_numbered_reference_blocked():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    audit = legal_norm_ir_slot_provenance(norm)

    assert element["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in element["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in element["llm_repair"]["reasons"]
    assert norm.proof_ready is False
    assert "cross_reference_requires_resolution" in norm.blockers
    assert "exception_requires_scope_review" in norm.blockers
    assert "cross_references" in audit["grounded_slots"]
    assert "exceptions" in audit["grounded_slots"]

    records = {record["slot"]: record for record in audit["slot_grounding"]}
    assert records["cross_references"]["status"] == "grounded"
    assert records["exceptions"]["status"] == "grounded"
    assert records["cross_references"]["spans"]
    assert records["exceptions"]["spans"]
