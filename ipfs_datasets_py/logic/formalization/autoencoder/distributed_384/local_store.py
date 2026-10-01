"""Host-local journal for distributed 384d training over the existing registry.

One process owns each DuckDB file. Its threads share this adapter, whose short
control operations are serialized; numerical workers never receive a database
connection. Different hosts exchange immutable artifacts, not this database.

This layer checks identity, lineage and delivery, not numerical correctness.
The coordinator must validate sufficient statistics before aggregation. Stored
updates, checkpoints and publication receipts confer no model/proof authority.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
import threading

from .....duckdb_control.autoencoder_registry import AutoencoderRegistry, RegistryError
from . import contracts


SCHEMA = "distributed-structured-384-local-store/v1"
PLAN_SCHEMA = "distributed-structured-384-plan/v1"
UPDATE_SCHEMA = "distributed-structured-384-update/v1"
MAX_DOCUMENT_BYTES = contracts.MAX_BYTES
MAX_PLAN_BYTES = 4 * 1024 * 1024
MAX_SHARDS = 4096
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")
_DOMAINS = {"legal_ir", "intent_ir", "security_ir", "ui_ux_ir"}
_FALSE = {**contracts.FALSE, "promoted": False,
          "numerical_correctness_verified": False}
_BINDINGS = ("plan_id", "base_checkpoint_sha256", "dataset_sha256", "recipe_sha256")


class LocalTrainingStoreError(RegistryError):
    """Malformed, conflicting or stale local campaign input."""


def _require(condition, message):
    if not condition:
        raise LocalTrainingStoreError(message)


def _raw(value):
    try:
        return contracts.raw(value)
    except (ValueError, TypeError, RecursionError) as exc:
        raise LocalTrainingStoreError("finite JSON document required") from exc


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _hash(value, name):
    _require(type(value) is str and _SHA.fullmatch(value), name + " must be a lowercase SHA256")


def _lease_seconds(value):
    _require(type(value) in (int, float) and math.isfinite(value) and 0 < value <= 86400,
             "lease_seconds must be finite and within (0, 86400]")


def _read(path, maximum=MAX_DOCUMENT_BYTES):
    path = Path(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            _require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= maximum,
                     "bounded nonempty regular file required")
            value = stream.read(maximum + 1)
    except OSError as exc:
        raise LocalTrainingStoreError("artifact is missing, aliased or unreadable") from exc
    _require(0 < len(value) <= maximum, "artifact exceeds byte bound")
    return value


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=pairs)
        _raw(value)  # Reject nonfinite values accepted by Python's JSON reader.
        return value
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise LocalTrainingStoreError("finite unambiguous JSON document required") from exc


def _plan(value):
    _require(type(value) is dict, "plan must be an object")
    encoded = _raw(value)
    _require(len(encoded) <= MAX_PLAN_BYTES, "plan exceeds byte bound")
    plan = _json(encoded)
    _require(plan.get("schema") == PLAN_SCHEMA and plan.get("domain_id") in _DOMAINS,
             "unsupported campaign schema or domain")
    for key in _BINDINGS:
        _hash(plan.get(key), key)
    _require(plan["plan_id"] == _digest({k: v for k, v in plan.items() if k != "plan_id"}),
             "plan content identity differs")
    shards = plan.get("shards")
    _require(type(shards) is list and 1 <= len(shards) <= MAX_SHARDS, "bounded nonempty shards required")
    seen = set()
    for shard in shards:
        _require(type(shard) is dict, "shard must be an object")
        name = shard.get("shard_id")
        _require(type(name) is str and _ID.fullmatch(name) and name not in seen,
                 "unique bounded shard IDs required")
        seen.add(name)
        _hash(shard.get("rows_sha256"), "rows_sha256")
        _require(type(shard.get("row_count")) is int and 0 < shard["row_count"] <= 10**9,
                 "positive bounded shard row_count required")
    return plan


def _run_id(plan, shard_id):
    return "ir384:" + plan["plan_id"] + ":" + shard_id


def _shard(plan, shard_id):
    found = [row for row in plan["shards"] if row["shard_id"] == shard_id]
    _require(len(found) == 1, "shard does not belong to this plan")
    return found[0]


def _update(raw, plan, shard):
    value = _json(raw)
    _require(type(value) is dict and value.get("schema") == UPDATE_SCHEMA, "unsupported update schema")
    for key in _BINDINGS:
        _require(value.get(key) == plan[key], "update " + key + " binding differs")
    for key in ("shard_id", "rows_sha256", "row_count"):
        _require(type(value.get(key)) is type(shard[key]) and value.get(key) == shard[key],
                 "update " + key + " binding differs")
    _require(type(value.get("statistics")) is dict, "update statistics must be an object")
    _hash(value.get("update_id"), "update_id")
    _require(value["update_id"] == _digest({k: v for k, v in value.items() if k != "update_id"}),
             "update content identity differs")
    if "domain_id" in value:
        _require(value["domain_id"] == plan["domain_id"], "update domain binding differs")
    return value


class LocalTrainingStore:
    """An explicit single-owner local registry; safe to share among host threads.

    Opening another instance for the same file is rejected by the existing
    cross-process registry lock. Restart fences old leases. A successful claim
    returns the raw registry lease, and an already completed shard returns None.
    """

    def __init__(self, database_path, artifact_root):
        self._lock = threading.RLock()
        self.registry = AutoencoderRegistry(database_path, artifact_root)

    def __enter__(self):
        self.registry._ensure_owner()
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        with self._lock:
            self.registry.close()

    def _stage_bytes(self, raw):
        path = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.registry.artifact_root, prefix=".ir384-", delete=False) as stream:
                path = Path(stream.name)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            return self.registry.stage_artifact(path, expected_sha256=hashlib.sha256(raw).hexdigest())
        finally:
            if path is not None:
                path.unlink(missing_ok=True)

    @staticmethod
    def _base_payload(plan, manifest):
        return {"variant_id": "ir384:" + plan["plan_id"], "artifact": manifest["base_artifact"],
                "metadata": {"schema": SCHEMA, "role": "base_checkpoint", "plan_id": plan["plan_id"], **_FALSE},
                "parent_version_id": None}

    def _campaign(self, plan):
        plan = _plan(plan)
        variant_id = "ir384:" + plan["plan_id"]
        manifest = self.registry.get_variant(variant_id)["manifest"]
        _require(set(manifest) == {"schema", "domain_id", "plan_id", "plan_sha256", "plan_artifact", "base_artifact", *_FALSE}
                 and manifest.get("schema") == SCHEMA
                 and manifest.get("plan_sha256") == _digest(plan)
                 and manifest.get("plan_id") == plan["plan_id"]
                 and manifest.get("domain_id") == plan["domain_id"]
                 and all(manifest.get(k) is False for k in _FALSE),
                 "registered campaign plan differs")
        self.registry.verify_artifact(manifest["plan_artifact"])
        _require(_json(_read(self.registry.artifact_path(manifest["plan_artifact"]), MAX_PLAN_BYTES)) == plan,
                 "registered campaign plan artifact differs")
        self.registry.verify_artifact(manifest["base_artifact"])
        _require(manifest["base_artifact"]["sha256"] == plan["base_checkpoint_sha256"],
                 "registered base checkpoint binding differs")
        receipt = self.registry.resolve_operation("ir384:base:" + plan["plan_id"], "RegisterVersion",
                                                  self._base_payload(plan, manifest))
        _require(receipt is not None, "campaign registration incomplete; rerun register_campaign")
        return plan, {"variant_id": variant_id, "base_version_id": receipt["version_id"],
                      "plan_sha256": manifest["plan_sha256"],
                      "run_ids": {s["shard_id"]: _run_id(plan, s["shard_id"]) for s in plan["shards"]}}

    @staticmethod
    def _spec(plan, shard):
        return {"schema": SCHEMA, "role": "shard_update", "plan_sha256": _digest(plan),
                **{k: plan[k] for k in _BINDINGS}, "shard": shard, **_FALSE}

    def _run(self, plan, campaign, shard):
        run = self.registry.get_run(_run_id(plan, shard["shard_id"]))
        _require(run["variant_id"] == campaign["variant_id"]
                 and run["base_version_id"] == campaign["base_version_id"]
                 and run["spec"] == self._spec(plan, shard), "registered shard binding differs")
        return run

    def register_campaign(self, plan, base_path):
        """Idempotently register the exact base and all shard runs; never a head."""
        with self._lock:
            plan = _plan(plan)
            base = _read(base_path)
            _require(hashlib.sha256(base).hexdigest() == plan["base_checkpoint_sha256"],
                     "base checkpoint SHA256 differs")
            base_ref = self._stage_bytes(base)
            manifest = {"schema": SCHEMA, "domain_id": plan["domain_id"], "plan_id": plan["plan_id"],
                        "plan_sha256": _digest(plan), "plan_artifact": self._stage_bytes(_raw(plan)),
                        "base_artifact": base_ref, **_FALSE}
            self.registry.register_variant("ir384:variant:" + plan["plan_id"],
                                           "ir384:" + plan["plan_id"], manifest)
            base_receipt = self.registry.register_version("ir384:base:" + plan["plan_id"],
                                                         **self._base_payload(plan, manifest))
            for shard in plan["shards"]:
                run_id = _run_id(plan, shard["shard_id"])
                self.registry.create_run("create:" + run_id, run_id, "ir384:" + plan["plan_id"],
                                         base_receipt["version_id"], self._spec(plan, shard))
            return self._campaign(plan)[1]

    def _completed_path(self, plan, campaign, shard):
        run = self._run(plan, campaign, shard)
        history = self.registry.get_run_completion(run["run_id"])
        if history is None:
            return None
        version = history["candidate_version"]
        self.registry.verify_artifact(version["artifact"])
        path = self.registry.artifact_path(version["artifact"])
        update = _update(_read(path), plan, shard)
        expected = {"schema": SCHEMA, "role": "shard_update", "plan_id": plan["plan_id"],
                    "shard_id": shard["shard_id"], "update_id": update["update_id"],
                    "update_artifact": version["artifact"], **_FALSE}
        _require(run["result"] == expected, "completed shard result binding differs")
        return path

    def claim(self, plan, shard_id, worker_id, lease_seconds=300):
        """Claim one missing shard. A repeated live claim by its owner is stable."""
        with self._lock:
            _lease_seconds(lease_seconds)
            plan, campaign = self._campaign(plan)
            shard = _shard(plan, shard_id)
            run = self._run(plan, campaign, shard)
            if run["status"] == "completed":
                self._completed_path(plan, campaign, shard)
                return None
            lease = run["lease"]
            if self.registry._live(lease) and lease["worker_id"] == worker_id:
                return lease
            operation = "ir384:claim:" + _digest({"run_id": run["run_id"], "worker_id": worker_id,
                "generation": self.registry.owner_generation, "fence": run["fence"] + 1,
                "lease_seconds": lease_seconds})
            return self.registry.claim_run(operation, run["run_id"], worker_id, lease_seconds)["lease"]

    def _lease_shard(self, plan, campaign, lease):
        _require(type(lease) is dict, "lease must be an object")
        rows = [s for s in plan["shards"] if _run_id(plan, s["shard_id"]) == lease.get("run_id")]
        _require(len(rows) == 1, "lease does not belong to this plan")
        self._run(plan, campaign, rows[0])
        return rows[0]

    def renew(self, plan, lease, lease_seconds=300):
        with self._lock:
            _lease_seconds(lease_seconds)
            plan, campaign = self._campaign(plan)
            self._lease_shard(plan, campaign, lease)
            operation = "ir384:renew:" + _digest({"lease": lease, "lease_seconds": lease_seconds})
            return self.registry.renew_lease(operation, lease, lease_seconds)["lease"]

    def complete(self, plan, lease, update_path):
        """Retain one exact shard update; duplicate bytes replay its receipt."""
        with self._lock:
            plan, campaign = self._campaign(plan)
            shard = self._lease_shard(plan, campaign, lease)
            raw = _read(update_path)
            update = _update(raw, plan, shard)
            artifact = self._stage_bytes(_raw(update))
            result = {"schema": SCHEMA, "role": "shard_update", "plan_id": plan["plan_id"],
                      "shard_id": shard["shard_id"], "update_id": update["update_id"],
                      "update_artifact": artifact, **_FALSE}
            history = self.registry.get_run_completion(lease["run_id"])
            if history is not None:
                _require(history["run"]["lease"] == lease and history["run"]["result"] == result
                         and history["candidate_version"]["artifact"] == artifact,
                         "completed shard conflicts with this lease or update")
                self._completed_path(plan, campaign, shard)
                return history["completion_receipt"]
            operation = "ir384:complete:" + _digest({"lease": lease, "artifact": artifact})
            return self.registry.complete_run(operation, lease, artifact, result)

    def completed(self, plan):
        """Return verified CAS paths only; never trust a worker's success flag."""
        with self._lock:
            plan, campaign = self._campaign(plan)
            result = {}
            for shard in plan["shards"]:
                path = self._completed_path(plan, campaign, shard)
                if path is not None:
                    result[shard["shard_id"]] = path
            return result

    def pending(self, plan):
        """Incomplete shards, including currently leased work, in plan order."""
        with self._lock:
            plan = _plan(plan)
            done = self.completed(plan)
            return [s["shard_id"] for s in plan["shards"] if s["shard_id"] not in done]

    def record_checkpoint(self, plan, checkpoint_path, evidence):
        """Record one aggregate only after every shard is durable, without promotion."""
        with self._lock:
            plan, campaign = self._campaign(plan)
            done = self.completed(plan)
            _require(len(done) == len(plan["shards"]), "all shard updates must be complete")
            _require(type(evidence) is dict, "checkpoint evidence must be an object")
            checkpoint = self._stage_bytes(_read(checkpoint_path))
            evidence_raw = _raw(evidence)
            _require(len(evidence_raw) <= MAX_DOCUMENT_BYTES, "checkpoint evidence exceeds byte bound")
            evidence_ref = self._stage_bytes(evidence_raw)
            updates = []
            for shard in plan["shards"]:
                history = self.registry.get_run_completion(_run_id(plan, shard["shard_id"]))
                updates.append({"shard_id": shard["shard_id"],
                                "version_id": history["candidate_version"]["version_id"],
                                "artifact": history["candidate_version"]["artifact"],
                                "update_id": history["run"]["result"]["update_id"]})
            aggregation = {"schema": SCHEMA, "role": "aggregation_inputs", "plan_id": plan["plan_id"],
                           "updates": updates, "evidence_artifact": evidence_ref, **_FALSE}
            metadata = {"schema": SCHEMA, "role": "aggregate_checkpoint", "plan_id": plan["plan_id"],
                        "plan_sha256": campaign["plan_sha256"], "aggregation_artifact": self._stage_bytes(_raw(aggregation)),
                        "evidence_artifact": evidence_ref, "shard_count": len(updates), **_FALSE}
            receipt = self.registry.register_version("ir384:aggregate:" + plan["plan_id"],
                campaign["variant_id"], checkpoint, metadata, campaign["base_version_id"])
            return self.registry.get_version(receipt["version_id"])

    def enqueue_publication(self, plan, version_id, publication_plan_path):
        """Durably queue an exact artifact delivery; no network or head changes."""
        with self._lock:
            plan, campaign = self._campaign(plan)
            version = self.registry.get_version(version_id)
            _require(version["variant_id"] == campaign["variant_id"]
                     and version["metadata"].get("role") == "aggregate_checkpoint"
                     and version["metadata"].get("plan_id") == plan["plan_id"],
                     "publication must reference this campaign aggregate")
            self.registry.verify_artifact(version["artifact"])
            raw = _read(publication_plan_path, MAX_PLAN_BYTES)
            _require(type(_json(raw)) is dict, "publication plan must be an object")
            ref = self._stage_bytes(raw)
            return self.registry.enqueue_publication("ir384:publish:" + _digest([version_id, ref]), version_id, ref)

    def publication_status(self, event_id):
        return self.registry.get_outbox_event("huggingface", event_id)

    def claim_publication(self, event_id, worker_id, lease_seconds=300):
        with self._lock:
            _lease_seconds(lease_seconds)
            event = self.publication_status(event_id)
            lease = event["lease"]
            if event["status"] == "leased" and self.registry._live(lease) and lease["worker_id"] == worker_id:
                return {k: event[k] for k in ("event_id", "consumer", "kind", "payload", "lease")}
            operation = "ir384:delivery:" + _digest({"event_id": event_id, "worker_id": worker_id,
                "generation": self.registry.owner_generation, "previous_lease": lease,
                "lease_seconds": lease_seconds})
            return self.registry.claim_outbox_event(operation,
                event_id, "huggingface", worker_id, lease_seconds)["delivery"]

    def ack_publication(self, event_id, lease, receipt):
        """Record a caller-verified transport receipt; this is not verification."""
        with self._lock:
            operation = "ir384:ack:" + _digest([event_id, lease, receipt])
            return self.registry.ack_outbox(operation, event_id, "huggingface", receipt, lease)
