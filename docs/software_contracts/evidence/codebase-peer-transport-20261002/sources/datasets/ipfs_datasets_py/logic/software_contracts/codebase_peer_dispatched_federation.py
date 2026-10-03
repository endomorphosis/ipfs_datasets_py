"""Source-owned FedAvg over explicit local MCP++ peer processes.

This additive owner shares canonical capture, artifact, numerical replay and
registry completion. It does not widen the old local worker's identity check.
Only the transport execution policy/sidecar are new. Remote networking and
gradient collectives are not implemented by this profile.
"""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
import hashlib
import json
from pathlib import Path
import re
import tempfile
import threading
import time
import uuid

from . import codebase_dispatched_federation as owner
from . import codebase_federated_artifacts as artifacts_owner
from . import codebase_federated_training as federation
from . import codebase_source_training as source
from .codebase_resources import acquire_codebase_resources
from .content import cid_for_structured
from ipfs_datasets_py.duckdb_control.autoencoder_federated import create_federated_run, complete_federated_run
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_federated import ClientSpec, aggregate_round
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_federated_update_codec import read_client_update
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_sync import TrainingMode, GradientBackendUnavailable

SCHEMA = "codebase-local-peer-federation@1"
POLICY_SCHEMA = "codebase-local-peer-policy@1"
_require, _wire = source._require, source._wire


def _peer():
    from ipfs_accelerate_py.p2p_tasks import codebase_peer_transport
    return codebase_peer_transport


def _pins():
    return {"owner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "peer": _peer().pins(), "canonical_owner": owner._pins()}


class _Peers:
    def __init__(self, peers):
        _require(type(peers) is dict and 1 <= len(peers) <= 2
                 and all(type(value) is _peer().CodebasePeerWorker for value in peers.values()),
                 "one or two explicit native local peer profiles required")
        _require(len({value.profile_id for value in peers.values()}) == len(peers)
                 and len({value.receipt_root for value in peers.values()}) == len(peers),
                 "distinct peer identities and receipt roots required")
        self.peers = dict(peers)
        self.artifacts = next(iter(peers.values())).artifacts
        _require(all(value.artifacts is self.artifacts for value in peers.values()), "exact shared immutable CAS required")

    def __call__(self, task):
        work = task["payload"]["declaration"]["payload"]["work_binding"]
        _require(work["client_id"] in self.peers, "client has no explicit peer assignment")
        return self.peers[work["client_id"]](task)

    @contextmanager
    def execution_context(self, **kwargs):
        with ExitStack() as stack:
            for peer in self.peers.values():
                stack.enter_context(peer.execution_context(**kwargs))
            yield self


@contextmanager
def _resources(index, repository, head, *, parent_lease, cancel_event, timeout_seconds, memory_mb, limits):
    _require(type(timeout_seconds) in (int, float) and 0 < timeout_seconds <= 600
             and type(memory_mb) is int and memory_mb >= 1024, "bounded CPU peer envelope required")
    _require(limits.max_ancestry_bytes + 2 * limits.max_candidate_bytes + limits.max_target_bytes
             <= memory_mb * 1024**2 // 4, "retained bytes exceed control memory")
    signal = threading.Event() if cancel_event is None else cancel_event
    _require(callable(getattr(signal, "is_set", None)), "cancellation signal required")
    deadline = time.monotonic() + timeout_seconds
    with acquire_codebase_resources(parent_lease=parent_lease, cancel_event=signal, cpu_slots=3,
            memory_mb=2 * memory_mb + 512, child_process_slots=3,
            timeout_seconds=min(30, timeout_seconds)) as root:
        combined = root.combined_cancellation_signal(signal)
        def remaining():
            seconds = deadline - time.monotonic()
            _require(not combined.is_set() and seconds > 0, "peer federation cancelled or deadline exceeded")
            return seconds
        with acquire_codebase_resources(parent_lease=root, cancel_event=combined, memory_mb=memory_mb,
                timeout_seconds=remaining()) as control:
            def observe():
                index.observe_current(repository, expected_head=head, parent_lease=control, cancel_event=combined,
                    timeout_seconds=remaining(), admission_timeout_seconds=min(30, remaining()), memory_mb=memory_mb)
                remaining()
            observe()
            yield root, control, combined, remaining, observe
            observe()


def _stage(task, result, payload, work, adapter, base, limits, artifacts, registry, round_spec, path):
    item = artifacts_owner.validate_codebase_artifact_result(task, result, artifacts, limits=limits)
    _require(item["local_payload"] == payload and item["work_binding"] == work.to_dict(),
             "peer result differs from source-owned client work")
    steps = federation._local_report(item, payload, adapter, base, limits)
    derived = adapter.build_update(round_spec, work.to_dict()["client_id"], item["local_state"], local_steps=steps)
    reference = item["update_artifact"]
    path.write_bytes(artifacts_owner.read_codebase_artifact(artifacts, reference, maximum=limits.max_candidate_bytes))
    staged = registry.stage_artifact(path, reference["sha256"])
    update = read_client_update(registry.artifact_path(staged), round_spec, expected_sha256=staged["sha256"],
        expected_cidv1=item["update_cid"], max_bytes=limits.max_candidate_bytes)
    _require(update.update_sha256 == derived.update_sha256, "peer binary differs from replayed local state")
    return update, {**item, "update_artifact": staged}


def load_peer_dispatched_codebase_round(index, registry, *, queue, artifact_cid, limits=None):
    """Historical integrity replay; never renews a lease or claims live transport."""
    value = index.artifacts.get(artifact_cid, expected_schema=SCHEMA)
    _require(set(value) == {"schema", "compatible_record_cid", "version_id", "policy_cid", "deliveries", "authority"}
             and value["authority"] == _peer().FALSE, "closed peer sidecar required")
    policy = index.artifacts.get(value["policy_cid"], expected_schema=POLICY_SCHEMA)
    _require(policy["implementation"] == _pins(), "peer producer lineage differs")
    native = owner.load_dispatched_codebase_round(index, registry, value["version_id"], queue=queue,
        artifacts=index.artifacts, artifact_cid=value["compatible_record_cid"], limits=limits)
    _require(native.to_dict()["native_run_id"] == "codebase-dispatched-fed:peer:" + value["policy_cid"],
             "peer policy was not bound by the native round")
    expected = {item["request_sha256"]: item for item in native.to_dict()["clients"]}
    _require(type(value["deliveries"]) is list and len(value["deliveries"]) == len(expected), "complete peer delivery cohort required")
    seen = set()
    for ref in value["deliveries"]:
        receipt = json.loads(index.artifacts.get(ref, expected_schema="codebase-peer-delivery-snapshot@1")["canonical_json"])
        key = receipt["request_sha256"]
        _require(key in expected and key not in seen and receipt.get("delivery_verified") is True
                 and receipt["authority"] == _peer().FALSE and receipt["implementation"] == policy["implementation"]["peer"],
                 "peer receipt cohort or provenance differs")
        seen.add(key)
        client = expected[key]
        row = queue.get(client["task_id"])
        _require(receipt["queue_dispatch"]["queue_task_id"] == row["task_id"]
                 and receipt["queue_dispatch"]["queue_attempt"] == row["attempt"]
                 and receipt["queue_dispatch"]["worker_id"] == row["assigned_worker"]
                 and receipt["profile_id"] == policy["peers"][client["client_id"]]
                 and receipt["result_sha256"] == _peer()._sha(row["result"]), "peer/native completed task binding differs")
    return value


def train_current_peer_dispatched_codebase_round(index, repository, *, expected_head, registry,
        base_version_id, clients, operation_id, queue, peers, epochs=1, learning_rate=.002, seed=1729,
        mode=TrainingMode.FEDERATED, limits=None, parent_lease=None, cancel_event=None,
        timeout_seconds=300.0, memory_mb=1024):
    """One sequential two-profile local process round, with exact native FedAvg.

    A completed round is loaded by its returned sidecar CID. Recalling this
    training API after native completion refuses; it cannot reconstruct missing
    process evidence or relabel an older execution as a new peer invocation.
    """
    _require(type(mode) is TrainingMode, "explicit native training mode required")
    if mode is not TrainingMode.FEDERATED:
        raise GradientBackendUnavailable("local peer profile supports federation only")
    source._native_owners(index, registry)
    source._text(operation_id, "operation_id", 128)
    _require(re.fullmatch(r"[A-Za-z0-9._:-]+", operation_id), "native operation token required")
    limits = owner._limits(limits)
    worker = _Peers(peers)
    _require(worker.artifacts is index.artifacts, "source owner and peers must share exact CAS")
    dispatcher = owner._transport().CodebaseQueueDispatcher(queue, worker, worker_id_prefix="codebase-peer-controller")
    configuration = federation._configuration(epochs, learning_rate, seed)
    with _resources(index, repository, expected_head, parent_lease=parent_lease, cancel_event=cancel_event,
            timeout_seconds=timeout_seconds, memory_mb=memory_mb, limits=limits) as (root, control, signal, remaining, observe):
        base = federation._parent(index, registry, base_version_id, limits)
        _require(base["depth"] < limits.max_ancestry, "prospective federation ancestry exceeded")
        adapter = federation._adapter().CodebaseFeatureCheckpoint.from_runtime(federation._runtime(base["saved"]),
            base_sha256=base["row"]["artifact"]["sha256"], base_version_id=base_version_id)
        _require(adapter.state["optimizer_config"]["learning_rate"] == configuration["learning_rate"], "private Adam resume learning rate differs")
        clients = federation._clients(clients, [source.CodebaseTrainingSelection.from_dict(x) for x in base["origin"]["selections"]])
        payloads, _ = federation._capture(index, expected_head, base, clients, configuration, limits)
        _require(set(worker.peers) == {item["client_id"] for item in payloads}, "complete explicit client/peer mapping required")
        policy = {"schema": POLICY_SCHEMA, "operation_id": operation_id, "peers": {key: value.profile_id for key, value in peers.items()},
            "configuration": configuration, "implementation": _pins(), "authority": dict(_peer().FALSE),
            "scope": "sequential_local_processes_shared_CAS_not_remote_network"}
        # Native DAG-JSON excludes floats; keep the exact configuration as text.
        policy["configuration"] = _wire(configuration).decode("ascii")
        policy_cid = index.artifacts.put(policy)
        run_id = "codebase-dispatched-fed:peer:" + policy_cid
        round_spec = adapter.build_round(run_id, "codebase-source:" + base["origin_version_id"],
            tuple(ClientSpec(item["client_id"], item["sample_count"], features.digest(item)) for item in payloads), max_local_steps=epochs)
        create_federated_run(registry, "peer-create:" + policy_cid, run_id, base_version_id, round_spec)
        _require(registry.get_run_completion(run_id) is None, "completed peer round requires explicit historical sidecar load")
        registry.verify_artifact(base["row"]["artifact"])
        base_bytes = registry.artifact_path(base["row"]["artifact"]).read_bytes()
        context = {"tuning_targets": [x.to_dict() for x in base["tune"]], "canary_targets": [x.to_dict() for x in base["canary"]],
                   "replay_targets": [x.to_dict() for x in base["replay"]]}
        invocation = uuid.uuid4().hex
        claim = registry.claim_run("peer-claim:" + invocation, run_id, "peer-owner:" + invocation,
                                   lease_seconds=remaining() + 5)["lease"]
        def guard(task=None):
            observe()
            native = registry.get_run(run_id)
            _require(native["status"] == "running" and native["spec"]["round"] == round_spec.manifest, "native peer round is stale")
            registry._check_lease(claim, native["lease"])
            if task is not None:
                work = federation._sync().CodebaseFederatedWorkBinding.from_dict(task["payload"]["declaration"]["payload"]["work_binding"])
                work.validate_round(round_spec)
                value = work.to_dict()
                _require(value["source_head"] == expected_head.to_dict() and value["base_version_id"] == base_version_id
                         and value["attempt"] == claim["attempt"] and value["fence"] == claim["fence"], "peer task escaped source/model/native fence")
            remaining()
            return True
        try:
            updates, local, deliveries = [], [], []
            with tempfile.TemporaryDirectory(prefix="codebase-peer-", dir=registry.artifact_root) as directory:
                workspace = Path(directory)
                with dispatcher.scoped_guard(guard), worker.execution_context(parent_lease=root, cancel_event=signal,
                        remaining=remaining, memory_mb=memory_mb, limits=limits):
                    for position, payload in enumerate(payloads):
                        guard()
                        work = federation._sync().bind_codebase_federated_work(round_spec, base_version_id=base_version_id,
                            source_head=expected_head, client_id=payload["client_id"], local_target_sha256=features.digest(payload),
                            sample_count=payload["sample_count"], attempt=claim["attempt"], fence=claim["fence"])
                        task = artifacts_owner.prepare_codebase_artifact_task(work, base_bytes=base_bytes,
                            local_payload=payload, context=context, artifacts=index.artifacts)
                        result = dispatcher.dispatch(task, round_spec.model_id, timeout_seconds=remaining(), lease_seconds=min(600, remaining() + 5))
                        guard()
                        update, item = _stage(task, result, payload, work, adapter, base, limits, index.artifacts,
                                             registry, round_spec, workspace / f"{position}.update.bin")
                        updates.append(update); local.append(item)
                        _require(sum(len(_wire(x)) + x["update_artifact"]["bytes"] for x in local) <= limits.max_candidate_bytes,
                                 "retained peer updates exceed bound")
                        receipts = [r for r in peers[payload["client_id"]].receipts if r.get("delivery_verified")
                                    and r["request_sha256"] == result["request_sha256"]]
                        _require(len(receipts) == 1, "exact completed peer delivery receipt required")
                        deliveries.append(index.artifacts.put({"schema": "codebase-peer-delivery-snapshot@1",
                                                              "canonical_json": _wire(receipts[0]).decode("ascii")}))
                candidate = aggregate_round(round_spec, adapter.parameters, updates)
                state = adapter.materialize_state(round_spec, candidate)
                materialized = {"contract": base["saved"]["contract"], "feature_space": base["saved"]["feature_space"], "state": state}
                comparison = {"baseline": federation._evaluate(federation._runtime(base["saved"]), base, remaining=remaining,
                    memory_mb=memory_mb, limits=limits, signal=signal, lease=control),
                    "aggregate": federation._evaluate(federation._runtime(materialized), base, remaining=remaining,
                    memory_mb=memory_mb, limits=limits, signal=signal, lease=control),
                    "purpose": "post_aggregation_fixed_canary_and_replay_diagnostics_not_qualification", "used_for_selection": False}
                federation._evaluation(comparison, base, state, limits)
                report = {"schema": federation.REPORT_SCHEMA, "origin_version_id": base["origin_version_id"], "round": round_spec.manifest,
                    "head": expected_head.to_dict(), "configuration": configuration, "clients": local, "implementation": federation._pins(),
                    "evaluation": comparison, "optimizer_policy": federation.OPTIMIZER_POLICY,
                    "base_state_sha256": features.digest(base["saved"]["state"]), "candidate_sha256": candidate.candidate_sha256,
                    "aggregation": candidate.provenance, **source._FALSE}
                materialized["report"] = {"codebase_federation": report, **features.FALSE}
                raw = _wire(materialized)
                _require(len(raw) + sum(x["update_artifact"]["bytes"] for x in local) <= limits.max_candidate_bytes
                         and base["bytes"] + len(raw) + sum(x["update_artifact"]["bytes"] for x in local) <= limits.max_ancestry_bytes,
                         "aggregate/ancestry bytes exceed bounds")
                _require(_pins() == policy["implementation"], "peer owner producer changed")
                guard()
                path = workspace / "aggregate.json"; path.write_bytes(raw)
                def verify(verified_round, verified_candidate, stored):
                    return (verified_round.manifest == round_spec.manifest and verified_candidate.candidate_sha256 == candidate.candidate_sha256
                            and stored.read_bytes() == raw and json.loads(raw)["state"] == adapter.materialize_state(verified_round, verified_candidate))
                complete = complete_federated_run(registry, "peer-complete:" + policy_cid, claim, round_spec,
                    adapter.parameters, updates, path, verify_checkpoint=verify)
                claim = None
            observe()
            compatible = owner.recover_dispatched_codebase_round(index, registry, complete["version_id"], queue=queue, artifacts=index.artifacts, limits=limits)
            value = {"schema": SCHEMA, "compatible_record_cid": compatible.artifact_cid, "version_id": complete["version_id"],
                     "policy_cid": policy_cid, "deliveries": deliveries, "authority": dict(_peer().FALSE)}
            cid = index.artifacts.put(value)
            _require(load_peer_dispatched_codebase_round(index, registry, queue=queue, artifact_cid=cid, limits=limits) == value,
                     "published peer history replay differs")
            return {"artifact_cid": cid, **value}
        except BaseException as error:
            if claim is not None:
                try:
                    registry.fail_run("peer-fail:" + invocation, claim, {"admitted": False, "qualified": False,
                        "promotion_performed": False, "reason": "source_peer_federation_incomplete"})
                except Exception as cleanup:
                    error.add_note("Native peer failure recording also failed: " + str(cleanup))
            raise
