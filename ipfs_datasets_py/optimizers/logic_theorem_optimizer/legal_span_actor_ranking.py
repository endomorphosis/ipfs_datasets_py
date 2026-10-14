"""Actor-only CE plus the retained compatible-span ranking hinge above N4.

All original34 tensors stay frozen. Four copied full6 pointer tensors own fresh
Adam state; only actor row0 affects the returned actor scores and objective.
The fixed0.25/margin1 hinge, domain, argmax and diagnostics are reused unchanged.
Original modality, all presence and nonactor boundaries retain their exact path.
This opt-in outer confers no legal, proof, latent or promotion authority.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys
import time

from . import legal_span_actor_boundary as actor_ce
from . import legal_span_split_features as split
from . import legal_span_targeted_loss as targeted
from . import legal_span_continuation as continuation
from . import legal_span_formula as span

SCHEMA = "bounded-actor-ranking-adapter-checkpoint/v1"
LINEAGE_ID = "bounded_actor_ranking_adapter_v1"
POLICY_SCHEMA = "bounded-actor-ranking-adapter-policy/v1"
MAX_BYTES, MAX_NEW_STEPS, MAX_SECONDS = targeted.MAX_BYTES, 32, 32
FALSE = span.FALSE
_require, _raw, checkpoint_digest = span._require, span._raw, span.checkpoint_digest
SOURCE_SPLIT_SHA256 = "95bd50a7cc6e25381ad126e3d955f0816c31470ec469fb22ceca297e35115035"
SOURCE_SPLIT_MODEL_SHA256 = "fb63e61c7e2591259d40492b5ac5c020ae77f64c08e409d16b372ff7229b9aa5"
BASE_PARAMETER_NAMES = split.MODEL_PARAMETER_NAMES
TRAINABLE_PARAMETER_NAMES = ("actor_start.weight", "actor_start.bias", "actor_end.weight", "actor_end.bias")
ENCODED_WIDTH, STORED_TRAINABLE_SCALARS, ACTIVE_TRAINABLE_SCALARS = 64, 780, 130
MODEL_PARAMETER_NAMES = BASE_PARAMETER_NAMES + TRAINABLE_PARAMETER_NAMES
OBJECTIVES = ("actor-ranking-hinge",)
INACTIVE_ROWS = (1, 2, 3, 4, 5)
DERIVED_ACTOR_CE_SHA256 = "442bfb72ae1038f541530a8d2446872f0393a5eeab07ba9c5616d6ad80368d4a"


def _finite_shape(value, dimensions, label, *, nonnegative=False):
    if dimensions:
        _require(type(value) is list and len(value) == dimensions[0], "exact tensor shape required: " + label)
        for child in value:
            _finite_shape(child, dimensions[1:], label, nonnegative=nonnegative)
    else:
        _require(type(value) in (int, float) and math.isfinite(value) and abs(value) <= 3.4028234663852886e38
            and (not nonnegative or value >= 0), "finite typed tensor scalar required: " + label)


def _trainable_shapes():
    return {name: (6, ENCODED_WIDTH) if name.endswith("weight") else (6,) for name in TRAINABLE_PARAMETER_NAMES}


def _initial_state(base):
    _require(type(base) is dict and set(base) == set(BASE_PARAMETER_NAMES), "exact original34 split state required")
    result = copy.deepcopy(base)
    for name, shape in _trainable_shapes().items():
        original = name.removeprefix("actor_")
        _finite_shape(base[original], shape, original)
        result[name] = copy.deepcopy(base[original])
    return result

def _inactive_state(state):
    result = {}
    for name, shape in _trainable_shapes().items():
        _finite_shape(state[name], shape, name)
        result[name] = copy.deepcopy(state[name][1:])
    return result

def _all_zero(value):
    if type(value) is list:
        return all(_all_zero(item) for item in value)
    return type(value) in (int, float) and math.isfinite(value) and value == 0


def _partition():
    return {"model_parameter_names": list(MODEL_PARAMETER_NAMES),
        "trainable_parameter_names": list(TRAINABLE_PARAMETER_NAMES),
        "frozen_parameter_names": list(BASE_PARAMETER_NAMES), "optimizer_parameter_order": list(TRAINABLE_PARAMETER_NAMES),
        "inactive_head_rows": list(INACTIVE_ROWS), "active_head_rows": [0],
        "encoded_width": ENCODED_WIDTH, "stored_trainable_scalar_count": STORED_TRAINABLE_SCALARS,
        "active_trainable_scalar_count": ACTIVE_TRAINABLE_SCALARS, "inactive_stored_scalar_count": 650,
        "original34_frozen": True, "all_presence_from_original_head": True,
        "nonactor_boundaries_from_original_heads": True, "feature_parameters_or_storage_shared": False}

def _policy(objective, *, seed=1729, batch_order_seed=1729, batch_size=12):
    _require(type(objective) is str and objective in OBJECTIVES, "closed actor CE-plus-ranking hinge objective required")
    _require(type(seed) is int and seed == 1729 and type(batch_order_seed) is int and batch_order_seed == 1729
        and type(batch_size) is int and batch_size == 12, "fixed1729/12 recipe required")
    return {"schema": POLICY_SCHEMA, "objective": objective, "trainable_parameter_policy": objective,
        "parameter_partition": _partition(), "objective_policy": targeted._policy(seed, actor_ranking_enabled=True,
            presence_ce_weight=1, batch_order_seed=batch_order_seed, batch_size=batch_size),
        "actor_training_count": 168,
        "optimizer": {"name": "Adam", "learning_rate": .001, "betas": [.9, .999], "eps": 1e-8,
            "weight_decay": 0., "foreach": False, "gradient_clip_norm": 5.},
        "initialization": "copy_completed_N4_split34_and_full6_start_end_fresh_four_tensor_Adam/v1",
        "source_split_optimizer_steps": 32, "inherited_optimizer_moments": False,
        "frozen_parameter_gradients": "None_for_original34_before_after_every_completed_update",
        "inactive_head_gradients_and_moments": "exact_zero_rows1_through5",
        "actor_projection": "full6x64_parent_geometry_no_residual_add",
        "initial_binary32_parity": "requires_external_source_gate_before_any_update_including_signed_zero",
        "frozen_modality_presence_and_nonactor_boundary_logits": True,
        "feature_paths_per_source_model_forward": 2, "teacher_model_forwards": 0,
        "max_new_optimizer_steps": 32, "latent_dimension": 384, "latent_enabled": False,
        "evaluation_references_used": False, "automatic_selection_or_promotion": False,
        "full_IR_retention_guaranteed": False, "independent_legal_gold": False}

def _validate_policy(value):
    _require(type(value) is dict and "objective" in value, "closed adapter policy required")
    expected = _policy(value["objective"])
    _require(_raw(value) == _raw(expected), "adapter policy differs")
    return expected


def _capture_implementation():
    _require(hashlib.sha256(Path(actor_ce.__file__).read_bytes()).hexdigest() == DERIVED_ACTOR_CE_SHA256,
        "immutable N8 CE derivation source differs")
    return {"actor_ranking_adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "actor_boundary_ce": actor_ce._implementation(),
        "split_features": split._implementation(), "targeted_loss": targeted._implementation(),
        "continuation": continuation._implementation(), "span": span._implementation()}


_IMPLEMENTATION_AT_IMPORT = _capture_implementation()


def _implementation():
    result = _capture_implementation()
    _require(result == _IMPLEMENTATION_AT_IMPORT, "adapter source changed since import")
    return result


def _source(source):
    split._validated(source)
    _require(checkpoint_digest(source) == SOURCE_SPLIT_SHA256
        and checkpoint_digest(source["model_state"]) == SOURCE_SPLIT_MODEL_SHA256
        and source["progress"]["optimizer_steps"] == 32, "exact completed N4 split checkpoint required")
    return source


def _training_records(training_examples, tuning_examples=()):
    _require(type(tuning_examples) in (list, tuple) and not tuning_examples, "actor tuning references prohibited")
    records, tuning = targeted._bounded_splits(training_examples, ())
    _require(not tuning and tuple(span.SPAN_FIELDS) == ("actor", "action", "object", "conditions", "exceptions", "temporal")
        and tuple(span.OPTIONAL_FIELDS) == ("object", "conditions", "exceptions", "temporal"), "exact six role geometry required")
    for row in records:
        targeted._actor_record(row)
    return records

def _branch_digests(state):
    base = {name: state[name] for name in BASE_PARAMETER_NAMES}
    _require(set(state) == set(MODEL_PARAMETER_NAMES), "closed38 adapter state required")
    return {**split._branch_digests(base), "frozen_base34_state_sha256": checkpoint_digest(base),
        "actor_head_state_sha256": checkpoint_digest({name: state[name] for name in TRAINABLE_PARAMETER_NAMES}),
        "inactive_actor_head_rows_sha256": checkpoint_digest(_inactive_state(state))}


def _model(torch, config):
    ambient = torch.get_rng_state().clone()
    _require(config["hidden_size"] * 2 == ENCODED_WIDTH, "fixed64 encoded geometry required")
    base = split._model(torch, config)
    class ActorBoundaryAdapter(type(base)):
        def forward(self, byte_ids, byte_lengths, lengths, latent, *, enabled=True):
            with torch.no_grad():
                original, original_mask = self._features(byte_ids, byte_lengths, lengths, latent, enabled, False)
                original_pooled = (original * original_mask[..., None]).sum(1) / lengths[:, None]
                modality = self.modality(original_pooled)
                encoded, mask = self._features(byte_ids, byte_lengths, lengths, latent, enabled, True)
                pooled = (encoded * mask[..., None]).sum(1) / lengths[:, None]
                presence = self.presence(pooled).reshape(-1, 4, 2)
                starts = self.start(encoded).transpose(1, 2).masked_fill(~mask[:, None, :], -1e9)
                ends = self.end(encoded).transpose(1, 2).masked_fill(~mask[:, None, :], -1e9)
            # Full6 projections preserve parent arithmetic geometry. Original
            # nonactor rows are returned directly, without a residual zero-add.
            actor_starts = self.actor_start(encoded).transpose(1, 2).masked_fill(~mask[:, None, :], -1e9)
            actor_ends = self.actor_end(encoded).transpose(1, 2).masked_fill(~mask[:, None, :], -1e9)
            for key in self._actor_forward_accounting:
                self._actor_forward_accounting[key] += 1
            return {"modality": modality, "presence": presence,
                "start": torch.cat((actor_starts[:, :1, :], starts[:, 1:, :]), dim=1),
                "end": torch.cat((actor_ends[:, :1, :], ends[:, 1:, :]), dim=1)}
    base.__class__ = ActorBoundaryAdapter
    base.actor_start = copy.deepcopy(base.start)
    base.actor_end = copy.deepcopy(base.end)
    base._actor_forward_accounting = dict.fromkeys(("source_model_forwards", "modality_encoder_forwards",
        "span_encoder_forwards", "original_presence_head_forwards", "original_start_head_forwards",
        "original_end_head_forwards", "actor_start_head_forwards", "actor_end_head_forwards"), 0)
    _require(torch.equal(ambient, torch.get_rng_state()), "actor construction changed ambient CPU RNG")
    return base

def _state_digest(model, names=MODEL_PARAMETER_NAMES):
    state = model.state_dict()
    _require(set(state) == set(MODEL_PARAMETER_NAMES), "closed38 live state required")
    return checkpoint_digest({name: state[name].detach().tolist() for name in names})


def _configure_parameters(model):
    named = dict(model.named_parameters())
    _require(tuple(named) == MODEL_PARAMETER_NAMES, "ordered actor named parameters differ")
    _require(len({id(p) for p in named.values()}) == 38 and
        len({p.untyped_storage().data_ptr() for p in named.values()}) == 38, "Parameter/storage alias refused")
    _require(all(tuple(named[name].shape) == shape for name, shape in _trainable_shapes().items())
        and sum(named[name].numel() for name in TRAINABLE_PARAMETER_NAMES) == STORED_TRAINABLE_SCALARS,
        "live actor pointer shapes/scalar count differ")
    for name, parameter in named.items():
        parameter.requires_grad_(name in TRAINABLE_PARAMETER_NAMES)
        parameter.grad = None
    return named, [named[name] for name in TRAINABLE_PARAMETER_NAMES]

def _validate_optimizer_state(state, steps):
    _require(type(steps) is int and 0 <= steps <= MAX_NEW_STEPS, "bounded actual Adam step required")
    _require(type(state) is dict and set(state) == {"schema", "parameters"}
        and state["schema"] == "adam-default-betas-eps/v1" and type(state["parameters"]) is dict,
        "closed actor Adam state required")
    _require(set(state["parameters"]) == (set(TRAINABLE_PARAMETER_NAMES) if steps else set()),
        "Adam must own exactly the actual four tensors")
    for name, moment in state["parameters"].items():
        _require(type(moment) is dict and set(moment) == {"step", "exp_avg", "exp_avg_sq"}
            and type(moment["step"]) is int and moment["step"] == steps, "actor Adam step differs")
        for key in ("exp_avg", "exp_avg_sq"):
            _finite_shape(moment[key], _trainable_shapes()[name], name + "." + key, nonnegative=key == "exp_avg_sq")
            _require(_all_zero(moment[key][1:]), "inactive actor Adam rows must remain exact zero")

def _origin(checkpoint):
    result = copy.deepcopy(checkpoint)
    result["model_state"] = _initial_state(result["source_split_checkpoint"]["model_state"])
    result["optimizer_state"] = {"schema": "adam-default-betas-eps/v1", "parameters": {}}
    result["progress"] = {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0}
    result["parent_checkpoint_sha256"] = None
    result.pop("initial_checkpoint_sha256", None)
    return result


def build_checkpoint(source_split, training_examples, tuning_examples=(), *, context_contract,
                     objective="actor-ranking-hinge", seed=1729, batch_order_seed=1729,
                     batch_size=12, learning_rate=.001, latent_enabled=False):
    policy = _policy(objective, seed=seed, batch_order_seed=batch_order_seed, batch_size=batch_size)
    _require(type(learning_rate) in (int, float) and learning_rate == .001 and latent_enabled is False,
        "fixed source-only .001 adapter recipe required")
    source = copy.deepcopy(_source(source_split)); _training_records(training_examples, tuning_examples)
    contract = continuation._context_contract(context_contract)
    child = source["initial_continuation_checkpoint"]
    _require(_raw(contract) == _raw(child["context_contract"])
        and checkpoint_digest(training_examples) == source["training_manifest_sha256"], "source context/training identity differs")
    state = _initial_state(source["model_state"])
    result = {"schema": SCHEMA, "lineage_id": LINEAGE_ID, "implementation": _implementation(),
        "training_policy": policy, "training_policy_sha256": checkpoint_digest(policy),
        "initial_training_policy_sha256": checkpoint_digest(policy),
        "source_split_checkpoint": source, "source_split_checkpoint_sha256": SOURCE_SPLIT_SHA256,
        "source_split_model_state_sha256": SOURCE_SPLIT_MODEL_SHA256, "source_split_optimizer_steps": 32,
        "source_parent_checkpoint_sha256": source["source_parent_checkpoint_sha256"],
        "source_parent_model_state_sha256": source["source_parent_model_state_sha256"],
        "initial_continuation_checkpoint": copy.deepcopy(child),
        "initial_continuation_checkpoint_sha256": checkpoint_digest(child),
        "context_contract": contract, "context_contract_sha256": checkpoint_digest(contract),
        "config": copy.deepcopy(source["config"]), "training_manifest_sha256": checkpoint_digest(training_examples),
        "tuning_manifest_sha256": checkpoint_digest(tuning_examples), "training_count": 168, "tuning_count": 0,
        "legacy_prefix_sha256": targeted.LEGACY96_SHA256, "actor_training_count": 168,
        "actor_adapter_source_state_map": {name: name.removeprefix("actor_") for name in TRAINABLE_PARAMETER_NAMES},
        "model_state": state, "initial_branch_digests": _branch_digests(state),
        "optimizer_state": {"schema": "adam-default-betas-eps/v1", "parameters": {}},
        "progress": {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0},
        "parent_checkpoint_sha256": None, **FALSE}
    result["initial_checkpoint_sha256"] = checkpoint_digest(result)
    _require(len(_raw(result)) <= MAX_BYTES, "adapter checkpoint exceeds byte bound")
    return result


def _validated(checkpoint):
    fields = {"schema", "lineage_id", "implementation", "training_policy", "training_policy_sha256",
        "initial_training_policy_sha256", "initial_checkpoint_sha256", "source_split_checkpoint",
        "source_split_checkpoint_sha256", "source_split_model_state_sha256", "source_split_optimizer_steps",
        "source_parent_checkpoint_sha256", "source_parent_model_state_sha256", "initial_continuation_checkpoint",
        "initial_continuation_checkpoint_sha256", "context_contract", "context_contract_sha256", "config",
        "training_manifest_sha256", "tuning_manifest_sha256", "training_count", "tuning_count", "legacy_prefix_sha256",
        "actor_training_count", "actor_adapter_source_state_map", "model_state", "initial_branch_digests",
        "optimizer_state", "progress", "parent_checkpoint_sha256", *FALSE}
    _require(type(checkpoint) is dict and set(checkpoint) == fields, "closed adapter checkpoint required")
    _require(checkpoint["schema"] == SCHEMA and checkpoint["lineage_id"] == LINEAGE_ID
        and all(checkpoint[key] is False for key in FALSE) and checkpoint["implementation"] == _implementation()
        and len(_raw(checkpoint)) <= MAX_BYTES, "adapter schema/source/authority/bound differs")
    source = _source(checkpoint["source_split_checkpoint"])
    policy = _validate_policy(checkpoint["training_policy"])
    _require(checkpoint["training_policy_sha256"] == checkpoint["initial_training_policy_sha256"] == checkpoint_digest(policy),
        "immutable adapter policy differs")
    for key, value in {"source_split_checkpoint_sha256": SOURCE_SPLIT_SHA256,
        "source_split_model_state_sha256": SOURCE_SPLIT_MODEL_SHA256, "source_split_optimizer_steps": 32,
        "config": source["config"], "training_manifest_sha256": source["training_manifest_sha256"],
        "source_parent_checkpoint_sha256": source["source_parent_checkpoint_sha256"],
        "source_parent_model_state_sha256": source["source_parent_model_state_sha256"],
        "initial_continuation_checkpoint": source["initial_continuation_checkpoint"],
        "initial_continuation_checkpoint_sha256": checkpoint_digest(source["initial_continuation_checkpoint"]),
        "context_contract": source["initial_continuation_checkpoint"]["context_contract"],
        "context_contract_sha256": source["initial_continuation_checkpoint"]["context_contract_sha256"],
        "training_count": 168, "tuning_count": 0, "tuning_manifest_sha256": checkpoint_digest(()),
        "legacy_prefix_sha256": targeted.LEGACY96_SHA256, "actor_training_count": 168,
        "actor_adapter_source_state_map": {name: name.removeprefix("actor_") for name in TRAINABLE_PARAMETER_NAMES}}.items():
        _require(_raw(checkpoint[key]) == _raw(value), "adapter provenance differs: " + key)
    _require(checkpoint["config"]["latent_dimension"] == 384 and checkpoint["config"]["latent_enabled"] is False
        and checkpoint["config"]["hidden_size"] * 2 == ENCODED_WIDTH, "source-only fixed64 geometry required")
    initial = _initial_state(source["model_state"])
    _require(checkpoint["initial_branch_digests"] == _branch_digests(initial), "initial adapter branch digests differ")
    state = checkpoint["model_state"]
    _require(type(state) is dict and set(state) == set(MODEL_PARAMETER_NAMES), "closed38 state required")
    _require(all(_raw(state[name]) == _raw(source["model_state"][name]) for name in BASE_PARAMETER_NAMES)
        and _raw(_inactive_state(state)) == _raw(_inactive_state(initial)), "frozen base or inactive adapter rows changed")
    progress = targeted._progress(checkpoint["progress"])
    _require(progress["optimizer_steps"] <= 32, "adapter update budget exceeded")
    targeted._batch_indices(168, progress, 12, 1729)
    previous = checkpoint["parent_checkpoint_sha256"]
    _require((progress["optimizer_steps"] == 0 and previous is None and _raw(state) == _raw(initial))
        or (progress["optimizer_steps"] > 0 and type(previous) is str and span._SHA.fullmatch(previous)),
        "adapter preceding checkpoint lineage differs")
    _require(checkpoint["initial_checkpoint_sha256"] == checkpoint_digest(_origin(checkpoint)), "adapter origin differs")
    _validate_optimizer_state(checkpoint["optimizer_state"], progress["optimizer_steps"])
    return source, policy


def _restore(checkpoint):
    import torch
    ambient = torch.get_rng_state().clone(); _, policy = _validated(checkpoint)
    model = _model(torch, checkpoint["config"]); template = model.state_dict()
    model.load_state_dict({name: span._tensor(torch, checkpoint["model_state"][name], value.shape, name)
        for name, value in template.items()}, strict=True)
    named, selected = _configure_parameters(model)
    optimizer = torch.optim.Adam(selected, lr=.001, betas=(.9, .999), eps=1e-8, weight_decay=0., foreach=False)
    for name, moment in checkpoint["optimizer_state"]["parameters"].items():
        parameter = named[name]
        optimizer.state[parameter] = {"step": torch.tensor(float(moment["step"])),
            "exp_avg": span._tensor(torch, moment["exp_avg"], parameter.shape, name),
            "exp_avg_sq": span._tensor(torch, moment["exp_avg_sq"], parameter.shape, name, nonnegative=True)}
    model.eval(); _require(torch.equal(ambient, torch.get_rng_state()), "adapter restore changed ambient CPU RNG")
    return torch, model, optimizer


def validate_checkpoint(checkpoint):
    _restore(checkpoint)


def _loss(torch, output, records, indices, policy):
    _validate_policy(policy)
    _require(len(records) == len(indices) and len(records) > 0, "complete actor training membership required")
    total, base_details = targeted._loss(torch, lambda *_: output, records, policy["objective_policy"])
    rows = []
    for index, record in zip(indices, records, strict=True):
        count, gold, _, _ = targeted._actor_record(record)
        rows.append({"id": record["id"], "training_index": index,
            "token_count": count, "actor_gold_coordinates": list(gold), "actor_present": True})
    return total, {"base_objective": base_details, "total_loss": float(total.detach()),
        "batch_denominator": len(rows), "rows": rows, "evaluation_references_used": False, "teacher_forcing": True}

def _validate_objective_entry(entry, batch, policy):
    _validate_policy(policy)
    _require(type(entry) is dict and set(entry) == {"optimizer_step", "indices", "ids", "details"}
        and all(entry[key] == batch[key] for key in ("optimizer_step", "indices", "ids")), "actor objective/batch join differs")
    d = entry["details"]
    _require(type(d) is dict and set(d) == {"base_objective", "total_loss", "batch_denominator", "rows",
        "evaluation_references_used", "teacher_forcing"} and d["evaluation_references_used"] is False
        and d["teacher_forcing"] is True, "closed actor CE-plus-ranking diagnostics required")
    targeted._validate_objective_diagnostics(d["base_objective"])
    _require(d["base_objective"]["actor_hinge_applied"] is policy["objective_policy"]["actor_ranking_enabled"] is True,
        "ranking objective must apply the retained actor hinge")
    _require(type(d["rows"]) is list and type(d["batch_denominator"]) is int
        and d["batch_denominator"] == len(entry["indices"]) == len(entry["ids"]) == len(d["rows"])
        and d["batch_denominator"] > 0, "actor full batch denominator differs")
    base_rows = d["base_objective"]["rows"]
    _require(len(base_rows) == len(d["rows"]), "actor target/base objective row count differs")
    for index, identifier, row, base_row in zip(entry["indices"], entry["ids"], d["rows"], base_rows, strict=True):
        _require(type(row) is dict and set(row) == {"id", "training_index", "token_count", "actor_gold_coordinates", "actor_present"}
            and row["id"] == identifier and row["training_index"] == index and type(index) is int and 0 <= index < 168
            and row["actor_present"] is True and type(row["token_count"]) is int and 1 <= row["token_count"] <= 128,
            "authenticated actor ranking membership required")
        targeted._span_coordinates(row["actor_gold_coordinates"], row["token_count"])
        _require(base_row["id"] == identifier and base_row["token_count"] == row["token_count"]
            and _raw(base_row["gold_coordinates"]) == _raw(row["actor_gold_coordinates"]),
            "actor target/base objective coordinate join differs")
    _require(type(d["total_loss"]) in (int, float) and math.isfinite(d["total_loss"])
        and d["total_loss"] == d["base_objective"]["total_loss"] == batch["loss"], "actor CE-plus-ranking scalar differs")

def _frozen_head_digest(output):
    return checkpoint_digest({"modality": output["modality"].detach().tolist(),
        "presence": output["presence"].detach().tolist(),
        "start_nonactor": output["start"][:, 1:, :].detach().tolist(),
        "end_nonactor": output["end"][:, 1:, :].detach().tolist()})

def _row_invariants(named, optimizer):
    _require(all(named[name].grad is None for name in BASE_PARAMETER_NAMES), "frozen34 gradient accumulated")
    for name in TRAINABLE_PARAMETER_NAMES:
        p = named[name]
        _require(p.grad is not None and bool(p.grad.isfinite().all()) and bool((p.grad[1:] == 0).all()),
            "actor gradient nonfinite/missing or inactive rows nonzero")
        if p in optimizer.state:
            for key in ("exp_avg", "exp_avg_sq"):
                moment = optimizer.state[p][key]
                _require(bool(moment.isfinite().all()) and bool((moment[1:] == 0).all()), "inactive actor moments changed")

def _validate_freeze_entry(entry, batch):
    required = {"optimizer_step", "indices", "ids", "frozen_before", "frozen_after", "inactive_before", "inactive_after",
        "frozen_head_sample_sha256", "frozen_gradients_none", "trainable_gradients_finite_nonNone",
        "inactive_gradients_zero", "inactive_moments_zero", "changed_parameter_names", "completed_returned_update",
        "branch_digests_before", "branch_digests_after"}
    _require(type(entry) is dict and set(entry) == required and all(entry[k] == batch[k] for k in ("optimizer_step", "indices", "ids")),
        "closed freeze/batch trace join differs")
    for key in ("frozen_gradients_none", "trainable_gradients_finite_nonNone", "inactive_gradients_zero", "inactive_moments_zero", "completed_returned_update"):
        _require(entry[key] is True, "returned update invariants required")
    _require(entry["frozen_before"] == entry["frozen_after"] == SOURCE_SPLIT_MODEL_SHA256
        and entry["inactive_before"] == entry["inactive_after"]
        and type(entry["changed_parameter_names"]) is list
        and len(entry["changed_parameter_names"]) == len(set(entry["changed_parameter_names"]))
        and set(entry["changed_parameter_names"]) <= set(TRAINABLE_PARAMETER_NAMES), "frozen values/heads or unknown parameters changed")
    before, after = entry["branch_digests_before"], entry["branch_digests_after"]
    _require(set(before) == set(after) and set(before) == {"modality_feature_state_sha256", "span_feature_state_sha256", "modality_path_state_sha256",
        "span_path_state_sha256", "dormant_latent_state_sha256", "frozen_base34_state_sha256", "actor_head_state_sha256", "inactive_actor_head_rows_sha256"}
        and all(before[k] == after[k] for k in before if k != "actor_head_state_sha256")
        and before["frozen_base34_state_sha256"] == SOURCE_SPLIT_MODEL_SHA256
        and before["inactive_actor_head_rows_sha256"] == entry["inactive_before"], "normalized frozen branch state changed")
    for digest in (*before.values(), *after.values(), entry["inactive_before"], entry["frozen_head_sample_sha256"]):
        _require(type(digest) is str and span._SHA.fullmatch(digest), "raw invariant digest required")


def train_decoder(checkpoint, training_examples, tuning_examples=(), *, max_steps=32, max_seconds=32):
    _require(type(max_steps) is int and 0 <= max_steps <= 32 and type(max_seconds) in (int, float)
        and math.isfinite(max_seconds) and 0 <= max_seconds <= 32, "bounded adapter32-step/time call required")
    started = time.monotonic(); deadline = started+max_seconds
    _, policy = _validated(checkpoint); records = _training_records(training_examples, tuning_examples)
    _require(checkpoint["training_manifest_sha256"] == checkpoint_digest(training_examples), "resume training rows differ")
    progress = dict(checkpoint["progress"]); initial_progress = dict(progress)
    _require(progress["optimizer_steps"]+max_steps <= 32, "adapter cumulative32-step limit exceeded")
    torch, model, optimizer = _restore(checkpoint); named = dict(model.named_parameters())
    selected = [named[name] for name in TRAINABLE_PARAMETER_NAMES]
    initial_state = {name: p.detach().tolist() for name, p in model.state_dict().items()}
    initial_hash = checkpoint_digest(initial_state); initial_branches = _branch_digests(initial_state)
    forward_counts_before = dict(model._actor_forward_accounting)
    batches, objectives, freezes, losses = [], [], [], []; maximum_gradient = 0.; reason = "step_limit"
    for _ in range(max_steps):
        if time.monotonic() >= deadline: reason = "deadline_before_batch"; break
        before_progress = dict(progress); indices = targeted._batch_indices(168, progress, 12, 1729)
        batch = [records[index] for index in indices]
        model.train(); optimizer.zero_grad(set_to_none=True)
        _require(all(named[name].grad is None for name in BASE_PARAMETER_NAMES), "frozen34 preupdate gradient accumulated")
        before_state = {name: p.detach().tolist() for name, p in model.state_dict().items()}
        branch_before = _branch_digests(before_state)
        _require(branch_before["frozen_base34_state_sha256"] == SOURCE_SPLIT_MODEL_SHA256, "frozen34 preupdate drift")
        output = model(*span._batch(torch, batch)); before_heads = _frozen_head_digest(output)
        loss, details = _loss(torch, output, batch, indices, policy)
        _require(bool(torch.isfinite(loss)), "nonfinite adapter loss")
        loss.backward(); _row_invariants(named, optimizer)
        gradient = float(torch.nn.utils.clip_grad_norm_(selected, 5., error_if_nonfinite=True)); maximum_gradient = max(maximum_gradient, gradient)
        optimizer.step(); _row_invariants(named, optimizer)
        _require(all(bool(torch.isfinite(p).all()) for p in named.values()) and all(bool(torch.isfinite(value).all())
            for moment in optimizer.state.values() for value in moment.values() if torch.is_tensor(value)), "nonfinite weights/moments")
        after_state = {name: p.detach().tolist() for name, p in model.state_dict().items()}; branch_after = _branch_digests(after_state)
        progress = targeted._advance_progress(before_progress, len(indices), 168); scalar = float(loss.detach()); losses.append(scalar)
        trace = targeted._batch_trace_entry(indices, training_examples, before_progress, progress, loss=scalar, gradient_norm=gradient)
        batches.append(trace)
        entry = {"optimizer_step": progress["optimizer_steps"], "indices": list(indices), "ids": list(trace["ids"]), "details": details}
        _validate_objective_entry(entry, trace, policy); objectives.append(entry)
        freeze = {"optimizer_step": progress["optimizer_steps"], "indices": list(indices), "ids": list(trace["ids"]),
            "frozen_before": branch_before["frozen_base34_state_sha256"], "frozen_after": branch_after["frozen_base34_state_sha256"],
            "inactive_before": branch_before["inactive_actor_head_rows_sha256"], "inactive_after": branch_after["inactive_actor_head_rows_sha256"],
            "frozen_head_sample_sha256": before_heads, "frozen_gradients_none": True,
            "trainable_gradients_finite_nonNone": True, "inactive_gradients_zero": True, "inactive_moments_zero": True,
            "changed_parameter_names": [name for name in MODEL_PARAMETER_NAMES if before_state[name] != after_state[name]],
            "completed_returned_update": True, "branch_digests_before": branch_before, "branch_digests_after": branch_after}
        _validate_freeze_entry(freeze, trace); freezes.append(freeze)
    weights, moments = span._pack(model, optimizer); _validate_optimizer_state(moments, progress["optimizer_steps"])
    updated = copy.deepcopy(checkpoint); updated.update(model_state=weights, optimizer_state=moments, progress=progress,
        parent_checkpoint_sha256=checkpoint_digest(checkpoint) if losses else checkpoint["parent_checkpoint_sha256"])
    _validated(updated)
    for previous, current in zip(freezes, freezes[1:]):
        _require(previous["branch_digests_after"] == current["branch_digests_before"], "interupdate branch discontinuity")
    initial_origin = _initial_state(checkpoint["source_split_checkpoint"]["model_state"])
    final_branches = _branch_digests(weights)
    forward_counts = {key: model._actor_forward_accounting[key] - forward_counts_before[key] for key in forward_counts_before}
    _require(all(count == len(losses) for count in forward_counts.values()), "actual actor training forward counts differ")
    report = {"schema": "bounded-actor-ranking-adapter-training/v1", "checkpoint_sha256": checkpoint_digest(updated),
        "previous_actor_adapter_checkpoint_sha256": checkpoint_digest(checkpoint),
        "initial_checkpoint_sha256": checkpoint["initial_checkpoint_sha256"],
        "source_split_checkpoint_sha256": SOURCE_SPLIT_SHA256, "source_split_model_state_sha256": SOURCE_SPLIT_MODEL_SHA256,
        "source_split_optimizer_steps": 32, "source_parent_checkpoint_sha256": checkpoint["source_parent_checkpoint_sha256"],
        "source_parent_model_state_sha256": checkpoint["source_parent_model_state_sha256"],
        "initial_continuation_checkpoint_sha256": checkpoint["initial_continuation_checkpoint_sha256"],
        "initial_model_state_sha256": checkpoint_digest(initial_origin), "final_model_state_sha256": checkpoint_digest(weights),
        "training_call_initial_model_state_sha256": initial_hash, "initial_branch_digests": checkpoint["initial_branch_digests"],
        "training_call_initial_branch_digests": initial_branches, "final_branch_digests": final_branches,
        "training_policy": copy.deepcopy(policy), "training_policy_sha256": checkpoint_digest(policy), "parameter_partition": _partition(),
        "optimizer_parameter_order": list(TRAINABLE_PARAMETER_NAMES), "optimizer_steps": len(losses),
        "stored_trainable_scalar_count": STORED_TRAINABLE_SCALARS,
        "active_trainable_scalar_count": ACTIVE_TRAINABLE_SCALARS,
        "continuation_optimizer_steps_total": progress["optimizer_steps"], "training_executed": bool(losses),
        "batch_losses": losses, "batch_trace": targeted._trace_summary(batches, initial_progress, progress, policy["objective_policy"], training_examples),
        "objective_trace": {"schema": "completed-actor-ranking-adapter-objective-trace/v1", "completed_updates": len(objectives),
            "batches": objectives, "batches_sha256": checkpoint_digest(objectives), "evaluation_references_used": False,
            "independent_numerical_kernel_trace": False},
        "freeze_trace": {"schema": "completed-actor-ranking-adapter-freeze-trace/v1", "completed_updates": len(freezes),
            "batches": freezes, "batches_sha256": checkpoint_digest(freezes), "independent_numerical_kernel_trace": False},
        "frozen_base34_sha256_initial": initial_branches["frozen_base34_state_sha256"],
        "frozen_base34_sha256_final": final_branches["frozen_base34_state_sha256"],
        "inactive_head_rows_sha256_initial": initial_branches["inactive_actor_head_rows_sha256"],
        "inactive_head_rows_sha256_final": final_branches["inactive_actor_head_rows_sha256"],
        "frozen_parameters_sha256_initial": initial_branches["frozen_base34_state_sha256"],
        "frozen_parameters_sha256_final": final_branches["frozen_base34_state_sha256"],
        "legacy_prefix_sha256": targeted.LEGACY96_SHA256, "actor_training_count": 168,
        "actor_adapter_source_state_map": checkpoint["actor_adapter_source_state_map"],
        "gradient_norm_max": maximum_gradient, "changed_parameter_names": [name for name in MODEL_PARAMETER_NAMES if weights[name] != initial_state[name]],
        "stopped_reason": reason, "elapsed_seconds": time.monotonic()-started,
        "deadline_scope": "soft_boundary_before_numeric_batch; initialization_and_serialization_not_interruptible",
        "partial_failure_scope": "only_successfully_returned_prefix_traced; unreturned_partial_failure_unknown",
        "forward_accounting": {"schema": "actor-ranking-adapter-training-forward-accounting/v1",
            "training_model_forward_calls": forward_counts["source_model_forwards"],
            "training_modality_encoder_calls": forward_counts["modality_encoder_forwards"],
            "training_span_encoder_calls": forward_counts["span_encoder_forwards"],
            "training_original_presence_head_calls": forward_counts["original_presence_head_forwards"],
            "training_original_start_head_calls": forward_counts["original_start_head_forwards"],
            "training_original_end_head_calls": forward_counts["original_end_head_forwards"],
            "training_actor_start_head_calls": forward_counts["actor_start_head_forwards"],
            "training_actor_end_head_calls": forward_counts["actor_end_head_forwards"],
            "actual_model_counter_deltas": forward_counts, "training_source_row_occurrences": sum(len(b["indices"]) for b in batches),
            "tuning_model_forward_calls": 0, "teacher_model_forward_calls": 0, "restore_validation_and_external_evaluation_forwards_included": False},
        "tuning": {"rows_evaluated": 0, "used_for_fit_or_selection": False}, **FALSE}
    return {"checkpoint": updated, "report": report}


class SpanActorRankingAdapterDecoder:
    """Use the unchanged single-source readout under this new outer's custody."""
    def __init__(self, checkpoint):
        self.torch, self.model, _ = _restore(checkpoint)
        self._checkpoint_bytes = _raw(checkpoint)
        self.checkpoint_sha256 = hashlib.sha256(self._checkpoint_bytes).hexdigest()
        self._expected_model_sha256 = _state_digest(self.model)
        self._implementation_snapshot = _raw(checkpoint["implementation"])
        self._policy = copy.deepcopy(checkpoint["training_policy"])
        view = object.__new__(span.SpanLegalFormulaDecoder)
        view.torch, view.model = self.torch, self.model
        view.checkpoint = {"config": copy.deepcopy(checkpoint["config"])}
        self._inference_view = view

    @property
    def checkpoint(self):
        return json.loads(self._checkpoint_bytes)

    def decode_formal_logic(self, texts, latents=None, *, latent_ablation="none"):
        _require(type(texts) in (list, tuple) and 1 <= len(texts) <= 128
            and all(type(text) is str and len(span.tokenize_source(text)) <= 128 for text in texts),
            "one to128 bounded source strings required")
        _require(type(latents) in (list, tuple) and len(latents) == len(texts), "one latent placeholder per source required")
        vectors = [span._vector(vector, 384) for vector in latents]
        _require(latent_ablation in ("none", "zero", "rotate", "disabled"), "unsupported latent ablation")
        _require(latent_ablation != "rotate" or len(texts) > 1, "rotate requires at leasttwo sources")
        _require(_raw(_implementation()) == self._implementation_snapshot
            and hashlib.sha256(self._checkpoint_bytes).hexdigest() == self.checkpoint_sha256,
            "owned inference source or checkpoint changed")
        _require(self._inference_view.model is self.model and self._inference_view.torch is self.torch
            and self._inference_view.checkpoint == {"config": self.checkpoint["config"]}, "readout adapter changed")
        _require(_state_digest(self.model) == self._expected_model_sha256, "owned inference model changed")
        if latent_ablation == "zero": vectors = [[0.] * 384 for _ in vectors]
        elif latent_ablation == "rotate": vectors = vectors[1:] + vectors[:1]
        forward_counts_before = dict(self.model._actor_forward_accounting)
        rows = [self._inference_view._decode(text, vector, enabled=latent_ablation != "disabled")
            for text, vector in zip(texts, vectors, strict=True)]
        _require(_state_digest(self.model) == self._expected_model_sha256
            and _raw(_implementation()) == self._implementation_snapshot, "inference changed source or model")
        forward_counts = {key: self.model._actor_forward_accounting[key] - forward_counts_before[key] for key in forward_counts_before}
        _require(all(value == len(rows) for value in forward_counts.values()), "actual actor inference forward counts differ")
        count = sum(row["status"] == "decoded" for row in rows)
        child = self.checkpoint["initial_continuation_checkpoint"]
        return {"schema": "bounded-actor-ranking-adapter-inference/v1", "lineage_id": LINEAGE_ID,
            "checkpoint_sha256": self.checkpoint_sha256, "initial_continuation_checkpoint_sha256": checkpoint_digest(child),
            "source_parent_checkpoint_sha256": child["source_parent_checkpoint_sha256"], "source_parent_optimizer_steps": 400, "source_split_optimizer_steps": 32,
            "source_split_checkpoint_sha256": SOURCE_SPLIT_SHA256, "source_split_model_state_sha256": SOURCE_SPLIT_MODEL_SHA256,
            "context_contract_sha256": child["context_contract_sha256"], "model_state_sha256": self._expected_model_sha256,
            "training_policy": copy.deepcopy(self._policy), "training_policy_sha256": checkpoint_digest(self._policy),
            "rows": rows, "decoded_count": count, "status": "decoded" if count == len(rows) else "partial" if count else "abstained",
            "latent_ablation": latent_ablation, "target_access": False, "teacher_forcing": False,
            "training_executed": False, "legacy_single_source_readout_unchanged": True, "split_feature_model_forward": True, "actor_adapter_model_forward": True,
            "branch_digests": _branch_digests(self.checkpoint["model_state"]),
            **forward_counts, **FALSE}


def captured_inference(torch, span, warm, checkpoint, rows, *, control="none"):
    """Capture same-forward heads without exposing labels to inference."""
    _require(span is globals()["span"] and warm is continuation, "exact unchanged source owners required")
    _require(type(rows) in (list, tuple) and 1 <= len(rows) <= 128, "one to128 bounded capture source rows required")
    decoder = SpanActorRankingAdapterDecoder(checkpoint)
    _require(torch is decoder.torch, "exact decoder numerical owner required")
    ambient = torch.get_rng_state().clone()
    model_before = _state_digest(decoder.model)
    _require(not decoder.model._forward_hooks and not decoder.model._forward_pre_hooks, "pre-existing hooks refused")
    sources = [{key: row[key] for key in ("id", "source_text", "latent")} for row in rows]
    _require(control in ("none", "zero", "disabled", "rotate"), "unknown latent control")
    tokens = [span.tokenize_source(row["source_text"]) for row in sources]
    captures = []
    def hook(module, incoming, output):
        position = len(captures)
        _require(module is decoder.model and position < len(sources), "unexpected extra source forward")
        count = len(tokens[position])
        _require(type(output) is dict and set(output) == {"modality", "presence", "start", "end"}, "closed heads required")
        for field, shape in {"modality": (1, 3), "presence": (1, 4, 2), "start": (1, 6, count), "end": (1, 6, count)}.items():
            value = output[field]
            _require(torch.is_tensor(value) and tuple(value.shape) == shape and value.dtype == torch.float32
                and value.device.type == "cpu" and not value.requires_grad and bool(torch.isfinite(value).all()),
                "finite detached CPU heads required")
        captures.append({"schema": "joint-source-span-scores/v1",
            "tokens": [{key: token[key] for key in ("text", "start", "end")} for token in tokens[position]],
            "modality_logits": output["modality"][0].tolist(),
            "presence_logits": dict(zip(span.OPTIONAL_FIELDS, output["presence"][0].tolist(), strict=True)),
            "start_logits": dict(zip(span.SPAN_FIELDS, output["start"][0].tolist(), strict=True)),
            "end_logits": dict(zip(span.SPAN_FIELDS, output["end"][0].tolist(), strict=True))})
        return None
    handle = decoder.model.register_forward_hook(hook)
    try:
        with torch.random.fork_rng(devices=[]):
            report = decoder.decode_formal_logic([row["source_text"] for row in sources], [row["latent"] for row in sources],
                latent_ablation=control)
    finally:
        handle.remove()
    _require(len(captures) == len(rows) == len(report["rows"]) and not decoder.model._forward_hooks
        and _state_digest(decoder.model) == model_before and torch.equal(ambient, torch.get_rng_state()),
        "capture changed model/hooks/RNG or lacked complete source coverage")
    _require(all(report[key] == len(rows) for key in decoder.model._actor_forward_accounting), "actual capture forward accounting differs")
    observer = sys.modules["ipfs_datasets_py.logic.formalization.autoencoder.retained_span_score_capture"]
    for source, scores, raw in zip(sources, captures, report["rows"], strict=True):
        _require(raw["source_sha256"] == hashlib.sha256(source["source_text"].encode()).hexdigest(), "raw source identity differs")
        observer._verify_greedy(source["source_text"], scores, raw)
    return {"schema": "actor-ranking-adapter-target-free-head-capture/v1", "inference": report,
        "occurrences": [{"id": source["id"], "source_sha256": hashlib.sha256(source["source_text"].encode()).hexdigest(), "scores": scores}
            for source, scores in zip(sources, captures, strict=True)], "actual_source_forwards": len(rows), "source_model_forwards": len(rows),
        "modality_encoder_forwards": len(rows), "span_encoder_forwards": len(rows),
        "original_presence_head_forwards": len(rows), "original_start_head_forwards": len(rows), "original_end_head_forwards": len(rows),
        "actor_start_head_forwards": len(rows), "actor_end_head_forwards": len(rows),
        "extra_capture_forwards": 0, "model_weights_unchanged": True, "original_greedy_observations_verified": True,
        "ambient_CPU_RNG_preserved": True, "target_access": False, "teacher_forcing": False, **FALSE}


def _write_artifact(path, value):
    path = Path(path).absolute(); raw = _raw(value)
    _require(path.parent.resolve(strict=True) == path.parent, "canonical artifact parent required")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def source_only_parity(torch, span, warm, checkpoint, rows, out, state_name):
    _require(type(state_name) is str and state_name in ("initial", "trained"), "closed parity state required")
    sources = [{key: row[key] for key in ("id", "source_text", "latent")} for row in rows[:2]]
    _require(len(sources) == 2, "two parity source rows required")
    sources = [dict(row, latent=[0.] * 384) for row in sources]
    alternate = [dict(row, latent=[.25 if index == 0 else -.25] * 384) for index, row in enumerate(sources)]
    controls = [("zeros", sources, "none"), ("alternate_placeholders", alternate, "none"),
        ("disabled", alternate, "disabled"), ("rotated_placeholders", alternate, "rotate")]
    captures, projection = [], None
    for name, inputs, control in controls:
        report = captured_inference(torch, span, warm, checkpoint, inputs, control=control)
        observed = [{"scores": capture["scores"], "raw": {key: raw.get(key) for key in
            ("status", "reason", "canonical_ir", "span_diagnostics", "minimum_decision_logit_margin")}}
            for capture, raw in zip(report["occurrences"], report["inference"]["rows"], strict=True)]
        if projection is None: projection = observed
        _require(_raw(observed) == _raw(projection), "disabled source-only scores changed under latent placeholder control")
        captures.append({"name": name, "control": control,
            "report": _write_artifact(Path(out) / (state_name + "-parity-" + name + ".json"), report)})
    return _write_artifact(Path(out) / (state_name + "-parity.json"),
        {"schema": "source-only-dormant384-placeholder-parity/v1", "passed": True, "controls": captures,
            "source_count": 2, "score_and_greedy_decisions_bit_equal": True,
            "genuine_latent_semantics_tested": False, "actual_encoder_calls": 0,
            "actual_external_latent_encoder_calls": 0, "source_model_forwards": 8,
            "modality_encoder_forwards": 8, "span_encoder_forwards": 8, **FALSE})


def save_checkpoint(checkpoint, path):
    validate_checkpoint(checkpoint)
    result = _write_artifact(path, checkpoint)
    return {**result, "schema": SCHEMA}


def load_checkpoint(path, *, expected_sha256):
    _require(type(expected_sha256) is str and span._SHA.fullmatch(expected_sha256), "expected checkpoint hash required")
    path = Path(path).absolute()
    _require(path.resolve(strict=True) == path, "canonical checkpoint path required")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        _require(stat.S_ISREG(before.st_mode) and before.st_size <= MAX_BYTES, "bounded regular checkpoint required")
        raw = stream.read(MAX_BYTES + 1); after = os.fstat(stream.fileno())
    _require(len(raw) <= MAX_BYTES and (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
        and hashlib.sha256(raw).hexdigest() == expected_sha256, "checkpoint changed or raw hash differs")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate checkpoint JSON key")
            result[key] = value
        return result
    def reject(value): raise ValueError("invalid JSON constant: " + value)
    checkpoint = json.loads(raw, object_pairs_hook=unique, parse_constant=reject)
    validate_checkpoint(checkpoint)
    return checkpoint
