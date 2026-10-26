"""Opt-in engineering fits and target-free decoding from live native4096 inputs.

Training and decoding require the completed native owner's live capability.
Model-only checkpoint restoration issues no live input capability. Saved
receipts cannot restore that capability. Source, target, split, exposure and
producer identities are checked before their respective numerical dispatch.
The caller retains resource/execution policy; this module starts no encoder,
adds no scheduler, and grants no statutory, semantic or proof qualification.
4096 denotes source input width, not an assertion about a bottleneck width.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
import hashlib
import json
import math
import os
from pathlib import Path
import stat

from . import legal_span_consumer_binding as base
from . import legal_span_bound_dimensions as checks
from . import legal_span_formula as span
from . import legal_span_native4096_binding as binding_owner
from . import legal_span_native4096_numeric as numeric

Native4096BoundError = base.SourceSpanConsumerBindingError
_PINS = tuple((Path(module.__file__), hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest())
              for module in (base, checks, binding_owner, numeric))
_SELF = (Path(__file__), hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
MAX_BYTES = min(base.MAX_BYTES, numeric.MAX_BYTES)


def _require(condition, message, *, receipt=None):
    if not condition:
        raise Native4096BoundError(message, receipt=receipt)


def _contract_errors(function):
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Native4096BoundError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as error:
            raise Native4096BoundError("native4096 contract failed: " + str(error)) from error
    return call


@dataclass(frozen=True, slots=True)
class Native4096BoundBatch:
    """Original declared inputs plus an independently issued live operation."""
    binding: binding_owner.Native4096SpanBinding
    rows: list
    split_manifest: dict
    eligibility_records: list
    exposure_records: list
    native_result: object
    expected_producer: dict


def _implementation():
    for path, digest in (_SELF, *_PINS):
        _require(hashlib.sha256(path.read_bytes()).hexdigest() == digest,
                 "bound native4096 implementation changed since import")
    binding_owner._implementation()
    numeric._implementation()


def _arguments(batch):
    _require(type(batch) is Native4096BoundBatch, "Native4096BoundBatch required")
    return {key: getattr(batch, key) for key in ("split_manifest", "eligibility_records",
            "exposure_records", "native_result", "expected_producer")}


def _originals(batch):
    arguments = _arguments(batch)
    return [batch.rows, *[value for key, value in arguments.items() if key != "native_result"]]


def _materialize_batches(training, tuning):
    batches = [training] if tuning is None else [training, tuning]
    guards = [base._guard(json.loads(base._preflight(_originals(batch)))) for batch in batches]
    rows, receipts = [], []
    for batch, operation in zip(batches, ("training", "hparam_selection")):
        _require(type(batch.binding) is binding_owner.Native4096SpanBinding,
                 "prepared Native4096SpanBinding required")
        receipt = batch.binding.receipt()
        _require(receipt["status"] == "ready", "bound batch is blocked", receipt=receipt)
        _require(receipt["operation"] == operation, "bound batch operation differs", receipt=receipt)
        _require(receipt["schema"] == binding_owner.SCHEMA and receipt["profile"] == binding_owner.PROFILE,
                 "native4096 engineering binding required")
        _require(receipt["context_contract"]["dimension"] == 4096, "native4096 input width required")
        materialized = binding_owner.consume_native4096_span_binding(batch.binding, batch.rows,
            **_arguments(batch), consumer=lambda value: value)
        base._guard(materialized, receipt["numerical_rows_sha256"])
        rows.append(materialized)
        receipts.append(receipt)
    if tuning is None:
        rows.append([])
    span._splits(rows[0], rows[1], 4096)
    contracts = {"training": None, "tuning": None}
    native_receipts = {"training": None, "tuning": None}
    for name, receipt in zip(contracts, receipts):
        contracts[name] = {key: receipt[key] for key in
            ("input_sha256s", "context_contract", "numerical_rows_sha256")}
        native_receipts[name] = receipt["native_receipt_sha256"]
    context = receipts[0]["context_contract"]
    numeric._batch_contracts(contracts, context, *[span.checkpoint_digest(value) for value in rows], len(rows[1]))
    numeric._native_receipts(native_receipts, len(rows[1]))
    # Replaying a later batch must not invalidate an earlier one during admission.
    for batch in batches:
        binding_owner.validate_native4096_span_binding(batch.binding, batch.rows, **_arguments(batch))
    for guard, batch in zip(guards, batches):
        base._check(guard, _originals(batch), "original native4096 batch changed during preflight")
    for value, receipt in zip(rows, receipts):
        base._guard(value, receipt["numerical_rows_sha256"])
    return rows[0], rows[1], context, contracts, native_receipts


def _parent_header(parent):
    checks._parent_header(parent)
    _require(parent["config"]["latent_dimension"] == 0, "literal source-only parent required")


def _header(checkpoint, materialized=None):
    base._closed(checkpoint, numeric._FIELDS, "bound native4096 checkpoint")
    _require(checkpoint["schema"] == numeric.SCHEMA and checkpoint["lineage_id"] == numeric.LINEAGE_ID
             and all(checkpoint[key] is False for key in span.FALSE), "native4096 schema/lineage/authority differs")
    base._check(base._guard(numeric._implementation()), checkpoint["implementation"], "numerical implementation")
    config = checkpoint["config"]
    checks._scalars(config)
    _require(type(config.get("latent_dimension")) is int and config["latent_dimension"] == 4096,
             "4096D bound checkpoint required")
    # The old configuration factory imports Torch. Validate its closed metadata
    # here without that import; numerical restore later checks installed version.
    constants = {"architecture": numeric.old.ARCHITECTURE, "latent_dimension": 4096,
        "device": "cpu", "dtype": "float32", "max_source_characters": span.MAX_SOURCE_CHARACTERS,
        "max_source_tokens": span.MAX_SOURCE_TOKENS, "max_token_bytes": span.MAX_TOKEN_BYTES,
        "tokenizer": "unicode_word_or_punctuation_exact_offsets/v1", "byte_alphabet": "casefold_utf8_plus1_pad0/v1",
        "initialization": "fresh_native4096_adapter_exact_zero_output/v1",
        "loss": "equal_facet_modality_presence_mean_start_end/v1"}
    base._closed(config, {*constants, *numeric.old._CONFIG_KEYS, "torch_version"}, "native configuration")
    for key, value in constants.items():
        _require(span._raw(config[key]) == span._raw(value), "native configuration differs: " + key)
    _require(type(config["torch_version"]) is str and 0 < len(config["torch_version"]) <= 128,
             "bounded recorded Torch version required")
    context = numeric.old._context_contract(checkpoint["context_contract"])
    base._guard(context, checkpoint["context_contract_sha256"])
    parent = checkpoint["source_parent_checkpoint"]
    _parent_header(parent)
    base._guard(parent, checkpoint["source_parent_checkpoint_sha256"])
    _require(type(checkpoint["source_parent_optimizer_steps"]) is int and
             checkpoint["source_parent_optimizer_steps"] == parent["progress"]["optimizer_steps"],
             "source-parent update count differs")
    for key in ("seed", "hidden_size", "embedding_dim", "projection_width", "residual_scale"):
        _require(span._raw(config[key]) == span._raw(parent["config"][key]), "inherited configuration differs: " + key)
    for key in ("initial_source_model_sha256", "initial_model_state_sha256"):
        base._sha256(checkpoint[key], key)
    checks._progress(checkpoint)
    _require((checkpoint["progress"]["optimizer_steps"] == 0) == (checkpoint["parent_checkpoint_sha256"] is None),
             "checkpoint update and parent identity differ")
    _require(checkpoint["training_count"] <= 128 and checkpoint["tuning_count"] <= 128,
             "native operation population exceeds 128")
    numeric._batch_contracts(checkpoint["batch_contracts"], context, checkpoint["training_manifest_sha256"],
                            checkpoint["tuning_manifest_sha256"], checkpoint["tuning_count"])
    provenance = checkpoint["provenance"]
    base._closed(provenance, {"schema", "kind", "serialized_evidence_is_execution_authority",
        "initial_native_receipts", "last_native_receipts"}, "native provenance")
    _require(provenance["schema"] == "bound-native4096-input-provenance/v1" and
             provenance["kind"] == "live_bound_engineering_inputs" and
             provenance["serialized_evidence_is_execution_authority"] is False, "native provenance differs")
    for key in ("initial_native_receipts", "last_native_receipts"):
        numeric._native_receipts(provenance[key], checkpoint["tuning_count"])
    if checkpoint["progress"]["optimizer_steps"] == 0:
        _require(provenance["initial_native_receipts"] == provenance["last_native_receipts"],
                 "zero-update native receipt provenance differs")
    if materialized is not None:
        train, tune, training_context, contracts, _ = materialized
        base._check(base._guard(training_context), context, "training context")
        base._check(base._guard(contracts), checkpoint["batch_contracts"], "stable training/tuning bindings")
        for prefix, rows in (("training", train), ("tuning", tune)):
            _require(checkpoint[prefix + "_count"] == len(rows), "checkpoint " + prefix + " count differs")
            base._guard(rows, checkpoint[prefix + "_manifest_sha256"])


def _dispatch(original, detached, guard):
    base._check(guard, original, "original checkpoint changed before dispatch")
    base._check(guard, detached, "detached checkpoint changed before dispatch")
    _implementation()


@_contract_errors
def build_bound_checkpoint(parent, training, tuning=None, *, expected_parent_sha256,
        learning_rate=.001, batch_size=12, latent_enabled=True):
    detached, guard = checks._snapshot(parent, expected_parent_sha256)
    _parent_header(detached)
    checks._scalars({**{key: detached["config"][key] for key in
        ("seed", "hidden_size", "embedding_dim", "projection_width", "residual_scale")},
        "learning_rate": learning_rate, "batch_size": batch_size, "latent_enabled": latent_enabled})
    train, tune, context, contracts, receipts = _materialize_batches(training, tuning)
    _dispatch(parent, detached, guard)
    return numeric._build(detached, train, tune, context_contract=context, batch_contracts=contracts,
        native_receipts=receipts, learning_rate=learning_rate, batch_size=batch_size, latent_enabled=latent_enabled)


@_contract_errors
def train_bound_decoder(checkpoint, training, tuning=None, *, expected_checkpoint_sha256,
                        max_steps=100, max_seconds=60):
    _require(type(max_steps) is int and 0 <= max_steps <= 10000, "bounded integer max_steps required")
    _require(type(max_seconds) in (int, float) and math.isfinite(max_seconds) and 0 <= max_seconds <= 3600,
             "bounded finite max_seconds required")
    detached, guard = checks._snapshot(checkpoint, expected_checkpoint_sha256)
    materialized = _materialize_batches(training, tuning)
    _header(detached, materialized)
    _dispatch(checkpoint, detached, guard)
    return numeric._train(detached, materialized[0], materialized[1], native_receipts=materialized[4],
                          max_steps=max_steps, max_seconds=max_seconds)


@_contract_errors
def save_bound_checkpoint(checkpoint, path, training, tuning=None, *, expected_checkpoint_sha256):
    detached, guard = checks._snapshot(checkpoint, expected_checkpoint_sha256)
    materialized = _materialize_batches(training, tuning)
    _header(detached, materialized)
    _dispatch(checkpoint, detached, guard)
    numeric._restore(detached)
    raw = span._raw(detached) + b"\n"
    _require(len(raw) <= MAX_BYTES, "checkpoint exceeds file byte bound")
    path = Path(path)
    _require(path.parent.resolve(strict=True) == path.parent.absolute(), "canonical existing parent required")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    created = os.fstat(fd)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        # Clean up only our own incomplete leaf; preserve a replacement made by
        # another writer. The directory must already be caller-controlled.
        try:
            leaf = path.stat(follow_symlinks=False)
            if (leaf.st_dev, leaf.st_ino) == (created.st_dev, created.st_ino) and leaf.st_nlink == 1:
                path.unlink()
        except OSError:
            pass
        raise
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "schema": numeric.SCHEMA}


def _read(path, expected_sha256):
    base._sha256(expected_sha256, "expected checkpoint file SHA256")
    path = Path(path)
    _require(path.parent.resolve(strict=True) == path.parent.absolute(), "canonical existing parent required")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    def identity(value):
        return (value.st_dev, value.st_ino, value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= MAX_BYTES,
                 "bounded single-link regular checkpoint required")
        raw = stream.read(MAX_BYTES + 1)
        after = os.fstat(stream.fileno())
        leaf = path.stat(follow_symlinks=False)
        _require(stat.S_ISREG(leaf.st_mode) and identity(before) == identity(after) == identity(leaf)
                 and len(raw) == before.st_size, "checkpoint file changed during read")
    _require(hashlib.sha256(raw).hexdigest() == expected_sha256, "checkpoint file SHA256 differs")
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate checkpoint JSON key")
            result[key] = value
        return result
    def nonfinite(value):
        raise Native4096BoundError("nonfinite checkpoint JSON: " + value)
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)


@_contract_errors
def load_bound_checkpoint(path, training, tuning=None, *, expected_sha256):
    checkpoint = _read(path, expected_sha256)
    # Strict plain-data and canonical-size guard before constructing tensors.
    detached, guard = checks._snapshot(checkpoint, span.checkpoint_digest(checkpoint))
    materialized = _materialize_batches(training, tuning)
    _header(detached, materialized)
    _dispatch(checkpoint, detached, guard)
    numeric._restore(detached)
    return detached


@_contract_errors
def load_bound_inference_checkpoint(path, *, expected_sha256):
    """Restore a pinned historical model without live training inputs.

    Validate the original source profile, complete weights and named optimizer
    moments using the unchanged numerical owner. Construct no optimizer and
    execute no forward or native encoder. The returned plain checkpoint grants
    no training, inference, source compatibility, teacher or proof authority;
    ``decode_bound_sources`` still requires a freshly issued native capability.
    """
    checkpoint = _read(path, expected_sha256)
    detached, guard = checks._snapshot(checkpoint, span.checkpoint_digest(checkpoint))
    _header(detached)
    _dispatch(checkpoint, detached, guard)
    numeric._restore(detached)
    closing = _read(path, expected_sha256)
    base._check(guard, closing, "checkpoint file changed during model restoration")
    _dispatch(checkpoint, detached, guard)
    return detached


@_contract_errors
def decode_bound_sources(checkpoint, sources, *, expected_checkpoint_sha256, native_result,
        expected_producer, expected_producer_sha256, expected_native_receipt_sha256, latent_ablation="none"):
    _require(type(latent_ablation) is str and latent_ablation in ("none", "zero", "rotate", "disabled"),
             "unsupported latent ablation")
    detached, guard = checks._snapshot(checkpoint, expected_checkpoint_sha256)
    _header(detached)
    source_copy = json.loads(base._preflight(sources))
    source_guard = base._guard(source_copy)
    _require(type(source_copy) is list and 1 <= len(source_copy) <= 128, "one through 128 target-free sources required")
    identifiers = set()
    for row in source_copy:
        base._closed(row, {"id", "source_text"}, "target-free source")
        _require(type(row["id"]) is str and 0 < len(row["id"]) <= 256 and row["id"] not in identifiers,
                 "unique bounded source IDs required")
        identifiers.add(row["id"])
        span.tokenize_source(row["source_text"])
    _require(latent_ablation != "rotate" or len(source_copy) >= 2, "rotate requires at least two sources")
    producer = json.loads(base._preflight(expected_producer))
    base._sha256(expected_producer_sha256, "expected producer SHA256")
    base._sha256(expected_native_receipt_sha256, "expected native receipt SHA256")
    producer_guard = base._guard(producer, expected_producer_sha256)
    context = detached["context_contract"]
    _require(context["producer_sha256"] == expected_producer_sha256, "checkpoint native producer differs")
    handle = binding_owner._receive(native_result, source_copy, producer)
    observed = binding_owner._read(handle)
    observation_guard = base._guard(observed)
    _require(observed["dimension"] == 4096 and observed["profile"] == context["representation_id"],
             "native inference representation differs")
    _require(observed["native_provenance"]["receipt_sha256"] == expected_native_receipt_sha256,
             "native inference receipt differs")
    latents = [row["embedding"][:] for row in observed["rows"]]
    base._check(observation_guard, binding_owner._read(handle), "native inference capability changed")
    base._check(source_guard, sources, "original inference sources changed")
    base._check(source_guard, source_copy, "detached inference sources changed")
    base._check(producer_guard, expected_producer, "original inference producer changed")
    _dispatch(checkpoint, detached, guard)
    result = numeric._decode(detached, [row["source_text"] for row in source_copy], latents,
                             latent_ablation=latent_ablation)
    result["native_input_binding"] = {
        "schema": "bound-native4096-inference-inputs/v1", "sources_sha256": source_guard.sha256,
        "source_ids": [row["id"] for row in source_copy], "producer_sha256": producer_guard.sha256,
        "native_receipt_sha256": expected_native_receipt_sha256,
        "verified_observation_sha256": observation_guard.sha256,
        "serialized_evidence_is_execution_authority": False}
    return result


__all__ = ["Native4096BoundBatch", "Native4096BoundError", "build_bound_checkpoint", "train_bound_decoder",
           "save_bound_checkpoint", "load_bound_checkpoint", "load_bound_inference_checkpoint",
           "decode_bound_sources"]
