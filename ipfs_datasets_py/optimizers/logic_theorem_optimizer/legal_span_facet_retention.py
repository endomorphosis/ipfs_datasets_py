"""Matched facet-preservation training from exact frozen Consistency weights.

The two arms share model, inference, paired CE/JS, curriculum and sampler.
Only the retention arm adds detached correct-teacher qualifier preservation and
a differentiable overlap penalty. Teacher gating uses training labels only.
Authored supervision is not independently verified statutory meaning.
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
import time
from types import MappingProxyType

from . import legal_span_mixed_replay as mixed
from . import legal_span_consistency as previous

span = mixed.span
_require, _raw, checkpoint_digest = span._require, span._raw, span.checkpoint_digest
FALSE = span.FALSE
SCHEMA = "facet-retention-span-checkpoint/v1"
LINEAGE_ID = "facet_retention_span_v1"
MAX_BYTES = mixed.MAX_BYTES
POOLS = ("earlier", "historical_new", "pairs")
PAIR_POSITIONS = ((6, 7), (8, 9), (10, 11))
ROLE_NAMES = (*span.SPAN_FIELDS, "trigger", "other")


def _capture_implementation():
    return {"facet_retention_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "frozen_consistency": previous._implementation()}


_IMPLEMENTATION_AT_IMPORT = _capture_implementation()


def _implementation():
    value = _capture_implementation()
    _require(value == _IMPLEMENTATION_AT_IMPORT, "facet retention implementation source drift")
    return value


def _training_config(objective, seed, learning_rate=.001, batch_size=12):
    _require(objective in ("base", "facet_retention"), "known matched training objective required")
    config = previous._training_config("consistency", seed, learning_rate, batch_size)
    return {**config, "objective": objective, "optimizer_step_budget": 800,
        "teacher_weight": .5 if objective == "facet_retention" else 0.,
        "overlap_weight": .1 if objective == "facet_retention" else 0.,
        "teacher_profile": "frozen_parent_train_only_correct_optional_presence_and_present_qualifier_endpoints/v1",
        "teacher_historical_batch_positions": list(range(6)),
        "overlap_profile": "mean_overlap_probability_gold_present_facets_conditional_valid_spans/v1",
        "initialization": "copy_all_consistency_parent_weights_fresh_adam/v1"}


_pairs_and_pools = previous._pairs_and_pools
_progress = previous._progress
next_batch_indices = previous.next_batch_indices


def _valid_span_scores(torch, start, end):
    _require(start.ndim == end.ndim == 1 and start.shape == end.shape and start.numel() > 0,
        "equal nonempty endpoint vectors required")
    count = start.numel()
    mask = torch.ones((count, count), dtype=torch.bool, device=start.device).triu()
    scores = (start[:, None] + end[None, :]).masked_fill(~mask, float('-inf'))
    return scores


def _valid_span_distribution(torch, start, end):
    """Normalize over the complete nonempty start<=end span space."""
    scores = _valid_span_scores(torch, start, end)
    return scores.reshape(-1).softmax(-1).reshape(scores.shape)


def _teacher_loss(torch, output, teacher_output, records, historical_positions=tuple(range(6))):
    """Detached parent KL only where historical training labels confirm its decision."""
    zero = output['modality'].sum() * 0
    presence_terms, endpoint_terms = [], []
    for index in historical_positions:
        record = records[index]
        count = len(record['tokens'])
        for optional, field in enumerate(span.OPTIONAL_FIELDS):
            facet = span.SPAN_FIELDS.index(field)
            gold_present = record['labels']['presence'][facet]
            teacher_presence = teacher_output['presence'][index, optional].detach()
            agrees = (int(teacher_presence.argmax()) == int(gold_present)
                and float(abs(teacher_presence[1] - teacher_presence[0])) > 1e-7)
            if not agrees:
                continue
            presence_terms.append(torch.nn.functional.kl_div(output['presence'][index, optional].log_softmax(-1),
                teacher_presence.softmax(-1), reduction='sum'))
            if field not in ('conditions', 'exceptions', 'temporal') or not gold_present:
                continue
            start = teacher_output['start'][index, facet, :count].detach()
            end = teacher_output['end'][index, facet, :count].detach()
            valid_scores = _valid_span_scores(torch, start, end).reshape(-1)
            ranked, indices = valid_scores.topk(min(2, valid_scores.numel()))
            chosen = int(indices[0])
            unique = ranked.numel() == 1 or float(ranked[0] - ranked[1]) > 1e-7
            if not unique or (chosen // count, chosen % count) != tuple(record['labels']['spans'][facet]):
                continue
            for key, teacher_logits in (('start', start), ('end', end)):
                endpoint_terms.append(torch.nn.functional.kl_div(output[key][index, facet, :count].log_softmax(-1),
                    teacher_logits.softmax(-1), reduction='sum'))
    presence = torch.stack(presence_terms).mean() if presence_terms else zero
    endpoints = torch.stack(endpoint_terms).mean() if endpoint_terms else zero
    return (presence + endpoints) * .5, {'teacher_presence_kl': presence, 'teacher_endpoint_kl': endpoints,
        'teacher_presence_terms': zero.detach() + len(presence_terms),
        'teacher_endpoint_terms': zero.detach() + len(endpoint_terms)}


def _pair_overlap_probability(left, right):
    """Independent valid spans overlap unless either strictly precedes the other."""
    left_start, left_end = left.sum(1), left.sum(0)
    right_start, right_end = right.sum(1), right.sum(0)
    def after(start):
        return start.flip(0).cumsum(0).flip(0) - start
    disjoint = (left_end * after(right_start)).sum() + (right_end * after(left_start)).sum()
    return (1. - disjoint).clamp(0., 1.)


def _overlap_loss(torch, output, records):
    """Bounded mean overlap probability over labeled-present copied-facet pairs."""
    terms = []
    for index, record in enumerate(records):
        count = len(record['tokens']); occupied = []
        for facet, present in enumerate(record['labels']['presence']):
            if present:
                joint = _valid_span_distribution(torch, output['start'][index, facet, :count],
                    output['end'][index, facet, :count])
                occupied.append(joint)
        for left in range(len(occupied)):
            for right in range(left + 1, len(occupied)):
                terms.append(_pair_overlap_probability(occupied[left], occupied[right]))
    zero = output['modality'].sum() * 0
    result = torch.stack(terms).mean() if terms else zero
    return result, {'overlap_facet_pairs': zero.detach() + len(terms)}


def _loss(torch, model, teacher, records, model_config, objective):
    _require(objective in ('base', 'facet_retention'), 'known matched training objective required')
    batch = span._batch(torch, records)
    output = model(*batch)
    with torch.no_grad():
        teacher_output = teacher(*batch)
    base, parts = previous._loss(torch, lambda *_: output, records, model_config, 'consistency')
    preservation, teacher_parts = _teacher_loss(torch, output, teacher_output, records)
    overlap, overlap_parts = _overlap_loss(torch, output, records)
    teacher_weight, overlap_weight = (.5, .1) if objective == 'facet_retention' else (0., 0.)
    total = base + teacher_weight * preservation + overlap_weight * overlap
    return total, {**parts, **teacher_parts, **overlap_parts, 'base_objective': base,
        'teacher_kl': preservation, 'span_overlap': overlap,
        'weighted_teacher': teacher_weight * preservation, 'weighted_overlap': overlap_weight * overlap,
        'total': total}


def build_checkpoint(parent_consistency_payload, training_rows, tuning_rows, pairs, *, objective, seed,
                     learning_rate=.001, batch_size=12):
    previous.validate_checkpoint(parent_consistency_payload)
    parent = copy.deepcopy(parent_consistency_payload)
    _require(parent["training_config"]["objective"] == "consistency", "fixed consistency-objective parent required")
    _require(parent["progress"]["optimizer_steps"] > 0 and parent["model_config"]["seed"] == seed, "trained same-seed Consistency parent required")
    mixed._splits(training_rows, tuning_rows)
    pools = _pairs_and_pools(training_rows, pairs)
    counts = {name: len(pool) for name, pool in pools.items()}
    config = _training_config(objective, seed, learning_rate, batch_size)
    return {"schema": SCHEMA, "lineage_id": LINEAGE_ID, "implementation": _implementation(),
        "consistency_parent_checkpoint": parent, "consistency_parent_checkpoint_sha256": checkpoint_digest(parent),
        "consistency_parent_optimizer_steps": parent["progress"]["optimizer_steps"],
        "model_config": copy.deepcopy(parent["model_config"]), "training_config": config,
        "initial_model_state_sha256": checkpoint_digest(parent["model_state"]),
        "training_manifest_sha256": checkpoint_digest(training_rows), "tuning_manifest_sha256": checkpoint_digest(tuning_rows),
        "pair_manifest_sha256": checkpoint_digest(pairs), "training_count": len(training_rows), "tuning_count": len(tuning_rows),
        "pool_counts": counts, "model_state": copy.deepcopy(parent["model_state"]),
        "optimizer_state": {"schema": "adam-default-betas-eps/v1", "parameters": {}},
        "progress": _progress(counts, seed), "parent_checkpoint_sha256": None, **FALSE}


def _restore(checkpoint):
    import torch
    fields = {"schema", "lineage_id", "implementation", "consistency_parent_checkpoint", "consistency_parent_checkpoint_sha256",
        "consistency_parent_optimizer_steps", "model_config", "training_config", "initial_model_state_sha256",
        "training_manifest_sha256", "tuning_manifest_sha256", "pair_manifest_sha256", "training_count", "tuning_count",
        "pool_counts", "model_state", "optimizer_state", "progress", "parent_checkpoint_sha256", *FALSE}
    _require(type(checkpoint) is dict and set(checkpoint) == fields, "closed facet retention checkpoint required")
    _require(checkpoint["schema"] == SCHEMA and checkpoint["lineage_id"] == LINEAGE_ID and
             all(checkpoint[key] is False for key in FALSE), "facet retention schema/authority differs")
    _require(len(_raw(checkpoint)) <= MAX_BYTES, "checkpoint exceeds byte bound")
    _require(checkpoint["implementation"] == _implementation(), "facet retention implementation source drift")
    parent = checkpoint["consistency_parent_checkpoint"]
    previous.validate_checkpoint(parent)
    _require(parent["training_config"]["objective"] == "consistency", "fixed consistency-objective parent required")
    _require(checkpoint["consistency_parent_checkpoint_sha256"] == checkpoint_digest(parent), "Consistency parent hash differs")
    _require(type(checkpoint["consistency_parent_optimizer_steps"]) is int and
             checkpoint["consistency_parent_optimizer_steps"] == parent["progress"]["optimizer_steps"] > 0, "parent update count differs")
    config, model_config = checkpoint["training_config"], checkpoint["model_config"]
    _require(type(config) is dict and {"objective", "seed", "learning_rate", "batch_size"} <= set(config), "incomplete training config")
    _require(_raw(config) == _raw(_training_config(**{k: config[k] for k in ("objective", "seed", "learning_rate", "batch_size")})),
             "training config differs")
    _require(_raw(model_config) == _raw(parent["model_config"]) and config["seed"] == model_config["seed"], "frozen model config differs")
    _require(checkpoint["initial_model_state_sha256"] == checkpoint_digest(parent["model_state"]), "initial weights differ")
    for name in ("training_manifest_sha256", "tuning_manifest_sha256", "pair_manifest_sha256"):
        _require(type(checkpoint[name]) is str and span._SHA.fullmatch(checkpoint[name]), "invalid manifest hash")
    count, tuning_count, counts = checkpoint["training_count"], checkpoint["tuning_count"], checkpoint["pool_counts"]
    _require(type(count) is int and 1 <= count <= span.MAX_EXAMPLES and type(tuning_count) is int and
             0 <= tuning_count <= span.MAX_EXAMPLES, "invalid split counts")
    _require(type(counts) is dict and set(counts) == set(POOLS) and
             all(type(n) is int and 3 <= n <= span.MAX_EXAMPLES for n in counts.values()) and
             counts["earlier"] >= 6 and counts["earlier"] + counts["historical_new"] + 2 * counts["pairs"] == count,
             "invalid pool counts")
    progress = checkpoint["progress"]
    _require(type(progress) is dict and type(progress.get("optimizer_steps")) is int and
             0 <= progress["optimizer_steps"] <= 800, "invalid optimizer progress")
    steps = progress["optimizer_steps"]
    _require(_raw(progress) == _raw(_progress(counts, config["seed"], steps)), "deterministic sampler progress differs")
    preceding_hash = checkpoint["parent_checkpoint_sha256"]
    _require(preceding_hash is None or type(preceding_hash) is str and span._SHA.fullmatch(preceding_hash), "invalid preceding checkpoint hash")
    if steps == 0:
        _require(checkpoint["model_state"] == parent["model_state"] and preceding_hash is None, "zero-update weights differ")
    else:
        _require(preceding_hash is not None, "trained checkpoint lacks preceding hash")
    model = mixed._model(torch, model_config)
    template, weights = model.state_dict(), checkpoint["model_state"]
    _require(type(weights) is dict and set(weights) == set(template), "model state keys differ")
    model.load_state_dict({k: span._tensor(torch, weights[k], v.shape, k) for k, v in template.items()}, strict=True)
    optimizer = torch.optim.Adam(model.parameters(), lr=config["learning_rate"], foreach=False)
    state, parameters = checkpoint["optimizer_state"], dict(model.named_parameters())
    _require(type(state) is dict and set(state) == {"schema", "parameters"} and state["schema"] == "adam-default-betas-eps/v1"
             and type(state["parameters"]) is dict, "unsupported optimizer state")
    _require(set(state["parameters"]) == (set(parameters) if steps else set()), "optimizer parameter keys differ")
    for name, moment in state["parameters"].items():
        _require(type(moment) is dict and set(moment) == {"step", "exp_avg", "exp_avg_sq"} and
                 type(moment["step"]) is int and moment["step"] == steps, "optimizer step differs")
        parameter = parameters[name]
        optimizer.state[parameter] = {"step": torch.tensor(float(steps)),
            "exp_avg": span._tensor(torch, moment["exp_avg"], parameter.shape, name),
            "exp_avg_sq": span._tensor(torch, moment["exp_avg_sq"], parameter.shape, name, nonnegative=True)}
    model.eval()
    return torch, model, optimizer


def validate_checkpoint(checkpoint):
    _restore(checkpoint)


def optimizer_steps(checkpoint):
    validate_checkpoint(checkpoint)
    return checkpoint["progress"]["optimizer_steps"]


def train_decoder(checkpoint, training_rows, tuning_rows, pairs, *, max_steps=800, max_seconds=600):
    _require(type(max_steps) is int and 0 <= max_steps <= 800, "max_steps must be in0..800")
    _require(type(max_seconds) in (int, float) and math.isfinite(max_seconds) and 0 <= max_seconds <= 3600,
             "max_seconds must be in0..3600")
    started = time.monotonic()
    torch, model, optimizer = _restore(checkpoint)
    for key, value in (("training_manifest_sha256", training_rows), ("tuning_manifest_sha256", tuning_rows), ("pair_manifest_sha256", pairs)):
        _require(checkpoint[key] == checkpoint_digest(value), "resume manifest differs: " + key)
    records, _ = mixed._splits(training_rows, tuning_rows)
    pools, by_id = _pairs_and_pools(training_rows, pairs), {row["id"]: row for row in records}
    counts, config, model_config = checkpoint["pool_counts"], checkpoint["training_config"], checkpoint["model_config"]
    _require(counts == {k: len(v) for k, v in pools.items()}, "resume pool counts differ")
    progress = copy.deepcopy(checkpoint["progress"])
    _require(progress["optimizer_steps"] + max_steps <= 800, "optimizer step budget exceeded")
    teacher = mixed._model(torch, model_config)
    teacher.load_state_dict({k: span._tensor(torch, checkpoint["consistency_parent_checkpoint"]["model_state"][k], v.shape, k)
        for k, v in teacher.state_dict().items()}, strict=True)
    teacher.eval(); teacher.requires_grad_(False)
    teacher_hash = mixed._state_digest(teacher)
    losses, components, exposures, maximum_gradient, reason = [], [], [], 0., "step_limit"
    auxiliary_gradients = {prefix[:-1]: 0. for prefix in mixed._EXTRA}
    for _ in range(max_steps):
        if time.monotonic() >= started + max_seconds:
            reason = "deadline_before_batch"
            break
        indices, advanced = next_batch_indices(progress, counts, config["seed"])
        chosen_pairs = [pools["pairs"][i] for i in indices["pairs"]]
        ids = [pools[name][i] for name in POOLS[:2] for i in indices[name]] + [i for pair in chosen_pairs for i in pair]
        batch = [by_id[i] for i in ids]
        model.train()
        optimizer.zero_grad(set_to_none=True)
        loss, parts = _loss(torch, model, teacher, batch, model_config, config["objective"])
        _require(bool(torch.isfinite(loss)), "nonfinite training loss")
        loss.backward()
        parameters = list(model.parameters())
        _require(all(p.grad is not None and bool(torch.isfinite(p.grad).all()) for p in parameters), "missing/nonfinite gradients")
        for prefix in mixed._EXTRA:
            gradients = [p.grad.flatten() for name, p in model.named_parameters() if name.startswith(prefix)]
            norm = float(torch.linalg.vector_norm(torch.cat(gradients)))
            auxiliary_gradients[prefix[:-1]] = max(auxiliary_gradients[prefix[:-1]], norm)
        clipped = parameters if model_config["trigger_enabled"] else [p for name, p in model.named_parameters() if not name.startswith(mixed._EXTRA)]
        norm = torch.nn.utils.clip_grad_norm_(clipped, 5., error_if_nonfinite=True)
        maximum_gradient = max(maximum_gradient, float(norm))
        optimizer.step()
        _require(all(bool(torch.isfinite(p).all()) for p in parameters), "nonfinite updated weights")
        _require(all(bool(torch.isfinite(v).all()) for moment in optimizer.state.values() for v in moment.values()
                     if torch.is_tensor(v)), "nonfinite optimizer moments")
        progress = advanced
        losses.append(float(loss.detach()))
        components.append({**{k: float(v.detach()) for k, v in parts.items()}, "domain_rows": {"earlier": 3, "new": 9},
            "supervised_trigger_rows": 9, "trigger_loss_rows": 9 if model_config["trigger_enabled"] else 0,
            "pair_count": 3, "consistency_weight": config["consistency_weight"],
            "teacher_weight": config["teacher_weight"], "overlap_weight": config["overlap_weight"]})
        exposures.append({"optimizer_step": progress["optimizer_steps"], "indices_by_pool": indices,
            "ids": ids, "pairs": chosen_pairs})
    model.eval()
    _require(mixed._state_digest(teacher) == teacher_hash and all(p.grad is None for p in teacher.parameters()),
        "frozen teacher changed or received gradients")
    weights, moments = span._pack(model, optimizer)
    result = ({**copy.deepcopy(checkpoint), "model_state": weights, "optimizer_state": moments, "progress": progress,
               "parent_checkpoint_sha256": checkpoint_digest(checkpoint)} if losses else copy.deepcopy(checkpoint))
    _require(_implementation() == checkpoint["implementation"], "implementation changed during training")
    _require(len(_raw(result)) <= MAX_BYTES, "checkpoint exceeds byte bound")
    return {"checkpoint": result, "report": {"schema": "facet-retention-span-training/v1",
        "checkpoint_sha256": checkpoint_digest(result), "consistency_parent_checkpoint_sha256": checkpoint["consistency_parent_checkpoint_sha256"],
        "consistency_parent_optimizer_steps": checkpoint["consistency_parent_optimizer_steps"], "optimizer_steps": len(losses),
        "new_optimizer_steps_total": progress["optimizer_steps"], "training_executed": bool(losses),
        "objective": config["objective"], "batch_losses": losses, "batch_loss_components": components, "batch_exposures": exposures,
        "domain_exposures": {"earlier": 3 * len(losses), "new": 9 * len(losses)}, "pair_exposures": 3 * len(losses),
        "auxiliary_gradient_norm_max": auxiliary_gradients, "gradient_norm_max": maximum_gradient,
        "changed_parameter_names": [k for k in weights if weights[k] != checkpoint["model_state"][k]],
        "stopped_reason": reason, "elapsed_seconds": time.monotonic() - started,
        "deadline_scope": "soft_boundary_before_numeric_batch; initialization_and_serialization_not_interruptible",
        "tuning_used_for_fit": False, "teacher_training_labels_only": True,
        "teacher_state_unchanged": True, "teacher_gradients_disabled": True, **FALSE}}


class FacetRetentionDecoder:
    def __init__(self, checkpoint):
        self.torch, self.model, _ = _restore(checkpoint)
        self._checkpoint_bytes = _raw(checkpoint)
        self.checkpoint_sha256 = hashlib.sha256(self._checkpoint_bytes).hexdigest()
        self._consistency_parent_sha256 = checkpoint["consistency_parent_checkpoint_sha256"]
        self._implementation_snapshot = _raw(checkpoint["implementation"])
        self._expected_model_sha256 = mixed._state_digest(self.model)
        view = object.__new__(mixed._InferenceView)
        view.torch, view.model = self.torch, self.model
        view._checkpoint = MappingProxyType({"config": MappingProxyType({"latent_enabled": False,
            "trigger_enabled": checkpoint["model_config"]["trigger_enabled"]})})
        self._inference_view, self._inference_config = view, view._checkpoint

    @property
    def checkpoint(self):
        return json.loads(self._checkpoint_bytes)

    def decode_formal_logic(self, texts, *, trigger_ablation="none"):
        _require(type(texts) in (list, tuple) and 1 <= len(texts) <= 128 and all(type(t) is str for t in texts), "one to128 source strings required")
        _require(trigger_ablation in ("none", "disabled"), "unsupported trigger ablation")
        _require(_raw(_implementation()) == self._implementation_snapshot, "implementation source drift")
        _require(hashlib.sha256(self._checkpoint_bytes).hexdigest() == self.checkpoint_sha256, "owned inference checkpoint changed")
        _require(self._inference_view.model is self.model and self._inference_view._checkpoint is self._inference_config,
                 "inference snapshot changed")
        before = mixed._state_digest(self.model)
        _require(before == self._expected_model_sha256, "inference model state changed")
        rows = [self._inference_view._decode(text, [], enabled=trigger_ablation != "disabled") for text in texts]
        _require(before == mixed._state_digest(self.model), "inference model state changed")
        _require(_raw(_implementation()) == self._implementation_snapshot, "implementation changed during inference")
        count = sum(row["status"] == "decoded" for row in rows)
        return {"schema": "facet-retention-span-inference/v1", "lineage_id": LINEAGE_ID,
            "checkpoint_sha256": self.checkpoint_sha256, "consistency_parent_checkpoint_sha256": self._consistency_parent_sha256,
            "rows": rows, "decoded_count": count, "status": "decoded" if count == len(rows) else "partial" if count else "abstained",
            "trigger_ablation": trigger_ablation, "target_access": False, "teacher_forcing": False,
            "training_executed": False, "model_state_unchanged": True, **FALSE}


def save_checkpoint(checkpoint, path):
    validate_checkpoint(checkpoint)
    raw, path = _raw(checkpoint), Path(path).absolute()
    _require(path.parent.resolve(strict=True) == path.parent, "canonical existing checkpoint parent required")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "schema": SCHEMA}


def load_checkpoint(path, *, expected_sha256):
    _require(type(expected_sha256) is str and span._SHA.fullmatch(expected_sha256), "expected checkpoint hash required")
    path = Path(path).absolute()
    _require(path.resolve(strict=True) == path, "canonical checkpoint path required")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        _require(stat.S_ISREG(before.st_mode) and before.st_size <= MAX_BYTES, "bounded regular checkpoint required")
        raw = stream.read(MAX_BYTES + 1)
        after = os.fstat(stream.fileno())
    _require(len(raw) <= MAX_BYTES and (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns), "checkpoint changed while reading")
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
    validate_checkpoint(checkpoint)
    return checkpoint
