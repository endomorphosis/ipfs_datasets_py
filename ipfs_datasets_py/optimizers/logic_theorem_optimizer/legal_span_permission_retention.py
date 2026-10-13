"""Matched full versus facet-head updates with an explicit permission boundary.

The source-only400 parent, objective, data schedule and legacy readout are
unchanged. The facet-head arm freezes every shared feature and modality tensor;
its Adam state contains only the six actual trainable head tensors. This new
outer owns that state. It never labels subset moments as an old span checkpoint.
These authored-supervision experiments confer no statutory or proof authority.
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

from . import legal_span_continuation as continuation
from . import legal_span_formula as span
from . import legal_span_targeted_loss as targeted

SCHEMA = "bounded-permission-retention-span-legal-formula-checkpoint/v1"
LINEAGE_ID = "bounded_source_span_permission_retention_v1"
POLICY_SCHEMA = "bounded-source-span-permission-retention-policy/v1"
MAX_BYTES, MAX_NEW_STEPS, MAX_SECONDS = targeted.MAX_BYTES, 32, 32
FALSE = span.FALSE
_require, _raw, checkpoint_digest = span._require, span._raw, span.checkpoint_digest
MODEL_PARAMETER_NAMES = (
    "byte_embedding.weight", "token_projection.weight", "token_projection.bias",
    "encoder.weight_ih_l0", "encoder.weight_hh_l0", "encoder.bias_ih_l0", "encoder.bias_hh_l0",
    "encoder.weight_ih_l0_reverse", "encoder.weight_hh_l0_reverse",
    "encoder.bias_ih_l0_reverse", "encoder.bias_hh_l0_reverse",
    "modality.weight", "modality.bias", "presence.weight", "presence.bias",
    "start.weight", "start.bias", "end.weight", "end.bias",
    "latent_down.weight", "latent_down.bias", "latent_up.weight", "latent_up.bias",
)
FACET_PARAMETER_NAMES = ("presence.weight", "presence.bias", "start.weight", "start.bias", "end.weight", "end.bias")


def _partition(mode):
    _require(type(mode) is str and mode in ("all-parameters", "span-heads-only"), "closed trainable parameter policy required")
    trainable = MODEL_PARAMETER_NAMES if mode == "all-parameters" else FACET_PARAMETER_NAMES
    frozen = tuple(name for name in MODEL_PARAMETER_NAMES if name not in trainable)
    return {"model_parameter_names": list(MODEL_PARAMETER_NAMES), "trainable_parameter_names": list(trainable),
        "frozen_parameter_names": list(frozen), "optimizer_parameter_order": list(trainable),
        "shared_features_and_modality_frozen": mode == "span-heads-only"}


def _policy(mode, *, batch_order_seed=1729, seed=1729, batch_size=12):
    _require(type(batch_order_seed) is int and batch_order_seed == 1729 and type(seed) is int and seed == 1729
        and type(batch_size) is int and batch_size == 12, "fixed1729/12 matched recipe required")
    return {"schema": POLICY_SCHEMA, "trainable_parameter_policy": mode, "parameter_partition": _partition(mode),
        "objective_policy": targeted._policy(seed, actor_ranking_enabled=False, presence_ce_weight=1,
            batch_order_seed=batch_order_seed, batch_size=batch_size),
        "initialization": "copy_exact_source_only400_weights_fresh_adam_over_ordered_trainable_subset/v1",
        "frozen_parameter_gradients": "None_required_before_and_after_every_completed_update",
        "trainable_parameter_gradients": "finite_nonNone_required_including_zero_gated_latent_tensors",
        "frozen_state_evidence": "canonical_JSON_parameter_values_sha256_before_after_each_returned_update",
        "modality_evidence": "same_batch_pre_post_update_float32_vectors_for_every_completed_training_occurrence",
        "frozen_modality_scope": "unchanged_shared_features_and_modality_tensors_for_identical_source_inputs",
        "full_IR_retention_guaranteed": False, "latent_enabled": False, "latent_dimension": 384,
        "max_new_optimizer_steps": MAX_NEW_STEPS, "max_seconds": MAX_SECONDS,
        "automatic_selection_or_promotion": False, "independent_legal_gold": False}


def _validate_policy(policy):
    _require(type(policy) is dict and "trainable_parameter_policy" in policy, "closed permission retention policy required")
    expected = _policy(policy["trainable_parameter_policy"])
    _require(_raw(policy) == _raw(expected), "permission retention policy differs")
    return copy.deepcopy(expected)


def _capture_implementation():
    return {"permission_retention_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "targeted_loss": targeted._implementation(), "continuation": continuation._implementation(),
        "span": span._implementation()}


_IMPLEMENTATION_AT_IMPORT = _capture_implementation()


def _implementation():
    result = _capture_implementation()
    _require(result == _IMPLEMENTATION_AT_IMPORT, "permission retention source changed since import")
    return result


def _state_digest(model, names=MODEL_PARAMETER_NAMES):
    state = model.state_dict()
    _require(set(state) == set(MODEL_PARAMETER_NAMES), "closed model parameter state required")
    return checkpoint_digest({name: state[name].detach().tolist() for name in names})


def _configure_parameters(model, partition):
    named = dict(model.named_parameters())
    _require(tuple(named) == MODEL_PARAMETER_NAMES and _raw(partition) == _raw(_partition(
        "span-heads-only" if partition["shared_features_and_modality_frozen"] else "all-parameters")),
        "actual named parameter partition differs")
    trainable = partition["trainable_parameter_names"]
    for name, parameter in named.items():
        parameter.requires_grad_(name in trainable)
        parameter.grad = None
    selected = [named[name] for name in partition["optimizer_parameter_order"]]
    _require(len(selected) == len({id(value) for value in selected}), "optimizer parameter alias refused")
    return named, selected


def _validate_optimizer_state(state, partition, steps):
    _require(type(state) is dict and set(state) == {"schema", "parameters"}
        and state["schema"] == "adam-default-betas-eps/v1" and type(state["parameters"]) is dict,
        "closed subset Adam state required")
    expected = set(partition["trainable_parameter_names"]) if steps else set()
    _require(set(state["parameters"]) == expected, "optimizer moments must name exactly the actual trainable subset")
    for moment in state["parameters"].values():
        _require(type(moment) is dict and set(moment) == {"step", "exp_avg", "exp_avg_sq"}
            and type(moment["step"]) is int and moment["step"] == steps, "subset Adam moment step differs")


def _origin(checkpoint):
    result = copy.deepcopy(checkpoint)
    initial = result["initial_continuation_checkpoint"]["base_checkpoint"]
    result["model_state"] = copy.deepcopy(initial["model_state"])
    result["optimizer_state"] = {"schema": "adam-default-betas-eps/v1", "parameters": {}}
    result["progress"] = {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0}
    result["parent_checkpoint_sha256"] = None
    result.pop("initial_checkpoint_sha256", None)
    return result


def build_checkpoint(parent, training_examples, tuning_examples=(), *, context_contract,
                     trainable_parameter_policy="all-parameters", batch_order_seed=1729, seed=1729,
                     learning_rate=.001, batch_size=12, latent_enabled=False):
    policy = _policy(trainable_parameter_policy, batch_order_seed=batch_order_seed, seed=seed, batch_size=batch_size)
    # The unchanged targeted constructor authenticates the exact400 parent and
    # bounded168-row supervision. Only its immutable zero-update child is kept.
    initial_targeted = targeted.build_checkpoint(parent, training_examples, tuning_examples,
        context_contract=context_contract, actor_ranking_enabled=False, presence_ce_weight=1,
        batch_order_seed=batch_order_seed, seed=seed, learning_rate=learning_rate,
        batch_size=batch_size, latent_enabled=latent_enabled)
    child = copy.deepcopy(initial_targeted["continuation_checkpoint"])
    base = child["base_checkpoint"]
    result = {"schema": SCHEMA, "lineage_id": LINEAGE_ID, "implementation": _implementation(),
        "training_policy": policy, "training_policy_sha256": checkpoint_digest(policy),
        "initial_training_policy_sha256": checkpoint_digest(policy),
        "initial_continuation_checkpoint": child, "initial_continuation_checkpoint_sha256": checkpoint_digest(child),
        "source_parent_checkpoint_sha256": child["source_parent_checkpoint_sha256"],
        "source_parent_model_state_sha256": child["initial_model_state_sha256"],
        "config": copy.deepcopy(base["config"]), "training_manifest_sha256": base["training_manifest_sha256"],
        "tuning_manifest_sha256": base["tuning_manifest_sha256"], "training_count": base["training_count"],
        "tuning_count": base["tuning_count"], "model_state": copy.deepcopy(base["model_state"]),
        "optimizer_state": {"schema": "adam-default-betas-eps/v1", "parameters": {}},
        "progress": dict(base["progress"]), "parent_checkpoint_sha256": None, **FALSE}
    result["initial_checkpoint_sha256"] = checkpoint_digest(result)
    _require(len(_raw(result)) <= MAX_BYTES, "permission retention checkpoint exceeds bound")
    return result


def _validated(checkpoint):
    fields = {"schema", "lineage_id", "implementation", "training_policy", "training_policy_sha256",
        "initial_training_policy_sha256", "initial_checkpoint_sha256", "initial_continuation_checkpoint",
        "initial_continuation_checkpoint_sha256", "source_parent_checkpoint_sha256", "source_parent_model_state_sha256",
        "config", "training_manifest_sha256", "tuning_manifest_sha256", "training_count", "tuning_count",
        "model_state", "optimizer_state", "progress", "parent_checkpoint_sha256", *FALSE}
    _require(type(checkpoint) is dict and set(checkpoint) == fields, "closed permission retention checkpoint required")
    _require(checkpoint["schema"] == SCHEMA and checkpoint["lineage_id"] == LINEAGE_ID
        and all(checkpoint[key] is False for key in FALSE), "permission retention schema or authority differs")
    _require(len(_raw(checkpoint)) <= MAX_BYTES and checkpoint["implementation"] == _implementation(),
        "permission retention source or byte bound differs")
    policy = _validate_policy(checkpoint["training_policy"])
    _require(checkpoint["training_policy_sha256"] == checkpoint["initial_training_policy_sha256"] == checkpoint_digest(policy),
        "original immutable parameter/objective policy differs")
    child = checkpoint["initial_continuation_checkpoint"]
    initial = continuation._validated(child)
    _require(child["source_parent_checkpoint_sha256"] == targeted.SOURCE_PARENT_SHA256
        and child["initial_model_state_sha256"] == targeted.SOURCE_MODEL_SHA256
        and child["source_parent_optimizer_steps"] == 400
        and child["parent_checkpoint_sha256"] is None
        and initial["progress"] == dict(epochs_completed=0, row_cursor=0, optimizer_steps=0)
        and initial["optimizer_state"] == dict(schema="adam-default-betas-eps/v1", parameters={}),
        "immutable exact400 zero-update initialization required")
    _require(checkpoint["initial_continuation_checkpoint_sha256"] == checkpoint_digest(child)
        and checkpoint["source_parent_checkpoint_sha256"] == child["source_parent_checkpoint_sha256"]
        and checkpoint["source_parent_model_state_sha256"] == child["initial_model_state_sha256"],
        "initial continuation and source provenance differ")
    for key in ("config", "training_manifest_sha256", "tuning_manifest_sha256", "training_count", "tuning_count"):
        _require(_raw(checkpoint[key]) == _raw(initial[key]), "initial training boundary differs: " + key)
    _require(checkpoint["config"]["latent_dimension"] == 384 and checkpoint["config"]["latent_enabled"] is False
        and checkpoint["config"]["seed"] == 1729 and checkpoint["config"]["learning_rate"] == .001
        and checkpoint["config"]["batch_size"] == 12 and checkpoint["training_count"] == 168,
        "fixed matched source-only recipe differs")
    progress = targeted._progress(checkpoint["progress"])
    _require(progress["optimizer_steps"] <= MAX_NEW_STEPS, "permission retention update bound exceeded")
    targeted._batch_indices(checkpoint["training_count"], progress, 12, 1729)
    previous = checkpoint["parent_checkpoint_sha256"]
    _require(previous is None or type(previous) is str and span._SHA.fullmatch(previous), "invalid prior checkpoint hash")
    if progress["optimizer_steps"]:
        _require(previous is not None, "trained permission checkpoint requires preceding outer hash")
    else:
        _require(previous is None and checkpoint["model_state"] == initial["model_state"], "zero-update state differs")
    _require(checkpoint["initial_checkpoint_sha256"] == checkpoint_digest(_origin(checkpoint)),
        "initial outer provenance boundary differs")
    partition = policy["parameter_partition"]
    _require(type(checkpoint["model_state"]) is dict and set(checkpoint["model_state"]) == set(MODEL_PARAMETER_NAMES),
        "closed live model state required")
    frozen = partition["frozen_parameter_names"]
    _require(all(_raw(checkpoint["model_state"][name]) == _raw(initial["model_state"][name]) for name in frozen),
        "frozen parameter changed from the source parent")
    _validate_optimizer_state(checkpoint["optimizer_state"], partition, progress["optimizer_steps"])
    return initial, policy


def _restore(checkpoint):
    import torch
    _, policy = _validated(checkpoint)
    model = span._model(torch, checkpoint["config"])
    template = model.state_dict()
    model.load_state_dict({name: span._tensor(torch, checkpoint["model_state"][name], value.shape, name)
        for name, value in template.items()}, strict=True)
    named, selected = _configure_parameters(model, policy["parameter_partition"])
    optimizer = torch.optim.Adam(selected, lr=.001, foreach=False)
    for name, moment in checkpoint["optimizer_state"]["parameters"].items():
        parameter = named[name]
        optimizer.state[parameter] = {"step": torch.tensor(float(moment["step"])),
            "exp_avg": span._tensor(torch, moment["exp_avg"], parameter.shape, name),
            "exp_avg_sq": span._tensor(torch, moment["exp_avg_sq"], parameter.shape, name, nonnegative=True)}
    model.eval()
    return torch, model, optimizer


def validate_checkpoint(checkpoint):
    _restore(checkpoint)


def _modal_rows(records, logits):
    _require(type(logits) is list and len(logits) == len(records), "complete modality row coverage required")
    result = []
    for record, vector in zip(records, logits, strict=True):
        _require(type(vector) is list and len(vector) == 3
            and all(type(value) is float and math.isfinite(value) and targeted._f32(value) == value for value in vector),
            "exact finite float32 modality vectors required")
        result.append({"id": record["id"], "source_sha256": hashlib.sha256(record["source_text"].encode()).hexdigest(),
            "modality_logits": vector})
    return result


def _freeze_entry(step, indices, records, partition, before, after, changed, before_modal, after_modal):
    _require(type(step) is int and 1 <= step <= MAX_NEW_STEPS and len(indices) == len(records)
        and len(set(indices)) == len(indices), "completed freeze update geometry differs")
    _require(type(before) is str and span._SHA.fullmatch(before) and type(after) is str and span._SHA.fullmatch(after),
        "frozen parameter digests required")
    _require(type(changed) is list and len(set(changed)) == len(changed)
        and set(changed) <= set(partition["trainable_parameter_names"]), "updated frozen or unknown parameter")
    _require(before == after, "frozen parameter digest changed during optimizer update")
    left, right = _modal_rows(records, before_modal), _modal_rows(records, after_modal)
    equal = _raw(left) == _raw(right)
    _require(equal or not partition["shared_features_and_modality_frozen"], "frozen shared features changed modality scores")
    return {"schema": "completed-permission-retention-freeze-batch/v1", "optimizer_step": step,
        "indices": list(indices), "ids": [record["id"] for record in records],
        "frozen_parameter_names": list(partition["frozen_parameter_names"]),
        "trainable_parameter_names": list(partition["trainable_parameter_names"]),
        "optimizer_parameter_order": list(partition["optimizer_parameter_order"]),
        "frozen_parameters_sha256_before": before, "frozen_parameters_sha256_after": after,
        "frozen_gradients_none_before_and_after": True, "trainable_gradients_finite_nonNone": True,
        "changed_parameter_names": list(changed), "modality_before": left, "modality_after": right,
        "same_batch_modality_logits_bit_equal": equal, "completed_returned_optimizer_update": True}


def _freeze_summary(entries, batches, partition):
    _require(type(entries) is list and len(entries) == len(batches), "freeze trace and completed update counts differ")
    fields = {"schema", "optimizer_step", "indices", "ids", "frozen_parameter_names", "trainable_parameter_names",
        "optimizer_parameter_order", "frozen_parameters_sha256_before", "frozen_parameters_sha256_after",
        "frozen_gradients_none_before_and_after", "trainable_gradients_finite_nonNone", "changed_parameter_names",
        "modality_before", "modality_after", "same_batch_modality_logits_bit_equal", "completed_returned_optimizer_update"}
    for entry, batch in zip(entries, batches, strict=True):
        _require(type(entry) is dict and set(entry) == fields
            and entry["schema"] == "completed-permission-retention-freeze-batch/v1"
            and all(entry[key] == batch[key] for key in ("optimizer_step", "indices", "ids")),
            "freeze trace completed-batch join differs")
        _require(entry["frozen_parameter_names"] == partition["frozen_parameter_names"]
            and entry["trainable_parameter_names"] == partition["trainable_parameter_names"]
            and entry["optimizer_parameter_order"] == partition["optimizer_parameter_order"], "freeze trace partition differs")
        _require(entry["frozen_parameters_sha256_before"] == entry["frozen_parameters_sha256_after"]
            and type(entry["frozen_parameters_sha256_before"]) is str
            and span._SHA.fullmatch(entry["frozen_parameters_sha256_before"])
            and all(entry[key] is True for key in ("frozen_gradients_none_before_and_after",
                "trainable_gradients_finite_nonNone", "completed_returned_optimizer_update"))
            and type(entry["changed_parameter_names"]) is list
            and len(set(entry["changed_parameter_names"])) == len(entry["changed_parameter_names"])
            and set(entry["changed_parameter_names"]) <= set(partition["trainable_parameter_names"]),
            "freeze trace state, gradients or changed parameters differ")
        for key in ("modality_before", "modality_after"):
            _require(type(entry[key]) is list and [row["id"] for row in entry[key]] == entry["ids"],
                "freeze trace modality IDs differ")
            for row in entry[key]:
                _require(type(row) is dict and set(row) == {"id", "source_sha256", "modality_logits"}
                    and type(row["source_sha256"]) is str and span._SHA.fullmatch(row["source_sha256"])
                    and type(row["modality_logits"]) is list and len(row["modality_logits"]) == 3
                    and all(type(value) is float and math.isfinite(value) and targeted._f32(value) == value
                        for value in row["modality_logits"]), "freeze trace modality vector differs")
        _require([row["source_sha256"] for row in entry["modality_before"]]
            == [row["source_sha256"] for row in entry["modality_after"]], "freeze trace modality source joins differ")
        equal = _raw(entry["modality_before"]) == _raw(entry["modality_after"])
        _require(type(entry["same_batch_modality_logits_bit_equal"]) is bool
            and entry["same_batch_modality_logits_bit_equal"] is equal
            and (equal or not partition["shared_features_and_modality_frozen"]), "freeze trace modality parity differs")
    _require(len({entry["frozen_parameters_sha256_before"] for entry in entries}) <= 1,
        "frozen state differs between completed update boundaries")
    return {"schema": "completed-permission-retention-freeze-trace/v1", "completed_updates": len(entries),
        "batches": entries, "batches_sha256": checkpoint_digest(entries), "parameter_partition": copy.deepcopy(partition),
        "scope": "trainer_observed_same_batch_pre_post_scores_and_frozen_state_after_returned_finite_optimizer_updates",
        "independent_tensor_custody_attested": False, "evaluation_references_used": False}


def train_decoder(checkpoint, training_examples, tuning_examples=(), *, max_steps=32, max_seconds=32):
    _require(type(max_steps) is int and 0 <= max_steps <= MAX_NEW_STEPS, "max_steps must be integer0..32")
    _require(type(max_seconds) in (int, float) and math.isfinite(max_seconds) and 0 <= max_seconds <= MAX_SECONDS,
        "max_seconds must be0..32")
    started = time.monotonic(); deadline = started + max_seconds
    _, policy = _validated(checkpoint)
    progress = dict(checkpoint["progress"]); initial_progress = dict(progress)
    _require(progress["optimizer_steps"] + max_steps <= MAX_NEW_STEPS, "resumption exceeds32 total new updates")
    _require(checkpoint["training_manifest_sha256"] == checkpoint_digest(training_examples)
        and checkpoint["tuning_manifest_sha256"] == checkpoint_digest(tuning_examples), "resume manifests differ")
    records, tuning = targeted._bounded_splits(training_examples, tuning_examples)
    torch, model, optimizer = _restore(checkpoint)
    partition = policy["parameter_partition"]; named = dict(model.named_parameters())
    selected = [named[name] for name in partition["optimizer_parameter_order"]]
    frozen = [named[name] for name in partition["frozen_parameter_names"]]
    origin_frozen = _state_digest(model, partition["frozen_parameter_names"])
    initial_model = _state_digest(model)
    batches, objective_entries, freeze_entries, losses = [], [], [], []
    maximum_gradient, reason = 0., "step_limit"
    for _ in range(max_steps):
        if time.monotonic() >= deadline:
            reason = "deadline_before_batch"; break
        before_progress = dict(progress)
        indices = targeted._batch_indices(len(records), progress, 12, 1729)
        batch = [records[index] for index in indices]
        model.train(); optimizer.zero_grad(set_to_none=True)
        _require(all(parameter.grad is None for parameter in frozen), "frozen gradients must remainNone")
        before_state = {name: value.detach().tolist() for name, value in model.state_dict().items()}
        frozen_before = _state_digest(model, partition["frozen_parameter_names"])
        _require(frozen_before == origin_frozen, "frozen state drift before update")
        output = model(*span._batch(torch, batch))
        before_modal = output["modality"].detach().tolist()
        loss, objective = targeted._loss(torch, lambda *_: output, batch, policy["objective_policy"])
        _require(bool(torch.isfinite(loss)), "nonfinite permission retention loss")
        loss.backward()
        _require(all(parameter.grad is not None and bool(torch.isfinite(parameter.grad).all()) for parameter in selected),
            "missing or nonfinite trainable gradients")
        _require(all(parameter.grad is None for parameter in frozen), "frozen gradient accumulated")
        gradient = float(torch.nn.utils.clip_grad_norm_(selected, 5, error_if_nonfinite=True))
        maximum_gradient = max(maximum_gradient, gradient)
        optimizer.step()
        _require(all(bool(torch.isfinite(parameter).all()) for parameter in named.values()), "nonfinite updated weights")
        _require(all(bool(torch.isfinite(value).all()) for moment in optimizer.state.values()
            for value in moment.values() if torch.is_tensor(value)), "nonfinite subset Adam moments")
        _require(all(parameter.grad is None for parameter in frozen), "frozen gradient changed after step")
        with torch.no_grad():
            after_modal = model(*span._batch(torch, batch))["modality"].tolist()
        frozen_after = _state_digest(model, partition["frozen_parameter_names"])
        after_state = {name: value.detach().tolist() for name, value in model.state_dict().items()}
        changed = [name for name in MODEL_PARAMETER_NAMES if before_state[name] != after_state[name]]
        progress = targeted._advance_progress(before_progress, len(indices), len(records))
        scalar_loss = float(loss.detach()); losses.append(scalar_loss)
        batches.append(targeted._batch_trace_entry(indices, training_examples, before_progress, progress,
            loss=scalar_loss, gradient_norm=gradient))
        objective_entries.append(targeted._objective_trace_entry(indices, training_examples, progress["optimizer_steps"], objective))
        freeze_entries.append(_freeze_entry(progress["optimizer_steps"], indices, batch, partition,
            frozen_before, frozen_after, changed, before_modal, after_modal))
    model.eval(); total, measured = 0., 0
    with torch.no_grad():
        for start in range(0, len(tuning), 12):
            if time.monotonic() >= deadline: break
            batch = tuning[start:start + 12]
            loss, _ = targeted._loss(torch, model, batch, policy["objective_policy"])
            _require(bool(torch.isfinite(loss)), "nonfinite tuning loss")
            total += float(loss) * len(batch); measured += len(batch)
    weights, moments = span._pack(model, optimizer)
    _validate_optimizer_state(moments, partition, progress["optimizer_steps"])
    updated = {**copy.deepcopy(checkpoint), "model_state": weights, "optimizer_state": moments,
        "progress": progress, "parent_checkpoint_sha256": checkpoint_digest(checkpoint)}
    # A zero-update call preserves the actual initial lineage rather than
    # inventing a preceding trained boundary.
    if not losses: updated["parent_checkpoint_sha256"] = checkpoint["parent_checkpoint_sha256"]
    _validated(updated)
    _require(_implementation() == checkpoint["implementation"], "producer changed during training")
    final_model = _state_digest(model)
    report = {"schema": "bounded-permission-retention-span-legal-formula-training/v1",
        "checkpoint_sha256": checkpoint_digest(updated), "previous_permission_checkpoint_sha256": checkpoint_digest(checkpoint),
        "initial_checkpoint_sha256": checkpoint["initial_checkpoint_sha256"],
        "initial_continuation_checkpoint_sha256": checkpoint["initial_continuation_checkpoint_sha256"],
        "source_parent_checkpoint_sha256": checkpoint["source_parent_checkpoint_sha256"],
        "source_parent_model_state_sha256": checkpoint["source_parent_model_state_sha256"],
        "initial_model_state_sha256": checkpoint["source_parent_model_state_sha256"],
        "training_call_initial_model_state_sha256": initial_model, "final_model_state_sha256": final_model,
        "training_policy": copy.deepcopy(policy), "training_policy_sha256": checkpoint_digest(policy),
        "parameter_partition": copy.deepcopy(partition), "optimizer_steps": len(losses),
        "continuation_optimizer_steps_total": progress["optimizer_steps"], "training_executed": bool(losses),
        "batch_losses": losses, "batch_trace": targeted._trace_summary(batches, initial_progress, progress,
            policy["objective_policy"], training_examples),
        "objective_trace": targeted._objective_trace_summary(objective_entries, batches, policy["objective_policy"]),
        "freeze_trace": _freeze_summary(freeze_entries, batches, partition),
        "frozen_parameters_sha256_initial": origin_frozen,
        "frozen_parameters_sha256_final": _state_digest(model, partition["frozen_parameter_names"]),
        "gradient_norm_max": maximum_gradient,
        "changed_parameter_names": [name for name in MODEL_PARAMETER_NAMES if weights[name] != checkpoint["model_state"][name]],
        "stopped_reason": reason, "elapsed_seconds": time.monotonic() - started,
        "deadline_scope": "soft_boundary_before_numeric_batch; initialization_and_serialization_not_interruptible",
        "partial_failure_scope": "only_successfully_returned_prefix_traced; exceptions_can_leave_unreturned_partial_updates_unknown",
        "tuning": {"objective_loss": total / measured if measured else None, "rows_evaluated": measured,
            "complete": measured == len(tuning), "teacher_forcing": True, "used_for_fit_or_selection": False,
            "objective_policy_sha256": checkpoint_digest(policy["objective_policy"])}, **FALSE}
    return {"checkpoint": updated, "report": report}


class SpanPermissionRetentionDecoder:
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
        rows = [self._inference_view._decode(text, vector, enabled=latent_ablation != "disabled")
            for text, vector in zip(texts, vectors, strict=True)]
        _require(_state_digest(self.model) == self._expected_model_sha256
            and _raw(_implementation()) == self._implementation_snapshot, "inference changed source or model")
        count = sum(row["status"] == "decoded" for row in rows)
        child = self.checkpoint["initial_continuation_checkpoint"]
        return {"schema": "bounded-permission-retention-span-legal-formula-inference/v1", "lineage_id": LINEAGE_ID,
            "checkpoint_sha256": self.checkpoint_sha256, "initial_continuation_checkpoint_sha256": checkpoint_digest(child),
            "source_parent_checkpoint_sha256": child["source_parent_checkpoint_sha256"], "source_parent_optimizer_steps": 400,
            "context_contract_sha256": child["context_contract_sha256"], "model_state_sha256": self._expected_model_sha256,
            "training_policy": copy.deepcopy(self._policy), "training_policy_sha256": checkpoint_digest(self._policy),
            "rows": rows, "decoded_count": count, "status": "decoded" if count == len(rows) else "partial" if count else "abstained",
            "latent_ablation": latent_ablation, "target_access": False, "teacher_forcing": False,
            "training_executed": False, "legacy_single_source_readout_unchanged": True, **FALSE}


def captured_inference(torch, span, warm, checkpoint, rows, *, control="none"):
    """Capture same-forward heads without exposing labels to inference."""
    _require(span is globals()["span"] and warm is continuation, "exact unchanged source owners required")
    decoder = SpanPermissionRetentionDecoder(checkpoint)
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
    observer = sys.modules["ipfs_datasets_py.logic.formalization.autoencoder.retained_span_score_capture"]
    for source, scores, raw in zip(sources, captures, report["rows"], strict=True):
        _require(raw["source_sha256"] == hashlib.sha256(source["source_text"].encode()).hexdigest(), "raw source identity differs")
        observer._verify_greedy(source["source_text"], scores, raw)
    return {"schema": "permission-retention-target-free-head-capture/v1", "inference": report,
        "occurrences": [{"id": source["id"], "source_sha256": hashlib.sha256(source["source_text"].encode()).hexdigest(), "scores": scores}
            for source, scores in zip(sources, captures, strict=True)], "actual_source_forwards": len(rows),
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
        _require(observed == projection, "disabled source-only scores changed under latent placeholder control")
        captures.append({"name": name, "control": control,
            "report": _write_artifact(Path(out) / (state_name + "-parity-" + name + ".json"), report)})
    return _write_artifact(Path(out) / (state_name + "-parity.json"),
        {"schema": "source-only-dormant384-placeholder-parity/v1", "passed": True, "controls": captures,
            "source_count": 2, "score_and_greedy_decisions_bit_equal": True,
            "genuine_latent_semantics_tested": False, "actual_encoder_calls": 0, **FALSE})


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
