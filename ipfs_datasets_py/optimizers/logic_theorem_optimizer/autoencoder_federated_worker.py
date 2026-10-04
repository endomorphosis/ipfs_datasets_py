"""Private local Legal training for an owner's exact-base federated round.

This worker reads one owner-pinned local dataset snapshot, constructs the
selected Legal lineage from verified base parameters, and returns a parameter
delta candidate. It opens no database or network service, attaches no formula
head, and grants no evaluation, publication, or promotion authority.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import math
from pathlib import Path
import time
from typing import Any

from .autoencoder_federated import ClientUpdate, FederatedRound


CLIENT_DATA_SCHEMA = "legal-federated-client-data/v1"
WORKER_REPORT_SCHEMA = "legal-federated-local-worker/v1"
MAX_CLIENT_DATA_BYTES = 64 * 1024 * 1024
MAX_SPLIT_ROWS = 4096
MAX_SAMPLE_TEXT_BYTES = 65536
_RUNTIMES = frozenset(("legacy_v1", "legacy_v1_optimized", "current_v2"))
_REQUIRED_ROW_FIELDS = frozenset((
    "title", "section", "text", "embedding_model", "embedding_vector",
))
_METRIC_FIELDS = (
    "embedding_cosine_similarity", "cosine_loss", "reconstruction_loss",
    "cross_entropy_loss", "cross_entropy_excess_loss", "frame_ranking_loss",
    "symbolic_validity_penalty",
)


class FederatedWorkerError(ValueError):
    """Local training cannot satisfy its pinned data or numerical contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise FederatedWorkerError(message)


def _text(value: Any, label: str, maximum: int = 4096) -> None:
    _require(type(value) is str and bool(value.strip())
             and len(value.encode("utf-8")) <= maximum,
             label + " must be bounded nonempty text")


def _positive_number(value: Any, label: str, maximum: float) -> None:
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and 0 < value <= maximum
    except OverflowError:
        valid = False
    _require(valid, label + " is outside its finite positive bound")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, "duplicate local-data JSON field")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise FederatedWorkerError("nonfinite local-data JSON constant: " + value)


def _load_data(path: str | Path, expected_sha256: str) -> tuple[dict[str, Any], str]:
    # Read once, including a sentinel byte for the bound. Hashing, parsing and
    # sample construction use these owned bytes even if the path later changes.
    with Path(path).open("rb") as source:
        raw = source.read(MAX_CLIENT_DATA_BYTES + 1)
    _require(0 < len(raw) <= MAX_CLIENT_DATA_BYTES, "local dataset exceeds its byte bound")
    digest = hashlib.sha256(raw).hexdigest()
    _require(digest == expected_sha256, "local dataset SHA-256 differs from the approved client")
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise FederatedWorkerError("invalid local-data JSON") from error
    _require(type(payload) is dict and set(payload) == {
        "schema", "embedding_producer_sha256", "training", "validation",
    }, "local-data envelope requires its exact closed fields")
    _require(payload["schema"] == CLIENT_DATA_SCHEMA, "unsupported local-data schema")
    return payload, digest


def _samples(rows: Any, *, namespace: Any, dimension: int, label: str) -> list[Any]:
    _require(type(rows) is list and 1 <= len(rows) <= MAX_SPLIT_ROWS,
             label + " requires a bounded nonempty array")
    samples = []
    for row in rows:
        _require(type(row) is dict and _REQUIRED_ROW_FIELDS <= set(row)
                 and set(row) <= _REQUIRED_ROW_FIELDS | {"citation"},
                 label + " row has missing or unknown fields")
        for field in ("title", "section", "embedding_model"):
            _text(row[field], field)
        _text(row["text"], "text", MAX_SAMPLE_TEXT_BYTES)
        if "citation" in row:
            _text(row["citation"], "citation")
        vector = row["embedding_vector"]
        _require(type(vector) is list and len(vector) == dimension,
                 "embedding vector differs from the round dimension")
        for value in vector:
            try:
                valid = type(value) in (int, float) and math.isfinite(value)
            except OverflowError:
                valid = False
            _require(valid, "embedding values must be finite builtin numbers, excluding bool")
        # The facade requires explicit vectors and provenance; it cannot use
        # the original sample factory's optional mock-embedding default.
        samples.append(namespace.build_sample(**row))
    return samples


def _metrics(value: Any, expected_count: int) -> dict[str, float]:
    _require(type(value) is dict and value.get("sample_count") == expected_count,
             "training evaluation sample coverage differs")
    result = {}
    for name in _METRIC_FIELDS:
        number = value.get(name)
        try:
            valid = type(number) in (int, float) and math.isfinite(number)
        except OverflowError:
            valid = False
        _require(valid, "training returned nonfinite or missing metric: " + name)
        result[name] = float(number)
    return result


def train_modal_client(
    adapter: Any, round_spec: FederatedRound, client_id: str,
    local_data_path: str | Path, *, epochs: int = 1, learning_rate: float = .01,
    max_seconds: float = 60, max_line_search_attempts: int = 1,
    compute_device: str = "cpu",
) -> tuple[ClientUpdate, dict[str, Any]]:
    """Run genuine local feature training and snapshot a fixed-layout update.

    ``local_steps`` in the resulting update counts attempted projection epochs;
    the report separately records accepted epochs. Tuning data selects local
    updates and supplies no independent aggregate qualification. The existing
    trainers' time budget cannot preempt an in-flight Python operation.
    """
    from .autoencoder_federated_modal import ModalCheckpoint

    _require(type(adapter) is ModalCheckpoint, "an exact verified ModalCheckpoint adapter is required")
    round_spec = adapter.validate_round(round_spec)
    _text(client_id, "client_id", 128)
    client = next((value for value in round_spec.clients if value.client_id == client_id), None)
    _require(client is not None, "client is not approved for this round")
    _require(type(epochs) is int and 1 <= epochs <= min(64, round_spec.max_local_steps),
             "epochs exceeds the round's local-step bound")
    _positive_number(learning_rate, "learning_rate", 1)
    _positive_number(max_seconds, "max_seconds", 600)
    _require(type(max_line_search_attempts) is int and 1 <= max_line_search_attempts <= 8,
             "max_line_search_attempts must be in 1..8")
    _require(type(compute_device) is str and compute_device in {"cpu", "python"},
             "this local worker currently requires explicit cpu or python execution")
    _require(adapter.runtime_version in _RUNTIMES, "unsupported Legal training lineage")
    payload, data_sha256 = _load_data(local_data_path, client.local_data_sha256)
    _require(payload["embedding_producer_sha256"] == round_spec.embedding_producer_sha256,
             "local embedding producer differs from the round")
    namespace = importlib.import_module(
        __package__ + ".autoencoder_lineages." + adapter.runtime_version,
    )
    training = _samples(payload["training"], namespace=namespace,
                        dimension=round_spec.dimension, label="training")
    tuning = _samples(payload["validation"], namespace=namespace,
                      dimension=round_spec.dimension, label="validation")
    _require(len(training) == client.sample_count, "training count differs from the approved client count")
    all_samples = training + tuning
    _require(len({row.sample_id for row in all_samples}) == len(all_samples),
             "training and tuning sample identities must be unique and disjoint")
    normalized = {" ".join(row.normalized_text.lower().split()) for row in all_samples}
    _require(len(normalized) == len(all_samples),
             "training and tuning normalized sources must be unique and disjoint")
    model = adapter.fresh_model(compute_device=compute_device)
    _require(model._joint_formula_checkpoint is None and model._joint_formula_decoder is None,
             "local feature training must not attach a formula head")
    # Validate the installed private numerical basis before invoking the trainer.
    adapter.extract_parameters(model.state)
    current = adapter.runtime_version == "current_v2"
    objective = "raw_decoder" if current else "historical_safety_projected"
    options = {
        "validation_samples": tuning,
        "epochs": epochs, "learning_rate": learning_rate,
        "max_seconds": max_seconds, "max_line_search_attempts": max_line_search_attempts,
        "l2_regularization": 0.0, "legal_ir_bridge_names": (),
        "legal_ir_evaluate_provers": False, "legal_ir_parallel_workers": 1,
        "projection_update_backend": "python_sparse_batch",
    }
    if current:
        options.update(projection_optimizer_mode="fixed", projection_momentum=0.0,
                       projection_reconstruction_objective="raw_decoder")
    started = time.monotonic()
    result = model.train_generalizable_projection(training, **options)
    elapsed = time.monotonic() - started
    _require(type(result) is dict and result.get("sample_memory_used") is False,
             "trainer must report sample-memory-free updates")
    _require(model._joint_formula_checkpoint is None and model._joint_formula_decoder is None,
             "feature training must not attach a formula head")
    attempts = result.get("epoch_reports")
    _require(type(attempts) is list and 1 <= len(attempts) <= epochs,
             "trainer did not attempt a bounded projection epoch")
    accepted = result.get("accepted_epochs")
    _require(type(accepted) is int and 0 <= accepted <= len(attempts),
             "trainer returned an invalid accepted-epoch count")
    before = _metrics(result.get("before"), len(tuning))
    after = _metrics(result.get("after"), len(tuning))
    _require(result.get("validation_sample_count") == len(tuning),
             "trainer tuning count differs from the local dataset")
    # The adapter checks all state fields, including excluded metadata, and
    # rejects new/deleted keys, shape changes, and architecture/schema drift.
    # A worker may not extract an allowed subset and silently discard changes.
    update = adapter.make_update_from_state(
        round_spec, client_id, model.state, local_steps=len(attempts),
        local_data_sha256=data_sha256,
    )
    report = {
        "schema": WORKER_REPORT_SCHEMA, "client_id": client_id,
        "training_scope": "reusable_modal_feature_heads", "formula_training_executed": False,
        "runtime_version": adapter.runtime_version, "dimension": round_spec.dimension,
        "round_sha256": round_spec.round_sha256, "base_sha256": round_spec.base_sha256,
        "layout_sha256": round_spec.layout_sha256,
        "embedding_producer_sha256": round_spec.embedding_producer_sha256,
        "local_data_sha256": data_sha256, "training_sample_count": len(training),
        "tuning_sample_count": len(tuning), "requested_epochs": epochs,
        "attempted_epochs": len(attempts), "accepted_epochs": accepted,
        "local_steps_policy": "attempted_projection_epochs",
        "reconstruction_objective": objective, "optimizer_mode": "fixed",
        "optimizer_reset": True, "optimizer_state_aggregated": False,
        "compute_device": compute_device, "elapsed_training_seconds": elapsed,
        "learning_rate": float(learning_rate), "requested_max_seconds": float(max_seconds),
        "max_line_search_attempts": max_line_search_attempts,
        "tuning_metrics_before": before, "tuning_metrics_after": after,
        "sample_memory_used": False, "tuning_used_for_selection": True,
        "independent_validation": False, "qualified": False,
        "admitted": False, "promotion_performed": False, "publication_performed": False,
    }
    return update, report


__all__ = [
    "CLIENT_DATA_SCHEMA", "WORKER_REPORT_SCHEMA", "FederatedWorkerError",
    "train_modal_client",
]
