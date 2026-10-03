"""Durable peer-population references in the existing native registry owner.

One immutable manifest is bound under a source/base/run/fence-derived operation
before native model completion. The reference is evidence only: recovery first
requires authoritative native completion and independently replays its complete
numerical and queue history. No new table, head, lease or model is created.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import stat
import tempfile

from ipfs_datasets_py.duckdb_control.autoencoder_registry import SCHEMA as REGISTRY_SCHEMA
from . import codebase_dispatched_federation as canonical
from . import codebase_indexed_dispatch_recovery as indexed
from . import codebase_source_training as source
from . import codebase_federated_training as federation
from .content import cid_for_structured

SCHEMA = "codebase-peer-recovery-population@1"
COMMAND = "BindCodebasePeerRecoveryV1"
MAX_MANIFEST_BYTES = 65536
_require, _wire = source._require, source._wire


def _owner():
    from . import codebase_peer_dispatched_federation
    return codebase_peer_dispatched_federation


def producer_pins():
    names = (__name__, indexed.__name__, "ipfs_datasets_py.logic.software_contracts.content",
             "ipfs_datasets_py.duckdb_control.autoencoder_registry",
             "ipfs_datasets_py.duckdb_control.autoencoder_federated",
             "ipfs_accelerate_py.p2p_tasks.codebase_federated_history")
    return {name: hashlib.sha256(Path(importlib.import_module(name).__file__).read_bytes()).hexdigest() for name in names}


def _identity(run):
    _require(type(run) is dict and run["run_id"].startswith("codebase-dispatched-fed:peer:"),
             "native peer producer run required")
    round_spec = federation._round(run["spec"]["round"])
    _require(round_spec.round_id == run["run_id"] and round_spec.model_id == run["variant_id"]
             and run["spec"]["round_sha256"] == round_spec.round_sha256,
             "native peer round identity differs")
    _require(type(run["attempt"]) is int and run["attempt"] > 0 and type(run["fence"]) is int and run["fence"] > 0,
             "positive native peer attempt/fence required")
    identity = {"run_id": run["run_id"], "round_sha256": round_spec.round_sha256,
                "base_version_id": run["base_version_id"], "variant_id": run["variant_id"],
                "attempt": run["attempt"], "fence": run["fence"]}
    return identity, round_spec


def _operation(identity):
    return "peer-recovery:" + hashlib.sha256(_wire(identity)).hexdigest()


def _read_manifest(registry, descriptor):
    _require(type(descriptor) is dict and set(descriptor) == {"sha256", "bytes"}
             and type(descriptor["bytes"]) is int and 0 < descriptor["bytes"] <= MAX_MANIFEST_BYTES,
             "bounded native peer manifest descriptor required")
    # Verify the bounded, opened descriptor itself. The general registry reader
    # hashes to EOF, which is inappropriate before rejecting a corrupt FIFO or
    # an oversized body under this much smaller manifest envelope.
    registry._ensure_owner()
    path = registry.artifact_path(descriptor)
    _require(not path.parent.is_symlink(), "peer manifest directory must not be a symlink")
    descriptor_fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor_fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        _require(stat.S_ISREG(info.st_mode) and info.st_size == descriptor["bytes"], "bounded regular peer manifest required")
        raw = stream.read(MAX_MANIFEST_BYTES + 1)
    _require(len(raw) == descriptor["bytes"] and len(raw) <= MAX_MANIFEST_BYTES
             and hashlib.sha256(raw).hexdigest() == descriptor["sha256"], "native peer manifest bytes differ")
    value = json.loads(raw)
    _require(raw == _wire(value), "canonical native peer manifest bytes differ")
    _require(type(value) is dict and set(value) == {"schema", "identity", "policy_cid", "source_head", "clients",
                 "deliveries", "implementation", "authority"}
             and value["schema"] == SCHEMA and value["authority"] == _owner()._peer().FALSE
             and value["implementation"] == _owner()._pins(), "closed peer recovery manifest or producer differs")
    return value


def _validate_population(index, queue, run, manifest):
    identity, round_spec = _identity(run)
    _require(manifest["identity"] == identity and manifest["policy_cid"] == run["run_id"].split(":peer:", 1)[1],
             "peer population run/base/round/fence differs")
    policy = index.artifacts.get(manifest["policy_cid"], expected_schema=_owner().POLICY_SCHEMA)
    _require(policy["implementation"] == _owner()._pins(), "peer population producer policy differs")
    clients = manifest["clients"]
    _require(type(clients) is list and len(clients) == len(round_spec.clients)
             and 1 <= len(clients) <= 2 and len(manifest["deliveries"]) == len(clients), "complete bounded peer population required")
    rows = []
    for client, expected in zip(clients, round_spec.clients):
        _require(type(client) is dict and set(client) == {"client_id", "task_id", "request_sha256", "work_sha256"}
                 and client["client_id"] == expected.client_id, "peer client order/identity differs")
        row = queue.get(client["task_id"])
        _require(type(row) is dict, "retained native peer task is missing")
        work = federation._sync().CodebaseFederatedWorkBinding.from_dict(row["payload"]["declaration"]["payload"]["work_binding"])
        work.validate_round(round_spec)
        declared = work.to_dict()
        _require(work.sha256 == client["work_sha256"] and declared["client_id"] == expected.client_id
                 and declared["base_version_id"] == run["base_version_id"]
                 and declared["source_head"] == manifest["source_head"]
                 and declared["attempt"] == run["attempt"] and declared["fence"] == run["fence"],
                 "peer work source/base/native attempt or fence differs")
        request = canonical._completed_row(row, round_spec, declared)
        _require(request == client["request_sha256"], "peer exact request commitment differs")
        rows.append(row)
    _owner()._validate_deliveries(index, queue, policy, clients, manifest["deliveries"])
    return rows


def bind_peer_population(index, registry, queue, *, lease, policy_cid, deliveries):
    """Bind exact retained delivery references before native completion.

    The existing registry mutation owns atomicity and operation uniqueness. Its
    result remains admitted=false and cannot independently assert completion.
    """
    source._native_owners(index, registry)
    run = registry.get_run(lease["run_id"])
    registry._check_lease(lease, run["lease"])
    _require(run["status"] == "running", "peer recovery binding requires a running native round")
    identity, round_spec = _identity(run)
    _require(type(deliveries) is list and len(deliveries) == len(round_spec.clients) and 1 <= len(deliveries) <= 2,
             "bounded complete peer deliveries required")
    clients, source_head = [], None
    for ref in deliveries:
        snapshot = index.artifacts.get(ref, expected_schema="codebase-peer-delivery-snapshot@1")
        receipt = json.loads(snapshot["canonical_json"])
        row = queue.get(receipt["queue_dispatch"]["queue_task_id"])
        _require(type(row) is dict, "peer task no longer retained")
        work = federation._sync().CodebaseFederatedWorkBinding.from_dict(row["payload"]["declaration"]["payload"]["work_binding"])
        declared = work.to_dict()
        if source_head is None: source_head = declared["source_head"]
        clients.append({"client_id": declared["client_id"], "task_id": row["task_id"],
                        "request_sha256": receipt["request_sha256"], "work_sha256": work.sha256})
    manifest = {"schema": SCHEMA, "identity": identity, "policy_cid": policy_cid, "source_head": source_head,
                "clients": clients, "deliveries": list(deliveries), "implementation": _owner()._pins(),
                "authority": dict(_owner()._peer().FALSE)}
    _validate_population(index, queue, run, manifest)
    raw = _wire(manifest)
    _require(len(raw) <= MAX_MANIFEST_BYTES, "peer population manifest exceeds byte bound")
    with tempfile.TemporaryDirectory(prefix="peer-recovery-", dir=registry.artifact_root) as directory:
        path = Path(directory) / "manifest.json"; path.write_bytes(raw)
        descriptor = registry.stage_artifact(path, hashlib.sha256(raw).hexdigest())
    operation = _operation(identity)
    payload = {"identity": identity, "manifest": descriptor, "lease": dict(lease)}
    def apply(cx):
        current = registry._run(cx, run["run_id"])
        registry._check_lease(lease, current["lease"])
        _require(current["status"] == "running" and _identity(current)[0] == identity,
                 "native peer round changed before durable reference binding")
        return {"identity": identity, "manifest": descriptor, "scope": "prepared_transport_population_not_completion",
                "proof_authority": False, "model_admission": False}
    result = registry._mutate(operation, COMMAND, payload, apply)
    _require(result["identity"] == identity and result["manifest"] == descriptor,
             "peer recovery operation rebinding refused")
    return result


def _bound_manifest(index, registry, queue, completion):
    run = completion["run"]; identity, _ = _identity(run); operation = _operation(identity)
    with registry._transaction() as cx:
        stored = cx.execute("SELECT payload_digest,receipt FROM autoencoder_control.operations WHERE operation_id=?", [operation]).fetchone()
    _require(stored is not None and type(stored[1]) is str and len(stored[1].encode()) <= MAX_MANIFEST_BYTES,
             "completed peer round has no bounded durable transport reference")
    receipt = json.loads(stored[1])
    _require(type(receipt) is dict and set(receipt) == {"schema", "operation_id", "command", "admitted", "identity", "manifest",
                 "scope", "proof_authority", "model_admission"}
             and receipt["schema"] == REGISTRY_SCHEMA and receipt["operation_id"] == operation and receipt["command"] == COMMAND
             and receipt["identity"] == identity and receipt["admitted"] is False
             and receipt["scope"] == "prepared_transport_population_not_completion"
             and receipt["proof_authority"] is False and receipt["model_admission"] is False,
             "native peer reference receipt fields differ")
    payload = {"identity": identity, "manifest": receipt["manifest"], "lease": run["lease"]}
    _require(registry._command_digest(operation, COMMAND, payload) == stored[0]
             and registry.resolve_operation(operation, COMMAND, payload) == receipt,
             "native peer reference command digest differs")
    manifest = _read_manifest(registry, receipt["manifest"])
    _validate_population(index, queue, run, manifest)
    return manifest


def recover_peer_dispatched_codebase_round(index, registry, *, queue, run_id, limits=None):
    """Recover the exact sidecar after a lost final reply, without fitting.

    Current source/model heads are unchanged. Missing references fail closed;
    historical completion is not a new live execution or lease capability.
    """
    source._native_owners(index, registry)
    limits = canonical._limits(limits)
    queue = canonical._queue(None, queue)
    completion = registry.get_run_completion(run_id)
    _require(completion is not None, "peer population was prepared but native round is not completed")
    manifest = _bound_manifest(index, registry, queue, completion)
    version_id = completion["candidate_version"]["version_id"]
    # Exact indexed reconstruction independently verifies the checkpoint, native
    # reduction/diagnostics, all queue receipts and immutable artifact bodies.
    compatible = indexed.recover_indexed_dispatched_codebase_round(index, registry, version_id,
        queue=queue, artifacts=index.artifacts, limits=limits)
    expected = [{key: client[key] for key in ("client_id", "task_id", "request_sha256", "work_sha256")}
                for client in compatible.to_dict()["clients"]]
    _require(expected == manifest["clients"] and compatible.to_dict()["head"] == manifest["source_head"],
             "durable peer population differs from replayed numerical source history")
    value = {"schema": _owner().SCHEMA, "compatible_record_cid": compatible.artifact_cid, "version_id": version_id,
             "policy_cid": manifest["policy_cid"], "deliveries": manifest["deliveries"], "authority": dict(_owner()._peer().FALSE)}
    cid = index.artifacts.put(value)
    _require(_owner().load_peer_dispatched_codebase_round(index, registry, queue=queue, artifact_cid=cid, limits=limits) == value,
             "recovered peer sidecar differs")
    return {"artifact_cid": cid, **value}
