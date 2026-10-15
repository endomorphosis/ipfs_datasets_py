"""Explicit semicolon duties keep source-local slots through downstream exports."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.deontic.decoder import decode_legal_norm_ir
from ipfs_datasets_py.logic.deontic.exports import (
    build_document_export_tables_from_ir,
    parser_elements_for_metrics,
    parser_elements_with_ir_export_readiness,
)
from ipfs_datasets_py.logic.deontic.formula_builder import build_deontic_formula_record_from_ir
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.metrics import summarize_parser_elements
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


LOCAL_EXCEPTION = "except as provided in this section"
REFERENCE_BLOCKER = "formula_reference_exception_unresolved"
SCOPE_BLOCKER = "formula_duty_scope_unresolved"
ACTORS = ("Secretary", "clerk")
ACTIONS = ("publish the notice", "retain the record")
BASE_CLAUSES = ("The Secretary shall publish the notice", "the clerk shall retain the record")
FORMULAS = ("O(∀x (Secretary(x) → PublishNotice(x)))", "O(∀x (Clerk(x) → RetainRecord(x)))")


def parse_source(left, right, *, conjunction=False):
    source = left + ("; and " if conjunction else "; ") + right + "."
    elements = extract_normative_elements(source)
    assert len(elements) == 2
    return elements


def assert_source_local(element, norm, index):
    text = element["text"]
    assert norm.source_text == text
    assert norm.actor == ACTORS[index]
    assert norm.action == ACTIONS[index]
    support_start, support_end = element["support_span"]
    assert 0 <= support_start < support_end <= len(text)
    assert element["support_text"] == text[support_start:support_end]
    assert norm.support_text == element["support_text"]
    assert ";" not in element["support_text"]
    for slot in ("subject", "modal", "action"):
        start, end = element["field_spans"][slot]
        assert type(start) is int and type(end) is int
        assert support_start <= start < end <= support_end
    for alias in ("modality", "deontic_operator"):
        assert norm.field_spans[alias] == element["field_spans"]["modal"]
    assert text[slice(*element["field_spans"]["action"])] == ACTIONS[index]
    for record in [*norm.conditions, *norm.exceptions, *norm.cross_references]:
        start, end = record["span"]
        assert type(start) is int and type(end) is int
        assert support_start <= start < end <= support_end
        assert text[start:end] == record["raw_text"]


def assert_active_blocker(element, marker):
    ready = element["export_readiness"]
    assert ready["formula_proof_ready"] is False
    assert ready["formula_requires_validation"] is True
    assert ready["formula_repair_required"] is True
    assert ready["export_requires_validation"] is True
    assert ready["export_repair_required"] is True
    assert marker in ready["formula_blockers"]
    assert ready["deterministic_resolution"] == {}
    assert element["active_repair_required"] is True
    assert marker in element["active_repair_warnings"]
    assert element["llm_repair"]["allow_llm_repair"] is False


@pytest.mark.parametrize("exception_owners", [(0,), (1,), (0, 1)])
@pytest.mark.parametrize("conjunction", [False, True])
def test_semicolon_duties_keep_local_exception_ownership_and_clean_formula_readiness(exception_owners, conjunction):
    clauses = [base + (" " + LOCAL_EXCEPTION if index in exception_owners else "")
               for index, base in enumerate(BASE_CLAUSES)]
    elements = parse_source(*clauses, conjunction=conjunction)
    original = deepcopy(elements)
    norms = [LegalNormIR.from_parser_element(element) for element in elements]
    assert elements[0]["text"] == elements[1]["text"]
    assert len({norm.source_id for norm in norms}) == 2
    tables = build_document_export_tables_from_ir(norms)
    for index, (element, norm) in enumerate(zip(elements, norms, strict=True)):
        assert_source_local(element, norm, index)
        assert [row["raw_text"] for row in norm.exceptions] == (["as provided in this section"] if index in exception_owners else [])
        record = build_deontic_formula_record_from_ir(norm)
        assert record["formula"] == FORMULAS[index]
        assert record["proof_ready"] is True
        assert SCOPE_BLOCKER not in record["blockers"]
        canonical = next(row for row in tables["canonical"] if row["source_id"] == norm.source_id)
        assert (canonical["actor"], canonical["action"]) == (ACTORS[index], ACTIONS[index])
        for name in ("canonical", "formal_logic", "proof_obligations"):
            row = next(row for row in tables[name] if row["source_id"] == norm.source_id)
            assert row["proof_ready"] is True
            assert SCOPE_BLOCKER not in row["blockers"]
        expected = f"{ACTORS[index].capitalize()} shall {ACTIONS[index]}" + (" " + LOCAL_EXCEPTION if index in exception_owners else "") + "."
        decoder = next(row for row in tables["decoder_reconstructions"] if row["source_id"] == norm.source_id)
        assert decoder["decoded_text"] == decode_legal_norm_ir(norm).text == expected
    assert tables["repair_queue"] == []
    projected = parser_elements_for_metrics(elements)
    for element in projected:
        assert element["export_readiness"]["formula_proof_ready"] is True
        assert element["active_repair_required"] is False
    assert summarize_parser_elements(projected)["repair_required_count"] == 0
    assert elements == original


def test_two_substantive_exceptions_remain_in_their_own_duty_scaffolds():
    elements = parse_source(BASE_CLAUSES[0] + " unless approval is denied", BASE_CLAUSES[1] + " unless consent is revoked")
    original = deepcopy(elements)
    norms = [LegalNormIR.from_parser_element(element) for element in elements]
    expected = (
        ("approval is denied", "O(∀x (Secretary(x) ∧ ¬ApprovalIsDenied(x) → PublishNotice(x)))"),
        ("consent is revoked", "O(∀x (Clerk(x) ∧ ¬ConsentIsRevoked(x) → RetainRecord(x)))"),
    )
    tables = build_document_export_tables_from_ir(norms)
    for index, (element, norm) in enumerate(zip(elements, norms, strict=True)):
        assert_source_local(element, norm, index)
        body, formula = expected[index]
        assert [row["raw_text"] for row in norm.exceptions] == [body]
        assert build_deontic_formula_record_from_ir(norm)["formula"] == formula
        decoder = next(row for row in tables["decoder_reconstructions"] if row["source_id"] == norm.source_id)
        assert decoder["decoded_text"] == f"{ACTORS[index].capitalize()} shall {ACTIONS[index]} unless {body}."
        # Retaining a conditional scaffold does not supply independent legal interpretation.
        assert element["promotable_to_theorem"] is False
    assert elements == original


def test_inline_local_exception_and_second_prohibition_stay_separate():
    elements = parse_source("The Secretary shall (except as provided in this section) publish the notice", "the clerk shall not retain the record")
    norms = [LegalNormIR.from_parser_element(element) for element in elements]
    for index, (element, norm) in enumerate(zip(elements, norms, strict=True)):
        assert_source_local(element, norm, index)
    assert norms[0].modality == "O" and norms[1].modality == "F"
    assert len(norms[0].exceptions) == 1 and norms[1].exceptions == []
    records = [build_deontic_formula_record_from_ir(norm) for norm in norms]
    assert [record["formula"] for record in records] == [FORMULAS[0], "F(∀x (Clerk(x) → RetainRecord(x)))"]
    assert all(record["proof_ready"] is True for record in records)
    decoded = [decode_legal_norm_ir(norm).text for norm in norms]
    assert decoded == ["Secretary shall publish the notice except as provided in this section.", "Clerk shall not retain the record."]


def test_fronted_condition_on_second_duty_does_not_qualify_first_duty():
    elements = parse_source(BASE_CLAUSES[0], "if approval is granted, " + BASE_CLAUSES[1])
    original = deepcopy(elements)
    norms = [LegalNormIR.from_parser_element(element) for element in elements]
    for index, (element, norm) in enumerate(zip(elements, norms, strict=True)):
        assert_source_local(element, norm, index)
    assert norms[0].conditions == []
    assert [row["raw_text"] for row in norms[1].conditions] == ["approval is granted"]
    records = [build_deontic_formula_record_from_ir(norm) for norm in norms]
    assert records[0]["formula"] == FORMULAS[0]
    assert records[1]["formula"] == "O(∀x (Clerk(x) ∧ ApprovalIsGranted(x) → RetainRecord(x)))"
    assert all(SCOPE_BLOCKER not in record["blockers"] for record in records)
    assert [decode_legal_norm_ir(norm).text for norm in norms] == [
        "Secretary shall publish the notice.",
        "Clerk shall retain the record if approval is granted.",
    ]
    assert elements == original


@pytest.mark.parametrize("owner", [0, 1])
def test_external_reference_blocks_only_its_source_duty(owner):
    clauses = [base + (" except as provided in section 552" if index == owner else "")
               for index, base in enumerate(BASE_CLAUSES)]
    elements = parse_source(*clauses)
    original = deepcopy(elements)
    norms = [LegalNormIR.from_parser_element(element) for element in elements]
    tables = build_document_export_tables_from_ir(norms)
    for index, (element, norm) in enumerate(zip(elements, norms, strict=True)):
        assert_source_local(element, norm, index)
        assert {row["value"] for row in norm.cross_references} == ({"552"} if index == owner else set())
        for name in ("canonical", "formal_logic", "proof_obligations"):
            row = next(row for row in tables[name] if row["source_id"] == norm.source_id)
            assert row["proof_ready"] is (index != owner)
            assert (REFERENCE_BLOCKER in row["blockers"]) is (index == owner)
        decoder = next(row for row in tables["decoder_reconstructions"] if row["source_id"] == norm.source_id)
        assert ("section 552" in decoder["decoded_text"]) is (index == owner)
    repair, = tables["repair_queue"]
    assert repair["source_id"] == norms[owner].source_id
    assert REFERENCE_BLOCKER in repair["reasons"]
    projected = parser_elements_for_metrics(elements)
    assert_active_blocker(projected[owner], REFERENCE_BLOCKER)
    assert projected[1 - owner]["export_readiness"]["formula_proof_ready"] is True
    assert projected[1 - owner]["active_repair_required"] is False
    assert summarize_parser_elements(projected)["repair_required_count"] == 1
    assert elements == original


@pytest.mark.parametrize("owner", [0, 1])
def test_cached_readiness_cannot_clear_one_dutys_unresolved_reference(owner):
    clauses = [base + (" except as provided in section 552" if index == owner else "")
               for index, base in enumerate(BASE_CLAUSES)]
    elements = parse_source(*clauses)
    stale_resolution = {"type": "source_grounded_reconstruction_warning_bundle", "core_slots": ["actor", "modality", "action"]}
    blocked = elements[owner]
    blocked["active_repair_required"] = False
    blocked["repair_required"] = False
    blocked["export_readiness"] = {
        **blocked.get("export_readiness", {}),
        "formula_proof_ready": True, "formula_requires_validation": False,
        "formula_repair_required": False, "export_requires_validation": False,
        "export_repair_required": False, "deterministic_resolution": stale_resolution,
    }
    blocked["llm_repair"] = {
        **blocked.get("llm_repair", {}), "required": False,
        "deterministically_resolved": True, "deterministic_resolution": stale_resolution,
    }
    original = deepcopy(elements)
    projected = parser_elements_with_ir_export_readiness(elements)
    for _ in range(3):
        projected = parser_elements_for_metrics(projected)
        assert_active_blocker(projected[owner], REFERENCE_BLOCKER)
        assert projected[1 - owner]["export_readiness"]["formula_proof_ready"] is True
        assert projected[1 - owner]["active_repair_required"] is False
        for index, element in enumerate(projected):
            assert_source_local(element, LegalNormIR.from_parser_element(element), index)
    assert elements == original


@pytest.mark.parametrize("exception", [
    "except as provided in this section unless approval is granted",
    "unless approval is granted except as provided in this section",
])
def test_nested_inline_exception_introducers_retain_existing_conservative_blocker(exception):
    source = f"The Secretary shall ({exception}) publish the notice."
    element, = extract_normative_elements(source)
    original = deepcopy(element)
    norm = LegalNormIR.from_parser_element(element)
    marker = "formula_inline_exception_action_unresolved"
    tables = build_document_export_tables_from_ir([norm])
    for name in ("canonical", "formal_logic", "proof_obligations"):
        row, = tables[name]
        assert row["proof_ready"] is False
        assert marker in row["blockers"]
    assert marker in tables["repair_queue"][0]["reasons"]
    assert tables["decoder_reconstructions"][0]["requires_validation"] is True
    projected, = parser_elements_for_metrics([element])
    assert_active_blocker(projected, marker)
    assert element == original


@pytest.mark.parametrize("mutation", [
    "actor_as_action", "action_suffix", "actor_suffix",
    "operator_permission", "operator_non_deontic", "operator_unknown",
    "wrong_local_modal_alias",
])
def test_matching_local_source_slices_cannot_replace_the_actual_duty_core(mutation):
    source = "The Deputy Secretary shall publish the notice; the Clerk shall retain the record unless approval is denied."
    element, _ = extract_normative_elements(source)
    norm = LegalNormIR.from_parser_element(element)
    fields = deepcopy(norm.field_spans)
    updates = {}
    row = deepcopy(element)
    if mutation == "actor_as_action":
        fields["action"] = fields["subject"][:]
        updates["action"] = norm.source_text[slice(*fields["action"])]
        row["action"] = [updates["action"]]
    elif mutation == "action_suffix":
        start = norm.source_text.index("notice")
        fields["action"] = [start, start + len("notice")]
        updates["action"] = "notice"
        row["action"] = [updates["action"]]
    elif mutation == "actor_suffix":
        start = norm.source_text.index("Secretary")
        fields["subject"] = [start, start + len("Secretary")]
        updates["actor"] = "Secretary"
        row["subject"] = [updates["actor"]]
    elif mutation.startswith("operator_"):
        operator, norm_type = {
            "operator_permission": ("P", "permission"),
            "operator_non_deontic": ("DEF", "definition"),
            "operator_unknown": ("UNKNOWN", "unknown"),
        }[mutation]
        updates.update(modality=operator, norm_type=norm_type)
        row.update(modality=operator, deontic_operator=operator, norm_type=norm_type)
        row["logic_frame"].update(modality=operator, norm_type=norm_type)
        row["legal_frame"].update(deontic_operator=operator, norm_type=norm_type)
    elif mutation == "wrong_local_modal_alias":
        fields["deontic_operator"] = fields["action"][:]
    stale_resolution = {"type": "core_slots_complete"}
    cache = {
        "formula_proof_ready": True, "formula_requires_validation": False,
        "formula_repair_required": False, "deterministic_resolution": stale_resolution,
    }
    quality = replace(norm.quality, promotable_to_theorem=True,
                      export_readiness={**norm.quality.export_readiness, **cache})
    altered = replace(norm, field_spans=fields, quality=quality, **updates)
    before = deepcopy(altered)
    record = build_deontic_formula_record_from_ir(altered)
    assert SCOPE_BLOCKER in record["blockers"]
    assert record["proof_ready"] is False
    assert record["requires_validation"] is record["repair_required"] is True
    assert record["deterministic_resolution"] == {}
    tables = build_document_export_tables_from_ir([altered])
    for name in ("canonical", "formal_logic", "proof_obligations"):
        assert tables[name][0]["proof_ready"] is False
        assert SCOPE_BLOCKER in tables[name][0]["blockers"]
    for name in ("decoder_reconstructions", "prover_syntax_summaries"):
        assert tables[name][0]["proof_ready"] is False
        assert tables[name][0]["requires_validation"] is True
    assert SCOPE_BLOCKER in tables["repair_queue"][0]["reasons"]
    assert altered == before

    row["field_spans"] = deepcopy(fields)
    row["active_repair_required"] = False
    row["repair_required"] = False
    row["export_readiness"].update(cache)
    row["llm_repair"].update(required=False, deterministically_resolved=True,
                             deterministic_resolution=stale_resolution)
    input_row = row
    original = deepcopy(row)
    for _ in range(3):
        row, = parser_elements_for_metrics([row])
        if mutation == "operator_unknown":
            # Parser-to-IR normalization can recover O from the unchanged
            # lexical "shall"; direct typed UNKNOWN above stays blocked.
            assert row["modality"] == row["deontic_operator"] == "O"
            recovered = LegalNormIR.from_parser_element(row)
            assert (recovered.actor, recovered.action, recovered.modality) == (norm.actor, norm.action, norm.modality)
            for slot in ("subject", "modal", "action"):
                assert recovered.field_spans[slot] == norm.field_spans[slot]
            recovered_record = build_deontic_formula_record_from_ir(recovered)
            assert recovered_record["formula"] == build_deontic_formula_record_from_ir(norm)["formula"]
            assert SCOPE_BLOCKER not in recovered_record["blockers"]
            assert row["export_readiness"]["formula_proof_ready"] is True
        else:
            assert_active_blocker(row, SCOPE_BLOCKER)
            assert row["export_readiness"]["metric_repair_required"] is True
    assert original["text"] == element["text"]
    assert input_row == original
