"""The comparison keeps unseen composition and target leakage measurable."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("legal_comparison_prepare", ROOT / "scripts/ops/legal_ir/prepare_legal_decoder_comparison.py")
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


def fixture():
    return json.loads(prepare.FIXTURE.read_text())


def test_panels_use_only_original_training_vocabulary_and_keep_families_together():
    authored = fixture()
    panels = prepare.make_panels(authored)
    assert {key: len(rows) for key, rows in panels.items()} == {"development": 108, "challenge": 216}
    receipt = prepare.check_panels(authored, panels)
    assert receipt["source_and_complete_target_overlap"] == 0
    groups = [{row["actor_action_group"] for row in panels[key]} for key in panels]
    assert not groups[0] & groups[1]
    for rows in panels.values():
        families = {}
        for row in rows:
            families.setdefault(row["family_group"], set()).add(row["canonical_ir"]["rules"][0]["modality"])
        assert all(values == {"O", "P", "F"} for values in families.values())
        assert {row["qualifier_pattern"] for row in rows} >= {"deadline-exception", "minimum-exception"}


@pytest.mark.parametrize("field", ["source_text", "canonical_ir"])
def test_panel_cannot_reuse_a_prior_source_or_target(field):
    authored = fixture()
    panels = prepare.make_panels(authored)
    panels["challenge"][0][field] = copy.deepcopy(authored["train"][0][field])
    with pytest.raises(ValueError, match="overlap"):
        prepare.check_panels(authored, panels)


def test_minimal_pair_family_cannot_cross_new_partitions():
    authored = fixture()
    panels = prepare.make_panels(authored)
    panels["challenge"].append(panels["development"].pop())
    with pytest.raises(ValueError, match="crosses partitions"):
        prepare.check_panels(authored, panels)


def test_new_words_are_not_fitted_from_evaluation():
    authored = fixture()
    panels = prepare.make_panels(authored)
    panels["challenge"][0]["source_text"] += " genuinely-unseen-token"
    with pytest.raises(ValueError, match="out-of-vocabulary"):
        prepare.check_panels(authored, panels)


def test_source_oov_panel_does_not_infer_targets():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_formula_codec
    codec = legal_formula_codec.fit_codec(fixture()["train"])
    queue = {"repository": "justicedao/uscode-autoformal-span-cache", "revision": prepare.DATASET_REVISION,
             "entries": [{"source_span_id": "observed-fragment", "source_text_variants": ["L."],
                          "source_text_consistent_across_occurrences": True, "legal_ids": ["usc:example"]}]}
    row = prepare.oov_panel(queue, codec)[0]
    assert row["source_text"] == "L."
    assert row["source_codec_rejection"]
    assert not row["target_available"] and not row["training_qualified"]
    assert "canonical_ir" not in row


def test_saved_plan_is_exclusive_and_detects_changes(tmp_path):
    path = tmp_path / "plan.json"
    ref = prepare.save(path, {"sealed": True})
    assert json.loads(prepare.verify_ref(ref)) == {"sealed": True}
    with pytest.raises(FileExistsError):
        prepare.save(path, {"sealed": False})
    path.write_text('{"sealed":false}')
    with pytest.raises(ValueError, match="differs"):
        prepare.verify_ref(ref)
