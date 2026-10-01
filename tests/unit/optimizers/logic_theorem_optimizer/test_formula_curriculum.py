"""The fixed source panel is a data-design diagnostic, never formula gold."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import formula_curriculum as curriculum


ROOT = Path(__file__).resolve().parents[4]
PANEL = ROOT / "tests/fixtures/logic/actor_composition_panel.json"
OLD = ROOT / "tests/fixtures/logic/legacy_teacher_distillation.json"
MANIFEST_SHA = "2e8c4e2726e97b5faf87f9d7aa52e98354ce2385fc8d4a44f231d8967c1c2095"
EXPOSED_PAIRS = [("officer", "disclose"), ("agency", "retain"), ("Company A", "disclose"), ("officer", "submit")]


def exclusions():
    return dict(excluded_source_texts=[row["text"] for row in json.loads(OLD.read_text())["rows"]],
                excluded_evaluation_actor_actions=EXPOSED_PAIRS)


def prepare(panel=None, **kwargs):
    options = exclusions()
    options.update(kwargs)
    return curriculum.prepare_curriculum(curriculum.build_authored_panel() if panel is None else panel, **options)


def test_fixture_is_exact_deterministic_panel_and_has_pinned_canonical_manifest():
    authored = curriculum.build_authored_panel()
    assert json.loads(PANEL.read_text()) == authored
    assert curriculum.manifest_digest(authored) == MANIFEST_SHA
    prepared = curriculum.load_curriculum(PANEL,
        expected_file_sha256=hashlib.sha256(PANEL.read_bytes()).hexdigest(),
        expected_manifest_sha256=MANIFEST_SHA, **exclusions())
    assert prepared.manifest_sha256 == MANIFEST_SHA
    assert prepared.receipt["manifest_sha256"] == MANIFEST_SHA


def test_balanced_pairs_and_marginals_are_disjoint_before_training():
    prepared = prepare()
    seen_pairs, seen_sources, seen_ids = set(), set(), set()
    for split, expected_rows, count in (("training", 24, 4), ("tuning", 6, 1), ("sealed_evaluation", 6, 1)):
        rows = prepared.rows(split)
        pairs = {(row["actor"], row["norm_template_id"]) for row in rows}
        sources = {" ".join(row["text"].casefold().split()) for row in rows}
        ids = {row["id"] for row in rows}
        assert len(rows) == len(pairs) == len(sources) == len(ids) == expected_rows
        assert not seen_pairs & pairs and not seen_sources & sources and not seen_ids & ids
        assert set(Counter(row["actor"] for row in rows).values()) == {count}
        assert set(Counter(row["norm_template_id"] for row in rows).values()) == {count}
        seen_pairs |= pairs; seen_sources |= sources; seen_ids |= ids
    assert len(seen_pairs) == 36
    assert seen_sources.isdisjoint(" ".join(text.casefold().split()) for text in exclusions()["excluded_source_texts"])


def test_diagonal_subset_is_training_only_and_preserves_every_actor_template_and_surface_atom():
    prepared = prepare()
    balanced = prepared.rows("training")
    diagonal = prepared.rows("training", training_subset="confounded_diagonal")
    assert len(diagonal) == 6 and all(row in balanced for row in diagonal)
    for name in ("actor", "norm_template_id"):
        assert {row[name] for row in balanced} == {row[name] for row in diagonal}
    assert prepared.receipt["splits"]["training"]["surface_vocabulary_sha256"] == prepared.receipt["confounded_diagonal"]["surface_vocabulary_sha256"]
    assert prepared.receipt["actor_template_surface_coverage_equal"] is True
    assert prepared.receipt["formula_vocabulary_equality_verified"] is False
    assert prepared.receipt["compiler_label_coverage_verified"] is False


def test_association_counts_do_not_mistake_balanced_marginals_for_independence():
    receipt = prepare().receipt
    balanced, diagonal = receipt["splits"]["training"], receipt["confounded_diagonal"]
    assert balanced["actor_template"]["actor_deterministic_given_value"] is False
    assert balanced["actor_action"]["actor_deterministic_given_value"] is False
    assert diagonal["actor_template"]["actor_deterministic_given_value"] is True
    # Report and deadline are separate norm templates sharing the submit action.
    assert diagonal["actor_action"]["actor_deterministic_given_value"] is False
    assert balanced["actor_template"]["mutual_information_bits"] == pytest.approx(0.5849625007211562)
    assert diagonal["actor_template"]["mutual_information_bits"] == pytest.approx(2.584962500721156)
    assert balanced["actor_template"]["max_actor_fraction_given_value"] == .25
    assert diagonal["actor_template"]["max_actor_fraction_given_value"] == 1.
    assert balanced["actor_template"]["independence_established"] is False


def test_existing_actor_action_pairs_do_not_enter_sealed_evaluation():
    prepared = prepare()
    templates = {row["id"]: row for row in prepared.manifest["norm_templates"]}
    for row in prepared.rows("sealed_evaluation"):
        assert (row["actor"], templates[row["norm_template_id"]]["action_surface"]) not in EXPOSED_PAIRS
    exposed = prepared.rows("sealed_evaluation")[0]
    pair = ["The " + exposed["actor"].upper(), templates[exposed["norm_template_id"]]["action_surface"].upper()]
    with pytest.raises(ValueError, match="actor/action pair overlaps"):
        prepare(excluded_evaluation_actor_actions=[pair])


def test_normalized_prior_source_overlap_rejects_any_split():
    for row in prepare().manifest["rows"][::7]:
        with pytest.raises(ValueError, match="source overlaps"):
            prepare(excluded_source_texts=["  " + row["text"].upper() + "  "])


@pytest.mark.parametrize("change,reason", [
    (lambda p: p["rows"][0].update(split="sealed_evaluation"), "source/split assignment"),
    (lambda p: p["rows"][0].update(text="The registrar may submit reports."), "source/split assignment"),
    (lambda p: p["rows"][0].update(actor="officer"), "source/split assignment"),
    (lambda p: p["rows"][0].update(norm_template_id="deadline"), "source/split assignment"),
    (lambda p: p["rows"][0].update(corpus="constitution"), "source/split assignment"),
    (lambda p: p["rows"][0].update(canonical_ir={"rules": []}), "unknown or missing"),
    (lambda p: p["rows"].reverse(), "row ordering differs"),
    (lambda p: p["rows"].pop(), "all 36"),
    (lambda p: p["rows"].__setitem__(1, deepcopy(p["rows"][0])), "duplicate"),
    (lambda p: p["split_policy"].update(evaluation_labels_used_for_selection=True), "split policy differs"),
    (lambda p: p["split_policy"].update(training_offsets=[1, 2, 3, 4]), "split policy differs"),
    (lambda p: p["actors"].reverse(), "actors or templates differ"),
    (lambda p: p["norm_templates"][0].update(action_surface="disclose"), "actors or templates differ"),
    (lambda p: p.update(admitted=True), "cannot assert qualification"),
    (lambda p: p.update(formalized=0), "cannot assert qualification"),
])
def test_mutation_cannot_silently_reassign_sources_splits_or_semantic_scope(change, reason):
    panel = curriculum.build_authored_panel()
    change(panel)
    with pytest.raises(ValueError, match=reason):
        prepare(panel)


def test_receipt_and_panel_accessors_are_copy_safe_and_have_no_labels_or_model_results():
    source = curriculum.build_authored_panel()
    prepared = prepare(source)
    expected = prepared.manifest
    source["rows"].clear()
    prepared.manifest["rows"].clear()
    prepared.rows("training")[0]["actor"] = "changed"
    prepared.receipt["splits"].clear()
    assert prepared.manifest == expected
    assert len(prepared.rows("training")) == 24
    assert set(prepared.receipt["splits"]) == set(curriculum.SPLITS)
    assert prepared.receipt["evaluation_labels_present"] is False
    for field in curriculum.FALSE:
        assert prepared.receipt[field] is False
    assert "not enforced" in prepared.receipt["evaluation_seal_enforcement"]


def test_manifest_and_file_hashes_are_separate_pins(tmp_path):
    path = tmp_path / "panel.json"
    panel = curriculum.build_authored_panel()
    path.write_text(json.dumps(panel))
    file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    prepared = curriculum.load_curriculum(path, expected_file_sha256=file_hash,
                                          expected_manifest_sha256=MANIFEST_SHA, **exclusions())
    assert prepared.manifest_sha256 != file_hash
    with pytest.raises(ValueError, match="manifest SHA-256 differs"):
        prepare(expected_manifest_sha256="0" * 64)
    with pytest.raises(ValueError, match="file SHA-256 differs"):
        curriculum.load_curriculum(path, expected_file_sha256="0" * 64, **exclusions())
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        prepare(expected_manifest_sha256="bad")


def test_missing_exclusion_declarations_and_invalid_subset_requests_fail():
    with pytest.raises(ValueError, match="previously exposed source texts"):
        prepare(excluded_source_texts=[])
    with pytest.raises(ValueError, match="previously exposed evaluation actor/action pairs"):
        prepare(excluded_evaluation_actor_actions=[])
    with pytest.raises(ValueError, match="malformed excluded"):
        prepare(excluded_evaluation_actor_actions=["officer/disclose"])
    prepared = prepare()
    with pytest.raises(ValueError, match="unknown curriculum split"):
        prepared.rows("holdout")
    with pytest.raises(ValueError, match="subsets apply only to training"):
        prepared.rows("sealed_evaluation", training_subset="confounded_diagonal")
    with pytest.raises(ValueError, match="unknown training subset"):
        prepared.rows("training", training_subset="best_predictions")


def test_duplicate_json_keys_and_oversized_payload_are_rejected(tmp_path, monkeypatch):
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema":1,"schema":2}')
    with pytest.raises(ValueError, match="invalid curriculum JSON"):
        curriculum.load_curriculum(path, **exclusions())
    monkeypatch.setattr(curriculum, "MAX_BYTES", 1)
    with pytest.raises(ValueError, match="byte bound"):
        prepare()
