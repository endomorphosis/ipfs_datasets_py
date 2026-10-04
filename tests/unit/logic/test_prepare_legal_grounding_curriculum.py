"""Acceptance checks for authored, coordinate-bound grounding split contracts."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/ops/legal_ir/prepare_legal_grounding_curriculum.py"
SPEC = importlib.util.spec_from_file_location("grounding_curriculum", SCRIPT)
corpus = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(corpus)


@pytest.fixture(scope="module")
def panels():
    return corpus.make_panels()


def make_frozen(tmp_path):
    historical = tmp_path / "historical.json"
    historical.write_text(json.dumps({"rows": [{"source_text": "Old example with a distinct source."}]}))
    ref = corpus.freeze(tmp_path / "frozen", [historical])
    return Path(ref["path"])


def test_counts_modal_balance_and_construction_holdouts(panels):
    rows, membership = panels
    assert {k: len(v) for k, v in rows.items()} == {"train": 600, "tuning": 96, "challenge": 150}
    corpus.check_panels(rows, membership)
    construction_sets = [set(corpus.CONSTRUCTIONS[s]) for s in corpus.SPLITS]
    assert all(not a & b for i, a in enumerate(construction_sets) for b in construction_sets[i + 1:])
    assert len(set(corpus.CONSTRUCTION_DESCRIPTIONS.values())) == 14


def test_exact_source_coordinates_and_closed_row_contract(panels):
    for rows in panels[0].values():
        for row in rows:
            assert set(row) == corpus.ROW_KEYS
            corpus.validate_row(row)
            rule = row["canonical_ir"]["rules"][0]
            for field, span in row["facet_spans"].items():
                if span is not None:
                    expected = rule[field] if field in corpus.FIELDS[:3] else rule[field][0]
                    assert row["source_text"][slice(*span)] == expected


def test_repeated_actor_surface_uses_occurrence_coordinates():
    row = corpus.render_row("train", "condition_prefix", 0, "P")
    actor = row["canonical_ir"]["rules"][0]["actor"]
    assert row["source_text"].count(actor) >= 2
    assert row["facet_spans"]["actor"][0] > row["source_text"].index(actor)
    corpus.validate_row(row)


def test_embedded_modal_words_and_actor_lengths(panels):
    rules = [row["canonical_ir"]["rules"][0] for row in panels[0]["train"]]
    assert {len(r["actor"].split()) for r in rules} == set(range(1, 9))
    for word in ("May", "Must", "Permission", "Required"):
        assert any(word in r["actor"].split() for r in rules)


def test_all_modal_meanings_present_in_training(panels):
    triggers = {r["source_text"][slice(*r["trigger_span"])] for r in panels[0]["train"]}
    assert triggers == set(corpus.TRIGGER_MEANINGS)
    assert "may not" not in triggers


def test_minimal_modal_contrasts_share_other_target_facets():
    rows = [corpus.render_row("challenge", "actor_condition_insertion", 7, m) for m in ("O", "P", "F")]
    facets = [{k: v for k, v in r["canonical_ir"]["rules"][0].items() if k != "modality"} for r in rows]
    assert facets[0] == facets[1] == facets[2]
    stripped_sources = [r["source_text"][:r["trigger_span"][0]] + "<MODAL>" + r["source_text"][r["trigger_span"][1]:] for r in rows]
    assert len(set(stripped_sources)) == 1


@pytest.mark.parametrize("mutation", ["actor_start", "trigger_modality", "trigger_overlap", "null_required", "extra_key", "non_token", "bool_coordinate", "absent_optional"])
def test_coordinate_and_contract_corruption_rejected(mutation):
    row = corpus.render_row("train", "suffix_qualifiers", 7, "P")
    if mutation == "actor_start":
        row["facet_spans"]["actor"][0] += 1
    elif mutation == "trigger_modality":
        row["canonical_ir"]["rules"][0]["modality"] = "O"
    elif mutation == "trigger_overlap":
        row["facet_spans"]["actor"] = row["trigger_span"].copy()
    elif mutation == "null_required":
        row["facet_spans"]["actor"] = None
    elif mutation == "extra_key":
        row["source_spans"] = {}
    elif mutation == "non_token":
        row["trigger_span"][1] -= 1
    elif mutation == "bool_coordinate":
        row["facet_spans"]["actor"][0] = False
    else:
        row["facet_spans"]["conditions"] = None
    with pytest.raises(ValueError):
        corpus.validate_row(row)


def test_duplicate_or_cross_split_source_rejected(panels):
    rows, membership = copy.deepcopy(panels)
    rows["tuning"][0] = copy.deepcopy(rows["train"][0])
    with pytest.raises(ValueError):
        corpus.check_panels(rows, membership)


def test_wrong_construction_membership_rejected(panels):
    rows, membership = copy.deepcopy(panels)
    membership["challenge"][rows["challenge"][0]["id"]] = "suffix_qualifiers"
    with pytest.raises(ValueError, match="construction crosses"):
        corpus.check_panels(rows, membership)


def test_generator_is_deterministic(panels):
    assert corpus.make_panels() == panels


def test_loader_never_opens_sealed_annotations(tmp_path, monkeypatch):
    manifest_path = make_frozen(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    sealed = {Path(manifest["artifacts"][k]["path"]) for k in ("challenge_targets", "construction_membership")}
    original = Path.read_bytes

    def guarded(path):
        if path in sealed:
            raise AssertionError("training reader tried to open sealed annotations")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", guarded)
    loaded, train, tune, challenge = corpus.load_training_inputs(manifest_path)
    assert loaded == manifest
    assert (len(train), len(tune), len(challenge)) == (600, 96, 150)
    assert all(set(r) == {"id", "source_text"} for r in challenge)


def test_loader_works_when_sealed_targets_are_unavailable(tmp_path):
    manifest_path = make_frozen(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    for key in ("challenge_targets", "construction_membership"):
        Path(manifest["artifacts"][key]["path"]).unlink()
    assert len(corpus.load_training_inputs(manifest_path)[3]) == 150


def test_artifact_tamper_rejected(tmp_path):
    manifest_path = make_frozen(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    path = Path(manifest["artifacts"]["train"]["path"])
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="artifact hash or size"):
        corpus.load_training_inputs(manifest_path)


def test_historical_overlap_is_rejected(tmp_path):
    row = corpus.render_row("train", "suffix_qualifiers", 0, "O")
    historical = tmp_path / "history.json"
    historical.write_text(json.dumps([{"source_text": row["source_text"]}]))
    with pytest.raises(ValueError, match="overlaps historical"):
        corpus.freeze(tmp_path / "frozen", [historical])


def test_normalized_historical_overlap_is_rejected(tmp_path):
    row = corpus.render_row("train", "suffix_qualifiers", 0, "O")
    historical = tmp_path / "history.json"
    historical.write_text(json.dumps([{"source_text": row["source_text"].upper().replace(" ", "   ")}]))
    with pytest.raises(ValueError, match="overlaps historical"):
        corpus.freeze(tmp_path / "frozen", [historical])


def test_freeze_cannot_overwrite_existing_artifacts(tmp_path):
    manifest_path = make_frozen(tmp_path)
    with pytest.raises(FileExistsError):
        corpus.freeze(manifest_path.parent, [tmp_path / "historical.json"])


def test_historical_audit_cannot_be_vacuous(tmp_path):
    historical = tmp_path / "empty.json"
    historical.write_text("{}")
    with pytest.raises(ValueError, match="no source_text"):
        corpus.freeze(tmp_path / "frozen", [historical])
