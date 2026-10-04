"""The calendar replay policy is explicit and never fills missing model output."""
import hashlib
from copy import deepcopy
import pytest

from scripts.ops.legal_ir import check_legal_calendar_decoder_outputs as replay


def candidate(temporal):
    text = "An authored policy test source."
    return {"candidate_id": "test:one", "source_text": text,
        "source_sha256": hashlib.sha256(text.encode()).hexdigest(), "canonical_ir": {"rules": [{
            "modality": "O", "actor": "agency", "action": "retain", "object": "record",
            "conditions": [], "exceptions": [], "temporal": temporal}]}}


def test_explicit_calendar_policy_fills_only_declared_source_indices():
    row = candidate(["before 2000-03-01"])
    interpreted = replay.synthetic_interpretation(row, policy=replay.POLICY)
    clock = interpreted["formulas"][0]["temporal"]
    assert clock["date_ordinal"] == 730180
    assert clock["upper_inclusive"] is False
    assert clock["ordinal_epoch_value"] == 1
    assert replay.POLICY_DESCRIPTION["independently_reviewed"] is False


def test_missing_temporal_is_never_created_by_policy():
    row = candidate([])
    snapshot = deepcopy(row)
    interpreted = replay.synthetic_interpretation(row, policy=replay.POLICY)
    assert interpreted["formulas"][0]["temporal"] is None
    assert row == snapshot


def test_no_policy_default_and_no_invalid_calendar_repair():
    with pytest.raises(ValueError):
        replay.synthetic_interpretation(candidate([]), policy="unspecified")
    with pytest.raises(ValueError):
        replay.synthetic_interpretation(candidate(["before 1900-02-29"]), policy=replay.POLICY)


def test_source_and_free_generation_bindings_are_checked_before_selection():
    row = candidate(["before 2000-03-01"])
    source = {"id": row["candidate_id"], "source_text": row["source_text"], "source_sha256": row["source_sha256"]}
    generation = {"id": source["id"], "source_sha256": source["source_sha256"], "status": "decoded",
                  "target_access": False, "teacher_forcing": False, "canonical_ir": row["canonical_ir"]}
    selected = replay.select_candidates([source], [generation], toolchain="leanprover/lean4:v4.34.1", policy=replay.POLICY)
    assert selected["supported_count"] == 1 and not selected["excluded"]
    generation["target_access"] = True
    with pytest.raises(ValueError):
        replay.select_candidates([source], [generation], toolchain="leanprover/lean4:v4.34.1", policy=replay.POLICY)
