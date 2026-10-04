"""The pilot must not confuse targets, conditioning and build evidence."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("legal_pilot_runner", ROOT / "scripts/ops/legal_ir/run_legal_decoder_pilot.py")
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)


def corpus():
    fixture = json.loads((ROOT / "tests/fixtures/legal_formula_learning/v1.json").read_text())
    return {"label_origin": pilot.LABEL_ORIGIN, "splits": {
        split: [{**copy.deepcopy(row), "embedding": [.1] * 384} for row in fixture[split]]
        for split in ("train", "tuning", "heldout", "regression")}}


def test_original_fixture_is_disjoint_and_target_labels_are_explicit():
    data = corpus()
    assert len(pilot.validate_corpus(data)["heldout"]) == 12
    data["label_origin"] = "reviewed_gold"
    with pytest.raises(ValueError, match="authored synthetic"):
        pilot.validate_corpus(data)


def test_normalized_source_and_target_overlap_are_rejected():
    data = corpus()
    data["splits"]["heldout"][0]["source_text"] = data["splits"]["train"][0]["source_text"].upper()
    with pytest.raises(ValueError, match="source overlap"):
        pilot.validate_corpus(data)
    data = corpus()
    data["splits"]["heldout"][0]["canonical_ir"] = data["splits"]["train"][0]["canonical_ir"]
    with pytest.raises(ValueError, match="target overlap"):
        pilot.validate_corpus(data)


def test_vector_controls_never_receive_targets_and_leave_source_bindings_intact():
    rows = [{"id": str(i), "source_text": f"source {i}", "latent": [float(i), 1.],
             "canonical_ir": {"secret": i}, "embedding": [42.]} for i in range(3)]
    original = copy.deepcopy(rows)
    normal = pilot.inference_inputs(rows)
    rotated = pilot.inference_inputs(rows, "rotated_latent")
    zero = pilot.inference_inputs(rows, "zero_latent")
    assert rows == original
    assert all(set(row) == {"id", "source_text", "latent"} for row in normal + rotated + zero)
    for i in range(3):
        assert normal[i]["source_text"] == rotated[i]["source_text"] == zero[i]["source_text"]
        assert rotated[i]["latent"] == rows[(i + 1) % 3]["latent"]
        assert zero[i]["latent"] == [0., 0.]


def test_build_selection_keeps_wrong_predictions_and_does_not_erase_qualifiers():
    sources = corpus()["splits"]["heldout"][:3]
    wrong = copy.deepcopy(sources[0]["canonical_ir"])
    for facet in ("conditions", "exceptions", "temporal"):
        wrong["rules"][0][facet] = []
    wrong["rules"][0]["actor"] = "incorrect_actor"
    qualified = copy.deepcopy(wrong)
    qualified["rules"][0]["exceptions"] = ["emergency"]
    report = {"rows": [
        {"id": sources[0]["id"], "status": "decoded", "canonical_ir": wrong},
        {"id": sources[1]["id"], "status": "decoded", "canonical_ir": qualified},
        {"id": sources[2]["id"], "status": "abstained", "canonical_ir": None}]}
    candidates, excluded = pilot.build_candidates(report, sources, 1729)
    assert len(candidates) == 1 and candidates[0]["canonical_ir"] == wrong
    assert candidates[0]["source_sha256"] == hashlib.sha256(sources[0]["source_text"].encode()).hexdigest()
    assert [row["reason"] for row in excluded] == ["qualified_rule_lowering_unsupported", "decoder_abstained"]
    assert qualified["rules"][0]["exceptions"] == ["emergency"]


def test_duplicate_json_keys_and_nonfinite_values_are_rejected(tmp_path):
    path = tmp_path / "input.json"
    path.write_text('{"a": 1, "a": 2}')
    with pytest.raises(ValueError, match="duplicate"):
        pilot.read(path)
    path.write_text('{"a": NaN}')
    with pytest.raises(ValueError, match="nonfinite"):
        pilot.read(path)
