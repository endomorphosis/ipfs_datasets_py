"""Synthetic fixtures only: no campaign cohort, encoder or model execution."""
from collections import Counter, defaultdict
from copy import deepcopy
import json
import random

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import authored_modality_holdout_v2 as subject
from ipfs_datasets_py.logic.formalization.autoencoder import fresh_scalar_source_inputs as source_inputs
from .test_authored_scalar_holdout import inputs as old_inputs


def inputs():
    result = old_inputs()
    prior = result.pop("prior_sources_by_split")
    prior["exposed_r6"] = [dict(id="exposed-passive", source_text="The notice must be approved by the registrar."),
        dict(id="exposed-gerund", source_text="For the registrar, approving the notice is obligatory."),
        dict(id="exposed-nominal", source_text="The registrar has a duty to approve the notice.")]
    result.update(prior_sources_by_dataset=prior,
        family_roles=dict(training=["active_v2_modal", "active_v2_adjective"],
            exposed=list(subject.base.FAMILIES), evaluation=list(subject.FAMILIES)))
    return result


def test_complete_balanced_counterfactual_inventory_and_input_immutability():
    args = inputs(); before = deepcopy(args)
    result = subject.build_holdout(**args)
    assert args == before
    rows, refs, receipt = (result[k] for k in ("source_rows", "references", "receipt"))
    assert len(rows) == len(refs) == 48
    assert all(set(r) == {"id", "source_text"} for r in rows)
    assert Counter(r["clause_count"] for r in refs) == {1:12, 2:12, 4:12, 8:12}
    assert Counter(r["template_family"] for r in refs) == dict.fromkeys(subject.FAMILIES, 16)
    clauses = [p for row in rows for p in row["source_text"].split("\n\n")]
    assert len(clauses) == len(set(clauses)) == 180
    assert len(set(clauses + [r["source_text"] for r in rows])) == 216
    groups = defaultdict(list)
    for ref in refs:
        for component, rule in zip(ref["components"], ref["target"]["rules"]):
            groups[component["counterfactual_group_id"]].append(rule)
    assert len(groups) == 60
    for rules in groups.values():
        assert Counter(r["modality"] for r in rules) == dict.fromkeys(subject.MODALITIES, 1)
        assert len({(r["actor"], r["action"], r["object"]) for r in rules}) == 1
    for family in subject.FAMILIES:
        selected = [r for r in refs if r["template_family"] == family]
        rules = [r for row in selected for r in row["target"]["rules"]]
        assert Counter(c["training_pair_seen"] for row in selected for c in row["components"]) == {True:30, False:30}
        assert Counter(r["actor"] for r in rules) == dict.fromkeys(subject.ACTORS, 12)
        assert Counter(r["action"] for r in rules) == dict.fromkeys(subject.ACTIONS, 12)
        assert Counter(r["object"] for r in rules) == dict.fromkeys(subject.OBJECTS, 30)
        assert Counter(r["modality"] for r in rules) == dict.fromkeys(subject.MODALITIES, 20)
    assert receipt["source_rows_sha256"] == subject.digest(rows)
    assert receipt["references_sha256"] == subject.digest(refs)
    assert receipt["receipt_sha256"] == subject.digest({k:v for k,v in receipt.items() if k != "receipt_sha256"})
    assert receipt["family_roles"] == args["family_roles"]
    assert receipt["prior_sources_by_dataset_sha256"] == subject.digest(args["prior_sources_by_dataset"])
    assert all(receipt[k] is False for k in subject.FALSE)
    assert receipt["comparison_seal_verified"] is False
    assert receipt["prior_inventory_completeness_verified"] is False
    assert receipt["family_assignment_inferred_from_text"] is False


def test_full_vocabulary_complete_roundtrip_and_positioned_references():
    result = subject.build_holdout(**inputs())
    for row, ref in zip(result["source_rows"], result["references"]):
        ids = ref["target_ids"]
        assert row["id"] == ref["id"] and row["source_text"] == ref["source_text"]
        assert ids[0] == 1 and ids[-1] == 2 and len(ids) <= 512
        assert all(3 <= token < 32 for token in ids[1:-1])
        assert json.loads("".join(subject.VOCABULARY[token] for token in ids[1:-1])) == ref["target"]
        slots = set()
        for component, rule in zip(ref["components"], ref["target"]["rules"]):
            text = row["source_text"][component["char_start"]:component["char_end"]]
            assert row["source_text"].encode()[component["byte_start"]:component["byte_end"]] == text.encode()
            assert subject.text_sha(text) == component["source_sha256"]
            assert text == subject._sentence(ref["template_family"], rule["actor"], rule["action"], rule["object"], rule["modality"])
            key = (rule["actor"], rule["action"], rule["object"])
            assert key not in slots
            slots.add(key)


def test_existing_source_only_plan_accepts_fixture_without_encoder_execution():
    result = subject.build_holdout(**inputs())
    plan = source_inputs.source_plan(result["source_rows"],
        expected_source_rows_sha256=result["receipt"]["source_rows_sha256"], sealed_comparison_sha256="a"*64)
    assert plan["paragraph_count"] == 48 and plan["unique_sources"] == 216
    assert plan["clause_occurrences"] == 180
    assert all(set(row) == {"id", "source_text"} for row in plan["source_inputs"])
    assert plan["target_access"] is False and plan["training_executed"] is False


@pytest.mark.parametrize("seed", [0, 1, 1729, 2718, 20261005, 2**31-1])
def test_bounded_deterministic_matching_without_clauses_reused(seed):
    args = inputs(); args["seed"] = seed
    first = subject.build_holdout(**args)
    assert first == subject.build_holdout(**args)
    assert len({p for r in first["source_rows"] for p in r["source_text"].split("\n\n")}) == 180


@pytest.mark.parametrize("text", ["Unknown prior syntax with a café.",
    "前提を限定した以前の文章。", "An old heading.\n\nA second arbitrary clause.",
    "The notice must be approved by the registrar."])
def test_generic_blacklist_accepts_unrelated_syntax_without_parser(text):
    args = inputs(); args["prior_sources_by_dataset"]["miscellaneous"] = [dict(id="misc", source_text=text)]
    result = subject.build_holdout(**args)
    assert result["receipt"]["prior_dataset_inventory"]["miscellaneous"]["rows"] == 1


@pytest.mark.parametrize("dataset", ["train", "validation", "test", "canary", "exposed_r6", "new_training_paraphrases"])
@pytest.mark.parametrize("scope", ["literal_clause", "normalized_clause", "normalized_paragraph"])
def test_every_named_inventory_excludes_overlapping_sources(dataset, scope):
    args = inputs(); produced = subject.build_holdout(**args)
    ref = next(r for r in produced["references"] if r["clause_count"] == 8)
    text = ref["source_text"] if scope == "normalized_paragraph" else ref["source_text"].split("\n\n")[0]
    if scope != "literal_clause":text = "  " + " \t ".join(text.upper().split()) + "  "
    args["prior_sources_by_dataset"].setdefault(dataset, []).append(dict(id="collision", source_text=text))
    with pytest.raises(ValueError, match="overlaps prior blacklist"):
        subject.build_holdout(**args)


@pytest.mark.parametrize("role", ["training", "exposed"])
def test_evaluation_family_may_not_be_relabelled_or_shared(role):
    args = inputs(); args["family_roles"][role].append(subject.FAMILIES[0])
    with pytest.raises(ValueError, match="roles overlap"):
        subject.build_holdout(**args)


@pytest.mark.parametrize("change", ["missing_role", "extra_role", "empty", "duplicate", "foreign", "nonlist", "unsafe_name", "repeated_across_prior_roles"])
def test_closed_explicit_family_partition(change):
    args = inputs(); roles = args["family_roles"]
    if change == "missing_role":del roles["exposed"]
    elif change == "extra_role":roles["unknown"] = []
    elif change == "empty":roles["training"] = []
    elif change == "duplicate":roles["evaluation"].append(roles["evaluation"][0])
    elif change == "foreign":roles["evaluation"][0] = "another-family"
    elif change == "nonlist":roles["training"] = "active"
    elif change == "unsafe_name":roles["training"][0] = "../family"
    else:roles["exposed"].append(roles["training"][0])
    with pytest.raises(ValueError, match="family|families"):
        subject.build_holdout(**args)


@pytest.mark.parametrize("value", [None, [], {}, {"../bad": []}, {"missing": []}, {"bad": "rows"}])
def test_invalid_prior_inventory_container_rejected(value):
    args = inputs(); args["prior_sources_by_dataset"] = value
    with pytest.raises(ValueError, match="inventor"):
        subject.build_holdout(**args)


@pytest.mark.parametrize("key", ["target", "embedding", "target_ids", "predictions", "template_family", "clause_count"])
def test_prior_rows_never_accept_targets_or_model_annotations(key):
    args = inputs(); args["prior_sources_by_dataset"]["exposed_r6"][0][key] = "poison"
    with pytest.raises(ValueError, match="closed"):
        subject.build_holdout(**args)


def test_prior_identity_conflicts_fail_but_same_literal_across_inventories_is_allowed():
    args = inputs(); row = deepcopy(args["prior_sources_by_dataset"]["train"][0])
    args["prior_sources_by_dataset"]["repeat"] = [row]
    subject.build_holdout(**args)
    row["source_text"] += " Changed."
    with pytest.raises(ValueError, match="conflicting literal"):
        subject.build_holdout(**args)


def test_duplicate_prior_identity_within_inventory_rejected():
    args = inputs(); prior = args["prior_sources_by_dataset"]["test"]
    prior.append(deepcopy(prior[0]))
    with pytest.raises(ValueError, match="duplicate source identity"):
        subject.build_holdout(**args)


def test_all_training_clauses_must_be_in_supplied_inventories():
    args = inputs(); args["prior_sources_by_dataset"]["train"].pop(0)
    with pytest.raises(ValueError, match="training clause absent"):
        subject.build_holdout(**args)


def test_conflicting_training_labels_are_not_repaired():
    args = inputs(); original = args["training_rows"][0]
    row = dict(id="conflict", source_text=original["source_text"].split("\n\n")[0],
        target={"rules": [deepcopy(original["target"]["rules"][0])]})
    row["target"]["rules"][0]["modality"] = "F"
    args["training_rows"].append(row)
    with pytest.raises(ValueError, match="conflicting reference"):
        subject.build_holdout(**args)


@pytest.mark.parametrize("key,value", [("actor", "agency"), ("modality", "R"),
    ("temporal", ["tomorrow"]), ("exceptions", ["emergency"]), ("conditions", ["requested"])])
def test_no_unsupported_facet_repair(key, value):
    args = inputs(); args["training_rows"][0]["target"]["rules"][0][key] = value
    before = deepcopy(args)
    with pytest.raises(ValueError, match="outside fixed scalar coverage"):
        subject.build_holdout(**args)
    assert args == before


@pytest.mark.parametrize("seed", [True, False, -1, 2**31, 1.0, None])
def test_invalid_seed_rejected(seed):
    args = inputs(); args["seed"] = seed
    with pytest.raises(ValueError, match="seed"):
        subject.build_holdout(**args)


@pytest.mark.parametrize("seal", [None, True, "", "x"*64, "a"*63])
def test_explicit_sealed_recipe_hash_required(seal):
    args = inputs(); args["sealed_comparison_sha256"] = seal
    with pytest.raises(ValueError, match="sealed comparison"):
        subject.build_holdout(**args)


@pytest.mark.parametrize("behavior", ["reject", "mutate", "canonical_change"])
def test_validator_cannot_rewrite_or_omit_authored_rule(behavior):
    args = inputs()
    def bad(value):
        if behavior == "mutate":value["rules"][0]["modality"] = "P"
        return {"valid": behavior != "reject", **({"canonical_ir": {"rules": []}} if behavior == "canonical_change" else {})}
    args["validate_rule"] = bad
    with pytest.raises(ValueError, match="validator|validation"):
        subject.build_holdout(**args)


def test_exact_codec_and_balanced_training_graph_required():
    args = inputs(); args["codec"]["target_vocabulary"].append('"new"')
    with pytest.raises(ValueError, match="exact unchanged"):
        subject.build_holdout(**args)
    args = inputs()
    for row in args["training_rows"]:
        for rule in row["target"]["rules"]:
            rule["action"] = subject.ACTIONS[0]
    with pytest.raises(ValueError, match="balanced degree three"):
        subject.build_holdout(**args)


def test_prior_byte_bound_limits_arbitrary_source_processing():
    args = inputs()
    args["prior_sources_by_dataset"]["large"] = [dict(id="large:"+str(i), source_text="x"*32768)
        for i in range(513)]
    with pytest.raises(ValueError, match="total byte bound"):
        subject.build_holdout(**args)


def test_no_hidden_io_import_rng_model_or_parser_access(monkeypatch):
    args = inputs(); state = random.getstate()
    def forbidden(*args, **kwargs):
        raise RuntimeError("hidden file or dynamic import access")
    with monkeypatch.context() as patch:
        patch.setattr("builtins.open", forbidden)
        patch.setattr("builtins.__import__", forbidden)
        result = subject.build_holdout(**args)
    assert random.getstate() == state
    assert not result["receipt"]["comparison_seal_verified"]
    assert not result["receipt"]["encoder_token_limit_checked"]
