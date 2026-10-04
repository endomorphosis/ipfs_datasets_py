"""Bounded parallel artifact fits with source-owned compatible aggregation.

The existing numerical checkpoint/transport profile is preserved. A separately
bound execution policy and sidecar record this producer's resource contract.
Every client joins before owner reduction or failure releases the root lease.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import dataclass
import hashlib
import importlib
import json
from pathlib import Path
import re
import tempfile
import threading
import uuid

from . import codebase_dispatched_federation as owner
from . import codebase_federated_artifacts as artifacts_worker
from . import codebase_federated_training as federation
from . import codebase_indexed_dispatch_recovery as recovery
from . import codebase_source_training as source
from .codebase_parallel_resources import parallel_codebase_resources
from .content import canonical_dag_json_bytes, cid_for_structured
from ipfs_datasets_py.duckdb_control.autoencoder_federated import create_federated_run, complete_federated_run
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_federated import ClientSpec, aggregate_round
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_federated_update_codec import read_client_update
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_sync import TrainingMode, GradientBackendUnavailable

SCHEMA = "codebase-parallel-dispatched-federation@1"
POLICY_SCHEMA = "codebase-parallel-execution-policy@1"
_PREFIX = "codebase-dispatched-fed:parallel:"
_FALSE = {**owner._FALSE, "parallel_fleet_qualified": False}
_require, _wire = source._require, source._wire


def _pins():
    names = (__name__, "ipfs_datasets_py.logic.software_contracts.codebase_parallel_resources",
        recovery.__name__, "ipfs_accelerate_py.p2p_tasks.codebase_federated_history")
    return {"files": {name: hashlib.sha256(Path(importlib.import_module(name).__file__).read_bytes()).hexdigest()
            for name in names}, "compatible_transport_producer": owner._pins(),
        "scope": "listed_local_files_only_not_execution_attestation"}


def _policy(operation_id, client_count, max_workers, parallel, worker_memory_mb, control_memory_mb, use_request_index):
    source._text(operation_id, "operation_id", 128)
    _require(re.fullmatch(r"[A-Za-z0-9._:-]+", operation_id), "native operation token required")
    _require(type(client_count) is int and 2 <= client_count <= 8
             and type(max_workers) is int and 1 <= max_workers <= 8
             and type(parallel) is bool and type(use_request_index) is bool,
             "bounded exact parallel/index policy required")
    _require(all(type(value) is int and value >= 512 for value in (worker_memory_mb, control_memory_mb)),
             "bounded worker/control memory required")
    workers = min(max_workers, client_count) if parallel else 1
    return {"schema": POLICY_SCHEMA, "operation_id": operation_id, "client_count": client_count,
        "max_workers": max_workers, "parallel": parallel, "workers": workers,
        "worker_memory_mb": worker_memory_mb, "control_memory_mb": control_memory_mb,
        "cpu_slots": workers + 1, "child_process_slots": workers + 1,
        "total_memory_mb": workers * worker_memory_mb + control_memory_mb,
        "use_request_index": use_request_index, "reduction_order": "committed_source_client_order",
        "failure_cleanup": "cancel_and_join_all_clients_before_owner_failure_or_release",
        "implementation": _pins(), "authority": dict(_FALSE)}


@dataclass(frozen=True, slots=True)
class CodebaseParallelTrainingRecord:
    artifact_cid: str
    _payload: bytes
    observed_live: bool = False

    def __post_init__(self):
        _require(type(self._payload) is bytes and type(self.observed_live) is bool,
                 "immutable parallel training record required")
        value = json.loads(self._payload)
        _require(canonical_dag_json_bytes(value) == self._payload and cid_for_structured(value) == self.artifact_cid
                 and value["schema"] == SCHEMA and value["authority"] == _FALSE
                 and all(flag is False for flag in value["authority"].values()),
                 "parallel record identity/authority differs")

    def to_dict(self):
        return json.loads(self._payload)


def _retained_policy(index, registry, version_id, limits):
    row, saved = source._read_candidate(registry, version_id, limits)
    run_id = row["metadata"].get("producer_run")
    _require(type(run_id) is str and run_id.startswith(_PREFIX), "parallel producer run required")
    policy_cid = run_id.rsplit(":", 1)[1]
    policy = index.artifacts.get(policy_cid, expected_schema=POLICY_SCHEMA)
    expected = _policy(policy["operation_id"], len(saved["report"]["codebase_federation"]["round"]["clients"]),
        policy["max_workers"], policy["parallel"], policy["worker_memory_mb"], policy["control_memory_mb"],
        policy["use_request_index"])
    _require(policy == expected and policy_cid == cid_for_structured(expected)
             and run_id == _PREFIX + policy["operation_id"] + ":" + policy_cid
             and saved["report"]["codebase_federation"]["round"]["round_id"] == run_id,
             "retained execution policy differs from exact native run")
    return policy_cid, policy


def _record(compatible, policy_cid):
    original = compatible.to_dict()
    value = {"schema": SCHEMA, **{key: original[key] for key in ("version_id", "variant_id", "parent_version_id",
        "origin_version_id", "head", "round_sha256")}, "policy_cid": policy_cid,
        "compatible_dispatch_record_cid": compatible.artifact_cid, "implementation": _pins(),
        "authority": dict(_FALSE)}
    raw = canonical_dag_json_bytes(value)
    return CodebaseParallelTrainingRecord(cid_for_structured(value), raw)


def load_parallel_dispatched_codebase_round(index, registry, version_id, *, dispatcher=None,
        queue=None, artifacts=None, artifact_cid=None, limits=None):
    """Replay exact parallel policy and compatible model/task history; no work."""
    limits = owner._limits(limits)
    policy_cid, policy = _retained_policy(index, registry, version_id, limits)
    existing = None if artifact_cid is None else index.artifacts.get(artifact_cid, expected_schema=SCHEMA)
    _require(existing is None or existing["version_id"] == version_id, "parallel sidecar belongs to another model")
    compatible = recovery.load_indexed_dispatched_codebase_round(index, registry, version_id,
        dispatcher=dispatcher, queue=queue, artifacts=artifacts, limits=limits,
        artifact_cid=None if existing is None else existing["compatible_dispatch_record_cid"],
        use_request_index=policy["use_request_index"])
    record = _record(compatible, policy_cid)
    _require(artifact_cid is None or artifact_cid == record.artifact_cid, "parallel sidecar belongs to another run")
    _require(existing is None or existing == record.to_dict(), "parallel sidecar differs from exact native history")
    _require(index.artifacts.get(record.artifact_cid, expected_schema=SCHEMA) == record.to_dict(),
             "published parallel sidecar differs")
    return record


def recover_parallel_dispatched_codebase_round(index, registry, version_id, *, dispatcher=None,
        queue=None, artifacts=None, limits=None):
    """Explicit provenance repair after durable completion; no fitting."""
    limits = owner._limits(limits)
    policy_cid, policy = _retained_policy(index, registry, version_id, limits)
    compatible = recovery.recover_indexed_dispatched_codebase_round(index, registry, version_id,
        dispatcher=dispatcher, queue=queue, artifacts=artifacts, limits=limits,
        use_request_index=policy["use_request_index"])
    record = _record(compatible, policy_cid)
    _require(index.artifacts.put(record.to_dict()) == record.artifact_cid, "parallel sidecar publication differs")
    return record


class _Signals:
    def __init__(self, *signals):
        self.signals = tuple(signal for signal in signals if signal is not None)

    def is_set(self):
        return any(signal.is_set() for signal in self.signals)


def _dispatch_all(tasks, *, dispatcher, worker, guard, lease, signal, stop, remaining,
        worker_memory_mb, limits, workers, model_id):
    """Keep at most workers submitted futures and join all even after failure."""
    results = [None] * len(tasks)
    failures, failure_lock = [], threading.Lock()
    def invoke(position):
        try:
            with dispatcher.scoped_guard(guard), worker.execution_context(parent_lease=lease,
                    cancel_event=signal, remaining=remaining, memory_mb=worker_memory_mb, limits=limits):
                guard()
                result = dispatcher.dispatch(tasks[position], model_id, timeout_seconds=remaining(),
                    lease_seconds=min(600.0, remaining() + 5.0))
                guard()
                return result
        except BaseException as error:
            with failure_lock:
                if not failures:
                    failures.append(error)
                stop.set()
            raise
    executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="codebase-fit")
    pending, next_position = {}, 0
    try:
        for position in range(min(workers, len(tasks))):
            pending[executor.submit(invoke, position)] = position
            next_position += 1
        while pending:
            settled, _ = wait(tuple(pending), return_when=FIRST_COMPLETED)
            for future in settled:
                position = pending.pop(future)
                results[position] = future.result()
            remaining()
            while next_position < len(tasks) and len(pending) < workers:
                pending[executor.submit(invoke, next_position)] = next_position
                next_position += 1
        return results
    except BaseException:
        stop.set()
        for future in pending:
            future.cancel()
        if failures:
            raise failures[0]
        raise
    finally:
        executor.shutdown(wait=True, cancel_futures=True)


def train_current_parallel_dispatched_codebase_round(index, repository, *, expected_head, registry,
        base_version_id, clients, operation_id, dispatcher, worker=None, artifacts=None,
        max_workers=2, parallel=True, worker_memory_mb=1024, control_memory_mb=1024,
        use_request_index=True, epochs=1, learning_rate=.002, seed=1729, mode=TrainingMode.FEDERATED,
        limits=None, scheduler=None, parent_lease=None, cancel_event=None,
        admission_timeout_seconds=30.0, timeout_seconds=120.0):
    """Fit bounded independent clients and register one exact compatible candidate."""
    _require(type(mode) is TrainingMode, "explicit native training mode required")
    if mode is not TrainingMode.FEDERATED:
        raise GradientBackendUnavailable("parallel CodebaseIR executor implements federation only")
    source._native_owners(index, registry)
    limits, queue = owner._limits(limits), owner._queue(dispatcher, None)
    _require(type(dispatcher) is owner._transport().CodebaseQueueDispatcher, "native local dispatcher required")
    worker = dispatcher.handler if worker is None else worker
    _require(type(worker) is artifacts_worker.CodebaseFederatedArtifactWorker and dispatcher.handler is worker,
             "trusted native artifact worker required")
    artifacts = worker.artifacts if artifacts is None else artifacts
    _require(artifacts is worker.artifacts, "owner and worker must share the admitted transfer store")
    _require(cancel_event is None or callable(getattr(cancel_event, "is_set", None)), "typed cancellation signal required")
    configuration = federation._configuration(epochs, learning_rate, seed)
    # Validate the requested controls before reserving resources; the complete
    # client partition/count and final immutable policy are checked inside.
    _policy(operation_id, 2, max_workers, parallel, worker_memory_mb, control_memory_mb, use_request_index)
    _require(type(clients) in {tuple, list} and 2 <= len(clients) <= 8, "bounded client cohort required")
    workers = min(max_workers, len(clients)) if parallel else 1
    stop = threading.Event()
    with parallel_codebase_resources(index, repository, expected_head, workers=workers,
            worker_memory_mb=worker_memory_mb, control_memory_mb=control_memory_mb, scheduler=scheduler,
            parent_lease=parent_lease, cancel_event=_Signals(cancel_event, stop), limits=limits,
            admission_timeout_seconds=admission_timeout_seconds, timeout_seconds=timeout_seconds) as (lease, signal, remaining, observe):
        base = recovery._checked_child(index, registry, base_version_id, limits)
        _require(base["depth"] < limits.max_ancestry, "prospective federation ancestry depth exceeded")
        adapter = federation._adapter().CodebaseFeatureCheckpoint.from_runtime(federation._runtime(base["saved"]),
            base_sha256=base["row"]["artifact"]["sha256"], base_version_id=base_version_id)
        _require(adapter.state["optimizer_config"]["learning_rate"] == configuration["learning_rate"],
                 "private Adam resume requires the parent learning rate")
        selections = [source.CodebaseTrainingSelection.from_dict(item) for item in base["origin"]["selections"]]
        clients = federation._clients(clients, selections)
        policy = _policy(operation_id, len(clients), max_workers, parallel, worker_memory_mb, control_memory_mb, use_request_index)
        policy_cid, pins = cid_for_structured(policy), _pins()
        run_id = _PREFIX + operation_id + ":" + policy_cid
        payloads, current_train = federation._capture(index, expected_head, base, clients, configuration, limits)
        _require(len(base["history"]) + len(current_train) <= limits.max_training_history,
                 "prospective training history exceeds admitted history bound")
        round_spec = adapter.build_round(run_id, "codebase-source:" + base["origin_version_id"],
            tuple(ClientSpec(item["client_id"], item["sample_count"], features.digest(item)) for item in payloads),
            max_local_steps=epochs)
        create_federated_run(registry, "codebase-parallel-create:" + operation_id, run_id, base_version_id, round_spec)
        _require(index.artifacts.put(policy) == policy_cid, "parallel execution policy publication differs")
        completed = registry.get_run_completion(run_id)
        if completed is not None:
            record = recover_parallel_dispatched_codebase_round(index, registry,
                completed["candidate_version"]["version_id"], queue=queue, artifacts=artifacts, limits=limits)
            observe()
            return CodebaseParallelTrainingRecord(record.artifact_cid, record._payload, True)
        registry.verify_artifact(base["row"]["artifact"])
        base_bytes = registry.artifact_path(base["row"]["artifact"]).read_bytes()
        context = {"tuning_targets": [item.to_dict() for item in base["tune"]],
            "canary_targets": [item.to_dict() for item in base["canary"]], "replay_targets": [item.to_dict() for item in base["replay"]]}
        invocation = uuid.uuid4().hex
        run_lease = registry.claim_run("codebase-parallel-claim:" + operation_id + ":" + invocation,
            run_id, "codebase-parallel-worker:" + invocation, lease_seconds=remaining() + 5.0)["lease"]
        owner_lock = threading.RLock()
        def guard(task=None):
            with owner_lock:
                observe()
                native = registry.get_run(run_id)
                _require(native["status"] == "running" and native["spec"]["round"] == round_spec.manifest,
                         "native parallel round no longer running")
                registry._check_lease(run_lease, native["lease"])
                if task is not None:
                    work = federation._sync().CodebaseFederatedWorkBinding.from_dict(
                        task["payload"]["declaration"]["payload"]["work_binding"])
                    work.validate_round(round_spec)
                    value = work.to_dict()
                    _require(value["source_head"] == expected_head.to_dict() and value["base_version_id"] == base_version_id
                             and value["attempt"] == run_lease["attempt"] and value["fence"] == run_lease["fence"],
                             "parallel task escaped live source/native run fence")
                remaining()
                return True
        try:
            tasks = []
            for payload, client in zip(payloads, round_spec.clients):
                guard()
                work = federation._sync().bind_codebase_federated_work(round_spec, base_version_id=base_version_id,
                    source_head=expected_head, client_id=client.client_id, local_target_sha256=client.local_data_sha256,
                    sample_count=client.sample_count, attempt=run_lease["attempt"], fence=run_lease["fence"])
                tasks.append(artifacts_worker.prepare_codebase_artifact_task(work, base_bytes=base_bytes,
                    local_payload=payload, context=context, artifacts=artifacts))
            results = _dispatch_all(tasks, dispatcher=dispatcher, worker=worker, guard=guard, lease=lease,
                signal=signal, stop=stop, remaining=remaining, worker_memory_mb=worker_memory_mb,
                limits=limits, workers=workers, model_id=round_spec.model_id)
            guard()
            updates, local = [], []
            with tempfile.TemporaryDirectory(prefix="codebase-parallel-", dir=registry.artifact_root) as workspace:
                for position, (payload, task, result) in enumerate(zip(payloads, tasks, results)):
                    item = artifacts_worker.validate_codebase_artifact_result(task, result, artifacts, limits=limits)
                    _require(item["local_payload"] == payload
                             and item["work_binding"] == task["declaration"]["payload"]["work_binding"],
                             "parallel result differs from approved source client")
                    attempted = federation._local_report(item, payload, adapter, base, limits)
                    derived = adapter.build_update(round_spec, payload["client_id"], item["local_state"], local_steps=attempted)
                    artifact = item["update_artifact"]
                    binary = artifacts_worker.read_codebase_artifact(artifacts, artifact, maximum=limits.max_candidate_bytes)
                    path = Path(workspace) / f"client-{position}.update.bin"
                    path.write_bytes(binary)
                    staged = registry.stage_artifact(path, artifact["sha256"])
                    update = read_client_update(registry.artifact_path(staged), round_spec,
                        expected_sha256=staged["sha256"], expected_cidv1=item["update_cid"], max_bytes=limits.max_candidate_bytes)
                    _require(update.update_sha256 == derived.update_sha256, "worker binary differs from exact private state/base")
                    updates.append(update)
                    local.append({**item, "update_artifact": staged})
                    _require(sum(len(_wire(value)) + value["update_artifact"]["bytes"] for value in local)
                             <= limits.max_candidate_bytes, "retained parallel clients exceed admitted bound")
                    guard()
                candidate = aggregate_round(round_spec, adapter.parameters, updates)
                state = adapter.materialize_state(round_spec, candidate)
                materialized = {"contract": base["saved"]["contract"], "feature_space": base["saved"]["feature_space"], "state": state}
                comparison = {"baseline": federation._evaluate(federation._runtime(base["saved"]), base,
                    remaining=remaining, memory_mb=control_memory_mb, limits=limits, signal=signal, lease=lease),
                    "aggregate": federation._evaluate(federation._runtime(materialized), base,
                    remaining=remaining, memory_mb=control_memory_mb, limits=limits, signal=signal, lease=lease),
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
                         "prospective parallel aggregate/ancestry exceeds bounds")
                _require(_pins() == pins, "parallel producer changed during execution")
                guard()
                path = Path(workspace) / "aggregate.checkpoint.json"
                path.write_bytes(raw)
                def verify_checkpoint(verified_round, verified_candidate, stored):
                    return (verified_round.manifest == round_spec.manifest
                        and verified_candidate.candidate_sha256 == candidate.candidate_sha256
                        and stored.read_bytes() == raw
                        and json.loads(stored.read_bytes())["state"] == adapter.materialize_state(verified_round, verified_candidate))
                completed = complete_federated_run(registry, "codebase-parallel-complete:" + operation_id,
                    run_lease, round_spec, adapter.parameters, updates, path, verify_checkpoint=verify_checkpoint)
                run_lease = None
            observe()
            record = recover_parallel_dispatched_codebase_round(index, registry, completed["version_id"],
                queue=queue, artifacts=artifacts, limits=limits)
            remaining()
            return CodebaseParallelTrainingRecord(record.artifact_cid, record._payload, True)
        except BaseException as error:
            stop.set()
            if run_lease is not None:
                try:
                    registry.fail_run("codebase-parallel-fail:" + operation_id + ":" + str(run_lease["attempt"]), run_lease,
                        {"admitted": False, "qualified": False, "promotion_performed": False,
                         "reason": "source_parallel_federation_incomplete"})
                except Exception as cleanup_error:
                    error.add_note("Native parallel failure recording also failed: " + str(cleanup_error))
            raise


__all__ = ["SCHEMA", "POLICY_SCHEMA", "CodebaseParallelTrainingRecord", "train_current_parallel_dispatched_codebase_round",
    "load_parallel_dispatched_codebase_round", "recover_parallel_dispatched_codebase_round"]
