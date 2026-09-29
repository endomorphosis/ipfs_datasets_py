"""Stage completion, represented identity and source coverage are distinct."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic import autoformal
from ipfs_datasets_py.logic.autoformal.semantic_integrity import (
    canonical_cycle_integrity, unsupported_source_grammar,
)
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    CanonicalRoundTripIR, CanonicalRule, OperationStatus,
)
from ipfs_datasets_py.logic.legal_ir.canonical_roundtrip import CanonicalSemanticRoundTrip


def _rule(**changes):
    return replace(CanonicalRule("O", "agency", "submit", "report",
                                 ("request",), ("emergency",), ("within_10_days",)), **changes)


def _cycle(left, right, **changes):
    return SimpleNamespace(status=OperationStatus.SUCCESS,
                           l1_result=SimpleNamespace(canonical_ir=CanonicalRoundTripIR(tuple(left)),
                                                     unsupported_semantics=()),
                           l2_result=SimpleNamespace(canonical_ir=CanonicalRoundTripIR(tuple(right)),
                                                     unsupported_semantics=()), **changes)


@pytest.mark.parametrize("change", [
    {"modality": "F"}, {"actor": "officer"}, {"action": "retain"},
    {"object": "records"}, {"conditions": ()}, {"exceptions": ()}, {"temporal": ()},
])
def test_successful_stages_with_changed_meaning_are_not_roundtrip_integrity(change):
    report = canonical_cycle_integrity(_cycle([_rule()], [_rule(**change)]))
    assert report["passed"] is False
    assert report["reasons"] == ["canonical_cycle_ir_mismatch"]
    assert report["l1_ir_cid"] != report["l2_ir_cid"]
    assert report["admitted"] is False


def test_canonical_order_and_request_metadata_do_not_change_meaning():
    other = _rule(actor="company", modality="P")
    cycle = _cycle([_rule(), other], [other, _rule()], request_id="independent-request")
    report = canonical_cycle_integrity(cycle)
    assert report["passed"] is True
    assert report["full_source_equivalence_proved"] is False
    assert report["admitted"] is False


def test_missing_or_partial_cycle_cannot_pass():
    cycle = _cycle([_rule()], [_rule()])
    cycle.l2_result.canonical_ir = None
    assert "missing_canonical_cycle_ir" in canonical_cycle_integrity(cycle)["reasons"]
    cycle = _cycle([_rule()], [_rule()])
    cycle.l1_result.unsupported_semantics = ("disclosed partial field",)
    assert canonical_cycle_integrity(cycle)["reasons"] == ["partial_canonical_cycle_semantics"]
    cycle = _cycle([_rule()], [_rule()])
    cycle.status = OperationStatus.ABSTAINED
    assert canonical_cycle_integrity(cycle)["passed"] is False


def test_session_does_not_promote_pipeline_success_with_ir_drift(monkeypatch):
    session = autoformal.AutoformalSession()
    opened = session.open_document("The agency shall submit the report.", document_id="drift")
    clause_id = opened["clauses"][0]["id"]
    session.compile_clause("drift", clause_id)
    assert session.rows[0].status == "compiled"
    monkeypatch.setattr(CanonicalSemanticRoundTrip, "run",
                        lambda *args: _cycle([_rule()], [_rule(modality="F")]))
    result = session.roundtrip_clause("drift", clause_id)
    assert result["roundtrip_status"] == OperationStatus.SUCCESS.value
    assert result["semantic_integrity"]["passed"] is False
    assert result["rows"][0]["status"] == "compiled"
    assert result["rows"][0]["reason"] == "semantic_integrity:canonical_cycle_ir_mismatch"
    assert result["rows"][0]["admitted"] is False


@pytest.mark.parametrize("text,reason", [
    ("An action described in subsection (a) may be taken if—\n"
     "(1) the Secretary has submitted a report; and\n(2) a period of 30 days has elapsed.",
     "unsupported_enumerated_condition_scope"),
    ("Such factors shall be used except that other factors may be used if—\n"
     "(1) the other factors are approved;\n(2) using the factors would violate law; or\n"
     "(3) statutory requirements require modification.",
     "unsupported_enumerated_condition_scope"),
    ("The statement shall be made by—\n(A) an owner if one resides at the port; or\n"
     "(B) the master if an owner does not reside at the port.",
     "unsupported_enumerated_participant_scope"),
    ("Nothing in this section shall be construed to authorize an individual to enter "
     "a public building that the individual is not otherwise authorized to enter.",
     "unsupported_negative_interpretive_scope"),
    ("Factors and data consented to pursuant to may be revised and agreed to by a consensus.",
     "unresolved_source_cross_reference"),
    ("The Secretary shall submit a report describing—(1) the requirements of ; and "
     "(2) the status of projects funded under this part.",
     "unresolved_source_cross_reference"),
])
def test_known_unrepresented_scope_is_explicit_and_not_roundtrip(text, reason, monkeypatch):
    assert reason in unsupported_source_grammar(text)
    session = autoformal.AutoformalSession()
    opened = session.open_document(text, document_id="source-scope")
    clause_id = opened["clauses"][0]["id"]
    clause = session.documents.clause("source-scope", clause_id)
    session.rows.append(autoformal.RuleRow("source-scope", clause_id, clause.start, clause.end,
                                         "unassigned", rule=_rule().to_dict(),
                                         decompiled="Incomplete represented text.", status="compiled"))
    monkeypatch.setattr(CanonicalSemanticRoundTrip, "run",
                        lambda *args: pytest.fail("unsupported scope must not be promoted by a cycle"))
    result = session.roundtrip_clause("source-scope", clause_id)
    assert result["evaluated"] is False
    assert result["rows"][0]["status"] == "compiled"
    assert reason in result["rows"][0]["reason"]


def test_split_condition_continuation_is_not_an_independent_obligation():
    before = "A building may be excluded if—\n(1) the building lacks a room; or\n\n"
    after = "(2) new construction would be required to create a room and its cost is unfeasible."
    assert unsupported_source_grammar(after, preceding_text=before) == [
        "unsupported_enumerated_condition_continuation"]
    assert unsupported_source_grammar(after) == []
    assert unsupported_source_grammar(after, preceding_text="The agency shall file; or\n") == []


@pytest.mark.parametrize("text", [
    "The owner or master shall submit the report.",
    "The agency shall retain the report or file.",
    "Company A shall submit backup report within 10 days unless emergency.",
    "The agency shall submit a report if requested.",
    "The agency shall not disclose records.",
    "The officer shall retain the file for at least 20 days.",
    "(2) The agency shall submit a report.",
    'The label "if—(1)" shall be printed on the form.',
    "The label “if—(1)” shall be printed on the form.",
    "The statement shall be made by the owner.",
    "Factors pursuant to section 5 may be revised.",
    "Factors pursuant to May 5 regulations may be revised.",
    "The report shall describe (1) requirements of section 5; and (2) project status.",
    'The label "pursuant to may be" shall be printed on the form.',
    'The label "of ; and (2)" shall be printed on the form.',
])
def test_simple_supported_grammar_and_literal_labels_are_not_blanket_refused(text):
    assert unsupported_source_grammar(text) == []
