"""Actual cap loss blocks formula readiness without discarding source records."""

from copy import deepcopy
from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.deontic.formula_builder import (
    build_deontic_formula_from_ir,
    build_deontic_formula_record_from_ir,
    build_deontic_formula_records_from_irs,
    normalize_predicate_name,
)
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


CONDITIONS = ["requirements are met", "fees are paid", "inspection is complete",
              "notice is posted", "records are retained"]
EXCEPTIONS = ["approval is denied", "the application is incomplete", "the fee is unpaid",
              "the site is unsafe", "publication is impossible"]
MARKERS = {"formula_condition_cap_exceeded", "formula_exception_cap_exceeded"}


def source_norm(*, conditions=(), exceptions=(), prefix="", operator="shall"):
    source = prefix + f"The Director {operator} issue a permit"
    clauses = ["if " + value for value in conditions] + ["unless " + value for value in exceptions]
    if clauses:
        source += " " + ", ".join(clauses)
    source += "."
    row, = extract_normative_elements(source)
    norm = LegalNormIR.from_parser_element(row)
    for slot in ("conditions", "exceptions"):
        for detail in getattr(norm, slot):
            start, end = detail["span"]
            assert norm.source_text[start:end] == detail["raw_text"]
    return norm


@pytest.mark.parametrize("slot,marker,bodies", [
    ("conditions", "formula_condition_cap_exceeded", CONDITIONS),
    ("exceptions", "formula_exception_cap_exceeded", EXCEPTIONS),
])
@pytest.mark.parametrize("count", [0, 1, 3, 4, 5])
def test_source_valid_cap_boundary_blocks_only_actual_loss(slot, marker, bodies, count):
    norm = source_norm(**{slot: bodies[:count]})
    before = deepcopy(norm)
    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)
    assert len(getattr(norm, slot)) == count
    assert record["formula"] == formula
    assert norm == before
    assert set(record["blockers"]) & MARKERS == ({marker} if count > 3 else set())
    if count > 3:
        assert record["proof_ready"] is False
        assert record["requires_validation"] is True
        assert record["repair_required"] is True
        assert record["deterministic_resolution"] == {}
        omitted = record["omitted_formula_slots"][slot]
        assert [row["value"] for row in omitted] == list(bodies[3:count])
        assert [row["span"] for row in omitted] == [
            row["span"] for row in getattr(norm, slot)[3:]
        ]
        assert all(row["predicate"] + "(x)" not in formula for row in omitted)
    else:
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert slot not in record["omitted_formula_slots"]


def test_condition_formula_string_keeps_existing_cap_and_exact_predicate_order():
    norm = source_norm(conditions=CONDITIONS)
    assert build_deontic_formula_from_ir(norm) == (
        "O(∀x (Director(x) ∧ RequirementsAreMet(x) ∧ FeesArePaid(x) "
        "∧ InspectionIsComplete(x) → IssuePermit(x)))"
    )
    assert norm.proof_ready is True
    assert build_deontic_formula_record_from_ir(norm)["proof_ready"] is False


@pytest.mark.parametrize("operator", ["may", "shall not"])
def test_permission_and_prohibition_caps_are_also_checked(operator):
    norm = source_norm(conditions=CONDITIONS[:4], operator=operator)
    record = build_deontic_formula_record_from_ir(norm)
    assert record["formula"].startswith(("P(", "F("))
    assert record["proof_ready"] is False
    assert "formula_condition_cap_exceeded" in record["blockers"]


def test_condition_and_exception_omissions_have_independent_ordered_blockers():
    norm = source_norm(conditions=CONDITIONS[:4], exceptions=EXCEPTIONS[:4])
    record = build_deontic_formula_record_from_ir(norm)
    assert [item for item in record["blockers"] if item in MARKERS] == [
        "formula_condition_cap_exceeded", "formula_exception_cap_exceeded"
    ]
    assert [item["value"] for item in record["omitted_formula_slots"]["conditions"]] == [
        CONDITIONS[3]
    ]
    assert [item["value"] for item in record["omitted_formula_slots"]["exceptions"]] == [
        EXCEPTIONS[3]
    ]
    assert record["deterministic_resolution"] == {}


@pytest.mark.parametrize("slot,bodies", [("conditions", CONDITIONS), ("exceptions", EXCEPTIONS)])
@pytest.mark.parametrize("resolution_type", [
    "compiler_guidance_deontic_ir_reconstruction",
    "source_grounded_reconstruction_warning_bundle",
    "standard_substantive_exception",
])
def test_current_omissions_override_promoted_norm_and_cached_resolution(slot, bodies, resolution_type):
    norm = source_norm(**{slot: bodies[:4]})
    readiness = {**norm.quality.export_readiness, "formula_proof_ready": True,
                 "formula_requires_validation": False, "formula_repair_required": False,
                 "deterministic_resolution": {"type": resolution_type, "resolved_blockers": []}}
    norm = replace(norm, quality=replace(norm.quality, promotable_to_theorem=True,
                                        parser_warnings=[], export_readiness=readiness))
    before = deepcopy(norm)
    record = build_deontic_formula_record_from_ir(norm)
    assert norm.proof_ready is True
    assert record["proof_ready"] is False
    assert record["deterministic_resolution"] == {}
    assert record["parser_warnings"] == []
    assert norm == before


@pytest.mark.parametrize("slot,bodies", [("conditions", CONDITIONS), ("exceptions", EXCEPTIONS)])
def test_repeated_source_occurrences_of_represented_predicates_are_not_omissions(slot, bodies):
    sequence = [bodies[0], bodies[0], bodies[1], bodies[1], bodies[2], bodies[0]]
    norm = source_norm(**{slot: sequence})
    assert len(getattr(norm, slot)) == 6
    record = build_deontic_formula_record_from_ir(norm)
    assert not set(record["blockers"]) & MARKERS
    assert slot not in record["omitted_formula_slots"]
    assert record["proof_ready"] is True
    for body in bodies[:3]:
        assert record["formula"].count(normalize_predicate_name(body) + "(x)") == 1


@pytest.mark.parametrize("slot,bodies", [("conditions", CONDITIONS), ("exceptions", EXCEPTIONS)])
def test_omission_accounting_follows_distinct_predicates_not_record_indexes(slot, bodies):
    sequence = [bodies[0], bodies[0], bodies[1], bodies[2], bodies[3], bodies[3], bodies[0]]
    norm = source_norm(**{slot: sequence})
    record = build_deontic_formula_record_from_ir(norm)
    omitted = record["omitted_formula_slots"][slot]
    assert [item["value"] for item in omitted] == [bodies[3], bodies[3]]
    assert [item["span"] for item in omitted] == [
        detail["span"] for detail in getattr(norm, slot)[4:6]
    ]
    assert omitted[0]["span"] != omitted[1]["span"]
    assert all(item["predicate"] + "(x)" not in record["formula"] for item in omitted)


def test_normalization_aliases_are_counted_as_one_rendered_predicate():
    sequence = ["fees are paid", "the fees are paid", "inspection is complete", "notice is posted"]
    norm = source_norm(conditions=sequence)
    assert len(norm.conditions) == 4
    record = build_deontic_formula_record_from_ir(norm)
    assert record["formula"].count("FeesArePaid(x)") == 1
    assert record["omitted_formula_slots"] == {}
    assert not set(record["blockers"]) & MARKERS
    assert record["proof_ready"] is True


def test_reference_provenance_does_not_consume_substantive_condition_capacity():
    norm = source_norm(prefix="Subject to section 552, ", conditions=CONDITIONS[:3])
    record = build_deontic_formula_record_from_ir(norm)
    assert not set(record["blockers"]) & MARKERS
    assert [item["value"] for item in record["omitted_formula_slots"]["conditions"]] == ["section 552"]
    assert all(normalize_predicate_name(body) + "(x)" in record["formula"] for body in CONDITIONS[:3])


def test_reference_omission_is_preserved_alongside_actual_substantive_cap_loss():
    norm = source_norm(prefix="Subject to section 552, ", conditions=CONDITIONS[:4])
    record = build_deontic_formula_record_from_ir(norm)
    assert [item["value"] for item in record["omitted_formula_slots"]["conditions"]] == [
        "section 552", CONDITIONS[3]
    ]
    assert "formula_condition_cap_exceeded" in record["blockers"]
    assert "cross_reference_requires_resolution" in record["blockers"]
    assert record["proof_ready"] is False


def test_batch_readiness_does_not_clear_cap_blockers_or_change_norms():
    norms = [source_norm(conditions=CONDITIONS[:4]), source_norm(exceptions=EXCEPTIONS[:4])]
    before = deepcopy(norms)
    records = build_deontic_formula_records_from_irs(norms)
    assert [set(record["blockers"]) & MARKERS for record in records] == [
        {"formula_condition_cap_exceeded"}, {"formula_exception_cap_exceeded"}
    ]
    assert all(not record["proof_ready"] and record["deterministic_resolution"] == {} for record in records)
    assert norms == before


def test_frame_renderer_is_not_reported_as_using_deontic_antecedent_caps():
    source = "This section applies to food carts " + ", ".join("if " + value for value in CONDITIONS[:4]) + "."
    norm = LegalNormIR.from_parser_element(extract_normative_elements(source)[0])
    record = build_deontic_formula_record_from_ir(norm)
    assert record["formula"].startswith("AppliesTo(")
    assert not set(record["blockers"]) & MARKERS
