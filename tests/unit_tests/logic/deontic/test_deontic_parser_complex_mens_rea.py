"""Parser coverage for source-grounded complex mens rea clauses."""

from ipfs_datasets_py.logic.deontic.decoder import decode_legal_norm_ir
from ipfs_datasets_py.logic.deontic.formula_builder import (
    build_deontic_formula_from_ir,
    build_deontic_formula_record_from_ir,
)
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.prover_syntax import validate_ir_with_provers
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
    extract_normative_elements,
)


def test_complex_mens_rea_phrases_are_source_grounded_parser_slots():
    examples = [
        (
            "No person shall, with intent to defraud, submit a claim.",
            "person",
            "with intent to defraud",
            "submit a claim",
            "submit",
            "a claim",
            "F(∀x (Person(x) ∧ IntentDefraud(x) → SubmitClaim(x)))",
            "Person shall not with intent to defraud submit a claim.",
        ),
        (
            "No licensee shall, with knowledge that the statement is false, file the statement.",
            "licensee",
            "with knowledge that the statement is false",
            "file the statement",
            "file",
            "the statement",
            "F(∀x (Licensee(x) ∧ KnowledgeThatStatementIsFalse(x) → FileStatement(x)))",
            "Licensee shall not with knowledge that the statement is false file the statement.",
        ),
        (
            "No operator shall, with reckless disregard for the truth, certify the report.",
            "operator",
            "with reckless disregard for the truth",
            "certify the report",
            "certify",
            "the report",
            "F(∀x (Operator(x) ∧ RecklessDisregardTruth(x) → CertifyReport(x)))",
            "Operator shall not with reckless disregard for the truth certify the report.",
        ),
    ]

    for (
        text,
        actor,
        mental_state,
        action,
        action_verb,
        action_object,
        expected_formula,
        expected_decoded,
    ) in examples:
        elements = extract_normative_elements(text)

        assert len(elements) == 1
        element = elements[0]
        assert element["deontic_operator"] == "F"
        assert element["norm_type"] == "prohibition"
        assert element["subject"] == [actor]
        assert element["mental_state"] == mental_state
        assert element["action"] == [action]
        assert element["action_verb"] == action_verb
        assert element["action_object"] == action_object
        assert element["text"][element["field_spans"]["mental_state"][0]:element["field_spans"]["mental_state"][1]] == mental_state
        assert element["text"][element["field_spans"]["action"][0]:element["field_spans"]["action"][1]] == action
        assert element["llm_repair"]["required"] is False

        norm = LegalNormIR.from_parser_element(element)
        formula = build_deontic_formula_from_ir(norm)
        formula_record = build_deontic_formula_record_from_ir(norm)
        decoded = decode_legal_norm_ir(norm)
        prover_report = validate_ir_with_provers(norm)

        assert norm.mental_state == mental_state
        assert norm.action == action
        assert formula == expected_formula
        assert formula_record["included_formula_slots"] == [
            "actor",
            "modality",
            "mental_state",
            "action",
        ]
        assert formula_record["proof_ready"] is True
        assert formula_record["requires_validation"] is False
        assert decoded.text == expected_decoded
        assert [phrase.slot for phrase in decoded.phrases] == [
            "actor",
            "modality",
            "mental_state",
            "action",
        ]
        assert prover_report.syntax_valid is True
        assert prover_report.proof_ready is True
        assert prover_report.valid_target_count == 5


def test_complex_mens_rea_slice_preserves_unresolved_numbered_reference_blocker():
    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]

    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]
