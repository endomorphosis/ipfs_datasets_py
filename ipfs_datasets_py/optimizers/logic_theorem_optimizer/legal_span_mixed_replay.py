"""Balanced replay of earlier source labels and explicitly grounded new labels.

Frozen grounded model math is retained. Each batch consumes six earlier and six
new examples, with independent persistent pool permutations and Adam moments.
Only new labels supervise the trigger pointer; actor and semantic objectives use
equal domain weights. Inference receives source text only and an immutable view
of model configuration. No statutory or general logic-family claim is implied.
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

from . import legal_span_formula as span
from . import legal_span_dimensions as dimensions
from . import legal_span_grounding as grounded
from types import MappingProxyType

SCHEMA = "mixed-replay-grounded-span-checkpoint/v1"
LINEAGE_ID = "mixed_replay_grounded_span_v1"
ARCHITECTURE = grounded.ARCHITECTURE
MAX_BYTES = 128 * 1024 * 1024
FALSE = span.FALSE
_require, _raw, checkpoint_digest = span._require, span._raw, span.checkpoint_digest
_EXTRA = ("trigger_boundary.", "trigger_modality.", "actor_boundary.")
_CONFIG_KEYS = ("learning_rate", "batch_size", "seed", "hidden_size", "embedding_dim",
                "projection_width", "residual_scale", "trigger_enabled", "trigger_loss_weight", "actor_loss_weight")
_INITIALIZATION = {
    "mode": "copy_all_source_only_dimensional_parent_parameters_add_grounding_heads",
    "source_parameters_copied": True,
    "trigger_boundary": "seeded_linear_start_end",
    "trigger_modality": "zero_weight_and_bias",
    "actor_boundary": "zero_weight_and_bias",
    "optimizer": "fresh_adam_then_exact_moment_resumption",
    "parent_optimizer_moments_transferred": False,
    "trainable_parameters": "all_parameters; disabled_grounding_heads_have_exact_zero_gradients",
}


def _capture_implementation():
    return {"mixed_replay_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "grounded_parent": grounded._implementation()}


_IMPLEMENTATION_AT_IMPORT = _capture_implementation()


def _implementation():
    value = _capture_implementation()
    _require(value == _IMPLEMENTATION_AT_IMPORT, "mixed replay implementation source drift")
    return value


def _source_state(state):
    return {name: value for name, value in state.items() if not name.startswith(_EXTRA)}


def _config(*, trigger_enabled, trigger_loss_weight, actor_loss_weight, **kwargs):
    _require(type(trigger_enabled) is bool, "trigger_enabled must be boolean")
    for value in (trigger_loss_weight, actor_loss_weight):
        _require(type(value) in (int, float) and math.isfinite(value) and 0 < value <= 1,
                 "auxiliary loss weights must be in (0,1]")
    _require(type(kwargs.get("batch_size")) is int and kwargs["batch_size"] == 12, "batch_size must be exactly 12")
    config = span._config(latent_dimension=0, latent_enabled=False, **kwargs)
    return {**config, "architecture": ARCHITECTURE, "trigger_enabled": trigger_enabled,
            "trigger_loss_weight": float(trigger_loss_weight), "actor_loss_weight": float(actor_loss_weight),
            "initialization": "copied_source_parent_zero_output_grounding_adapters/v1",
            "loss": "equal_domain_seven_facets_and_actor_plus_masked_new_trigger_ce/v1",
            "sampling": "independent_domain_shuffle_wrap_6_each/v1", "optimizer_step_budget": 800}


# Frozen grounded numerical architecture; no copied or modified forward math.
_model = grounded._model


def _span_indices(value, tokens, text, label):
    _require(type(value) is list and len(value) == 2 and all(type(x) is int for x in value)
             and 0 <= value[0] < value[1] <= len(text), "invalid " + label + " character span")
    starts = {token["start"]: i for i, token in enumerate(tokens)}
    ends = {token["end"]: i for i, token in enumerate(tokens)}
    _require(value[0] in starts and value[1] in ends, label + " must align with source tokens")
    return starts[value[0]], ends[value[1]]


def _splits(training, tuning):
    parsed_splits, split_ids, split_sources = [], [], []
    for split_index, rows in enumerate((training, tuning)):
        _require(type(rows) in (list, tuple) and (len(rows) or split_index == 1)
                 and len(rows) <= span.MAX_EXAMPLES, "bounded annotated example sequence required")
        parsed, identifiers, sources = [], set(), set()
        for row in rows:
            _require(type(row) is dict and set(row) == {
                "id", "source_text", "canonical_ir", "trigger_span", "facet_spans", "domain", "trigger_supervised"},
                "closed grounding training example schema required")
            identifier, text = row["id"], row["source_text"]
            _require(type(identifier) is str and 0 < len(identifier.strip()) <= 512 and identifier not in identifiers,
                     "unique bounded example ID required")
            tokens = span.tokenize_source(text)
            _require(text not in sources, "duplicate source text")
            identifiers.add(identifier)
            sources.add(text)
            rule = span.codec_module._rule(row["canonical_ir"])
            _require(all(len(rule[field]) <= 1 for field in span.codec_module.QUALIFIERS),
                     "at most one atom per qualifier facet supported")
            domain, supervised = row["domain"], row["trigger_supervised"]
            _require(type(domain) is str and domain in DOMAINS and type(supervised) is bool,
                     "domain and boolean trigger supervision required")
            _require((domain == "earlier" and supervised is False and row["trigger_span"] is None)
                     or (domain == "new" and supervised is True and row["trigger_span"] is not None),
                     "earlier trigger must be null/masked; new trigger must be annotated")
            trigger = (_span_indices(row["trigger_span"], tokens, text, "trigger") if supervised else None)
            facets = row["facet_spans"]
            _require(type(facets) is dict and set(facets) == set(span.SPAN_FIELDS), "closed facet span map required")
            spans, presence, occupied = [], [], set()
            for field in span.SPAN_FIELDS:
                atom = (rule[field][0] if rule[field] else "") if field in span.codec_module.QUALIFIERS else rule[field]
                if not atom:
                    _require(field in span.OPTIONAL_FIELDS, "actor/action must be nonempty")
                    _require(facets[field] is None, "absent facet requires null span")
                    spans.append((-100, -100))
                    presence.append(False)
                else:
                    actual = _span_indices(facets[field], tokens, text, field)
                    _require(text[facets[field][0]:facets[field][1]] == atom,
                             "explicit " + field + " span differs from canonical source copy")
                    _require(trigger is None or trigger[1] < actual[0] or trigger[0] > actual[1], "trigger overlaps a copied facet")
                    positions = set(range(actual[0], actual[1] + 1))
                    _require(not occupied & positions, "copied facet spans overlap")
                    occupied.update(positions)
                    spans.append(actual)
                    presence.append(True)
            parsed.append({"id": identifier, "domain": domain, "trigger_supervised": supervised,
                "tokens": tokens, "latent": [], "trigger_span": trigger,
                "labels": {"modality": span.MODALITIES.index(rule["modality"]), "spans": spans, "presence": presence}})
        parsed_splits.append(parsed)
        split_ids.append(identifiers)
        split_sources.append(sources)
    _require(not split_ids[0] & split_ids[1] and not split_sources[0] & split_sources[1], "training/tuning overlap")
    for rows in parsed_splits[:1]:
        _require(all(sum(row["domain"] == domain for row in rows) >= 6 for domain in DOMAINS),
                 "at least six training rows per domain required")
    return tuple(parsed_splits)


def _loss(torch, model, records, config):
    """Original seven-facet objective per domain, weighted equally across domains.

    Missing earlier trigger labels are never targets. Disabled controls keep the
    identical balanced semantic computation and exactly zero auxiliary gradients.
    """
    output = model(*span._batch(torch, records))
    zero = output["modality"].sum() * 0
    semantic_parts, actor_parts = {}, {}
    ce = torch.nn.functional.cross_entropy
    for domain in DOMAINS:
        indices = [i for i, row in enumerate(records) if row["domain"] == domain]
        if not indices:
            continue
        rows = [records[i] for i in indices]
        selected = {key: value[indices] for key, value in output.items()}
        semantic_parts[domain] = span._loss(torch, lambda *_: selected, rows)
        if config["trigger_enabled"]:
            targets = torch.tensor([row["labels"]["spans"][0] for row in rows], dtype=torch.long)
            actor_parts[domain] = (ce(selected["actor_boundary"][:, 0], targets[:, 0]) +
                                   ce(selected["actor_boundary"][:, 1], targets[:, 1])) * .5
    semantic = sum(semantic_parts.values()) / len(semantic_parts)
    if config["trigger_enabled"]:
        supervised = [i for i, row in enumerate(records) if row["trigger_supervised"]]
        if supervised:
            targets = torch.tensor([records[i]["trigger_span"] for i in supervised], dtype=torch.long)
            trigger = (ce(output["trigger_boundary"][supervised, 0], targets[:, 0]) +
                       ce(output["trigger_boundary"][supervised, 1], targets[:, 1])) * .5
        else:
            trigger = output["trigger_boundary"].sum() * 0
        actor = sum(actor_parts.values()) / len(actor_parts)
        loss = semantic + config["trigger_loss_weight"] * trigger + config["actor_loss_weight"] * actor
    else:
        actor, trigger, loss = zero, zero, semantic
    return loss, {"semantic": semantic, "trigger": trigger, "actor": actor,
        **{"semantic_" + domain: semantic_parts.get(domain, zero) for domain in DOMAINS},
        **{"actor_" + domain: actor_parts.get(domain, zero) for domain in DOMAINS}}


DOMAINS = ("earlier", "new")


def _pool_order(count, seed, domain, epoch):
    order = list(range(count))
    # Domain and epoch names avoid correlations between independently sized pools.
    random.Random(f"mixed-replay/v1:{seed}:{domain}:{epoch}").shuffle(order)
    return order


def _initial_progress(counts, seed):
    return {"optimizer_steps": 0, "pools": {domain: {
        "epochs_completed": 0, "row_cursor": 0,
        "shuffle_order": _pool_order(counts[domain], seed, domain, 0)} for domain in DOMAINS}}


def next_batch_indices(progress, counts, seed):
    """Return six local indices per pool and a NEW deterministic progress value.

    A batch crossing a pool boundary consumes the remaining old permutation then
    the new epoch permutation. No final short batches or discarded rows occur.
    """
    updated, selected = copy.deepcopy(progress), {}
    for domain in DOMAINS:
        state, count, indices = updated["pools"][domain], counts[domain], []
        for _ in range(6):
            indices.append(state["shuffle_order"][state["row_cursor"]])
            state["row_cursor"] += 1
            if state["row_cursor"] == count:
                state["epochs_completed"] += 1
                state["row_cursor"] = 0
                state["shuffle_order"] = _pool_order(count, seed, domain, state["epochs_completed"])
        selected[domain] = indices
    updated["optimizer_steps"] += 1
    return selected, updated


def _counts(rows):
    return {domain: sum(row["domain"] == domain for row in rows) for domain in DOMAINS}


def _initial_state(parent, config):
    import torch
    model = _model(torch, config)
    state = {name: tensor.detach().tolist() for name, tensor in model.state_dict().items()}
    _require(set(_source_state(state)) == set(parent["model_state"]), "source parent tensor names differ")
    state.update(copy.deepcopy(parent["model_state"]))
    model.load_state_dict({key: span._tensor(torch, state[key], value.shape, key)
                           for key, value in model.state_dict().items()}, strict=True)
    return state


def build_checkpoint(parent, training_examples, tuning_examples=(), *, trigger_enabled=True,
                     seed=None, learning_rate=.001, batch_size=12, trigger_loss_weight=.25, actor_loss_weight=.25):
    dimensions.validate_checkpoint(parent)
    pc = parent["config"]
    _require(pc["latent_dimension"] == 0 and parent["progress"]["optimizer_steps"] > 0,
             "trained zero-dimensional source parent required")
    _require(seed is None or type(seed) is int and seed == pc["seed"], "seed must match source parent")
    config = _config(trigger_enabled=trigger_enabled, trigger_loss_weight=trigger_loss_weight,
        actor_loss_weight=actor_loss_weight, learning_rate=learning_rate, batch_size=batch_size,
        **{key: pc[key] for key in ("seed", "hidden_size", "embedding_dim", "projection_width", "residual_scale")})
    _splits(training_examples, tuning_examples)
    counts, tune_counts = _counts(training_examples), _counts(tuning_examples)
    state = _initial_state(parent, config)
    result = {"schema": SCHEMA, "lineage_id": LINEAGE_ID, "implementation": _implementation(),
        "initialization": copy.deepcopy(_INITIALIZATION), "config": config,
        "source_parent_checkpoint": copy.deepcopy(parent), "source_parent_checkpoint_sha256": checkpoint_digest(parent),
        "source_parent_optimizer_steps": parent["progress"]["optimizer_steps"],
        "initial_source_model_sha256": checkpoint_digest(parent["model_state"]),
        "initial_model_state_sha256": checkpoint_digest(state),
        "training_manifest_sha256": checkpoint_digest(training_examples), "training_count": len(training_examples),
        "tuning_manifest_sha256": checkpoint_digest(tuning_examples), "tuning_count": len(tuning_examples),
        "training_domain_counts": counts, "tuning_domain_counts": tune_counts,
        "model_state": state, "optimizer_state": {"schema": "adam-default-betas-eps/v1", "parameters": {}},
        "progress": _initial_progress(counts, config["seed"]),
        "parent_checkpoint_sha256": None, **FALSE}
    _require(len(_raw(result)) <= MAX_BYTES, "grounding checkpoint exceeds byte bound")
    return result


def _restore(checkpoint):
    import torch
    fields = {"schema", "lineage_id", "implementation", "initialization", "config", "source_parent_checkpoint",
        "source_parent_checkpoint_sha256", "source_parent_optimizer_steps", "initial_source_model_sha256",
        "initial_model_state_sha256", "training_manifest_sha256", "training_count", "tuning_manifest_sha256",
        "tuning_count", "training_domain_counts", "tuning_domain_counts", "model_state", "optimizer_state", "progress", "parent_checkpoint_sha256", *FALSE}
    _require(type(checkpoint) is dict and set(checkpoint) == fields, "closed grounding checkpoint required")
    _require(checkpoint["schema"] == SCHEMA and checkpoint["lineage_id"] == LINEAGE_ID
             and all(checkpoint[key] is False for key in FALSE), "grounding schema/authority differs")
    _require(len(_raw(checkpoint)) <= MAX_BYTES, "grounding checkpoint exceeds byte bound")
    _require(checkpoint["implementation"] == _implementation(), "mixed replay implementation source drift")
    _require(_raw(checkpoint["initialization"]) == _raw(_INITIALIZATION), "initialization policy differs")
    config = copy.deepcopy(checkpoint["config"])
    _require(type(config) is dict and set(_CONFIG_KEYS) <= set(config), "incomplete grounding configuration")
    _require(_raw(config) == _raw(_config(**{key: config[key] for key in _CONFIG_KEYS})), "configuration/runtime differs")
    parent = checkpoint["source_parent_checkpoint"]
    dimensions.validate_checkpoint(parent)
    _require(parent["config"]["latent_dimension"] == 0, "zero-dimensional source parent required")
    _require(checkpoint["source_parent_checkpoint_sha256"] == checkpoint_digest(parent), "source parent hash differs")
    _require(type(checkpoint["source_parent_optimizer_steps"]) is int and
             checkpoint["source_parent_optimizer_steps"] == parent["progress"]["optimizer_steps"] > 0,
             "source parent update count differs")
    for key in ("seed", "hidden_size", "embedding_dim", "projection_width", "residual_scale"):
        _require(_raw(config[key]) == _raw(parent["config"][key]), "inherited configuration differs: " + key)
    initial = _initial_state(parent, config)
    _require(checkpoint["initial_source_model_sha256"] == checkpoint_digest(parent["model_state"]) and
             checkpoint["initial_model_state_sha256"] == checkpoint_digest(initial), "initial weight boundary differs")
    for key in ("training_manifest_sha256", "tuning_manifest_sha256"):
        _require(type(checkpoint[key]) is str and span._SHA.fullmatch(checkpoint[key]), "invalid data manifest hash")
    count, tune_count = checkpoint["training_count"], checkpoint["tuning_count"]
    _require(type(count) is int and 1 <= count <= span.MAX_EXAMPLES and type(tune_count) is int and
             0 <= tune_count <= span.MAX_EXAMPLES, "invalid split counts")
    counts, tune_counts = checkpoint["training_domain_counts"], checkpoint["tuning_domain_counts"]
    for values, total, minimum in ((counts, count, 6), (tune_counts, tune_count, 0)):
        _require(type(values) is dict and set(values) == set(DOMAINS) and
                 all(type(value) is int and minimum <= value <= span.MAX_EXAMPLES for value in values.values())
                 and sum(values.values()) == total, "invalid domain counts")
    progress = checkpoint["progress"]
    _require(type(progress) is dict and set(progress) == {"optimizer_steps", "pools"} and
             type(progress["optimizer_steps"]) is int and 0 <= progress["optimizer_steps"] <= 800 and
             type(progress["pools"]) is dict and set(progress["pools"]) == set(DOMAINS), "invalid progress")
    for domain in DOMAINS:
        state = progress["pools"][domain]
        _require(type(state) is dict and set(state) == {"epochs_completed", "row_cursor", "shuffle_order"}
                 and type(state["epochs_completed"]) is int and type(state["row_cursor"]) is int,
                 "invalid pool progress")
        epochs, cursor = divmod(progress["optimizer_steps"] * 6, counts[domain])
        _require(state["epochs_completed"] == epochs and state["row_cursor"] == cursor,
                 "pool step/cursor identity differs")
        _require(type(state["shuffle_order"]) is list and
                 all(type(index) is int for index in state["shuffle_order"]) and
                 state["shuffle_order"] == _pool_order(counts[domain], config["seed"], domain, epochs),
                 "pool shuffle state differs")
    previous = checkpoint["parent_checkpoint_sha256"]
    _require(previous is None or type(previous) is str and span._SHA.fullmatch(previous), "invalid preceding checkpoint hash")
    if progress["optimizer_steps"] == 0:
        _require(checkpoint["model_state"] == initial and previous is None, "zero-update initialization differs")
    else:
        _require(previous is not None, "trained checkpoint lacks preceding hash")
    model = _model(torch, config)
    template, weights = model.state_dict(), checkpoint["model_state"]
    _require(type(weights) is dict and set(weights) == set(template), "model state keys differ")
    model.load_state_dict({key: span._tensor(torch, weights[key], value.shape, key) for key, value in template.items()}, strict=True)
    optimizer = torch.optim.Adam(model.parameters(), lr=config["learning_rate"], foreach=False)
    state, parameters = checkpoint["optimizer_state"], dict(model.named_parameters())
    _require(type(state) is dict and set(state) == {"schema", "parameters"} and
             state["schema"] == "adam-default-betas-eps/v1" and type(state["parameters"]) is dict,
             "unsupported optimizer state")
    _require(set(state["parameters"]) == (set(parameters) if progress["optimizer_steps"] else set()),
             "optimizer parameter keys differ")
    for name, moment in state["parameters"].items():
        _require(type(moment) is dict and set(moment) == {"step", "exp_avg", "exp_avg_sq"} and
                 type(moment["step"]) is int and moment["step"] == progress["optimizer_steps"], "optimizer step differs")
        parameter = parameters[name]
        optimizer.state[parameter] = {"step": torch.tensor(float(moment["step"])),
            "exp_avg": span._tensor(torch, moment["exp_avg"], parameter.shape, name),
            "exp_avg_sq": span._tensor(torch, moment["exp_avg_sq"], parameter.shape, name, nonnegative=True)}
    model.eval()
    return torch, model, optimizer


def validate_checkpoint(checkpoint):
    _restore(checkpoint)


def initial_model_digest(checkpoint):
    validate_checkpoint(checkpoint)
    return checkpoint["initial_model_state_sha256"]


def initial_source_model_digest(checkpoint):
    validate_checkpoint(checkpoint)
    return checkpoint["initial_source_model_sha256"]


def optimizer_steps(checkpoint):
    validate_checkpoint(checkpoint)
    return checkpoint["progress"]["optimizer_steps"]


def train_decoder(checkpoint, training_examples, tuning_examples=(), *, max_steps=100, max_seconds=60):
    _require(type(max_steps) is int and 0 <= max_steps <= 800, "max_steps must be in 0..800")
    _require(type(max_seconds) in (int, float) and math.isfinite(max_seconds) and 0 <= max_seconds <= 3600,
             "max_seconds must be in 0..3600")
    started = time.monotonic()
    deadline = started + max_seconds
    torch, model, optimizer = _restore(checkpoint)
    _require(checkpoint["training_manifest_sha256"] == checkpoint_digest(training_examples) and
             checkpoint["tuning_manifest_sha256"] == checkpoint_digest(tuning_examples), "resume manifests differ")
    records, tuning = _splits(training_examples, tuning_examples)
    _require(checkpoint["training_domain_counts"] == _counts(records) and
             checkpoint["tuning_domain_counts"] == _counts(tuning), "resume domain counts differ")
    config, progress = checkpoint["config"], copy.deepcopy(checkpoint["progress"])
    _require(progress["optimizer_steps"] + max_steps <= 800, "optimizer step budget exceeded")
    pools = {domain: [row for row in records if row["domain"] == domain] for domain in DOMAINS}
    losses, components, exposures, maximum_gradient, reason = [], [], [], 0., "step_limit"
    auxiliary_gradients = {prefix[:-1]: 0. for prefix in _EXTRA}
    for _ in range(max_steps):
        if time.monotonic() >= deadline:
            reason = "deadline_before_batch"
            break
        indices, advanced = next_batch_indices(progress, checkpoint["training_domain_counts"], config["seed"])
        batch = [pools[domain][index] for domain in DOMAINS for index in indices[domain]]
        _require(_counts(batch) == {"earlier": 6, "new": 6}, "balanced batch invariant differs")
        model.train()
        optimizer.zero_grad(set_to_none=True)
        loss, parts = _loss(torch, model, batch, config)
        _require(bool(torch.isfinite(loss)), "nonfinite training loss")
        loss.backward()
        parameters = list(model.parameters())
        _require(all(parameter.grad is not None and bool(torch.isfinite(parameter.grad).all()) for parameter in parameters),
                 "missing or nonfinite gradients")
        for prefix in _EXTRA:
            values = [p.grad for name, p in model.named_parameters() if name.startswith(prefix)]
            norm = float(torch.linalg.vector_norm(torch.cat([value.flatten() for value in values])))
            auxiliary_gradients[prefix[:-1]] = max(auxiliary_gradients[prefix[:-1]], norm)
        clipped = parameters if config["trigger_enabled"] else [p for name, p in model.named_parameters() if not name.startswith(_EXTRA)]
        norm = torch.nn.utils.clip_grad_norm_(clipped, 5, error_if_nonfinite=True)
        maximum_gradient = max(maximum_gradient, float(norm))
        optimizer.step()
        _require(all(bool(torch.isfinite(parameter).all()) for parameter in parameters), "nonfinite updated weights")
        _require(all(bool(torch.isfinite(value).all()) for moment in optimizer.state.values()
                     for value in moment.values() if torch.is_tensor(value)), "nonfinite optimizer moments")
        progress = advanced
        losses.append(float(loss.detach()))
        components.append({**{key: float(value.detach()) for key, value in parts.items()},
            "domain_rows": {"earlier": 6, "new": 6}, "supervised_trigger_rows": 6,
            "trigger_loss_rows": 6 if config["trigger_enabled"] else 0,
            "actor_loss_rows_by_domain": {domain: 6 if config["trigger_enabled"] else 0 for domain in DOMAINS}})
        exposures.append({"optimizer_step": progress["optimizer_steps"], "indices_by_domain": indices,
                          "ids_by_domain": {domain: [pools[domain][i]["id"] for i in indices[domain]] for domain in DOMAINS}})
    model.eval()
    tuning_report = {}
    with torch.no_grad():
        for domain in DOMAINS:
            rows = [row for row in tuning if row["domain"] == domain]
            total, measured = 0., 0
            for start in range(0, len(rows), config["batch_size"]):
                if time.monotonic() >= deadline:
                    break
                chunk = rows[start:start + config["batch_size"]]
                loss, _ = _loss(torch, model, chunk, config)
                _require(bool(torch.isfinite(loss)), "nonfinite tuning loss")
                total += float(loss) * len(chunk)
                measured += len(chunk)
            tuning_report[domain] = {"objective_loss": total / measured if measured else None,
                "rows_evaluated": measured, "complete": measured == len(rows), "teacher_forcing": False,
                "used_for_fit_or_selection": False}
    weights, moments = span._pack(model, optimizer)
    result = ({**copy.deepcopy(checkpoint), "model_state": weights, "optimizer_state": moments, "progress": progress,
               "parent_checkpoint_sha256": checkpoint_digest(checkpoint)} if losses else copy.deepcopy(checkpoint))
    _require(_implementation() == checkpoint["implementation"], "mixed replay source changed during training")
    _require(len(_raw(result)) <= MAX_BYTES, "checkpoint exceeds byte bound")
    return {"checkpoint": result, "report": {"schema": "mixed-replay-grounded-span-training/v1",
        "checkpoint_sha256": checkpoint_digest(result), "optimizer_steps": len(losses), "training_executed": bool(losses),
        "source_parent_checkpoint_sha256": checkpoint["source_parent_checkpoint_sha256"],
        "source_parent_optimizer_steps": checkpoint["source_parent_optimizer_steps"],
        "new_optimizer_steps_total": progress["optimizer_steps"], "batch_losses": losses,
        "batch_loss_components": components, "batch_exposures": exposures,
        "domain_exposures": {domain: 6 * len(losses) for domain in DOMAINS},
        "auxiliary_gradient_norm_max": auxiliary_gradients, "gradient_norm_max": maximum_gradient,
        "changed_parameter_names": [key for key in weights if weights[key] != checkpoint["model_state"][key]],
        "stopped_reason": reason, "elapsed_seconds": time.monotonic() - started,
        "deadline_scope": "soft_boundary_before_numeric_batch; initialization_and_serialization_not_interruptible",
        "tuning_by_domain": tuning_report, **FALSE}}


def _state_digest(model):
    """Hash tensor values directly; avoid checkpoint JSON copies during inference."""
    hasher = hashlib.sha256()
    for name, tensor in model.state_dict().items():
        value = tensor.detach().cpu().contiguous()
        metadata = _raw({"name": name, "shape": list(value.shape), "dtype": str(value.dtype)})
        hasher.update(len(metadata).to_bytes(8, "big"))
        hasher.update(metadata)
        hasher.update(value.numpy().tobytes())
    return hasher.hexdigest()


class _InferenceView(grounded.GroundedSpanDecoder):
    @property
    def checkpoint(self):
        # Frozen nested mapping, containing only the settings used by the frozen
        # span grammar. Its property access performs no deep copy or target read.
        return self._checkpoint


class MixedReplayDecoder:
    def __init__(self, checkpoint):
        self.torch, self.model, _ = _restore(checkpoint)
        self._checkpoint_bytes = _raw(checkpoint)
        self.checkpoint_sha256 = hashlib.sha256(self._checkpoint_bytes).hexdigest()
        self._source_parent_sha256 = checkpoint["source_parent_checkpoint_sha256"]
        self._implementation_snapshot = _raw(checkpoint["implementation"])
        self._expected_model_sha256 = _state_digest(self.model)
        view = object.__new__(_InferenceView)
        view.torch, view.model = self.torch, self.model
        view._checkpoint = MappingProxyType({"config": MappingProxyType({
            "latent_enabled": False, "trigger_enabled": checkpoint["config"]["trigger_enabled"]})})
        self._inference_view = view
        self._inference_config = view._checkpoint

    @property
    def checkpoint(self):
        # Explicit caller inspection gets an owned copy; decoding never reads it.
        return json.loads(self._checkpoint_bytes)

    def decode_formal_logic(self, texts, *, trigger_ablation="none"):
        _require(type(texts) in (list, tuple) and 1 <= len(texts) <= 128 and all(type(t) is str for t in texts),
                 "one to128 source strings required")
        _require(trigger_ablation in ("none", "disabled"), "unsupported trigger ablation")
        _require(_raw(_implementation()) == self._implementation_snapshot, "mixed replay implementation source drift")
        _require(hashlib.sha256(self._checkpoint_bytes).hexdigest() == self.checkpoint_sha256,
                 "owned inference checkpoint changed")
        _require(self._inference_view.model is self.model and
                 self._inference_view._checkpoint is self._inference_config, "inference snapshot changed")
        before = _state_digest(self.model)
        _require(before == self._expected_model_sha256, "inference model state changed")
        rows = [self._inference_view._decode(text, [], enabled=trigger_ablation != "disabled") for text in texts]
        _require(before == _state_digest(self.model), "inference model state changed")
        _require(_raw(_implementation()) == self._implementation_snapshot, "mixed replay source changed during inference")
        count = sum(row["status"] == "decoded" for row in rows)
        return {"schema": "mixed-replay-grounded-span-inference/v1", "lineage_id": LINEAGE_ID,
            "checkpoint_sha256": self.checkpoint_sha256,
            "source_parent_checkpoint_sha256": self._source_parent_sha256,
            "rows": rows, "decoded_count": count,
            "status": "decoded" if count == len(rows) else "partial" if count else "abstained",
            "trigger_ablation": trigger_ablation, "target_access": False, "teacher_forcing": False,
            "ablation_scope": "both_trigger_modality_and_actor_boundary_residuals; predictions_retained_for_diagnostics",
            "training_executed": False, "model_state_unchanged": True, **FALSE}


def save_checkpoint(checkpoint, path):
    validate_checkpoint(checkpoint)
    raw = _raw(checkpoint)
    path = Path(path).absolute()
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
    _require(len(raw) <= MAX_BYTES and (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
             "checkpoint changed while reading")
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
