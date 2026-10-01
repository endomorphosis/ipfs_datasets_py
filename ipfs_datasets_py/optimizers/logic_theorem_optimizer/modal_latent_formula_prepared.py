"""Opt-in prepared CPU batches for the current 384D formula trainer.

This module leaves the reference decoder/checkpoint implementation unchanged.
Targets are validated and encoded once per call; tensors and epoch permutations
are reused. Each numerical batch has the same row order, dtype, values, exact
padding width and contiguity as the reference. Both backward traversals,
clipping, finite checks, Adam settings and loss observations are preserved.
Compatible v1 heads retain their reference decoder source pins; this separate
training producer is bound explicitly in the returned report, not hidden in a
changed checkpoint schema. A prepared run cannot grant semantic qualification.
"""
from __future__ import annotations

import copy
import hashlib
import math
from pathlib import Path
import random
import time

from . import modal_latent_formula as reference
from . import modal_joint_formula as joint

PROFILE = "current-formula-prepared-tensor-training/v1"
_require, _restore, _splits = reference._require, reference._restore, reference._splits
checkpoint_digest, _pack, _norm = reference.checkpoint_digest, reference._pack, reference._norm
_raw, _implementation = reference._raw, reference._implementation
MAX_BYTES, PROJECTION_ID, FALSE = reference.MAX_BYTES, reference.PROJECTION_ID, reference.FALSE


def _source_identity():
    info = Path(__file__).stat()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


_SOURCE_IDENTITY = _source_identity()
_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_JOINT_SHA256 = hashlib.sha256(Path(joint.__file__).read_bytes()).hexdigest()
_require(_source_identity() == _SOURCE_IDENTITY, "prepared trainer changed during import")


def _check_sources():
    _require(_source_identity() == _SOURCE_IDENTITY, "prepared trainer changed since import")
    _require(hashlib.sha256(Path(joint.__file__).read_bytes()).hexdigest() == _JOINT_SHA256,
             "joint adapter changed since prepared trainer import")
    return {"profile": PROFILE, "prepared_trainer_sha256": _SOURCE_SHA256,
            "joint_adapter_sha256": _JOINT_SHA256,
            "reference_implementation": reference._implementation(),
            "scope": "listed prepared trainer and reference decoder sources"}


class _PreparedRows:
    """Private per-call tensors, with reference-identical batch padding."""
    def __init__(self, rows, codec, dimension):
        torch = reference._torch()
        encoded = [reference.codec_module.encode_target(codec, row["canonical_ir"]) for row in rows]
        self.lengths = tuple(map(len, encoded))
        width = max(self.lengths, default=0)
        self.latent = torch.tensor([row["latent"] for row in rows], dtype=torch.float32).reshape(len(rows), dimension)
        self.embedding = torch.tensor([row["embedding"] for row in rows], dtype=torch.float32).reshape(len(rows), dimension)
        self.target = torch.tensor([value + [0] * (width - len(value)) for value in encoded], dtype=torch.long).reshape(len(rows), width)
        self.tensor_bytes = sum(value.nelement() * value.element_size() for value in (self.latent, self.embedding, self.target))

    def __len__(self):
        return len(self.lengths)

    def batch(self, indices):
        torch = reference._torch()
        width = max(self.lengths[index] for index in indices)
        index = torch.tensor(indices, dtype=torch.long)
        return (self.latent.index_select(0, index), self.embedding.index_select(0, index),
                self.target.index_select(0, index)[:, :width].contiguous())


def _loss(model, batch, config):
    torch = reference._torch()
    latent, expected_embedding, target = batch
    projected, logits = model(latent, target[:, :-1])
    expected = target[:, 1:]
    formula = torch.nn.functional.cross_entropy(logits.reshape(-1, logits.shape[-1]), expected.reshape(-1), ignore_index=0)
    reconstruction = torch.nn.functional.mse_loss(projected, expected_embedding)
    total = config["formula_weight"] * formula + config["reconstruction_weight"] * reconstruction
    return total, formula, reconstruction, int((expected != 0).sum())


def _metrics(model, rows, config, deadline):
    torch = reference._torch()
    evaluated, tokens, ce, reconstruction = 0, 0, 0., 0.
    model.eval()
    with torch.no_grad():
        for start in range(0, len(rows), config["batch_size"]):
            if time.monotonic() >= deadline:
                break
            indices = list(range(start, min(start + config["batch_size"], len(rows))))
            loss, formula, mse, count = _loss(model, rows.batch(indices), config)
            _require(bool(torch.isfinite(loss)), "nonfinite evaluation loss")
            ce += float(formula) * count
            reconstruction += float(mse) * len(indices)
            tokens += count
            evaluated += len(indices)
    return {"token_cross_entropy": ce / tokens if tokens else None,
        "reconstruction_mse": reconstruction / evaluated if evaluated else None,
        "rows_evaluated": evaluated, "token_count": tokens, "complete": evaluated == len(rows),
        "teacher_forcing": True, "used_for_fit_or_selection": False}


def train(checkpoint, train_rows, tune_rows, *, epochs=20, max_seconds=60, max_optimizer_steps=None):
    """Continue complete batches, retaining exact Adam and partial-epoch cursor.

    Formula and reconstruction losses jointly update the residual projection.
    Tuning metrics are observational; this API does not select or promote a
    candidate. The deadline is soft at numeric-batch and evaluation boundaries.
    """
    started = time.monotonic()
    producer = _check_sources()
    _require(type(epochs) is int and 1 <= epochs <= 1000, "epochs must be in 1..1000")
    _require(type(max_seconds) in (int, float) and math.isfinite(max_seconds) and 0 <= max_seconds <= 3600,
             "bounded nonnegative deadline required")
    _require(max_optimizer_steps is None or type(max_optimizer_steps) is int and 0 <= max_optimizer_steps <= 100000,
             "bounded optimizer step budget required")
    deadline = started + max_seconds
    torch, model, optimizer = _restore(checkpoint)
    parent_identity = checkpoint_digest(checkpoint)
    _require(checkpoint["binding"]["lineage_id"] == "current_legal_v2", "prepared training requires current 384D lineage")
    training, tuning = _splits(train_rows, tune_rows, checkpoint["binding"]["dimension"])
    _require(checkpoint_digest(training) == checkpoint["training_manifest_sha256"]
             and checkpoint_digest(tuning) == checkpoint["tuning_manifest_sha256"], "resume manifests differ")
    config, codec = checkpoint["config"], checkpoint["codec"]
    progress = dict(checkpoint["progress"])
    start_step, start_epoch = progress["optimizer_steps"], progress["epochs_completed"]
    goal = start_epoch + epochs
    preparation_started = time.monotonic()
    prepared_training = _PreparedRows(training, codec, checkpoint["binding"]["dimension"])
    prepared_tuning = _PreparedRows(tuning, codec, checkpoint["binding"]["dimension"])
    preparation_seconds = time.monotonic() - preparation_started
    before = _metrics(model, prepared_training, config, deadline)
    initial, _ = _pack(model, optimizer)
    groups = {"projection": [parameter for name, parameter in model.named_parameters() if name.startswith("projection_")],
              "decoder": [parameter for name, parameter in model.named_parameters() if not name.startswith("projection_")]}
    maximum = {"projection": 0., "decoder": 0., "formula_to_projection": 0.}
    history, stopped = [], "epoch_limit"
    cached_epoch, order = None, None
    loop_started = time.monotonic()
    while progress["epochs_completed"] < goal:
        if time.monotonic() >= deadline:
            stopped = "deadline_before_batch"; break
        if max_optimizer_steps is not None and progress["optimizer_steps"] - start_step >= max_optimizer_steps:
            stopped = "optimizer_step_budget"; break
        if cached_epoch != progress["epochs_completed"]:
            cached_epoch = progress["epochs_completed"]
            order = list(range(len(training)))
            random.Random(config["seed"] + cached_epoch).shuffle(order)
        indices = order[progress["row_cursor"]:progress["row_cursor"] + config["batch_size"]]
        batch = prepared_training.batch(indices)
        model.train()
        optimizer.zero_grad(set_to_none=True)
        loss, formula, mse, tokens = _loss(model, batch, config)
        _require(bool(torch.isfinite(loss)), "nonfinite joint training loss")
        formula_gradients = torch.autograd.grad(formula, groups["projection"], retain_graph=True)
        _require(all(bool(torch.isfinite(value).all()) for value in formula_gradients), "nonfinite formula projection gradient")
        maximum["formula_to_projection"] = max(maximum["formula_to_projection"], _norm(formula_gradients))
        loss.backward()
        for name, parameters in groups.items():
            _require(all(parameter.grad is not None and bool(torch.isfinite(parameter.grad).all()) for parameter in parameters),
                     "missing or nonfinite joint gradient")
            maximum[name] = max(maximum[name], _norm(parameter.grad for parameter in parameters))
        torch.nn.utils.clip_grad_norm_(list(model.parameters()), 5., error_if_nonfinite=True)
        optimizer.step()
        _require(all(bool(torch.isfinite(parameter).all()) for parameter in model.parameters()), "nonfinite updated weights")
        _require(all(bool(torch.isfinite(value).all()) for item in optimizer.state.values() for value in item.values()
                     if torch.is_tensor(value)), "nonfinite updated Adam moments")
        progress["optimizer_steps"] += 1
        progress["row_cursor"] += len(indices)
        if progress["row_cursor"] == len(training):
            progress["epochs_completed"] += 1
            progress["row_cursor"] = 0
        history.append({"step": progress["optimizer_steps"], "token_cross_entropy": float(formula.detach()),
                        "reconstruction_mse": float(mse.detach()), "joint_loss": float(loss.detach()), "token_count": tokens})
    loop_seconds = time.monotonic() - loop_started
    after = _metrics(model, prepared_training, config, deadline)
    tuning_metrics = _metrics(model, prepared_tuning, config, deadline)
    weights, moments = _pack(model, optimizer)
    result = copy.deepcopy(checkpoint)
    result.update(model_state=weights, optimizer_state=moments, progress=progress,
                  parent_checkpoint_sha256=checkpoint_digest(checkpoint))
    _require(result["implementation"] == _implementation(), "latent producer changed during training")
    _require(len(_raw(result)) <= MAX_BYTES, "latent checkpoint exceeds byte bound")
    selected = lambda state, prefix: {name: value for name, value in state.items()
                                     if name.startswith("projection_") == (prefix == "projection")}
    evidence = {name: {"gradient_norm_max": maximum[name],
        "initial_parameters_sha256": checkpoint_digest(selected(initial, name)),
        "final_parameters_sha256": checkpoint_digest(selected(weights, name)),
        "parameter_update_l2": _norm(torch.tensor(weights[key], dtype=torch.float64) - torch.tensor(initial[key], dtype=torch.float64)
                                      for key in selected(weights, name))} for name in groups}
    report = {"schema": "modal-latent-formula-training/v1", "binding": copy.deepcopy(checkpoint["binding"]),
        "checkpoint_sha256": checkpoint_digest(result), "parent_checkpoint_sha256": checkpoint_digest(checkpoint),
        "projection_id": PROJECTION_ID, "training_executed": progress["optimizer_steps"] > start_step,
        "optimizer_steps": progress["optimizer_steps"] - start_step,
        "epochs_completed": progress["epochs_completed"] - start_epoch, "progress": dict(progress),
        "stopped_reason": stopped, "elapsed_seconds": time.monotonic() - started,
        "deadline_scope": "soft_before_batch; preparation_serialization_and_inflight_batch_not_interruptible",
        "training_before": before, "training_after": after, "tuning": tuning_metrics, "batch_losses": history,
        "parameter_evidence": evidence, "formula_projection_gradient_norm_max": maximum["formula_to_projection"],
        "objective": "formula_token_cross_entropy_plus_projected_embedding_mse",
        "core_sparse_weights_frozen_for_formula_gradient": True, "sample_memory_used": False,
        "source_text_is_neural_input": False, "formula_conditioning": "learned_residual_projection_of_core_representation",
        "heldout_canary": False, "selection_performed": False, "family_backend_syntax_checked": False,
        "unsupported_projection_policy": "explicit_abstention", "examples_persisted": False,
        "download_calls": 0, "provider_calls": 0, **FALSE}
    _require(checkpoint_digest(training) == checkpoint["training_manifest_sha256"]
             and checkpoint_digest(tuning) == checkpoint["tuning_manifest_sha256"], "input rows changed during prepared training")
    _require(checkpoint_digest(checkpoint) == parent_identity, "input checkpoint changed during prepared training")
    _require(_check_sources() == producer, "prepared training producer changed")
    report.update(training_backend=PROFILE, prepared_training_producer=producer,
        tensor_preparation_seconds=preparation_seconds, optimization_loop_seconds=loop_seconds,
        prepared_tensor_bytes=prepared_training.tensor_bytes + prepared_tuning.tensor_bytes,
        targets_encoded_once=len(training) + len(tuning),
        exact_reference_update_rule=True, formula_gradient_telemetry="unchanged second backward traversal",
        elapsed_seconds=time.monotonic() - started)
    return {"checkpoint": result, "report": report}



def train_model(model, samples, targets, *, validation_samples, validation_targets,
                epochs=20, max_seconds=60, formula_options=None, max_optimizer_steps=None):
    """Train and attach a prepared head to an explicitly owned current model.

    For example pass ``runtime.model`` from the legal/current_v2 registry.
    Input preparation consumes the same deadline. Exceptions and core drift
    prevent attachment; resumed configuration and exact source bindings remain
    immutable. This does not enable concurrent inference on a mutable model.
    """
    started = time.monotonic()
    producer = _check_sources()
    _require(type(max_seconds) in (int, float) and math.isfinite(max_seconds) and 0 < max_seconds <= 3600,
             "joint formula training requires a positive bounded deadline")
    binding = joint._core_binding(model)
    _require(binding["lineage_id"] == "current_legal_v2", "prepared training requires current 384D lineage")
    training = joint._rows(model, samples, targets)
    tuning = joint._rows(model, validation_samples, validation_targets)
    checkpoint = getattr(model, "_joint_formula_checkpoint", None)
    if checkpoint is None:
        _require(formula_options is None or type(formula_options) is dict, "formula_options must be a mapping")
        checkpoint = reference.build_checkpoint(binding, training, tuning, **(formula_options or {}))
    else:
        checkpoint = joint._attached_checkpoint(model, validate_runtime=True)
        _require(not formula_options, "resumed decoder configuration is immutable")
        _require(checkpoint["binding"] == binding, "core changed after decoder attachment; explicit new branch required")
    remaining = max_seconds - (time.monotonic() - started)
    if remaining <= 0:
        raise TimeoutError("joint formula preparation exhausted training deadline; no model update committed")
    result = train(checkpoint, training, tuning, epochs=epochs,
                   max_seconds=remaining, max_optimizer_steps=max_optimizer_steps)
    _require(joint._core_binding(model) == binding, "core changed during joint formula training")
    _require(_check_sources() == producer, "prepared model training producer changed")
    joint.attach(model, result["checkpoint"])
    result["report"]["pipeline_elapsed_seconds"] = time.monotonic() - started
    result["report"]["joint_profile"] = joint.describe(model)
    return result


__all__ = ["PROFILE", "train", "train_model"]
