"""One class-balanced conditions-presence head above the immutable trained N10 model.

All40 parent tensors are frozen. Full8-output copied presence geometry preserves
initial arithmetic; only rows2:4 contribute to returned conditions logits and CE.
All pointer logits, modality and other presence pairs retain the parent path.
No target, oracle rule, lexical parser or inference repair enters this model.
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

from . import legal_span_actor_features as parent
from . import legal_span_targeted_loss as targeted
from . import legal_span_continuation as continuation
from . import legal_span_formula as span

SCHEMA = "bounded-conditions-balanced-adapter-checkpoint/v1"
LINEAGE_ID = "bounded_conditions_balanced_adapter_v1"
POLICY_SCHEMA = "bounded-conditions-balanced-adapter-policy/v1"
MAX_BYTES, MAX_NEW_STEPS, MAX_SECONDS = targeted.MAX_BYTES, 32, 32
FALSE = span.FALSE
_require, _raw, checkpoint_digest = span._require, span._raw, span.checkpoint_digest
SOURCE_ACTOR_FEATURES_SHA256 = "b4ea8a502789f6dddba6e159eb7ecebb753d8344a833b0afb9109cfd6830bcd3"
SOURCE_ACTOR_FEATURES_MODEL_SHA256 = "c05074b28fb827500f7be6e30d606faee39436047685a1a41b85fa88913100ab"
BASE_PARAMETER_NAMES = parent.MODEL_PARAMETER_NAMES
TRAINABLE_PARAMETER_NAMES = ("conditions_presence.weight", "conditions_presence.bias")
ENCODED_WIDTH, STORED_TRAINABLE_SCALARS, ACTIVE_TRAINABLE_SCALARS = 64, 520, 130
MODEL_PARAMETER_NAMES = BASE_PARAMETER_NAMES + TRAINABLE_PARAMETER_NAMES
OBJECTIVES = ("conditions-balanced-ce",)
INACTIVE_ROWS = (0, 1, 4, 5, 6, 7)
ACTIVE_ROWS = (2, 3)


def _finite_shape(value, dimensions, label, *, nonnegative=False):
    if dimensions:
        _require(type(value) is list and len(value) == dimensions[0], "exact tensor shape required: " + label)
        for child in value:
            _finite_shape(child, dimensions[1:], label, nonnegative=nonnegative)
    else:
        _require(type(value) in (int, float) and math.isfinite(value) and abs(value) <= 3.4028234663852886e38
            and (not nonnegative or value >= 0), "finite typed tensor scalar required: " + label)


def _trainable_shapes():
    return {"conditions_presence.weight": (8, ENCODED_WIDTH), "conditions_presence.bias": (8,)}



def _initial_state(base):
    _require(type(base) is dict and set(base) == set(BASE_PARAMETER_NAMES), "exact trained N10 forty-tensor state required")
    result = copy.deepcopy(base)
    for name, dimensions in _trainable_shapes().items():
        source = name.removeprefix("conditions_")
        _finite_shape(base[source], dimensions, source)
        result[name] = copy.deepcopy(base[source])
    return result


def _inactive_state(state):
    result = {}
    for name, dimensions in _trainable_shapes().items():
        _finite_shape(state[name], dimensions, name)
        result[name] = [copy.deepcopy(state[name][row]) for row in INACTIVE_ROWS]
    return result


def _all_zero(value):
    if type(value) is list:
        return all(_all_zero(item) for item in value)
    return type(value) in (int, float) and math.isfinite(value) and value == 0


def _partition():
    return {"model_parameter_names": list(MODEL_PARAMETER_NAMES), "trainable_parameter_names": list(TRAINABLE_PARAMETER_NAMES),
        "frozen_parameter_names": list(BASE_PARAMETER_NAMES), "optimizer_parameter_order": list(TRAINABLE_PARAMETER_NAMES),
        "inactive_head_rows": list(INACTIVE_ROWS), "active_head_rows": list(ACTIVE_ROWS),
        "encoded_width": 64, "stored_trainable_scalar_count": 520, "active_trainable_scalar_count": 130,
        "inactive_stored_scalar_count": 390, "parent40_frozen": True,
        "modality_and_all_boundaries_from_parent": True, "nonconditions_presence_from_parent": True}


def _class_balance(counts):
    _require(type(counts) is dict and set(counts) == {"absent", "present"}
        and all(type(value) is int and value > 0 for value in counts.values())
        and counts == {"absent": 96, "present": 72}, "authenticated training96absent72present required")
    total = sum(counts.values()); rational = []
    for label in ("absent", "present"):
        denominator = 2 * counts[label]; common = math.gcd(total, denominator)
        rational.append([total // common, denominator // common])
    return {"class_order": ["absent", "present"], "counts": dict(counts), "weights_rational": rational,
        "weights": [numerator / denominator for numerator, denominator in rational],
        "weight_rule": "training_count/(2*class_count)",
        "counts_source": "authenticated_training168_conditions_presence_only", "normalization": "fixed_batch_row_count"}


def _conditions_class_counts(records):
    _require(type(records) in (list, tuple) and len(records) == 168, "exact168 training records required")
    labels = [record["labels"]["presence"][3] for record in records]
    _require(all(type(value) is bool for value in labels), "typed conditions training labels required")
    return {"absent": labels.count(False), "present": labels.count(True)}


def _policy(objective, *, seed=1729, batch_order_seed=1729, batch_size=12):
    _require(type(objective) is str and objective == "conditions-balanced-ce", "closed conditions CE objective required")
    _require(type(seed) is int and seed == 1729 and type(batch_order_seed) is int and batch_order_seed == 1729
        and type(batch_size) is int and batch_size == 12, "fixed1729/12 recipe required")
    return {"schema": POLICY_SCHEMA, "objective": objective, "trainable_parameter_policy": objective,
        "parameter_partition": _partition(), "objective_policy": {"conditions_pair_cross_entropy": True,
            "mean_all_batch_rows": True, "actor_ranking_enabled": False, "training_row_reweighting": True,
            "class_balance": _class_balance({"absent": 96, "present": 72}),
            "source_order": "unchanged_targeted_seed1729_epoch_permutation", "batch_order_seed": 1729, "batch_size": 12},
        "optimizer": {"name": "Adam", "learning_rate": .001, "betas": [.9, .999], "eps": 1e-8,
            "weight_decay": 0., "foreach": False, "gradient_clip_norm": 5.},
        "initialization": "copy_exact_completed_N10_forty_tensors_and_full8_presence_head_fresh_two_tensor_Adam/v1",
        "source_actor_features_optimizer_steps": 32, "inherited_optimizer_moments": False,
        "frozen_parameter_gradients": "None_for_parent40_before_after_every_completed_update",
        "inactive_head_gradients_and_moments": "exact_zero_rows0_1_4_5_6_7",
        "projection": "full8x64_GEMM_replace_conditions_rows2_3_only",
        "max_new_optimizer_steps": 32, "latent_dimension": 384, "latent_enabled": False,
        "feature_paths_per_source_model_forward": 3, "teacher_model_forwards": 0,
        "evaluation_references_used": False, "automatic_selection_or_promotion": False,
        "gold_dependent_oracle_used_in_model": False, "full_IR_retention_guaranteed": False}


def _validate_policy(value):
    _require(type(value) is dict and "objective" in value, "closed adapter policy required")
    expected = _policy(value["objective"])
    _require(_raw(value) == _raw(expected), "adapter policy differs")
    return expected


def _capture_implementation():
    return {"conditions_balanced_adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "actor_features_parent": parent._implementation(), "targeted_loss": targeted._implementation(),
        "continuation": continuation._implementation(), "span": span._implementation()}



_IMPLEMENTATION_AT_IMPORT = _capture_implementation()


def _implementation():
    result = _capture_implementation()
    _require(result == _IMPLEMENTATION_AT_IMPORT, "adapter source changed since import")
    return result


def _source(source):
    parent._validated(source)
    _require(checkpoint_digest(source) == SOURCE_ACTOR_FEATURES_SHA256
        and checkpoint_digest(source["model_state"]) == SOURCE_ACTOR_FEATURES_MODEL_SHA256
        and source["progress"]["optimizer_steps"] == 32, "exact completed N10 checkpoint required")
    return source



def _training_records(training_examples, tuning_examples=()):
    _require(type(tuning_examples) in (list, tuple) and not tuning_examples, "actor tuning references prohibited")
    records, tuning = targeted._bounded_splits(training_examples, ())
    _require(not tuning and tuple(span.SPAN_FIELDS) == ("actor", "action", "object", "conditions", "exceptions", "temporal")
        and tuple(span.OPTIONAL_FIELDS) == ("object", "conditions", "exceptions", "temporal"), "exact six role geometry required")
    for row in records:
        targeted._actor_record(row)
    _class_balance(_conditions_class_counts(records))
    return records

def _branch_digests(state):
    _require(type(state) is dict and set(state) == set(MODEL_PARAMETER_NAMES), "closed42 conditions state required")
    base = {name: state[name] for name in BASE_PARAMETER_NAMES}
    return {**parent._branch_digests(base), "frozen_parent40_state_sha256": checkpoint_digest(base),
        "conditions_presence_state_sha256": checkpoint_digest({name: state[name] for name in TRAINABLE_PARAMETER_NAMES}),
        "inactive_conditions_presence_rows_sha256": checkpoint_digest(_inactive_state(state))}



def _model(torch, config):
    ambient = torch.get_rng_state().clone()
    base = parent._model(torch, config)
    inherited_forward = base.forward
    class ConditionsPresenceAdapter(type(base)):
        def forward(self, byte_ids, byte_lengths, lengths, latent, *, enabled=True):
            with torch.no_grad():
                original = inherited_forward(byte_ids, byte_lengths, lengths, latent, enabled=enabled)
                encoded, mask = self._features(byte_ids, byte_lengths, lengths, latent, enabled, True)
                pooled = (encoded * mask[..., None]).sum(1) / lengths[:, None]
            complete = self.conditions_presence(pooled).reshape(-1, 4, 2)
            presence = torch.cat((original["presence"][:, :1, :], complete[:, 1:2, :], original["presence"][:, 2:, :]), dim=1)
            for key in self._conditions_forward_accounting: self._conditions_forward_accounting[key] += 1
            return {**original, "presence": presence}
    base.__class__ = ConditionsPresenceAdapter
    base.conditions_presence = copy.deepcopy(base.presence)
    base._conditions_forward_accounting = dict.fromkeys(("source_model_forwards", "frozen_actor_features_model_forwards",
        "frozen_modality_encoder_forwards", "frozen_span_encoder_forwards", "additional_frozen_span_encoder_forwards",
        "conditions_presence_head_forwards"), 0)
    _require(torch.equal(ambient, torch.get_rng_state()), "conditions construction changed ambient CPU RNG")
    return base


def _state_digest(model, names=MODEL_PARAMETER_NAMES):
    state = model.state_dict()
    _require(set(state) == set(MODEL_PARAMETER_NAMES), "closed42 live state required")
    return checkpoint_digest({name: state[name].detach().tolist() for name in names})


def _configure_parameters(model):
    named = dict(model.named_parameters())
    _require(tuple(named) == MODEL_PARAMETER_NAMES, "ordered actor named parameters differ")
    _require(len({id(p) for p in named.values()}) == 42 and
        len({p.untyped_storage().data_ptr() for p in named.values()}) == 42, "Parameter/storage alias refused")
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
        "Adam must own exactly the actual two tensors")
    for name, moment in state["parameters"].items():
        _require(type(moment) is dict and set(moment) == {"step", "exp_avg", "exp_avg_sq"}
            and type(moment["step"]) is int and moment["step"] == steps, "actor Adam step differs")
        for key in ("exp_avg", "exp_avg_sq"):
            _finite_shape(moment[key], _trainable_shapes()[name], name + "." + key, nonnegative=key == "exp_avg_sq")
            _require(_all_zero([moment[key][row] for row in INACTIVE_ROWS]), "inactive conditions Adam rows must remain exact zero")

def _origin(checkpoint):
    result = copy.deepcopy(checkpoint)
    result["model_state"] = _initial_state(result["source_actor_features_checkpoint"]["model_state"])
    result["optimizer_state"] = {"schema": "adam-default-betas-eps/v1", "parameters": {}}
    result["progress"] = {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0}
    result["parent_checkpoint_sha256"] = None
    result.pop("initial_checkpoint_sha256", None)
    return result


def build_checkpoint(source_actor_features, training_examples, tuning_examples=(), *, context_contract,
                     objective="conditions-balanced-ce", seed=1729, batch_order_seed=1729,
                     batch_size=12, learning_rate=.001, latent_enabled=False):
    policy = _policy(objective, seed=seed, batch_order_seed=batch_order_seed, batch_size=batch_size)
    _require(type(learning_rate) in (int, float) and learning_rate == .001 and latent_enabled is False,
        "fixed source-only .001 adapter recipe required")
    source = copy.deepcopy(_source(source_actor_features)); _training_records(training_examples, tuning_examples)
    contract = continuation._context_contract(context_contract)
    child = source["initial_continuation_checkpoint"]
    _require(_raw(contract) == _raw(child["context_contract"])
        and checkpoint_digest(training_examples) == source["training_manifest_sha256"], "source context/training identity differs")
    state = _initial_state(source["model_state"])
    result = {"schema": SCHEMA, "lineage_id": LINEAGE_ID, "implementation": _implementation(),
        "training_policy": policy, "training_policy_sha256": checkpoint_digest(policy),
        "initial_training_policy_sha256": checkpoint_digest(policy),
        "source_actor_features_checkpoint": source, "source_actor_features_checkpoint_sha256": SOURCE_ACTOR_FEATURES_SHA256,
        "source_actor_features_model_state_sha256": SOURCE_ACTOR_FEATURES_MODEL_SHA256, "source_actor_features_optimizer_steps": 32,
        "source_parent_checkpoint_sha256": source["source_parent_checkpoint_sha256"],
        "source_parent_model_state_sha256": source["source_parent_model_state_sha256"],
        "initial_continuation_checkpoint": copy.deepcopy(child),
        "initial_continuation_checkpoint_sha256": checkpoint_digest(child),
        "context_contract": contract, "context_contract_sha256": checkpoint_digest(contract),
        "config": copy.deepcopy(source["config"]), "training_manifest_sha256": checkpoint_digest(training_examples),
        "tuning_manifest_sha256": checkpoint_digest(tuning_examples), "training_count": 168, "tuning_count": 0,
        "legacy_prefix_sha256": targeted.LEGACY96_SHA256, "conditions_training_count": 168,
        "conditions_adapter_source_state_map": {name: name.removeprefix("conditions_") for name in TRAINABLE_PARAMETER_NAMES},
        "model_state": state, "initial_branch_digests": _branch_digests(state),
        "optimizer_state": {"schema": "adam-default-betas-eps/v1", "parameters": {}},
        "progress": {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0},
        "parent_checkpoint_sha256": None, **FALSE}
    result["initial_checkpoint_sha256"] = checkpoint_digest(result)
    _require(len(_raw(result)) <= MAX_BYTES, "adapter checkpoint exceeds byte bound")
    return result


def _validated(checkpoint):
    fields = {"schema", "lineage_id", "implementation", "training_policy", "training_policy_sha256",
        "initial_training_policy_sha256", "initial_checkpoint_sha256", "source_actor_features_checkpoint",
        "source_actor_features_checkpoint_sha256", "source_actor_features_model_state_sha256", "source_actor_features_optimizer_steps",
        "source_parent_checkpoint_sha256", "source_parent_model_state_sha256", "initial_continuation_checkpoint",
        "initial_continuation_checkpoint_sha256", "context_contract", "context_contract_sha256", "config",
        "training_manifest_sha256", "tuning_manifest_sha256", "training_count", "tuning_count", "legacy_prefix_sha256",
        "conditions_training_count", "conditions_adapter_source_state_map", "model_state", "initial_branch_digests",
        "optimizer_state", "progress", "parent_checkpoint_sha256", *FALSE}
    _require(type(checkpoint) is dict and set(checkpoint) == fields, "closed adapter checkpoint required")
    _require(checkpoint["schema"] == SCHEMA and checkpoint["lineage_id"] == LINEAGE_ID
        and all(checkpoint[key] is False for key in FALSE) and checkpoint["implementation"] == _implementation()
        and len(_raw(checkpoint)) <= MAX_BYTES, "adapter schema/source/authority/bound differs")
    source = _source(checkpoint["source_actor_features_checkpoint"])
    policy = _validate_policy(checkpoint["training_policy"])
    _require(checkpoint["training_policy_sha256"] == checkpoint["initial_training_policy_sha256"] == checkpoint_digest(policy),
        "immutable adapter policy differs")
    for key, value in {"source_actor_features_checkpoint_sha256": SOURCE_ACTOR_FEATURES_SHA256,
        "source_actor_features_model_state_sha256": SOURCE_ACTOR_FEATURES_MODEL_SHA256, "source_actor_features_optimizer_steps": 32,
        "config": source["config"], "training_manifest_sha256": source["training_manifest_sha256"],
        "source_parent_checkpoint_sha256": source["source_parent_checkpoint_sha256"],
        "source_parent_model_state_sha256": source["source_parent_model_state_sha256"],
        "initial_continuation_checkpoint": source["initial_continuation_checkpoint"],
        "initial_continuation_checkpoint_sha256": checkpoint_digest(source["initial_continuation_checkpoint"]),
        "context_contract": source["initial_continuation_checkpoint"]["context_contract"],
        "context_contract_sha256": source["initial_continuation_checkpoint"]["context_contract_sha256"],
        "training_count": 168, "tuning_count": 0, "tuning_manifest_sha256": checkpoint_digest(()),
        "legacy_prefix_sha256": targeted.LEGACY96_SHA256, "conditions_training_count": 168,
        "conditions_adapter_source_state_map": {name: name.removeprefix("conditions_") for name in TRAINABLE_PARAMETER_NAMES}}.items():
        _require(_raw(checkpoint[key]) == _raw(value), "adapter provenance differs: " + key)
    _require(checkpoint["config"]["latent_dimension"] == 384 and checkpoint["config"]["latent_enabled"] is False
        and checkpoint["config"]["hidden_size"] * 2 == ENCODED_WIDTH, "source-only fixed64 geometry required")
    initial = _initial_state(source["model_state"])
    _require(checkpoint["initial_branch_digests"] == _branch_digests(initial), "initial adapter branch digests differ")
    state = checkpoint["model_state"]
    _require(type(state) is dict and set(state) == set(MODEL_PARAMETER_NAMES), "closed42 state required")
    _require(all(_raw(state[name]) == _raw(source["model_state"][name]) for name in BASE_PARAMETER_NAMES)
        and _raw(_inactive_state(state)) == _raw(_inactive_state(initial)), "frozen base or inactive adapter rows changed")
    for name, dimensions in _trainable_shapes().items():
        _finite_shape(state[name], dimensions, name)
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
    _require(len(records) == len(indices) and 1 <= len(records) <= 12, "complete bounded conditions batch required")
    labels = [int(row["labels"]["presence"][3]) for row in records]
    logits = output["presence"][:, 1, :]
    _require(logits.requires_grad, "conditions logits must remain connected")
    unweighted = torch.nn.functional.cross_entropy(logits, torch.tensor(labels), reduction="none")
    constants = policy["objective_policy"]["class_balance"]["weights"]
    weights = unweighted.new_tensor([constants[label] for label in labels])
    weighted = unweighted * weights
    total = weighted.mean()
    details = {"conditions_cross_entropy_unweighted": float(unweighted.mean().detach()),
        "conditions_cross_entropy_balanced": float(total.detach()), "total_loss": float(total.detach()),
        "batch_denominator": len(records), "batch_class_counts": {"absent": labels.count(0), "present": labels.count(1)},
        "batch_weight_sum": float(weights.sum().detach()),
        "rows": [{"id": row["id"], "training_index": index, "conditions_present": bool(label),
            "conditions_logits": vector, "class_weight": weight, "unweighted_cross_entropy": before,
            "weighted_cross_entropy": after}
            for row, index, label, vector, weight, before, after in zip(records, indices, labels,
                logits.detach().tolist(), weights.detach().tolist(), unweighted.detach().tolist(), weighted.detach().tolist(), strict=True)],
        "teacher_forcing": True, "evaluation_references_used": False, "actor_hinge_applied": False}
    return total, details


def _validate_objective_entry(entry, batch, policy):
    _validate_policy(policy)
    _require(type(entry) is dict and set(entry) == {"optimizer_step", "indices", "ids", "details"}
        and all(entry[key] == batch[key] for key in ("optimizer_step", "indices", "ids")), "conditions objective/batch join differs")
    details = entry["details"]
    _require(type(details) is dict and set(details) == {"conditions_cross_entropy_unweighted", "conditions_cross_entropy_balanced",
        "total_loss", "batch_denominator", "batch_class_counts", "batch_weight_sum", "rows",
        "teacher_forcing", "evaluation_references_used", "actor_hinge_applied"}
        and details["teacher_forcing"] is True and details["evaluation_references_used"] is False
        and details["actor_hinge_applied"] is False and type(details["batch_denominator"]) is int
        and details["batch_denominator"] == len(details["rows"]) == len(entry["indices"]) == len(entry["ids"])
        and 1 <= details["batch_denominator"] <= 12, "closed balanced conditions CE diagnostics required")
    for key in ("conditions_cross_entropy_unweighted", "conditions_cross_entropy_balanced", "total_loss", "batch_weight_sum"):
        _require(type(details[key]) is float and math.isfinite(details[key]) and details[key] >= 0, "finite balanced CE scalar required")
    _require(details["conditions_cross_entropy_balanced"] == details["total_loss"] == batch["loss"], "balanced CE scalar differs")
    counts = {"absent": 0, "present": 0}; weight_sum = 0.
    constants = policy["objective_policy"]["class_balance"]["weights"]
    for row, index, identifier in zip(details["rows"], entry["indices"], entry["ids"], strict=True):
        _require(type(row) is dict and set(row) == {"id", "training_index", "conditions_present", "conditions_logits",
            "class_weight", "unweighted_cross_entropy", "weighted_cross_entropy"}
            and row["id"] == identifier and type(index) is int and 0 <= index < 168 and row["training_index"] == index
            and type(row["conditions_present"]) is bool, "authenticated balanced conditions row required")
        _finite_shape(row["conditions_logits"], (2,), "conditions_logits")
        for key in ("class_weight", "unweighted_cross_entropy", "weighted_cross_entropy"):
            _require(type(row[key]) is float and math.isfinite(row[key]) and row[key] >= 0
                and targeted._f32(row[key]) == row[key], "exact finite binary32 weighted-row trace required")
        label = int(row["conditions_present"])
        _require(row["class_weight"] == targeted._f32(constants[label])
            and row["weighted_cross_entropy"] == targeted._f32(row["unweighted_cross_entropy"] * row["class_weight"]),
            "per-row class weight or CE product differs")
        counts["present" if label else "absent"] += 1; weight_sum += row["class_weight"]
    _require(type(details["batch_class_counts"]) is dict and set(details["batch_class_counts"]) == set(counts)
        and all(type(details["batch_class_counts"][key]) is int for key in counts)
        and details["batch_class_counts"] == counts and abs(details["batch_weight_sum"] - weight_sum) <= 2e-6,
        "actual batch class counts or diagnostic weight sum differs")


def _frozen_head_digest(output):
    return checkpoint_digest({"modality": output["modality"].detach().tolist(),
        "presence_object": output["presence"][:, :1, :].detach().tolist(),
        "presence_exceptions_temporal": output["presence"][:, 2:, :].detach().tolist(),
        "start": output["start"].detach().tolist(), "end": output["end"].detach().tolist()})


def _row_invariants(named, optimizer):
    _require(all(named[name].grad is None for name in BASE_PARAMETER_NAMES), "frozen40 gradient accumulated")
    for name in TRAINABLE_PARAMETER_NAMES:
        parameter = named[name]
        _require(parameter.grad is not None and bool(parameter.grad.isfinite().all()), "finite connected conditions gradient required")
        _require(all(bool((parameter.grad[row] == 0).all()) for row in INACTIVE_ROWS), "inactive conditions gradients nonzero")
        if parameter in optimizer.state:
            for key in ("exp_avg", "exp_avg_sq"):
                moment = optimizer.state[parameter][key]
                _require(bool(moment.isfinite().all()) and all(bool((moment[row] == 0).all()) for row in INACTIVE_ROWS),
                    "inactive conditions moments changed or nonfinite")


def _validate_freeze_entry(entry, batch):
    required = {"optimizer_step", "indices", "ids", "frozen_before", "frozen_after", "inactive_before", "inactive_after",
        "frozen_head_sample_sha256", "frozen_gradients_none", "trainable_gradients_finite_nonNone", "inactive_gradients_zero",
        "inactive_moments_zero", "changed_parameter_names", "completed_returned_update", "branch_digests_before", "branch_digests_after"}
    _require(type(entry) is dict and set(entry) == required and all(entry[k] == batch[k] for k in ("optimizer_step", "indices", "ids")),
        "closed freeze/batch trace join differs")
    for key in ("frozen_gradients_none", "trainable_gradients_finite_nonNone", "inactive_gradients_zero", "inactive_moments_zero", "completed_returned_update"):
        _require(entry[key] is True, "returned conditions update invariants required")
    _require(entry["frozen_before"] == entry["frozen_after"] == SOURCE_ACTOR_FEATURES_MODEL_SHA256
        and entry["inactive_before"] == entry["inactive_after"] and type(entry["changed_parameter_names"]) is list
        and len(entry["changed_parameter_names"]) == len(set(entry["changed_parameter_names"]))
        and set(entry["changed_parameter_names"]) <= set(TRAINABLE_PARAMETER_NAMES), "frozen/unknown conditions parameters changed")
    before, after = entry["branch_digests_before"], entry["branch_digests_after"]
    expected = {"modality_feature_state_sha256", "span_feature_state_sha256", "modality_path_state_sha256", "span_path_state_sha256",
        "dormant_latent_state_sha256", "frozen_base34_state_sha256", "actor_head_state_sha256", "inactive_actor_head_rows_sha256",
        "actor_attention_query_sha256", "actor_context_gate_sha256", "frozen_parent40_state_sha256",
        "conditions_presence_state_sha256", "inactive_conditions_presence_rows_sha256"}
    _require(type(before) is dict and type(after) is dict and set(before) == set(after) == expected
        and all(before[k] == after[k] for k in expected - {"conditions_presence_state_sha256"})
        and before["frozen_parent40_state_sha256"] == SOURCE_ACTOR_FEATURES_MODEL_SHA256
        and before["inactive_conditions_presence_rows_sha256"] == entry["inactive_before"], "parent/branch values changed")
    for value in (*before.values(), *after.values(), entry["frozen_head_sample_sha256"]):
        _require(type(value) is str and span._SHA.fullmatch(value), "raw branch digest required")



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
    forward_counts_before = dict(model._conditions_forward_accounting)
    batches, objectives, freezes, losses = [], [], [], []; maximum_gradient = 0.; reason = "step_limit"
    for _ in range(max_steps):
        if time.monotonic() >= deadline: reason = "deadline_before_batch"; break
        before_progress = dict(progress); indices = targeted._batch_indices(168, progress, 12, 1729)
        batch = [records[index] for index in indices]
        model.train(); optimizer.zero_grad(set_to_none=True)
        _require(all(named[name].grad is None for name in BASE_PARAMETER_NAMES), "frozen40 preupdate gradient accumulated")
        before_state = {name: p.detach().tolist() for name, p in model.state_dict().items()}
        branch_before = _branch_digests(before_state)
        _require(branch_before["frozen_parent40_state_sha256"] == SOURCE_ACTOR_FEATURES_MODEL_SHA256, "frozen40 preupdate drift")
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
            "frozen_before": branch_before["frozen_parent40_state_sha256"], "frozen_after": branch_after["frozen_parent40_state_sha256"],
            "inactive_before": branch_before["inactive_conditions_presence_rows_sha256"], "inactive_after": branch_after["inactive_conditions_presence_rows_sha256"],
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
    initial_origin = _initial_state(checkpoint["source_actor_features_checkpoint"]["model_state"])
    final_branches = _branch_digests(weights)
    forward_counts = {key: model._conditions_forward_accounting[key] - forward_counts_before[key] for key in forward_counts_before}
    _require(all(count == len(losses) for count in forward_counts.values()), "actual actor training forward counts differ")
    report = {"schema": "bounded-conditions-balanced-adapter-training/v1", "checkpoint_sha256": checkpoint_digest(updated),
        "previous_conditions_adapter_checkpoint_sha256": checkpoint_digest(checkpoint),
        "initial_checkpoint_sha256": checkpoint["initial_checkpoint_sha256"],
        "source_actor_features_checkpoint_sha256": SOURCE_ACTOR_FEATURES_SHA256, "source_actor_features_model_state_sha256": SOURCE_ACTOR_FEATURES_MODEL_SHA256,
        "source_actor_features_optimizer_steps": 32, "source_parent_checkpoint_sha256": checkpoint["source_parent_checkpoint_sha256"],
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
        "batch_losses": losses, "batch_trace": targeted._trace_summary(batches, initial_progress, progress, targeted._policy(1729, actor_ranking_enabled=False, presence_ce_weight=1, batch_order_seed=1729, batch_size=12), training_examples),
        "objective_trace": {"schema": "completed-conditions-balanced-adapter-objective-trace/v1", "completed_updates": len(objectives),
            "batches": objectives, "batches_sha256": checkpoint_digest(objectives), "evaluation_references_used": False,
            "independent_numerical_kernel_trace": False},
        "freeze_trace": {"schema": "completed-conditions-balanced-adapter-freeze-trace/v1", "completed_updates": len(freezes),
            "batches": freezes, "batches_sha256": checkpoint_digest(freezes), "independent_numerical_kernel_trace": False},
        "frozen_parent40_sha256_initial": initial_branches["frozen_parent40_state_sha256"],
        "frozen_parent40_sha256_final": final_branches["frozen_parent40_state_sha256"],
        "inactive_head_rows_sha256_initial": initial_branches["inactive_conditions_presence_rows_sha256"],
        "inactive_head_rows_sha256_final": final_branches["inactive_conditions_presence_rows_sha256"],
        "frozen_parameters_sha256_initial": initial_branches["frozen_parent40_state_sha256"],
        "frozen_parameters_sha256_final": final_branches["frozen_parent40_state_sha256"],
        "legacy_prefix_sha256": targeted.LEGACY96_SHA256, "conditions_training_count": 168,
        "training_conditions_class_counts": _conditions_class_counts(records),
        "conditions_adapter_source_state_map": checkpoint["conditions_adapter_source_state_map"],
        "gradient_norm_max": maximum_gradient, "changed_parameter_names": [name for name in MODEL_PARAMETER_NAMES if weights[name] != initial_state[name]],
        "stopped_reason": reason, "elapsed_seconds": time.monotonic()-started,
        "deadline_scope": "soft_boundary_before_numeric_batch; initialization_and_serialization_not_interruptible",
        "partial_failure_scope": "only_successfully_returned_prefix_traced; unreturned_partial_failure_unknown",
        "forward_accounting": {"schema": "conditions-balanced-adapter-training-forward-accounting/v1",
            "training_model_forward_calls": forward_counts["source_model_forwards"],
            "training_frozen_actor_features_model_calls": forward_counts["frozen_actor_features_model_forwards"],
            "training_modality_encoder_calls": forward_counts["frozen_modality_encoder_forwards"],
            "training_span_encoder_calls": forward_counts["frozen_span_encoder_forwards"] + forward_counts["additional_frozen_span_encoder_forwards"],
            "training_conditions_presence_head_calls": forward_counts["conditions_presence_head_forwards"],
            "actual_model_counter_deltas": forward_counts, "training_source_row_occurrences": sum(len(b["indices"]) for b in batches),
            "tuning_model_forward_calls": 0, "teacher_model_forward_calls": 0, "restore_validation_and_external_evaluation_forwards_included": False},
        "tuning": {"rows_evaluated": 0, "used_for_fit_or_selection": False}, **FALSE}
    return {"checkpoint": updated, "report": report}


class SpanConditionsBalancedAdapterDecoder:
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
        forward_counts_before = dict(self.model._conditions_forward_accounting)
        rows = [self._inference_view._decode(text, vector, enabled=latent_ablation != "disabled")
            for text, vector in zip(texts, vectors, strict=True)]
        _require(_state_digest(self.model) == self._expected_model_sha256
            and _raw(_implementation()) == self._implementation_snapshot, "inference changed source or model")
        forward_counts = {key: self.model._conditions_forward_accounting[key] - forward_counts_before[key] for key in forward_counts_before}
        _require(all(value == len(rows) for value in forward_counts.values()), "actual actor inference forward counts differ")
        count = sum(row["status"] == "decoded" for row in rows)
        child = self.checkpoint["initial_continuation_checkpoint"]
        return {"schema": "bounded-conditions-balanced-adapter-inference/v1", "lineage_id": LINEAGE_ID,
            "checkpoint_sha256": self.checkpoint_sha256, "initial_continuation_checkpoint_sha256": checkpoint_digest(child),
            "source_parent_checkpoint_sha256": child["source_parent_checkpoint_sha256"], "source_parent_optimizer_steps": 400, "source_actor_features_optimizer_steps": 32,
            "source_actor_features_checkpoint_sha256": SOURCE_ACTOR_FEATURES_SHA256, "source_actor_features_model_state_sha256": SOURCE_ACTOR_FEATURES_MODEL_SHA256,
            "context_contract_sha256": child["context_contract_sha256"], "model_state_sha256": self._expected_model_sha256,
            "training_policy": copy.deepcopy(self._policy), "training_policy_sha256": checkpoint_digest(self._policy),
            "rows": rows, "decoded_count": count, "status": "decoded" if count == len(rows) else "partial" if count else "abstained",
            "latent_ablation": latent_ablation, "target_access": False, "teacher_forcing": False,
            "training_executed": False, "legacy_single_source_readout_unchanged": True, "feature_paths_per_source_forward": 3, "split_feature_model_forward": True, "conditions_presence_adapter_model_forward": True,
            "branch_digests": _branch_digests(self.checkpoint["model_state"]),
            **forward_counts, **FALSE}


def captured_inference(torch, span, warm, checkpoint, rows, *, control="none"):
    """Capture same-forward heads without exposing labels to inference."""
    _require(span is globals()["span"] and warm is continuation, "exact unchanged source owners required")
    _require(type(rows) in (list, tuple) and 1 <= len(rows) <= 128, "one to128 bounded capture source rows required")
    decoder = SpanConditionsBalancedAdapterDecoder(checkpoint)
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
    _require(all(report[key] == len(rows) for key in decoder.model._conditions_forward_accounting), "actual capture forward accounting differs")
    observer = sys.modules["ipfs_datasets_py.logic.formalization.autoencoder.retained_span_score_capture"]
    for source, scores, raw in zip(sources, captures, report["rows"], strict=True):
        _require(raw["source_sha256"] == hashlib.sha256(source["source_text"].encode()).hexdigest(), "raw source identity differs")
        observer._verify_greedy(source["source_text"], scores, raw)
    return {"schema": "conditions-balanced-adapter-target-free-head-capture/v1", "inference": report,
        "occurrences": [{"id": source["id"], "source_sha256": hashlib.sha256(source["source_text"].encode()).hexdigest(), "scores": scores}
            for source, scores in zip(sources, captures, strict=True)], "actual_source_forwards": len(rows), "source_model_forwards": len(rows),
        "frozen_actor_features_model_forwards": len(rows), "frozen_modality_encoder_forwards": len(rows),
        "frozen_span_encoder_forwards": len(rows), "additional_frozen_span_encoder_forwards": len(rows),
        "conditions_presence_head_forwards": len(rows), "extra_capture_forwards": 0,
        "target_access": False, "teacher_forcing": False, "model_weights_unchanged": True,
        "original_greedy_observations_verified": True, "ambient_CPU_RNG_preserved": True, **FALSE}


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
            "modality_encoder_forwards": 8, "span_encoder_forwards": 16, "feature_paths_per_source_forward": 3, **FALSE})


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
