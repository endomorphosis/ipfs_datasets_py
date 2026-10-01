"""Additive, domain-neutral grammar-constrained neural paired-copy search.

A policy receives only a generated token prefix and an EOS flag. The caller
owns and pins the policy; this module does not inspect semantic domains, source
ASTs, expected slots, or training labels. Constraints prune candidates before
top-k selection. Scores remain original neural probabilities, never grammar-
renormalized probabilities. Grammar feasibility does not establish meaning.
"""
from __future__ import annotations

import math
from pathlib import Path
import re

from . import autoencoder_paired_copy as shared
from . import autoencoder_paired_copy_continuation as continuation

SCHEMA = "shared-paired-copy-grammar-beam/v1"
MAX_NEW_TOKENS = 160


def implementation_pins():
    return {"grammar_search_sha256": shared._sha(Path(__file__).read_bytes()), **continuation._implementation()}


def infer_paired_copy_grammar_beam(descriptor, source, direction, *, prefix_constraint,
        policy_id, policy_sha256, beam_width=8, max_new_tokens=160, weight_ablation=None):
    """Return source-local neural alternatives satisfying a prefix policy.

    ``prefix_constraint(tuple_of_generated_tokens, *, eos=False)`` must return
    an exact bool. ``eos=True`` asks whether that unchanged prefix is complete.
    It never receives the source, model tensors, expected output, or direction;
    use a separately pinned domain policy for each direction when necessary.
    The caller must independently review policy freedom from hidden targets.
    """
    import torch
    require = shared._require
    require(type(beam_width) is int and 1 <= beam_width <= 16, "beam width must be between 1 and 16")
    require(type(max_new_tokens) is int and 1 <= max_new_tokens <= MAX_NEW_TOKENS,
            "grammar search decoder length must be between 1 and 160")
    require(type(policy_id) is str and re.fullmatch(r"[A-Za-z0-9_./:-]{1,160}", policy_id) is not None and
            continuation._digest(policy_sha256), "bounded policy identity and SHA256 required")
    require(callable(prefix_constraint), "callable generated-prefix grammar constraint required")
    require(direction in ("encode", "decode") and type(source) is str, "source string and paired direction required")
    tokens = shared.tokenize(source)
    require(len(tokens) < shared.MAX_TOKENS, "source must leave room for direction token")
    loaded = continuation._load_parent(descriptor)
    model, config = loaded["model"], loaded["config"]
    disabled = shared._ablate(model, weight_ablation)
    vocabulary = config["vocabulary"]
    inputs, copied, extra, _ = shared._source_ids(tokens, vocabulary, direction)
    alphabet = vocabulary + extra
    source_ids = torch.tensor([inputs], dtype=torch.long)
    copy_ids = torch.tensor([copied], dtype=torch.long)
    mask = source_ids != 0
    mask[:, 0] = False
    completed, calls, policy_calls, pruned, dead_ends, displaced_top1 = [], 0, 0, 0, 0, 0

    def allowed(prefix, eos):
        nonlocal policy_calls
        policy_calls += 1
        answer = prefix_constraint(prefix, eos=eos)
        require(type(answer) is bool, "prefix constraint must return an exact bool")
        return answer

    with torch.inference_mode():
        encoded, hidden = model.encode(source_ids, torch.tensor([len(inputs)]))
        # Original score, token IDs, hidden state, next decoder token, traces.
        active = [(0.0, (), hidden, 1, ())]
        for _ in range(max_new_tokens):
            expanded = []
            for score, ids, state, current, traces in active:
                probabilities, state, generator, pointer, attention, gate = model.decode(
                    torch.tensor([[current]], dtype=torch.long), state, encoded, mask,
                    copy_ids, len(alphabet), disable_copy=disabled)
                calls += 1
                require(all(bool(torch.isfinite(value).all()) for value in
                    (probabilities, state, generator, pointer, attention, gate)), "nonfinite grammar beam inference")
                values = probabilities[0, -1]
                require(bool((values >= 0).all()) and bool((values <= 1 + 1e-6).all()),
                        "invalid grammar beam probabilities")
                prefix = tuple(alphabet[index] for index in ids)
                # Every alphabet entry is checked before top-k. Reserved model
                # tokens remain protocol-invalid even if the policy allows them.
                feasible = []
                for index, token in enumerate(alphabet):
                    if index in (0, 1, 3, 4, 5):
                        feasible.append(False)
                    elif index == 2:
                        feasible.append(bool(prefix) and allowed(prefix, True))
                    else:
                        feasible.append(allowed(prefix + (token,), False))
                pruned += len(feasible) - sum(feasible)
                raw_order = torch.argsort(values, descending=True, stable=True).tolist()
                raw_rank = {index: rank for rank, index in enumerate(raw_order)}
                raw_top = raw_order[0]
                displaced_top1 += not feasible[raw_top]
                valid = torch.tensor(feasible, dtype=torch.bool)
                admissible = values.masked_fill(~valid, -math.inf)
                indices = torch.argsort(admissible, descending=True, stable=True)[:beam_width].tolist()
                admitted_here = 0
                for index in indices:
                    probability = float(values[index])
                    if not feasible[index] or probability <= 0:
                        continue
                    admitted_here += 1
                    increment = math.log(probability)
                    score_next = score + increment
                    if index == 2:
                        completed.append((score_next, ids, traces, probability, raw_rank[index]))
                        continue
                    token = alphabet[index]
                    gen_mass, copy_mass = float(generator[0, -1, index]), float(pointer[0, -1, index])
                    trace = {"token": token, "extended_copy_token": index >= len(vocabulary),
                        "generator_probability": gen_mass, "copy_probability": copy_mass,
                        "copy_source_positions": [i for i, value in enumerate(tokens) if value == token],
                        "dominant_branch": "copy" if copy_mass > gen_mass else "generator",
                        "raw_token_probability": probability, "raw_log_probability_increment": increment,
                        "raw_vocabulary_rank": raw_rank[index], "grammar_allowed": True,
                        "raw_top1_token": alphabet[raw_top],
                        "raw_top1_permitted_by_grammar_and_protocol": feasible[raw_top]}
                    expanded.append((score_next, ids + (index,), state, index, traces + (trace,)))
                dead_ends += admitted_here == 0
            active = sorted(expanded, key=lambda row: (-row[0], row[1]))[:beam_width]
            completed = sorted(completed, key=lambda row: (-row[0], row[1]))[:beam_width]
            if not active or (len(completed) >= beam_width and completed[-1][0] >= active[0][0]):
                break
    unknown = sorted(set(tokens) - set(vocabulary))
    rows = []
    for rank, (score, ids, traces, eos_probability, eos_rank) in enumerate(completed):
        predicted = [alphabet[index] for index in ids]
        rows.append({"rank": rank, "log_probability": score, "generated_text": " ".join(predicted),
            "tokens": predicted, "ended": True, "status": "generated",
            "input_oov_tokens": unknown, "uncovered_input_tokens": unknown if disabled else [],
            "input_coverage_complete": not unknown or not disabled,
            "copy_trace": list(traces), "copy_enabled": not disabled,
            "copy_vocabulary_scope": "current_input_only", "copy_probability_is_semantic_confidence": False,
            "eos_probability": eos_probability, "eos_raw_vocabulary_rank": eos_rank,
            "policy_id": policy_id, "policy_sha256": policy_sha256,
            "grammar_constraints_applied": True, "probabilities_renormalized_after_grammar_mask": False,
            "checkpoint_weights_sha256": loaded["training"]["final_state_sha256"],
            "weight_ablation": weight_ablation, "teacher_forcing": False,
            "target_access": False, "training_executed": False,
            "provider_calls": 0, "download_calls": 0, **shared._FALSE})
    return {"schema": SCHEMA, "status": "generated" if rows else "no_grammar_admissible_completion",
        "direction": direction, "source_sha256": shared._sha(source.encode()), "checkpoint": dict(descriptor),
        "checkpoint_weights_sha256": loaded["training"]["final_state_sha256"],
        "implementation_pins": implementation_pins(), "search_producer_sha256": shared._sha(Path(__file__).read_bytes()),
        "policy_id": policy_id, "policy_sha256": policy_sha256,
        "policy_arguments": "generated_prefix_tuple_and_eos_boolean_only",
        "policy_semantic_independence_verified_by_backend": False,
        "beam_width": beam_width, "max_new_tokens": max_new_tokens,
        "ranking": "descending_original_autoregressive_log_probability_including_EOS",
        "mask_applied_before_top_k": True, "probabilities_renormalized_after_grammar_mask": False,
        "native_encoder_calls": 1, "native_decoder_calls": calls,
        "policy_evaluations": policy_calls, "pruned_candidate_decisions": pruned,
        "raw_top1_pruned_nodes": displaced_top1, "dead_end_nodes": dead_ends,
        "rows": rows, "weight_ablation": weight_ablation,
        "teacher_forcing": False, "target_access": False, "training_executed": False,
        "provider_calls": 0, "download_calls": 0, **shared._FALSE}


__all__ = ["SCHEMA", "MAX_NEW_TOKENS", "implementation_pins", "infer_paired_copy_grammar_beam"]
