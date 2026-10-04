"""Portable, bounded CodebaseIR client fitting on verified inert artifacts.

The worker opens neither a model registry nor a source index. A durable private
receipt recovers an exact request after queue delivery/response loss. Queue and
round liveness remain the dispatcher's and source owner's responsibilities.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time

from . import codebase_federated_training as federation
from . import codebase_source_training as source
from .cache import ImmutableCAS
from .codebase_resources import acquire_codebase_resources
from .content import cid_for_bytes
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import codebase_federated_sync as sync
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_federated_update_codec import write_client_update, read_client_update

TASK_TYPE = "codebase_ir.federated_artifact_update@1"
REQUEST_SCHEMA = "codebase-federated-artifact-request@1"
RESULT_SCHEMA = "codebase-federated-artifact-result@1"
_FALSE = {**source._FALSE, "network_authority": False}
_require, _wire = source._require, source._wire


def codebase_artifact_implementation():
    return {"artifact_worker_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "compatible_model_producer": federation._pins(),
            "scope": "listed_local_files_only_not_execution_attestation"}


def _reference(raw):
    return sync.CodebaseArtifactReference(hashlib.sha256(raw).hexdigest(), cid_for_bytes(raw), len(raw)).to_dict()


def _put(artifacts, raw):
    _require(type(artifacts) is ImmutableCAS and type(raw) is bytes, "native artifact store and exact bytes required")
    reference = _reference(raw)
    _require(artifacts.put_bytes(raw) == reference["cidv1"], "artifact store returned another raw identity")
    return reference


def read_codebase_artifact(artifacts, reference, *, maximum=16 * 1024 * 1024):
    _require(type(artifacts) is ImmutableCAS, "native worker artifact store required")
    reference = sync.CodebaseArtifactReference.from_dict(reference).to_dict()
    _require(type(maximum) is int and 0 < reference["bytes"] <= maximum, "artifact exceeds admitted byte bound")
    raw = artifacts.get_bytes(reference["cidv1"])
    _require(len(raw) == reference["bytes"] and hashlib.sha256(raw).hexdigest() == reference["sha256"],
             "owned artifact bytes differ from their reference")
    return raw


def _json(raw):
    value = json.loads(raw)
    _require(_wire(value) == raw, "canonical inert artifact JSON required")
    return value


def codebase_artifact_request_sha256(payload, model_name):
    return hashlib.sha256(_wire({"task_type": TASK_TYPE, "model_name": model_name, "payload": payload})).hexdigest()


def prepare_codebase_artifact_task(work, *, base_bytes, local_payload, context, artifacts):
    """Publish approved bytes to the private transfer store; activate no queue."""
    _require(type(work) is sync.CodebaseFederatedWorkBinding, "native approved work binding required")
    round_bytes = _wire(work.to_dict()["round"])
    local_bytes = _wire(local_payload)
    declaration = sync.make_codebase_federated_task(work,
        round_artifact=sync.CodebaseArtifactReference.from_dict(_put(artifacts, round_bytes)),
        base_artifact=sync.CodebaseArtifactReference.from_dict(_put(artifacts, base_bytes)),
        local_payload_artifact=sync.CodebaseArtifactReference.from_dict(_put(artifacts, local_bytes)))
    payload = {"schema": REQUEST_SCHEMA, "declaration": declaration,
               "context_artifact": _put(artifacts, _wire(context)), "implementation": codebase_artifact_implementation()}
    _load_inputs(payload, artifacts, source.CodebaseFeatureTrainingLimits())
    return payload


def _load_inputs(payload, artifacts, limits):
    _require(type(payload) is dict and set(payload) == {"schema", "declaration", "context_artifact", "implementation"}
             and payload["schema"] == REQUEST_SCHEMA and payload["implementation"] == codebase_artifact_implementation(),
             "closed compatible artifact request required")
    declaration = payload["declaration"]
    data = declaration["payload"]
    work = sync.CodebaseFederatedWorkBinding.from_dict(data["work_binding"], expected_sha256=data["work_sha256"])
    refs = data["artifacts"]
    _require(type(refs) is dict and set(refs) == {"round", "base_checkpoint", "local_payload"}, "closed transfer artifacts required")
    expected = sync.make_codebase_federated_task(work,
        round_artifact=sync.CodebaseArtifactReference.from_dict(refs["round"]),
        base_artifact=sync.CodebaseArtifactReference.from_dict(refs["base_checkpoint"]),
        local_payload_artifact=sync.CodebaseArtifactReference.from_dict(refs["local_payload"]))
    _require(declaration == expected, "task declaration route/scope/authority differs")
    snapshots = {key: read_codebase_artifact(artifacts, ref, maximum=limits.max_candidate_bytes) for key, ref in refs.items()}
    context_bytes = read_codebase_artifact(artifacts, payload["context_artifact"], maximum=limits.max_target_bytes)
    _require(sum(map(len, snapshots.values())) + len(context_bytes) <= 2 * limits.max_candidate_bytes,
             "combined transfer snapshots exceed admitted bound")
    round_spec = federation._round(_json(snapshots["round"]))
    work.validate_round(round_spec)
    base = _json(snapshots["base_checkpoint"])
    _require(type(base) is dict and set(base) == {"contract", "feature_space", "state", "report"},
             "complete native base checkpoint required")
    runtime = federation._runtime(base)
    adapter = federation._adapter().CodebaseFeatureCheckpoint.from_runtime(runtime,
        base_sha256=refs["base_checkpoint"]["sha256"], base_version_id=work.to_dict()["base_version_id"])
    adapter.validate_round(round_spec)
    local = _json(snapshots["local_payload"])
    _require(type(local) is dict and set(local) == {"schema", "client_id", "head", "selections", "training_targets",
            "sample_count", "tuning_targets_sha256", "configuration", "implementation"}
        and local["schema"] == federation.LOCAL_SCHEMA and local["implementation"] == federation._pins(),
        "closed native captured client payload required")
    claimed = work.to_dict()
    _require(local["client_id"] == claimed["client_id"] and local["head"] == claimed["source_head"]
             and features.digest(local) == claimed["local_target_sha256"]
             and type(local["sample_count"]) is int and local["sample_count"] == claimed["sample_count"],
             "local source/client/count commitment differs")
    head = CodebaseHead.from_dict(local["head"])
    selections = [source.CodebaseTrainingSelection.from_dict(item) for item in local["selections"]]
    train = source._batch(local["training_targets"], limits)
    _require(len(train) == len(selections) == local["sample_count"]
             and len({item.path for item in selections}) == len(selections)
             and all(item.role == "train" for item in selections), "local count/source selection inventory differs")
    for selection, target in zip(selections, train):
        binding = source._binding(target)
        _require(target.ready_for_training and binding["head"] == head.to_dict() and binding["path"] == selection.path
                 and binding["authored_contracts"] == [item.to_dict() for item in selection.contracts],
                 "training envelope source/contract differs from admitted selection")
    context = _json(context_bytes)
    _require(type(context) is dict and set(context) == {"tuning_targets", "canary_targets", "replay_targets"},
             "closed fixed inherited context required")
    tune, canary, replay = [source._batch(context[role], limits) for role in ("tuning_targets", "canary_targets", "replay_targets")]
    _require(features.digest([item.to_dict() for item in tune]) == local["tuning_targets_sha256"]
             == adapter.state["tuning_targets_sha256"], "fixed tuning targets differ from exact base")
    source._split_check(train, tune, canary, [])
    configuration = federation._configuration(**local["configuration"])
    _require(configuration == local["configuration"] and configuration["epochs"] == round_spec.max_local_steps
             and configuration["learning_rate"] == adapter.state["optimizer_config"]["learning_rate"],
             "local configuration differs from exact parent/round")
    return work, round_spec, base, adapter, local, train, tune, canary, replay, context


def validate_codebase_artifact_result(payload, result, artifacts, *, limits=None):
    """Replay owned snapshots and binary delta; performs no fitting or writes."""
    limits = source.CodebaseFeatureTrainingLimits() if limits is None else limits
    _require(type(limits) is source.CodebaseFeatureTrainingLimits, "native artifact bounds required")
    work, round_spec, base, adapter, local, *_ = _load_inputs(payload, artifacts, limits)
    fields = {"schema", "request_sha256", "work_sha256", "local_checkpoint", "update", "implementation", "authority"}
    _require(type(result) is dict and set(result) == fields and result["schema"] == RESULT_SCHEMA
             and result["implementation"] == codebase_artifact_implementation()
             and result["authority"] == _FALSE and all(flag is False for flag in result["authority"].values())
             and result["work_sha256"] == work.sha256
             and result["request_sha256"] == codebase_artifact_request_sha256(payload, work.to_dict()["model_id"]),
             "worker result request/authority differs")
    checkpoint = _json(read_codebase_artifact(artifacts, result["local_checkpoint"], maximum=limits.max_candidate_bytes))
    _require(type(checkpoint) is dict and set(checkpoint) == {"contract", "feature_space", "state", "report", "worker_receipt"}
             and checkpoint["contract"] == base["contract"] and checkpoint["feature_space"] == base["feature_space"],
             "local checkpoint contract/basis differs")
    item = {"local_payload": local, "local_state": checkpoint["state"], "training_report": checkpoint["report"],
            "worker_receipt": checkpoint["worker_receipt"], "work_binding": work.to_dict()}
    steps = federation._local_report(item, local, adapter, {"saved": base}, limits)
    derived = adapter.build_update(round_spec, local["client_id"], checkpoint["state"], local_steps=steps)
    raw = read_codebase_artifact(artifacts, result["update"], maximum=limits.max_candidate_bytes)
    _require(hashlib.sha256(raw).hexdigest() == derived.update_sha256, "binary delta differs from local state/parent")
    # Codec readers check every coordinate/layout and the full byte commitment.
    with tempfile.TemporaryDirectory(prefix="codebase-update-replay-") as workspace:
        path = Path(workspace) / "update.bin"
        path.write_bytes(raw)
        actual = read_client_update(path, round_spec, expected_sha256=result["update"]["sha256"],
            expected_cidv1=result["update"]["cidv1"], max_bytes=limits.max_candidate_bytes)
    _require(actual.update_sha256 == derived.update_sha256, "stored binary update differs")
    return {**item, "update_artifact": result["update"], "update_cid": result["update"]["cidv1"]}


class CodebaseFederatedArtifactWorker:
    """Explicit hook callable with private durable exact-request receipts."""
    def __init__(self, artifacts, receipt_root, *, scheduler=None, memory_mb=1024, timeout_seconds=120, limits=None):
        _require(type(artifacts) is ImmutableCAS, "native worker artifact store required")
        _require(type(memory_mb) is int and memory_mb >= 512 and type(timeout_seconds) in {int, float}
                 and math.isfinite(timeout_seconds) and 0 < timeout_seconds <= 600, "bounded worker resources required")
        self.artifacts = artifacts
        self.receipt_root = Path(receipt_root).resolve()
        self.receipt_root.mkdir(parents=True, exist_ok=True)
        self.scheduler, self.memory_mb, self.timeout_seconds = scheduler, memory_mb, timeout_seconds
        self.limits = source.CodebaseFeatureTrainingLimits() if limits is None else limits
        _require(type(self.limits) is source.CodebaseFeatureTrainingLimits, "native worker limits required")
        self._context = ContextVar("codebase-artifact-worker-context", default=None)
        self.numerical_invocations = 0

    @contextmanager
    def execution_context(self, *, parent_lease, cancel_event, remaining, memory_mb, limits):
        _require(callable(remaining) and callable(getattr(cancel_event, "is_set", None))
                 and type(memory_mb) is int and memory_mb >= 512
                 and type(limits) is source.CodebaseFeatureTrainingLimits,
                 "trusted owner execution context required")
        token = self._context.set((parent_lease, cancel_event, remaining, memory_mb, limits))
        try:
            yield self
        finally:
            self._context.reset(token)

    @contextmanager
    def _resources(self, dispatch):
        deadline = min(time.time() + self.timeout_seconds, dispatch["deadline_unix_s"])
        inherited = self._context.get()
        signal = threading.Event() if inherited is None else inherited[1]
        memory_mb, limits = (self.memory_mb, self.limits) if inherited is None else inherited[3:]
        def remaining():
            from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import LeaseCancelledError, LeaseTimeoutError
            if signal.is_set():
                raise LeaseCancelledError("artifact worker cancelled")
            seconds = deadline - time.time()
            if inherited is not None:
                seconds = min(seconds, inherited[2]())
            if seconds <= 0:
                raise LeaseTimeoutError("artifact task deadline exceeded")
            return seconds
        remaining()
        if inherited is not None:
            yield inherited[0], signal, remaining, memory_mb, limits
            remaining()
        else:
            with acquire_codebase_resources(scheduler=self.scheduler, cancel_event=signal,
                    memory_mb=memory_mb, timeout_seconds=remaining()) as lease:
                combined = lease.combined_cancellation_signal(signal)
                signal = combined
                yield lease, combined, remaining, memory_mb, limits
                remaining()

    def __call__(self, task):
        _require(type(task) is dict and task.get("task_type") == TASK_TYPE, "registered artifact task type required")
        payload, model = task["payload"], task["model_name"]
        request = codebase_artifact_request_sha256(payload, model)
        dispatch = task.get("dispatch")
        _require(type(dispatch) is dict and set(dispatch) == {"queue_task_id", "queue_attempt", "worker_id",
                    "request_sha256", "deadline_unix_s"}
                 and all(type(dispatch[key]) is str and 0 < len(dispatch[key]) <= 512
                         for key in ("queue_task_id", "worker_id"))
                 and dispatch.get("request_sha256") == request
                 and type(dispatch.get("queue_attempt")) is int and dispatch["queue_attempt"] > 0
                 and type(dispatch.get("deadline_unix_s")) in {float, int}
                 and math.isfinite(dispatch["deadline_unix_s"]) and dispatch["deadline_unix_s"] > time.time(),
                 "live typed queue dispatch context required")
        lock_path, receipt_path = self.receipt_root / (request + ".lock"), self.receipt_root / (request + ".json")
        with lock_path.open("a+b") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise source.CodebaseFeatureTrainingError("artifact request already executing") from error
            try:
                limits = self.limits if self._context.get() is None else self._context.get()[4]
                work, round_spec, base, adapter, local, train, tune, canary, replay, _ = _load_inputs(payload, self.artifacts, limits)
                _require(model == work.to_dict()["model_id"], "queue model differs from artifact model")
                if receipt_path.exists():
                    inherited = self._context.get()
                    if inherited is not None:
                        inherited[2]()
                        _require(not inherited[1].is_set(), "artifact receipt replay cancelled")
                    with receipt_path.open("rb") as stored:
                        raw = stored.read(1024 * 1024 + 1)
                    _require(len(raw) <= 1024 * 1024, "private result receipt exceeds bound")
                    result = _json(raw)
                    validate_codebase_artifact_result(payload, result, self.artifacts, limits=limits)
                    _require(dispatch["deadline_unix_s"] > time.time(), "artifact receipt replay deadline exceeded")
                    if inherited is not None:
                        inherited[2]()
                        _require(not inherited[1].is_set(), "artifact receipt replay cancelled")
                    return result
                with self._resources(dispatch) as (lease, signal, remaining, memory_mb, bounds):
                    self.numerical_invocations += 1
                    output, receipt = source._worker(federation._runtime(base), train, tune, canary, replay,
                        action="train", **local["configuration"], remaining=remaining, memory_mb=memory_mb,
                        limits=bounds, signal=signal, lease=lease)
                    remaining()
                    state, report = output["result"]["state"], output["result"]["report"]
                    item = {"local_state": state, "training_report": report, "worker_receipt": receipt}
                    steps = federation._local_report(item, local, adapter, {"saved": base}, bounds)
                    update = adapter.build_update(round_spec, local["client_id"], state, local_steps=steps)
                    checkpoint = {"contract": base["contract"], "feature_space": base["feature_space"],
                                  "state": state, "report": report, "worker_receipt": receipt}
                    with tempfile.TemporaryDirectory(prefix="codebase-artifact-output-") as workspace:
                        path = Path(workspace) / "update.bin"
                        write_client_update(path, round_spec, update, max_bytes=bounds.max_candidate_bytes)
                        update_ref = _put(self.artifacts, path.read_bytes())
                    result = {"schema": RESULT_SCHEMA, "request_sha256": request, "work_sha256": work.sha256,
                        "local_checkpoint": _put(self.artifacts, _wire(checkpoint)), "update": update_ref,
                        "implementation": codebase_artifact_implementation(), "authority": dict(_FALSE)}
                    validate_codebase_artifact_result(payload, result, self.artifacts, limits=bounds)
                    remaining()
                    raw = _wire(result)
                    with tempfile.NamedTemporaryFile(prefix="receipt-", dir=self.receipt_root, delete=False) as temporary:
                        temporary.write(raw)
                        temporary.flush()
                        os.fsync(temporary.fileno())
                        temporary_path = Path(temporary.name)
                    try:
                        os.link(temporary_path, receipt_path)
                        descriptor = os.open(self.receipt_root, os.O_RDONLY)
                        try:
                            os.fsync(descriptor)
                        finally:
                            os.close(descriptor)
                    finally:
                        temporary_path.unlink(missing_ok=True)
                    return result
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
