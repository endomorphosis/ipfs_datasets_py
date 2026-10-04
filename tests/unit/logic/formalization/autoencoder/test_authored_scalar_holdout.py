"""Pure authored holdout controls; fixtures establish no semantic admission."""
from collections import Counter
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import random

import pytest

_PATH = Path(__file__).resolve().parents[5] / "ipfs_datasets_py/logic/formalization/autoencoder/authored_scalar_holdout.py"
_SPEC = importlib.util.spec_from_file_location("_authored_scalar_holdout_tests", _PATH)
subject = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(subject)


def validator(value):
    return {"valid": type(value) is dict and set(value) == {"rules"} and len(value["rules"]) == 1}


def inputs():
    clauses = []
    for i, actor in enumerate(subject.ACTORS):
        for j, action in enumerate(subject.ACTIONS):
            if j in (i, (i + 1) % 5):
                continue
            for object_ in subject.OBJECTS:
                for modality, word in zip(subject.MODALITIES, ("must", "may", "must not")):
                    rule = dict(actor=actor, action=action, object=object_, modality=modality,
                                conditions=[], exceptions=[], temporal=[])
                    clauses.append(dict(id="prior:" + str(len(clauses)),
                        source_text=f"The {actor} {word} {action} the {object_}.", target={"rules": [rule]}))
    training = [dict(id="train:" + str(i), source_text="\n\n".join(r["source_text"] for r in clauses[i:i+4]),
                    target={"rules": [r["target"]["rules"][0] for r in clauses[i:i+4]]})
                for i in range(0, len(clauses), 4)]
    prior = dict(train=[{k:r[k] for k in ("id", "source_text")} for r in clauses],
        validation=[dict(id="olddev", source_text="The registrar must approve the notice.")],
        test=[dict(id="oldtest", source_text="The registrar is allowed to approve the notice.")],
        canary=[dict(id="oldcanary", source_text="By policy, the registrar may approve the notice.")])
    return dict(training_rows=training, prior_sources_by_split=prior,
        codec=dict(schema="typed-json-lexical/v1", target_vocabulary=list(subject.VOCABULARY)),
        sealed_comparison_sha256="a" * 64, validate_rule=validator)


def test_balanced_complete_inventory_and_separate_source_only_rows():
    args = inputs(); before = deepcopy(args); result = subject.build_holdout(**args)
    assert args == before
    rows, refs, receipt = (result[k] for k in ("source_rows", "references", "receipt"))
    assert len(rows) == len(refs) == 48
    assert all(set(row) == {"id", "source_text"} for row in rows)
    assert Counter(r["clause_count"] for r in refs) == {1:12, 2:12, 4:12, 8:12}
    assert Counter(r["template_family"] for r in refs) == dict.fromkeys(subject.FAMILIES, 16)
    clauses = [part for row in rows for part in row["source_text"].split("\n\n")]
    assert len(clauses) == len(set(clauses)) == 180
    assert len(set(clauses + [r["source_text"] for r in rows])) == 216
    pairs = {(r["actor"], r["action"]) for row in args["training_rows"] for r in row["target"]["rules"]}
    for family in subject.FAMILIES:
        selected = [r for r in refs if r["template_family"] == family]
        rules = [r for row in selected for r in row["target"]["rules"]]
        assert Counter((r["actor"], r["action"]) in pairs for r in rules) == {True:30, False:30}
        assert Counter(r["actor"] for r in rules) == dict.fromkeys(subject.ACTORS, 12)
        assert Counter(r["action"] for r in rules) == dict.fromkeys(subject.ACTIONS, 12)
        assert Counter(r["modality"] for r in rules) == dict.fromkeys(subject.MODALITIES, 20)
        assert Counter(r["object"] for r in rules) == dict.fromkeys(subject.OBJECTS, 30)
    assert receipt["source_rows_sha256"] == subject.digest(rows)
    assert receipt["references_sha256"] == subject.digest(refs)
    assert receipt["receipt_sha256"] == subject.digest({k:v for k,v in receipt.items() if k != "receipt_sha256"})
    assert all(receipt[k] is False for k in subject.FALSE)
    assert receipt["comparison_seal_verified"] is False


def test_full_32_vocabulary_roundtrip_and_positioned_reference_alignment():
    result = subject.build_holdout(**inputs())
    for row, ref in zip(result["source_rows"], result["references"]):
        assert row["id"] == ref["id"] and row["source_text"] == ref["source_text"]
        ids = ref["target_ids"]
        assert ids[0] == 1 and ids[-1] == 2 and all(3 <= t < 32 for t in ids[1:-1])
        assert len(ids) <= 512
        assert json.loads("".join(subject.VOCABULARY[i] for i in ids[1:-1])) == ref["target"]
        slots = set()
        for component, rule in zip(ref["components"], ref["target"]["rules"]):
            text = row["source_text"][component["char_start"]:component["char_end"]]
            assert row["source_text"].encode()[component["byte_start"]:component["byte_end"]] == text.encode()
            assert subject.text_sha(text) == component["source_sha256"]
            expected = subject._sentence(ref["template_family"], rule["actor"], rule["action"], rule["object"], rule["modality"])
            assert text == expected
            slot = tuple(rule[k] for k in ("actor", "action", "object"))
            assert slot not in slots
            slots.add(slot)


@pytest.mark.parametrize("seed", [0, 1, 17, 1729, 2718, 20261004, 2**31-1])
def test_fixed_algorithm_terminates_without_reusing_clauses_for_valid_seeds(seed):
    args = inputs(); args["seed"] = seed
    first = subject.build_holdout(**args)
    assert first == subject.build_holdout(**args)
    assert len({p for r in first["source_rows"] for p in r["source_text"].split("\n\n")}) == 180


@pytest.mark.parametrize("split", subject.PRIOR_SPLITS)
@pytest.mark.parametrize("scope", ["clause", "paragraph"])
def test_all_prior_splits_exclude_normalized_new_literals_and_paragraphs(split, scope):
    args = inputs(); produced = subject.build_holdout(**args)
    row = next(r for r in produced["references"] if r["clause_count"] == 8)
    text = row["source_text"] if scope == "paragraph" else row["source_text"].split("\n\n")[0]
    # Case and whitespace changes must not evade the exclusion.
    args["prior_sources_by_split"][split].append(dict(id="collision", source_text="  "+" \t ".join(text.upper().split())+"  "))
    with pytest.raises(ValueError, match="overlaps prior blacklist|unreviewed syntactic template"):
        subject.build_holdout(**args)


@pytest.mark.parametrize("old", ["The notice must be approved by the registrar.",
    "For the registrar, approving the notice is obligatory.",
    "The registrar has a duty to approve the notice.", "An unknown prior template."])
def test_unknown_old_syntax_prevents_unfounded_template_novelty_claim(old):
    args = inputs(); args["prior_sources_by_split"]["canary"][0]["source_text"] = old
    with pytest.raises(ValueError, match="cannot establish new-family separation"):
        subject.build_holdout(**args)


@pytest.mark.parametrize("split", subject.PRIOR_SPLITS)
def test_missing_blacklist_split_rejected(split):
    args = inputs(); del args["prior_sources_by_split"][split]
    with pytest.raises(ValueError, match="all four"):
        subject.build_holdout(**args)


@pytest.mark.parametrize("key", ["target", "embedding", "target_ids", "clause_count", "predictions"])
def test_blacklist_cannot_expose_development_labels_or_model_outputs(key):
    args = inputs(); args["prior_sources_by_split"]["validation"][0][key] = "poisoned"
    with pytest.raises(ValueError, match="closed"):
        subject.build_holdout(**args)


@pytest.mark.parametrize("key,value", [("actor", "agency"), ("action", "retain"),
    ("object", "file"), ("modality", "R"), ("temporal", ["tomorrow"]),
    ("exceptions", ["emergency"]), ("conditions", ["requested"])])
def test_unsupported_training_fields_are_rejected_without_repair(key, value):
    args = inputs(); args["training_rows"][0]["target"]["rules"][0][key] = value
    before = deepcopy(args)
    with pytest.raises(ValueError, match="outside fixed scalar coverage"):
        subject.build_holdout(**args)
    assert args == before


@pytest.mark.parametrize("change", ["reordered", "extended", "missing", "foreign_schema", "extra_key"])
def test_exact_original_codec_is_required(change):
    args = inputs(); codec = args["codec"]
    if change == "reordered":codec["target_vocabulary"][3:5] = reversed(codec["target_vocabulary"][3:5])
    elif change == "extended":codec["target_vocabulary"].append('"other"')
    elif change == "missing":codec["target_vocabulary"].pop()
    elif change == "foreign_schema":codec["schema"] = "new"
    else:codec["admitted"] = True
    with pytest.raises(ValueError, match="exact unchanged 32"):
        subject.build_holdout(**args)


@pytest.mark.parametrize("seed", [True, False, -1, 2**31, 1.0, None])
def test_invalid_seed_cannot_change_split_recipe(seed):
    args = inputs(); args["seed"] = seed
    with pytest.raises(ValueError, match="seed"):
        subject.build_holdout(**args)


@pytest.mark.parametrize("seal", [None, True, "", "0" * 63, "z" * 64])
def test_explicit_seal_identity_required(seal):
    args = inputs(); args["sealed_comparison_sha256"] = seal
    with pytest.raises(ValueError, match="sealed comparison"):
        subject.build_holdout(**args)


def test_unbalanced_training_pairs_fail_instead_of_choosing_an_easier_cohort():
    args = inputs()
    omitted = (subject.ACTORS[0], subject.ACTIONS[2])
    rows = []
    for row in args["training_rows"]:
        parts = [(s,r) for s,r in zip(row["source_text"].split("\n\n"),row["target"]["rules"])
                 if (r["actor"],r["action"]) != omitted]
        if parts:rows.append(dict(id=row["id"],source_text="\n\n".join(s for s,r in parts),target={"rules":[r for s,r in parts]}))
    args["training_rows"] = rows
    with pytest.raises(ValueError, match="balanced degree three"):
        subject.build_holdout(**args)


def test_conflicting_literal_training_labels_fail_closed():
    args = inputs(); original = args["training_rows"][0]
    duplicate = dict(id="conflict",source_text=original["source_text"].split("\n\n")[0],
        target={"rules":[deepcopy(original["target"]["rules"][0])]})
    duplicate["target"]["rules"][0]["modality"] = "F"
    args["training_rows"].append(duplicate)
    with pytest.raises(ValueError, match="conflicting"):
        subject.build_holdout(**args)


@pytest.mark.parametrize("behavior", ["reject", "mutate", "canonical_change"])
def test_native_validator_result_cannot_drop_or_rewrite_target(behavior):
    args = inputs()
    def bad(value):
        if behavior == "mutate":value["rules"][0]["modality"] = "P"
        return {"valid": behavior != "reject", **({"canonical_ir": {"rules": []}} if behavior == "canonical_change" else {})}
    args["validate_rule"] = bad
    with pytest.raises(ValueError, match="validator|validation"):
        subject.build_holdout(**args)


def test_no_hidden_file_network_rng_or_model_access(monkeypatch):
    args = inputs(); before = random.getstate()
    monkeypatch.setattr("builtins.open", lambda *a,**k:pytest.fail("hidden file access"))
    monkeypatch.setattr("builtins.__import__", lambda *a,**k:pytest.fail("hidden import or model access"))
    result = subject.build_holdout(**args)
    assert random.getstate() == before
    assert result["receipt"]["comparison_seal_verified"] is False
    assert not result["receipt"]["encoder_token_limit_checked"]
