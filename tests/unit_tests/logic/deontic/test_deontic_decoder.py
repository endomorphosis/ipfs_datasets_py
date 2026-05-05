"""Tests for deterministic LegalNormIR reconstruction."""

from dataclasses import replace

from ipfs_datasets_py.logic.deontic.decoder import decode_legal_norm_ir
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


def _decode(text: str):
    element = extract_normative_elements(text)[0]
    norm = LegalNormIR.from_parser_element(element)
    return element, norm, decode_legal_norm_ir(norm)


def test_decoder_reconstructs_simple_obligation_without_temporal_duplication():
    element, norm, decoded = _decode("The tenant must pay rent monthly.")

    assert decoded.text == "Tenant shall pay rent monthly."
    assert decoded.source_id == element["source_id"]
    assert decoded.support_span == element["support_span"]
    assert decoded.parser_warnings == []
    assert decoded.missing_slots == []
    assert [phrase.slot for phrase in decoded.phrases] == ["actor", "modality", "action"]
    assert decoded.phrases[0].spans
    assert decoded.phrases[1].slot == "modality"
    assert decoded.phrases[2].text == norm.action


def test_decoder_reconstructs_separated_mental_state_slot_with_provenance():
    _, norm, _ = _decode("The applicant shall file the report.")
    mens_rea_norm = replace(
        norm,
        mental_state="knowingly",
        action="file the report",
        field_spans={
            **norm.field_spans,
            "mental_state": [20, 29],
            "action": [30, 45],
        },
    )

    decoded = decode_legal_norm_ir(mens_rea_norm)

    assert decoded.text == "Applicant shall knowingly file the report."
    assert [phrase.slot for phrase in decoded.phrases] == [
        "actor",
        "modality",
        "mental_state",
        "action",
    ]
    mental_state_phrase = decoded.phrases[2]
    assert mental_state_phrase.text == "knowingly"
    assert mental_state_phrase.spans == [[20, 29]]

    already_encoded = replace(mens_rea_norm, action="knowingly file the report")
    already_decoded = decode_legal_norm_ir(already_encoded)

    assert already_decoded.text == "Applicant shall knowingly file the report."
    assert [phrase.slot for phrase in already_decoded.phrases] == [
        "actor",
        "modality",
        "mental_state",
        "action",
    ]


def test_decoder_splits_source_grounded_mental_state_from_action_phrase():
    element, norm, decoded = _decode("The inspector shall knowingly approve the discharge.")

    assert norm.mental_state == "knowingly"
    assert norm.action == "knowingly approve the discharge"
    assert decoded.text == "Inspector shall knowingly approve the discharge."
    assert [phrase.slot for phrase in decoded.phrases] == [
        "actor",
        "modality",
        "mental_state",
        "action",
    ]
    assert decoded.phrases[2].spans == [[20, 29]]
    assert decoded.phrases[3].text == "approve the discharge"
    assert decoded.phrases[3].spans == [[30, 51]]
    assert element["field_spans"]["action"] == [20, 51]


def test_decoder_reconstructs_separated_recipient_slot_with_provenance():
    _, norm, _ = _decode("The Director shall issue a permit.")
    recipient_norm = replace(
        norm,
        action="provide notice",
        recipient="the applicant",
        field_spans={
            **norm.field_spans,
            "action": [19, 33],
            "action_recipient": [37, 50],
        },
    )

    decoded = decode_legal_norm_ir(recipient_norm)

    assert decoded.text == "Director shall provide notice to the applicant."
    assert [phrase.slot for phrase in decoded.phrases] == [
        "actor",
        "modality",
        "action",
        "recipient_connector",
        "recipient",
    ]
    recipient_phrase = decoded.phrases[-1]
    assert recipient_phrase.text == "the applicant"
    assert recipient_phrase.spans == [[37, 50]]


def test_decoder_reconstructs_separate_temporal_deadline_once():
    element, norm, decoded = _decode(
        "The Director shall issue a permit within 10 days after application."
    )

    assert decoded.text == "Director shall issue a permit within 10 days after application."
    assert decoded.text.count("within 10 days after application") == 1
    assert decoded.text.count("issue a permit") == 1

    temporal_phrase = next(
        phrase for phrase in decoded.phrases if phrase.slot == "temporal_constraints"
    )
    assert temporal_phrase.text == "within 10 days after application"
    assert temporal_phrase.spans == [element["temporal_constraint_details"][0]["span"]]
    assert norm.temporal_constraints[0]["value"] == "10 days after application"


def test_decoder_does_not_duplicate_recipient_already_in_action_slot():
    _, norm, _ = _decode("The Director shall issue a permit.")
    recipient_norm = replace(
        norm,
        action="provide notice to the applicant",
        recipient="to the applicant",
    )

    decoded = decode_legal_norm_ir(recipient_norm)

    assert decoded.text == "Director shall provide notice to the applicant."
    assert [phrase.slot for phrase in decoded.phrases] == ["actor", "modality", "action"]


def test_decoder_preserves_unresolved_reference_exception_without_clearing_repair():
    element, norm, decoded = _decode(
        "The Secretary shall publish the notice except as provided in section 552."
    )

    assert decoded.text == (
        "Secretary shall publish the notice except as provided in section 552."
    )
    assert "cross_reference_requires_resolution" in decoded.parser_warnings
    assert "exception_requires_scope_review" in decoded.parser_warnings
    assert norm.proof_ready is False
    assert "cross_reference_requires_resolution" in norm.blockers
    assert element["llm_repair"]["required"] is True

    exception_phrase = next(phrase for phrase in decoded.phrases if phrase.slot == "exceptions")
    assert exception_phrase.text == "as provided in section 552"
    assert exception_phrase.spans == [element["exception_details"][0]["span"]]
    reference_phrase = next(
        phrase for phrase in decoded.phrases if phrase.slot == "cross_references"
    )
    assert reference_phrase.text == "section 552"
    assert reference_phrase.spans == [element["cross_reference_details"][0]["span"]]
    assert reference_phrase.provenance_only is True


def test_decoder_preserves_precedence_override_with_provenance():
    element, norm, decoded = _decode(
        "Notwithstanding section 5.01.020, the Director may issue a variance."
    )

    assert decoded.text == (
        "Notwithstanding section 5.01.020, Director may issue a variance."
    )
    assert norm.proof_ready is False
    assert element["llm_repair"]["required"] is False
    assert element["llm_repair"]["deterministic_resolution"]["type"] == (
        "pure_precedence_override"
    )

    override_phrase = next(phrase for phrase in decoded.phrases if phrase.slot == "overrides")
    assert override_phrase.text == "section 5.01.020"
    assert override_phrase.spans == [element["override_clause_details"][0]["span"]]
    assert [phrase.slot for phrase in decoded.phrases[:3]] == [
        "override_connector",
        "overrides",
        "override_punctuation",
    ]
    reference_phrase = next(
        phrase for phrase in decoded.phrases if phrase.slot == "cross_references"
    )
    assert reference_phrase.text == "section 5.01.020"
    assert reference_phrase.provenance_only is True

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_decoder_makes_lossy_temporal_ir_visible():
    _, norm, decoded = _decode(
        "The Director shall issue a permit within 10 days after application."
    )

    lossy_norm = replace(norm, temporal_constraints=[])
    lossy_decoded = decode_legal_norm_ir(lossy_norm)

    assert decoded.text == "Director shall issue a permit within 10 days after application."
    assert lossy_decoded.text == "Director shall issue a permit."
    assert decoded.text != lossy_decoded.text
    assert all(phrase.slot != "temporal_constraints" for phrase in lossy_decoded.phrases)


def test_decoder_renders_scope_and_lifecycle_norm_types_from_ir_slots():
    _, applicability, applicability_decoded = _decode("This section applies to food carts.")
    _, exemption, exemption_decoded = _decode("A permit is not required for emergency work.")
    _, lifecycle, lifecycle_decoded = _decode("The license is valid for 30 days.")

    assert applicability_decoded.text == "This section applies to food carts."
    assert applicability.modality == "APP"
    assert [phrase.slot for phrase in applicability_decoded.phrases] == [
        "actor",
        "applicability_connector",
        "action",
        "cross_references",
    ]
    assert applicability_decoded.phrases[1].fixed is True
    assert applicability_decoded.phrases[-1].provenance_only is True

    assert exemption_decoded.text == "Emergency work is exempt from permit."
    assert exemption.modality == "EXEMPT"

    assert lifecycle_decoded.text == "License is valid for 30 days."
    assert lifecycle.modality == "LIFE"


def test_decoder_renders_penalty_clauses_without_duplicate_condition_or_deadline():
    examples = [
        (
            "A violation is punishable by a civil fine of not less than $100 and not more than $500 per violation.",
            "civil",
            "Violation is subject to a civil fine of not less than $100 and not more than $500 per violation.",
        ),
        (
            "A violation is punishable by imprisonment for not more than 30 days.",
            "criminal",
            "Violation is subject to imprisonment for not more than 30 days.",
        ),
        (
            "A violation is subject to an administrative penalty of $250 per day.",
            "administrative",
            "Violation is subject to an administrative penalty of $250 per day.",
        ),
    ]

    for text, classification, expected_decoded in examples:
        element, norm, decoded = _decode(text)

        assert element["norm_type"] == "penalty"
        assert element["penalty"]["classification"] == classification
        assert norm.penalty["classification"] == classification
        assert decoded.text == expected_decoded
        assert decoded.missing_slots == []
        assert [phrase.slot for phrase in decoded.phrases] == [
            "actor",
            "penalty_connector",
            "action",
        ]
        assert decoded.phrases[1].fixed is True
        assert decoded.phrases[2].spans == [element["field_spans"]["action"]]
        assert " within " not in decoded.text.lower()
        assert decoded.text.lower().count(" if ") == 0


def test_decoder_exposes_cross_reference_provenance_without_reconstruction_text_drift():
    examples = [
        (
            "The Secretary shall publish the notice except as provided in section 552.",
            "Secretary shall publish the notice except as provided in section 552.",
            "section 552",
        ),
        (
            "This section applies to food carts.",
            "This section applies to food carts.",
            "section this section",
        ),
        (
            "Notwithstanding section 5.01.020, the Director may issue a variance.",
            "Notwithstanding section 5.01.020, Director may issue a variance.",
            "section 5.01.020",
        ),
    ]

    for text, expected_decoded, expected_reference in examples:
        element, norm, decoded = _decode(text)
        reference_phrase = next(
            phrase for phrase in decoded.phrases if phrase.slot == "cross_references"
        )

        assert decoded.text == expected_decoded
        assert reference_phrase.text == expected_reference
        assert reference_phrase.spans == [element["cross_reference_details"][0]["span"]]
        assert reference_phrase.fixed is False
        assert reference_phrase.provenance_only is True
        assert decoded.text.count(expected_reference) == expected_decoded.count(
            expected_reference
        )

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_decoder_renders_multiple_conditions_with_deterministic_connectors():
    element, norm, decoded = _decode(
        "The Director shall issue a permit if the application is complete, if fees are paid, "
        "and within 10 days after application."
    )

    assert decoded.text == (
        "Director shall issue a permit if the application is complete and if fees are paid "
        "and within 10 days after application."
    )
    assert [phrase.slot for phrase in decoded.phrases] == [
        "actor",
        "modality",
        "action",
        "condition_connector",
        "conditions",
        "condition_connector",
        "conditions",
        "temporal_connector",
        "temporal_constraints",
    ]
    assert [
        phrase.text for phrase in decoded.phrases if phrase.slot == "condition_connector"
    ] == [
        "if",
        "and if",
    ]
    assert [phrase.spans for phrase in decoded.phrases if phrase.slot == "conditions"] == [
        [element["condition_details"][0]["span"]],
        [element["condition_details"][1]["span"]],
    ]
    assert [phrase.text for phrase in decoded.phrases if phrase.slot == "temporal_connector"] == [
        "and",
    ]
    assert decoded.phrases[-1].text == "within 10 days after application"
    assert decoded.phrases[-1].spans == [
        element["temporal_constraint_details"][0]["span"]
    ]
    assert norm.conditions[1]["clause_type"] == "if"


def test_decoder_strips_duplicate_condition_and_exception_connectors_from_ir_details():
    _, norm, _ = _decode("The Director shall issue a permit.")
    detailed_norm = replace(
        norm,
        conditions=[
            {
                "clause_type": "provided_that",
                "raw_text": "provided that the application is complete",
                "span": [34, 77],
            },
            {
                "clause_type": "when",
                "raw_text": "when fees are paid",
                "span": [82, 100],
            },
        ],
        exceptions=[
            {
                "clause_type": "unless",
                "raw_text": "unless approval is denied",
                "span": [101, 126],
            },
            {
                "clause_type": "except",
                "raw_text": "except as provided in this section",
                "span": [131, 165],
            },
        ],
    )

    decoded = decode_legal_norm_ir(detailed_norm)

    assert decoded.text == (
        "Director shall issue a permit provided that the application is complete "
        "and when fees are paid unless approval is denied and except as provided in this section."
    )
    assert [
        phrase.text for phrase in decoded.phrases if phrase.slot == "condition_connector"
    ] == [
        "provided that",
        "and when",
    ]
    assert [phrase.text for phrase in decoded.phrases if phrase.slot == "conditions"] == [
        "the application is complete",
        "fees are paid",
    ]
    assert [
        phrase.text for phrase in decoded.phrases if phrase.slot == "exception_connector"
    ] == [
        "unless",
        "and except",
    ]
    assert [phrase.text for phrase in decoded.phrases if phrase.slot == "exceptions"] == [
        "approval is denied",
        "as provided in this section",
    ]
    assert decoded.missing_slots == []


def test_decoder_renders_temporal_chains_without_losing_each_span():
    _, norm, _ = _decode("The Clerk shall file the order.")
    temporal_norm = replace(
        norm,
        temporal_constraints=[
            {
                "type": "deadline",
                "raw_text": "before approval",
                "span": [32, 47],
            },
            {
                "type": "deadline",
                "raw_text": "after hearing",
                "span": [52, 65],
            },
            {
                "type": "deadline",
                "value": "10 days after service",
                "span": [70, 98],
            },
        ],
    )

    decoded = decode_legal_norm_ir(temporal_norm)

    assert decoded.text == (
        "Clerk shall file the order before approval and after hearing and "
        "within 10 days after service."
    )
    assert [
        phrase.text for phrase in decoded.phrases if phrase.slot == "temporal_connector"
    ] == [
        "and",
        "and",
    ]
    assert [
        phrase.text for phrase in decoded.phrases if phrase.slot == "temporal_constraints"
    ] == [
        "before approval",
        "after hearing",
        "within 10 days after service",
    ]
    assert [
        phrase.spans for phrase in decoded.phrases if phrase.slot == "temporal_constraints"
    ] == [
        [[32, 47]],
        [[52, 65]],
        [[70, 98]],
    ]


def test_decoder_connector_slice_preserves_unresolved_numbered_reference_repair_gate():
    element, norm, decoded = _decode(
        "The Secretary shall publish the notice except as provided in section 552."
    )

    assert decoded.text == "Secretary shall publish the notice except as provided in section 552."
    assert decoded.missing_slots == []
    assert element["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in element["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in element["llm_repair"]["reasons"]
    assert norm.proof_ready is False
    assert "cross_reference_requires_resolution" in norm.blockers
    assert "exception_requires_scope_review" in norm.blockers
