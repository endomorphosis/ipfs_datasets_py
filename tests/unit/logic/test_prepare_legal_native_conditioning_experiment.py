from copy import deepcopy
import pytest
from scripts.ops.legal_ir import prepare_legal_native_conditioning_experiment as preparation
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span


def test_fresh_panels_have_disjoint_values_and_exact_copy_targets():
    panels = preparation.make_panels({"splits": {"train": []}})
    assert {k: len(v) for k, v in panels.items()} == {"train": 384, "tuning": 96, "challenge": 192}
    for rows in panels.values():
        assert span.audit_examples(rows)["all_supported"]
    actors = {split: {r["canonical_ir"]["rules"][0]["actor"] for r in rows} for split, rows in panels.items()}
    assert not actors["train"] & actors["challenge"]
    assert not actors["tuning"] & actors["challenge"]
    assert max(len(s.split()) for s in actors["train"]) == 7


def test_previous_training_is_copied_without_formal_embeddings():
    old = preparation.make_panels({"splits": {"train": []}})["train"][0]
    old = deepcopy(old)
    old["id"] = "old-independent"
    old["family_group"] = "old-independent"
    # Make an independent old source using the existing renderer.
    old["source_text"] = old["source_text"].replace("Aspen", "Independent").replace("aspen", "independent")
    old["canonical_ir"]["rules"][0]["actor"] = old["canonical_ir"]["rules"][0]["actor"].replace("Aspen", "Independent")
    old["canonical_ir"]["rules"][0]["object"] = old["canonical_ir"]["rules"][0]["object"].replace("aspen", "independent")
    old["source_sha256"] = preparation.shared.sha(old["source_text"].encode())
    old["canonical_target_sha256"] = preparation.shared.sha(preparation.shared.canonical_bytes(old["canonical_ir"]))
    old["formal_embedding"] = [99.]
    before = deepcopy(old)
    panels = preparation.make_panels({"splits": {"train": [old]}})
    assert len(panels["train"]) == 385 and "formal_embedding" not in panels["train"][0]
    assert old == before


def test_reusing_exposed_challenge_source_is_rejected():
    exposed = preparation.make_panels({"splits": {"train": []}})["challenge"][0]
    with pytest.raises(ValueError, match="overlaps previous"):
        preparation.make_panels({"splits": {"train": [], "challenge": [exposed]}})
