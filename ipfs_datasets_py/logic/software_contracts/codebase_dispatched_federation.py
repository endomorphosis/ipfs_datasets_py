"""Source-owned artifact dispatch for CodebaseIR federation.

The model checkpoint deliberately retains the existing federation schema and
native registry completion. Transport provenance is a separate immutable CAS
record, verified against the completed native task rows. Neither record grants
model admission, promotion, proof, or network authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import json
from pathlib import Path
import re
import tempfile
import uuid

from ipfs_datasets_py.duckdb_control.autoencoder_federated import create_federated_run, complete_federated_run
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_federated import ClientSpec, aggregate_round
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_federated_update_codec import read_client_update
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_sync import TrainingMode, GradientBackendUnavailable
from . import codebase_federated_training as federation
from . import codebase_source_training as source
from .content import canonical_dag_json_bytes, cid_for_structured

SCHEMA = "codebase-source-dispatched-federation@1"
TASK_TYPE = "codebase_ir.federated_artifact_update@1"
_FALSE = {**source._FALSE, "worker_dispatch_qualified": False, "network_authority": False}
_require, _wire = source._require, source._wire
_ROW_FIELDS = {"task_id", "task_type", "model_name", "payload", "status", "assigned_worker",
    "created_at", "updated_at", "result", "error", "priority", "attempt", "max_attempts",
    "next_attempt_at", "lease_until", "heartbeat_at", "idempotency_key"}


def _artifacts():
    return importlib.import_module("ipfs_datasets_py.logic.software_contracts.codebase_federated_artifacts")


def _transport():
    return importlib.import_module("ipfs_accelerate_py.p2p_tasks.codebase_federated_dispatch")


def _pins():
    names = (__name__, _artifacts().__name__, _transport().__name__)
    return {"files": {name: hashlib.sha256(Path(importlib.import_module(name).__file__).read_bytes()).hexdigest()
                      for name in names},
        "compatible_model_producer": federation._pins(),
        "scope": "listed_local_files_only_not_execution_attestation"}


@dataclass(frozen=True, slots=True)
class CodebaseDispatchedTrainingRecord:
    artifact_cid: str
    _payload: bytes
    observed_live: bool = False

    def __post_init__(self):
        _require(type(self._payload) is bytes and type(self.observed_live) is bool,
                 "immutable dispatched federation record required")
        value = json.loads(self._payload)
        _require(canonical_dag_json_bytes(value) == self._payload and cid_for_structured(value) == self.artifact_cid
                 and value["schema"] == SCHEMA and value["authority"] == _FALSE
                 and all(flag is False for flag in value["authority"].values()),
                 "dispatched record identity/authority differs")

    def to_dict(self):
        return json.loads(self._payload)


def _limits(value):
    result = source.CodebaseFeatureTrainingLimits() if value is None else value
    _require(type(result) is source.CodebaseFeatureTrainingLimits, "native federation bounds required")
    return result


def _queue(dispatcher, queue):
    result = queue if queue is not None else getattr(dispatcher, "queue", None)
    _require(isinstance(result, _transport().TaskQueue) and not result._quack,
             "native local task queue history required")
    return result


def _snapshot(kind, value):
    # The reviewed DAG-JSON profile excludes floats. Queue timestamps and the
    # native numerical round remain exact in their canonical inert JSON text.
    return {"schema": "codebase-dispatched-" + kind + "-snapshot@1", "canonical_json": _wire(value).decode("ascii")}


def _completed_row(row, round_spec, expected_work):
    _require(type(row) is dict and set(row) == _ROW_FIELDS and row["status"] == "completed"
             and row["task_type"] == TASK_TYPE and row["model_name"] == round_spec.model_id
             and type(row["attempt"]) is int and row["attempt"] >= 1
             and type(row["assigned_worker"]) is str and row["assigned_worker"]
             and row["error"] is None and type(row["result"]) is dict,
             "closed successful native queue history required")
    payload = row["payload"]
    _require(type(payload) is dict, "persisted artifact task required")
    try:
        declared = payload["declaration"]["payload"]["work_binding"]
    except (KeyError, TypeError) as exc:
        raise source.CodebaseFeatureTrainingError("persisted source work declaration absent") from exc
    _require(declared == expected_work, "persisted queue source/native attempt binding differs")
    request = _transport().codebase_dispatch_request_sha256(payload, round_spec.model_id)
    _require(row["idempotency_key"] == request, "persisted queue request identity differs")
    return request


def _matching_rows(queue, report):
    """Bounded restart discovery; exact loads can instead supply a sidecar CID."""
    round_spec = federation._round(report["round"])
    expected = {item["work_binding"]["client_id"]: item["work_binding"] for item in report["clients"]}
    found = {}
    for row in queue.list(status="completed", task_types=[TASK_TYPE], limit=1000):
        try:
            work = row["payload"]["declaration"]["payload"]["work_binding"]
        except (KeyError, TypeError):
            continue
        if type(work) is not dict or work.get("round_sha256") != round_spec.round_sha256:
            continue
        client_id = work.get("client_id")
        if client_id not in expected or work != expected[client_id]:
            continue
        _require(client_id not in found, "duplicate persisted task for one source client")
        found[client_id] = row
    _require(set(found) == set(expected), "retained completed source client tasks absent within queue discovery bound")
    return [found[item["work_binding"]["client_id"]] for item in report["clients"]]


def _derive(index, registry, version_id, *, queue, artifacts, limits, rows=None):
    model_record = federation._record(index, registry, version_id, limits)
    row, saved = source._read_candidate(registry, version_id, limits)
    report = saved["report"]["codebase_federation"]
    round_spec = federation._round(report["round"])
    parent = federation._parent(index, registry, row["parent_version_id"], limits)
    context_bytes = _wire({"tuning_targets": [item.to_dict() for item in parent["tune"]],
        "canary_targets": [item.to_dict() for item in parent["canary"]],
        "replay_targets": [item.to_dict() for item in parent["replay"]]})
    completion = registry.get_run_completion(row["metadata"]["producer_run"])
    _require(completion is not None and completion["candidate_version"] == row,
             "native dispatched model completion differs")
    run = completion["run"]
    _require(run["run_id"].startswith("codebase-dispatched-fed:")
             and round_spec.round_id == run["run_id"], "model was not produced by dispatched source owner")
    rows = _matching_rows(queue, report) if rows is None else rows
    _require(type(rows) is list and len(rows) == len(report["clients"]), "exact completed queue cohort required")
    retained, clients, snapshots = 0, [], []
    for local, completed_row in zip(report["clients"], rows):
        request = _completed_row(completed_row, round_spec, local["work_binding"])
        current = queue.get(completed_row["task_id"])
        _require(current == completed_row, "persisted completed queue row differs")
        context = _artifacts().read_codebase_artifact(artifacts,
            completed_row["payload"]["context_artifact"], maximum=limits.max_target_bytes)
        _require(context == context_bytes, "dispatched fixed evaluation/replay context differs from inherited source lineage")
        verified = _artifacts().validate_codebase_artifact_result(completed_row["payload"],
            completed_row["result"], artifacts, limits=limits)
        _require(set(verified) == set(local), "artifact worker local record fields differ")
        for key in set(local) - {"update_artifact"}:
            _require(verified[key] == local[key], "artifact result differs from committed local " + key)
        artifact = verified["update_artifact"]
        registered = local["update_artifact"]
        _require(artifact["sha256"] == registered["sha256"] and artifact["bytes"] == registered["bytes"]
                 and artifact["cidv1"] == local["update_cid"], "artifact worker binary differs from native staged update")
        binary = _artifacts().read_codebase_artifact(artifacts, artifact, maximum=limits.max_candidate_bytes)
        registry.verify_artifact(registered)
        _require(registry.artifact_path(registered).read_bytes() == binary,
                 "retained artifact update differs from native update bytes")
        task, result = completed_row["payload"], completed_row["result"]
        task_snapshot = _snapshot("task", task)
        result_snapshot = _snapshot("result", result)
        row_snapshot = _snapshot("queue-row", completed_row)
        retained += len(_wire(task)) + len(_wire(result)) + len(_wire(completed_row))
        _require(retained <= limits.max_candidate_bytes, "retained dispatch evidence exceeds byte bound")
        clients.append({"client_id": local["work_binding"]["client_id"], "task_id": completed_row["task_id"],
            "request_sha256": request, "task_cid": cid_for_structured(task_snapshot), "task_sha256": features.digest(task),
            "result_cid": cid_for_structured(result_snapshot), "result_sha256": features.digest(result),
            "queue_row_cid": cid_for_structured(row_snapshot), "queue_row_sha256": features.digest(completed_row),
            "update_sha256": artifact["sha256"], "update_cid": artifact["cidv1"],
            "work_sha256": federation._sync().CodebaseFederatedWorkBinding.from_dict(local["work_binding"]).sha256})
        snapshots.extend((task_snapshot, result_snapshot, row_snapshot))
    value = {"schema": SCHEMA, "version_id": version_id, "variant_id": row["variant_id"],
        "parent_version_id": row["parent_version_id"], "origin_version_id": report["origin_version_id"],
        "model_record_cid": model_record.artifact_cid, "head": report["head"],
        "round_sha256": round_spec.round_sha256, "native_run_id": run["run_id"],
        "native_attempt": run["lease"]["attempt"], "native_fence": run["lease"]["fence"],
        "clients": clients, "implementation": _pins(), "authority": dict(_FALSE)}
    raw = canonical_dag_json_bytes(value)
    _require(len(raw) <= limits.max_candidate_bytes, "dispatch sidecar exceeds admitted byte bound")
    return CodebaseDispatchedTrainingRecord(cid_for_structured(value), raw), model_record, snapshots


def _publish(index, record, model_record, snapshots):
    _require(index.artifacts.put(model_record.to_dict()) == model_record.artifact_cid,
             "compatible model provenance publication differs")
    for value in snapshots:
        _require(index.artifacts.put(value) == cid_for_structured(value), "dispatch snapshot publication differs")
    _require(index.artifacts.put(record.to_dict()) == record.artifact_cid, "dispatch sidecar publication differs")


def load_dispatched_codebase_round(index, registry, version_id, *, dispatcher=None, queue=None,
                                 artifacts=None, artifact_cid=None, limits=None):
    """Read and replay source/model/task history, without dispatch or publication.

    Supplying the sidecar CID reads its exact task IDs. Otherwise discovery is
    bounded to the first 1000 retained completed tasks of this worker type.
    """
    limits, queue = _limits(limits), _queue(dispatcher, queue)
    artifacts = index.artifacts if artifacts is None else artifacts
    existing, rows = None, None
    if artifact_cid is not None:
        existing = index.artifacts.get(artifact_cid, expected_schema=SCHEMA)
        _require(existing["version_id"] == version_id, "sidecar belongs to another model version")
        rows = [queue.get(item["task_id"]) for item in existing["clients"]]
    record, model_record, snapshots = _derive(index, registry, version_id, queue=queue,
        artifacts=artifacts, limits=limits, rows=rows)
    _require(existing is None or existing == record.to_dict(), "dispatch sidecar differs from native history")
    _require(index.artifacts.get(record.artifact_cid, expected_schema=SCHEMA) == record.to_dict()
             and index.artifacts.get(model_record.artifact_cid) == model_record.to_dict(),
             "published dispatch/model provenance differs")
    for value in snapshots:
        _require(index.artifacts.get(cid_for_structured(value)) == value, "published dispatch snapshot differs")
    return record


def recover_dispatched_codebase_round(index, registry, version_id, *, dispatcher=None, queue=None,
                                     artifacts=None, limits=None):
    """Explicitly republish provenance after durable native completion; no fit."""
    limits, queue = _limits(limits), _queue(dispatcher, queue)
    artifacts = index.artifacts if artifacts is None else artifacts
    record, model_record, snapshots = _derive(index, registry, version_id, queue=queue,
        artifacts=artifacts, limits=limits)
    _publish(index, record, model_record, snapshots)
    return record


def train_current_dispatched_codebase_round(index, repository, *, expected_head, registry,
        base_version_id, clients, operation_id, dispatcher, worker=None, artifacts=None,
        epochs=1, learning_rate=.002, seed=1729, mode=TrainingMode.FEDERATED,
        limits=None, scheduler=None, parent_lease=None, cancel_event=None,
        admission_timeout_seconds=30.0, timeout_seconds=120.0, memory_mb=1024):
    """Dispatch each exact source client and durably register one FedAvg candidate."""
    _require(type(mode) is TrainingMode, "explicit native training mode required")
    if mode is not TrainingMode.FEDERATED:
        raise GradientBackendUnavailable("dispatched CodebaseIR executor implements federation only")
    source._native_owners(index, registry)
    source._text(operation_id, "operation_id", 128)
    _require(re.fullmatch(r"[A-Za-z0-9._:-]+", operation_id), "native operation token required")
    limits, queue = _limits(limits), _queue(dispatcher, None)
    _require(type(dispatcher) is _transport().CodebaseQueueDispatcher,
             "native CodebaseQueueDispatcher required")
    if artifacts is None:
        selected_worker = getattr(dispatcher, "handler", None) if worker is None else worker
        artifacts = getattr(selected_worker, "artifacts", index.artifacts)
    configuration = federation._configuration(epochs, learning_rate, seed)
    with source._resources(index, repository, expected_head, scheduler=scheduler, parent_lease=parent_lease,
            cancel_event=cancel_event, admission_timeout_seconds=admission_timeout_seconds,
            timeout_seconds=timeout_seconds, memory_mb=memory_mb, limits=limits) as (lease, signal, remaining, observe):
        base = federation._parent(index, registry, base_version_id, limits)
        _require(base["depth"] < limits.max_ancestry, "prospective federation ancestry depth exceeded")
        adapter = federation._adapter().CodebaseFeatureCheckpoint.from_runtime(federation._runtime(base["saved"]),
            base_sha256=base["row"]["artifact"]["sha256"], base_version_id=base_version_id)
        _require(adapter.state["optimizer_config"]["learning_rate"] == configuration["learning_rate"],
                 "private Adam resume requires the parent learning rate")
        selections = [source.CodebaseTrainingSelection.from_dict(item) for item in base["origin"]["selections"]]
        clients = federation._clients(clients, selections)
        pins = _pins()
        payloads, _ = federation._capture(index, expected_head, base, clients, configuration, limits)
        run_id = "codebase-dispatched-fed:" + operation_id
        round_spec = adapter.build_round(run_id, "codebase-source:" + base["origin_version_id"],
            tuple(ClientSpec(item["client_id"], item["sample_count"], features.digest(item)) for item in payloads),
            max_local_steps=epochs)
        create_federated_run(registry, "codebase-dispatched-create:" + operation_id, run_id, base_version_id, round_spec)
        completed = registry.get_run_completion(run_id)
        if completed is not None:
            record = recover_dispatched_codebase_round(index, registry, completed["candidate_version"]["version_id"],
                queue=queue, artifacts=artifacts, limits=limits)
            observe()
            return CodebaseDispatchedTrainingRecord(record.artifact_cid, record._payload, True)
        worker = getattr(dispatcher, "handler", None) if worker is None else worker
        _require(type(worker) is _artifacts().CodebaseFederatedArtifactWorker
                 and getattr(dispatcher, "handler", None) is worker, "trusted native artifact worker required")
        artifacts = worker.artifacts if artifacts is None else artifacts
        _require(artifacts is worker.artifacts, "owner and worker must share the admitted artifact store")
        registry.verify_artifact(base["row"]["artifact"])
        base_bytes = registry.artifact_path(base["row"]["artifact"]).read_bytes()
        context = {"tuning_targets": [item.to_dict() for item in base["tune"]],
                   "canary_targets": [item.to_dict() for item in base["canary"]],
                   "replay_targets": [item.to_dict() for item in base["replay"]]}
        invocation = uuid.uuid4().hex
        run_lease = registry.claim_run("codebase-dispatched-claim:" + operation_id + ":" + invocation,
            run_id, "codebase-dispatched-worker:" + invocation, lease_seconds=remaining() + 5.0)["lease"]
        def guard(task=None):
            observe()
            native = registry.get_run(run_id)
            _require(native["status"] == "running" and native["spec"]["round"] == round_spec.manifest,
                     "native dispatched round no longer running")
            registry._check_lease(run_lease, native["lease"])
            if task is not None:
                work = federation._sync().CodebaseFederatedWorkBinding.from_dict(
                    task["payload"]["declaration"]["payload"]["work_binding"])
                work.validate_round(round_spec)
                value = work.to_dict()
                _require(value["source_head"] == expected_head.to_dict() and value["base_version_id"] == base_version_id
                         and value["attempt"] == run_lease["attempt"] and value["fence"] == run_lease["fence"],
                         "dispatch task escaped its live source/native run fence")
            remaining()
            return True
        try:
            updates, local = [], []
            with tempfile.TemporaryDirectory(prefix="codebase-dispatched-", dir=registry.artifact_root) as workspace:
                with dispatcher.scoped_guard(guard), worker.execution_context(parent_lease=lease,
                        cancel_event=signal, remaining=remaining, memory_mb=memory_mb, limits=limits):
                    for position, (payload, client) in enumerate(zip(payloads, round_spec.clients)):
                        guard()
                        work = federation._sync().bind_codebase_federated_work(round_spec,
                            base_version_id=base_version_id, source_head=expected_head, client_id=client.client_id,
                            local_target_sha256=client.local_data_sha256, sample_count=client.sample_count,
                            attempt=run_lease["attempt"], fence=run_lease["fence"])
                        task = _artifacts().prepare_codebase_artifact_task(work, base_bytes=base_bytes,
                            local_payload=payload, context=context, artifacts=artifacts)
                        result = dispatcher.dispatch(task, round_spec.model_id,
                            timeout_seconds=remaining(), lease_seconds=min(600.0, remaining() + 5.0))
                        guard()
                        item = _artifacts().validate_codebase_artifact_result(task, result, artifacts, limits=limits)
                        _require(item["local_payload"] == payload and item["work_binding"] == work.to_dict(),
                                 "dispatched local result differs from approved source client")
                        attempted = federation._local_report(item, payload, adapter, base, limits)
                        derived = adapter.build_update(round_spec, client.client_id, item["local_state"], local_steps=attempted)
                        artifact = item["update_artifact"]
                        binary = _artifacts().read_codebase_artifact(artifacts, artifact, maximum=limits.max_candidate_bytes)
                        path = Path(workspace) / f"client-{position}.update.bin"
                        path.write_bytes(binary)
                        staged = registry.stage_artifact(path, artifact["sha256"])
                        update = read_client_update(registry.artifact_path(staged), round_spec,
                            expected_sha256=staged["sha256"], expected_cidv1=item["update_cid"],
                            max_bytes=limits.max_candidate_bytes)
                        _require(update.update_sha256 == derived.update_sha256,
                                 "worker binary differs from its exact local state and parent")
                        updates.append(update)
                        local.append({**item, "update_artifact": staged})
                        _require(sum(len(_wire(row)) + row["update_artifact"]["bytes"] for row in local)
                                 <= limits.max_candidate_bytes, "retained private clients exceed admitted bounds")
                        guard()
                candidate = aggregate_round(round_spec, adapter.parameters, updates)
                state = adapter.materialize_state(round_spec, candidate)
                materialized = {"contract": base["saved"]["contract"], "feature_space": base["saved"]["feature_space"], "state": state}
                comparison = {"baseline": federation._evaluate(federation._runtime(base["saved"]), base,
                    remaining=remaining, memory_mb=memory_mb, limits=limits, signal=signal, lease=lease),
                    "aggregate": federation._evaluate(federation._runtime(materialized), base,
                    remaining=remaining, memory_mb=memory_mb, limits=limits, signal=signal, lease=lease),
                    "purpose": "post_aggregation_fixed_canary_and_replay_diagnostics_not_qualification", "used_for_selection": False}
                federation._evaluation(comparison, base, state, limits)
                report = {"schema": federation.REPORT_SCHEMA, "origin_version_id": base["origin_version_id"],
                    "round": round_spec.manifest, "head": expected_head.to_dict(), "configuration": configuration,
                    "clients": local, "implementation": federation._pins(), "evaluation": comparison,
                    "optimizer_policy": federation.OPTIMIZER_POLICY, "base_state_sha256": features.digest(base["saved"]["state"]),
                    "candidate_sha256": candidate.candidate_sha256, "aggregation": candidate.provenance, **source._FALSE}
                materialized["report"] = {"codebase_federation": report, **features.FALSE}
                raw = _wire(materialized)
                update_bytes = sum(item["update_artifact"]["bytes"] for item in local)
                _require(len(raw) + update_bytes <= limits.max_candidate_bytes
                         and base["bytes"] + len(raw) + update_bytes <= limits.max_ancestry_bytes,
                         "prospective aggregate and retained update bytes exceed bounds")
                _require(_pins() == pins, "dispatched producer changed during execution")
                guard()
                path = Path(workspace) / "aggregate.checkpoint.json"
                path.write_bytes(raw)
                def verify_checkpoint(verified_round, verified_candidate, stored):
                    return (verified_round.manifest == round_spec.manifest
                            and verified_candidate.candidate_sha256 == candidate.candidate_sha256
                            and stored.read_bytes() == raw
                            and json.loads(stored.read_bytes())["state"] == adapter.materialize_state(verified_round, verified_candidate))
                completed = complete_federated_run(registry, "codebase-dispatched-complete:" + operation_id,
                    run_lease, round_spec, adapter.parameters, updates, path, verify_checkpoint=verify_checkpoint)
                run_lease = None
            observe()
            record = recover_dispatched_codebase_round(index, registry, completed["version_id"],
                queue=queue, artifacts=artifacts, limits=limits)
            remaining()
            return CodebaseDispatchedTrainingRecord(record.artifact_cid, record._payload, True)
        except BaseException as error:
            if run_lease is not None:
                try:
                    registry.fail_run("codebase-dispatched-fail:" + operation_id + ":" + str(run_lease["attempt"]),
                        run_lease, {"admitted": False, "qualified": False, "promotion_performed": False,
                                    "reason": "source_dispatched_federation_incomplete"})
                except Exception as cleanup_error:
                    error.add_note("Native dispatched federation failure recording also failed: " + str(cleanup_error))
            raise


__all__ = ["SCHEMA", "CodebaseDispatchedTrainingRecord", "train_current_dispatched_codebase_round",
           "load_dispatched_codebase_round", "recover_dispatched_codebase_round"]
