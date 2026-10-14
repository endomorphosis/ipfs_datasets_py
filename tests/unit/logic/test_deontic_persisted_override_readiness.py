"""A cached override-only clearance cannot validate newly represented scope."""
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.deontic.exports import (
    build_decoder_record_from_ir,
    parser_element_has_active_repair,
    parser_elements_for_metrics,
    parser_elements_with_ir_export_readiness,
)
from ipfs_datasets_py.logic.deontic.metrics import summarize_parser_elements
from ipfs_datasets_py.logic.deontic.formula_builder import build_deontic_formula_record_from_ir
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


PURE_OVERRIDE = "Notwithstanding section 5.01.020, the Director may issue a variance."
APPROVAL_OVERRIDE = (
    "Subject to approval, notwithstanding section 5.01.020, the Director may issue a variance."
)


def cached_row(text):
    pure = LegalNormIR.from_parser_element(extract_normative_elements(PURE_OVERRIDE)[0])
    resolution = build_deontic_formula_record_from_ir(pure)["deterministic_resolution"]
    assert resolution["type"] == "pure_precedence_override"
    row = deepcopy(extract_normative_elements(text)[0])
    row["export_readiness"].update(
        formula_proof_ready=True,
        formula_requires_validation=False,
        formula_repair_required=False,
        deterministic_resolution=resolution,
    )
    return row


@pytest.mark.parametrize(("text", "slot"), [
    (APPROVAL_OVERRIDE, "conditions"),
    ("Notwithstanding section 5.01.020, the Director may issue a variance unless approval is denied.", "exceptions"),
    ("Notwithstanding section 5.01.020, the Director may issue a variance within 10 days.", "temporal_constraints"),
])
def test_cached_pure_override_cannot_clear_a_represented_qualifier(text, slot):
    row = cached_row(text)
    before = deepcopy(row)
    norm = LegalNormIR.from_parser_element(row)
    assert getattr(norm, slot)
    record = build_deontic_formula_record_from_ir(norm)
    assert record["proof_ready"] is False
    assert record["requires_validation"] is True
    assert record["repair_required"] is True
    assert record["deterministic_resolution"] == {}
    assert "override_clause_requires_precedence_review" in record["blockers"]
    assert row == before


def test_persisted_pure_override_control_keeps_existing_clearance():
    row = cached_row(PURE_OVERRIDE)
    # Legacy rows may omit blocker lists while persisting explicit readiness.
    row["export_readiness"]["blockers"] = []
    row["parser_warnings"] = []
    norm = LegalNormIR.from_parser_element(row)
    record = build_deontic_formula_record_from_ir(norm)
    assert record["proof_ready"] is True
    assert record["deterministic_resolution"]["type"] == "pure_precedence_override"


def test_recovered_approval_reaches_export_and_metric_readiness():
    row = cached_row(APPROVAL_OVERRIDE)
    before = deepcopy(row)
    norm = LegalNormIR.from_parser_element(row)
    record = build_deontic_formula_record_from_ir(norm)
    assert "Approval(x)" in record["formula"]
    assert norm.conditions[0]["span"] == [11, 19]
    assert norm.source_text[11:19] == "approval"
    for project in (parser_elements_with_ir_export_readiness, parser_elements_for_metrics):
        projected, = project([row])
        readiness = projected["export_readiness"]
        assert readiness["formula_proof_ready"] is False
        assert readiness["formula_requires_validation"] is True
        assert readiness["formula_repair_required"] is True
        assert readiness["deterministic_resolution"] == {}
    assert row == before


def test_previously_inactive_projection_cannot_restore_stale_override_clearance():
    row = cached_row(APPROVAL_OVERRIDE)
    resolution = deepcopy(row["export_readiness"]["deterministic_resolution"])
    row.update(active_repair_required=False, repair_required=False,
               active_repair_warnings=[], repair_required_warnings=[])
    row["export_readiness"].update(metric_requires_validation=False, metric_repair_required=False)
    row["llm_repair"].update(required=False, deterministically_resolved=True,
                             deterministic_resolution=resolution)
    before = deepcopy(row)
    projected, = parser_elements_for_metrics([row])
    assert projected["export_readiness"]["formula_proof_ready"] is False
    assert projected["export_readiness"]["deterministic_resolution"] == {}
    assert projected["active_repair_required"] is True
    assert projected["export_readiness"]["metric_repair_required"] is True
    assert parser_element_has_active_repair(projected) is True
    # Repeated metric projection cannot resurrect the old clearance.
    repeated, = parser_elements_for_metrics([projected])
    assert repeated["export_readiness"]["formula_proof_ready"] is False
    assert repeated["active_repair_required"] is True
    summary = summarize_parser_elements([row])
    assert summary["repair_required_count"] == 1
    assert summary["phase8_parser_capability_formula_ready_rate"] == 0.0
    decoder = build_decoder_record_from_ir(LegalNormIR.from_parser_element(row))
    assert decoder["requires_validation"] is True
    assert row == before
