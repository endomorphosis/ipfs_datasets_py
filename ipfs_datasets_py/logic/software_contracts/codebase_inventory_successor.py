"""Bounded structural source deltas between two complete native publications.

A retained entry denotes exact captured inventory identity, not equivalent
behavior. Removed means absent from the current complete capture, including
Git selection changes; it does not establish physical filesystem absence.
Opaque members never establish byte equality. AST identities bind
the entire snapshot and can change when another file changes. This protocol
does not advance a model/scan, reuse numerical rows, open a model registry, or
run inference/training. Receiving makes sequential fresh observations; it does
not lock the checkout or attest producer execution. Serialized admission
estimates do not bound RSS.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import time

from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog, CodebaseHead, CodebasePublicationReceipt
from . import codebase_inventory_resume as scan
from .cache import ImmutableCAS
from .codebase_ir import RepositoryCodebaseIndex
from .codebase_resources import acquire_codebase_resources
from .content import canonical_dag_json_bytes, cid_for_structured
from .duckdb_ingest import DuckDBASTIngestor
from .semantic_index.snapshot import SnapshotEntry

SCHEMA = "codebase-inventory-source-delta@1"
_MIB = 1024 * 1024
_CLASSES = ("retained", "changed", "added", "removed")
_COMPARISONS = ("equal", "different", "unavailable")
_FIELDS = {"schema", "previous_head", "current_head", "previous_publication_receipt",
    "current_publication_receipt", "previous_membership_cid", "current_membership_cid",
    "capture_policy", "ledger", "coverage", "limits", "optimized", "implementation",
    "authority", "numerical_reuse", "model_advanced", "removal_scope", "physical_absence_verified"}


class CodebaseSourceDeltaError(ValueError):
    """A bounded structural transition or independently replayed delta differs."""


def _require(condition, message):
    if not condition:
        raise CodebaseSourceDeltaError(message)


@dataclass(frozen=True, slots=True)
class CodebaseSourceDeltaLimits:
    max_inventory_entries: int = 1024
    max_union_entries: int = 2048
    max_file_bytes: int = 64 * 1024
    max_manifest_bytes: int = 4 * _MIB
    max_delta_bytes: int = 8 * _MIB

    def __post_init__(self):
        for name, ceiling in zip(self.__dataclass_fields__, (1024, 2048, 65536, 4 * _MIB, 8 * _MIB)):
            scan._int(getattr(self, name), ceiling, 1)

    def to_dict(self):
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value):
        scan._closed(value, cls.__dataclass_fields__, "source delta limits")
        return cls(**value)


def _policy(snapshot):
    return {"max_entries": snapshot.max_entries, "max_file_bytes": snapshot.max_file_bytes,
            "exclusions": list(snapshot.exclusions)}


def _side_shape(value):
    if value is None:
        return None
    scan._closed(value, {"entry", "member"}, "source delta member")
    entry = SnapshotEntry.from_dict(value["entry"])
    _require(scan._wire(entry.to_dict()) == scan._wire(value["entry"]), "canonical exact snapshot entry required")
    member = value["member"]
    scan._member_shape(member)
    _require(all(member[key] == expected for key, expected in {
        "source_key": entry.source_key, "path": entry.path, "raw_path_hex": entry.raw_path_hex,
        "entry_cid": entry.entry_cid, "source_cid": entry.source_cid,
        "source_size_bytes": entry.size_bytes, "opaque_reason": entry.opaque_reason}.items()),
        "entry/native member identity differs")
    return entry


def _classification(previous, current):
    if previous is None:
        return "added"
    if current is None:
        return "removed"
    return "retained" if previous["entry"]["entry_cid"] == current["entry"]["entry_cid"] else "changed"


def _comparison(previous, current, *, ast=False):
    if previous is None or current is None:
        return "unavailable"
    if ast:
        left, right = previous["member"]["ast_cid"], current["member"]["ast_cid"]
        if left is None or right is None:
            return "unavailable"
    else:
        # An opaque Git entry may carry a blob locator; its bytes were not
        # admitted/read by this protocol and must remain unknown.
        if previous["entry"]["opaque_reason"] is not None or current["entry"]["opaque_reason"] is not None:
            return "unavailable"
        left = (previous["entry"]["source_cid"], previous["entry"]["size_bytes"])
        right = (current["entry"]["source_cid"], current["entry"]["size_bytes"])
    return "equal" if left == right else "different"


def _coverage(ledger):
    return {"previous_entries": sum(row["previous"] is not None for row in ledger),
        "current_entries": sum(row["current"] is not None for row in ledger), "union_entries": len(ledger),
        "classifications": {name: sum(row["classification"] == name for row in ledger) for name in _CLASSES},
        "source_bytes_comparisons": {name: sum(row["source_bytes_comparison"] == name for row in ledger) for name in _COMPARISONS},
        "ast_identity_comparisons": {name: sum(row["ast_identity_comparison"] == name for row in ledger) for name in _COMPARISONS}}


def _shape(value):
    scan._closed(value, _FIELDS, "source delta")
    _require(value["schema"] == SCHEMA and type(value["optimized"]) is bool, "source delta profile differs")
    _require(value["numerical_reuse"] is False and value["model_advanced"] is False,
             "source delta cannot advance models or reuse numerical results")
    _require(value["physical_absence_verified"] is False
             and value["removal_scope"] == "absent_from_current_complete_capture",
             "capture removal cannot establish physical absence")
    scan._authority(value["authority"])
    limits = CodebaseSourceDeltaLimits.from_dict(value["limits"])
    previous, current = scan._head(value["previous_head"]), scan._head(value["current_head"])
    _require(previous.repository_id == current.repository_id and current.generation == previous.generation + 1,
             "immediate same-repository successor required")
    for key, head in (("previous_publication_receipt", previous), ("current_publication_receipt", current)):
        receipt = CodebasePublicationReceipt.from_dict(value[key])
        _require(scan._wire(receipt.to_dict()) == scan._wire(value[key]) and receipt.head == head,
                 "canonical publication receipt/head differs")
        _require(len(canonical_dag_json_bytes(value[key])) <= 64 * 1024, "bounded native publication receipt required")
    _require(CodebasePublicationReceipt.from_dict(value["current_publication_receipt"]).previous_head == previous,
             "publication does not directly follow the previous head")
    policy = value["capture_policy"]
    scan._closed(policy, {"max_entries", "max_file_bytes", "exclusions"}, "source capture policy")
    scan._int(policy["max_entries"], limits.max_inventory_entries, 1)
    scan._int(policy["max_file_bytes"], limits.max_file_bytes, 1)
    exclusions = policy["exclusions"]
    _require(type(exclusions) is list and len(exclusions) <= 1024
             and all(type(item) is str and 0 < len(item.encode("utf-8")) <= 8192 for item in exclusions)
             and exclusions == sorted(set(exclusions)), "canonical bounded capture exclusions required")
    ledger = value["ledger"]
    _require(type(ledger) is list and len(ledger) <= limits.max_union_entries, "bounded full raw-path union required")
    previous_members, current_members, keys = [], [], []
    for row in ledger:
        scan._closed(row, {"source_key", "classification", "previous", "current", "source_bytes_comparison",
                          "ast_identity_comparison"}, "source delta row")
        old, new = _side_shape(row["previous"]), _side_shape(row["current"])
        _require(old is not None or new is not None, "delta row cannot omit both members")
        entry = old if old is not None else new
        _require(row["source_key"] == entry.source_key and (new is None or new.source_key == entry.source_key),
                 "raw path join differs")
        keys.append(entry.raw_path_hex)
        _require(row["classification"] == _classification(row["previous"], row["current"])
                 and row["source_bytes_comparison"] == _comparison(row["previous"], row["current"])
                 and row["ast_identity_comparison"] == _comparison(row["previous"], row["current"], ast=True),
                 "native identity classification/comparison differs")
        for side, entries in ((row["previous"], previous_members), (row["current"], current_members)):
            if side is not None:
                if side["entry"]["opaque_reason"] is None:
                    scan._int(side["entry"]["size_bytes"], policy["max_file_bytes"])
                entries.append(side["member"])
    _require(keys == sorted(set(keys)), "union raw paths duplicated or reordered")
    _require(len(previous_members) <= policy["max_entries"] and len(current_members) <= policy["max_entries"],
             "complete inventory exceeds capture bounds")
    for key, members in (("previous_membership_cid", previous_members), ("current_membership_cid", current_members)):
        scan._cid(value[key])
        _require(value[key] == cid_for_structured(members), "full inventory membership digest differs")
    _require(scan._wire(value["coverage"]) == scan._wire(_coverage(ledger)), "complete union coverage differs")
    scan._implementation_shape(value["implementation"])


@dataclass(frozen=True, slots=True)
class CodebaseSourceDeltaRecord:
    artifact_cid: str
    _payload: bytes

    def __post_init__(self):
        _require(type(self._payload) is bytes and len(self._payload) <= 8 * _MIB, "bounded immutable source delta required")
        value = json.loads(self._payload)
        _require(canonical_dag_json_bytes(value) == self._payload and cid_for_structured(value) == self.artifact_cid,
                 "canonical source delta CID/bytes differ")
        _shape(value)
        _require(len(self._payload) <= value["limits"]["max_delta_bytes"], "source delta output bound exceeded")

    def to_dict(self):
        return json.loads(self._payload)

    @classmethod
    def from_dict(cls, artifact_cid, value):
        return cls(artifact_cid, canonical_dag_json_bytes(value))


def load_codebase_source_delta(artifacts, artifact_cid):
    _require(type(artifacts) is ImmutableCAS, "exact immutable source artifact owner required")
    scan._cid(artifact_cid)
    scan._artifact_size(artifacts, artifact_cid, 8 * _MIB)
    return CodebaseSourceDeltaRecord.from_dict(artifact_cid, artifacts.get(artifact_cid))


def _implementation():
    files = dict(scan._implementation()["files"])
    for name in (__name__, "ipfs_datasets_py.duckdb_control.codebase_catalog",
                 "ipfs_datasets_py.logic.software_contracts.codebase_resources",
                 "ipfs_datasets_py.logic.software_contracts.duckdb_ingest",
                 "ipfs_datasets_py.logic.software_contracts.semantic_index.scanner"):
        module = importlib.import_module(name)
        files[name] = hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
    return {"files": files, "sha256": scan.features.digest(files),
            "scope": "listed_local_files_only_not_execution_attestation"}


def _owners(index):
    _require(type(index) is RepositoryCodebaseIndex and type(index.ingestor) is DuckDBASTIngestor
             and type(index.artifacts) is ImmutableCAS and type(index.catalog) is CodebaseCatalog
             and index.catalog.store is index.ingestor.store and index.catalog.artifacts is index.artifacts,
             "exact native structural source/CAS owner required")
    index.catalog._ensure_owner()
    scan._cas(index.artifacts)
    return (os.getpid(), id(index), id(index.ingestor), id(index.ingestor.store), id(index.catalog),
            id(index.catalog.store._connection), id(index.catalog.store._lock), id(index.artifacts),
            str(index.artifacts.root.resolve()))


@contextmanager
def _scope(index, *, scheduler, parent_lease, cancel_event, admission_timeout_seconds, timeout_seconds, memory_mb):
    owner = _owners(index)
    _require(type(timeout_seconds) in {int, float} and math.isfinite(timeout_seconds) and 0 < timeout_seconds <= 600,
             "finite bounded source delta deadline required")
    _require(type(admission_timeout_seconds) in {int, float} and math.isfinite(admission_timeout_seconds)
             and 0 <= admission_timeout_seconds <= 600, "finite bounded admission timeout required")
    scan._int(memory_mb, 65536, 1024)
    # Full current snapshot <=64 MiB, two <=4 MiB manifests, <=8 MiB
    # record/canonical transient and one bounded AST/source are phased with
    # the <=32 MiB batch relational replay. No numerical request/chain/cache.
    _require(128 * _MIB <= memory_mb * _MIB // 4, "serialized source retention exceeds reservation")
    deadline = time.monotonic() + timeout_seconds
    with acquire_codebase_resources(scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            timeout_seconds=min(admission_timeout_seconds, timeout_seconds), memory_mb=memory_mb) as lease:
        signal = lease.combined_cancellation_signal(cancel_event)
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import LeaseCancelledError, LeaseTimeoutError
        def remaining():
            if signal.is_set():
                raise LeaseCancelledError("source delta cancelled")
            seconds = deadline - time.monotonic()
            if seconds <= 0:
                raise LeaseTimeoutError("source delta deadline exceeded")
            return seconds
        remaining()
        yield remaining
        remaining()
        _require(_owners(index) == owner, "source owner changed during source delta operation")


def _scan_limits(limits):
    return scan.CodebaseScanResumeLimits(max_inventory_entries=limits.max_inventory_entries,
        max_file_bytes=limits.max_file_bytes, max_manifest_bytes=limits.max_manifest_bytes)


def _historical(index, head, limits, remaining, optimized):
    """Replay captured history, without treating invalidated SQL ASTs as live."""
    scan._artifact_size(index.artifacts, head.manifest_cid, limits.max_manifest_bytes)
    manifest = index.load(head.manifest_cid)
    snapshot = manifest.snapshot
    snapshot_cid = snapshot.snapshot_cid
    _require(manifest.cid == head.manifest_cid and snapshot.repository_id == head.repository_id
             and snapshot_cid == head.snapshot_cid and manifest.ast_revision_id == head.ast_revision_id,
             "historical source publication binding differs")
    _require(snapshot.max_entries <= limits.max_inventory_entries and snapshot.max_file_bytes <= limits.max_file_bytes,
             "historical capture exceeds source delta profile")
    receipt = scan._receipt(index, head, remaining)
    units = {unit.source_key: unit for unit in manifest.units}
    bounds = _scan_limits(limits)
    for entry in snapshot.entries:
        if not entry.is_opaque:
            scan._int(entry.size_bytes, snapshot.max_file_bytes)
        raw, ast = scan._member_native(index, manifest, entry, units[entry.source_key], bounds, remaining,
            snapshot_cid=snapshot_cid if optimized else None)
        del raw, ast
    remaining()
    _require(manifest.cid == head.manifest_cid and snapshot.snapshot_cid == head.snapshot_cid,
             "historical manifest changed during source replay")
    return manifest, receipt


def _ledger(previous, current):
    def sides(manifest):
        members = {row["source_key"]: row for row in scan._members(manifest)}
        return {entry.source_key: {"entry": entry.to_dict(), "member": members[entry.source_key]}
                for entry in manifest.snapshot.entries}
    old, new = sides(previous), sides(current)
    return [{"source_key": key, "classification": _classification(old.get(key), new.get(key)),
        "previous": old.get(key), "current": new.get(key),
        "source_bytes_comparison": _comparison(old.get(key), new.get(key)),
        "ast_identity_comparison": _comparison(old.get(key), new.get(key), ast=True)}
        for key in sorted(set(old) | set(new))]


def _value(previous, current, previous_receipt, current_receipt, limits, optimized, implementation):
    _require(current_receipt.previous_head == previous_receipt.head, "native publication is not an immediate successor")
    _require(scan._wire(_policy(previous.snapshot)) == scan._wire(_policy(current.snapshot)),
             "capture policy changed; source absence cannot be inferred")
    ledger = _ledger(previous, current)
    _require(len(ledger) <= limits.max_union_entries, "union exceeds source delta bound")
    return {"schema": SCHEMA, "previous_head": previous_receipt.head.to_dict(), "current_head": current_receipt.head.to_dict(),
        "previous_publication_receipt": previous_receipt.to_dict(), "current_publication_receipt": current_receipt.to_dict(),
        "previous_membership_cid": cid_for_structured(scan._members(previous)),
        "current_membership_cid": cid_for_structured(scan._members(current)), "capture_policy": _policy(current.snapshot),
        "ledger": ledger, "coverage": _coverage(ledger), "limits": limits.to_dict(), "optimized": optimized,
        "implementation": implementation, "authority": dict(scan._FALSE), "numerical_reuse": False, "model_advanced": False,
        "removal_scope": "absent_from_current_complete_capture", "physical_absence_verified": False}


def _observe(index, repository, previous_head, expected_head, limits, remaining, memory_mb, optimized, implementation):
    previous, old_receipt = _historical(index, previous_head, limits, remaining, optimized)
    current, new_receipt = scan._observe(index, repository, expected_head, _scan_limits(limits), remaining,
                                         memory_mb, optimized=optimized)
    value = _value(previous, current, old_receipt, new_receipt, limits, optimized, implementation)
    remaining()
    _require(previous.cid == previous_head.manifest_cid and current.cid == expected_head.manifest_cid,
             "source manifests changed during delta construction")
    return value


def build_current_codebase_source_delta(index, repository, *, previous_head, expected_head, limits=None,
        optimized=True, scheduler=None, parent_lease=None, cancel_event=None, admission_timeout_seconds=30.0,
        timeout_seconds=120.0, memory_mb=1024):
    """Persist a complete source delta for an already-published immediate head.

    Preparation/publication remains the explicit existing prepare_current API.
    This observation never creates a scan root or an updated model.
    """
    _require(type(previous_head) is CodebaseHead and type(expected_head) is CodebaseHead
             and type(optimized) is bool, "exact native heads and opt-out required")
    limits = CodebaseSourceDeltaLimits() if limits is None else limits
    _require(type(limits) is CodebaseSourceDeltaLimits, "exact source delta limits required")
    with _scope(index, scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            admission_timeout_seconds=admission_timeout_seconds, timeout_seconds=timeout_seconds, memory_mb=memory_mb) as remaining:
        implementation = _implementation()
        value = _observe(index, repository, previous_head, expected_head, limits, remaining, memory_mb, optimized, implementation)
        record = CodebaseSourceDeltaRecord.from_dict(cid_for_structured(value), value)
        remaining()
        _require(index.artifacts.put(value) == record.artifact_cid, "durable source delta publication differs")
        _receive(record, index, repository, remaining, memory_mb)
        return record


def _receive(record, index, repository, remaining, memory_mb):
    value = record.to_dict()
    implementation = _implementation()
    _require(scan._wire(value["implementation"]) == scan._wire(implementation), "source delta producer changed")
    _require(load_codebase_source_delta(index.artifacts, record.artifact_cid)._payload == record._payload,
             "durable source delta bytes differ")
    expected = _observe(index, repository, scan._head(value["previous_head"]), scan._head(value["current_head"]),
        CodebaseSourceDeltaLimits.from_dict(value["limits"]), remaining, memory_mb, value["optimized"], implementation)
    _require(canonical_dag_json_bytes(expected) == record._payload, "fresh native source delta ledger differs")
    remaining()
    _require(load_codebase_source_delta(index.artifacts, record.artifact_cid)._payload == record._payload
             and scan._wire(_implementation()) == scan._wire(implementation), "closing source delta bytes/producer differ")
    # All durable-record/pin work precedes this independent final source/SQL
    # observation. A same-head checkout/CAS mutation in those earlier stages
    # must not escape by checking only the catalog head.
    closing = _observe(index, repository, scan._head(value["previous_head"]), scan._head(value["current_head"]),
        CodebaseSourceDeltaLimits.from_dict(value["limits"]), remaining, memory_mb, value["optimized"], implementation)
    _require(canonical_dag_json_bytes(closing) == record._payload, "closing native source delta ledger differs")
    return record


def validate_current_codebase_source_delta(record, index, repository, *, scheduler=None, parent_lease=None,
        cancel_event=None, admission_timeout_seconds=30.0, timeout_seconds=120.0, memory_mb=1024):
    """One fresh receiving operation: exact retained bytes and native sources.

    No reusable freshness token is returned. Each later use needs another
    receiving operation; historical deltas cannot authorize current planning.
    """
    _require(type(record) is CodebaseSourceDeltaRecord, "exact immutable source delta required")
    with _scope(index, scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            admission_timeout_seconds=admission_timeout_seconds, timeout_seconds=timeout_seconds, memory_mb=memory_mb) as remaining:
        return _receive(record, index, repository, remaining, memory_mb)


__all__ = ["CodebaseSourceDeltaError", "CodebaseSourceDeltaLimits", "CodebaseSourceDeltaRecord",
    "build_current_codebase_source_delta", "validate_current_codebase_source_delta", "load_codebase_source_delta"]
