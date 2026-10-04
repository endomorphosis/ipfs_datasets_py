"""Matched temporal-presence continuation from exact frozen facet-parent weights.

Both arms use identical CE/JS, correct-parent teacher KL, overlap loss and
stratified batches. Only the targeted arm adds class-balanced temporal-presence
CE on new authored pairs. No inference thresholds or architecture change.
Authored supervision does not establish independently verified statutory meaning.
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
from . import legal_span_facet_retention as facet

span = mixed.span
_require, _raw, checkpoint_digest = span._require, span._raw, span.checkpoint_digest
FALSE = span.FALSE
SCHEMA = "temporal-presence-span-checkpoint/v1"
LINEAGE_ID = "temporal_presence_span_v1"
MAX_BYTES = mixed.MAX_BYTES
POOLS = ("earlier", "historical_new", "positive_pairs", "negative_pairs")
PAIR_POSITIONS = ((6, 7), (8, 9), (10, 11))
ROLE_NAMES = (*span.SPAN_FIELDS, "trigger", "other")


def _capture_implementation():
    return {"temporal_presence_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "frozen_facet": facet._implementation()}


_IMPLEMENTATION_AT_IMPORT = _capture_implementation()


def _implementation():
    value = _capture_implementation()
    _require(value == _IMPLEMENTATION_AT_IMPORT, "temporal presence implementation source drift")
    return value


def _training_config(objective, seed, learning_rate=.0005, batch_size=12):
    _require(objective in ("base", "temporal_presence"), "known matched training objective required")
    config = previous._training_config("consistency", seed, .001, batch_size)
    _require(type(learning_rate) in (int, float) and learning_rate == .0005, "learning rate must be .0005")
    return {**config, "objective": objective, "learning_rate": float(learning_rate), "optimizer_step_budget": 400,
        "teacher_weight": .5, "overlap_weight": .1,
        "temporal_presence_weight": .5 if objective == "temporal_presence" else 0.,
        "temporal_presence_profile": "equal_class_means_new_pairs_only/v1",
        "teacher_profile": "frozen_exact_facet_parent_train_only_correct_optional_presence_and_present_qualifier_endpoints/v1",
        "teacher_historical_batch_positions": list(range(6)),
        "overlap_profile": "mean_overlap_probability_gold_present_facets_conditional_valid_spans/v1",
        "sampling": "shuffle_wrap_3_earlier_3_historical_alternating_2positive_1negative_pairs/v1",
        "initialization": "copy_all_facet_parent_weights_fresh_adam/v1"}


_valid_span_scores = facet._valid_span_scores
_valid_span_distribution = facet._valid_span_distribution
_teacher_loss = facet._teacher_loss
_pair_overlap_probability = facet._pair_overlap_probability
_overlap_loss = facet._overlap_loss


def _pairs_and_pools(rows, pairs):
    original = previous._pairs_and_pools(rows, pairs)
    by_id = {row['id']: row for row in rows}
    positive = [pair for pair in original['pairs'] if bool(by_id[pair[0]]['canonical_ir']['rules'][0]['temporal'])]
    negative = [pair for pair in original['pairs'] if not bool(by_id[pair[0]]['canonical_ir']['rules'][0]['temporal'])]
    _require(len(positive) == len(negative) and len(positive) >= 2,
        'equal temporal-present and temporal-absent pair pools, at least two each, required')
    return {name: original[name] for name in POOLS[:2]} | {'positive_pairs': positive, 'negative_pairs': negative}


def _pool_order(count, seed, pool, epoch):
    order = list(range(count))
    random.Random(f"temporal-presence/v1:{seed}:{pool}:{epoch}").shuffle(order)
    return order


def _draw_counts(steps):
    return {'earlier': 3*steps, 'historical_new': 3*steps,
        'positive_pairs': 3*(steps//2) + 2*(steps%2),
        'negative_pairs': 3*(steps//2) + steps%2}


def _progress(counts, seed, steps=0):
    draws = _draw_counts(steps)
    return {'optimizer_steps': steps, 'pools': {name: {
        'epochs_completed': draws[name] // counts[name], 'row_cursor': draws[name] % counts[name],
        'shuffle_order': _pool_order(counts[name], seed, name, draws[name] // counts[name])} for name in POOLS}}


def next_batch_indices(progress, counts, seed):
    updated, selected = copy.deepcopy(progress), {}
    even = progress['optimizer_steps'] % 2 == 0
    quotas = {'earlier': 3, 'historical_new': 3, 'positive_pairs': 2 if even else 1,
        'negative_pairs': 1 if even else 2}
    for name in POOLS:
        state, indices = updated['pools'][name], []
        for _ in range(quotas[name]):
            indices.append(state['shuffle_order'][state['row_cursor']])
            state['row_cursor'] += 1
            if state['row_cursor'] == counts[name]:
                state['epochs_completed'] += 1; state['row_cursor'] = 0
                state['shuffle_order'] = _pool_order(counts[name], seed, name, state['epochs_completed'])
        selected[name] = indices
    updated['optimizer_steps'] += 1
    return selected, updated


def _temporal_presence_loss(torch, output, records):
    """New-pair-only CE: each class has equal mass regardless of the 4:2 quota."""
    _require(len(records) == 12, 'temporal objective requires the declared twelve-row batch')
    optional = span.OPTIONAL_FIELDS.index('temporal')
    facet_index = span.SPAN_FIELDS.index('temporal')
    groups = {False: [], True: []}
    for index in range(6, 12):
        present = bool(records[index]['labels']['presence'][facet_index])
        target = torch.tensor(int(present), dtype=torch.long, device=output['presence'].device)
        groups[present].append(torch.nn.functional.cross_entropy(output['presence'][index, optional], target))
    _require(all(groups.values()), 'both temporal presence classes required in every new-pair batch')
    negative, positive = (torch.stack(groups[present]).mean() for present in (False, True))
    zero = output['modality'].sum().detach() * 0
    return (negative + positive) * .5, {'temporal_positive_ce': positive, 'temporal_negative_ce': negative,
        'temporal_positive_rows': zero + len(groups[True]), 'temporal_negative_rows': zero + len(groups[False])}


def _loss(torch, model, teacher, records, model_config, objective):
    _require(objective in ('base', 'temporal_presence'), 'known matched training objective required')
    batch = span._batch(torch, records)
    output = model(*batch)
    with torch.no_grad():
        teacher_output = teacher(*batch)
    base, parts = previous._loss(torch, lambda *_: output, records, model_config, 'consistency')
    preservation, teacher_parts = _teacher_loss(torch, output, teacher_output, records)
    overlap, overlap_parts = _overlap_loss(torch, output, records)
    temporal, temporal_parts = _temporal_presence_loss(torch, output, records)
    common = base + .5*preservation + .1*overlap
    weight = .5 if objective == 'temporal_presence' else 0.
    total = common + weight*temporal
    return total, {**parts, **teacher_parts, **overlap_parts, **temporal_parts, 'base_objective': base,
        'teacher_kl': preservation, 'span_overlap': overlap, 'weighted_teacher': .5*preservation,
        'weighted_overlap': .1*overlap, 'common_objective': common, 'temporal_presence_ce': temporal,
        'weighted_temporal_presence': weight*temporal, 'total': total}


def build_checkpoint(parent_facet_payload, training_rows, tuning_rows, pairs, *, objective, seed,
                     learning_rate=.0005, batch_size=12):
    facet.validate_checkpoint(parent_facet_payload)
    parent = copy.deepcopy(parent_facet_payload)
    _require(parent["progress"]["optimizer_steps"] > 0 and parent["model_config"]["seed"] == seed, "trained same-seed facet parent required")
    mixed._splits(training_rows, tuning_rows)
    pools = _pairs_and_pools(training_rows, pairs)
    counts = {name: len(pool) for name, pool in pools.items()}
    config = _training_config(objective, seed, learning_rate, batch_size)
    return {"schema": SCHEMA, "lineage_id": LINEAGE_ID, "implementation": _implementation(),
        "facet_parent_checkpoint": parent, "facet_parent_checkpoint_sha256": checkpoint_digest(parent),
        "facet_parent_optimizer_steps": parent["progress"]["optimizer_steps"],
        "model_config": copy.deepcopy(parent["model_config"]), "training_config": config,
        "initial_model_state_sha256": checkpoint_digest(parent["model_state"]),
        "training_manifest_sha256": checkpoint_digest(training_rows), "tuning_manifest_sha256": checkpoint_digest(tuning_rows),
        "pair_manifest_sha256": checkpoint_digest(pairs), "training_count": len(training_rows), "tuning_count": len(tuning_rows),
        "pool_counts": counts, "model_state": copy.deepcopy(parent["model_state"]),
        "optimizer_state": {"schema": "adam-default-betas-eps/v1", "parameters": {}},
        "progress": _progress(counts, seed), "parent_checkpoint_sha256": None, **FALSE}


def _restore(checkpoint):
    import torch
    fields = {"schema", "lineage_id", "implementation", "facet_parent_checkpoint", "facet_parent_checkpoint_sha256",
        "facet_parent_optimizer_steps", "model_config", "training_config", "initial_model_state_sha256",
        "training_manifest_sha256", "tuning_manifest_sha256", "pair_manifest_sha256", "training_count", "tuning_count",
        "pool_counts", "model_state", "optimizer_state", "progress", "parent_checkpoint_sha256", *FALSE}
    _require(type(checkpoint) is dict and set(checkpoint) == fields, "closed temporal presence checkpoint required")
    _require(checkpoint["schema"] == SCHEMA and checkpoint["lineage_id"] == LINEAGE_ID and
             all(checkpoint[key] is False for key in FALSE), "temporal presence schema/authority differs")
    _require(len(_raw(checkpoint)) <= MAX_BYTES, "checkpoint exceeds byte bound")
    _require(checkpoint["implementation"] == _implementation(), "temporal presence implementation source drift")
    parent = checkpoint["facet_parent_checkpoint"]
    facet.validate_checkpoint(parent)
    _require(checkpoint["facet_parent_checkpoint_sha256"] == checkpoint_digest(parent), "facet parent hash differs")
    _require(type(checkpoint["facet_parent_optimizer_steps"]) is int and
             checkpoint["facet_parent_optimizer_steps"] == parent["progress"]["optimizer_steps"] > 0, "parent update count differs")
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
             all(type(n) is int and 2 <= n <= span.MAX_EXAMPLES for n in counts.values()) and
             counts["earlier"] >= 6 and counts["historical_new"] >= 3 and
             counts["positive_pairs"] == counts["negative_pairs"] and
             counts["earlier"] + counts["historical_new"] + 2 * (counts["positive_pairs"] + counts["negative_pairs"]) == count,
             "invalid pool counts")
    progress = checkpoint["progress"]
    _require(type(progress) is dict and type(progress.get("optimizer_steps")) is int and
             0 <= progress["optimizer_steps"] <= 400, "invalid optimizer progress")
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


def train_decoder(checkpoint, training_rows, tuning_rows, pairs, *, max_steps=400, max_seconds=600):
    _require(type(max_steps) is int and 0 <= max_steps <= 400, "max_steps must be in0..400")
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
    _require(progress["optimizer_steps"] + max_steps <= 400, "optimizer step budget exceeded")
    teacher = mixed._model(torch, model_config)
    teacher.load_state_dict({k: span._tensor(torch, checkpoint["facet_parent_checkpoint"]["model_state"][k], v.shape, k)
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
        chosen_pairs = [pools[name][i] for name in POOLS[2:] for i in indices[name]]
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
            "teacher_weight": config["teacher_weight"], "overlap_weight": config["overlap_weight"],
            "temporal_presence_weight": config["temporal_presence_weight"]})
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
    return {"checkpoint": result, "report": {"schema": "temporal-presence-span-training/v1",
        "checkpoint_sha256": checkpoint_digest(result), "facet_parent_checkpoint_sha256": checkpoint["facet_parent_checkpoint_sha256"],
        "facet_parent_optimizer_steps": checkpoint["facet_parent_optimizer_steps"], "optimizer_steps": len(losses),
        "new_optimizer_steps_total": progress["optimizer_steps"], "training_executed": bool(losses),
        "objective": config["objective"], "batch_losses": losses, "batch_loss_components": components, "batch_exposures": exposures,
        "domain_exposures": {"earlier": 3 * len(losses), "new": 9 * len(losses)}, "pair_exposures": 3 * len(losses),
        "auxiliary_gradient_norm_max": auxiliary_gradients, "gradient_norm_max": maximum_gradient,
        "changed_parameter_names": [k for k in weights if weights[k] != checkpoint["model_state"][k]],
        "stopped_reason": reason, "elapsed_seconds": time.monotonic() - started,
        "deadline_scope": "soft_boundary_before_numeric_batch; initialization_and_serialization_not_interruptible",
        "tuning_used_for_fit": False, "teacher_training_labels_only": True,
        "teacher_state_unchanged": True, "teacher_gradients_disabled": True, **FALSE}}


class TemporalPresenceDecoder:
    def __init__(self, checkpoint):
        self.torch, self.model, _ = _restore(checkpoint)
        self._checkpoint_bytes = _raw(checkpoint)
        self.checkpoint_sha256 = hashlib.sha256(self._checkpoint_bytes).hexdigest()
        self._facet_parent_sha256 = checkpoint["facet_parent_checkpoint_sha256"]
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
        return {"schema": "temporal-presence-span-inference/v1", "lineage_id": LINEAGE_ID,
            "checkpoint_sha256": self.checkpoint_sha256, "facet_parent_checkpoint_sha256": self._facet_parent_sha256,
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
