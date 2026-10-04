"""Mixed-pool provenance, masked trigger supervision and sealed reader checks."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/ops/legal_ir/prepare_legal_mixed_replay_corpus.py"
SPEC = importlib.util.spec_from_file_location("mixed_replay_corpus", SCRIPT)
corpus = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(corpus)


def earlier_fixture():
    row = corpus.prior.render_row("train", "suffix_qualifiers", 7, "P")
    return {"id": "earlier-example", "source_text": row["source_text"], "canonical_ir": row["canonical_ir"],
        "source_sha256": corpus.sha(row["source_text"].encode()),
        "canonical_target_sha256": corpus.sha(corpus.canonical_bytes(row["canonical_ir"])),
        "source_spans": {field: [span] if span is not None else [] for field, span in row["facet_spans"].items() if field in corpus.FIELDS[3:]} |
            {field: row["facet_spans"][field] for field in corpus.FIELDS[:3]}}


def test_earlier_conversion_copies_facets_without_guessing_trigger():
    old = earlier_fixture()
    mixed = corpus.convert_earlier(old)
    assert set(mixed) == corpus.ROW_KEYS
    assert mixed["source_text"] == old["source_text"] and mixed["canonical_ir"] == old["canonical_ir"]
    assert mixed["trigger_span"] is None and mixed["trigger_supervised"] is False
    assert mixed["domain"] == "earlier"
    assert mixed["facet_spans"]["conditions"] == old["source_spans"]["conditions"][0]


def test_new_conversion_retains_exact_annotated_trigger():
    row = corpus.prior.render_row("train", "suffix_qualifiers", 0, "P")
    mixed = corpus.convert_new(row)
    assert {k: mixed[k] for k in corpus.prior.ROW_KEYS} == row
    assert mixed["domain"] == "new" and mixed["trigger_supervised"] is True


@pytest.mark.parametrize("kind", ["old_trigger", "old_supervised", "new_unsupervised", "missing_old_coordinate", "non_token", "new_domain", "extra_key"])
def test_invalid_domain_supervision_and_coordinates_rejected(kind):
    row = corpus.convert_earlier(earlier_fixture())
    if kind == "old_trigger":
        row["trigger_span"] = [0, 1]
    elif kind == "old_supervised":
        row["trigger_supervised"] = True
    elif kind == "new_unsupervised":
        row = corpus.convert_new(corpus.prior.render_row("train", "suffix_qualifiers", 0, "P"))
        row["trigger_supervised"] = False
    elif kind == "missing_old_coordinate":
        row["facet_spans"]["actor"] = None
    elif kind == "non_token":
        row["facet_spans"]["actor"][0] += 1
    elif kind == "new_domain":
        row["domain"] = "challenge"
    else:
        row["labels"] = {}
    with pytest.raises(ValueError):
        corpus.validate_row(row)


def test_earlier_source_and_target_hashes_are_verified():
    row = earlier_fixture()
    row["source_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="source hash"):
        corpus.convert_earlier(row)
    row = earlier_fixture()
    row["canonical_target_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="target hash"):
        corpus.convert_earlier(row)


def test_fresh_panel_size_balance_coordinates_and_determinism():
    rows, membership = corpus.make_challenge()
    assert len(rows) == len(membership) == 144
    assert corpus.make_challenge() == (rows, membership)
    assert corpus.Counter(r["canonical_ir"]["rules"][0]["modality"] for r in rows) == {"O": 48, "P": 48, "F": 48}
    assert corpus.Counter(membership.values()) == {c: 24 for c in corpus.CONSTRUCTIONS}
    assert len({r["source_text"] for r in rows}) == 144
    for row in rows:
        corpus.validate_row(row)


def test_rendered_repeated_actor_uses_occurrence_coordinates():
    row = corpus.render_challenge("exception_actor_condition_rule", 0, "O")
    actor = row["canonical_ir"]["rules"][0]["actor"]
    assert row["source_text"].count(actor) == 3
    span = row["facet_spans"]["actor"]
    assert span[0] != row["source_text"].index(actor)
    assert row["source_text"][slice(*span)] == actor


def test_exposure_skeleton_does_not_depend_on_trigger_labels_or_names():
    old = corpus.convert_earlier(earlier_fixture())
    new = corpus.convert_new(corpus.prior.render_row("train", "suffix_qualifiers", 7, "P"))
    assert corpus.skeleton(old) == corpus.skeleton(new)
    fresh = corpus.render_challenge("suffix_rule", 7, "P")
    assert "<actor>" in corpus.skeleton(fresh)
    assert "heatherby" not in corpus.skeleton(fresh)
    assert "is permitted to" in corpus.skeleton(fresh)


def miniature_freeze(tmp_path, monkeypatch):
    old = earlier_fixture()
    old_tune = copy.deepcopy(old)
    old_tune["id"] = "earlier-tune"
    # Change one character while preserving all role lengths and coordinates.
    old_tune["source_text"] = old_tune["source_text"].replace("K", "Q")
    rule = old_tune["canonical_ir"]["rules"][0]
    for field in corpus.FIELDS:
        if isinstance(rule[field], str):
            rule[field] = rule[field].replace("K", "Q")
        else:
            rule[field] = [v.replace("K", "Q") for v in rule[field]]
    old_tune["source_sha256"] = corpus.sha(old_tune["source_text"].encode())
    old_tune["canonical_target_sha256"] = corpus.sha(corpus.canonical_bytes(old_tune["canonical_ir"]))
    earlier_path = tmp_path / "earlier.json"
    earlier_path.write_bytes(corpus.canonical_bytes({"splits": {"train": [old], "tuning": [old_tune]}}))
    train = [corpus.prior.render_row("train", "suffix_qualifiers", 0, "O")]
    tune = [corpus.prior.render_row("tuning", "temporal_prefix", 0, "O")]
    exposed = [corpus.prior.render_row("challenge", "actor_condition_insertion", 0, "O")]
    new_manifest = {"schema": "test-only", "semantics": {"trigger_meanings": corpus.prior.TRIGGER_MEANINGS},
        "artifacts": {"train": corpus.write_new(tmp_path / "new-train.json", train),
        "challenge_targets": corpus.write_new(tmp_path / "previously-exposed.json", exposed)}}
    new_path = tmp_path / "new-manifest.json"
    new_path.write_bytes(corpus.canonical_bytes(new_manifest))
    monkeypatch.setattr(corpus.prior, "load_training_inputs", lambda _: (new_manifest, train, tune,
        [{"id": r["id"], "source_text": r["source_text"]} for r in exposed]))
    monkeypatch.setattr(corpus, "EXPECTED", {"train_earlier": 1, "train_new": 1, "tuning_earlier": 1, "tuning_new": 1, "challenge": 144})
    return corpus.freeze(tmp_path / "frozen", earlier_path, new_path)


def test_loader_never_reads_sealed_targets_or_exposure_audit(tmp_path, monkeypatch):
    reference = miniature_freeze(tmp_path, monkeypatch)
    manifest = corpus.read_ref(reference)
    for name in ("challenge_targets", "exposure_audit"):
        Path(manifest["artifacts"][name]["path"]).unlink()
    loaded, train, earlier, new, sources = corpus.load_training_inputs(reference["path"])
    assert loaded == manifest
    assert (len(train), len(earlier), len(new), len(sources)) == (2, 1, 1, 144)
    assert all(set(r) == {"id", "source_text"} for r in sources)


def test_frozen_data_tamper_is_rejected(tmp_path, monkeypatch):
    reference = miniature_freeze(tmp_path, monkeypatch)
    manifest = corpus.read_ref(reference)
    path = Path(manifest["artifacts"]["train"]["path"])
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="artifact hash"):
        corpus.load_training_inputs(reference["path"])


def test_training_exact_pool_cardinalities_are_enforced():
    with pytest.raises(ValueError, match="training domain counts"):
        corpus.verify_pools([], [], [], [])


def test_frozen_directory_cannot_be_overwritten(tmp_path, monkeypatch):
    reference = miniature_freeze(tmp_path, monkeypatch)
    with pytest.raises(FileExistsError):
        corpus.freeze(Path(reference["path"]).parent)
