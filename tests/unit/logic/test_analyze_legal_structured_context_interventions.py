"""Field-effect counts separate decoded changes from abstention transitions."""
import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("context_effects", ROOT / "scripts/ops/legal_ir/analyze_legal_structured_context_interventions.py")
effects = importlib.util.module_from_spec(spec)
spec.loader.exec_module(effects)


def candidate(condition=True):
    rule = {"modality": "O", "actor": "Office", "action": "retain", "object": "records",
            "conditions": ["ready"] if condition else [], "exceptions": [], "temporal": []}
    facets = {field: {"char_start": 0, "char_end": 1} for field in effects.shared.SPAN_FIELDS}
    for field in effects.shared.QUALIFIERS:
        if not rule[field]:
            facets[field] = {"char_start": None, "char_end": None}
    return {"source_sha256": "same-source", "status": "decoded", "canonical_ir": {"rules": [rule]},
            "span_diagnostics": {"facets": facets}}


def test_presence_and_modality_changes_are_counted_separately():
    normal, changed = candidate(), candidate(False)
    changed["canonical_ir"]["rules"][0]["modality"] = "F"
    result = effects.field_changes([normal], [changed])
    assert result["canonical_output_or_status_changed"] == 1
    assert result["both_decoded_denominator"] == 1
    assert result["field_changed_among_both_decoded"]["modality"] == 1
    assert result["qualifier_presence_changed_among_both_decoded"]["conditions"] == 1
    assert result["qualifier_value_changed_when_both_present"]["conditions"] == 0
    assert result["span_boundary_changed_among_both_decoded"]["conditions"] == 1


def test_abstention_is_excluded_from_decoded_field_denominator():
    normal = candidate()
    changed = {**copy.deepcopy(normal), "status": "abstained", "canonical_ir": None}
    result = effects.field_changes([normal], [changed])
    assert result["status_transitions"] == {"decoded_to_abstained": 1}
    assert result["both_decoded_denominator"] == 0
    assert not any(result["field_changed_among_both_decoded"].values())


def test_intervention_cannot_change_source_binding():
    normal, changed = candidate(), candidate()
    changed["source_sha256"] = "another-source"
    with pytest.raises(ValueError, match="source changed"):
        effects.field_changes([normal], [changed])
