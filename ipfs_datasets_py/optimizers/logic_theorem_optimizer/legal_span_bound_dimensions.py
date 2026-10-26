"""Opt-in 384D/768D engineering batches over the unchanged dimensional owner.

Context producer evidence, complete split/exposure declarations and independent
checkpoint pins are checked before numerical dispatch. Training and tuning keep
separate row identities; only the training population defines checkpoint context
lineage. This profile does not admit reviewed statutory targets or 4096D heads.
It adds no semantic qualification, resource grant, automatic retry or scheduler.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import stat

from . import legal_span_consumer_binding as base
from . import legal_span_context_binding as context_owner
from . import legal_span_dimensions as dims
from . import legal_span_formula as span

SourceSpanContextBindingError = context_owner.SourceSpanContextBindingError
def _require(condition, message, *, receipt=None):
    if not condition:
        raise SourceSpanContextBindingError(message, receipt=receipt)

_PINS = tuple((Path(module.__file__), hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest())
              for module in (base, context_owner, dims))
_SELF = (Path(__file__), hashlib.sha256(Path(__file__).read_bytes()).hexdigest())


@dataclass(frozen=True, slots=True)
class ContextBoundBatch:
    """Caller-owned originals, rechecked on every use; no numerical authority."""
    binding: context_owner.SourceSpanContextBinding
    rows: list
    split_manifest: dict
    eligibility_records: list
    exposure_records: list
    contexts: list
    context_evidence: dict
    source_resolver: object = None


def _implementation():
    for path, digest in (_SELF, *_PINS):
        _require(hashlib.sha256(path.read_bytes()).hexdigest() == digest,
                 "bound dimensional implementation changed since import")
    dims._implementation()


def _arguments(batch):
    _require(type(batch) is ContextBoundBatch, "ContextBoundBatch required")
    return {name: getattr(batch, name) for name in ("split_manifest", "eligibility_records",
            "exposure_records", "contexts", "context_evidence", "source_resolver")}


def _originals(batch):
    arguments = _arguments(batch)
    return [batch.rows, *[value for name, value in arguments.items() if name != "source_resolver"]]


def _stage(stage, representation):
    _require(type(stage) is str and stage in context_owner.STAGES, "unsupported native context stage")
    _require(representation["dimension"] == (768 if stage == "native768" else 384),
             "context stage and dimension differ")
    # The original 384 producer includes stage in both identity and producer
    # digest. Native768 has one stage, checked by its original manifest owner.
    if stage != "native768":
        _require(representation["representation_id"] == "actual_frozen_legal_ir/" + stage + "/v1",
                 "native384 representation does not bind the requested stage")


def _materialize_batches(training, tuning):
    batches = [training] if tuning is None else [training, tuning]
    originals = [_originals(batch) for batch in batches]
    guards = [base._guard(json.loads(base._preflight(value))) for value in originals]
    receipts, rows = [], []
    for batch, operation in zip(batches, ("training", "hparam_selection")):
        _require(type(batch.binding) is context_owner.SourceSpanContextBinding,
                 "prepared SourceSpanContextBinding required")
        receipt = batch.binding.receipt()
        _require(receipt["status"] == "ready", "bound batch is blocked", receipt=receipt)
        _require(receipt["operation"] == operation, "bound batch operation differs", receipt=receipt)
        _require(receipt["profile"] == context_owner.PROFILE, "native engineering profile required")
        _stage(receipt["context_stage"], receipt["context_contract"])
        materialized = context_owner.consume_source_span_context_binding(batch.binding, batch.rows,
            **_arguments(batch), consumer=lambda value: value)
        base._check(base._guard(materialized, receipt["numerical_rows_sha256"]), materialized,
                    "numerical rows")
        receipts.append(receipt)
        rows.append(materialized)
    train = receipts[0]
    if len(receipts) == 2:
        tune = receipts[1]
        _require(train["input_sha256s"]["split_manifest"] == tune["input_sha256s"]["split_manifest"],
                 "training and tuning require the same complete split manifest")
        _require(train["context_stage"] == tune["context_stage"] and
                 all(train["context_contract"][key] == tune["context_contract"][key]
                     for key in ("dimension", "representation_id", "producer_sha256")),
                 "training and tuning context representations differ")
    else:
        rows.append([])
    try:
        span._splits(rows[0], rows[1], train["latent_dimension"])
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        raise SourceSpanContextBindingError("bound dimensional rows differ: " + str(error)) from error
    # A later batch's resolver must not change an earlier batch after admission.
    for guard, batch in zip(guards, batches):
        base._check(guard, _originals(batch), "original batch changed during preflight")
    return rows[0], rows[1], train["context_contract"]


def _snapshot(checkpoint, digest):
    base._sha256(digest, "expected canonical checkpoint SHA256")
    raw = base._preflight(checkpoint)
    guard = base._guard(checkpoint, digest)
    detached = json.loads(raw)
    base._check(guard, detached, "detached checkpoint")
    return detached, guard


def _scalars(config):
    _require(type(config) is dict, "checkpoint config mapping required")
    for key, low, high in (("batch_size", 1, 32), ("seed", 0, 2**31-1),
            ("hidden_size", 8, 128), ("embedding_dim", 4, 64), ("projection_width", 4, 128)):
        value = config.get(key)
        _require(type(value) is int and low <= value <= high, "invalid " + key)
    for key, high in (("learning_rate", .1), ("residual_scale", 1)):
        value = config.get(key)
        _require(type(value) in (int, float) and math.isfinite(value) and 0 < value <= high,
                 "invalid " + key)
    _require(type(config.get("latent_enabled")) is bool, "latent_enabled must be boolean")


def _progress(checkpoint):
    for prefix, low in (("training", 1), ("tuning", 0)):
        value = checkpoint.get(prefix + "_count")
        _require(type(value) is int and low <= value <= span.MAX_EXAMPLES, "invalid split counts")
        base._sha256(checkpoint.get(prefix + "_manifest_sha256"), "data manifest SHA256")
    progress = checkpoint.get("progress")
    base._closed(progress, {"epochs_completed", "row_cursor", "optimizer_steps"}, "progress")
    _require(all(type(v) is int and 0 <= v <= 10**9 for v in progress.values()), "invalid progress")
    count, batch = checkpoint["training_count"], checkpoint["config"]["batch_size"]
    cursor = progress["row_cursor"]
    _require(cursor < count and cursor % batch == 0 and progress["optimizer_steps"] ==
             progress["epochs_completed"] * math.ceil(count / batch) + cursor // batch,
             "checkpoint step/cursor identity differs")
    previous = checkpoint.get("parent_checkpoint_sha256")
    if previous is not None:
        base._sha256(previous, "previous checkpoint SHA256")
    _require(progress["optimizer_steps"] == 0 or previous is not None, "trained checkpoint lacks parent")


def _parent_header(parent):
    fields = {"schema", "lineage_id", "config", "implementation", "training_manifest_sha256", "training_count",
        "tuning_manifest_sha256", "tuning_count", "model_state", "optimizer_state", "progress",
        "parent_checkpoint_sha256", *span.FALSE}
    base._closed(parent, fields, "source parent")
    _require(parent["schema"] == span.SCHEMA and parent["lineage_id"] == span.LINEAGE_ID
             and all(parent[key] is False for key in span.FALSE), "source parent schema/lineage/authority differs")
    base._check(base._guard(span._implementation()), parent["implementation"], "source implementation")
    _scalars(parent["config"])
    _require(type(parent["config"].get("latent_dimension")) is int and
             parent["config"]["latent_dimension"] in (0, 384) and
             (not parent["config"]["latent_enabled"] or parent["config"]["latent_dimension"] == 0),
             "source-only parent required")
    _progress(parent)
    _require(parent["progress"]["optimizer_steps"] > 0, "trained source parent required")


def _header(checkpoint, materialized=None):
    fields = {"schema", "lineage_id", "implementation", "initialization", "config", "context_contract",
        "context_contract_sha256", "source_parent_checkpoint", "source_parent_checkpoint_sha256",
        "source_parent_optimizer_steps", "initial_source_model_sha256", "initial_model_state_sha256",
        "training_manifest_sha256", "training_count", "tuning_manifest_sha256", "tuning_count", "model_state",
        "optimizer_state", "progress", "parent_checkpoint_sha256", *span.FALSE}
    base._closed(checkpoint, fields, "dimensional checkpoint")
    _require(checkpoint["schema"] == dims.SCHEMA and checkpoint["lineage_id"] == dims.LINEAGE_ID
        and all(checkpoint[key] is False for key in span.FALSE), "dimensional schema/lineage/authority differs")
    base._check(base._guard(dims._implementation()), checkpoint["implementation"], "dimensional implementation")
    base._check(base._guard(dims._INITIALIZATION), checkpoint["initialization"], "initialization policy")
    config = checkpoint["config"]
    _scalars(config)
    _require(type(config.get("latent_dimension")) is int and config["latent_dimension"] in (384, 768),
             "384D or 768D bound checkpoint required")
    try:
        contract = dims._context_contract(checkpoint["context_contract"], config["latent_dimension"])
    except ValueError as error:
        raise SourceSpanContextBindingError(str(error)) from error
    base._check(base._guard(contract, checkpoint["context_contract_sha256"]), contract, "context contract")
    _parent_header(checkpoint["source_parent_checkpoint"])
    base._guard(checkpoint["source_parent_checkpoint"], checkpoint["source_parent_checkpoint_sha256"])
    _require(type(checkpoint["source_parent_optimizer_steps"]) is int and
             checkpoint["source_parent_optimizer_steps"] ==
             checkpoint["source_parent_checkpoint"]["progress"]["optimizer_steps"], "parent update count differs")
    for key in ("seed", "hidden_size", "embedding_dim", "projection_width", "residual_scale"):
        _require(span._raw(config[key]) == span._raw(checkpoint["source_parent_checkpoint"]["config"][key]),
                 "inherited configuration differs: " + key)
    for key in ("initial_source_model_sha256", "initial_model_state_sha256"):
        base._sha256(checkpoint[key], key)
    _progress(checkpoint)
    if materialized is not None:
        train, tune, training_contract = materialized
        base._check(base._guard(training_contract), contract, "training context contract")
        for prefix, rows in (("training", train), ("tuning", tune)):
            _require(checkpoint[prefix + "_count"] == len(rows), "checkpoint " + prefix + " count differs")
            base._guard(rows, checkpoint[prefix + "_manifest_sha256"])


def _dispatch_check(original, detached, guard):
    base._check(guard, original, "original checkpoint changed before dispatch")
    base._check(guard, detached, "detached checkpoint changed before dispatch")
    _implementation()


def build_bound_checkpoint(parent, training, tuning=None, *, expected_parent_sha256,
        learning_rate=.001, batch_size=12, latent_enabled=True):
    """Copy a trained source-only parent with the admitted training context."""
    _implementation()
    _require(type(learning_rate) in (int, float) and math.isfinite(learning_rate) and 0 < learning_rate <= .1,
             "invalid learning_rate")
    _require(type(batch_size) is int and 1 <= batch_size <= 32, "invalid batch_size")
    _require(type(latent_enabled) is bool, "latent_enabled must be boolean")
    detached, guard = _snapshot(parent, expected_parent_sha256)
    _parent_header(detached)
    train, tune, contract = _materialize_batches(training, tuning)
    _dispatch_check(parent, detached, guard)
    return dims.build_checkpoint(detached, train, tune, latent_dimension=contract["dimension"],
        latent_enabled=latent_enabled, context_contract=contract, learning_rate=learning_rate, batch_size=batch_size)


def train_bound_decoder(checkpoint, training, tuning=None, *, expected_checkpoint_sha256,
        max_steps=100, max_seconds=60):
    """Resume the exact dimensional model, Adam moments and ordered batches."""
    _implementation()
    _require(type(max_steps) is int and 0 <= max_steps <= 10000, "max_steps must be in 0..10000")
    _require(type(max_seconds) in (int, float) and math.isfinite(max_seconds) and 0 <= max_seconds <= 3600,
             "max_seconds must be in 0..3600")
    detached, guard = _snapshot(checkpoint, expected_checkpoint_sha256)
    materialized = _materialize_batches(training, tuning)
    _header(detached, materialized)
    _dispatch_check(checkpoint, detached, guard)
    return dims.train_decoder(detached, *materialized[:2], max_steps=max_steps, max_seconds=max_seconds)


def save_bound_checkpoint(checkpoint, path, training, tuning=None, *, expected_checkpoint_sha256):
    """Use the original exclusive-create writer after training-batch preflight.

    This training-lifecycle API retains the owner's full Adam validation;
    optimizer-free restoration is specific to target-free inference.
    """
    _implementation()
    detached, guard = _snapshot(checkpoint, expected_checkpoint_sha256)
    _header(detached, _materialize_batches(training, tuning))
    _dispatch_check(checkpoint, detached, guard)
    return dims.save_checkpoint(detached, path)


def _read(path, expected_sha256):
    base._sha256(expected_sha256, "expected raw checkpoint SHA256")
    path = Path(path).absolute()
    _require(path.resolve(strict=True) == path, "canonical checkpoint path required")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        _require(stat.S_ISREG(before.st_mode) and before.st_size <= dims.MAX_BYTES,
                 "bounded regular checkpoint required")
        raw = stream.read(dims.MAX_BYTES + 1)
        after = os.fstat(stream.fileno())
    _require(len(raw) <= dims.MAX_BYTES and (before.st_size, before.st_mtime_ns) ==
             (after.st_size, after.st_mtime_ns), "checkpoint changed while reading")
    _require(hashlib.sha256(raw).hexdigest() == expected_sha256, "raw checkpoint hash differs")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate checkpoint JSON key")
            result[key] = value
        return result
    def reject(value):
        raise SourceSpanContextBindingError("invalid JSON constant: " + value)
    return json.loads(raw, object_pairs_hook=unique, parse_constant=reject)


def load_bound_checkpoint(path, training, tuning=None, *, expected_sha256):
    """Raw-file pin first, batch/lineage admission before numerical restoration."""
    _implementation()
    checkpoint = _read(path, expected_sha256)
    detached, guard = _snapshot(checkpoint, base._guard(checkpoint).sha256)
    _header(detached, _materialize_batches(training, tuning))
    _dispatch_check(checkpoint, detached, guard)
    dims.validate_checkpoint(detached)
    return detached


def decode_bound_sources(checkpoint, sources, *, expected_checkpoint_sha256, stage,
        contexts, expected_contexts_sha256, context_evidence, expected_context_evidence_sha256,
        source_resolver=None, latent_ablation="none"):
    """Target-free CPU decode over source-bound original producer evidence.

    Inference sources may be new or held out; they do not replace the training
    index embedded in the checkpoint. No canonical targets are accepted here.
    """
    _implementation()
    _require(type(latent_ablation) is str and latent_ablation in ("none", "zero", "rotate", "disabled"),
             "unsupported latent ablation")
    detached, checkpoint_guard = _snapshot(checkpoint, expected_checkpoint_sha256)
    _header(detached)
    base._sha256(expected_contexts_sha256, "expected contexts SHA256")
    base._sha256(expected_context_evidence_sha256, "expected context evidence SHA256")
    originals = [sources, contexts, context_evidence]
    source_guard = base._guard(json.loads(base._preflight(originals)))
    copied_sources, copied_contexts, copied_evidence = json.loads(base._preflight(originals))
    _require(type(copied_sources) is list and 1 <= len(copied_sources) <= 128,
             "bounded nonempty inference sources required")
    for source in copied_sources:
        base._closed(source, {"id", "source_text"}, "target-free inference source")
        base._text(source["id"], "source id", 512)
        base._text(source["source_text"], "source text", span.MAX_SOURCE_CHARACTERS)
        try:
            span.tokenize_source(source["source_text"])
        except ValueError as error:
            raise SourceSpanContextBindingError(str(error)) from error
    _require(len({s["id"] for s in copied_sources}) == len(copied_sources), "duplicate inference source id")
    _require(latent_ablation != "rotate" or len(copied_sources) > 1, "rotate requires at least two sources")
    context_guard = base._guard(copied_contexts, expected_contexts_sha256)
    evidence_guard = base._guard(copied_evidence, expected_context_evidence_sha256)
    implementation_guard = base._guard(context_owner._implementation(stage))
    context_owner._contexts(copied_sources, copied_contexts, detached["config"]["latent_dimension"])
    verification = context_owner._verify(stage, copied_sources, copied_evidence, source_resolver)
    representation = context_owner._representation(verification, stage)
    _stage(stage, representation)
    base._check(context_guard, context_owner._verification_contexts(verification), "original producer contexts")
    contract = detached["context_contract"]
    _require(all(contract[key] == representation[key] for key in representation),
             "inference representation differs from checkpoint context")
    base._check(evidence_guard, copied_evidence, "verified evidence changed")
    base._check(source_guard, originals, "original inference arguments changed")
    base._check(source_guard, [copied_sources, copied_contexts, copied_evidence], "detached inference arguments changed")
    base._check(implementation_guard, context_owner._implementation(stage), "context implementation")
    _dispatch_check(checkpoint, detached, checkpoint_guard)
    from .legal_span_dimensions_cpu_inference import CpuDimensionalSpanDecoder
    return CpuDimensionalSpanDecoder(detached).decode_formal_logic(
        [s["source_text"] for s in copied_sources], [c["context"] for c in copied_contexts],
        latent_ablation=latent_ablation)


__all__ = ["ContextBoundBatch", "SourceSpanContextBindingError", "build_bound_checkpoint",
           "train_bound_decoder", "save_bound_checkpoint", "load_bound_checkpoint", "decode_bound_sources"]
