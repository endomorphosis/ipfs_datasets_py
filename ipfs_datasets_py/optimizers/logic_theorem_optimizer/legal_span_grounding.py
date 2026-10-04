"""Source-only warm starts with learned trigger and actor-boundary supervision.

The control arm retains the frozen source decoder's logits and objective. The
grounded arm adds a learned trigger pointer, attention-pooled modality residual,
and actor-boundary residual. Source annotations supervise fitting only; inference
uses no trigger lexicon, actor repair, target, or source parser. All weights and
Adam moments resume exactly. This restricted single-rule decoder proves neither
legal semantics nor support for arbitrary statutory language.
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

SCHEMA = "source-grounded-span-checkpoint/v1"
LINEAGE_ID = "source_grounded_span_v1"
ARCHITECTURE = "source-byte-gru-trigger-attention-modality-actor-residual/v1"
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
    return {"grounding_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "dimensional_parent": dimensions._implementation()}


_IMPLEMENTATION_AT_IMPORT = _capture_implementation()


def _implementation():
    value = _capture_implementation()
    _require(value == _IMPLEMENTATION_AT_IMPORT, "grounding implementation source drift")
    return value


def _source_state(state):
    return {name: value for name, value in state.items() if not name.startswith(_EXTRA)}


def _config(*, trigger_enabled, trigger_loss_weight, actor_loss_weight, **kwargs):
    _require(type(trigger_enabled) is bool, "trigger_enabled must be boolean")
    for value in (trigger_loss_weight, actor_loss_weight):
        _require(type(value) in (int, float) and math.isfinite(value) and 0 < value <= 1,
                 "auxiliary loss weights must be in (0,1]")
    config = span._config(latent_dimension=0, latent_enabled=False, **kwargs)
    return {**config, "architecture": ARCHITECTURE, "trigger_enabled": trigger_enabled,
            "trigger_loss_weight": float(trigger_loss_weight), "actor_loss_weight": float(actor_loss_weight),
            "initialization": "copied_source_parent_zero_output_grounding_adapters/v1",
            "loss": "base_equal_seven_facets_plus_weighted_trigger_and_actor_boundary_ce/v1"}


def _model(torch, config):
    # Inherit the frozen constructor so the names and shapes of copied source
    # parameters stay exact. Only source-only forward computation is extended.
    base_type = type(span._model(torch, config))

    class GroundedModel(base_type):
        def __init__(self):
            super().__init__()
            width = config["hidden_size"] * 2
            self.trigger_boundary = torch.nn.Linear(width, 2)
            self.trigger_modality = torch.nn.Linear(width, 3)
            self.actor_boundary = torch.nn.Linear(width, 2)
            for head in (self.trigger_modality, self.actor_boundary):
                torch.nn.init.zeros_(head.weight)
                torch.nn.init.zeros_(head.bias)

        def forward(self, byte_ids, byte_lengths, lengths, latent, *, enabled=True):
            embedded = self.byte_embedding(byte_ids)
            mean = embedded.sum(2) / byte_lengths.clamp(min=1)[..., None]
            first = embedded[:, :, 0, :]
            last = embedded.gather(2, (byte_lengths.clamp(min=1) - 1)[:, :, None, None].expand(
                -1, -1, 1, config["embedding_dim"])).squeeze(2)
            size = torch.log1p(byte_lengths.to(torch.float32))[..., None] / math.log1p(span.MAX_TOKEN_BYTES)
            token = torch.tanh(self.token_projection(torch.cat((mean, first, last, size), dim=-1)))
            packed = torch.nn.utils.rnn.pack_padded_sequence(token, lengths.cpu(), batch_first=True, enforce_sorted=False)
            encoded, _ = self.encoder(packed)
            encoded, _ = torch.nn.utils.rnn.pad_packed_sequence(encoded, batch_first=True)
            mask = torch.arange(encoded.shape[1])[None, :] < lengths[:, None]
            pooled = (encoded * mask[..., None]).sum(1) / lengths[:, None]
            trigger = self.trigger_boundary(encoded).transpose(1, 2).masked_fill(~mask[:, None, :], -1e9)
            attention = torch.softmax(trigger.mean(1), dim=-1)
            attended = (encoded * attention[..., None]).sum(1)
            modality_residual = self.trigger_modality(attended)
            actor = self.actor_boundary(encoded).transpose(1, 2)
            gate = float(enabled and config["trigger_enabled"])
            start = self.start(encoded).transpose(1, 2)
            end = self.end(encoded).transpose(1, 2)
            start = torch.cat((start[:, :1] + actor[:, :1] * gate, start[:, 1:]), dim=1)
            end = torch.cat((end[:, :1] + actor[:, 1:2] * gate, end[:, 1:]), dim=1)
            return {"modality": self.modality(pooled) + modality_residual * gate,
                    "presence": self.presence(pooled).reshape(-1, 4, 2),
                    "start": start.masked_fill(~mask[:, None, :], -1e9),
                    "end": end.masked_fill(~mask[:, None, :], -1e9),
                    "trigger_boundary": trigger, "trigger_attention": attention,
                    "modality_residual": modality_residual,
                    "actor_boundary": actor.masked_fill(~mask[:, None, :], -1e9)}

    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(config["seed"])
        return GroundedModel()


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
                "id", "source_text", "canonical_ir", "trigger_span", "facet_spans"},
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
            trigger = _span_indices(row["trigger_span"], tokens, text, "trigger")
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
                    _require(trigger[1] < actual[0] or trigger[0] > actual[1], "trigger overlaps a copied facet")
                    positions = set(range(actual[0], actual[1] + 1))
                    _require(not occupied & positions, "copied facet spans overlap")
                    occupied.update(positions)
                    spans.append(actual)
                    presence.append(True)
            parsed.append({"tokens": tokens, "latent": [], "trigger_span": trigger,
                "labels": {"modality": span.MODALITIES.index(rule["modality"]), "spans": spans, "presence": presence}})
        parsed_splits.append(parsed)
        split_ids.append(identifiers)
        split_sources.append(sources)
    _require(not split_ids[0] & split_ids[1] and not split_sources[0] & split_sources[1], "training/tuning overlap")
    return tuple(parsed_splits)


def _loss(torch, model, records, config):
    output = model(*span._batch(torch, records))
    semantic = span._loss(torch, lambda *_: output, records)
    if not config["trigger_enabled"]:
        return semantic, {"semantic": semantic, "trigger": semantic * 0, "actor": semantic * 0}
    trigger_targets = torch.tensor([row["trigger_span"] for row in records], dtype=torch.long)
    actor_targets = torch.tensor([row["labels"]["spans"][0] for row in records], dtype=torch.long)
    ce = torch.nn.functional.cross_entropy
    trigger = (ce(output["trigger_boundary"][:, 0], trigger_targets[:, 0]) +
               ce(output["trigger_boundary"][:, 1], trigger_targets[:, 1])) * .5
    actor = (ce(output["actor_boundary"][:, 0], actor_targets[:, 0]) +
             ce(output["actor_boundary"][:, 1], actor_targets[:, 1])) * .5
    loss = semantic + config["trigger_loss_weight"] * trigger + config["actor_loss_weight"] * actor
    return loss, {"semantic": semantic, "trigger": trigger, "actor": actor}


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
    state = _initial_state(parent, config)
    result = {"schema": SCHEMA, "lineage_id": LINEAGE_ID, "implementation": _implementation(),
        "initialization": copy.deepcopy(_INITIALIZATION), "config": config,
        "source_parent_checkpoint": copy.deepcopy(parent), "source_parent_checkpoint_sha256": checkpoint_digest(parent),
        "source_parent_optimizer_steps": parent["progress"]["optimizer_steps"],
        "initial_source_model_sha256": checkpoint_digest(parent["model_state"]),
        "initial_model_state_sha256": checkpoint_digest(state),
        "training_manifest_sha256": checkpoint_digest(training_examples), "training_count": len(training_examples),
        "tuning_manifest_sha256": checkpoint_digest(tuning_examples), "tuning_count": len(tuning_examples),
        "model_state": state, "optimizer_state": {"schema": "adam-default-betas-eps/v1", "parameters": {}},
        "progress": {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0},
        "parent_checkpoint_sha256": None, **FALSE}
    _require(len(_raw(result)) <= MAX_BYTES, "grounding checkpoint exceeds byte bound")
    return result


def _restore(checkpoint):
    import torch
    fields = {"schema", "lineage_id", "implementation", "initialization", "config", "source_parent_checkpoint",
        "source_parent_checkpoint_sha256", "source_parent_optimizer_steps", "initial_source_model_sha256",
        "initial_model_state_sha256", "training_manifest_sha256", "training_count", "tuning_manifest_sha256",
        "tuning_count", "model_state", "optimizer_state", "progress", "parent_checkpoint_sha256", *FALSE}
    _require(type(checkpoint) is dict and set(checkpoint) == fields, "closed grounding checkpoint required")
    _require(checkpoint["schema"] == SCHEMA and checkpoint["lineage_id"] == LINEAGE_ID
             and all(checkpoint[key] is False for key in FALSE), "grounding schema/authority differs")
    _require(len(_raw(checkpoint)) <= MAX_BYTES, "grounding checkpoint exceeds byte bound")
    _require(checkpoint["implementation"] == _implementation(), "grounding implementation source drift")
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
    progress = checkpoint["progress"]
    _require(type(progress) is dict and set(progress) == {"epochs_completed", "row_cursor", "optimizer_steps"} and
             all(type(value) is int and 0 <= value <= 10**9 for value in progress.values()), "invalid progress")
    cursor, batch = progress["row_cursor"], config["batch_size"]
    _require(cursor < count and cursor % batch == 0 and progress["optimizer_steps"] ==
             progress["epochs_completed"] * math.ceil(count / batch) + cursor // batch, "step/cursor identity differs")
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
    _require(type(max_steps) is int and 0 <= max_steps <= 10000, "max_steps must be in 0..10000")
    _require(type(max_seconds) in (int, float) and math.isfinite(max_seconds) and 0 <= max_seconds <= 3600,
             "max_seconds must be in 0..3600")
    started = time.monotonic()
    deadline = started + max_seconds
    torch, model, optimizer = _restore(checkpoint)
    _require(checkpoint["training_manifest_sha256"] == checkpoint_digest(training_examples) and
             checkpoint["tuning_manifest_sha256"] == checkpoint_digest(tuning_examples), "resume manifests differ")
    records, tuning = _splits(training_examples, tuning_examples)
    config, progress = checkpoint["config"], dict(checkpoint["progress"])
    losses, components, maximum_gradient, reason = [], [], 0., "step_limit"
    auxiliary_gradients = {prefix[:-1]: 0. for prefix in _EXTRA}
    for _ in range(max_steps):
        if time.monotonic() >= deadline:
            reason = "deadline_before_batch"
            break
        order = list(range(len(records)))
        random.Random(config["seed"] + progress["epochs_completed"]).shuffle(order)
        indices = order[progress["row_cursor"]:progress["row_cursor"] + config["batch_size"]]
        model.train()
        optimizer.zero_grad(set_to_none=True)
        loss, parts = _loss(torch, model, [records[index] for index in indices], config)
        _require(bool(torch.isfinite(loss)), "nonfinite training loss")
        loss.backward()
        parameters = list(model.parameters())
        _require(all(parameter.grad is not None and bool(torch.isfinite(parameter.grad).all()) for parameter in parameters),
                 "missing or nonfinite gradients")
        for prefix in _EXTRA:
            values = [p.grad for name, p in model.named_parameters() if name.startswith(prefix)]
            norm = float(torch.linalg.vector_norm(torch.cat([value.flatten() for value in values])))
            auxiliary_gradients[prefix[:-1]] = max(auxiliary_gradients[prefix[:-1]], norm)
        # Preserve the exact control clipping reduction order: appending zero
        # tensors can otherwise change floating-point reduction grouping.
        clipped = parameters if config["trigger_enabled"] else [p for name, p in model.named_parameters() if not name.startswith(_EXTRA)]
        norm = torch.nn.utils.clip_grad_norm_(clipped, 5, error_if_nonfinite=True)
        maximum_gradient = max(maximum_gradient, float(norm))
        optimizer.step()
        _require(all(bool(torch.isfinite(parameter).all()) for parameter in parameters), "nonfinite updated weights")
        _require(all(bool(torch.isfinite(value).all()) for moment in optimizer.state.values()
                     for value in moment.values() if torch.is_tensor(value)), "nonfinite optimizer moments")
        progress["optimizer_steps"] += 1
        progress["row_cursor"] += len(indices)
        if progress["row_cursor"] == len(records):
            progress["epochs_completed"] += 1
            progress["row_cursor"] = 0
        losses.append(float(loss.detach()))
        components.append({key: float(value.detach()) for key, value in parts.items()})
    model.eval()
    total, measured = 0., 0
    with torch.no_grad():
        for start in range(0, len(tuning), config["batch_size"]):
            if time.monotonic() >= deadline:
                break
            chunk = tuning[start:start + config["batch_size"]]
            loss, _ = _loss(torch, model, chunk, config)
            _require(bool(torch.isfinite(loss)), "nonfinite tuning loss")
            total += float(loss) * len(chunk)
            measured += len(chunk)
    weights, moments = span._pack(model, optimizer)
    result = ({**copy.deepcopy(checkpoint), "model_state": weights, "optimizer_state": moments, "progress": progress,
               "parent_checkpoint_sha256": checkpoint_digest(checkpoint)} if losses else copy.deepcopy(checkpoint))
    _require(_implementation() == checkpoint["implementation"], "grounding source changed during training")
    _require(len(_raw(result)) <= MAX_BYTES, "checkpoint exceeds byte bound")
    return {"checkpoint": result, "report": {"schema": "source-grounded-span-training/v1",
        "checkpoint_sha256": checkpoint_digest(result), "optimizer_steps": len(losses), "training_executed": bool(losses),
        "source_parent_checkpoint_sha256": checkpoint["source_parent_checkpoint_sha256"],
        "source_parent_optimizer_steps": checkpoint["source_parent_optimizer_steps"],
        "new_optimizer_steps_total": progress["optimizer_steps"], "batch_losses": losses,
        "batch_loss_components": components, "auxiliary_gradient_norm_max": auxiliary_gradients,
        "gradient_norm_max": maximum_gradient,
        "changed_parameter_names": [key for key in weights if weights[key] != checkpoint["model_state"][key]],
        "stopped_reason": reason, "elapsed_seconds": time.monotonic() - started,
        "deadline_scope": "soft_boundary_before_numeric_batch; initialization_and_serialization_not_interruptible",
        "tuning": {"objective_loss": total / measured if measured else None, "rows_evaluated": measured,
                   "complete": measured == len(tuning), "teacher_forcing": False, "used_for_fit_or_selection": False}, **FALSE}}


class GroundedSpanDecoder(span.SpanLegalFormulaDecoder):
    def __init__(self, checkpoint):
        self.torch, self.model, _ = _restore(checkpoint)
        self._checkpoint = copy.deepcopy(checkpoint)
        self.checkpoint_sha256 = checkpoint_digest(checkpoint)

    @property
    def checkpoint(self):
        return copy.deepcopy(self._checkpoint)

    def _decode(self, text, latent, *, enabled):
        result = super()._decode(text, latent, enabled=enabled)
        try:
            tokens = span.tokenize_source(text)
        except ValueError:
            return result
        torch = self.torch
        with torch.no_grad():
            output = self.model(*span._batch(torch, [{"tokens": tokens, "latent": []}]), enabled=enabled)
        if not all(bool(torch.isfinite(value).all()) for value in output.values()):
            return result
        scores = output["trigger_boundary"][0, 0, :, None] + output["trigger_boundary"][0, 1, None, :]
        scores = scores.masked_fill(~torch.triu(torch.ones_like(scores, dtype=torch.bool)), -float("inf"))
        left, right = divmod(int(scores.flatten().argmax()), len(tokens))
        effective = bool(enabled and self._checkpoint["config"]["trigger_enabled"])
        result["grounding_diagnostics"] = {
            "trigger": {"char_start": tokens[left]["start"], "char_end": tokens[right]["end"],
                        "token_start": left, "token_end_inclusive": right,
                        "text": text[tokens[left]["start"]:tokens[right]["end"]]},
            "trigger_span": [tokens[left]["start"], tokens[right]["end"]],
            "trigger_text": text[tokens[left]["start"]:tokens[right]["end"]],
            "trigger_token_span_inclusive": [left, right],
            "trigger_attention_probabilities": output["trigger_attention"][0].tolist(),
            "trigger_boundary_logits": output["trigger_boundary"][0].tolist(),
            "modality_residual_logits": output["modality_residual"][0].tolist(),
            "actor_boundary_residual_logits": output["actor_boundary"][0].tolist(),
            "trigger_residual_enabled": effective, "actor_residual_enabled": effective,
            "diagnostic_tie_policy": "first_flat_index; diagnostic_only_no_formula_repair",
            "annotations_accessed": False, "source_semantics_verified": False}
        return result

    def decode_formal_logic(self, texts, *, trigger_ablation="none"):
        _require(type(texts) in (list, tuple) and 1 <= len(texts) <= 128 and all(type(t) is str for t in texts),
                 "one to128 source strings required")
        _require(trigger_ablation in ("none", "disabled"), "unsupported trigger ablation")
        _require(_implementation() == self._checkpoint["implementation"], "grounding implementation source drift")
        _require(checkpoint_digest(self._checkpoint) == self.checkpoint_sha256, "owned inference checkpoint changed")
        before = checkpoint_digest({key: value.detach().tolist() for key, value in self.model.state_dict().items()})
        _require(before == checkpoint_digest(self._checkpoint["model_state"]), "inference model state changed")
        rows = [self._decode(text, [], enabled=trigger_ablation != "disabled") for text in texts]
        after = checkpoint_digest({key: value.detach().tolist() for key, value in self.model.state_dict().items()})
        _require(before == after, "inference model state changed")
        _require(_implementation() == self._checkpoint["implementation"], "grounding source changed during inference")
        count = sum(row["status"] == "decoded" for row in rows)
        return {"schema": "source-grounded-span-inference/v1", "lineage_id": LINEAGE_ID,
            "checkpoint_sha256": self.checkpoint_sha256,
            "source_parent_checkpoint_sha256": self._checkpoint["source_parent_checkpoint_sha256"],
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
