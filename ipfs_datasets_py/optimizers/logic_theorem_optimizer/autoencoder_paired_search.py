"""Bounded neural beam search for existing shared paired-copy checkpoints.

This inference-only extension leaves trained packages and their original
producer pins untouched. It receives source text, direction and numeric search
bounds; it has no target, domain parser, source-label lookup or training path.
"""
from __future__ import annotations

import math
from pathlib import Path

from . import autoencoder_paired_copy as shared


def infer_paired_copy_beam(descriptor, source, direction, *, beam_width=8,
                           max_new_tokens=96, weight_ablation=None):
    """Return independently scored learned alternatives for downstream checking."""
    import torch
    if type(beam_width) is not int or not 1 <= beam_width <= 16:
        raise ValueError("beam width must be between 1 and 16")
    if type(max_new_tokens) is not int or not 1 <= max_new_tokens <= shared.MAX_TOKENS:
        raise ValueError("bounded decoder length required")
    if direction not in ("encode", "decode") or type(source) is not str:
        raise ValueError("source string and paired direction required")
    loaded = shared.load_paired_copy(descriptor)
    model, config = loaded["model"], loaded["config"]
    disabled = shared._ablate(model, weight_ablation)
    tokens = shared.tokenize(source)
    if len(tokens) >= shared.MAX_TOKENS:
        raise ValueError("source must leave room for direction token")
    vocabulary = config["vocabulary"]
    inputs, copied, extra, _ = shared._source_ids(tokens, vocabulary, direction)
    alphabet = vocabulary + extra
    source_ids = torch.tensor([inputs], dtype=torch.long)
    copy_ids = torch.tensor([copied], dtype=torch.long)
    mask = source_ids != 0
    mask[:, 0] = False
    completed, calls = [], 0
    with torch.inference_mode():
        encoded, hidden = model.encode(source_ids, torch.tensor([len(inputs)]))
        # score, generated IDs, hidden state, next decoder input, copy traces
        active = [(0.0, (), hidden, 1, ())]
        for _ in range(max_new_tokens):
            expanded = []
            for score, ids, state, current, traces in active:
                probs, state, generator, copy, attention, gate = model.decode(
                    torch.tensor([[current]], dtype=torch.long), state,
                    encoded, mask, copy_ids, len(alphabet), disable_copy=disabled)
                calls += 1
                if not all(bool(torch.isfinite(t).all()) for t in
                           (probs, state, generator, copy, attention, gate)):
                    raise ValueError("nonfinite beam inference")
                values = probs[0, -1]
                # A stable token-ID tie break makes report replay deterministic.
                indices = torch.argsort(values, descending=True, stable=True)[:beam_width].tolist()
                for index in indices:
                    probability = float(values[index])
                    if probability <= 0:
                        continue
                    score_next = score + math.log(probability)
                    if index == 2:
                        if ids:
                            completed.append((score_next, ids, traces))
                        continue
                    if index in (0, 1, 3, 4, 5):
                        continue
                    token = alphabet[index]
                    gen_mass, copy_mass = float(generator[0, -1, index]), float(copy[0, -1, index])
                    trace = {"token": token, "extended_copy_token": index >= len(vocabulary),
                        "generator_probability": gen_mass, "copy_probability": copy_mass,
                        "copy_source_positions": [i for i, value in enumerate(tokens) if value == token],
                        "dominant_branch": "copy" if copy_mass > gen_mass else "generator"}
                    expanded.append((score_next, ids + (index,), state, index, traces + (trace,)))
            active = sorted(expanded, key=lambda row: (-row[0], row[1]))[:beam_width]
            # Keep completed paths separate so a short EOS cannot eliminate
            # every still-active alternative. Selection uses raw log likelihood.
            completed = sorted(completed, key=lambda row: (-row[0], row[1]))[:beam_width]
            if not active:
                break
            if len(completed) >= beam_width and completed[-1][0] >= active[0][0]:
                break
    unknown = sorted(set(tokens) - set(vocabulary))
    rows = []
    for rank, (score, ids, traces) in enumerate(completed):
        predicted = [alphabet[index] for index in ids]
        rows.append({"rank": rank, "log_probability": score,
            "generated_text": " ".join(predicted), "tokens": predicted,
            "ended": True, "status": "generated", "input_oov_tokens": unknown,
            "uncovered_input_tokens": unknown if disabled else [],
            "input_coverage_complete": not unknown or not disabled,
            "copy_trace": list(traces), "copy_enabled": not disabled,
            "checkpoint_weights_sha256": loaded["training"]["final_state_sha256"],
            "weight_ablation": weight_ablation, "teacher_forcing": False,
            "target_access": False, "training_executed": False,
            "copy_probability_is_semantic_confidence": False,
            "provider_calls": 0, "download_calls": 0, **shared._FALSE})
    return {"schema": "shared-paired-copy-beam-search/v1", "direction": direction,
        "source_sha256": shared._sha(source.encode()), "checkpoint": dict(descriptor),
        "checkpoint_weights_sha256": loaded["training"]["final_state_sha256"],
        "search_producer_sha256": shared._sha(Path(__file__).read_bytes()),
        "beam_width": beam_width, "max_new_tokens": max_new_tokens,
        "ranking": "descending_raw_autoregressive_log_probability",
        "native_decoder_calls": calls, "rows": rows,
        "weight_ablation": weight_ablation, "teacher_forcing": False,
        "target_access": False, "training_executed": False,
        "provider_calls": 0, "download_calls": 0, **shared._FALSE}
