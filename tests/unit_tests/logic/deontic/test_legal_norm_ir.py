"""Tests for the deterministic legal norm intermediate representation."""

from ipfs_datasets_py.logic.deontic import LegalNormIR, parser_element_to_ir
from ipfs_datasets_py.logic.deontic.exports import build_decoder_record_from_ir
from ipfs_datasets_py.logic.deontic.ir import legal_norm_ir_slot_provenance
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


def test_legal_norm_ir_recovers_section_application_actor_from_source_text() -> None:
    element = extract_normative_elements(
        "Sections 5102 and 5124 of this title shall apply to this section."
    )[0]

    ir = LegalNormIR.from_parser_element(element)
    provenance = legal_norm_ir_slot_provenance(ir, ("actor", "modality", "action"))

    assert element["subject"] == ["of this title"]
    assert ir.actor == "Sections 5102 and 5124 of this title"
    assert ir.action == "apply to this section"
    assert provenance["missing_slots"] == []
    assert provenance["ungrounded_slots"] == []
    assert provenance["grounded_slots"] == ["actor", "modality", "action"]
    actor_grounding = provenance["slot_grounding"][0]
    assert actor_grounding["slot"] == "actor"
    assert actor_grounding["value"] == "Sections 5102 and 5124 of this title"
    assert actor_grounding["spans"] == [[0, 36]]


def test_legal_norm_ir_carries_official_usc_leadin_citation_to_norm_sentence() -> None:
    elements = extract_normative_elements(
        "38 U.S.C. 1731: U.S.C. Title 38 - VETERANS' BENEFITS "
        "Sec. 1731 - Hospital care and medical services. "
        "The Secretary shall furnish hospital care and medical services which "
        "the Secretary determines are needed."
    )

    ir = LegalNormIR.from_parser_element(elements[0])

    assert len(elements) == 1
    assert elements[0]["canonical_citation"] == "38 U.S.C. 1731"
    assert elements[0]["section_context"] == {
        "title": "38",
        "section": "1731",
        "canonical_citation": "38 U.S.C. 1731",
    }
    assert ir.canonical_citation == "38 U.S.C. 1731"
    assert ir.modality == "O"
    assert ir.actor == "Secretary"
    assert ir.action.startswith("furnish hospital care and medical services")


def test_legal_norm_ir_preserves_full_institutional_actor_with_internal_the_phrase() -> None:
    elements = extract_normative_elements(
        "2 U.S.C. 5541: U.S.C. Title 2 - THE CONGRESS "
        "Sec. 5541 - Fees for internal delivery in House of Representatives. "
        "The Chief Administrative Officer of the House of Representatives may "
        "establish reasonable fees for delivery of mail matter and other items "
        "within the House of Representatives."
    )

    ir = LegalNormIR.from_parser_element(elements[0])
    provenance = legal_norm_ir_slot_provenance(ir, ("actor", "modality", "action"))

    assert ir.actor == "Chief Administrative Officer of the House of Representatives"
    assert ir.field_spans["subject"] == [4, 64]
    assert provenance["missing_slots"] == []
    assert provenance["ungrounded_slots"] == []
    assert provenance["slot_grounding"][0]["value"] == (
        "Chief Administrative Officer of the House of Representatives"
    )


def test_legal_norm_ir_recovers_clipped_passive_contribution_actor() -> None:
    elements = extract_normative_elements(
        "The total amount contributed by the Secretary of Defense in any fiscal "
        "year for the common-funded budgets of NATO may be an amount in excess "
        "of the maximum amount that would otherwise be applicable to those "
        "contributions in such fiscal year under the fiscal year 1998 baseline "
        "limitation."
    )

    ir = LegalNormIR.from_parser_element(elements[0])
    provenance = legal_norm_ir_slot_provenance(ir, ("actor", "modality", "action"))

    assert elements[0]["subject"] == [
        "Defense in any fiscal year for the common-funded budgets of NATO"
    ]
    assert ir.actor == "Secretary of Defense"
    assert ir.field_spans["subject"] == [36, 56]
    assert provenance["missing_slots"] == []
    assert provenance["ungrounded_slots"] == []
    assert provenance["slot_grounding"][0]["value"] == "Secretary of Defense"


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


def test_legal_norm_ir_merges_persisted_formula_readiness_from_top_level_row() -> None:
    source_text = "The Secretary shall publish notice except as provided in section 552."
    exception_start = source_text.index("except")
    reference_start = source_text.index("section 552")
    element = {
        "schema_version": "legal_norm_ir-v1",
        "source_id": "legacy:deontic:persisted-top-level-readiness",
        "text": source_text,
        "support_text": source_text,
        "support_span": [0, len(source_text)],
        "norm_type": "obligation",
        "deontic_operator": "shall",
        "subject": ["Secretary"],
        "action": ["publish notice"],
        "parser_warnings": [
            "cross_reference_requires_resolution",
            "exception_requires_scope_review",
        ],
        "quality": {
            "export_readiness": {
                "blockers": [
                    "cross_reference_requires_resolution",
                    "exception_requires_scope_review",
                ],
            },
        },
        "export_readiness": {
            "formula_proof_ready": True,
            "formula_requires_validation": False,
            "formula_repair_required": False,
            "deterministic_resolution": {
                "type": "resolved_same_document_reference_exception",
            },
        },
        "field_spans": {
            "subject": [4, 13],
            "modality": [14, 19],
            "action": [20, 34],
        },
        "exception_details": [
            {
                "value": "except as provided in section 552",
                "span": [exception_start, len(source_text) - 1],
            },
        ],
        "cross_reference_details": [
            {
                "value": "section 552",
                "span": [reference_start, reference_start + len("section 552")],
            },
        ],
    }

    ir = LegalNormIR.from_parser_element(element)
    decoder_record = build_decoder_record_from_ir(ir)

    assert ir.quality.export_readiness["blockers"] == [
        "cross_reference_requires_resolution",
        "exception_requires_scope_review",
    ]
    assert ir.quality.export_readiness["formula_proof_ready"] is True
    assert decoder_record["missing_slots"] == []
    assert decoder_record["requires_validation"] is False
    assert decoder_record["decoder_validation_resolution"]["type"] == (
        "formula_deterministic_readiness"
    )


def test_legal_norm_ir_recovers_clipped_negative_action_from_field_span() -> None:
    source_text = (
        "The Secretary shall not waive, under subsection (b), the non-Federal "
        "share requirement for any program."
    )
    element = {
        "schema_version": "legal_norm_ir-v1",
        "source_id": "legacy:deontic:clipped-shall-not",
        "text": source_text,
        "support_text": source_text,
        "support_span": [0, len(source_text)],
        "norm_type": "prohibition",
        "deontic_operator": "F",
        "subject": ["Secretary"],
        "action": ["waive,"],
        "field_spans": {
            "subject": [4, 13],
            "modal": [14, 23],
            "action": [24, len(source_text) - 1],
        },
        "promotable_to_theorem": True,
        "export_readiness": {"blockers": []},
    }

    ir = LegalNormIR.from_parser_element(element)
    audit = legal_norm_ir_slot_provenance(ir, ("actor", "modality", "action"))

    assert ir.modality == "F"
    assert ir.action == (
        "waive, under subsection (b), the non-Federal share requirement for any program"
    )
    assert audit["missing_slots"] == []
    assert audit["ungrounded_slots"] == []


def test_legal_norm_ir_recovers_unlawful_for_actor_action_and_modality() -> None:
    source_text = (
        "It shall be unlawful for any person, partnership, or corporation to "
        "disseminate any false advertisement."
    )
    element = {
        "schema_version": "legal_norm_ir-v1",
        "source_id": "legacy:deontic:unlawful-for",
        "text": source_text,
        "support_text": source_text,
        "support_span": [0, len(source_text)],
        "norm_type": "obligation",
        "deontic_operator": "O",
        "subject": ["It"],
        "action": [
            "be unlawful for any person, partnership, or corporation to "
            "disseminate any false advertisement"
        ],
        "field_spans": {
            "subject": [0, 2],
            "modal": [3, 8],
            "action": [9, len(source_text) - 1],
        },
        "export_readiness": {"proof_ready": True, "blockers": []},
    }

    ir = LegalNormIR.from_parser_element(element)
    audit = legal_norm_ir_slot_provenance(ir, ("actor", "modality", "action"))

    assert ir.norm_type == "prohibition"
    assert ir.modality == "F"
    assert ir.actor == "any person, partnership, or corporation"
    assert ir.action == "disseminate any false advertisement"
    assert ir.proof_ready is True
    assert audit["missing_slots"] == []
    assert audit["ungrounded_slots"] == []
    assert audit["slot_grounding"][0]["spans"] == [[25, 64]]
    assert audit["slot_grounding"][2]["spans"] == [[68, 103]]


def test_legal_norm_ir_recovers_source_text_conditions_for_reduced_rows() -> None:
    source_text = (
        "The Secretary may waive the requirement if such application is "
        "otherwise approvable."
    )
    element = {
        "schema_version": "legal_norm_ir-v1",
        "source_id": "legacy:deontic:source-condition",
        "text": source_text,
        "support_text": source_text,
        "support_span": [0, len(source_text)],
        "norm_type": "permission",
        "deontic_operator": "may",
        "subject": ["Secretary"],
        "action": ["waive the requirement"],
        "field_spans": {
            "subject": [4, 13],
            "modal": [14, 17],
            "action": [18, 39],
        },
        "promotable_to_theorem": True,
        "export_readiness": {"blockers": []},
    }

    ir = LegalNormIR.from_parser_element(element)

    assert ir.modality == "P"
    assert ir.conditions == [
        {
            "type": "condition",
            "clause_type": "if",
            "raw_text": "if such application is otherwise approvable",
            "normalized_text": "such application is otherwise approvable",
            "span": [43, 83],
            "clause_span": [40, 83],
            "value": "such application is otherwise approvable",
        }
    ]
