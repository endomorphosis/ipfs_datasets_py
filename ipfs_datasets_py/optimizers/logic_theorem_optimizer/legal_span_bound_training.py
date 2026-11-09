"""Opt-in numerical entrypoints over complete zero-latent engineering bindings.

Existing span functions, checkpoint schemas and optimizer behavior are
unchanged. Batch declarations establish argument custody, not reviewed gold.
All wrapper checks precede dispatch; owner results and exceptions pass through
once, with no late validation or retry of numerical work.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import hashlib
import re

from . import legal_span_consumer_binding as binding_owner
from . import legal_span_formula as span
from .checkpoint_content_guard import CheckpointContentGuard
from .legal_span_consumer_binding import SourceSpanConsumerBindingError


_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SOURCE_PATH = Path(__file__)
_SOURCE_AT_IMPORT = hashlib.sha256(_SOURCE_PATH.read_bytes()).hexdigest()
_BINDING_SOURCE_PATH = Path(binding_owner.__file__)
_BINDING_SOURCE_AT_IMPORT = hashlib.sha256(_BINDING_SOURCE_PATH.read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class SourceSpanBoundBatch:
    """Original input container; frozen fields do not grant input authority.

    Nested originals remain caller-owned and are checked by the existing
    binding on every wrapper call. Numerical owners receive detached copies.
    """
    binding: binding_owner.SourceSpanConsumerBinding
    rows: list
    split_manifest: dict
    eligibility_records: list
    exposure_records: list


def _require(condition, message, *, receipt=None):
    if not condition:
        raise SourceSpanConsumerBindingError(message, receipt=receipt)


def _implementation():
    try:
        _require(hashlib.sha256(_SOURCE_PATH.read_bytes()).hexdigest() == _SOURCE_AT_IMPORT,
                 "bound training wrapper source changed since import")
        _require(hashlib.sha256(_BINDING_SOURCE_PATH.read_bytes()).hexdigest() == _BINDING_SOURCE_AT_IMPORT,
                 "consumer binding source changed since wrapper import")
    except OSError as error:
        raise SourceSpanConsumerBindingError("bound training source custody unavailable") from error
    return {"wrapper_sha256": _SOURCE_AT_IMPORT, "consumer_binding_sha256": _BINDING_SOURCE_AT_IMPORT,
            "scope": "listed_direct_wrapper_and_consumer_binding_sources_only"}


def _guard(value, expected_sha256=None):
    try:
        return CheckpointContentGuard(value, expected_sha256=expected_sha256)
    except (ValueError, TypeError, OverflowError, RecursionError) as error:
        raise SourceSpanConsumerBindingError(str(error)) from error


def _check(guard, value, message):
    try:
        guard.check(value, message=message)
    except (ValueError, TypeError, OverflowError, RecursionError) as error:
        raise SourceSpanConsumerBindingError(str(error)) from error


def _batch_arguments(batch):
    _require(type(batch) is SourceSpanBoundBatch, "SourceSpanBoundBatch required")
    return {"split_manifest": batch.split_manifest, "eligibility_records": batch.eligibility_records,
            "exposure_records": batch.exposure_records}


def _batch_receipt(batch, operation):
    arguments = _batch_arguments(batch)
    receipt = binding_owner.validate_source_span_consumer_binding(batch.binding, batch.rows, **arguments)
    _require(receipt["status"] == "ready", "bound batch is blocked", receipt=receipt)
    _require(receipt["operation"] == operation, "bound batch operation differs", receipt=receipt)
    _require(receipt["profile"] == binding_owner.PROFILE
             and type(receipt["latent_dimension"]) is int and receipt["latent_dimension"] == 0,
             "zero-latent bound batch required", receipt=receipt)
    return receipt


def _materialize_batches(training, tuning):
    train_receipt = _batch_receipt(training, "training")
    tune_receipt = None if tuning is None else _batch_receipt(tuning, "hparam_selection")
    if tune_receipt is not None:
        _require(train_receipt["input_sha256s"]["split_manifest"] ==
                 tune_receipt["input_sha256s"]["split_manifest"],
                 "training and tuning require the same complete split manifest")
    # Validate both original batches before either fixed identity callback.
    train_rows = binding_owner.consume_source_span_binding(training.binding, training.rows,
        **_batch_arguments(training), consumer=lambda rows: rows)
    tune_rows = [] if tuning is None else binding_owner.consume_source_span_binding(tuning.binding, tuning.rows,
        **_batch_arguments(tuning), consumer=lambda rows: rows)
    train_guard = _guard(train_rows, train_receipt["input_sha256s"]["rows"])
    tune_guard = _guard(tune_rows, None if tune_receipt is None else tune_receipt["input_sha256s"]["rows"])
    try:
        span._splits(train_rows, tune_rows, 0)
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as error:
        raise SourceSpanConsumerBindingError("bound training/tuning inputs differ: " + str(error)) from error
    _check(train_guard, train_rows, "detached training rows changed during preflight")
    _check(tune_guard, tune_rows, "detached tuning rows changed during preflight")
    return train_rows, tune_rows, train_guard.sha256, tune_guard.sha256


def _build_options(learning_rate, batch_size, seed, hidden_size, embedding_dim, projection_width, residual_scale):
    # Match the owner's inexpensive scalar gates without calling its Torch
    # config factory or constructing a second model/config serialization.
    for value, low, high, label in ((batch_size, 1, 32, "batch_size"),
            (seed, 0, 2**31 - 1, "seed"), (hidden_size, 8, 128, "hidden_size"),
            (embedding_dim, 4, 64, "embedding_dim"), (projection_width, 4, 128, "projection_width")):
        _require(type(value) is int and low <= value <= high, "invalid " + label)
    _require(type(learning_rate) in (int, float) and 0 < learning_rate <= .1
             and math.isfinite(learning_rate), "learning_rate outside (0, .1]")
    _require(type(residual_scale) in (int, float) and 0 < residual_scale <= 1
             and math.isfinite(residual_scale), "residual_scale outside (0, 1]")
    return {"learning_rate": learning_rate, "batch_size": batch_size, "seed": seed,
            "hidden_size": hidden_size, "embedding_dim": embedding_dim,
            "projection_width": projection_width, "residual_scale": residual_scale}


def build_bound_checkpoint(training, tuning=None, *, learning_rate=.003, batch_size=12, seed=1729,
        hidden_size=32, embedding_dim=16, projection_width=16, residual_scale=.25):
    """Validate complete bound batches before the unchanged checkpoint builder.

    ``tuning=None`` explicitly supplies no tuning rows. Latent dimension and
    enabled flag are fixed at zero and True; unknown keywords never dispatch.
    """
    _implementation()
    options = _build_options(learning_rate, batch_size, seed, hidden_size,
                             embedding_dim, projection_width, residual_scale)
    train_rows, tune_rows, _, _ = _materialize_batches(training, tuning)
    _implementation()
    return span.build_checkpoint(train_rows, tune_rows, latent_dimension=0, latent_enabled=True, **options)


def _checkpoint_header(checkpoint, train_rows, tune_rows, train_sha256, tune_sha256):
    fields = {"schema", "lineage_id", "config", "implementation", "training_manifest_sha256", "training_count",
              "tuning_manifest_sha256", "tuning_count", "model_state", "optimizer_state", "progress",
              "parent_checkpoint_sha256", *span.FALSE}
    _require(type(checkpoint) is dict and set(checkpoint) == fields, "closed span checkpoint header required")
    _require(checkpoint["schema"] == span.SCHEMA and checkpoint["lineage_id"] == span.LINEAGE_ID
             and all(checkpoint[key] is False for key in span.FALSE), "span checkpoint schema/lineage/authority differs")
    current_implementation = _guard(span._implementation())
    _check(current_implementation, checkpoint["implementation"], "span checkpoint implementation differs")
    config = checkpoint["config"]
    _require(type(config) is dict and type(config.get("latent_dimension")) is int
             and config["latent_dimension"] == 0, "zero-latent checkpoint required")
    batch_size = config.get("batch_size")
    _require(type(batch_size) is int and 1 <= batch_size <= 32, "valid checkpoint batch_size required")
    for prefix, rows, expected_sha in (("training", train_rows, train_sha256), ("tuning", tune_rows, tune_sha256)):
        _require(type(checkpoint[prefix + "_count"]) is int and checkpoint[prefix + "_count"] == len(rows),
                 "checkpoint " + prefix + " count differs from bound rows")
        digest = checkpoint[prefix + "_manifest_sha256"]
        _require(type(digest) is str and _SHA.fullmatch(digest) is not None and digest == expected_sha,
                 "checkpoint " + prefix + " manifest differs from ordered bound rows")
    parent = checkpoint["parent_checkpoint_sha256"]
    _require(parent is None or type(parent) is str and _SHA.fullmatch(parent) is not None,
             "valid parent checkpoint SHA256 or None required")
    progress = checkpoint["progress"]
    _require(type(progress) is dict and set(progress) == {"epochs_completed", "row_cursor", "optimizer_steps"}
             and all(type(value) is int and 0 <= value <= 10**9 for value in progress.values()),
             "closed bounded checkpoint progress required")
    count = len(train_rows)
    cursor = progress["row_cursor"]
    _require(cursor < count and cursor % batch_size == 0 and progress["optimizer_steps"] ==
             progress["epochs_completed"] * math.ceil(count / batch_size) + cursor // batch_size,
             "checkpoint step/cursor identity differs")


def train_bound_decoder(checkpoint, training, tuning=None, *, expected_checkpoint_sha256,
        max_steps=100, max_seconds=60):
    """Resume unchanged Adam state only after batch and checkpoint custody checks.

    Expected checkpoint SHA256 is canonical content, not a raw-file digest.
    Tensor/config validation remains owned by the existing span implementation.
    No callback, alternate latent profile or arbitrary owner options are exposed.
    """
    _implementation()
    _require(type(max_steps) is int and 0 <= max_steps <= 10000, "max_steps must be in 0..10000")
    _require(type(max_seconds) in (int, float) and 0 <= max_seconds <= 3600 and math.isfinite(max_seconds),
             "max_seconds must be in 0..3600")
    _require(type(expected_checkpoint_sha256) is str and _SHA.fullmatch(expected_checkpoint_sha256) is not None,
             "expected checkpoint requires an exact lowercase canonical SHA256")
    train_rows, tune_rows, train_sha, tune_sha = _materialize_batches(training, tuning)
    raw = binding_owner._preflight(checkpoint)
    checkpoint_guard = _guard(checkpoint, expected_checkpoint_sha256)
    detached = json.loads(raw)
    _check(checkpoint_guard, detached, "detached checkpoint content differs")
    _checkpoint_header(detached, train_rows, tune_rows, train_sha, tune_sha)
    _check(checkpoint_guard, checkpoint, "original checkpoint changed before dispatch")
    _check(checkpoint_guard, detached, "detached checkpoint changed before dispatch")
    _implementation()
    return span.train_decoder(detached, train_rows, tune_rows, max_steps=max_steps, max_seconds=max_seconds)


__all__ = ["SourceSpanBoundBatch", "SourceSpanConsumerBindingError",
           "build_bound_checkpoint", "train_bound_decoder"]
