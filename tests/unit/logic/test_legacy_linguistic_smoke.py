"""Keep operational checks distinct from observable historical semantic gaps."""

import importlib.util
from pathlib import Path


def _audit(formulas, expected):
    path = Path(__file__).resolve().parents[3] / "scripts/ops/legal_ir/smoke_legacy_linguistic_autoencoder.py"
    spec = importlib.util.spec_from_file_location("legacy_linguistic_smoke_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = "The officer shall retain records for at least 20 days."
    observations = [{"source_text": source,
                     "linguistic_observation": {"modal_ir": {"formulas": formulas}},
                     "decompiled": {"text": source}}]
    gates = {"rows": [{"source_text": source, "rule_with_parser_sidecars": expected}]}
    return module._semantic_audit(observations, gates)


def test_temporal_f_does_not_hide_wrong_deontic_operator_or_missing_quantity():
    formulas = [
        {"operator": {"family": "deontic", "symbol": "O"},
         "predicate": {"name": "retain", "arguments": ["records"]},
         "provenance": {"source_text": "20 days"}, "metadata": {"quantity": 20},
         "formula_id": "20"},
        {"operator": {"family": "temporal", "symbol": "F"}},
    ]
    result = _audit(formulas, {"modality": "F", "temporal_records": [
        {"quantity": 20, "temporal_kind": "minimum_duration"}]})
    assert result["semantic_conflict_count"] == 1
    assert result["coverage_gap_count"] == 1
    assert result["rows"][0]["decompiled_text_matches_source"] is True
    assert result["formula_fidelity_verified"] is False
    assert result["admitted"] is False


def test_token_presence_does_not_grant_semantic_equivalence():
    formulas = [{"operator": {"family": "deontic", "symbol": "F"},
                 "predicate": {"name": "retain", "arguments": ["20 days"]}}]
    result = _audit(formulas, {"modality": "F", "temporal_records": [
        {"quantity": 20, "temporal_kind": "minimum_duration"}]})
    assert result["known_issue_count"] == 0
    assert result["formula_fidelity_verified"] is False
    assert result["complete_semantic_equivalence_check"] is False
    assert result["admitted"] is False
