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
