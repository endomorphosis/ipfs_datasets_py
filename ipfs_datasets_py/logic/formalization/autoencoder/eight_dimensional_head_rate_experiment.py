"""Closed optimizer-rate diagnostic for the preserved historical 8D inputs.

This does not change an encoder, decoder architecture, source representation,
loss, or selection rule.  Both arms retain the existing two-group AdamW path.
The larger rate also scales its decoupled weight decay; that is intentional and
must be reported.  Saved-data diagnostics do not confer proof authority.
"""
from collections import defaultdict
import math


ARMS = [
    dict(name="head-rate10-baseline", non_action_learning_rate_multiplier=10.),
    dict(name="head-rate2-candidate", non_action_learning_rate_multiplier=2.),
]


def multiplier(arm):
    if type(arm) is not dict or arm not in ARMS or any(type(arm[k]) is not type(v) for k, v in ARMS[ARMS.index(arm)].items()):
        raise ValueError("an exact registered 8D head-rate arm is required")
    return arm["non_action_learning_rate_multiplier"]


def diagnose_source_geometry(contexts, model_state, *, input_transform):
    """Pure saved-data calculation, with no fitting or label-dependent transform."""
    if type(contexts) is not dict or set(contexts) != {"train", "validation"}:
        raise ValueError("exact train and development source contexts required")
    if (type(input_transform) is not dict or set(input_transform) != {"mode", "mean", "scale", "origin"}
            or input_transform["mode"] not in ("center_rms", "none") or input_transform["origin"] != "training_only"
            or len(input_transform["mean"]) != 8 or not all(type(v) in (int, float) and math.isfinite(v) for v in input_transform["mean"])
            or type(input_transform["scale"]) not in (int, float) or not math.isfinite(input_transform["scale"])
            or not .01 <= input_transform["scale"] <= 1e8
            or (input_transform["mode"] == "none" and (input_transform["mean"] != [0.]*8 or input_transform["scale"] != 1.))):
        raise ValueError("explicit existing training-only source input transform required")
    # This archived sidecar's frozen residual projection is the identity because
    # its complete up-projection is zero. Refuse to omit a nonidentity projector.
    up = model_state["body.body.body.projection_up.weight"]
    up_bias = model_state["body.body.body.projection_up.bias"]
    if (len(up) != 8 or any(len(row) != 8 for row in up) or len(up_bias) != 8
            or not all(type(v) in (int, float) and v == 0. for v in [*up_bias, *(v for row in up for v in row)])):
        raise ValueError("diagnostic requires the authenticated frozen identity residual projection")
    means = model_state["clause_source_mean"]
    scale = model_state["clause_source_scale"]
    weights = model_state["non_action_head.source_projection.weight"]
    biases = model_state["non_action_head.source_projection.bias"]
    if (len(means) != 8 or len(weights) != 64 or len(biases) != 64
            or any(len(row) != 8 for row in weights)
            or type(scale) not in (int, float) or not math.isfinite(scale) or scale <= 0):
        raise ValueError("exact saved 8-to-64 source geometry required")
    if not all(type(v) in (int, float) and math.isfinite(v) for v in [*means, *biases, *(v for row in weights for v in row)]):
        raise ValueError("finite saved projection required")
    splits = {}; inventory = {}
    for split, rows in contexts.items():
        unique = {}
        for row in rows.values():
            for segment in row["segments"]:
                text = segment["source_text"]; vector = segment["vector"]
                if type(text) is not str or not text or len(vector) != 8 or not all(type(v) in (int, float) and math.isfinite(v) for v in vector):
                    raise ValueError("finite actual eight-dimensional source required")
                if text in unique and unique[text] != vector:
                    raise ValueError("same source has conflicting cached vectors")
                unique[text] = vector
        if not unique:
            raise ValueError("nonempty source split required")
        buckets = defaultdict(list)
        for text, vector in unique.items(): buckets[tuple(vector)].append(text)
        saturation = 0; maximum = 0.
        for vector in unique.values():
            transformed = [(v - mean) / input_transform["scale"] for v, mean in zip(vector, input_transform["mean"])]
            normalized = [(v - mean) / scale for v, mean in zip(transformed, means)]
            for weight, bias in zip(weights, biases):
                preactivation = sum(w * v for w, v in zip(weight, normalized)) + bias
                saturation += abs(math.tanh(preactivation)) >= .99
                maximum = max(maximum, abs(preactivation))
        splits[split] = dict(unique_sources=len(unique), unique_vectors=len(buckets),
            colliding_source_groups=[items for items in buckets.values() if len(items) > 1],
            tanh_abs_at_least_point99=saturation, activation_count=len(unique)*64,
            maximum_absolute_preactivation=maximum)
        inventory[split] = unique
    overlap = set(inventory["train"]) & set(inventory["validation"])
    cross = [(a, b) for a, x in inventory["train"].items() for b, y in inventory["validation"].items() if x == y]
    return dict(schema="eight-dimensional-source-geometry/v2", splits=splits,
        cross_split_exact_vector_collisions=cross, cross_split_literal_overlap=sorted(overlap),
        calculation="Python float64 from saved float32 tensor exports; diagnostics only",
        feature_path=["raw_cached8D", "frozen_input_center_rms", "verified_identity_residual_projection", "frozen_clause_center_rms", "source_projection_affine", "tanh"],
        frozen_input_transform_applied=True, nonidentity_projection_allowed=False,
        source_representation="historical linguistic feature hash; not semantic embeddings",
        encoder_executed=False, normalization_refitted=False, training_executed=False,
        qualified=False, admitted=False, lake_executed=False)
