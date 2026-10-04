from copy import deepcopy
import hashlib
import pytest
from scripts.ops.legal_ir import summarize_legal_calendar_decoder_outputs as summary
from scripts.ops.legal_ir import check_legal_calendar_decoder_outputs as checker


def example(temporal):
    source = {"id": "case", "source_text": "Agency shall retain records " + temporal + "."}
    source["source_sha256"] = hashlib.sha256(source["source_text"].encode()).hexdigest()
    ir = {"rules": [{"modality": "O", "actor": "Agency", "action": "retain", "object": "records",
                     "conditions": [], "exceptions": [], "temporal": [temporal] if temporal else []}]}
    candidate = {"candidate_id": source["id"], "source_text": source["source_text"],
                 "source_sha256": source["source_sha256"], "canonical_ir": ir}
    return source, {"canonical_ir": ir}, candidate


@pytest.mark.parametrize("temporal", ["before 2000-02-29", "before 0001-01-01", "within 1 day",
                                     "within 42 days", "for at least 3 hours", ""])
def test_independent_policy_matches_exact_declared_convention(temporal):
    source, prediction, candidate = example(temporal)
    declaration = summary.expected_interpretation(candidate)
    assert declaration == checker.synthetic_interpretation(candidate, policy=checker.POLICY)
    summary.verify_entry(source, prediction, {"candidate": candidate, "interpretation": declaration})


@pytest.mark.parametrize("field,value", [("upper_inclusive", True), ("date_ordinal", 0), ("calendar", "business")])
def test_changed_calendar_policy_is_rejected(field, value):
    source, prediction, candidate = example("before 2000-02-29")
    declaration = summary.expected_interpretation(candidate)
    declaration["formulas"][0]["temporal"][field] = value
    with pytest.raises(ValueError, match="interpretation differs"):
        summary.verify_entry(source, prediction, {"candidate": candidate, "interpretation": declaration})


def test_dropping_predicted_date_cannot_be_hidden_by_rebuilding_declaration():
    source, prediction, candidate = example("before 2000-02-29")
    edited = deepcopy(candidate)
    edited["canonical_ir"]["rules"][0]["temporal"] = []
    with pytest.raises(ValueError, match="frozen prediction"):
        summary.verify_entry(source, prediction, {"candidate": edited, "interpretation": summary.expected_interpretation(edited)})


def test_invalid_gregorian_date_is_rejected():
    _, _, candidate = example("before 1900-02-29")
    with pytest.raises(ValueError):
        summary.expected_interpretation(candidate)
