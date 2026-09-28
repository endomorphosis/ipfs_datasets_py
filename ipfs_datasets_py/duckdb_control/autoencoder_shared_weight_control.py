"""Existing Quack transport for a single shared, owner-verified weight registry.

This adapter lets the normal training coordinator use native Quack for scoped
run/version reads and successful lease/candidate mutations. Its workers retain
private numerical state and send sparse updates to the owner's immutable CAS;
they never concurrently open the DuckDB file. The owner coordinator still
verifies checkpoint replay and receipt provenance before authorizing CompleteRun.

This is the installed loopback Quack prototype, not a new public network server.
Full baseline artifacts must already be present locally. No artifacts or model
weights are downloaded. Cross-host execution and artifact transfer are separate
deployment work; an SSH tunnel alone does not qualify remote model execution.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from typing import Any, Mapping
import uuid

from .autoencoder_quack import (
    RegistryQuackGateway, RegistryTransportClient, RegistryTransportError, WorkerScope,
)
from .autoencoder_registry import AutoencoderRegistry
from .contracts import canonical_json_bytes

SCHEMA = "autoencoder-shared-weight-control/v1"
MAX_SCOPED_RUNS = 64
MAX_OWNER_OPERATIONS = 8192
_MUTATIONS = frozenset({"ClaimRun", "RenewLease", "CompleteRun"})


class SharedWeightControlError(ValueError):
    """Shared owner scope, prepared operation, or transport binding changed."""


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _durable_operation(worker_id: str, operation_id: str) -> str:
    # Exact existing RegistryQuackGateway namespace, not a new mutation log.
    return "worker-quack:" + _digest({"worker_id": worker_id, "operation_id": operation_id})


class _OwnerPreparedGateway(RegistryQuackGateway):
    """Allow only exact commands already prepared by the trusted coordinator.

    The generic gateway rightly refuses owner-verified training runs. This
    separate profile does not relax that gateway: every mutation here requires
    an out-of-band owner authorization, unavailable through the wire vocabulary.
    """

    def __init__(self, registry: AutoencoderRegistry, scope: WorkerScope):
        super().__init__(registry, scope, enable_prototype=True)
        self._prepared_lock = threading.RLock()
        self._prepared: dict[str, str] = {}
        self._bindings = {}
        self._bases = {}
        for run_id in scope.run_ids:
            run = registry.get_run(run_id)
            if not {"job_spec_sha256", "job_spec_artifact"}.issubset(run["spec"]):
                raise SharedWeightControlError("shared weight control requires an owner-registered training job")
            self._bindings[run_id] = _digest({key: run[key] for key in
                ("run_id", "variant_id", "base_version_id", "spec")})
            # The typed job, immutable registry version and worker assignment
            # must name the same base before any lease can dispatch a model.
            from ..optimizers.logic_theorem_optimizer.autoencoder_training_worker import TrainingJobSpec
            ref = registry.verify_artifact(run["spec"]["job_spec_artifact"])
            if ref["bytes"] > 64 * 1024 * 1024:
                raise SharedWeightControlError("registered job exceeds bounded control input")
            raw = registry.artifact_path(ref).read_bytes()
            if len(raw) != ref["bytes"] or hashlib.sha256(raw).hexdigest() != ref["sha256"]:
                raise SharedWeightControlError("registered job artifact changed during binding")
            spec = TrainingJobSpec.from_dict(json.loads(raw))
            base = registry.get_version(run["base_version_id"])
            if (spec.canonical_sha256 != run["spec"]["job_spec_sha256"] or spec.run_id != run_id
                    or spec.base_version_id != run["base_version_id"]
                    or base["variant_id"] != run["variant_id"]
                    or base["artifact"] != {"sha256": spec.base_checkpoint.sha256,
                                            "bytes": spec.base_checkpoint.bytes}):
                raise SharedWeightControlError("registered job and shared base version differ")
            self._bases[run_id] = base

    def authorize(self, operation_id: str, command: str, payload: Mapping[str, Any]) -> None:
        self.registry._ensure_owner()
        if command not in _MUTATIONS:
            raise SharedWeightControlError("only owner-prepared run mutations can be authorized")
        if command == "ClaimRun":
            self._worker_mutation_run(payload.get("run_id"))
        else:
            self._lease(payload)
        if command == "CompleteRun":
            result = payload.get("result")
            if not isinstance(result, Mapping) or result.get("admitted") is not False:
                raise SharedWeightControlError("candidate completion must remain unadmitted")
        digest = _digest({"command": command, "payload": payload})
        with self._prepared_lock:
            previous = self._prepared.get(operation_id)
            if previous is not None and previous != digest:
                raise SharedWeightControlError("owner operation ID reused with different content")
            if previous is None and len(self._prepared) >= MAX_OWNER_OPERATIONS:
                raise SharedWeightControlError("owner authorization window exceeds bound")
            self._prepared[operation_id] = digest

    def _worker_mutation_run(self, run_id: Any) -> str:
        run_id = self._run_scope(run_id)
        run = self.registry.get_run(run_id)
        if _digest({key: run[key] for key in ("run_id", "variant_id", "base_version_id", "spec")}) != self._bindings[run_id]:
            raise SharedWeightControlError("owner-registered training assignment changed")
        return run_id

    def dispatch(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        command = envelope.get("command")
        if command in _MUTATIONS:
            digest = _digest({"command": command, "payload": envelope.get("payload")})
            with self._prepared_lock:
                if self._prepared.get(envelope.get("operation_id")) != digest:
                    raise SharedWeightControlError("mutation was not prepared by the verifying owner coordinator")
        return super().dispatch(envelope)

    def status(self):
        return {**super().status(), "command_profile": "owner_prepared_shared_weights",
                "owner_prepared_mutations_only": True}


class SharedWeightRegistry:
    """Coordinator-compatible facade over one already-open registry owner.

    Use only around ``run_training_jobs``. The coordinator's existing independent
    receipt and sparse replay verification precedes ``complete_run``. No worker
    callback can call ``authorize`` or select another worker's run. Registration,
    local CAS staging, failure recording and historical replay remain owner-side;
    ClaimRun, RenewLease, CompleteRun and assigned reads use installed Quack.

    Closing this facade closes its clients/listeners, never the registry. A
    database-head change still uses the existing promotion policy and exact CAS;
    simultaneous children of a base remain separate immutable candidate versions.
    """

    def __init__(self, registry: AutoencoderRegistry, *, enable_prototype: bool = False):
        if enable_prototype is not True:
            raise SharedWeightControlError("shared native Quack control requires explicit prototype opt-in")
        if type(registry) is not AutoencoderRegistry:
            raise SharedWeightControlError("shared control requires the actual existing registry owner")
        registry._ensure_owner()
        self._registry = registry
        self._pid = os.getpid()
        self._closed = False
        self._lock = threading.RLock()
        self._channels: dict[str, tuple[_OwnerPreparedGateway, RegistryTransportClient]] = {}
        self._counts: dict[str, int] = {}

    def _ensure_open(self):
        if self._closed or os.getpid() != self._pid:
            raise SharedWeightControlError("shared control is closed or inherited by another process")
        self._registry._ensure_owner()

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        self._ensure_open()
        return getattr(self._registry, name)

    def __enter__(self):
        self._ensure_open()
        return self

    def __exit__(self, *exc):
        self.close()

    def _channel(self, run_id: str, worker_id: str):
        self._ensure_open()
        with self._lock:
            self._ensure_open()
            channel = self._channels.get(run_id)
            if channel is not None:
                if channel[0].scope.worker_id != worker_id:
                    raise SharedWeightControlError("run is already bound to another transport worker")
                return channel
            if len(self._channels) >= MAX_SCOPED_RUNS:
                raise SharedWeightControlError("shared dispatch exceeds the 64-run transport window")
            gateway = _OwnerPreparedGateway(self._registry, WorkerScope(worker_id, frozenset({run_id})))
            gateway.start()
            try:
                client = RegistryTransportClient(**gateway.connection_parameters())
            except BaseException:
                gateway.close()
                raise
            self._channels[run_id] = (gateway, client)
            return gateway, client

    def _request(self, run_id, worker_id, command, payload, operation_id):
        gateway, client = self._channel(run_id, worker_id)
        if command in _MUTATIONS:
            gateway.authorize(operation_id, command, payload)
        result = client.request(command, payload, operation_id)
        with self._lock:
            self._counts[command] = self._counts.get(command, 0) + 1
        return result

    def claim_run(self, operation_id, run_id, worker_id, lease_seconds=300):
        result = self._request(run_id, worker_id, "ClaimRun",
                               {"run_id": run_id, "lease_seconds": lease_seconds}, operation_id)
        self._verify_claim_base(run_id, worker_id)
        return result

    def _verify_claim_base(self, run_id, worker_id):
        gateway, _ = self._channel(run_id, worker_id)
        run = self._request(run_id, worker_id, "ReadRun", {"run_id": run_id},
                            "verify-base-run:" + uuid.uuid4().hex)["run"]
        if _digest({key: run[key] for key in ("run_id", "variant_id", "base_version_id", "spec")}) != gateway._bindings[run_id]:
            raise SharedWeightControlError("Quack run identity differs from owner-registered assignment")
        base = self._request(run_id, worker_id, "ReadVersion", {"version_id": run["base_version_id"]},
                             "verify-base-version:" + uuid.uuid4().hex)["version"]
        if canonical_json_bytes(base) != canonical_json_bytes(gateway._bases[run_id]):
            raise SharedWeightControlError("Quack base version differs from registered job checkpoint")

    def renew_lease(self, operation_id, lease, lease_seconds=300):
        return self._request(lease["run_id"], lease["worker_id"], "RenewLease",
                             {"lease": lease, "lease_seconds": lease_seconds}, operation_id)

    def complete_run(self, operation_id, lease, artifact, result):
        # Trusted coordinator boundary: _prepare_completion already verified
        # native provenance, exact checkpoint replay and staged this descriptor.
        completed = self._request(lease["run_id"], lease["worker_id"], "CompleteRun",
                                   {"lease": lease, "artifact": artifact, "result": result}, operation_id)
        self._verify_completed_candidate(completed, lease, artifact, result)
        return completed

    def _verify_completed_candidate(self, completed, lease, artifact, result):
        run_id, worker_id = lease["run_id"], lease["worker_id"]
        gateway, _ = self._channel(run_id, worker_id)
        version = self._request(run_id, worker_id, "ReadVersion", {"version_id": completed["version_id"]},
                                "verify-candidate-version:" + uuid.uuid4().hex)["version"]
        base = gateway._bases[run_id]
        expected_metadata = {"producer_run": run_id, "attempt": lease["attempt"], "result": result}
        if (completed.get("run_id") != run_id or completed.get("status") != "completed"
                or completed.get("admitted") is not False or completed.get("promoted") is not False
                or version["version_id"] != completed["version_id"]
                or version["artifact"] != artifact or version["parent_version_id"] != base["version_id"]
                or version["variant_id"] != base["variant_id"]
                or canonical_json_bytes(version["metadata"]) != canonical_json_bytes(expected_metadata)):
            raise SharedWeightControlError("Quack candidate differs from exact owner-verified completion")

    def resolve_operation(self, operation_id, command, payload):
        self._ensure_open()
        if command in _MUTATIONS:
            worker_id = payload["worker_id"] if command == "ClaimRun" else payload["lease"]["worker_id"]
            operation_id = _durable_operation(worker_id, operation_id)
        # Durable replay must work even after the disposable gateway disappeared.
        receipt = self._registry.resolve_operation(operation_id, command, payload)
        if receipt is not None and command == "ClaimRun":
            self._verify_claim_base(payload["run_id"], payload["worker_id"])
        elif receipt is not None and command == "CompleteRun":
            self._verify_completed_candidate(receipt, payload["lease"], payload["artifact"], payload["result"])
        return receipt

    def get_run(self, run_id):
        self._ensure_open()
        channel = self._channels.get(run_id)
        if channel is None:
            return self._registry.get_run(run_id)  # Owner validation before claim.
        return self._request(run_id, channel[0].scope.worker_id, "ReadRun",
                             {"run_id": run_id}, "read-run:" + uuid.uuid4().hex)["run"]

    def get_version(self, version_id):
        self._ensure_open()
        # Choosing a channel requires trusted local metadata; the actual scoped
        # read then crosses Quack. Unassigned bootstrap/admin reads remain local.
        version = self._registry.get_version(version_id)
        producer = version["metadata"].get("producer_run")
        with self._lock:
            channels = tuple(self._channels.items())
        for run_id, (gateway, _) in channels:
            run = self._registry.get_run(run_id)
            if run["base_version_id"] == version_id or producer == run_id:
                return self._request(run_id, gateway.scope.worker_id, "ReadVersion",
                                     {"version_id": version_id}, "read-version:" + uuid.uuid4().hex)["version"]
        return version

    def transport_report(self):
        self._ensure_open()
        with self._lock:
            channels = tuple(self._channels.values())
            counts = dict(self._counts)
        return {"schema_version": SCHEMA, "transport": "native_scoped_quack_prototype",
                "command_counts": counts, "scoped_run_count": len(channels),
                "capabilities": [gateway.capability for gateway, _ in channels],
                "shared_database_path": str(self._registry.database_path),
                "shared_artifact_root": str(self._registry.artifact_root),
                "database_writer_count": 1, "workers_open_database": False,
                "worker_weight_storage": "private_state_and_immutable_sparse_registry_artifacts",
                "owner_verified_completion_required": True, "automatic_branch_merge": False,
                "remote_artifact_transfer": False, "weights_downloaded": False,
                "cross_host_execution_qualified": False, "production_activation": False,
                "failure_recording": "trusted_owner_local", "historical_replay": "trusted_owner_local",
                "admitted": False, "formalized": False, "promotion_performed": False}

    def close(self):
        if self._closed:
            return
        self._ensure_open()
        with self._lock:
            errors = []
            for gateway, client in reversed(tuple(self._channels.values())):
                try:
                    client.close()
                    gateway.close()
                except Exception as exc:
                    errors.append(exc)
            if errors:
                raise SharedWeightControlError("shared transport did not close; keep owner alive") from errors[0]
            self._closed = True
