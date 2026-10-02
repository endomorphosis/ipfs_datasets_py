"""Durable retention for an explicit isolated codebase-history artifact profile.

The existing registry transaction/event log owns pins, producer/reader leases and
quiescence. A fresh dedicated CAS holds source-history candidate envelopes only.
No source/proof/model head or general shared-CAS collector is introduced. Native
DuckLake snapshots are inspected and pinned, never expired by this profile.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat

from .autoencoder_registry import AutoencoderRegistry, SCHEMA as REGISTRY_SCHEMA
from .contracts import canonical_json_bytes, content_identity
from .codebase_ducklake_history import (
    prepare_codebase_history_request, register_codebase_history_request,
    deliver_codebase_history, inspect_codebase_history, _request,
)
from ..ducklake.autoencoder_history import IsolatedNativeDuckLakeHistory
from ..logic.software_contracts.cache import ImmutableCAS
from ..logic.software_contracts.content import canonical_dag_json_bytes, cid_for_structured, validate_cid

SCHEMA = "codebase-history-retention@1"
CANDIDATE_SCHEMA = "codebase-history-candidate@1"
KIND = "codebase_history_retention_v1"
COMMAND = "CodebaseHistoryRetentionV1"
MAX_EVENTS = 512
MAX_EVENT_BYTES = 48 * 1024
MAX_CANDIDATE_BYTES = 24 * 1024
MAX_TARGETS = 8
MAX_NATIVE_OPERATIONS = 4096
MAX_NATIVE_RECEIPT_BYTES = 128 * 1024


class RetentionError(ValueError):
    """A durable pin, lease, source-history candidate or collection is invalid."""


def _require(condition, message):
    if not condition:
        raise RetentionError(message)


def _copy(value):
    return json.loads(canonical_json_bytes(value))


def _closed(value, fields):
    _require(type(value) is dict and set(value) == set(fields), "closed retention fields required")


def _id(value):
    _require(type(value) is str and 1 <= len(value.encode()) <= 256, "bounded retention identifier required")
    return value


def _derived(operation, phase):
    return "codebase-retention." + content_identity(dict(operation=_id(operation), phase=phase))


def _candidate(value, profile_id):
    _closed(value, ("schema", "profile_id", "stage_operation_id", "request"))
    _require(value["schema"] == CANDIDATE_SCHEMA and value["profile_id"] == profile_id,
             "candidate does not belong to this managed history profile")
    _id(value["stage_operation_id"])
    _request(value["request"])
    _require(len(canonical_dag_json_bytes(value)) <= MAX_CANDIDATE_BYTES, "candidate byte bound exceeded")
    return value


def _initial():
    return dict(descriptor=None, candidates={}, leases={}, pins={}, gate=None, collection=None, completed={})


def _reduce(state, action, data, operation_id):
    """Closed deterministic transition, replayed from the native operation log."""
    _require(type(action) is str and type(data) is dict, "closed retention command required")
    if action == "initialize":
        _closed(data, ("descriptor",))
        _require(state["descriptor"] is None, "retention profile already initialized")
        state["descriptor"] = data["descriptor"]
        return dict(initialized=True)
    _require(state["descriptor"] is not None, "retention profile is not initialized")
    profile_id = content_identity(state["descriptor"])
    if action == "acquire":
        _closed(data, ("kind", "owner_generation"))
        _require(state["gate"] is None and data["kind"] in ("producer", "reader")
                 and type(data["owner_generation"]) is int and data["owner_generation"] > 0,
                 "quiescence gate or invalid lease prevents admission")
        lease = dict(profile_id=profile_id, lease_id=operation_id, **data)
        _require(operation_id not in state["leases"], "lease already exists")
        _require(len(state["leases"]) < 32, "retention lease capacity exhausted")
        state["leases"][operation_id] = lease
        return dict(lease=lease)
    if action == "release":
        _closed(data, ("lease",))
        lease = data["lease"]
        _closed(lease, ("profile_id", "lease_id", "kind", "owner_generation"))
        _require(state["leases"].get(lease["lease_id"]) == lease, "unknown or stale lease")
        del state["leases"][lease["lease_id"]]
        return dict(released=lease["lease_id"])
    if action == "recover_leases":
        _closed(data, ("owner_generation",))
        generation = data["owner_generation"]
        _require(type(generation) is int and generation > 0 and state["gate"] is None,
                 "invalid native recovery generation")
        obsolete = sorted(key for key, lease in state["leases"].items() if lease["owner_generation"] < generation)
        _require(all(lease["owner_generation"] <= generation for lease in state["leases"].values()),
                 "retention owner generation moved backward")
        for key in obsolete:
            del state["leases"][key]
        return dict(recovered_leases=obsolete)
    if action == "register_candidate":
        _closed(data, ("lease", "candidate_cid", "envelope"))
        lease = data["lease"]
        _require(state["gate"] is None and state["leases"].get(lease.get("lease_id")) == lease
                 and lease["kind"] == "producer", "active producer lease required")
        envelope = _candidate(data["envelope"], profile_id)
        cid = data["candidate_cid"]
        _require(cid_for_structured(envelope) == cid and cid not in state["candidates"], "candidate identity conflict")
        _require(len(state["candidates"]) < 64, "retention candidate capacity exhausted")
        state["candidates"][cid] = dict(envelope=envelope, deleted=False)
        return dict(candidate_cid=cid, record_cid=envelope["request"]["record_cid"])
    if action == "pin":
        _closed(data, ("pin_id", "candidate_cid", "registration", "snapshot"))
        pin_id, cid = _id(data["pin_id"]), data["candidate_cid"]
        candidate = state["candidates"].get(cid)
        _require(state["gate"] is None and candidate is not None and not candidate["deleted"]
                 and pin_id not in state["pins"], "candidate missing, collected, pinned or quiescent")
        _closed(data["registration"], ("operation_id", "request"))
        _require(candidate["envelope"]["request"] == data["registration"]["request"], "pin origin differs")
        snapshot = data["snapshot"]
        _closed(snapshot, ("history_id", "source_id", "event_id", "snapshot_id"))
        _require(snapshot["history_id"] == state["descriptor"]["history_id"]
                 and type(snapshot["snapshot_id"]) is int and snapshot["snapshot_id"] > 0,
                 "pin snapshot identity differs")
        _require(len(state["pins"]) < 8, "retention pin capacity exhausted")
        state["pins"][pin_id] = data
        return dict(pin_id=pin_id, candidate_cid=cid, snapshot_id=snapshot["snapshot_id"])
    if action == "unpin":
        _closed(data, ("pin_id",))
        _require(state["gate"] is None and data["pin_id"] in state["pins"], "pin unavailable or profile quiescent")
        del state["pins"][data["pin_id"]]
        return dict(released_pin=data["pin_id"])
    if action == "quiesce":
        _closed(data, ())
        _require(state["gate"] is None and not state["leases"], "active or unreconciled leases prevent quiescence")
        state["gate"] = operation_id
        return dict(gate_id=operation_id)
    if action == "unquiesce":
        _closed(data, ("gate_id",))
        _require(state["gate"] == data["gate_id"] and state["collection"] is None, "collection pending or gate differs")
        state["gate"] = None
        return dict(released_gate=data["gate_id"])
    if action == "prepare_collection":
        _closed(data, ("gate_id", "collection_id", "targets"))
        _require(state["gate"] == data["gate_id"] and state["collection"] is None and not state["leases"],
                 "exact quiescence gate required")
        targets = data["targets"]
        _require(type(targets) is list and 1 <= len(targets) <= MAX_TARGETS, "bounded explicit collection required")
        cids = [target.get("candidate_cid") for target in targets]
        _require(cids == sorted(set(cids)), "unique ordered collection targets required")
        retained = {pin["candidate_cid"] for pin in state["pins"].values()}
        for target in targets:
            _closed(target, ("candidate_cid", "device", "inode", "bytes"))
            candidate = state["candidates"].get(target["candidate_cid"])
            _require(candidate is not None and not candidate["deleted"] and target["candidate_cid"] not in retained,
                     "unowned, collected or retained target cannot be collected")
            _require(all(type(target[key]) is int and target[key] >= 0 for key in ("device", "inode", "bytes"))
                     and target["bytes"] <= MAX_CANDIDATE_BYTES, "invalid target file identity")
        state["collection"] = data
        return dict(plan=data)
    if action == "complete_collection":
        _closed(data, ("collection_id", "plan"))
        plan = data["plan"]
        _require(state["collection"] == plan and plan["collection_id"] == data["collection_id"],
                 "collection completion does not match prepared intent")
        cids = [target["candidate_cid"] for target in plan["targets"]]
        for cid in cids:
            state["candidates"][cid]["deleted"] = True
        state["completed"][data["collection_id"]] = plan
        state["collection"] = None
        # The gate remains closed until a separate exact release command.
        return dict(collection_id=data["collection_id"], deleted_candidate_cids=cids)
    raise RetentionError("unknown retention action")


class ManagedCodebaseHistory:
    """Opt-in, bounded local owner; all public artifact accesses acquire leases.

    Leases have no expiry that silently authorizes deletion. After a process
    restart, the native exclusive registry owner may explicitly reconcile old
    generations. The owner lock is held across wrapper I/O and reader contexts;
    a same-process close cannot leave a supposedly dead wrapper writing later.
    """

    def __init__(self, registry, sink, root, *, create=False):
        _require(type(registry) is AutoencoderRegistry and type(sink) is IsolatedNativeDuckLakeHistory,
                 "exact native registry and DuckLake owners required")
        self.registry, self.sink = registry, sink
        raw = Path(root).absolute()
        _require(raw.resolve() == raw and ".." not in raw.parts, "managed root must have no aliases")
        if create:
            _require(not raw.exists(), "managed profile requires a new dedicated namespace")
            raw.mkdir(parents=True)
        _require(raw.is_dir() and not raw.is_symlink(), "managed profile root unavailable")
        self.root = raw
        if not create:
            _require(all((raw / name).is_dir() and not (raw / name).is_symlink()
                         for name in ("structured", "source")), "managed namespace is missing or aliased")
        self.cas = ImmutableCAS(raw, max_object_bytes=MAX_CANDIDATE_BYTES)
        identity = raw.stat()
        namespaces = {name: dict(device=(raw / name).stat().st_dev, inode=(raw / name).stat().st_ino)
                      for name in ("structured", "source")}
        self.descriptor = dict(schema=SCHEMA, database_path=str(registry.database_path),
            registry_artifact_root=str(registry.artifact_root), managed_root=str(raw),
            device=identity.st_dev, inode=identity.st_ino, namespaces=namespaces, history_id=sink.identity["history_id"],
            max_events=MAX_EVENTS, max_event_bytes=MAX_EVENT_BYTES,
            managed_artifacts="registered_source_history_candidate_envelopes_only")
        self.profile_id = content_identity(self.descriptor)
        if create:
            self._command(_derived(self.profile_id, "initialize"), "initialize", dict(descriptor=self.descriptor))
        self.state()

    def _boundary(self):
        self.registry._ensure_owner()
        _require(self.root.resolve() == self.root and self.root.is_dir()
                 and (self.root.stat().st_dev, self.root.stat().st_ino) == (self.descriptor["device"], self.descriptor["inode"]),
                 "managed root identity changed")
        for child in (self.cas.structured_root, self.cas.source_root):
            _require(child.is_dir() and not child.is_symlink() and child.resolve() == child
                     and dict(device=child.stat().st_dev, inode=child.stat().st_ino) == self.descriptor["namespaces"][child.name],
                     "managed namespace directory changed")
        with self.sink._mutex:
            self.sink._boundary()

    def _fold(self, cx):
        sizes = cx.execute("SELECT octet_length(encode(event_id)), octet_length(encode(event_data)) FROM autoencoder_control.events WHERE kind=? LIMIT ?", [KIND, MAX_EVENTS + 1]).fetchall()
        _require(len(sizes) <= MAX_EVENTS and all(type(n) is int and n <= MAX_EVENT_BYTES and identity_size <= 256 for identity_size, n in sizes),
                 "bounded retention event log exceeded")
        rows = cx.execute("SELECT event_id,event_data FROM autoencoder_control.events WHERE kind=? LIMIT ?", [KIND, MAX_EVENTS + 1]).fetchall()
        events = []
        for event_id, payload in rows:
            value = json.loads(payload)
            _closed(value, ("schema", "sequence", "previous_event_id", "operation_id", "request", "result"))
            _require(value["schema"] == SCHEMA and type(value["sequence"]) is int, "invalid retention log schema")
            events.append((value["sequence"], event_id, value))
        events.sort(key=lambda row: row[0])
        # Completeness matters: deleting the newest pin event cannot silently
        # roll back the retention fold while its native operation still exists.
        operation_sizes = cx.execute("SELECT octet_length(encode(operation_id)),octet_length(encode(receipt)) FROM autoencoder_control.operations LIMIT ?", [MAX_NATIVE_OPERATIONS + 1]).fetchall()
        _require(len(operation_sizes) <= MAX_NATIVE_OPERATIONS
                 and all(identity_size <= 256 and size <= MAX_NATIVE_RECEIPT_BYTES for identity_size, size in operation_sizes),
                 "native operation audit bound exceeded")
        controls = cx.execute("SELECT operation_id,payload_digest,receipt FROM autoencoder_control.operations WHERE json_extract_string(receipt, '$.command')=? LIMIT ?", [COMMAND, MAX_EVENTS + 1]).fetchall()
        _require({row[0] for row in controls} == {row[2]["operation_id"] for row in events}
                 and len(controls) == len(events), "retention event/operation completeness differs")
        operation_rows = {row[0]: row[1:] for row in controls}
        state, previous = _initial(), None
        for sequence, event_id, event in events:
            _require(sequence == (0 if previous is None else last_sequence + 1) and event["previous_event_id"] == previous,
                     "retention log sequence/chain differs")
            operation = event["operation_id"]
            request = event["request"]
            _closed(request, ("profile_id", "action", "data"))
            _require(request["profile_id"] == self.profile_id and event_id == content_identity(dict(operation_id=operation, kind=KIND, consumer="ducklake")),
                     "foreign retention event identity")
            result = _reduce(state, request["action"], request["data"], operation)
            _require(result == event["result"], "retention transition result differs")
            digest, encoded_receipt = operation_rows[operation]
            _require(len(encoded_receipt.encode()) <= MAX_EVENT_BYTES
                     and digest == self.registry._command_digest(operation, COMMAND, request),
                     "retention operation command/payload binding differs")
            receipt = json.loads(encoded_receipt)
            expected = dict(schema=REGISTRY_SCHEMA, operation_id=operation, command=COMMAND, admitted=False,
                            profile_id=self.profile_id, event_id=event_id, **result)
            _require(receipt == expected, "retention operation binding differs")
            previous, last_sequence = event_id, sequence
        _require(state["descriptor"] is None or state["descriptor"] == self.descriptor,
                 "managed history owner descriptor differs")
        return state, previous, len(events)

    def state(self):
        self._boundary()
        with self.registry._transaction() as cx:
            value, _, _ = self._fold(cx)
            _require(value["descriptor"] == self.descriptor, "missing durable retention profile")
        return _copy(value)

    def _command(self, operation, action, data):
        _id(operation)
        request = dict(profile_id=self.profile_id, action=action, data=_copy(data))
        _require(len(canonical_json_bytes(request)) <= 32 * 1024, "retention command byte bound exceeded")
        with self.registry._lock:
            self._boundary()
            def apply(cx):
                state, previous, sequence = self._fold(cx)
                _require(sequence < MAX_EVENTS, "retention log event capacity exhausted")
                result = _reduce(state, action, request["data"], operation)
                # Keep enough durable slots to finish already admitted work.
                # In particular, physical unlink must never consume the last
                # slot needed for completion and release of its persisted gate.
                reserved = len(state["leases"]) + int(state["collection"] is not None) + int(state["gate"] is not None)
                native_count = cx.execute("SELECT count(*) FROM (SELECT 1 FROM autoencoder_control.operations LIMIT ?)", [MAX_NATIVE_OPERATIONS + 1]).fetchone()[0]
                _require(sequence + 1 + reserved <= MAX_EVENTS
                         and native_count + 1 + reserved <= MAX_NATIVE_OPERATIONS,
                         "retention capacity must reserve lease/collection completion slots")
                event = dict(schema=SCHEMA, sequence=sequence, previous_event_id=previous,
                             operation_id=operation, request=request, result=result)
                _require(len(canonical_json_bytes(event)) <= MAX_EVENT_BYTES, "retention event byte bound exceeded")
                event_id = self.registry._event(cx, operation, KIND, event)
                return dict(profile_id=self.profile_id, event_id=event_id, **result)
            return self.registry._mutate(operation, COMMAND, request, apply)

    def acquire(self, operation, *, kind):
        result = self._command(operation, "acquire", dict(kind=kind, owner_generation=self.registry.owner_generation))
        lease = result["lease"]
        _require(self.state()["leases"].get(lease["lease_id"]) == lease, "historical lease is no longer active")
        return lease

    def release(self, operation, lease):
        _require(type(lease) is dict and lease.get("owner_generation") == self.registry.owner_generation,
                 "stale owner cannot release lease")
        return self._command(operation, "release", dict(lease=lease))

    def recover_abandoned_leases(self, operation):
        return self._command(operation, "recover_leases", dict(owner_generation=self.registry.owner_generation))

    def _read(self, cid, *, missing_ok=False):
        validate_cid(cid, codecs={"dag-json"})
        path = self.cas.path_for(cid)
        _require(path.parent.resolve() == path.parent and not path.parent.is_symlink(), "candidate path alias")
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        try:
            fd = os.open(path, flags)
        except FileNotFoundError:
            if missing_ok:
                return None
            raise
        try:
            info = os.fstat(fd)
            _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= MAX_CANDIDATE_BYTES,
                     "candidate must be one bounded regular owned file")
            raw = os.read(fd, MAX_CANDIDATE_BYTES + 1)
            value = json.loads(raw)
            _candidate(value, self.profile_id)
            _require(raw == canonical_dag_json_bytes(value) and cid_for_structured(value) == cid,
                     "candidate bytes or content identity differ")
            after = os.stat(path, follow_symlinks=False)
            _require((after.st_dev, after.st_ino, after.st_size, after.st_nlink) == (info.st_dev, info.st_ino, info.st_size, 1),
                     "candidate file identity changed during read")
            return value, dict(candidate_cid=cid, device=info.st_dev, inode=info.st_ino, bytes=info.st_size)
        finally:
            os.close(fd)

    def stage(self, discovery, record_cid, *, operation):
        """Create an immutable, source-owner-reconstructed history candidate."""
        with self.registry._lock:
            state = self.state()
            existing = [(cid, row) for cid, row in state["candidates"].items()
                        if row["envelope"]["stage_operation_id"] == operation]
            if existing:
                _require(len(existing) == 1 and existing[0][1]["envelope"]["request"]["record_cid"] == record_cid,
                         "stage operation reused for another source")
                return dict(candidate_cid=existing[0][0], record_cid=record_cid,
                            historical_replay=True, candidate_deleted=existing[0][1]["deleted"],
                            current_artifact_availability_verified=False)
            lease = self.acquire(_derived(operation, "producer"), kind="producer")
            try:
                request = prepare_codebase_history_request(discovery, record_cid)
                envelope = dict(schema=CANDIDATE_SCHEMA, profile_id=self.profile_id,
                                stage_operation_id=_id(operation), request=request)
                _candidate(envelope, self.profile_id)
                cid = self.cas.put(envelope)
                self._read(cid)
                self._command(_derived(operation, "register"), "register_candidate",
                              dict(lease=lease, candidate_cid=cid, envelope=envelope))
                return dict(candidate_cid=cid, record_cid=record_cid,
                            historical_replay=False, currently_available=True)
            finally:
                self.release(_derived(operation, "producer-release"), lease)

    @contextmanager
    def read(self, candidate_cid, *, operation):
        with self.registry._lock:
            lease = self.acquire(_derived(operation, "reader"), kind="reader")
            try:
                state = self.state()
                candidate = state["candidates"].get(candidate_cid)
                _require(candidate is not None and not candidate["deleted"], "candidate unregistered or collected")
                value, _ = self._read(candidate_cid)
                _require(value == candidate["envelope"], "candidate differs from native registration")
                yield _copy(value)
            finally:
                self.release(_derived(operation, "reader-release"), lease)

    def deliver_and_pin(self, discovery, candidate_cid, *, operation, source_id, output_directory):
        journal_root = Path(output_directory).absolute()
        _require(journal_root.resolve() == journal_root, "delivery journal root alias")
        journal_root.mkdir(parents=True, exist_ok=True)
        with self.read(candidate_cid, operation=operation) as envelope:
            registration = dict(operation_id=_derived(operation, "history-register"), request=envelope["request"])
            register_codebase_history_request(self.registry, discovery, registration["operation_id"], registration["request"])
            # Retention-control events share the existing outbox. Drain bounded
            # frozen batches with the same native worker and independent journals.
            for batch in range(MAX_EVENTS // 10 + 2):
                status = inspect_codebase_history(self.registry, self.sink, source_id=source_id, registrations=[registration])
                if status["pending_acknowledgements"] == 0:
                    break
                deliver_codebase_history(self.registry, self.sink, source_id=source_id,
                    output_directory=journal_root / str(batch), limit=10)
            _require(status["pending_acknowledgements"] == 0, "bounded history delivery did not reach candidate")
            row = status["records"][0]
            snapshot = dict(history_id=status["history_id"], source_id=source_id,
                            event_id=row["event_id"], snapshot_id=row["snapshot_id"])
            pin = self._command(_derived(operation, "pin"), "pin", dict(pin_id=operation,
                candidate_cid=candidate_cid, registration=registration, snapshot=snapshot))
            return dict(candidate_cid=candidate_cid, pin=pin, inspection=status)

    def inspect_pins(self):
        """Re-read actual native retained snapshots for each durable live pin."""
        with self.registry._lock:
            state = self.state()
            results = []
            for pin in state["pins"].values():
                status = inspect_codebase_history(self.registry, self.sink,
                    source_id=pin["snapshot"]["source_id"], registrations=[pin["registration"]])
                row = status["records"][0]
                _require(row["snapshot_retained"] and row["snapshot_id"] == pin["snapshot"]["snapshot_id"]
                         and row["event_id"] == pin["snapshot"]["event_id"], "pinned native snapshot unavailable")
                value, _ = self._read(pin["candidate_cid"])
                _require(value == state["candidates"][pin["candidate_cid"]]["envelope"], "pinned artifact unavailable")
                results.append(dict(pin_id=pin["pin_id"], candidate_cid=pin["candidate_cid"], snapshot=pin["snapshot"]))
            return dict(profile_id=self.profile_id, pins=results, durable_reader_pin=True,
                        scope="native_history_snapshots_and_registered_candidate_artifacts",
                        source_observed_live=False, proof_authority=False)

    def unpin(self, operation, pin_id):
        return self._command(operation, "unpin", dict(pin_id=pin_id))

    def quiesce(self, operation):
        return self._command(operation, "quiesce", {})["gate_id"]

    def unquiesce(self, operation, gate_id):
        return self._command(operation, "unquiesce", dict(gate_id=gate_id))

    def collect(self, *, operation, gate_id, candidate_cids):
        """Delete only explicit owned/unpinned candidates under durable intent.

        A missing file resolves only an already durable identical prepare intent.
        Recovery repeats that plan after native owner restart. It never marks or
        sweeps arbitrary CAS files, source artifacts, or DuckLake data/snapshots.
        """
        _require(type(candidate_cids) in (list, tuple) and 1 <= len(candidate_cids) <= MAX_TARGETS,
                 "bounded explicit candidate collection required")
        cids = sorted(candidate_cids)
        _require(cids == sorted(set(cids)), "duplicate collection target")
        with self.registry._lock:
            state = self.state()
            old = state["completed"].get(operation)
            if old is not None:
                _require(old["gate_id"] == gate_id and [v["candidate_cid"] for v in old["targets"]] == cids,
                         "collection operation reused with different payload")
                return dict(collection_id=operation, deleted_candidate_cids=cids, historical_replay=True)
            plan = state["collection"]
            if plan is not None:
                _require(plan["collection_id"] == operation and plan["gate_id"] == gate_id
                         and [v["candidate_cid"] for v in plan["targets"]] == cids,
                         "pending collection differs from exact operation/payload")
            else:
                _require(state["gate"] == gate_id and not state["leases"], "exact quiescence gate required")
                targets = [self._read(cid)[1] for cid in cids]
                plan = dict(gate_id=gate_id, collection_id=_id(operation), targets=targets)
                self._command(_derived(operation, "prepare"), "prepare_collection", plan)
            for target in plan["targets"]:
                self._boundary()
                current = self._read(target["candidate_cid"], missing_ok=True)
                if current is not None:
                    _require(current[1] == target, "prepared collection target was replaced")
                    self._unlink_prepared(target)
            self._boundary()
            _require(all(self._read(cid, missing_ok=True) is None for cid in cids), "collection target still exists")
            self._command(_derived(operation, "complete"), "complete_collection", dict(collection_id=operation, plan=plan))
            return dict(collection_id=operation, deleted_candidate_cids=cids, historical_replay=False)

    def _unlink_prepared(self, target):
        path = self.cas.path_for(target["candidate_cid"])
        # Namespace ownership excludes hostile writers. Directory descriptors and
        # nofollow checks still reject path aliases and accidental rebinding.
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
            _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                     and (info.st_dev, info.st_ino, info.st_size) == (target["device"], target["inode"], target["bytes"]),
                     "prepared unlink target identity differs")
            os.unlink(path.name, dir_fd=fd)
            os.fsync(fd)
        finally:
            os.close(fd)
