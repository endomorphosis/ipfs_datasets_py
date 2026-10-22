"""Private CPU kernels for the separately bound native4096 engineering lane.

Only the live-bound consumer supplies execution admission. Stored provenance is
historical evidence, never a live native capability or semantic qualification.
The original 4096 checkpoint and its training/inference refusals are unchanged.
This new lineage reuses their numerical helpers, loss and source-span decoder.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import random
import time

from . import legal_span_4096 as old
from . import legal_span_formula as span
from . import legal_span_native4096_binding as binding
from .checkpoint_content_guard import CheckpointContentGuard

SCHEMA = "bound-native4096-source-span-checkpoint/v1"
LINEAGE_ID = "bound_native4096_source_span_v1"
DIMENSION = old.DIMENSION
MAX_BYTES = min(old.MAX_BYTES, binding.base.MAX_BYTES)
FALSE = span.FALSE
_require, _raw, checkpoint_digest = span._require, span._raw, span.checkpoint_digest
_FIELDS = {"schema", "lineage_id", "implementation", "provenance", "config", "context_contract",
    "context_contract_sha256", "batch_contracts", "source_parent_checkpoint",
    "source_parent_checkpoint_sha256", "source_parent_optimizer_steps", "initial_source_model_sha256",
    "initial_model_state_sha256", "training_manifest_sha256", "training_count", "tuning_manifest_sha256",
    "tuning_count", "model_state", "optimizer_state", "progress", "parent_checkpoint_sha256", *FALSE}
_HELPERS = {name: getattr(old, name) for name in ("_config", "_context_contract", "_plain_json",
    "_fresh_model", "_initial_model", "_source_parent", "_source_state", "_weights", "_progress",
    "_moments", "_optimizer_for_model")}
_SPAN_HELPERS = {name: getattr(span, name) for name in ("_splits", "_loss", "_pack", "_vector")}
_DECODE = span.SpanLegalFormulaDecoder._decode
_SELF_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_BINDING_SHA = hashlib.sha256(Path(binding.__file__).read_bytes()).hexdigest()
_BINDING_IMPLEMENTATION = binding._implementation
_OLD_IMPLEMENTATION = old._implementation()


def _implementation():
    _require(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SELF_SHA
             and hashlib.sha256(Path(binding.__file__).read_bytes()).hexdigest() == _BINDING_SHA,
             "bound native4096 numerical source changed since import")
    _require(all(getattr(old, name) is helper for name, helper in _HELPERS.items())
             and all(getattr(span, name) is helper for name, helper in _SPAN_HELPERS.items())
             and span.SpanLegalFormulaDecoder._decode is _DECODE
             and binding._implementation is _BINDING_IMPLEMENTATION,
             "bound native4096 numerical helper changed since import")
    _require(old._implementation() == _OLD_IMPLEMENTATION,
             "original native4096 numerical implementation differs")
    return {"numeric_sha256": _SELF_SHA, "original_native4096": deepcopy(_OLD_IMPLEMENTATION),
            "live_binding": binding._implementation()}


def _sha(value, name):
    _require(type(value) is str and span._SHA.fullmatch(value), "invalid " + name)
    return value


def _native_receipts(value, tuning_count):
    _require(type(value) is dict and set(value) == {"training", "tuning"},
             "closed training/tuning native receipt references required")
    _sha(value["training"], "training native receipt SHA256")
    if tuning_count:
        _sha(value["tuning"], "tuning native receipt SHA256")
    else:
        _require(value["tuning"] is None, "absent tuning requires null native receipt")
    return deepcopy(value)


def _batch_contracts(value, context_contract, training_manifest_sha256,
                     tuning_manifest_sha256, tuning_count):
    """Check declared identities only; these ordinary records grant no authority."""
    _require(type(value) is dict and set(value) == {"training", "tuning"},
             "closed training/tuning batch contracts required")
    for name, manifest in (("training", training_manifest_sha256), ("tuning", tuning_manifest_sha256)):
        contract = value[name]
        if name == "tuning" and not tuning_count:
            _require(contract is None, "absent tuning requires null batch contract")
            _require(manifest == checkpoint_digest([]), "absent tuning manifest must identify the empty population")
            continue
        _require(type(contract) is dict and set(contract) == {
            "input_sha256s", "context_contract", "numerical_rows_sha256"},
            "closed " + name + " batch contract required")
        inputs = contract["input_sha256s"]
        _require(type(inputs) is dict and set(inputs) == {"rows", "split_manifest", "eligibility", "exposure"},
                 "closed " + name + " input identities required")
        for key, digest in inputs.items():
            _sha(digest, name + " " + key + " SHA256")
        _sha(contract["numerical_rows_sha256"], name + " numerical rows SHA256")
        _require(contract["numerical_rows_sha256"] == manifest,
                 name + " batch and numerical manifest differ")
        old._context_contract(contract["context_contract"])
    training = value["training"]
    _require(_raw(training["context_contract"]) == _raw(context_contract),
             "checkpoint context must be the exact training context")
    if tuning_count:
        tuning = value["tuning"]
        _require(training["input_sha256s"]["split_manifest"] == tuning["input_sha256s"]["split_manifest"],
                 "training and tuning complete split manifests differ")
        _require(all(training["context_contract"][key] == tuning["context_contract"][key]
                     for key in ("dimension", "representation_id", "producer_sha256")),
                 "training and tuning native representations differ")
    return deepcopy(value)


def _provenance(initial, last, tuning_count):
    return {"schema": "bound-native4096-input-provenance/v1", "kind": "live_bound_engineering_inputs",
            "serialized_evidence_is_execution_authority": False,
            "initial_native_receipts": _native_receipts(initial, tuning_count),
            "last_native_receipts": _native_receipts(last, tuning_count)}


def _runtime(torch):
    _require(str(torch.get_default_device()) == "cpu" and torch.get_default_dtype() == torch.float32,
             "unchanged CPU float32 defaults required")
    _require(not torch.is_autocast_enabled("cpu") and not torch.is_autocast_enabled("cuda"),
             "bound native4096 forbids autocast")


def _snapshot(checkpoint):
    _implementation()
    old._plain_json(checkpoint)
    # Public consumers replay the same complete plain-data contract. An output
    # that exceeds their depth/node/byte limits cannot be resumed through them.
    raw = binding.base._preflight(checkpoint)
    _require(len(raw) + 1 <= MAX_BYTES, "bound native4096 checkpoint exceeds byte bound including saved newline")
    guard = CheckpointContentGuard(checkpoint)
    detached = json.loads(raw)
    guard.check(detached, message="detached native4096 checkpoint differs")
    return detached, guard


def _restore_snapshot(torch, checkpoint):
    _require(type(checkpoint) is dict and set(checkpoint) == _FIELDS
             and checkpoint["schema"] == SCHEMA and checkpoint["lineage_id"] == LINEAGE_ID
             and all(checkpoint[name] is False for name in FALSE),
             "closed bound native4096 checkpoint required")
    _require(checkpoint["implementation"] == _implementation(),
             "bound native4096 checkpoint implementation differs")
    config = checkpoint["config"]
    _require(type(config) is dict and set(old._CONFIG_KEYS) <= set(config)
             and _raw(config) == _raw(old._config(**{name: config[name] for name in old._CONFIG_KEYS})),
             "bound native4096 configuration differs")
    context = old._context_contract(checkpoint["context_contract"])
    _require(checkpoint["context_contract_sha256"] == checkpoint_digest(context),
             "bound native4096 context changed")
    old._progress(checkpoint)
    _require(checkpoint["training_count"] <= 128 and checkpoint["tuning_count"] <= 128,
             "native4096 checkpoint populations exceed complete native operation bound")
    _batch_contracts(checkpoint["batch_contracts"], context, checkpoint["training_manifest_sha256"],
                     checkpoint["tuning_manifest_sha256"], checkpoint["tuning_count"])
    provenance = checkpoint["provenance"]
    _require(type(provenance) is dict and set(provenance) == {
        "schema", "kind", "serialized_evidence_is_execution_authority",
        "initial_native_receipts", "last_native_receipts"}, "closed native4096 provenance required")
    _require(_raw(provenance) == _raw(_provenance(provenance["initial_native_receipts"],
             provenance["last_native_receipts"], checkpoint["tuning_count"])),
             "native4096 provenance differs")
    if checkpoint["progress"]["optimizer_steps"] == 0:
        _require(provenance["initial_native_receipts"] == provenance["last_native_receipts"],
                 "zero-update native receipt provenance differs")
    parent = checkpoint["source_parent_checkpoint"]
    _require(type(parent) is dict, "trained source-only parent required")
    old._source_parent(torch, parent)
    _require(checkpoint["source_parent_checkpoint_sha256"] == checkpoint_digest(parent)
             and type(checkpoint["source_parent_optimizer_steps"]) is int
             and checkpoint["source_parent_optimizer_steps"] == parent["progress"]["optimizer_steps"],
             "source-parent content or update count differs")
    model = old._initial_model(torch, config, parent)
    initial = {name: value.detach().tolist() for name, value in model.state_dict().items()}
    _require(checkpoint["initial_source_model_sha256"] == checkpoint_digest(old._source_state(initial))
             and checkpoint["initial_model_state_sha256"] == checkpoint_digest(initial),
             "initial copied source and zero-adapter state differ")
    if checkpoint["progress"]["optimizer_steps"] == 0:
        _require(_raw(checkpoint["model_state"]) == _raw(initial), "zero-update native4096 model differs")
    old._weights(torch, model, checkpoint["model_state"])
    old._moments(torch, model, checkpoint)
    model.eval()
    return model


def _restore(checkpoint):
    """Private model-only restore; does not admit a consumer or construct Adam."""
    detached, guard = _snapshot(checkpoint)
    import torch
    _runtime(torch)
    with torch.random.fork_rng(devices=[]):
        model = _restore_snapshot(torch, detached)
    guard.check(checkpoint, message="original checkpoint changed during restoration")
    guard.check(detached, message="detached checkpoint changed during restoration")
    _implementation()
    _runtime(torch)
    return torch, model


def _build(parent, train, tune, *, context_contract, batch_contracts, native_receipts,
           learning_rate=.001, batch_size=12, latent_enabled=True):
    """Private initializer called only after live bound argument admission."""
    inputs = {"parent": parent, "train": train, "tune": tune, "context": context_contract,
              "batch_contracts": batch_contracts, "native_receipts": native_receipts}
    old._plain_json(inputs)
    _require(len(_raw(inputs)) <= MAX_BYTES, "bounded native4096 build inputs required")
    guard = CheckpointContentGuard(inputs)
    captured = json.loads(_raw(inputs))
    parent, train, tune = captured["parent"], captured["train"], captured["tune"]
    _require(type(train) is list and 1 <= len(train) <= 128 and type(tune) is list and len(tune) <= 128,
             "complete native4096 training/tuning populations must contain at most 128 rows")
    context = old._context_contract(captured["context"])
    span._splits(train, tune, DIMENSION)
    manifests = [checkpoint_digest(rows) for rows in (train, tune)]
    contracts = _batch_contracts(captured["batch_contracts"], context, *manifests, len(tune))
    receipts = _native_receipts(captured["native_receipts"], len(tune))
    _require(type(parent) is dict and type(parent.get("config")) is dict,
             "trained source-only parent required")
    _implementation()
    import torch
    _runtime(torch)
    with torch.random.fork_rng(devices=[]):
        old._source_parent(torch, parent)
        inherited = {name: parent["config"][name]
                     for name in ("seed", "hidden_size", "embedding_dim", "projection_width", "residual_scale")}
        config = old._config(**inherited, learning_rate=learning_rate, batch_size=batch_size,
                             latent_enabled=latent_enabled)
        initial = old._initial_model(torch, config, parent)
        state = {name: value.detach().tolist() for name, value in initial.state_dict().items()}
        result = {"schema": SCHEMA, "lineage_id": LINEAGE_ID, "implementation": _implementation(),
            "provenance": _provenance(receipts, receipts, len(tune)), "config": config,
            "context_contract": context, "context_contract_sha256": checkpoint_digest(context),
            "batch_contracts": contracts, "source_parent_checkpoint": parent,
            "source_parent_checkpoint_sha256": checkpoint_digest(parent),
            "source_parent_optimizer_steps": parent["progress"]["optimizer_steps"],
            "initial_source_model_sha256": checkpoint_digest(old._source_state(state)),
            "initial_model_state_sha256": checkpoint_digest(state),
            "training_manifest_sha256": manifests[0], "training_count": len(train),
            "tuning_manifest_sha256": manifests[1], "tuning_count": len(tune),
            "model_state": state, "optimizer_state": {"schema": "adam-default-betas-eps/v1", "parameters": {}},
            "progress": {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0},
            "parent_checkpoint_sha256": None, **FALSE}
        old._plain_json(result)
        _require(len(binding.base._preflight(result)) + 1 <= MAX_BYTES,
                 "bound native4096 checkpoint exceeds byte bound including saved newline")
        _restore_snapshot(torch, result)
    guard.check(inputs, message="native4096 build inputs changed during initialization")
    guard.check(captured, message="detached native4096 build inputs changed during initialization")
    _runtime(torch)
    _implementation()
    return result


def _train(checkpoint, train, tune, *, native_receipts, max_steps, max_seconds):
    """Private resumable update; all public callers must replay live custody."""
    _require(type(max_steps) is int and 0 <= max_steps <= 10000, "max_steps must be in 0..10000")
    _require(type(max_seconds) in (int, float) and math.isfinite(max_seconds) and 0 <= max_seconds <= 3600,
             "max_seconds must be in 0..3600")
    started = time.monotonic()
    detached, guard = _snapshot(checkpoint)
    inputs = {"training": train, "tuning": tune, "native_receipts": native_receipts}
    old._plain_json(inputs)
    _require(len(_raw(inputs)) <= MAX_BYTES, "bounded native4096 update inputs required")
    input_guard = CheckpointContentGuard(inputs)
    captured = json.loads(_raw(inputs))
    train, tune = captured["training"], captured["tuning"]
    _require(detached["training_manifest_sha256"] == checkpoint_digest(train)
             and detached["tuning_manifest_sha256"] == checkpoint_digest(tune)
             and detached["training_count"] == len(train) and detached["tuning_count"] == len(tune),
             "native4096 resume manifests or populations differ")
    records, tuning = span._splits(train, tune, DIMENSION)
    receipts = _native_receipts(captured["native_receipts"], len(tune))
    import torch
    _runtime(torch)
    _require(torch.is_grad_enabled() and not torch.is_inference_mode_enabled(),
             "native4096 training requires enabled autograd and no inference mode")
    with torch.random.fork_rng(devices=[]):
        model = _restore_snapshot(torch, detached)
        optimizer = old._optimizer_for_model(torch, model, detached)
        config, progress = detached["config"], dict(detached["progress"])
        losses, maximum_gradient, reason = [], 0., "step_limit"
        deadline = started + max_seconds
        for _ in range(max_steps):
            if time.monotonic() >= deadline:
                reason = "deadline_before_batch"
                break
            order = list(range(len(records)))
            random.Random(config["seed"] + progress["epochs_completed"]).shuffle(order)
            indices = order[progress["row_cursor"]:progress["row_cursor"] + config["batch_size"]]
            model.train()
            optimizer.zero_grad(set_to_none=True)
            loss = span._loss(torch, model, [records[index] for index in indices])
            _require(bool(torch.isfinite(loss)), "nonfinite training loss")
            loss.backward()
            parameters = list(model.parameters())
            _require(all(parameter.grad is not None and bool(torch.isfinite(parameter.grad).all())
                         for parameter in parameters), "missing or nonfinite gradients")
            norm = torch.nn.utils.clip_grad_norm_(parameters, 5, error_if_nonfinite=True)
            maximum_gradient = max(maximum_gradient, float(norm))
            optimizer.step()
            _require(all(bool(torch.isfinite(parameter).all()) for parameter in parameters),
                     "nonfinite updated weights")
            _require(all(bool(torch.isfinite(value).all()) for moment in optimizer.state.values()
                         for value in moment.values() if torch.is_tensor(value)), "nonfinite optimizer moments")
            progress["optimizer_steps"] += 1
            progress["row_cursor"] += len(indices)
            if progress["row_cursor"] == len(records):
                progress["epochs_completed"] += 1
                progress["row_cursor"] = 0
            losses.append(float(loss.detach()))
        model.eval()
        total, measured = 0., 0
        with torch.no_grad():
            for start in range(0, len(tuning), config["batch_size"]):
                if time.monotonic() >= deadline:
                    break
                chunk = tuning[start:start + config["batch_size"]]
                loss = span._loss(torch, model, chunk)
                _require(bool(torch.isfinite(loss)), "nonfinite tuning loss")
                total += float(loss) * len(chunk)
                measured += len(chunk)
        weights, moments = span._pack(model, optimizer)
        result = ({**deepcopy(detached), "model_state": weights, "optimizer_state": moments,
                   "progress": progress, "parent_checkpoint_sha256": checkpoint_digest(detached),
                   "provenance": _provenance(detached["provenance"]["initial_native_receipts"], receipts, len(tune))}
                  if losses else deepcopy(detached))
        old._plain_json(result)
        _require(len(binding.base._preflight(result)) + 1 <= MAX_BYTES,
                 "bound native4096 checkpoint exceeds byte bound including saved newline")
        _restore_snapshot(torch, result)
    guard.check(checkpoint, message="original checkpoint changed during native4096 training")
    guard.check(detached, message="detached checkpoint changed during native4096 training")
    input_guard.check(inputs, message="original native4096 training inputs changed")
    input_guard.check(captured, message="detached native4096 training inputs changed")
    _implementation()
    _runtime(torch)
    return {"checkpoint": result, "report": {"schema": "bound-native4096-source-span-training/v1",
        "checkpoint_sha256": checkpoint_digest(result), "optimizer_steps": len(losses),
        "training_executed": bool(losses), "new_optimizer_steps_total": progress["optimizer_steps"],
        "source_parent_optimizer_steps": detached["source_parent_optimizer_steps"],
        "batch_losses": losses, "gradient_norm_max": maximum_gradient,
        "changed_parameter_names": [name for name in weights if weights[name] != detached["model_state"][name]],
        "stopped_reason": reason, "elapsed_seconds": time.monotonic() - started,
        "deadline_scope": "soft_boundary_before_numeric_batch; initialization_and_serialization_not_interruptible",
        "native_receipts": receipts, "serialized_evidence_is_execution_authority": False,
        "tuning": {"objective_loss": total / measured if measured else None, "rows_evaluated": measured,
                   "complete": measured == len(tuning), "teacher_forcing": False, "used_for_fit_or_selection": False},
        **FALSE}}


class _Decoder:
    _decode = _DECODE


def _decode(checkpoint, sources, latents, *, latent_ablation="none"):
    """Private target-free CPU inference; public source admission is separate."""
    _require(type(sources) is list and 1 <= len(sources) <= 128
             and all(type(text) is str for text in sources), "one through 128 source strings required")
    _require(type(latents) is list and len(latents) == len(sources), "one native4096 vector per source required")
    _require(type(latent_ablation) is str and latent_ablation in ("none", "zero", "rotate", "disabled"),
             "unsupported latent ablation")
    _require(latent_ablation != "rotate" or len(sources) > 1, "rotate requires at least two sources")
    original_inputs = {"sources": sources, "latents": latents}
    old._plain_json(original_inputs)
    _require(len(_raw(original_inputs)) <= MAX_BYTES, "bounded native4096 inference inputs required")
    input_guard = CheckpointContentGuard(original_inputs)
    texts = list(sources)
    vectors = [span._vector(vector, DIMENSION) for vector in latents]
    detached, guard = _snapshot(checkpoint)
    torch, model = _restore(detached)
    decoder = _Decoder()
    decoder.torch, decoder.model, decoder.checkpoint = torch, model, detached
    if latent_ablation == "zero":
        vectors = [[0.] * DIMENSION for _ in vectors]
    elif latent_ablation == "rotate":
        vectors = vectors[1:] + vectors[:1]
    model_guard = CheckpointContentGuard(detached["model_state"])
    model_guard.check({name: value.detach().tolist() for name, value in model.state_dict().items()},
                      message="native4096 inference model differs before forward")
    with torch.random.fork_rng(devices=[]):
        rows = [decoder._decode(text, vector, enabled=latent_ablation != "disabled")
                for text, vector in zip(texts, vectors)]
    model_guard.check({name: value.detach().tolist() for name, value in model.state_dict().items()},
                      message="native4096 inference model changed")
    guard.check(checkpoint, message="original native4096 checkpoint changed during inference")
    guard.check(detached, message="detached native4096 checkpoint changed during inference")
    input_guard.check(original_inputs, message="original native4096 sources changed during inference")
    _runtime(torch)
    _implementation()
    count = sum(row["status"] == "decoded" for row in rows)
    return {"schema": "bound-native4096-source-span-inference/v1", "lineage_id": LINEAGE_ID,
        "checkpoint_sha256": guard.sha256, "context_contract_sha256": detached["context_contract_sha256"],
        "input_dimension": DIMENSION, "rows": rows, "decoded_count": count,
        "status": "decoded" if count == len(rows) else "partial" if count else "abstained",
        "latent_ablation": latent_ablation, "target_access": False, "teacher_forcing": False,
        "training_executed": False, "model_state_unchanged": True,
        "serialized_evidence_is_execution_authority": False, **FALSE}


__all__ = []
