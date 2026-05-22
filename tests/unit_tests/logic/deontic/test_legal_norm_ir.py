"""Tests for the deterministic legal norm intermediate representation."""

from ipfs_datasets_py.logic.deontic import LegalNormIR, parser_element_to_ir
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


def test_legal_norm_ir_preserves_core_parser_slots() -> None:
    elements = extract_normative_elements(
        "The Secretary shall submit a report to Congress within 30 days unless disclosure is classified."
    )

    ir = LegalNormIR.from_parser_element(elements[0])

    assert ir.schema_version == elements[0]["schema_version"]
    assert ir.source_id == elements[0]["source_id"]
    assert ir.modality == "O"
    assert ir.norm_type == "obligation"
    assert ir.actor == "Secretary"
    assert ir.actor_type == "government_actor"
    assert ir.action == "submit a report to Congress"
    assert ir.action_verb == "submit"
    assert ir.action_object == "a report to Congress"
    assert ir.recipient == "Congress"
    assert ir.temporal_constraints[0]["type"] == "deadline"
    assert ir.temporal_constraints[0]["quantity"] == 30
    assert ir.temporal_constraints[0]["unit"] == "day"
    assert ir.exceptions[0]["normalized_text"] == "disclosure is classified"
    assert ir.support_span.to_list() == elements[0]["support_span"]
    assert ir.to_dict()["proof_ready"] is False
    assert "exception_requires_scope_review" in ir.blockers


def test_parser_element_to_ir_function_is_deterministic() -> None:
    element = extract_normative_elements("The tenant must pay rent monthly.")[0]

    first = parser_element_to_ir(element).to_dict()
    second = parser_element_to_ir(element).to_dict()

    assert first == second
    assert first["actor"] == "tenant"
    assert first["action"] == "pay rent monthly"
    assert first["quality"]["promotable_to_theorem"] is True
    assert first["proof_ready"] is True
    assert first["blockers"] == []


def test_legal_norm_ir_recovers_textual_modalities_from_legacy_rows() -> None:
    base = {
        "schema_version": "legal_norm_ir-v1",
        "source_id": "legacy:modal",
        "subject": ["agency"],
        "action": ["publish notice"],
        "text": "The agency shall publish notice.",
        "support_text": "The agency shall publish notice.",
        "support_span": [0, 31],
    }
    rows = [
        ({**base, "deontic_operator": "shall", "norm_type": ""}, "O"),
        ({**base, "modality": "permission", "norm_type": ""}, "P"),
        ({**base, "norm_type": "violation"}, "F"),
        ({**base, "deontic_operator": "", "norm_type": "", "text": "The agency shall not disclose records."}, "F"),
    ]

    for row, expected in rows:
        ir = LegalNormIR.from_parser_element(row)
        assert ir.modality == expected


def test_legal_norm_ir_roundtrip_from_typed_dict_preserves_quality_and_slot_records() -> None:
    element = extract_normative_elements(
        "The Secretary shall submit a report to Congress within 30 days."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    rehydrated = LegalNormIR.from_parser_element(norm.to_dict())

    assert norm.proof_ready is True
    assert rehydrated.proof_ready is True
    assert rehydrated.quality.promotable_to_theorem is True
    assert rehydrated.quality.export_readiness.get("proof_ready") is True
    assert rehydrated.source_text == norm.source_text
    assert rehydrated.temporal_constraints
    assert rehydrated.temporal_constraints[0].get("type") == "deadline"
    assert rehydrated.temporal_constraints[0].get("quantity") == 30


def test_legal_norm_ir_recovers_modal_slots_from_prompt_context_detail_rows() -> None:
    parsed = extract_normative_elements(
        "The Director is authorized and directed to adopt rules."
    )[0]
    detail = {
        "schema_version": parsed["schema_version"],
        "source_id": f"{parsed['source_id']}:detail",
        "text": parsed["text"],
        "support_text": parsed["support_text"],
        "support_span": parsed["support_span"],
        "norm_type": "",
        "modality": None,
        "deontic_operator": "",
        "subject": list(parsed["subject"]),
        "action": list(parsed["action"]),
        "llm_repair": {
            "required": True,
            "reasons": ["legacy_detail_projection"],
            "prompt_context": {
                "source_text": parsed["text"],
                "norm_type": parsed["norm_type"],
                "deontic_operator": parsed["deontic_operator"],
            },
        },
    }

    ir = LegalNormIR.from_parser_element(detail)

    assert ir.norm_type == "obligation"
    assert ir.modality == "O"
    assert ir.canonical_modality == "O"


def test_legal_norm_ir_decoder_validation_gate_distinguishes_cross_reference_warning_classes() -> None:
    cross_reference_only = extract_normative_elements(
        "This section applies to food carts."
    )[0]
    unresolved_exception = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]

    cross_reference_only_ir = LegalNormIR.from_parser_element(cross_reference_only)
    unresolved_exception_ir = LegalNormIR.from_parser_element(unresolved_exception)

    assert "cross_reference_requires_resolution" in cross_reference_only_ir.blockers
    assert cross_reference_only_ir.decoder_requires_validation is False

    assert "cross_reference_requires_resolution" in unresolved_exception_ir.blockers
    assert "exception_requires_scope_review" in unresolved_exception_ir.blockers
    assert unresolved_exception_ir.decoder_requires_validation is True
