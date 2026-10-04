"""The expanded corpus tests new values without relabeling old grammar as new."""
import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("structured_retrieval_prepare", ROOT / "scripts/ops/legal_ir/prepare_legal_structured_retrieval_experiment.py")
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


def test_counts_new_values_and_variable_span_lengths():
    panels = prepare.make_panels()
    assert {split: len(rows) for split, rows in panels.items()} == {"train": 768, "tuning": 96, "challenge": 192}
    evidence = prepare.check_panels(panels)
    assert evidence["actor_word_lengths"] == [2, 3, 4, 5]
    assert evidence["object_word_lengths"] == [3, 4, 5, 6]
    assert evidence["source_token_maximum"] <= 256
    for field in ("actor", "object", "conditions", "exceptions", "temporal"):
        novelty = evidence["canonical_value_novelty"]["challenge"][field]
        assert novelty == {"distinct_values": 8, "unseen_in_current_train": 8, "unseen_in_prior_experiment": 8}
    assert evidence["canonical_value_novelty"]["challenge"]["action"]["unseen_in_current_train"] == 4


def test_preexisting_grammar_is_not_claimed_as_new():
    panels = prepare.make_panels()
    pairs = {split: {(row["template_id"], row["qualifier_pattern"]) for row in rows} for split, rows in panels.items()}
    assert len(pairs["train"]) == 64
    assert pairs["challenge"] <= pairs["train"]
    assert prepare.check_panels(panels)["globally_new_template_combinations_claimed"] is False


def test_shared_frozen_preparer_globals_are_unchanged():
    before = prepare.canonical_bytes(prepare.shared.make_panels())
    prepare.make_panels()
    assert prepare.canonical_bytes(prepare.shared.make_panels()) == before


def test_all_visible_targets_match_existing_canonical_contract():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_formula_codec
    for split, rows in prepare.make_panels().items():
        for row in rows:
            legal_formula_codec._rule(row["canonical_ir"])
            assert prepare.shared.source_spans(row["source_text"], row["canonical_ir"]) == row["source_spans"]


def test_old_complete_example_cannot_be_reintroduced():
    panels = prepare.make_panels()
    old = copy.deepcopy(prepare.shared.make_panels()["train"][0])
    old["id"] = "new-id-does-not-hide-old-content"
    panels["train"][0] = old
    with pytest.raises(ValueError, match="prior exposed source or target"):
        prepare.check_panels(panels)


def test_old_actor_atom_cannot_be_reused_in_an_otherwise_new_example():
    panels = prepare.make_panels()
    row = panels["train"][0]
    actor = prepare.shared.make_panels()["train"][0]["canonical_ir"]["rules"][0]["actor"]
    rule = row["canonical_ir"]["rules"][0]
    row["source_text"] = row["source_text"].replace(rule["actor"], actor)
    rule["actor"] = actor
    row["source_sha256"] = prepare.sha(row["source_text"].encode())
    row["canonical_target_sha256"] = prepare.sha(prepare.canonical_bytes(row["canonical_ir"]))
    row["source_spans"] = prepare.shared.source_spans(row["source_text"], row["canonical_ir"])
    with pytest.raises(ValueError, match="prior exposed canonical value"):
        prepare.check_panels(panels)


def test_modality_triple_cannot_be_split():
    panels = prepare.make_panels()
    panels["train"].pop()
    with pytest.raises(ValueError, match="modality triple incomplete"):
        prepare.check_panels(panels)


def test_family_cannot_cross_train_and_challenge():
    panels = prepare.make_panels()
    panels["challenge"][0]["family_group"] = panels["train"][0]["family_group"]
    with pytest.raises(ValueError, match="family crosses splits"):
        prepare.check_panels(panels)


def test_changed_canonical_commitment_is_rejected():
    panels = prepare.make_panels()
    panels["train"][0]["canonical_target_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="commitment differs"):
        prepare.check_panels(panels)
