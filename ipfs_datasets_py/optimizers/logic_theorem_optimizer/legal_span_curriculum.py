"""Opt-in bounded curricula around the unchanged source-span warm lineage.

This outer checkpoint is authoritative for the actual weighted objective and
batch order. Its nested legacy configuration describes the retained model
constructor; it does not label the objective used here. The legacy producer
hashes and checkpoint readers remain unchanged. No numerical library is loaded
until an explicit checkpoint-validation, building, training or decoder call.
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

from . import legal_span_continuation as continuation
from . import legal_span_formula as span

SCHEMA = "bounded-curriculum-span-legal-formula-checkpoint/v1"
LINEAGE_ID = "bounded_source_span_curriculum_v1"
POLICY_SCHEMA = "bounded-source-span-curriculum-policy/v1"
MAX_BYTES = 128 * 1024 * 1024
MAX_NEW_STEPS = 32
MAX_SECONDS = 32
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


def _policy(initialization_seed, *, modality_loss_weight=1,
            batch_order_seed=None, batch_size=12):
    """Closed bounded objective/sampler contract, independent of model restore."""
    _require(type(initialization_seed) is int and 0 <= initialization_seed < 2**31,
             "initialization_seed must be a bounded integer")
    _require(type(modality_loss_weight) is int and modality_loss_weight in (1, 2),
             "modality_loss_weight must be integer1 or2")
    _require(type(batch_size) is int and 1 <= batch_size <= 32,
             "batch_size must be integer1..32")
    _require(batch_order_seed is None or type(batch_order_seed) is int
             and 0 <= batch_order_seed < 2**31,
             "batch_order_seed must be None or a bounded integer")
    return {
        "schema": POLICY_SCHEMA,
        "objective": "weighted_modality_equal_facet_mean_pointer/v1",
        "modality_loss_weight": modality_loss_weight,
        "facet_loss_weights": {field: 1 for field in SPAN_FIELDS},
        "normalization_denominator": modality_loss_weight + len(SPAN_FIELDS),
        "initialization_seed": initialization_seed,
        "batch_order_seed": initialization_seed if batch_order_seed is None else batch_order_seed,
        "batch_order_seed_origin": "inherited_initialization_seed" if batch_order_seed is None else "explicit",
        "batch_size": batch_size,
        "max_new_optimizer_steps": MAX_NEW_STEPS,
        "latent_dimension": 384,
        "latent_enabled": False,
        "nested_loss_metadata_scope": "legacy_constructor_descriptor; this_outer_policy_defines_actual_training_objective",
    }


def _validate_policy(policy):
    _require(type(policy) is dict and policy.get("batch_order_seed_origin")
             in ("inherited_initialization_seed", "explicit"), "closed curriculum policy required")
    expected = _policy(policy.get("initialization_seed"),
        modality_loss_weight=policy.get("modality_loss_weight"),
        batch_order_seed=None if policy["batch_order_seed_origin"] == "inherited_initialization_seed"
        else policy.get("batch_order_seed"), batch_size=policy.get("batch_size"))
    _require(_raw(policy) == _raw(expected), "curriculum policy differs from its closed contract")
    return copy.deepcopy(expected)


def _combine_loss(modality, facets, modality_loss_weight):
    _require(type(modality_loss_weight) is int and modality_loss_weight in (1, 2),
             "modality_loss_weight must be integer1 or2")
    _require(type(facets) in (list, tuple) and len(facets) == len(SPAN_FIELDS),
             "exactly six facet losses required")
    if modality_loss_weight == 1:
        # Preserve the legacy summation/arithmetic order exactly, including no
        # extra multiply of modality by1 in the tensor expression.
        return (modality + sum(facets)) / 7
    return (2 * modality + sum(facets)) / 8


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


def _capture_implementation():
    return {"curriculum_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
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
                     modality_loss_weight=1, batch_order_seed=None, seed=None,
                     learning_rate=.001, batch_size=12, latent_enabled=False):
    """Explicitly fork the unchanged authenticated parent into this new policy."""
    _require(type(parent) is dict and type(parent.get("config")) is dict,
             "source-span parent required")
    selected_seed = parent["config"].get("seed") if seed is None else seed
    policy = _policy(selected_seed, modality_loss_weight=modality_loss_weight,
        batch_order_seed=batch_order_seed, batch_size=batch_size)
    _require(latent_enabled is False, "bounded curricula require disabled384 conditioning")
    child = continuation.build_checkpoint(parent, training_examples, tuning_examples,
        context_contract=context_contract, seed=seed, learning_rate=learning_rate,
        batch_size=batch_size, latent_enabled=False)
    result = {"schema": SCHEMA, "lineage_id": LINEAGE_ID,
        "implementation": _implementation(), "training_policy": policy,
        "training_policy_sha256": checkpoint_digest(policy),
        "initial_training_policy_sha256": checkpoint_digest(policy),
        "initial_continuation_checkpoint_sha256": checkpoint_digest(child),
        "source_parent_checkpoint_sha256": child["source_parent_checkpoint_sha256"],
        "source_parent_model_state_sha256": child["initial_model_state_sha256"],
        "continuation_checkpoint": child, "parent_checkpoint_sha256": None, **FALSE}
    # Exclude only this self-describing fingerprint when hashing its zero-update
    # origin; every policy/provenance field above participates in the binding.
    result["initial_curriculum_checkpoint_sha256"] = checkpoint_digest(result)
    _require(len(_raw(result)) <= MAX_BYTES, "curriculum checkpoint exceeds byte bound")
    return result


def _validated(checkpoint):
    fields = {"schema", "lineage_id", "implementation", "training_policy",
        "training_policy_sha256", "initial_training_policy_sha256",
        "initial_curriculum_checkpoint_sha256", "initial_continuation_checkpoint_sha256",
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
    _require(base["config"]["seed"] == policy["initialization_seed"]
        and base["config"]["batch_size"] == policy["batch_size"]
        and base["config"]["latent_dimension"] == 384
        and base["config"]["latent_enabled"] is False, "legacy constructor/policy differs")
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
    origin.pop("initial_curriculum_checkpoint_sha256")
    _require(checkpoint["initial_curriculum_checkpoint_sha256"] == checkpoint_digest(origin),
             "initial curriculum policy/provenance boundary differs")
    previous = checkpoint["parent_checkpoint_sha256"]
    _require(previous is None or type(previous) is str and span._SHA.fullmatch(previous),
             "invalid previous curriculum checkpoint hash")
    if base["progress"]["optimizer_steps"]:
        _require(previous is not None, "trained curriculum requires previous outer hash")
    return base, child, policy


def validate_checkpoint(checkpoint):
    _validated(checkpoint)


def _loss(torch, model, records, modality_loss_weight):
    output = model(*span._batch(torch, records))
    labels = [row["labels"] for row in records]
    modality = torch.nn.functional.cross_entropy(output["modality"], torch.tensor([x["modality"] for x in labels]))
    facets = []
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
        else:
            facets.append(pointer.mean())
    return _combine_loss(modality, facets, modality_loss_weight)


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
    torch, model, optimizer = span._restore(base)
    _require(base["training_manifest_sha256"] == checkpoint_digest(training_examples)
        and base["tuning_manifest_sha256"] == checkpoint_digest(tuning_examples), "resume manifests differ")
    records, tuning = span._splits(training_examples, tuning_examples, base["config"]["latent_dimension"])
    progress = dict(base["progress"])
    initial_progress = dict(progress)
    losses, batches, maximum_gradient, reason = [], [], 0., "step_limit"
    for _ in range(max_steps):
        if time.monotonic() >= deadline:
            reason = "deadline_before_batch"
            break
        before = dict(progress)
        indices = _batch_indices(len(records), before, policy["batch_size"], policy["batch_order_seed"])
        model.train()
        optimizer.zero_grad(set_to_none=True)
        loss = _loss(torch, model, [records[index] for index in indices], policy["modality_loss_weight"])
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
    model.eval()
    total, measured = 0., 0
    with torch.no_grad():
        for start in range(0, len(tuning), policy["batch_size"]):
            if time.monotonic() >= deadline:
                break
            batch = tuning[start:start + policy["batch_size"]]
            loss = _loss(torch, model, batch, policy["modality_loss_weight"])
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
    report = {"schema": "bounded-curriculum-span-legal-formula-training/v1",
        "checkpoint_sha256": checkpoint_digest(updated),
        "continuation_checkpoint_sha256": checkpoint_digest(updated_child),
        "base_checkpoint_sha256": checkpoint_digest(updated_base),
        "previous_curriculum_checkpoint_sha256": checkpoint_digest(checkpoint),
        "source_parent_checkpoint_sha256": checkpoint["source_parent_checkpoint_sha256"],
        "source_parent_model_state_sha256": checkpoint["source_parent_model_state_sha256"],
        "training_policy": copy.deepcopy(policy), "training_policy_sha256": checkpoint_digest(policy),
        "initial_curriculum_checkpoint_sha256": checkpoint["initial_curriculum_checkpoint_sha256"],
        "optimizer_steps": len(losses), "continuation_optimizer_steps_total": progress["optimizer_steps"],
        "training_executed": bool(losses), "batch_losses": losses, "batch_trace": trace,
        "gradient_norm_max": maximum_gradient,
        "changed_parameter_names": [key for key in weights if weights[key] != base["model_state"][key]],
        "stopped_reason": reason, "elapsed_seconds": time.monotonic() - started,
        "deadline_scope": "soft_boundary_before_numeric_batch; initialization_and_serialization_not_interruptible",
        "partial_failure_scope": "only_successfully_returned_prefix_traced; exceptions_can_leave_unreturned_partial_updates_unknown",
        "tuning": {"objective_loss": total / measured if measured else None, "rows_evaluated": measured,
            "complete": measured == len(tuning), "teacher_forcing": True, "used_for_fit_or_selection": False,
            "objective_policy_sha256": checkpoint_digest(policy)}, **FALSE}
    return {"checkpoint": updated, "report": report}


class SpanCurriculumDecoder:
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
        _require(_implementation() == self._checkpoint["implementation"], "curriculum inference producer changed")
        report = self._decoder.decode_formal_logic(texts, latents, latent_ablation=latent_ablation)
        return {**report, "schema": "bounded-curriculum-span-legal-formula-inference/v1",
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
