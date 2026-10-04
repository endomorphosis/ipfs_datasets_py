"""Exact request-index recovery of compatible native CodebaseIR dispatch.

Request references are reconstructed from verified committed model history.
The existing transport/model verifier still owns receipt validation. Neither
lookup nor historical load submits work, fits, observes live source, or publishes.
"""
from __future__ import annotations

import hashlib
import importlib

from . import codebase_dispatched_federation as owner
from . import codebase_federated_artifacts as artifacts_worker
from . import codebase_federated_training as federation
from . import codebase_source_training as source
from .cache import ImmutableCAS
from .content import cid_for_structured

_require, _wire = source._require, source._wire


def _history():
    return importlib.import_module("ipfs_accelerate_py.p2p_tasks.codebase_federated_history")


def _task_payload(local, parent_bytes, context_bytes, limits):
    """Derive the original immutable request without writing any artifact."""
    sync = federation._sync()
    work = sync.CodebaseFederatedWorkBinding.from_dict(local["work_binding"])
    snapshots = (_wire(work.to_dict()["round"]), parent_bytes, _wire(local["local_payload"]))
    _require(all(len(raw) <= limits.max_candidate_bytes for raw in snapshots)
             and len(context_bytes) <= limits.max_target_bytes
             and sum(map(len, snapshots)) + len(context_bytes) <= 2 * limits.max_candidate_bytes,
             "reconstructed transfer request exceeds admitted byte bounds")
    round_ref, parent_ref, local_ref = [sync.CodebaseArtifactReference.from_dict(
        artifacts_worker._reference(raw)) for raw in snapshots]
    declaration = sync.make_codebase_federated_task(work, round_artifact=round_ref,
        base_artifact=parent_ref, local_payload_artifact=local_ref)
    return {"schema": artifacts_worker.REQUEST_SCHEMA, "declaration": declaration,
        "context_artifact": artifacts_worker._reference(context_bytes),
        "implementation": artifacts_worker.codebase_artifact_implementation()}


def _checked_child(index, registry, version_id, limits):
    child = federation._parent(index, registry, version_id, limits)
    _require(len(child["saved"]["feature_space"]["columns"]) <= limits.max_features,
             "retained feature count exceeds admitted feature bound")
    _require(len(child["history"]) <= limits.max_training_history,
             "retained training history exceeds admitted history bound")
    return child


def _exact_rows(index, registry, version_id, queue, limits):
    child = _checked_child(index, registry, version_id, limits)
    row, saved = child["row"], child["saved"]
    _require(type(row["metadata"].get("producer_run")) is str
             and row["metadata"]["producer_run"].startswith("codebase-dispatched-fed:"),
             "exact recovery requires a dispatched source model")
    report = saved["report"]["codebase_federation"]
    # Full child replay above has already checked the parent ancestry and fixed
    # evaluation context. Re-read exact parent bytes without replaying it again.
    parent_row, parent_saved = source._read_candidate(registry, row["parent_version_id"], limits)
    with registry.artifact_path(parent_row["artifact"]).open("rb") as stream:
        parent_bytes = stream.read(limits.max_candidate_bytes + 1)
    _require(len(parent_bytes) <= limits.max_candidate_bytes
             and parent_bytes == _wire(parent_saved)
             and hashlib.sha256(parent_bytes).hexdigest() == parent_row["artifact"]["sha256"],
             "exact parent artifact changed during request reconstruction")
    context_bytes = _wire({"tuning_targets": [item.to_dict() for item in child["tune"]],
        "canary_targets": [item.to_dict() for item in child["canary"]],
        "replay_targets": [item.to_dict() for item in child["replay"]]})
    rows = []
    for local in report["clients"]:
        payload = _task_payload(local, parent_bytes, context_bytes, limits)
        request = owner._transport().codebase_dispatch_request_sha256(payload, report["round"]["model_id"])
        task = _history().find_codebase_federated_task(queue, request_sha256=request,
            payload=payload, model_name=report["round"]["model_id"])
        _require(task is not None, "retained exact source client task absent from native request index")
        rows.append(task)
    return rows


def _owners(index, registry, dispatcher, queue, artifacts, limits, use_request_index):
    source._native_owners(index, registry)
    _require(type(use_request_index) is bool, "explicit request-index policy required")
    limits, queue = owner._limits(limits), owner._queue(dispatcher, queue)
    if artifacts is None:
        artifacts = getattr(getattr(dispatcher, "handler", None), "artifacts", index.artifacts)
    _require(type(artifacts) is ImmutableCAS, "native retained transfer artifact store required")
    return queue, artifacts, limits


def load_indexed_dispatched_codebase_round(index, registry, version_id, *, dispatcher=None,
        queue=None, artifacts=None, artifact_cid=None, limits=None, use_request_index=True):
    """Load exact retained history with indexed discovery on by default.

    A supplied sidecar CID addresses exact task IDs directly. Opting out restores
    the prior bounded queue scan. Full model/artifact verification always runs.
    """
    queue, artifacts, limits = _owners(index, registry, dispatcher, queue, artifacts, limits, use_request_index)
    if artifact_cid is not None or not use_request_index:
        _checked_child(index, registry, version_id, limits)
        return owner.load_dispatched_codebase_round(index, registry, version_id, queue=queue,
            artifacts=artifacts, artifact_cid=artifact_cid, limits=limits)
    rows = _exact_rows(index, registry, version_id, queue, limits)
    record, model_record, snapshots = owner._derive(index, registry, version_id,
        queue=queue, artifacts=artifacts, limits=limits, rows=rows)
    _require(index.artifacts.get(record.artifact_cid, expected_schema=owner.SCHEMA) == record.to_dict()
             and index.artifacts.get(model_record.artifact_cid) == model_record.to_dict(),
             "published indexed dispatch/model provenance differs")
    for value in snapshots:
        _require(index.artifacts.get(cid_for_structured(value)) == value, "published indexed dispatch snapshot differs")
    return record


def recover_indexed_dispatched_codebase_round(index, registry, version_id, *, dispatcher=None,
        queue=None, artifacts=None, limits=None, use_request_index=True):
    """Explicit provenance publication after exact durable completion; no fit."""
    queue, artifacts, limits = _owners(index, registry, dispatcher, queue, artifacts, limits, use_request_index)
    if not use_request_index:
        _checked_child(index, registry, version_id, limits)
        return owner.recover_dispatched_codebase_round(index, registry, version_id,
            queue=queue, artifacts=artifacts, limits=limits)
    rows = _exact_rows(index, registry, version_id, queue, limits)
    record, model_record, snapshots = owner._derive(index, registry, version_id,
        queue=queue, artifacts=artifacts, limits=limits, rows=rows)
    owner._publish(index, record, model_record, snapshots)
    return record


__all__ = ["load_indexed_dispatched_codebase_round", "recover_indexed_dispatched_codebase_round"]
