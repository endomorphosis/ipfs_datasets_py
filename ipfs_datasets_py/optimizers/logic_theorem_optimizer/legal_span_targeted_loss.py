"""Bounded targeted losses around the authenticated400-step source-span parent.

This outer policy defines the actual objective. Nested legacy configuration is
an unchanged constructor descriptor, never permission to resume its old loss.
Actor compatibility is teacher-forced token-range nonoverlap during train/tune;
it grants no predictive or legal-semantic authority. Existing producers/loaders
stay byte-exact. Numerical methods run only by explicit caller invocation.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import random
import stat
import struct
import time

from . import legal_span_continuation as continuation
from . import legal_span_formula as span

SCHEMA = "bounded-targeted-loss-span-legal-formula-checkpoint/v1"
LINEAGE_ID = "bounded_source_span_targeted_loss_v1"
POLICY_SCHEMA = "bounded-source-span-targeted-loss-policy/v1"
MAX_BYTES = 128 * 1024 * 1024
MAX_NEW_STEPS = 32
MAX_SECONDS = 32
MAX_SOURCE_TOKENS = 128
SOURCE_PARENT_SHA256 = "fd7eb4bd7c8c5d5abb23d168e6b67300497eea6243b5c8cd5779cfbc566d5279"
SOURCE_MODEL_SHA256 = "54e745f0dc75a79c11828048ad5deb44b0f07dcac5b9083bde17948b5206bfcb"
LEGACY96_SHA256 = "4f78bd92f4f5cac93f69eddc1e9d713d08f3eee70372ee7729cccc60792e6995"
SPAN_FIELDS = ("actor", "action", "object", "conditions", "exceptions", "temporal")
FALSE = dict(span.FALSE)


def _require(value, message):
    if not value:
        raise ValueError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def checkpoint_digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _policy(initialization_seed=1729, *, actor_ranking_enabled=False,
            presence_ce_weight=1, batch_order_seed=1729, batch_size=12):
    _require(type(initialization_seed) is int and initialization_seed == 1729,
             "fixed inherited initialization seed1729 required")
    _require(type(actor_ranking_enabled) is bool, "explicit actor ranking boolean required")
    _require(type(presence_ce_weight) is int and presence_ce_weight in (1, 2),
             "conditions/exceptions presence weight must be integer1 or2")
    _require(type(batch_order_seed) is int and batch_order_seed == 1729,
             "fixed distinct batch-order seed1729 required")
    _require(type(batch_size) is int and batch_size == 12, "fixed batch size12 required")
    return {"schema": POLICY_SCHEMA,
        "objective": "modality2_presence_weighted_pointer_mean_plus_actor_hinge/v1",
        "modality_loss_weight": 2, "facet_pointer_CE_weights": {f: 1 for f in SPAN_FIELDS},
        "optional_presence_CE_weights": {f: presence_ce_weight if f in ("conditions", "exceptions") else 1
                                        for f in SPAN_FIELDS[2:]},
        "presence_ce_weight": presence_ce_weight,
        "normalization_denominator": 8 + 2 * (presence_ce_weight - 1),
        "main_summation_order": "(2*modality+sum(six_legacy_facets)+extra_two_presence_means)/(8+2*(w-1)); w1 uses exact legacy expression",
        "actor_ranking_enabled": actor_ranking_enabled, "actor_hinge_coefficient": .25,
        "actor_hinge_margin": 1., "actor_hinge_mean": "all_rows_in_batch_including_zero_negative_domain",
        "actor_span_score": "float32(start[left]+end[right])",
        "actor_negative_domain": "all_source_token_boundaries_left<=right_excluding_exactgold_and_overlap_with_present_gold_nonactor_facets",
        "actor_argmax": "detached_float32_scores; exact_ties_row_major; selected_score_recomputed_with_gradient",
        "actor_compatibility_scope": "teacher_forced_train_tune_only; token_range_nonoverlap_not_predictive_or_legalproof",
        "inference_candidate_coverage_guaranteed": False,
        "compatibility_filter_order_scope": "training_filters_before_argmax; unchanged_inference_topK_precedes_compatibility",
        "empty_actor_negative_domain": "differentiable_zero_on_valid_actor_logits; no_max_empty",
        "max_source_tokens": MAX_SOURCE_TOKENS, "source_length_policy": "reject_above128_without_truncation",
        "initialization_seed": initialization_seed, "batch_order_seed": batch_order_seed,
        "batch_order_seed_origin": "explicit", "batch_size": batch_size,
        "max_new_optimizer_steps": MAX_NEW_STEPS, "max_seconds": MAX_SECONDS,
        "latent_dimension": 384, "latent_enabled": False,
        "training_count": 168, "legacy_training_prefix_count": 96,
        "legacy_training_prefix_sha256": LEGACY96_SHA256,
        "promotion_gate": {"scope": "external_exposed_legacy96_engineering_diagnostic",
            "raw_exact_IR_required": 96, "joint_exact_IR_required": 96,
            "permission_to_obligation_errors_required": 0, "trainer_executes_promotion": False},
        "nested_loss_metadata_scope": "legacy_constructor_descriptor; this_outer_policy_defines_actual_training_objective"}


def _validate_policy(policy):
    _require(type(policy) is dict, "closed targeted-loss policy required")
    expected = _policy(policy.get("initialization_seed"),
        actor_ranking_enabled=policy.get("actor_ranking_enabled"),
        presence_ce_weight=policy.get("presence_ce_weight"),
        batch_order_seed=policy.get("batch_order_seed"), batch_size=policy.get("batch_size"))
    _require(_raw(policy) == _raw(expected), "targeted-loss policy differs from its closed contract")
    return copy.deepcopy(expected)


def _combine_main_loss(modality, facets, presence_means, presence_ce_weight):
    _require(type(presence_ce_weight) is int and presence_ce_weight in (1, 2), "integer presence weight1 or2 required")
    _require(type(facets) in (list, tuple) and len(facets) == 6, "exact six legacy facet means required")
    _require(type(presence_means) is dict and set(presence_means) == {"conditions", "exceptions"},
             "exact two separately recorded presence means required")
    if presence_ce_weight == 1:
        # Exactly the legacy modality2 expression: no zero add/multiply or
        # changed association, even when tensor arithmetic is not associative.
        return (2 * modality + sum(facets)) / 8
    return (2 * modality + sum(facets) + (presence_ce_weight - 1) *
            (presence_means["conditions"] + presence_means["exceptions"])) / 10


def _combine_total_loss(main, actor_hinge, actor_ranking_enabled):
    _require(type(actor_ranking_enabled) is bool, "explicit ranking switch required")
    return main + .25 * actor_hinge if actor_ranking_enabled else main


def _progress(progress):
    _require(type(progress) is dict and set(progress) == {
        "epochs_completed", "row_cursor", "optimizer_steps"}
        and all(type(v) is int and 0 <= v <= 10**9 for v in progress.values()),
        "closed nonnegative progress required")
    return dict(progress)


def _batch_indices(count, progress, batch_size, batch_order_seed):
    _require(type(count) is int and 1 <= count <= 4096, "bounded row count required")
    _require(type(batch_size) is int and 1 <= batch_size <= 32, "bounded batch size required")
    _require(type(batch_order_seed) is int and 0 <= batch_order_seed < 2**31,
             "bounded batch-order seed required")
    progress = _progress(progress)
    cursor = progress["row_cursor"]
    _require(cursor < count and cursor % batch_size == 0
        and progress["optimizer_steps"] == progress["epochs_completed"] * math.ceil(count / batch_size)
        + cursor // batch_size, "batch progress/cursor identity differs")
    order = list(range(count))
    random.Random(batch_order_seed + progress["epochs_completed"]).shuffle(order)
    return order[cursor:cursor + batch_size]


def _advance_progress(progress, indices_count, count):
    result = _progress(progress)
    _require(type(count) is int and 1 <= count <= 4096
        and type(indices_count) is int and 1 <= indices_count <= 32
        and result["row_cursor"] < count
        and result["row_cursor"] + indices_count <= count, "invalid completed batch size")
    result["optimizer_steps"] += 1
    result["row_cursor"] += indices_count
    if result["row_cursor"] == count:
        result["epochs_completed"] += 1
        result["row_cursor"] = 0
    return result


def _batch_trace_entry(indices, examples, before, after, *, loss, gradient_norm):
    _require(type(examples) in (list, tuple) and 1 <= len(examples) <= 4096,
             "bounded trace examples required")
    _require(type(indices) is list and 1 <= len(indices) <= 32
        and all(type(i) is int and 0 <= i < len(examples) for i in indices)
        and len(set(indices)) == len(indices), "unique contained batch indices required")
    _require(all(type(examples[i]) is dict for i in indices), "trace examples must be dictionaries")
    identifiers = [examples[i].get("id") for i in indices]
    _require(all(type(v) is str and 0 < len(v.strip()) <= 512 for v in identifiers)
        and len(set(identifiers)) == len(identifiers), "unique bounded batch IDs required")
    before, after = _progress(before), _progress(after)
    _require(after == _advance_progress(before, len(indices), len(examples)),
             "trace must follow one completed optimizer update")
    _require(after["optimizer_steps"] <= MAX_NEW_STEPS, "bounded curriculum update limit exceeded")
    _require(type(loss) in (int, float) and math.isfinite(loss) and loss >= 0
        and type(gradient_norm) in (int, float) and math.isfinite(gradient_norm)
        and gradient_norm >= 0, "finite trace loss and gradient norm required")
    return {"schema": "completed-curriculum-batch/v1", "indices": list(indices),
        "ids": identifiers, "pre_progress": before, "post_progress": after,
        "optimizer_step": after["optimizer_steps"], "loss": float(loss),
        "gradient_norm_before_clip": float(gradient_norm)}


def _trace_summary(entries, initial_progress, final_progress, policy, examples):
    policy = _validate_policy(policy)
    _require(type(entries) is list and len(entries) <= MAX_NEW_STEPS,
             "bounded completed trace required")
    _require(type(examples) in (list, tuple) and 1 <= len(examples) <= 4096,
             "bounded trace population required")
    _require(all(type(row) is dict for row in examples), "trace population must contain dictionaries")
    ids = [row.get("id") for row in examples]
    _require(all(type(v) is str and 0 < len(v.strip()) <= 512 for v in ids)
        and len(set(ids)) == len(ids), "unique bounded population IDs required")
    initial_progress, final_progress = _progress(initial_progress), _progress(final_progress)
    _batch_indices(len(examples), initial_progress, policy["batch_size"], policy["batch_order_seed"])
    _batch_indices(len(examples), final_progress, policy["batch_size"], policy["batch_order_seed"])
    cursor = dict(initial_progress)
    for entry in entries:
        _require(type(entry) is dict and entry.get("pre_progress") == cursor,
                 "completed trace progress chain differs")
        indices = _batch_indices(len(examples), cursor, policy["batch_size"], policy["batch_order_seed"])
        _require(entry.get("indices") == indices, "trace differs from the actual declared sampler")
        expected = _batch_trace_entry(indices, examples, cursor,
            _advance_progress(cursor, len(indices), len(examples)),
            loss=entry.get("loss"), gradient_norm=entry.get("gradient_norm_before_clip"))
        _require(_raw(entry) == _raw(expected), "closed trace index/ID/step evidence differs")
        cursor = expected["post_progress"]
    _require(cursor == final_progress
        and final_progress["optimizer_steps"] - initial_progress["optimizer_steps"] == len(entries)
        and final_progress["optimizer_steps"] <= MAX_NEW_STEPS,
        "trace must cover exactly the returned completed updates")
    indices, identifiers = [row["indices"] for row in entries], [row["ids"] for row in entries]
    return {"schema": "completed-curriculum-batch-trace/v1", "batches": copy.deepcopy(entries),
        "initial_progress": initial_progress, "final_progress": final_progress,
        "completed_updates": len(entries), "training_count": len(examples),
        "training_manifest_sha256": checkpoint_digest(examples),
        "batch_size": policy["batch_size"], "batch_order_seed": policy["batch_order_seed"],
        "batch_order_seed_origin": policy["batch_order_seed_origin"],
        "indices_sha256": checkpoint_digest(indices), "ids_sha256": checkpoint_digest(identifiers),
        "batches_sha256": checkpoint_digest(entries),
        "scope": "indices_and_IDs_used_by_this_trainer_recorded_after_returned_optimizer_step_and_finite_guards",
        "independent_runtime_trace": False, "unreturned_partial_updates_attested": False}



def _f32(value):
    _require(type(value) in (int, float) and math.isfinite(value), "finite float32 score required")
    try:
        result = struct.unpack("!f", struct.pack("!f", value))[0]
    except (OverflowError, struct.error) as error:
        raise ValueError("score overflows float32") from error
    _require(math.isfinite(result), "score overflows float32")
    return result


def _span_coordinates(value, token_count):
    _require(type(value) in (list, tuple) and len(value) == 2
        and all(type(i) is int for i in value)
        and 0 <= value[0] <= value[1] < token_count,
        "nonempty contained forward source-token span required")
    return tuple(value)


def _actor_domain(token_count, gold, other_spans):
    """Complete row-major compatible wrong domain; target-dependent training."""
    _require(type(token_count) is int and 1 <= token_count <= MAX_SOURCE_TOKENS,
             "one to128 source tokens required; truncation forbidden")
    gold = _span_coordinates(gold, token_count)
    _require(type(other_spans) is dict and set(other_spans) <= set(SPAN_FIELDS[1:]),
             "contained active gold nonactor facets required")
    others = {f: _span_coordinates(v, token_count) for f, v in other_spans.items()}
    all_spans = [gold, *others.values()]
    _require(all(right < next_left or next_right < left
        for index, (left, right) in enumerate(all_spans)
        for next_left, next_right in all_spans[index + 1:]), "gold copied facets overlap")
    return [(left, right) for left in range(token_count) for right in range(left, token_count)
        if (left, right) != gold and all(right < a or b < left for a, b in others.values())]


def _actor_record(record):
    _require(type(record) is dict and {"tokens", "labels", "id", "source_text"} <= set(record),
             "authenticated source record required")
    _require(type(record["id"]) is str and 0 < len(record["id"].strip()) <= 512,
             "bounded record ID required")
    tokens = record["tokens"]
    _require(type(tokens) is list and 1 <= len(tokens) <= MAX_SOURCE_TOKENS
        and tokens == span.tokenize_source(record["source_text"]), "complete exact source tokenization required")
    labels = record["labels"]
    _require(type(labels) is dict and set(labels) == {"modality", "spans", "presence"}
        and type(labels["modality"]) is int and labels["modality"] in (0, 1, 2)
        and type(labels["spans"]) in (list, tuple) and len(labels["spans"]) == 6
        and type(labels["presence"]) in (list, tuple) and len(labels["presence"]) == 6
        and all(type(v) is bool for v in labels["presence"]), "closed six-field source labels required")
    _require(labels["presence"][0] and labels["presence"][1], "actor/action cannot be absent")
    active = {}
    for field, present, coordinates in zip(SPAN_FIELDS, labels["presence"], labels["spans"], strict=True):
        if present:
            active[field] = _span_coordinates(coordinates, len(tokens))
        else:
            _require(field in SPAN_FIELDS[2:] and type(coordinates) in (list, tuple)
                and len(coordinates) == 2 and all(type(v) is int for v in coordinates)
                and tuple(coordinates) == (-100, -100), "absent optional pointers require exact -100 labels")
    domain = _actor_domain(len(tokens), active["actor"], {f: v for f, v in active.items() if f != "actor"})
    return len(tokens), active["actor"], {f: v for f, v in active.items() if f != "actor"}, domain


def _bounded_splits(training_examples, tuning_examples):
    _require(type(training_examples) in (list, tuple) and len(training_examples) == 168
        and checkpoint_digest(training_examples[:96]) == LEGACY96_SHA256,
        "168 mixed rows with byte-equivalent unchanged legacy96 declarations required")
    records, tuning = span._splits(training_examples, tuning_examples, 384)
    for examples, prepared in ((training_examples, records), (tuning_examples, tuning)):
        for example, record in zip(examples, prepared, strict=True):
            record.update(id=example["id"], source_text=example["source_text"])
            _actor_record(record)
    return records, tuning


def _choose_actor_wrong(starts, ends, token_count, gold, other_spans):
    """Only detached finite-score argmax; never a differentiable score."""
    domain = _actor_domain(token_count, gold, other_spans)
    _require(type(starts) is list and type(ends) is list and len(starts) == len(ends)
        and token_count <= len(starts) <= MAX_SOURCE_TOKENS,
        "bounded full actor score width required")
    for value in (*starts[:token_count], *ends[:token_count]):
        _require(type(value) is float and _f32(value) == value, "exact saved float32 actor logits required")
    gold_score = _f32(starts[gold[0]] + ends[gold[1]])
    ranked = [(_f32(starts[left] + ends[right]), left, right) for left, right in domain]
    # Exact score ties choose the earliest row-major source boundary pair.
    best = min(ranked, key=lambda row: (-row[0], row[1], row[2])) if ranked else None
    return {"token_count": token_count, "padded_score_width": len(starts),
        "full_valid_boundary_span_count": token_count * (token_count + 1) // 2,
        "compatible_wrong_candidate_count": len(domain),
        "compatible_wrong_domain_sha256": checkpoint_digest(domain),
        "gold_coordinates": list(gold), "gold_score_float32": gold_score,
        "chosen_wrong_coordinates": [best[1], best[2]] if best else None,
        "chosen_wrong_score_float32": best[0] if best else None,
        "chosen_wrong_tie_count": sum(row[0] == best[0] for row in ranked) if best else 0,
        "present_gold_nonactor_coordinates": {f: list(v) for f, v in other_spans.items()},
        "argmax_detached": True, "full_compatible_domain_traversed": True,
        "padding_reversed_exactgold_and_othergold_overlap_excluded": True}


def _actor_auxiliary(torch, output, records, enabled):
    _require(type(enabled) is bool and type(records) in (list, tuple) and 1 <= len(records) <= 12,
             "bounded actor auxiliary batch required")
    losses, rows = [], []
    for position, record in enumerate(records):
        count, gold, others, domain = _actor_record(record)
        start, end = output["start"][position, 0], output["end"][position, 0]
        _require(start.dtype == end.dtype == torch.float32 and start.device.type == end.device.type == "cpu"
            and tuple(start.shape) == tuple(end.shape) and len(start.shape) == 1
            and count <= start.shape[0] <= MAX_SOURCE_TOKENS, "bounded CPU float32 actor score width required")
        selected, wrong_value, ties = None, None, 0
        if domain:
            left = torch.tensor([v[0] for v in domain], dtype=torch.long)
            right = torch.tensor([v[1] for v in domain], dtype=torch.long)
            # Complete finite coordinate domain, one vectorized gather/sum. No
            # per-candidate tensor-to-Python calls or differentiable argmax.
            detached_wrong = start.detach()[left] + end.detach()[right]
            index = int(torch.argmax(detached_wrong).item())
            selected = list(domain[index])
            wrong_value = float(detached_wrong[index])
            ties = int((detached_wrong == detached_wrong[index]).sum().item())
        gold_score = start[gold[0]] + end[gold[1]]
        decision = {"token_count": count, "padded_score_width": start.shape[0],
            "full_valid_boundary_span_count": count * (count + 1) // 2,
            "compatible_wrong_candidate_count": len(domain),
            "compatible_wrong_domain_sha256": checkpoint_digest(domain),
            "gold_coordinates": list(gold), "gold_score_float32": float(gold_score.detach()),
            "chosen_wrong_coordinates": selected, "chosen_wrong_score_float32": wrong_value,
            "chosen_wrong_tie_count": ties,
            "present_gold_nonactor_coordinates": {f: list(v) for f, v in others.items()},
            "argmax_detached": True, "full_compatible_domain_traversed": True,
            "padding_reversed_exactgold_and_othergold_overlap_excluded": True,
            "selection_implementation": "vectorized_detached_source_boundary_gather"}
        if selected is None:
            hinge = (start[:count].sum() + end[:count].sum()) * 0
        else:
            # Only the choice used detached values. Both chosen wrong logits and
            # gold logits retain their graph, including cancellation when shared.
            wrong_score = start[selected[0]] + end[selected[1]]
            hinge = torch.nn.functional.relu(1. + wrong_score - gold_score)
        hinge_value = float(hinge.detach())
        _require(math.isfinite(hinge_value) and hinge_value >= 0, "finite actor hinge required")
        rows.append({**decision, "row_position": position, "id": record["id"],
            "source_sha256": hashlib.sha256(record["source_text"].encode()).hexdigest(),
            "actor_hinge_value": hinge_value, "hinge_active": hinge_value > 0,
            "gradient_enabled_by_policy": enabled,
            "zero_domain_differentiable_zero": selected is None,
            "teacher_forced_compatibility": True, "semantic_compatibility_verified": False})
        losses.append(hinge)
    return torch.stack(losses).mean(), rows


def _validate_objective_diagnostics(value):
    _require(type(value) is dict and set(value) == {"schema", "main_loss", "actor_hinge_mean",
        "actor_hinge_applied", "actor_hinge_coefficient", "total_loss", "presence_CE_means", "rows",
        "teacher_forcing", "evaluation_references_used", "semantic_compatibility_verified"}
        and value["schema"] == "targeted-source-span-objective-diagnostics/v1"
        and value["actor_hinge_coefficient"] == .25 and type(value["actor_hinge_applied"]) is bool
        and value["teacher_forcing"] is True and value["evaluation_references_used"] is False
        and value["semantic_compatibility_verified"] is False, "closed target-dependent objective diagnostics required")
    _require(type(value["rows"]) is list and 1 <= len(value["rows"]) <= 12,
             "bounded objective row diagnostics required")
    _require(type(value["presence_CE_means"]) is dict
        and set(value["presence_CE_means"]) == {"conditions", "exceptions"}, "two presence diagnostics required")
    numbers = [value[k] for k in ("main_loss", "actor_hinge_mean", "total_loss")]
    numbers.extend(value["presence_CE_means"].values())
    _require(all(type(v) is float and math.isfinite(v) and v >= 0 and _f32(v) == v for v in numbers),
             "finite exact float32 objective means required")
    for index, row in enumerate(value["rows"]):
        _require(type(row) is dict and set(row) == {"token_count", "padded_score_width",
            "full_valid_boundary_span_count", "compatible_wrong_candidate_count",
            "compatible_wrong_domain_sha256", "gold_coordinates", "gold_score_float32",
            "chosen_wrong_coordinates", "chosen_wrong_score_float32", "chosen_wrong_tie_count",
            "present_gold_nonactor_coordinates", "argmax_detached", "full_compatible_domain_traversed",
            "padding_reversed_exactgold_and_othergold_overlap_excluded", "selection_implementation",
            "row_position", "id", "source_sha256", "actor_hinge_value", "hinge_active",
            "gradient_enabled_by_policy", "zero_domain_differentiable_zero",
            "teacher_forced_compatibility", "semantic_compatibility_verified"},
            "closed objective row required")
        _require(type(row["id"]) is str and 0 < len(row["id"].strip()) <= 512
            and type(row["source_sha256"]) is str and span._SHA.fullmatch(row["source_sha256"])
            and row["row_position"] == index and type(row["token_count"]) is int
            and 1 <= row["token_count"] <= MAX_SOURCE_TOKENS
            and type(row["padded_score_width"]) is int
            and row["token_count"] <= row["padded_score_width"] <= MAX_SOURCE_TOKENS
            and row["full_valid_boundary_span_count"] == row["token_count"] * (row["token_count"] + 1) // 2
            and type(row["compatible_wrong_candidate_count"]) is int
            and 0 <= row["compatible_wrong_candidate_count"] < row["full_valid_boundary_span_count"]
            and row["argmax_detached"] is True and row["full_compatible_domain_traversed"] is True
            and row["padding_reversed_exactgold_and_othergold_overlap_excluded"] is True
            and row["selection_implementation"] == "vectorized_detached_source_boundary_gather"
            and row["teacher_forced_compatibility"] is True and row["semantic_compatibility_verified"] is False
            and type(row["actor_hinge_value"]) in (int, float) and math.isfinite(row["actor_hinge_value"])
            and row["actor_hinge_value"] >= 0 and row["hinge_active"] is (row["actor_hinge_value"] > 0)
            and row["gradient_enabled_by_policy"] is value["actor_hinge_applied"], "objective candidate/hinge diagnostics differ")
        _require((row["chosen_wrong_coordinates"] is None) is (row["compatible_wrong_candidate_count"] == 0)
            and row["zero_domain_differentiable_zero"] is (row["compatible_wrong_candidate_count"] == 0), "zero-domain diagnostic differs")
        domain = _actor_domain(row["token_count"], row["gold_coordinates"], row["present_gold_nonactor_coordinates"])
        _require(len(domain) == row["compatible_wrong_candidate_count"]
            and checkpoint_digest(domain) == row["compatible_wrong_domain_sha256"], "full objective candidate-domain hash/count differs")
        _require(type(row["gold_score_float32"]) is float and _f32(row["gold_score_float32"]) == row["gold_score_float32"],
                 "finite exact gold float32 score required")
        if domain:
            _require(tuple(row["chosen_wrong_coordinates"]) in domain
                and type(row["chosen_wrong_tie_count"]) is int and 1 <= row["chosen_wrong_tie_count"] <= len(domain)
                and type(row["chosen_wrong_score_float32"]) is float
                and _f32(row["chosen_wrong_score_float32"]) == row["chosen_wrong_score_float32"],
                "finite contained chosen wrong span required")
            expected_hinge = max(0., _f32(_f32(1. + row["chosen_wrong_score_float32"]) - row["gold_score_float32"]))
        else:
            _require(row["chosen_wrong_score_float32"] is None and row["chosen_wrong_tie_count"] == 0,
                     "empty domain cannot report a wrong score")
            expected_hinge = 0.
        _require(row["actor_hinge_value"] == expected_hinge, "reported float32 hinge arithmetic differs")
    # Every hinge is nonnegative. An arbitrary float32 reduction of n<=12
    # values uses at most n-1 additions and one division. gamma_(n+1) leaves an
    # extra rounding allowance versus math.fsum's float64 reference. The one
    # smallest-subnormal absolute allowance covers gradual underflow rounding.
    count = len(value["rows"])
    reference_mean = math.fsum(row["actor_hinge_value"] for row in value["rows"]) / count
    unit_roundoff = 2. ** -24
    gamma = (count + 1) * unit_roundoff / (1. - (count + 1) * unit_roundoff)
    tolerance = gamma * reference_mean + 2. ** -149
    _require(abs(value["actor_hinge_mean"] - reference_mean) <= tolerance,
             "batch actor hinge mean differs from row scalars beyond float32 reduction bound")
    expected_total = (_f32(value["main_loss"] + _f32(.25 * value["actor_hinge_mean"]))
                      if value["actor_hinge_applied"] else value["main_loss"])
    _require(value["total_loss"] == expected_total, "main/actor contribution float32 association differs")
    return copy.deepcopy(value)


def _objective_trace_entry(indices, examples, optimizer_step, diagnostics):
    diagnostics = _validate_objective_diagnostics(diagnostics)
    _require(type(indices) is list and len(indices) == len(diagnostics["rows"])
        and all(type(i) is int and 0 <= i < len(examples) for i in indices)
        and len(set(indices)) == len(indices) and type(optimizer_step) is int
        and 1 <= optimizer_step <= MAX_NEW_STEPS, "completed bounded objective update required")
    ids = [examples[i]["id"] for i in indices]
    _require(ids == [row["id"] for row in diagnostics["rows"]]
        and [hashlib.sha256(examples[i]["source_text"].encode()).hexdigest() for i in indices]
        == [row["source_sha256"] for row in diagnostics["rows"]], "objective trace actual source/ID join differs")
    return {"schema": "completed-targeted-objective-batch/v1", "optimizer_step": optimizer_step,
        "indices": list(indices), "ids": ids, "diagnostics": diagnostics}


def _objective_trace_summary(entries, batches, policy):
    policy = _validate_policy(policy)
    _require(type(entries) is list and type(batches) is list and len(entries) == len(batches)
        and len(entries) <= MAX_NEW_STEPS, "objective trace must cover exactly returned updates")
    for entry, batch in zip(entries, batches, strict=True):
        _require(set(entry) == {"schema", "optimizer_step", "indices", "ids", "diagnostics"}
            and entry["schema"] == "completed-targeted-objective-batch/v1"
            and all(entry[k] == batch[k] for k in ("optimizer_step", "indices", "ids")),
            "objective/completed-batch trace chain differs")
        diagnostics = _validate_objective_diagnostics(entry["diagnostics"])
        _require(diagnostics["actor_hinge_applied"] is policy["actor_ranking_enabled"]
            and entry["ids"] == [row["id"] for row in diagnostics["rows"]]
            and diagnostics["total_loss"] == batch["loss"], "objective trace policy/ID/loss join differs")
    return {"schema": "completed-targeted-objective-trace/v1", "batches": copy.deepcopy(entries),
        "completed_updates": len(entries), "batches_sha256": checkpoint_digest(entries),
        "training_policy_sha256": checkpoint_digest(policy),
        "scope": "teacher_forced_training_objective_recorded_only_after_returned_finite_optimizer_step",
        "independent_numerical_kernel_trace": False, "evaluation_references_used": False}


def _capture_implementation():
    return {"targeted_loss_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "continuation": continuation._implementation(), "span": span._implementation()}


_IMPLEMENTATION_AT_IMPORT = _capture_implementation()


def _implementation():
    current = _capture_implementation()
    _require(current == _IMPLEMENTATION_AT_IMPORT, "curriculum source changed since import")
    return current


def _initial_continuation(child):
    initial = copy.deepcopy(child)
    initial["base_checkpoint"] = continuation._initial_base(
        child["base_checkpoint"], child["source_parent_checkpoint"])
    initial["parent_checkpoint_sha256"] = None
    return initial


def build_checkpoint(parent, training_examples, tuning_examples=(), *, context_contract,
                     actor_ranking_enabled=False, presence_ce_weight=1,
                     batch_order_seed=1729, seed=1729, learning_rate=.001,
                     batch_size=12, latent_enabled=False):
    """Fork only the exact authenticated400-step parent into fresh Adam."""
    policy = _policy(seed, actor_ranking_enabled=actor_ranking_enabled,
        presence_ce_weight=presence_ce_weight, batch_order_seed=batch_order_seed, batch_size=batch_size)
    _require(latent_enabled is False and type(learning_rate) in (int, float) and learning_rate == .001,
             "fixed disabled384/.001 recipe required")
    _require(type(parent) is dict and checkpoint_digest(parent) == SOURCE_PARENT_SHA256,
             "exact source-span400 parent hash required")
    _require(checkpoint_digest(parent.get("model_state")) == SOURCE_MODEL_SHA256
        and parent.get("progress") == dict(epochs_completed=4, row_cursor=192, optimizer_steps=400)
        and parent.get("config", {}).get("seed") == 1729
        and parent.get("config", {}).get("latent_dimension") == 384
        and parent.get("config", {}).get("latent_enabled") is False, "exact parent400 source-only provenance required")
    _bounded_splits(training_examples, tuning_examples)
    child = continuation.build_checkpoint(parent, training_examples, tuning_examples,
        context_contract=context_contract, seed=seed, learning_rate=learning_rate,
        batch_size=batch_size, latent_enabled=False)
    result = {"schema": SCHEMA, "lineage_id": LINEAGE_ID, "implementation": _implementation(),
        "training_policy": policy, "training_policy_sha256": checkpoint_digest(policy),
        "initial_training_policy_sha256": checkpoint_digest(policy),
        "initial_continuation_checkpoint_sha256": checkpoint_digest(child),
        "source_parent_checkpoint_sha256": child["source_parent_checkpoint_sha256"],
        "source_parent_model_state_sha256": child["initial_model_state_sha256"],
        "continuation_checkpoint": child, "parent_checkpoint_sha256": None, **FALSE}
    result["initial_targeted_checkpoint_sha256"] = checkpoint_digest(result)
    _require(len(_raw(result)) <= MAX_BYTES, "targeted checkpoint exceeds byte bound")
    return result


def _validated(checkpoint):
    fields = {"schema", "lineage_id", "implementation", "training_policy",
        "training_policy_sha256", "initial_training_policy_sha256",
        "initial_targeted_checkpoint_sha256", "initial_continuation_checkpoint_sha256",
        "source_parent_checkpoint_sha256", "source_parent_model_state_sha256",
        "continuation_checkpoint", "parent_checkpoint_sha256", *FALSE}
    _require(type(checkpoint) is dict and set(checkpoint) == fields,
             "closed curriculum checkpoint required; vanilla warm checkpoints are refused")
    _require(checkpoint["schema"] == SCHEMA and checkpoint["lineage_id"] == LINEAGE_ID
        and all(checkpoint[key] is False for key in FALSE), "curriculum schema/authority differs")
    _require(len(_raw(checkpoint)) <= MAX_BYTES, "curriculum checkpoint exceeds byte bound")
    _require(checkpoint["implementation"] == _implementation(), "curriculum producer closure differs")
    policy = _validate_policy(checkpoint["training_policy"])
    _require(checkpoint["training_policy_sha256"] == checkpoint_digest(policy), "curriculum policy hash differs")
    _require(checkpoint["initial_training_policy_sha256"] == checkpoint["training_policy_sha256"],
             "resume must preserve the original objective and batch-order policy")
    child = checkpoint["continuation_checkpoint"]
    base = continuation._validated(child)
    _require(child["source_parent_checkpoint_sha256"] == SOURCE_PARENT_SHA256
        and child["initial_model_state_sha256"] == SOURCE_MODEL_SHA256
        and child["source_parent_optimizer_steps"] == 400, "exact retained parent400 required")
    _require(base["config"]["seed"] == policy["initialization_seed"]
        and base["config"]["batch_size"] == policy["batch_size"]
        and base["config"]["latent_dimension"] == 384
        and base["config"]["latent_enabled"] is False and base["config"]["learning_rate"] == .001
        and base["training_count"] == 168, "legacy constructor/policy differs")
    _require(base["progress"]["optimizer_steps"] <= MAX_NEW_STEPS,
             "curriculum lineage exceeds its32 new-update bound")
    _require(checkpoint["source_parent_checkpoint_sha256"] == child["source_parent_checkpoint_sha256"]
        and checkpoint["source_parent_model_state_sha256"] == child["initial_model_state_sha256"],
        "exact unchanged source-parent provenance differs")
    initial = _initial_continuation(child)
    _require(checkpoint["initial_continuation_checkpoint_sha256"] == checkpoint_digest(initial),
             "fresh copied-weight/Adam boundary differs")
    origin = copy.deepcopy(checkpoint)
    origin["continuation_checkpoint"] = initial
    origin["parent_checkpoint_sha256"] = None
    origin.pop("initial_targeted_checkpoint_sha256")
    _require(checkpoint["initial_targeted_checkpoint_sha256"] == checkpoint_digest(origin),
             "initial curriculum policy/provenance boundary differs")
    previous = checkpoint["parent_checkpoint_sha256"]
    _require(previous is None or type(previous) is str and span._SHA.fullmatch(previous),
             "invalid previous curriculum checkpoint hash")
    if base["progress"]["optimizer_steps"]:
        _require(previous is not None, "trained curriculum requires previous outer hash")
    return base, child, policy


def validate_checkpoint(checkpoint):
    _validated(checkpoint)


def _loss(torch, model, records, policy):
    policy = _validate_policy(policy)
    output = model(*span._batch(torch, records))
    _require(all(bool(torch.isfinite(value).all()) for value in output.values()), "nonfinite targeted heads")
    labels = [row["labels"] for row in records]
    modality = torch.nn.functional.cross_entropy(output["modality"], torch.tensor([x["modality"] for x in labels]))
    facets, presence_means = [], {}
    for index, field in enumerate(SPAN_FIELDS):
        present = torch.tensor([x["presence"][index] for x in labels], dtype=torch.bool)
        start = torch.tensor([x["spans"][index][0] for x in labels], dtype=torch.long)
        end = torch.tensor([x["spans"][index][1] for x in labels], dtype=torch.long)
        pointer = (torch.nn.functional.cross_entropy(output["start"][:, index], start,
                    ignore_index=-100, reduction="none") +
                   torch.nn.functional.cross_entropy(output["end"][:, index], end,
                    ignore_index=-100, reduction="none")) * .5
        if field in span.OPTIONAL_FIELDS:
            presence = torch.nn.functional.cross_entropy(output["presence"][:, span.OPTIONAL_FIELDS.index(field)],
                         present.to(torch.long), reduction="none")
            facets.append((presence + pointer).mean())
            if field in ("conditions", "exceptions"):
                presence_means[field] = presence.mean()
        else:
            facets.append(pointer.mean())
    main = _combine_main_loss(modality, facets, presence_means, policy["presence_ce_weight"])
    actor_hinge, actor_rows = _actor_auxiliary(torch, output, records, policy["actor_ranking_enabled"])
    total = _combine_total_loss(main, actor_hinge, policy["actor_ranking_enabled"])
    diagnostics = {"schema": "targeted-source-span-objective-diagnostics/v1",
        "main_loss": float(main.detach()), "actor_hinge_mean": float(actor_hinge.detach()),
        "actor_hinge_applied": policy["actor_ranking_enabled"],
        "actor_hinge_coefficient": .25, "total_loss": float(total.detach()),
        "presence_CE_means": {f: float(v.detach()) for f, v in presence_means.items()},
        "rows": actor_rows, "teacher_forcing": True, "evaluation_references_used": False,
        "semantic_compatibility_verified": False}
    _validate_objective_diagnostics(diagnostics)
    return total, diagnostics


def train_decoder(checkpoint, training_examples, tuning_examples=(), *, max_steps=32, max_seconds=32):
    """Own the weighted update loop and record each returned completed batch."""
    _require(type(max_steps) is int and 0 <= max_steps <= MAX_NEW_STEPS,
             "max_steps must be integer0..32")
    _require(type(max_seconds) in (int, float) and math.isfinite(max_seconds)
        and 0 <= max_seconds <= MAX_SECONDS, "max_seconds must be in0..32")
    started = time.monotonic()
    deadline = started + max_seconds
    base, child, policy = _validated(checkpoint)
    _require(base["progress"]["optimizer_steps"] + max_steps <= MAX_NEW_STEPS,
             "resumption must stay within32 total new updates")
    _require(base["training_manifest_sha256"] == checkpoint_digest(training_examples)
        and base["tuning_manifest_sha256"] == checkpoint_digest(tuning_examples), "resume manifests differ")
    records, tuning = _bounded_splits(training_examples, tuning_examples)
    torch, model, optimizer = span._restore(base)
    progress = dict(base["progress"])
    initial_progress = dict(progress)
    losses, batches, objective_entries, maximum_gradient, reason = [], [], [], 0., "step_limit"
    for _ in range(max_steps):
        if time.monotonic() >= deadline:
            reason = "deadline_before_batch"
            break
        before = dict(progress)
        indices = _batch_indices(len(records), before, policy["batch_size"], policy["batch_order_seed"])
        model.train()
        optimizer.zero_grad(set_to_none=True)
        loss, objective = _loss(torch, model, [records[index] for index in indices], policy)
        _require(bool(torch.isfinite(loss)), "nonfinite training loss")
        loss.backward()
        parameters = list(model.parameters())
        _require(all(parameter.grad is not None and bool(torch.isfinite(parameter.grad).all()) for parameter in parameters),
                 "missing or nonfinite gradients")
        gradient = float(torch.nn.utils.clip_grad_norm_(parameters, 5, error_if_nonfinite=True))
        maximum_gradient = max(maximum_gradient, gradient)
        optimizer.step()
        _require(all(bool(torch.isfinite(parameter).all()) for parameter in parameters), "nonfinite updated weights")
        _require(all(bool(torch.isfinite(value).all()) for moment in optimizer.state.values()
            for value in moment.values() if torch.is_tensor(value)), "nonfinite optimizer moments")
        progress = _advance_progress(before, len(indices), len(records))
        scalar_loss = float(loss.detach())
        losses.append(scalar_loss)
        batches.append(_batch_trace_entry(indices, training_examples, before, progress,
            loss=scalar_loss, gradient_norm=gradient))
        objective_entries.append(_objective_trace_entry(indices, training_examples, progress["optimizer_steps"], objective))
    model.eval()
    total, measured = 0., 0
    with torch.no_grad():
        for start in range(0, len(tuning), policy["batch_size"]):
            if time.monotonic() >= deadline:
                break
            batch = tuning[start:start + policy["batch_size"]]
            loss, _ = _loss(torch, model, batch, policy)
            _require(bool(torch.isfinite(loss)), "nonfinite tuning loss")
            total += float(loss) * len(batch)
            measured += len(batch)
    weights, moments = span._pack(model, optimizer)
    updated_base = {**copy.deepcopy(base), "model_state": weights, "optimizer_state": moments,
        "progress": progress, "parent_checkpoint_sha256": checkpoint_digest(base)}
    updated_child = {**copy.deepcopy(child), "base_checkpoint": updated_base,
        "parent_checkpoint_sha256": checkpoint_digest(child)}
    updated = {**copy.deepcopy(checkpoint), "continuation_checkpoint": updated_child,
        "parent_checkpoint_sha256": checkpoint_digest(checkpoint)}
    _require(_implementation() == checkpoint["implementation"], "curriculum source changed during training")
    _require(updated["training_policy"] == policy
        and updated_child["source_parent_checkpoint_sha256"] == checkpoint["source_parent_checkpoint_sha256"],
        "policy or source-parent provenance changed during training")
    _require(len(_raw(updated)) <= MAX_BYTES, "curriculum checkpoint exceeds byte bound")
    trace = _trace_summary(batches, initial_progress, progress, policy, training_examples)
    objective_trace = _objective_trace_summary(objective_entries, batches, policy)
    report = {"schema": "bounded-targeted-loss-span-legal-formula-training/v1",
        "checkpoint_sha256": checkpoint_digest(updated),
        "continuation_checkpoint_sha256": checkpoint_digest(updated_child),
        "base_checkpoint_sha256": checkpoint_digest(updated_base),
        "previous_targeted_checkpoint_sha256": checkpoint_digest(checkpoint),
        "source_parent_checkpoint_sha256": checkpoint["source_parent_checkpoint_sha256"],
        "source_parent_model_state_sha256": checkpoint["source_parent_model_state_sha256"],
        "training_policy": copy.deepcopy(policy), "training_policy_sha256": checkpoint_digest(policy),
        "initial_targeted_checkpoint_sha256": checkpoint["initial_targeted_checkpoint_sha256"],
        "optimizer_steps": len(losses), "continuation_optimizer_steps_total": progress["optimizer_steps"],
        "training_executed": bool(losses), "batch_losses": losses, "batch_trace": trace,
        "objective_trace": objective_trace,
        "gradient_norm_max": maximum_gradient,
        "changed_parameter_names": [key for key in weights if weights[key] != base["model_state"][key]],
        "stopped_reason": reason, "elapsed_seconds": time.monotonic() - started,
        "deadline_scope": "soft_boundary_before_numeric_batch; initialization_and_serialization_not_interruptible",
        "partial_failure_scope": "only_successfully_returned_prefix_traced; exceptions_can_leave_unreturned_partial_updates_unknown",
        "tuning": {"objective_loss": total / measured if measured else None, "rows_evaluated": measured,
            "complete": measured == len(tuning), "teacher_forcing": True, "used_for_fit_or_selection": False,
            "objective_policy_sha256": checkpoint_digest(policy)}, **FALSE}
    return {"checkpoint": updated, "report": report}


class SpanTargetedLossDecoder:
    """Target-free inference preserves the authoritative curriculum wrapper."""
    def __init__(self, checkpoint):
        _, child, policy = _validated(checkpoint)
        self._checkpoint = copy.deepcopy(checkpoint)
        self.checkpoint_sha256 = checkpoint_digest(checkpoint)
        self._policy = policy
        self._decoder = continuation.SpanContinuationDecoder(child)

    @property
    def checkpoint(self):
        return copy.deepcopy(self._checkpoint)

    @property
    def continuation_checkpoint(self):
        return copy.deepcopy(self._checkpoint["continuation_checkpoint"])

    @property
    def model(self):
        return self._decoder.model

    def decode_formal_logic(self, texts, latents, *, latent_ablation="none"):
        _require(_implementation() == self._checkpoint["implementation"], "targeted inference producer changed")
        _require(type(texts) in (list, tuple) and 1 <= len(texts) <= 128
            and all(len(span.tokenize_source(text)) <= MAX_SOURCE_TOKENS for text in texts),
            "targeted decoder refuses sources above128 tokens")
        report = self._decoder.decode_formal_logic(texts, latents, latent_ablation=latent_ablation)
        return {**report, "schema": "bounded-targeted-loss-span-legal-formula-inference/v1",
            "lineage_id": LINEAGE_ID, "checkpoint_sha256": self.checkpoint_sha256,
            "continuation_checkpoint_sha256": report["checkpoint_sha256"],
            "training_policy": copy.deepcopy(self._policy),
            "training_policy_sha256": self._checkpoint["training_policy_sha256"]}


def save_checkpoint(checkpoint, path):
    """Exclusively save the new authoritative outer schema, never vanilla warm."""
    _validated(checkpoint)
    raw = _raw(checkpoint)
    path = Path(path).absolute()
    _require(path.parent.resolve(strict=True) == path.parent, "canonical existing checkpoint parent required")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "schema": SCHEMA}


def load_checkpoint(path, *, expected_sha256):
    _require(type(expected_sha256) is str and span._SHA.fullmatch(expected_sha256), "expected checkpoint hash required")
    path = Path(path).absolute()
    _require(path.resolve(strict=True) == path, "canonical checkpoint path required")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        _require(stat.S_ISREG(before.st_mode) and before.st_size <= MAX_BYTES, "bounded regular checkpoint required")
        raw = stream.read(MAX_BYTES + 1)
        after = os.fstat(stream.fileno())
    _require(len(raw) <= MAX_BYTES and (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), "checkpoint changed while reading")
    _require(hashlib.sha256(raw).hexdigest() == expected_sha256, "checkpoint hash differs")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate checkpoint JSON key")
            result[key] = value
        return result
    def reject(value):
        raise ValueError("invalid JSON constant: " + value)
    checkpoint = json.loads(raw, object_pairs_hook=unique, parse_constant=reject)
    _validated(checkpoint)
    return checkpoint
