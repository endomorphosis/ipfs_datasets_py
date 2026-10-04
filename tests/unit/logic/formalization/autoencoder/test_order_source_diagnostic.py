"""Synthetic source-order preparation/scoring, never model-fidelity evidence."""
from copy import deepcopy
import json
import math

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import order_source_diagnostic as subject


@pytest.fixture
def corpus():
    rules = [dict(actor="actor" + str(i), action="action" + str(i), modality="O",
        object="object", conditions=[], exceptions=[], temporal=[]) for i in range(8)]
    tokens = sorted(set(subject.TOKEN.findall(subject.raw({"rules": rules}).decode())))
    codec = dict(schema="typed-json-lexical/v1", target_vocabulary=["<pad>", "<bos>", "<eos>"] + tokens)
    paragraphs = dict(schema="authored-legal-paragraph-curriculum/v1", codec=codec,
        codec_sha256=subject.digest(codec), original_split_inventory={}, train=[], validation=[])
    bindings = []
    for split in ("train", "validation"):
        inventory = []; components = {}
        for sample in range(12):
            for slot, rule in enumerate(rules):
                text = f"{split} café {sample}: {rule['actor']} shall {rule['action']} the object."
                identity = dict(id=f"{split}:{sample}:{slot}", group_id=f"{split}:group:{sample}:{slot}",
                    source_sha256=subject.text_digest(text),
                    normalized_source_sha256=subject.text_digest(" ".join(text.casefold().split())),
                    target_sha256=subject.digest({"rules": [rule]}))
                inventory.append(identity); components[sample, slot] = (text, identity)
        paragraphs["original_split_inventory"][split] = inventory
        for count in subject.COUNTS:
            for sample in range(12):
                chosen = [components[sample, slot] for slot in range(count)]
                text = "\n\n".join(item[0] for item in chosen)
                target = {"rules": deepcopy(rules[:count])}; offsets = []; source_parts = []
                cs = bs = 0
                for position, (clause, identity) in enumerate(chosen):
                    part = dict(identity, position=position, split=split, char_start=cs, char_end=cs+len(clause),
                        byte_start=bs, byte_end=bs+len(clause.encode()),
                        logical_slot=[rules[position][field] for field in ("actor", "action", "object")],
                        original_metadata={key: identity[key] for key in ("id", "group_id", "source_sha256")})
                    part["original_metadata"]["split"] = split
                    offsets.append(part)
                    source_parts.append(dict(id=identity["id"], group_id=identity["group_id"], split=split,
                        source_sha256=identity["source_sha256"], target_sha256=identity["target_sha256"],
                        source_text=clause, start_char=cs, end_char=cs+len(clause)))
                    cs, bs = part["char_end"]+2, part["byte_end"]+2
                groups = sorted(item[1]["group_id"] for item in chosen)
                row = dict(id=f"{split}:paragraph:{count}:{sample}", split=split, clause_count=count,
                    group_id="authored-component-groups:" + subject.digest(groups), component_group_ids=groups,
                    source_text=text, source_sha256=subject.text_digest(text), source_char_count=len(text),
                    source_byte_count=len(text.encode()), target=target, target_sha256=subject.digest(target),
                    target_ids=subject._encode(target, codec), target_component_ids=[part["id"] for part in offsets],
                    codec_sha256=subject.digest(codec), components=offsets, **subject.FALSE)
                paragraphs[split].append(row)
                bindings.append({**{key: deepcopy(row[key]) for key in ("id", "source_text", "source_sha256", "group_id",
                    "target_component_ids", "target_ids", "codec_sha256", "split")}, "components": source_parts,
                    "source_tokens": dict(source_sha256=row["source_sha256"], encoder_context_tokens=512,
                        truncated=False, padded=False, token_count=10*count, forward_token_count=10*count,
                        tokenizer_profile_id="gte-small:17e1f347d17fe144873b1201da91788898c639cd",
                        tokenizer_sha256="da0e79933b9ed51798a3ae27893d3c5fa4a201126cef75586296df9b4d2c62a0")})
    return paragraphs, bindings, codec


def prepare(corpus):
    paragraphs, bindings, codec = corpus
    return subject.build_order_variants(paragraphs, bindings, codec=codec)


def test_exact_fixed_panel_original_first_and_validation_unmodified(corpus):
    before = deepcopy(corpus); result = prepare(corpus)
    assert corpus == before
    assert result["unique_source_count"] == len(result["rows"]) == 108
    assert result["requested_variant_count"] == len(result["requests"]) == 120
    assert result["duplicate_alias_count"] == len(result["aliases"]) == 12
    assert len(result["pairs"]) == result["changed_source_count"] == 60
    assert [row["id"] for row in result["rows"][:48]] == [row["id"] for row in corpus[0]["train"]]
    for original, row in zip(corpus[0]["train"], result["rows"][:48]):
        assert all(row[key] == original[key] for key in ("id", "source_text", "target", "target_ids", "components"))
    assert all(row["split"] == "train" for row in result["rows"])
    assert result["validation_unchanged_sha256"] == subject.digest(corpus[0]["validation"])
    assert not any(result[key] for key in subject.FALSE)


def test_unicode_offsets_and_permutation_only_preserve_complete_references(corpus):
    result = prepare(corpus); parents = {row["id"]: row for row in corpus[0]["train"]}
    for row in result["rows"]:
        meta = row["order_diagnostic"]; parent = parents[meta["parent_id"]]
        assert [meta["permutation"][i] for i in meta["inverse_permutation"]] == list(range(row["clause_count"]))
        assert row["target"]["rules"] == [parent["target"]["rules"][i] for i in meta["permutation"]]
        for component in row["components"]:
            text = row["source_text"][component["char_start"]:component["char_end"]]
            assert row["source_text"].encode()[component["byte_start"]:component["byte_end"]] == text.encode()
            assert subject.text_digest(text) == component["source_sha256"]
        assert sorted(row["target_component_ids"]) == sorted(parent["target_component_ids"])
        assert "embedding" not in row and "source_tokens" not in row
    for alias in result["aliases"]:
        assert alias["variant"] == "rotate_left_one" and alias["clause_count"] == 2
        assert alias["alias_of_request"].endswith(":order:reverse")
        assert alias["independent_observation"] is False


@pytest.mark.parametrize("mutation", [
    lambda p, b: p["train"][12].update(split="validation"),
    lambda p, b: p["train"][12].update(source_sha256="0"*64),
    lambda p, b: p["train"][12].update(target_sha256="0"*64),
    lambda p, b: p["train"][12]["target_ids"].reverse(),
    lambda p, b: p["train"][12]["components"][0].update(byte_end=1),
    lambda p, b: p["train"][12]["components"][0].update(char_start=True),
    lambda p, b: p["train"][12]["components"][0].update(target_sha256="0"*64),
    lambda p, b: p["train"][12]["components"][0]["logical_slot"].reverse(),
    lambda p, b: p["train"][12]["components"][0]["original_metadata"].update(split="validation"),
    lambda p, b: p["train"][12].update(admitted=True),
    lambda p, b: b[12]["components"][0].update(source_text="different source"),
    lambda p, b: b[12]["components"][0].update(end_char=1),
    lambda p, b: b[12].update(target_ids=[1, 2]),
    lambda p, b: b[12]["source_tokens"].update(truncated=True),
    lambda p, b: b[12]["source_tokens"].update(encoder_context_tokens=1024),
    lambda p, b: b[12]["source_tokens"].update(forward_token_count=1),
    lambda p, b: b[12]["source_tokens"].update(tokenizer_sha256="0"*64),
    lambda p, b: p["train"][12].update(component_group_ids=[]),
    lambda p, b: p["original_split_inventory"]["validation"].append(deepcopy(p["original_split_inventory"]["train"][0])),
    lambda p, b: p["train"].pop(),
    lambda p, b: b.pop(),
])
def test_corrupt_or_leaking_source_bindings_refused(corpus, mutation):
    mutation(corpus[0], corpus[1])
    with pytest.raises(ValueError): prepare(corpus)


def test_codec_change_does_not_silently_retokenize_old_targets(corpus):
    codec = corpus[2]; codec["target_vocabulary"][-2:] = reversed(codec["target_vocabulary"][-2:])
    with pytest.raises(ValueError): prepare(corpus)


def test_vector_distances_zero_norm_and_finite_geometry():
    result = subject.vector_distance([3., 4.], [6., 8.])
    assert result["l2"] == 5 and result["normalized_l2"] == 0
    assert result["cosine_distance"] == 0 and result["left_norm"] == 5
    zero = subject.vector_distance([0., 0.], [0., 0.])
    assert zero["zero_norm_present"] and zero["cosine_distance"] is None and zero["normalized_l2"] is None
    assert zero["exact_values_equal"]
    for bad in ([math.nan], [math.inf], [True], [], [1e200]):
        with pytest.raises(ValueError): subject.vector_distance(bad, bad)
    with pytest.raises(ValueError): subject.vector_distance([1], [1, 2])


def test_deterministic_cyclic_baseline_and_repeat_noise_are_separate(corpus):
    data = prepare(corpus); vectors = {row["id"]: [float(i+1), 1.] for i, row in enumerate(data["rows"])}
    repeats = {key: vectors[key] for key in data["original_ids"]}
    before = deepcopy((data, vectors, repeats))
    result = subject.paired_vector_metrics(data, vectors, space="synthetic", repeat_vectors_by_id=repeats)
    assert (data, vectors, repeats) == before
    assert len(result["pairs"]) == 60 and len(result["different_parent_pairs"]) == len(result["repeat_pairs"]) == 48
    assert result["different_parent_pairs"][0]["other_id"] == data["original_ids"][1]
    assert result["different_parent_pairs"][11]["other_id"] == data["original_ids"][0]
    assert result["by_length"]["1"]["order_change"]["count"] == 0
    assert result["by_length"]["2"]["order_change"]["count"] == 12
    assert result["by_length"]["4"]["order_change"]["count"] == 24
    assert result["by_length"]["4"]["mean_distance_ratios"]["same_text_repeat"]["l2"] is None
    assert not result["order_recoverability_proven"]


def test_changed_inventory_and_preparation_are_refused(corpus):
    data = prepare(corpus); vectors = {row["id"]: [1.] for row in data["rows"]}
    with pytest.raises(ValueError): subject.paired_vector_metrics(data, {**vectors, "extra": [1.]}, space="test")
    with pytest.raises(ValueError): subject.paired_vector_metrics(data, vectors, space="test", repeat_vectors_by_id={})
    data["rows"][0]["source_text"] += "changed"
    with pytest.raises(ValueError): subject.paired_vector_metrics(data, vectors, space="test")


def predictions(data):
    return {row["id"]: dict(id=row["id"], token_ids=row["target_ids"][1:-1], eos_reached=True,
        generation_status="eos") for row in data["rows"]}


def logits(data, codec):
    vocabulary = codec["target_vocabulary"]; result = {}
    for row in data["rows"]:
        slots = [[[0.]*len(vocabulary) for _ in range(4)] for _ in range(8)]
        for i, rule in enumerate(row["target"]["rules"]):
            for f, field in enumerate(subject.FIELDS): slots[i][f][vocabulary.index(json.dumps(rule[field]))] = 2.
        result[row["id"]] = slots
    return result


def test_posthoc_prediction_permutation_and_repeated_label_strata(corpus):
    data = prepare(corpus); prediction = predictions(data)
    result = subject.paired_prediction_metrics(data, prediction, codec=corpus[2])
    assert all(row["exact_target_with_eos"] for row in result["rows"])
    assert all(pair["matches_permuted_original_prediction"] for pair in result["pairs"])
    for pair in result["pairs"]:
        assert pair["equivariance"]["modality"]["informative_slots"] == 0
        assert pair["equivariance"]["object"]["informative_slots"] == 0
        assert pair["equivariance"]["actor"]["informative_matches_permuted"] == pair["clause_count"]
        assert pair["equivariance"]["actor_action"]["informative_matches_fixed"] == 0
    changed = data["pairs"][0]; prediction[changed["id"]]["token_ids"] = prediction[changed["parent_id"]]["token_ids"]
    new = subject.paired_prediction_metrics(data, prediction, codec=corpus[2])
    pair = new["pairs"][0]
    assert pair["matches_fixed_original_prediction"] and not pair["matches_permuted_original_prediction"]
    assert pair["equivariance"]["actor_action"]["informative_matches_fixed"] == 2


def test_bad_generation_is_scored_without_repair_or_false_eos(corpus):
    data = prepare(corpus); prediction = predictions(data)
    first = data["rows"][0]["id"]
    prediction[first]["eos_reached"] = False
    result = subject.paired_prediction_metrics(data, prediction, codec=corpus[2])
    assert result["rows"][0]["syntax_valid"] and not result["rows"][0]["exact_target_with_eos"]
    prediction[first]["token_ids"] = [0]
    result = subject.paired_prediction_metrics(data, prediction, codec=corpus[2])
    assert not result["rows"][0]["syntax_valid"] and result["rows"][0]["actor_action_pairs_correct"] == 0
    prediction[first]["token_ids"] = [-1]
    with pytest.raises(ValueError): subject.paired_prediction_metrics(data, prediction, codec=corpus[2])


def test_scalar_source_only_scores_and_full_logit_slot_distances(corpus):
    data = prepare(corpus); scores = logits(data, corpus[2]); before = deepcopy(scores)
    result = subject.paired_scalar_metrics(data, scores, codec=corpus[2])
    assert scores == before
    assert all(row["actor_action_pairs_correct"] == row["clause_count"] for row in result["rows"])
    assert all(pair["ordered_argmax_equivariant"] for pair in result["pairs"])
    for pair in result["pairs"]:
        assert pair["full_logit_permuted_slot_distance"]["l2"] == 0
        assert pair["full_logit_fixed_slot_distance"]["l2"] > 0
        assert pair["equivariance"]["modality"]["informative_slots"] == 0
        assert pair["equivariance"]["actor_action"]["informative_matches_permuted"] == pair["clause_count"]
    key = data["rows"][0]["id"]; scores[key][0][0][0] = math.nan
    with pytest.raises(ValueError): subject.paired_scalar_metrics(data, scores, codec=corpus[2])


def test_full_vocabulary_ties_are_not_filtered(corpus):
    data = prepare(corpus); scores = {row["id"]: [[[0.]*len(corpus[2]["target_vocabulary"]) for _ in range(4)]
        for _ in range(8)] for row in data["rows"]}
    result = subject.paired_scalar_metrics(data, scores, codec=corpus[2])
    assert all(row["predicted_token_ids"] == [[0]*4 for _ in range(8)] for row in result["rows"])
    assert all(row["actor_action_pairs_correct"] == 0 for row in result["rows"])
    assert all(pair["ordered_argmax_equivariant"] for pair in result["pairs"])
    assert all(pair["equivariance"]["actor"]["comparable_slots"] == 0 for pair in result["pairs"])
    assert not result["order_recoverability_proven"]
