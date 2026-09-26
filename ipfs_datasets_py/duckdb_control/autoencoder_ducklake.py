"""Bounded owner delivery to the explicit isolated native DuckLake history.

The control owner alone claims, renews and acknowledges events. Lake work runs
outside its transactions. A durable local journal freezes batch membership
before append, so a lost response or partial acknowledgement cannot cause a
different batch to be silently substituted. This does not activate production
DuckLake, transfer checkpoint ownership, promote a model, or admit a theorem.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import stat
import uuid

from .autoencoder_registry import AutoencoderRegistry, RegistryError, _token
from .contracts import canonical_json_bytes, content_identity
from ..ducklake.autoencoder_history import (
    IsolatedNativeDuckLakeHistory, build_history_batch, validate_history_batch, validate_history_source,
)

SCHEMA = "autoencoder-ducklake-delivery-journal-v1"
MAX_JOURNAL_BYTES = 8 * 1024 * 1024
MAX_OPERATIONS = 128


class HistoryDeliveryError(ValueError):
    """A bounded history delivery cannot safely advance."""


def _canonical(value):
    return canonical_json_bytes(value)


def _copy(value):
    return json.loads(_canonical(value))


def _same(left, right):
    return _canonical(left) == _canonical(right)


def _path(value):
    path = Path(value).absolute()
    if path != path.resolve():
        raise HistoryDeliveryError("history journal path must not contain aliases")
    return path


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class _Journal:
    def __init__(self, path, binding):
        self.path = path
        if path.exists():
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_JOURNAL_BYTES:
                    raise HistoryDeliveryError("history journal is not a bounded regular file")
                raw = stream.read(MAX_JOURNAL_BYTES + 1)
            self.data = json.loads(raw)
            if (_canonical(self.data) + b"\n" != raw or type(self.data) is not dict
                    or set(self.data) != {"schema", "binding", "journal_id", "operations", "claim", "batch", "commit", "result"}
                    or self.data["schema"] != SCHEMA or not _same(self.data["binding"], binding)
                    or type(self.data["operations"]) is not list
                    or len(self.data["operations"]) > MAX_OPERATIONS):
                raise HistoryDeliveryError("history journal binding or shape differs")
        else:
            self.data = {"schema": SCHEMA, "binding": _copy(binding), "journal_id": uuid.uuid4().hex,
                         "operations": [], "claim": None, "batch": None, "commit": None, "result": None}
            self.save()

    def save(self):
        raw = _canonical(self.data) + b"\n"
        if len(raw) > MAX_JOURNAL_BYTES:
            raise HistoryDeliveryError("history delivery journal exceeds byte bound")
        temporary = self.path.with_name(".journal-" + uuid.uuid4().hex)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            _sync_directory(self.path.parent)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _invoke(registry, operation):
        methods = {"ClaimOutbox": registry.claim_outbox,
                   "ClaimOutboxEvent": registry.claim_outbox_event,
                   "RenewOutbox": registry.renew_outbox,
                   "AckOutbox": registry.ack_outbox}
        command = operation["command"]
        if command not in methods:
            raise HistoryDeliveryError("unknown history journal command")
        return methods[command](operation["operation_id"], **operation["payload"])

    def resolve_pending(self, registry):
        for operation in self.data["operations"]:
            if operation["result"] is not None or operation["rejected"]:
                continue
            result = registry.resolve_operation(operation["operation_id"], operation["command"], operation["payload"])
            if result is not None:
                operation["result"] = result
            else:
                # No effect was committed under this exact ID. A new attempt
                # may use the current owner generation/lease after restart.
                operation["rejected"] = True
            self.save()

    def call(self, registry, command, payload):
        if len(self.data["operations"]) >= MAX_OPERATIONS:
            raise HistoryDeliveryError("history delivery operation budget exhausted")
        operation = {"operation_id": "history-" + self.data["journal_id"] + "-" + str(len(self.data["operations"])),
                     "command": command, "payload": _copy(payload), "result": None, "rejected": False}
        self.data["operations"].append(operation)
        self.save()
        try:
            result = self._invoke(registry, operation)
        except Exception:
            result = registry.resolve_operation(operation["operation_id"], command, operation["payload"])
            if result is None:
                operation["rejected"] = True
                self.save()
                raise
        operation["result"] = result
        self.save()
        return result


@contextmanager
def _locked_journal(directory, binding):
    directory = _path(directory)
    directory.mkdir(mode=0o700, parents=False, exist_ok=True)
    fd = os.open(directory / "owner.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise HistoryDeliveryError("journal lock must be a regular file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise HistoryDeliveryError("history delivery journal already has an owner") from exc
        path = directory / "delivery.json"
        if not path.exists() and {item.name for item in directory.iterdir()} != {"owner.lock"}:
            raise HistoryDeliveryError("nonempty history journal directory has no durable binding")
        yield _Journal(path, binding)
    finally:
        os.close(fd)


def _event_row(registry, delivery, *, verify_artifact):
    event = registry.get_outbox_event("ducklake", delivery["event_id"])
    if not _same({key: event[key] for key in ("event_id", "consumer", "kind", "payload")},
                 {key: delivery[key] for key in ("event_id", "consumer", "kind", "payload")}):
        raise HistoryDeliveryError("delivery differs from immutable owner event")
    version = variant = None
    if "version_id" in event["payload"]:
        version = registry.get_version(event["payload"]["version_id"])
        variant = registry.get_variant(version["variant_id"])
        if verify_artifact:
            registry.verify_artifact(version["artifact"])
    elif "variant_id" in event["payload"]:
        variant = registry.get_variant(event["payload"]["variant_id"])
    # In particular, run_failed stays the historical run_id/attempt event.
    # Current mutable run/head contents must never enrich an old event.
    return {key: event[key] for key in ("event_id", "kind", "payload", "created_at")} | {
        "version": version, "variant": variant}


def _require_commit(receipt, batch, sink):
    expected_fields = {"schema", "scope", "history_id", "batch_id", "source_id", "event_ids",
                       "event_count", "snapshot_id", "event_payloads_verified", "production_activated", "admitted"}
    if (type(receipt) is not dict or set(receipt) != expected_fields
            or receipt["schema"] != "autoencoder-ducklake-commit-v1"
            or receipt["scope"] != "isolated_history"
            or receipt["history_id"] != sink.identity["history_id"]
            or receipt["batch_id"] != batch["batch_id"]
            or receipt["source_id"] != batch["source"]["source_id"]
            or receipt["event_ids"] != [row["event_id"] for row in batch["events"]]
            or type(receipt["event_count"]) is not int or receipt["event_count"] != len(batch["events"])
            or type(receipt["snapshot_id"]) is not int or receipt["snapshot_id"] < 1
            or receipt["event_payloads_verified"] is not True
            or receipt["production_activated"] is not False or receipt["admitted"] is not False):
        raise HistoryDeliveryError("DuckLake commit receipt differs from the frozen batch")


def _lease_for(journal, registry, event_id, worker_id, lease_seconds):
    event = registry.get_outbox_event("ducklake", event_id)
    if event["status"] == "acknowledged":
        return None
    lease = event["lease"]
    if lease is not None and lease.get("worker_id") == worker_id:
        try:
            return journal.call(registry, "RenewOutbox", {
                "event_id": event_id, "consumer": "ducklake", "lease": lease,
                "lease_seconds": lease_seconds})["lease"]
        except RegistryError:
            # A restart or expiry invalidates the old lease. Targeted claim
            # still refuses any competing live consumer's lease.
            pass
    return journal.call(registry, "ClaimOutboxEvent", {
        "event_id": event_id, "consumer": "ducklake", "worker_id": worker_id,
        "lease_seconds": lease_seconds})["delivery"]["lease"]


def deliver_ducklake_history(registry, sink, *, source_id, output_directory,
                            worker_id="autoencoder-history", lease_seconds=300, limit=10):
    """Deliver/reconcile one immutable batch; repeated calls reuse its journal.

Use a new output directory for the next batch. Existing directories can only
resume their original source, target and delivery settings. This API accepts
the actual isolated native sink, not the hermetic ingest default. It performs
no training, native training validation, HF upload, or production activation.
    """
    if type(registry) is not AutoencoderRegistry or type(sink) is not IsolatedNativeDuckLakeHistory:
        raise HistoryDeliveryError("delivery requires exact owner and isolated native history instances")
    if type(limit) is not int or not 1 <= limit <= 10:
        raise HistoryDeliveryError("history batches must contain at most ten events")
    if type(lease_seconds) not in (float, int) or not math.isfinite(lease_seconds) or not 0 < lease_seconds <= 3600:
        raise HistoryDeliveryError("history lease seconds must be finite and bounded")
    _token(worker_id, "worker_id")
    source = {"source_id": source_id, "database_path": str(registry.database_path),
              "artifact_root": str(registry.artifact_root)}
    # Validate even an empty queue before any lease is created.
    validate_history_source(source)
    binding = {"source": source, "sink": sink.identity, "worker_id": worker_id,
               "lease_seconds": lease_seconds, "limit": limit}
    with _locked_journal(output_directory, binding) as journal:
        journal.resolve_pending(registry)
        claims = [op for op in journal.data["operations"]
                  if op["command"] == "ClaimOutbox" and op["result"] is not None]
        if len(claims) > 1:
            raise HistoryDeliveryError("journal contains more than one successful batch claim")
        historical_claim = None
        if claims:
            op = claims[0]
            historical_claim = registry.resolve_operation(op["operation_id"], op["command"], op["payload"])
            if historical_claim is None or not _same(historical_claim, op["result"]):
                raise HistoryDeliveryError("journal claim differs from its durable owner receipt")
        if journal.data["claim"] is None:
            claimed = historical_claim if historical_claim is not None else journal.call(registry, "ClaimOutbox", {
                "consumer": "ducklake", "worker_id": worker_id, "lease_seconds": lease_seconds, "limit": limit})
            journal.data["claim"] = claimed
            journal.save()
        elif historical_claim is None or not _same(journal.data["claim"], historical_claim):
            raise HistoryDeliveryError("frozen claim differs from the authoritative owner operation")
        deliveries = journal.data["claim"]["deliveries"]
        if not deliveries:
            result = {"schema": "autoencoder-ducklake-delivery-v1", "status": "empty", "event_count": 0,
                      "commit": None, "production_activated": False, "admitted": False}
            if journal.data["result"] is not None and not _same(journal.data["result"], result):
                raise HistoryDeliveryError("recorded empty result differs from verified delivery state")
            journal.data["result"] = result
            journal.save()
            return _copy(result)
        if journal.data["batch"] is None:
            rows = [_event_row(registry, item, verify_artifact=True) for item in deliveries]
            journal.data["batch"] = build_history_batch(source, rows)
            journal.save()
        batch = validate_history_batch(journal.data["batch"])
        if not _same(batch["source"], source):
            raise HistoryDeliveryError("frozen history source binding differs")
        actual = build_history_batch(source, [_event_row(registry, item, verify_artifact=False) for item in deliveries])
        if not _same(actual, batch):
            raise HistoryDeliveryError("frozen history batch differs from authoritative immutable records")
        if journal.data["result"] is not None:
            observed = sink.lookup(batch)
            _require_commit(observed, batch, sink)
            if not _same(observed, journal.data["commit"]):
                raise HistoryDeliveryError("recorded completion differs from current target commit")
            for row in batch["events"]:
                event = registry.get_outbox_event("ducklake", row["event_id"])
                if event["status"] != "acknowledged" or not _same(event["receipt"], journal.data["commit"]):
                    raise HistoryDeliveryError("recorded completion differs from owner acknowledgements")
            result = {"schema": "autoencoder-ducklake-delivery-v1", "status": "acknowledged",
                      "event_count": len(batch["events"]), "commit": observed,
                      "production_activated": False, "admitted": False}
            if not _same(journal.data["result"], result):
                raise HistoryDeliveryError("recorded result differs from verified delivery state")
            return _copy(result)
        receipt = sink.lookup(batch)
        if receipt is None:
            for row in batch["events"]:
                if _lease_for(journal, registry, row["event_id"], worker_id, lease_seconds) is None:
                    raise HistoryDeliveryError("owner acknowledged an event absent from the target commit")
            try:
                receipt = sink.append(batch)
            except Exception:
                receipt = sink.lookup(batch)
                if receipt is None:
                    raise
        _require_commit(receipt, batch, sink)
        if journal.data["commit"] is not None and not _same(journal.data["commit"], receipt):
            raise HistoryDeliveryError("durable target commit identity changed")
        journal.data["commit"] = _copy(receipt)
        journal.save()
        for row in batch["events"]:
            event_id = row["event_id"]
            event = registry.get_outbox_event("ducklake", event_id)
            if event["status"] == "acknowledged":
                if not _same(event["receipt"], receipt):
                    raise HistoryDeliveryError("event already acknowledged with a different target receipt")
                continue
            lease = _lease_for(journal, registry, event_id, worker_id, lease_seconds)
            if lease is None:
                raise HistoryDeliveryError("event acknowledgement changed during delivery")
            observed = sink.lookup(batch)
            _require_commit(observed, batch, sink)
            if not _same(observed, receipt):
                raise HistoryDeliveryError("target commit changed before acknowledgement")
            journal.call(registry, "AckOutbox", {"event_id": event_id, "consumer": "ducklake",
                                                 "receipt": receipt, "lease": lease})
        result = {"schema": "autoencoder-ducklake-delivery-v1", "status": "acknowledged",
                  "event_count": len(batch["events"]), "commit": receipt,
                  "production_activated": False, "admitted": False}
        journal.data["result"] = _copy(result)
        journal.save()
        return _copy(result)
