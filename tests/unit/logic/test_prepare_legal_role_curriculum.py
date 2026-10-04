"""Authored corpus coordinates, pair identity, leakage, and seal boundaries."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts.ops.legal_ir import prepare_legal_role_curriculum as corpus


@pytest.fixture(scope="module")
def panels():
    return {name: corpus.make_panel(name) for name in corpus.COUNTS}


def test_full_inventory_has_exact_counts_pairs_and_modalities(panels):
    for name, (rows, annotations, pairs) in panels.items():
        assert len(rows) == len(annotations) == corpus.COUNTS[name]
        assert len(pairs) == len(rows) // 2
        assert Counter(r["canonical_ir"]["rules"][0]["modality"] for r in rows) == {m: len(rows) // 3 for m in "OPF"}
        assert len({p["case_group"] for p in pairs}) == len(pairs)
        corpus.validate_pairs(rows, pairs, len(pairs))


def test_every_annotation_and_trigger_slices_exact_authored_content(panels):
    for rows, annotations, _ in panels.values():
        for row, annotation in zip(rows, annotations, strict=True):
            corpus.validate_row(row)
            rule = row["canonical_ir"]["rules"][0]
            assert annotation["source_sha256"] == corpus.sha(row["source_text"].encode())
            actual_mask = sum((1 << index) for index, name in enumerate(corpus.FIELDS[3:]) if rule[name])
            assert annotation["presence_mask"] == actual_mask
            for name in corpus.FIELDS:
                value = rule[name]
                if isinstance(value, list): value = value[0] if value else None
                span = row["facet_spans"][name]
                assert (span is None) == (value is None)
                if span is not None: assert row["source_text"][slice(*span)] == value


def test_pair_targets_equal_but_renderings_and_offsets_independent(panels):
    for rows, _, pairs in panels.values():
        by_id = {row["id"]: row for row in rows}
        for pair in pairs:
            left, right = (by_id[pair[k]] for k in ["left_id", "right_id"])
            assert left["canonical_ir"] == right["canonical_ir"]
            assert left["source_text"] != right["source_text"]
            assert left["trigger_span"] != right["trigger_span"] or left["source_text"][slice(*left["trigger_span"])] != right["source_text"][slice(*right["trigger_span"])]


def test_new_split_source_meaning_and_concrete_templates_disjoint(panels):
    rows = {key: value[0] for key, value in panels.items()}
    annotations = {key: value[1] for key, value in panels.items()}
    result = corpus.validate_panels(rows, annotations)
    assert result["source_count"] == 624 and result["meaning_count"] == 312
    assert result["cross_split_template_overlap"] == 0
    assert "prior-template novelty" in result["scope"]
    assert "shared function words" in result["lexical_scope"]


def test_selected_content_lexicons_are_disjoint():
    for dictionary in [corpus.VERBS, corpus.ROLE_NOUNS]:
        seen = set()
        for values in dictionary.values():
            assert not seen & set(values)
            seen.update(values)
    assert len(set(corpus.PREFIXES.values())) == 3


def test_preposed_dates_have_real_temporal_coordinates_and_pair_identity(panels):
    for name, (rows, annotations, _) in panels.items():
        for row, annotation in zip(rows, annotations, strict=True):
            if annotation["family"] == "preposed_date":
                assert row["canonical_ir"]["rules"][0]["temporal"]
                start, end = row["facet_spans"]["temporal"]
                assert row["source_text"][start:end].startswith("before 20")


def test_extent_and_editorial_stipulations_remain_explicit(panels):
    for rows, annotations, _ in panels.values():
        for row, annotation in zip(rows, annotations, strict=True):
            assert annotation["annotation_authority"] == "authored_controlled_example_not_statutory_gold"
            if annotation["family"] == "extent_framing":
                assert row["canonical_ir"]["rules"][0]["conditions"]
            for note in annotation["editorial_context"]:
                assert row["source_text"][note["start_char"]:note["end_char"]] == note["source_text"]
                assert note["author_stipulated_role"] == "nonoperative_editorial_context"
                for span in row["facet_spans"].values():
                    if span: assert span[1] <= note["start_char"] or span[0] >= note["end_char"]


def test_each_optional_facet_has_positive_and_negative_examples(panels):
    for rows, _, _ in panels.values():
        for name in corpus.FIELDS[3:]:
            present = sum(bool(r["canonical_ir"]["rules"][0][name]) for r in rows)
            assert 0 < present < len(rows)


@pytest.mark.parametrize("mutation", ["trigger", "facet", "missing", "force", "identity"])
def test_invalid_source_coordinates_and_labels_rejected(panels, mutation):
    row = deepcopy(panels["train"][0][0])
    if mutation == "trigger": row["trigger_span"][0] += 1
    elif mutation == "facet": row["facet_spans"]["actor"] = row["trigger_span"]
    elif mutation == "missing": row["facet_spans"]["actor"] = None
    elif mutation == "force": row["canonical_ir"]["rules"][0]["modality"] = "P"
    else: row["id"] = "role-train-wrong"
    with pytest.raises((ValueError, TypeError)):
        corpus.validate_row(row)


@pytest.mark.parametrize("mutation", ["tuple", "missing_side", "duplicate_row", "wrong_meaning", "duplicate_case"])
def test_malformed_pair_inventory_rejected(panels, mutation):
    rows, _, pairs = deepcopy(panels["train"])
    if mutation == "tuple": pairs = tuple(pairs)
    elif mutation == "missing_side": pairs[0].pop("right_id")
    elif mutation == "duplicate_row": pairs[1]["left_id"] = pairs[0]["left_id"]
    elif mutation == "wrong_meaning": rows[1]["canonical_ir"]["rules"][0]["modality"] = "F"
    else: pairs[1]["case_group"] = pairs[0]["case_group"]
    with pytest.raises((ValueError, KeyError)):
        corpus.validate_pairs(rows, pairs, 192)


def test_annotation_source_binding_cannot_drift(panels):
    rows = {k: deepcopy(v[0]) for k, v in panels.items()}
    annotations = {k: deepcopy(v[1]) for k, v in panels.items()}
    annotations["train"][0]["source_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="annotation source"):
        corpus.validate_panels(rows, annotations)


def loader_fixture(tmp_path, panels, monkeypatch):
    def write(name, value):
        p = tmp_path / name; p.write_text(json.dumps(value)); return corpus.file_ref(p)
    artifacts = {
        "new_training": write("train.json", panels["train"][0]),
        "training_pairs": write("train-pairs.json", panels["train"][2]),
        "new_tuning": write("tuning.json", panels["tuning"][0]),
        "tuning_pairs": write("tuning-pairs.json", panels["tuning"][2]),
        "challenge_sources": write("sources.json", [{"id": r["id"], "source_text": r["source_text"]} for r in panels["fresh"][0]])}
    for key in corpus.SEALED:
        artifacts[key] = {"path": str(tmp_path / (key + ".sealed.json")), "sha256": "0" * 64, "bytes": 0}
    old = {"replay": {}, "tuning": {"earlier": [], "temporal": []}, "new_train": [], "new_tuning": []}
    monkeypatch.setattr(corpus.previous, "load_training_inputs", lambda _: old)
    manifest = {"schema": corpus.SCHEMA, "frozen_before_training": True, "counts": corpus.COUNTS,
                "sealed_artifacts": list(corpus.SEALED), "generator": corpus.file_ref(corpus.__file__),
                "dependencies": {}, "inputs": {"prior_corpus": write("prior.json", {})}, "artifacts": artifacts}
    pin = write("manifest.json", manifest)
    return Path(pin["path"]), manifest


def test_training_loader_never_opens_sealed_targets_pairs_or_ledgers(tmp_path, panels, monkeypatch):
    path, manifest = loader_fixture(tmp_path, panels, monkeypatch)
    forbidden = {a["path"] for k, a in manifest["artifacts"].items() if k in corpus.SEALED}
    opened = []
    original = Path.open
    def tracked(self, *args, **kwargs):
        opened.append(str(self)); assert str(self) not in forbidden
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, "open", tracked)
    loaded = corpus.load_training_inputs(path)
    assert len(loaded["new_train"]) == 384 and len(loaded["new_tuning"]) == 96
    assert len(loaded["fresh_sources"]) == 144
    assert all(set(r) == {"id", "source_text"} for r in loaded["fresh_sources"])
    assert not forbidden & set(opened)


@pytest.mark.parametrize("field", ["counts", "sealed_artifacts"])
def test_loader_rejects_metadata_denominator_or_seal_drift(tmp_path, panels, monkeypatch, field):
    path, manifest = loader_fixture(tmp_path, panels, monkeypatch)
    manifest[field] = {} if field == "counts" else []
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="denominators or seal"):
        corpus.load_training_inputs(path)


def test_loader_rejects_recommitted_duplicate_source_only_challenge(tmp_path, panels, monkeypatch):
    path, manifest = loader_fixture(tmp_path, panels, monkeypatch)
    source_path = Path(manifest["artifacts"]["challenge_sources"]["path"])
    sources = json.loads(source_path.read_text()); sources[1] = sources[0]
    source_path.write_text(json.dumps(sources)); manifest["artifacts"]["challenge_sources"] = corpus.file_ref(source_path)
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="duplicates or overlaps"):
        corpus.load_training_inputs(path)
