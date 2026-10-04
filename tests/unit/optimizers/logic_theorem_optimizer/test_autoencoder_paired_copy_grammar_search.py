"""Neural scores, full-alphabet masking, input-local copying and policy bounds."""
import math
from pathlib import Path

import pytest

from .test_autoencoder_paired_copy_continuation import parent, checkpoint
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_paired_copy as shared
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_paired_copy_continuation as continuation
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_paired_copy_grammar_search as search

POLICY = {"policy_id": "toy-four-field-grammar/v1", "policy_sha256": "a" * 64}


def lexical(token):
    return token.isalnum() and not token.startswith("<")


def sequence_policy(prefix, *, eos=False):
    if eos:
        return len(prefix) == 8
    if not 1 <= len(prefix) <= 8:
        return False
    position, token = len(prefix) - 1, prefix[-1]
    markers = {0: "<actor>", 2: "<action>", 4: "<object>", 6: "<modality>"}
    if position in markers:
        return token == markers[position]
    if position == 7:
        return token in ("required", "permitted")
    return lexical(token)


def text_policy(prefix, *, eos=False):
    if eos:
        return len(prefix) == 5
    if not 1 <= len(prefix) <= 5:
        return False
    position, token = len(prefix) - 1, prefix[-1]
    return token == "must" if position == 1 else token == "." if position == 4 else lexical(token)


def run(checkpoint, source, direction="encode", **kwargs):
    return search.infer_paired_copy_grammar_beam(checkpoint, source, direction,
        **{**POLICY, "prefix_constraint": sequence_policy if direction == "encode" else text_policy,
           "beam_width": 3, "max_new_tokens": 24, **kwargs})


@pytest.mark.parametrize("direction", ["encode", "decode"])
def test_actual_neural_forward_and_inverse_copy_unseen_input(checkpoint, direction):
    text = "agent must inspect unseenasteroid ."
    wire = "<actor> agent <action> inspect <object> unseenasteroid <modality> required"
    source, expected = (text, wire) if direction == "encode" else (wire, text)
    report = run(checkpoint, source, direction)
    assert report["rows"][0]["generated_text"] == expected
    assert report["native_encoder_calls"] == 1 and report["native_decoder_calls"] > 0
    assert report["mask_applied_before_top_k"]
    assert not report["probabilities_renormalized_after_grammar_mask"]
    trace = next(row for row in report["rows"][0]["copy_trace"] if row["token"] == "unseenasteroid")
    assert trace["extended_copy_token"] and trace["copy_probability"] > 0
    assert trace["generator_probability"] == 0
    assert [shared.tokenize(source)[i] for i in trace["copy_source_positions"]] == ["unseenasteroid"]
    assert report["policy_arguments"] == "generated_prefix_tuple_and_eos_boolean_only"
    assert report["policy_semantic_independence_verified_by_backend"] is False
    assert report["training_executed"] is report["target_access"] is report["proof_authority"] is False


def test_original_neural_path_score_includes_eos_without_renormalizing(checkpoint):
    import torch
    source = "agent must inspect unseenasteroid ."
    result = run(checkpoint, source)["rows"][0]
    loaded = continuation.load_paired_copy_continuation(checkpoint)
    vocabulary = loaded["config"]["vocabulary"]
    inputs, copied, extra, _ = shared._source_ids(shared.tokenize(source), vocabulary, "encode")
    alphabet = vocabulary + extra
    ids = torch.tensor([inputs]); copy_ids = torch.tensor([copied]); mask = ids != 0; mask[:, 0] = False
    current, score = 1, 0.0
    with torch.inference_mode():
        encoded, state = loaded["model"].encode(ids, torch.tensor([len(inputs)]))
        for token in result["tokens"] + ["<eos>"]:
            probabilities, state, *_ = loaded["model"].decode(torch.tensor([[current]]), state,
                encoded, mask, copy_ids, len(alphabet))
            current = alphabet.index(token)
            score += math.log(float(probabilities[0, -1, current]))
    assert result["log_probability"] == pytest.approx(score, abs=1e-9)
    assert score == pytest.approx(sum(x["raw_log_probability_increment"] for x in result["copy_trace"])
                                  + math.log(result["eos_probability"]), abs=1e-9)
    assert all(t["raw_token_probability"] == pytest.approx(t["generator_probability"] + t["copy_probability"], abs=1e-7)
               for t in result["copy_trace"])


def test_valid_token_below_original_top16_is_considered_before_topk(checkpoint):
    import torch
    source = "agent must inspect cache ."
    loaded = continuation.load_paired_copy_continuation(checkpoint)
    vocabulary = loaded["config"]["vocabulary"]
    inputs, copied, extra, _ = shared._source_ids(shared.tokenize(source), vocabulary, "encode")
    ids = torch.tensor([inputs]); copy_ids = torch.tensor([copied]); mask = ids != 0; mask[:, 0] = False
    with torch.inference_mode():
        encoded, state = loaded["model"].encode(ids, torch.tensor([len(inputs)]))
        probs, *_ = loaded["model"].decode(torch.tensor([[1]]), state, encoded, mask, copy_ids, len(vocabulary) + len(extra))
    order = torch.argsort(probs[0, -1], descending=True, stable=True).tolist()
    index = next(i for i in reversed(order) if i >= 6 and float(probs[0, -1, i]) > 0)
    assert order.index(index) >= 16
    rare_terminal = (vocabulary + extra)[index]
    observed = set()
    # A synthetic one-terminal grammar exercises starvation ordering only.
    # It makes no claim that this terminal represents the source's meaning.
    def narrow(prefix, *, eos=False):
        if not eos and len(prefix) == 1:
            observed.add(prefix[0])
        return prefix == (rare_terminal,)
    report = run(checkpoint, source, prefix_constraint=narrow, beam_width=1)
    assert report["rows"][0]["tokens"] == [rare_terminal]
    assert report["rows"][0]["copy_trace"][0]["raw_vocabulary_rank"] >= 16
    assert observed == set(vocabulary[6:] + extra)
    assert report["raw_top1_pruned_nodes"] >= 1


def test_policy_receives_only_immutable_generated_prefix_and_eos(checkpoint):
    calls = []
    def policy(prefix, *, eos=False):
        assert type(prefix) is tuple and all(type(token) is str for token in prefix)
        assert type(eos) is bool
        calls.append((prefix, eos))
        return sequence_policy(prefix, eos=eos)
    report = run(checkpoint, "agent must inspect cache .", prefix_constraint=policy)
    assert report["policy_evaluations"] == len(calls)
    assert not any(any(token in shared.SPECIAL for token in prefix) for prefix, _ in calls)
    assert any(eos for _, eos in calls)


def test_all_rejecting_grammar_returns_no_output_without_fallback(checkpoint):
    report = run(checkpoint, "agent must inspect cache .", prefix_constraint=lambda prefix, *, eos=False: False)
    assert report["rows"] == [] and report["status"] == "no_grammar_admissible_completion"
    assert report["native_decoder_calls"] == 1 and report["dead_end_nodes"] == 1


@pytest.mark.parametrize("ablation", ["zero_output_head", "disable_copy"])
def test_ablations_change_actual_probabilities_without_mutating_checkpoint(checkpoint, ablation):
    before = Path(checkpoint["path"]).read_bytes()
    source = "agent must inspect unseenasteroid ."
    normal = run(checkpoint, source)
    changed = run(checkpoint, source, weight_ablation=ablation)
    assert normal["rows"] != changed["rows"]
    assert changed["weight_ablation"] == ablation
    if ablation == "disable_copy":
        assert all("unseenasteroid" not in row["tokens"] for row in changed["rows"])
        assert all(t["copy_probability"] == 0 for row in changed["rows"] for t in row["copy_trace"])
    assert Path(checkpoint["path"]).read_bytes() == before


def test_replay_scores_and_search_pins_are_deterministic(checkpoint):
    source = "agent must inspect cache ."
    first = run(checkpoint, source)
    assert first == run(checkpoint, source)
    assert first["implementation_pins"] == search.implementation_pins()
    assert first["search_producer_sha256"] == shared._sha(Path(search.__file__).read_bytes())
    assert first["checkpoint_weights_sha256"] == continuation.load_paired_copy_continuation(checkpoint)["training"]["final_state_sha256"]
    scores = [row["log_probability"] for row in first["rows"]]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.parametrize("value", [None, 0, 1, [], "True"])
def test_policy_must_return_exact_boolean(checkpoint, value):
    with pytest.raises(ValueError, match="exact bool"):
        run(checkpoint, "agent must inspect cache .", prefix_constraint=lambda prefix, *, eos=False: value)


@pytest.mark.parametrize("settings", [
    {"beam_width": 0}, {"beam_width": 17}, {"beam_width": True},
    {"max_new_tokens": 0}, {"max_new_tokens": 161}, {"max_new_tokens": True},
    {"policy_id": ""}, {"policy_id": "not allowed spaces"}, {"policy_sha256": "bad"}, {"prefix_constraint": None},
])
def test_bounds_and_policy_identity_reject_before_checkpoint_loading(settings):
    with pytest.raises(ValueError):
        run({}, "agent must inspect cache .", **settings)


def test_no_intent_imports_or_training_path_in_generic_module():
    source = Path(search.__file__).read_text()
    assert "intent_ir" not in source and "rich_grammar" not in source
    assert "train_paired" not in source
