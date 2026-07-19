from ipfs_datasets_py.logic.deontic.ir import (
    LegalNormIR,
    legal_norm_ir_slot_provenance,
)
from ipfs_datasets_py.logic.deontic.exports import (
    build_deterministic_parser_capability_profile_record,
)
from ipfs_datasets_py.logic.deontic.prover_syntax import (
    build_prover_syntax_records_from_ir,
)
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


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

def test_subject_to_obligation_maps_to_conditional_normative_family():
    text = (
        "46 U.S.C. 53507. Nontaxation of deposits. Subject to subsection (b), "
        "taxable income shall be determined without regard to deposits."
    )
    element = {
        "schema_version": "legal-norm-ir/v1",
        "source_id": "us-code-46-53507-test",
        "canonical_citation": "46 U.S.C. 53507",
        "text": text,
        "support_text": text,
        "source_span": [0, len(text)],
        "support_span": [0, len(text)],
        "norm_type": "obligation",
        "deontic_operator": "O",
        "subject": ["taxable income"],
        "action": ["be determined without regard to deposits"],
        "field_spans": {
            "subject": [
                text.index("taxable income"),
                text.index("taxable income") + len("taxable income"),
            ],
            "modality": [text.index("shall"), text.index("shall") + len("shall")],
            "action": [
                text.index("be determined"),
                text.index("deposits.") + len("deposits"),
            ],
        },
    }

    norm = LegalNormIR.from_parser_element(element)

    assert norm.conditions[0]["clause_type"] == "subject to"
    assert norm.conditions[0]["value"] == "subsection (b)"
    assert norm.semantic_family == "conditional_normative"
    assert norm.to_dict()["semantic_family"] == "conditional_normative"

    prover_records = build_prover_syntax_records_from_ir(
        norm,
        targets=("frame_logic", "deontic_fol"),
    )
    assert {
        record["target_components"]["semantic_formula_family"]
        for record in prover_records
    } == {"conditional_normative"}

    capability = build_deterministic_parser_capability_profile_record(norm)
    assert capability["capability_family"] == "conditional_normative"
    assert "conditions" in capability["checked_slots"]


def test_enumerated_conditional_obligation_keeps_conditional_normative_family():
    text = (
        "(1) Subject to subsection (b), the Secretary shall provide assistance "
        "to eligible veterans."
    )
    element = {
        "schema_version": "legal-norm-ir/v1",
        "source_id": "us-code-38-118-test-enum",
        "text": text,
        "support_text": text,
        "source_span": [0, len(text)],
        "support_span": [0, len(text)],
        "parent_source_id": "us-code-38-118-test",
        "enumeration_label": "(1)",
        "norm_type": "obligation",
        "deontic_operator": "O",
        "subject": ["the Secretary"],
        "action": ["provide assistance to eligible veterans"],
        "field_spans": {
            "subject": [
                text.index("the Secretary"),
                text.index("the Secretary") + len("the Secretary"),
            ],
            "modality": [text.index("shall"), text.index("shall") + len("shall")],
            "action": [
                text.index("provide assistance"),
                text.index("eligible veterans") + len("eligible veterans"),
            ],
        },
    }

    norm = LegalNormIR.from_parser_element(element)
    capability = build_deterministic_parser_capability_profile_record(norm)

    assert norm.is_enumerated_child is True
    assert norm.semantic_family == "conditional_normative"
    assert capability["capability_family"] == "conditional_normative"
    assert capability["decoded_slots"] == ["actor", "modality", "action", "conditions"]
    assert capability["decoder_requires_validation"] is False


def test_editorial_renumbered_and_transferred_notes_expose_lifecycle_targets():
    text = (
        "42 U.S.C. 2751.: §2751. Transferred Editorial Notes Codification "
        "Section 2751, originally enacted as section 121 of Pub. L. 88-452, "
        "was renumbered section 441 of Pub. L. 89-329 and transferred to "
        "section 1087-51 of Title 20, Education."
    )

    norms = [
        LegalNormIR.from_parser_element(element)
        for element in extract_normative_elements(text, "statute")
    ]

    renumbered = next(norm for norm in norms if norm.action.startswith("renumbered"))
    transferred = next(
        norm for norm in norms if norm.action.startswith("transferred to section")
    )

    assert renumbered.norm_type == "instrument_lifecycle"
    assert renumbered.recipient.startswith("section 441")
    assert renumbered.field_spans["recipient"]
    assert transferred.recipient == "section 1087-51 of Title 20, Education"
    assert transferred.action == "transferred to section 1087-51 of Title 20, Education"

    provenance = legal_norm_ir_slot_provenance(
        transferred,
        slots=("actor", "action", "recipient"),
    )
    assert provenance["missing_slots"] == []
    assert provenance["ungrounded_slots"] == []


def test_passive_preference_grant_recovers_beneficiary_recipient():
    text = (
        "43 U.S.C. 433a.: §433a. Preference of needy families It is declared "
        "to be the policy of the Congress that, in the opening to entry of "
        "newly irrigated public lands, preference shall be given to families "
        "who have no other means of earning a livelihood, or..."
    )

    [norm] = [
        LegalNormIR.from_parser_element(element)
        for element in extract_normative_elements(text, "statute")
    ]

    assert norm.modality == "O"
    assert norm.recipient == "families who have no other means of earning a livelihood"
    provenance = legal_norm_ir_slot_provenance(
        norm,
        slots=("actor", "modality", "action", "recipient"),
    )
    assert provenance["missing_slots"] == []
    assert provenance["ungrounded_slots"] == []
