"""Source-valid integration checks for qualifier and procedure fidelity.

These are local parser/IR/formula checks, not candidate or native admission
tests. Existing formula action vocabulary is deliberately preserved.
"""
from __future__ import annotations

from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.deontic.exports import build_procedure_event_records_from_ir
from ipfs_datasets_py.logic.deontic.formula_builder import (
    build_deontic_formula_from_ir,
    build_deontic_formula_record_from_ir,
)
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
    extract_normative_elements,
    extract_procedure_details,
)


def _triples(procedure):
    return {
        (row["event"], row["relation"], row["anchor_event"])
        for row in procedure.get("event_relations", [])
    }


def _assert_source_spans(procedure, source):
    """Check every nested inventory copy against the original source."""
    if isinstance(procedure, dict):
        if "span" in procedure:
            start, end = procedure["span"]
            assert type(start) is int and type(end) is int
            assert 0 <= start < end <= len(source)
            if "raw_text" in procedure:
                assert source[start:end] == procedure["raw_text"]
        for value in procedure.values():
            _assert_source_spans(value, source)
    elif isinstance(procedure, list):
        for value in procedure:
            _assert_source_spans(value, source)


@pytest.mark.parametrize("citation", ["5.01.020", "12.345.6"])
def test_dotted_override_keeps_actual_approval_condition_and_blocks_pure_override(citation):
    source = (
        f"Subject to approval, notwithstanding section {citation}, "
        "the Director may issue a variance."
    )
    element = extract_normative_elements(source)[0]
    original = deepcopy(element)
    norm = LegalNormIR.from_parser_element(element)
    record = build_deontic_formula_record_from_ir(norm)

    assert element == original
    assert len(norm.conditions) == 1
    condition = norm.conditions[0]
    assert condition["value"] == "approval"
    start, end = condition["span"]
    assert source[start:end] == "approval"
    assert condition["span"] == element["condition_details"][0]["span"]
    assert norm.overrides[0]["value"] == f"section {citation}"
    assert record["formula"] == "P(∀x (Director(x) ∧ Approval(x) → IssueVariance(x)))"
    assert record["proof_ready"] is False
    assert record["requires_validation"] is True
    assert "override_clause_requires_precedence_review" in record["blockers"]
    assert record["deterministic_resolution"].get("type") != "pure_precedence_override"


def test_restored_approval_is_not_transferred_to_a_separate_norm():
    source = (
        "Subject to approval, notwithstanding section 5.01.020, "
        "the Director may issue a variance. The clerk shall retain the record."
    )
    elements = extract_normative_elements(source)
    norms = [LegalNormIR.from_parser_element(element) for element in elements]
    variance = next(norm for norm in norms if "variance" in norm.action)
    clerk = next(norm for norm in norms if "retain" in norm.action)
    assert [row["value"] for row in variance.conditions] == ["approval"]
    assert clerk.conditions == []
    assert clerk.overrides == []
    assert "Approval(" not in build_deontic_formula_from_ir(clerk)


def test_pure_override_control_does_not_invent_a_substantive_condition():
    source = "Notwithstanding section 5.01.020, the Director may issue a variance."
    norm = LegalNormIR.from_parser_element(extract_normative_elements(source)[0])
    record = build_deontic_formula_record_from_ir(norm)
    assert norm.conditions == []
    assert record["formula"] == "P(∀x (Director(x) → IssueVariance(x)))"
    assert record["deterministic_resolution"]["type"] == "pure_precedence_override"


def test_inspection_receipt_and_before_relations_retain_source_and_correct_owner():
    source = "Upon receipt of an application, the Bureau shall inspect the premises before approval."
    element = extract_normative_elements(source)[0]
    original = deepcopy(element)
    norm = LegalNormIR.from_parser_element(element)
    record = build_deontic_formula_record_from_ir(norm)

    expected = {
        ("inspection", "triggered_by_receipt_of", "application"),
        ("receipt", "receives", "application"),
        ("inspection", "before", "issuance"),
    }
    assert _triples(element["procedure"]) == expected
    assert _triples(norm.procedure) == expected
    _assert_source_spans(element["procedure"], element["text"])
    _assert_source_spans(norm.procedure, element["text"])
    mentions = norm.procedure["event_mentions"]
    assert sum(row["raw_text"] == "inspect" for row in mentions) == 1
    assert sum(row["raw_text"] == "approval" for row in mentions) == 1
    assert norm.action == "inspect the premises before approval"
    assert record["formula"] == (
        "O(∀x (Bureau(x) ∧ ProcedureUponReceiptApplication(x) "
        "→ InspectPremisesBeforeApproval(x)))"
    )
    exported = build_procedure_event_records_from_ir(norm)
    receipt = next(row for row in exported if row["relation"] == "triggered_by_receipt_of")
    ordering = next(row for row in exported if row["relation"] == "before")
    assert receipt["event"] == ordering["event"] == "inspection"
    assert receipt["is_formula_antecedent"] is True
    assert receipt["proof_role"] == "prerequisite"
    assert ordering["is_formula_antecedent"] is False
    assert ordering["proof_role"] == "ordering_provenance"
    assert "ProcedureBeforeIssuance" not in record["formula"]
    # Existing local formula readiness does not prove the ordering provenance.
    assert record["proof_ready"] is True
    assert element == original


@pytest.mark.parametrize("prefix", ["", "État 🏛: "])
def test_direct_procedure_inventory_uses_original_character_offsets(prefix):
    source = prefix + "The Bureau shall inspect the premises before approval."
    action = "inspect the premises before approval"
    procedure = extract_procedure_details(source, action)
    assert procedure["raw_text"] == source
    assert _triples(procedure) == {("inspection", "before", "issuance")}
    _assert_source_spans(procedure, source)
    inspection = next(row for row in procedure["event_mentions"] if row["event"] == "inspection")
    assert inspection["span"] == [source.index("inspect"), source.index("inspect") + 7]


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("inspect the premises before approval", {("inspection", "before", "issuance")}),
        ("issue a permit after hearing", {("issuance", "after", "hearing")}),
    ],
)
def test_procedure_relations_are_scoped_to_the_selected_action_sentence(action, expected):
    source = (
        "The Bureau shall inspect the premises before approval. "
        "The Board shall issue a permit after hearing."
    )
    procedure = extract_procedure_details(source, action)
    assert _triples(procedure) == expected
    _assert_source_spans(procedure, source)


@pytest.mark.parametrize("quote_pair", [('"', '"'), ("“", "”"), ("[", "]")])
def test_quoted_or_bracketed_connector_does_not_create_an_ordering_relation(quote_pair):
    opening, closing = quote_pair
    action = f"inspect the premises marked {opening}before approval{closing}"
    source = f"The Bureau shall {action}."
    procedure = extract_procedure_details(source, action)
    assert not procedure.get("event_relations")
    _assert_source_spans(procedure, source)


def test_repeated_exact_action_has_no_guessed_relation_owner():
    action = "inspect the premises before approval"
    source = f"The Bureau shall {action}. The Board shall {action}."
    procedure = extract_procedure_details(source, action)
    assert not procedure.get("event_relations")
    _assert_source_spans(procedure, source)


def test_action_absent_from_source_cannot_be_appended_as_procedure_evidence():
    source = "Upon receipt of an application, the Board shall issue a permit."
    procedure = extract_procedure_details(source, "inspect the premises before approval")
    assert "inspection" not in procedure.get("events", [])
    assert all(row["event"] == "receipt" for row in procedure.get("event_relations", []))
    assert procedure["raw_text"] == source
    _assert_source_spans(procedure, source)


def test_multiple_parser_elements_keep_procedure_offsets_in_each_local_source():
    source = (
        "The Bureau shall inspect the premises before approval. "
        "The Board shall issue a permit after hearing."
    )
    elements = extract_normative_elements(source)
    assert len(elements) == 2
    for element in elements:
        before = deepcopy(element)
        norm = LegalNormIR.from_parser_element(element)
        _assert_source_spans(norm.procedure, element["text"])
        expected = (
            {("inspection", "before", "issuance")}
            if "inspect" in norm.action
            else {("issuance", "after", "hearing")}
        )
        assert _triples(norm.procedure) == expected
        assert element == before
