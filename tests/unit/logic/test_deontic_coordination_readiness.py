"""Alternative-duty source evidence remains authoritative in mixed batches."""
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.deontic.exports import (
    build_document_export_tables_from_ir,
    parser_elements_for_metrics,
)
from ipfs_datasets_py.logic.deontic.formula_builder import build_deontic_formula_record_from_ir
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


ALTERNATIVE = "The Secretary shall publish notice or shall file the report."
INDEPENDENT = "The Registrar shall record the decision."
MARKER = "formula_coordination_scope_unresolved"


@pytest.mark.parametrize("identity", ["shared", "", None])
@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_or_missing_ids_cannot_borrow_independent_readiness(identity, reverse):
    blocked = extract_normative_elements(ALTERNATIVE)[0]
    clear, = extract_normative_elements(INDEPENDENT)
    rows = [blocked, clear]
    if reverse:
        rows.reverse()
    for row in rows:
        if identity is not None:
            row["source_id"] = identity
        row["export_readiness"].update({
            "formula_proof_ready": True, "formula_requires_validation": False,
            "formula_repair_required": False,
            "deterministic_resolution": {"type": "core_slots_complete"},
        })
    original = deepcopy(rows)
    for _ in range(3):
        rows = parser_elements_for_metrics(rows)
        for row in rows:
            unresolved = " or " in row["text"]
            ready = row["export_readiness"]
            assert ready["formula_proof_ready"] is (not unresolved)
            assert row["active_repair_required"] is unresolved
            assert (MARKER in ready.get("formula_blockers", [])) is unresolved
    tables = build_document_export_tables_from_ir([LegalNormIR.from_parser_element(row) for row in rows])
    for row in tables["canonical"]:
        assert row["proof_ready"] is (" or " not in row["text"])
    for row in tables["decoder_reconstructions"]:
        unresolved = " or " in row["source_text"]
        assert row["proof_ready"] is (not unresolved)
        assert row["requires_validation"] is unresolved
        assert bool(row.get("coordination_scope_evidence")) is unresolved
    assert [blocked, clear] == (list(reversed(original)) if reverse else original)


def test_exported_group_edits_do_not_mutate_future_source_evidence():
    element = extract_normative_elements(ALTERNATIVE)[0]
    norm = LegalNormIR.from_parser_element(element)
    original = deepcopy(norm)
    first = build_deontic_formula_record_from_ir(norm)
    expected = deepcopy(first["coordination_scope_evidence"])
    first["coordination_scope_evidence"][0]["connectors"][0]["raw_text"] = "and"
    first["coordination_scope_evidence"][0]["scope_span"] = [0, 1]
    second = build_deontic_formula_record_from_ir(norm)
    assert second["coordination_scope_evidence"] == expected
    assert MARKER in second["blockers"]
    assert second["proof_ready"] is False
    assert norm == original
