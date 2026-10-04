"""Operation-owned captured inventory and lossless compact target transport.

This additive profile reads a published structural inventory once.  It does
not observe a working tree or grant current-source, proof, or model authority.
The coordinator owns entry and completion fences.  Native target preparation
and receiver replay continue to use ``codebase_ir_targets`` unchanged.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import json
from types import MappingProxyType
from typing import Any

from .ast_ir import ASTRecord
from .cache import ImmutableCAS
from .codebase_ir import CodebaseIRManifest, CodebaseUnit, RepositoryCodebaseIndex
from .codebase_ir_targets import (
    CODEBASE_TARGET_SCHEMA, CodebaseTargetError, CodebaseTargetLimits,
    _binding, _prepare_bound, _specs,
)
from .content import canonical_dag_json_bytes, cid_for_bytes, cid_for_structured
from .duckdb_ast_store import DUCKDB_AST_STORE_SCHEMA_VERSION, classify_parse_status
from .semantic_index.snapshot import SnapshotEntry
from ..formalization.autoencoder.domain_targets import DomainTargetEnvelope
from ..software_verification.pipeline import ContractSpec

INVENTORY_SEAL_SCHEMA = "codebase-ir-owned-inventory-seal@1"
SHARED_INVENTORY_SCHEMA = "codebase-ir-shared-target-inventory@1"
COMPACT_TARGET_SCHEMA = "codebase-ir-compact-native-target@1"
_MIB = 1024 * 1024
_SHARED_FIELDS = frozenset({"schema", "head", "manifest", "publication_receipt", "shared_sha256"})
_COMPACT_FIELDS = frozenset({"schema", "shared_sha256", "target_sha256", "source_digest",
                             "detached_target", "compact_sha256"})
_FAILURE_FIELDS = frozenset({"schema", "kind", "source_cid", "path", "repository_id",
                             "revision", "code", "message", "language"})
_VALIDATED_TOKEN = object()


class CodebaseInventoryError(CodebaseTargetError):
    """A complete bounded inventory or lossless transport binding is invalid."""


@dataclass(frozen=True, slots=True)
class CodebaseInventoryLimits:
    """Hard serialized-byte bounds; these do not promise a process RSS limit."""

    max_entries: int = 256
    max_source_bytes: int = 64 * 1024
    max_total_source_bytes: int = 16 * _MIB
    max_ast_bytes: int = 4 * _MIB
    max_total_ast_bytes: int = 16 * _MIB
    max_manifest_bytes: int = 16 * _MIB
    max_receipt_bytes: int = 64 * 1024
    max_shared_bytes: int = 16 * _MIB
    max_target_bytes: int = 4 * _MIB

    def __post_init__(self) -> None:
        ceilings = (256, 64 * 1024, 16 * _MIB, 4 * _MIB, 16 * _MIB,
                    16 * _MIB, 64 * 1024, 16 * _MIB, 4 * _MIB)
        for name, ceiling in zip(self.__dataclass_fields__, ceilings):
            value = getattr(self, name)
            if type(value) is not int or not 0 < value <= ceiling:
                raise CodebaseInventoryError(f"{name} exceeds the bounded inventory profile")

    def to_dict(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(slots=True)
class InventoryCounters:
    manifest_reads: int = 0
    publication_receipt_reads: int = 0
    source_cas_reads: int = 0
    ast_cas_reads: int = 0
    manifest_bytes: int = 0
    publication_receipt_bytes: int = 0
    source_bytes: int = 0
    ast_bytes: int = 0
    target_preparation_attempts: int = 0
    target_preparations: int = 0
    prepared_target_bytes: int = 0
    shared_envelope_creations: int = 0
    shared_transport_bytes: int = 0
    compact_targets: int = 0
    full_target_transport_bytes: int = 0
    compact_target_transport_bytes: int = 0

    def to_dict(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class InventoryMember:
    entry: SnapshotEntry
    unit: CodebaseUnit
    raw: bytes | None
    ast_record: ASTRecord | None
    ast_payload: bytes | None
    disposition: str
    frontiers: tuple[Mapping[str, Any], ...]

    @property
    def path(self) -> str:
        return self.entry.path

    @property
    def source_key(self) -> str:
        return self.entry.source_key

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "source_key": self.source_key,
                "entry_cid": self.entry.entry_cid, "source_cid": self.entry.source_cid,
                "ast_cid": self.unit.ast_cid, "parse_status": self.unit.parse_status,
                "disposition": self.disposition,
                "frontiers": [dict(row) for row in self.frontiers],
                "captured_source_bytes": None if self.raw is None else len(self.raw),
                "captured_ast_bytes": None if self.ast_payload is None else len(self.ast_payload),
                "native_ast_record": self.ast_record is not None,
                "raw_capture_required": not self.entry.is_opaque}


@dataclass(frozen=True, slots=True)
class InventorySeal:
    """An in-process operation record; its lifetime is owned by the caller."""

    head: Any
    manifest: CodebaseIRManifest
    receipt: Any
    members: tuple[InventoryMember, ...]
    entries_by_path: Mapping[str, SnapshotEntry]
    entries_by_source_key: Mapping[str, SnapshotEntry]
    units_by_source_key: Mapping[str, CodebaseUnit]
    members_by_source_key: Mapping[str, InventoryMember]
    limits: CodebaseTargetLimits
    inventory_limits: CodebaseInventoryLimits
    counters: InventoryCounters = field(compare=False)

    def member(self, entry_or_source_key: SnapshotEntry | str) -> InventoryMember:
        if type(entry_or_source_key) is SnapshotEntry:
            found = self.members_by_source_key.get(entry_or_source_key.source_key)
            if found is None or found.entry != entry_or_source_key:
                raise CodebaseInventoryError("entry does not belong to this complete inventory")
            return found
        if type(entry_or_source_key) is not str:
            raise CodebaseInventoryError("native SnapshotEntry, captured path or source_key required")
        found = self.members_by_source_key.get(entry_or_source_key)
        if found is None:
            entry = self.entries_by_path.get(entry_or_source_key)
            found = None if entry is None else self.members_by_source_key[entry.source_key]
        if found is None:
            raise CodebaseInventoryError("requested member is outside the complete inventory")
        return found


def _wire(value: Any, maximum: int, what: str) -> bytes:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError, UnicodeError) as exc:
        raise CodebaseInventoryError(f"{what} requires bounded finite JSON") from exc
    if len(raw) > maximum:
        raise CodebaseInventoryError(f"{what} exceeds its serialized byte bound")
    return raw


def _digest(value: Any, maximum: int, what: str) -> str:
    return hashlib.sha256(_wire(value, maximum, what)).hexdigest()


def _sha(value: Any, what: str) -> str:
    if (type(value) is not str or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)):
        raise CodebaseInventoryError(f"{what} must be a lowercase SHA-256 digest")
    return value


def _artifact_size(artifacts: ImmutableCAS, cid: str, maximum: int, *, source: bool = False) -> int:
    # Native CAS.get/get_bytes remains the integrity owner.  Check the declared
    # budget before retaining payloads; its independent finite read ceiling also
    # bounds a concurrent replacement between this stat and the verified read.
    size = artifacts.path_for(cid, source=source).stat().st_size
    if not 0 <= size <= maximum:
        raise CodebaseInventoryError("captured CAS artifact exceeds the inventory byte bound")
    return size


def _failure_payload(value: dict[str, Any], entry: SnapshotEntry,
                     unit: CodebaseUnit, manifest: CodebaseIRManifest) -> None:
    if (set(value) != _FAILURE_FIELDS or value["schema"] != DUCKDB_AST_STORE_SCHEMA_VERSION
            or value["kind"] != "parse_failure" or unit.parse_status != "failed"
            or value["source_cid"] != entry.source_cid or value["path"] != entry.path
            or value["repository_id"] != manifest.snapshot.repository_id
            or value["revision"] != "snapshot:" + manifest.snapshot.snapshot_cid
            or any(type(value[name]) is not str or not value[name]
                   for name in ("code", "message", "language"))):
        raise CodebaseInventoryError("native parse-failure artifact differs from its captured unit")


def _member_disposition(entry: SnapshotEntry, unit: CodebaseUnit,
                        ast_record: ASTRecord | None) -> tuple[str, tuple[Mapping[str, Any], ...]]:
    if entry.is_opaque:
        disposition, reason = "opaque", entry.opaque_reason
    elif unit.parse_status == "failed":
        disposition, reason = "parse_failed", "captured_parse_failed"
    elif unit.parse_status == "partial":
        disposition, reason = "parse_partial", "captured_parse_partial"
    elif unit.parse_status == "unindexed":
        disposition, reason = "unindexed", "captured_source_has_no_ast_projection"
    elif not entry.path.endswith(".py"):
        disposition, reason = "unsupported_extension", "python_feature_profile_required"
    else:
        disposition, reason = "captured_python", None
    rows: list[Mapping[str, Any]] = []
    if reason is not None:
        rows.append(MappingProxyType({"kind": "captured_inventory", "reason": reason}))
    if unit.ast_cid is not None and ast_record is None:
        rows.append(MappingProxyType({"kind": "captured_ast", "reason": "native_parse_failure_envelope"}))
    return disposition, tuple(rows)


def seal_inventory(index: RepositoryCodebaseIndex, *, expected_head: Any,
                   limits: CodebaseTargetLimits | None = None,
                   inventory_limits: CodebaseInventoryLimits | None = None,
                   checkpoint: Callable[[], Any] | None = None) -> InventorySeal:
    """Read all admitted source/AST CAS and one native publication receipt.

    A historical publication is accepted independently of live checkout state.
    Opaque entries explicitly have no admitted source capture: native capture
    may retain an undecodable byte CID without publishing those bytes to CAS.
    All nonopaque sources and every declared AST must exist and verify, even
    when their feature disposition will be unsupported or deferred by callers.
    """
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog, CodebaseHead
    if checkpoint is not None and not callable(checkpoint):
        raise CodebaseInventoryError("inventory checkpoint must be callable")
    check = (lambda: None) if checkpoint is None else checkpoint
    check()
    if (type(index) is not RepositoryCodebaseIndex or type(index.artifacts) is not ImmutableCAS
            or type(index.catalog) is not CodebaseCatalog or type(expected_head) is not CodebaseHead):
        raise CodebaseInventoryError("native catalog-owned index, ImmutableCAS and CodebaseHead required")
    limits = CodebaseTargetLimits() if limits is None else limits
    bounds = CodebaseInventoryLimits() if inventory_limits is None else inventory_limits
    if type(limits) is not CodebaseTargetLimits or type(bounds) is not CodebaseInventoryLimits:
        raise CodebaseInventoryError("native target and inventory limit records required")
    if (type(index.artifacts.max_object_bytes) is not int
            or not 0 < index.artifacts.max_object_bytes <= 16 * _MIB):
        raise CodebaseInventoryError("finite native CAS read ceiling required for this inventory profile")
    if limits.max_source_bytes > bounds.max_source_bytes or limits.max_target_bytes > bounds.max_target_bytes:
        raise CodebaseInventoryError("target profile exceeds the sealed inventory bounds")
    counters = InventoryCounters()
    _artifact_size(index.artifacts, expected_head.manifest_cid, bounds.max_manifest_bytes)
    check()
    manifest = index.load(expected_head.manifest_cid)
    counters.manifest_reads = 1
    manifest_bytes = canonical_dag_json_bytes(manifest.to_dict())
    if len(manifest_bytes) > bounds.max_manifest_bytes:
        raise CodebaseInventoryError("manifest exceeds its inventory byte bound")
    counters.manifest_bytes = len(manifest_bytes)
    check()
    with index.catalog.store._lock:
        index.catalog._ensure_owner()
        with index.catalog.store._transaction():
            index.catalog._check_schema()
            check()
            receipt = index.catalog._read_receipt("receipt_cid", expected_head.receipt_cid)
    check()
    counters.publication_receipt_reads = 1
    if (receipt is None or receipt.head != expected_head
            or manifest.cid != expected_head.manifest_cid
            or manifest.snapshot.repository_id != expected_head.repository_id
            or manifest.snapshot.snapshot_cid != expected_head.snapshot_cid
            or manifest.ast_revision_id != expected_head.ast_revision_id):
        raise CodebaseInventoryError("published head does not bind the exact manifest and receipt")
    receipt_bytes = canonical_dag_json_bytes(receipt.to_dict())
    if len(receipt_bytes) > bounds.max_receipt_bytes:
        raise CodebaseInventoryError("publication receipt exceeds its inventory byte bound")
    counters.publication_receipt_bytes = len(receipt_bytes)
    entries = tuple(manifest.snapshot.entries)
    if (manifest.snapshot.max_entries > bounds.max_entries
            or manifest.snapshot.max_file_bytes > bounds.max_source_bytes
            or len(entries) > bounds.max_entries):
        raise CodebaseInventoryError("captured snapshot exceeds the inventory profile")
    by_path = {entry.path: entry for entry in entries}
    by_key = {entry.source_key: entry for entry in entries}
    units = {unit.source_key: unit for unit in manifest.units}
    if (len(by_path) != len(entries) or len(by_key) != len(entries)
            or len(units) != len(manifest.units) or set(units) != set(by_key)
            or [entry.raw_path_hex for entry in entries] != sorted(entry.raw_path_hex for entry in entries)):
        raise CodebaseInventoryError("ordered complete source and unit inventory required")
    members = []
    for entry in entries:
        check()
        unit = units[entry.source_key]
        if unit.entry_cid != entry.entry_cid:
            raise CodebaseInventoryError("captured unit entry identity differs")
        raw, record, ast_payload = None, None, None
        if not entry.is_opaque:
            if (type(entry.size_bytes) is not int
                    or not 0 <= entry.size_bytes <= bounds.max_source_bytes):
                raise CodebaseInventoryError("nonopaque capture has an invalid bounded source size")
            size = _artifact_size(index.artifacts, entry.source_cid, bounds.max_source_bytes, source=True)
            if counters.source_bytes + size > bounds.max_total_source_bytes:
                raise CodebaseInventoryError("complete captured source inventory exceeds its aggregate byte bound")
            check()
            raw = index.artifacts.get_bytes(entry.source_cid)
            counters.source_cas_reads += 1
            if (len(raw) != entry.size_bytes or len(raw) > bounds.max_source_bytes
                    or cid_for_bytes(raw) != entry.source_cid):
                raise CodebaseInventoryError("captured source bytes differ from their exact entry")
            counters.source_bytes += len(raw)
            if counters.source_bytes > bounds.max_total_source_bytes:
                raise CodebaseInventoryError("complete captured source inventory exceeds its aggregate byte bound")
        if unit.ast_cid is not None:
            size = _artifact_size(index.artifacts, unit.ast_cid, bounds.max_ast_bytes)
            if counters.ast_bytes + size > bounds.max_total_ast_bytes:
                raise CodebaseInventoryError("complete captured AST inventory exceeds its aggregate byte bound")
            check()
            value = index.artifacts.get(unit.ast_cid)
            counters.ast_cas_reads += 1
            ast_payload = canonical_dag_json_bytes(value)
            if (len(ast_payload) > bounds.max_ast_bytes or cid_for_structured(value) != unit.ast_cid
                    or type(value) is not dict):
                raise CodebaseInventoryError("captured AST artifact differs from its exact unit")
            counters.ast_bytes += len(ast_payload)
            if counters.ast_bytes > bounds.max_total_ast_bytes:
                raise CodebaseInventoryError("complete captured AST inventory exceeds its aggregate byte bound")
            if value.get("kind") == "parse_failure":
                _failure_payload(value, entry, unit, manifest)
            else:
                record = ASTRecord.from_dict(value)
                provenance = record.provenance
                if (record.to_dict() != value or classify_parse_status(record) != unit.parse_status
                        or provenance.source_cid != entry.source_cid or provenance.path != entry.path
                        or provenance.repository_id != expected_head.repository_id
                        or provenance.revision != "snapshot:" + manifest.snapshot.snapshot_cid
                        or provenance.repository_tree_cid != expected_head.snapshot_cid):
                    raise CodebaseInventoryError("captured AST does not bind its exact source and publication")
        disposition, frontiers = _member_disposition(entry, unit, record)
        members.append(InventoryMember(entry, unit, raw, record, ast_payload, disposition, frontiers))
    members_tuple = tuple(members)
    check()
    return InventorySeal(expected_head, manifest, receipt, members_tuple,
                         MappingProxyType(by_path), MappingProxyType(by_key), MappingProxyType(units),
                         MappingProxyType({member.source_key: member for member in members_tuple}),
                         limits, bounds, counters)


def prepare_inventory_target(seal: InventorySeal, entry_or_source_key: SnapshotEntry | str,
                             contracts: Sequence[ContractSpec] = ()) -> DomainTargetEnvelope:
    """Prepare an unchanged native target from already verified captured bytes."""
    if type(seal) is not InventorySeal:
        raise CodebaseInventoryError("operation-owned complete InventorySeal required")
    member = seal.member(entry_or_source_key)
    if member.entry.is_opaque or member.raw is None:
        raise CodebaseInventoryError("opaque inventory member has no admitted source target")
    if member.ast_payload is not None and member.ast_record is None:
        raise CodebaseInventoryError("native parser-failure envelope has no replayable ASTRecord target")
    seal.counters.target_preparation_attempts += 1
    specs = _specs(contracts, seal.limits)
    result = _prepare_bound(
        binding=_binding(seal.head, seal.manifest, member.entry, member.unit, member.raw),
        manifest=seal.manifest, receipt=seal.receipt, ast_record=member.ast_record,
        raw=member.raw, specs=specs, limits=seal.limits,
    )
    if len(result.canonical_bytes) > seal.inventory_limits.max_target_bytes:
        raise CodebaseInventoryError("prepared native target exceeds inventory byte bound")
    seal.counters.target_preparations += 1
    seal.counters.prepared_target_bytes += len(result.canonical_bytes)
    return result


def prepare_inventory_target_or_frontier(
    seal: InventorySeal, entry_or_source_key: SnapshotEntry | str,
    contracts: Sequence[ContractSpec] = (),
) -> tuple[DomainTargetEnvelope | None, dict[str, Any] | None]:
    """Keep known target-profile limits explicit without hiding integrity errors.

    The inventory has already verified the captured bytes and AST.  Some valid
    captures exceed the narrower native feature-target shape or serialized byte
    profile.  Only the exact bound errors from the unchanged native producer
    become dispositions; malformed contracts, source bindings, provenance,
    correspondence and unknown errors remain fatal.
    """
    if type(seal) is not InventorySeal:
        raise CodebaseInventoryError("operation-owned complete InventorySeal required")
    # Do not convert a malformed contract collection into a count frontier.
    if type(contracts) not in {tuple, list} or any(type(item) is not ContractSpec for item in contracts):
        raise CodebaseInventoryError("native bounded ContractSpec collection required")
    seal.member(entry_or_source_key)

    def frontier(disposition: str, reason: str, native_error: str):
        return None, {"disposition": disposition,
                      "frontiers": [{"kind": "target_profile", "reason": reason,
                                     "native_error": native_error}]}

    if len(contracts) > seal.limits.max_contracts:
        return frontier("unsupported_target", "authored_contract_count_profile_bound",
                        "authored contract count exceeds the native target profile")
    known = {
        "source or contract AST exceeds the bounded target profile":
            ("unsupported_target", "native_ast_shape_profile_bound"),
        "function inventory exceeds the target profile":
            ("unsupported_target", "native_function_count_profile_bound"),
        "contract identity or condition inventory exceeds the profile":
            ("unsupported_target", "authored_contract_inventory_profile_bound"),
        "captured source exceeds the target profile":
            ("deferred_budget", "native_source_byte_profile_bound"),
        "CodebaseIR target exceeds its byte bound":
            ("deferred_budget", "native_serialization_byte_profile_bound"),
    }
    try:
        return prepare_inventory_target(seal, entry_or_source_key, contracts), None
    except CodebaseTargetError as exc:
        # Exact type avoids treating errors from another owner or future
        # subclass as an optional target-profile frontier.
        if type(exc) is CodebaseTargetError and str(exc) in known:
            disposition, reason = known[str(exc)]
            return frontier(disposition, reason, str(exc))
        if (type(exc) is CodebaseInventoryError
                and str(exc) == "prepared native target exceeds inventory byte bound"):
            return frontier("deferred_budget", "inventory_target_byte_profile_bound", str(exc))
        raise


@dataclass(frozen=True, slots=True)
class ValidatedInventoryEnvelope:
    """Boundary-local immutable token for one independently parsed shared record."""

    canonical_bytes: bytes
    shared_sha256: str
    head: Any
    manifest: CodebaseIRManifest
    receipt: Any
    _manifest_value: dict[str, Any] = field(repr=False, compare=False)
    _receipt_value: dict[str, Any] = field(repr=False, compare=False)
    _token: object = field(repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self.canonical_bytes)


def shared_inventory_envelope(seal: InventorySeal) -> dict[str, Any]:
    """Return one canonical shared manifest/receipt envelope for the operation."""
    if type(seal) is not InventorySeal:
        raise CodebaseInventoryError("operation-owned complete InventorySeal required")
    value = {"schema": SHARED_INVENTORY_SCHEMA, "head": seal.head.to_dict(),
             "manifest": seal.manifest.to_dict(), "publication_receipt": seal.receipt.to_dict()}
    value["shared_sha256"] = _digest(value, seal.inventory_limits.max_shared_bytes, "shared inventory")
    raw = _wire(value, seal.inventory_limits.max_shared_bytes, "shared inventory")
    seal.counters.shared_envelope_creations += 1
    seal.counters.shared_transport_bytes += len(raw)
    return json.loads(raw)


def validate_shared_inventory_envelope(shared: Mapping[str, Any]) -> ValidatedInventoryEnvelope:
    """Parse and bind the shared native records once at the receiver boundary."""
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead, CodebasePublicationReceipt
    if type(shared) is not dict or set(shared) != _SHARED_FIELDS or shared["schema"] != SHARED_INVENTORY_SCHEMA:
        raise CodebaseInventoryError("closed shared native inventory envelope required")
    bounds = CodebaseInventoryLimits()
    raw = _wire(shared, bounds.max_shared_bytes, "shared inventory")
    value = json.loads(raw)
    sha = _sha(value["shared_sha256"], "shared inventory identity")
    payload = {name: child for name, child in value.items() if name != "shared_sha256"}
    if _digest(payload, bounds.max_shared_bytes, "shared inventory") != sha:
        raise CodebaseInventoryError("shared inventory transport identity differs")
    try:
        head = CodebaseHead.from_dict(value["head"])
        manifest = CodebaseIRManifest.from_dict(value["manifest"])
        receipt = CodebasePublicationReceipt.from_dict(value["publication_receipt"])
        if (head.to_dict() != value["head"] or manifest.to_dict() != value["manifest"]
                or receipt.to_dict() != value["publication_receipt"]
                or manifest.cid != head.manifest_cid or receipt.head != head
                or manifest.snapshot.snapshot_cid != head.snapshot_cid
                or manifest.snapshot.repository_id != head.repository_id
                or manifest.ast_revision_id != head.ast_revision_id
                or manifest.snapshot.max_entries > bounds.max_entries
                or manifest.snapshot.max_file_bytes > bounds.max_source_bytes
                or len(manifest.snapshot.entries) > bounds.max_entries
                or len(canonical_dag_json_bytes(value["manifest"])) > bounds.max_manifest_bytes
                or len(canonical_dag_json_bytes(value["publication_receipt"])) > bounds.max_receipt_bytes):
            raise CodebaseInventoryError("shared native inventory publication binding differs")
    except CodebaseInventoryError:
        raise
    except (KeyError, TypeError, ValueError, UnicodeError) as exc:
        raise CodebaseInventoryError("malformed shared native inventory publication") from exc
    return ValidatedInventoryEnvelope(raw, sha, head, manifest, receipt,
                                      value["manifest"], value["publication_receipt"], _VALIDATED_TOKEN)


def _validated(shared: ValidatedInventoryEnvelope | Mapping[str, Any]) -> ValidatedInventoryEnvelope:
    if type(shared) is ValidatedInventoryEnvelope:
        if shared._token is not _VALIDATED_TOKEN:
            raise CodebaseInventoryError("boundary-local verified shared inventory token required")
        return shared
    return validate_shared_inventory_envelope(shared)


def _target_details(value: dict[str, Any]) -> dict[str, Any]:
    if (value.get("domain_id") != "codebase_ir" or type(value.get("validation")) is not list
            or len(value["validation"]) != 1 or type(value["validation"][0]) is not dict
            or type(value["validation"][0].get("details")) is not dict
            or value["validation"][0]["details"].get("target_schema") != CODEBASE_TARGET_SCHEMA):
        raise CodebaseInventoryError("single native CodebaseIR target validation declaration required")
    return value["validation"][0]["details"]


def _source_head(details: dict[str, Any]) -> Any:
    binding = details.get("source_binding")
    if type(binding) is not dict:
        raise CodebaseInventoryError("exact native source binding required")
    return binding.get("head")


def compact_inventory_target(target: DomainTargetEnvelope,
                             shared: ValidatedInventoryEnvelope | Mapping[str, Any], *,
                             counters: InventoryCounters | None = None) -> dict[str, Any]:
    """Detach only two repeated fields; preserve every canonical native target bit."""
    if type(target) is not DomainTargetEnvelope or len(target.canonical_bytes) > 4 * _MIB:
        raise CodebaseInventoryError("bounded native DomainTargetEnvelope required")
    if counters is not None and type(counters) is not InventoryCounters:
        raise CodebaseInventoryError("native InventoryCounters required")
    token = _validated(shared)
    value = target.to_dict()
    details = _target_details(value)
    if (details.get("manifest") != token._manifest_value
            or details.get("publication_receipt") != token._receipt_value
            or _source_head(details) != token.head.to_dict()):
        raise CodebaseInventoryError("target does not bind the shared native publication")
    del details["manifest"]
    del details["publication_receipt"]
    compact = {"schema": COMPACT_TARGET_SCHEMA, "shared_sha256": token.shared_sha256,
               "target_sha256": target.digest, "source_digest": target.source_digest,
               "detached_target": value}
    compact["compact_sha256"] = _digest(compact, 4 * _MIB, "compact native target")
    raw = _wire(compact, 4 * _MIB, "compact native target")
    if counters is not None:
        counters.compact_targets += 1
        counters.full_target_transport_bytes += len(target.canonical_bytes)
        counters.compact_target_transport_bytes += len(raw)
    return json.loads(raw)


def restore_inventory_target(shared: ValidatedInventoryEnvelope | Mapping[str, Any],
                             compact: Mapping[str, Any]) -> DomainTargetEnvelope:
    """Losslessly restore a full native target; callers must run native replay.

    A valid transport digest cannot replace ``validate_codebase_targets``.  The
    isolated receiver independently runs that native validator after restoring
    each target and before feature extraction or numerical inference.
    """
    token = _validated(shared)
    if type(compact) is not dict or set(compact) != _COMPACT_FIELDS or compact["schema"] != COMPACT_TARGET_SCHEMA:
        raise CodebaseInventoryError("closed compact native target envelope required")
    raw = _wire(compact, 4 * _MIB, "compact native target")
    value = json.loads(raw)
    payload = {name: child for name, child in value.items() if name != "compact_sha256"}
    if (_digest(payload, 4 * _MIB, "compact native target") != _sha(value["compact_sha256"], "compact identity")
            or value["shared_sha256"] != token.shared_sha256):
        raise CodebaseInventoryError("compact target shared inventory or transport identity differs")
    original_digest = _sha(value["target_sha256"], "original canonical target identity")
    original_source_digest = _sha(value["source_digest"], "original native target source identity")
    detached = value["detached_target"]
    if type(detached) is not dict:
        raise CodebaseInventoryError("detached native target mapping required")
    details = _target_details(detached)
    if ("manifest" in details or "publication_receipt" in details
            or detached.get("source_digest") != original_source_digest
            or _source_head(details) != token.head.to_dict()):
        raise CodebaseInventoryError("compact target altered the exact detached-field boundary")
    details["manifest"] = token._manifest_value
    details["publication_receipt"] = token._receipt_value
    full = _wire(detached, 4 * _MIB, "restored native target")
    if hashlib.sha256(full).hexdigest() != original_digest:
        raise CodebaseInventoryError("restored canonical native target identity differs")
    try:
        target = DomainTargetEnvelope(full)
    except (TypeError, ValueError, UnicodeError) as exc:
        raise CodebaseInventoryError("restored native target envelope is invalid") from exc
    if target.source_digest != original_source_digest:
        raise CodebaseInventoryError("restored source identity differs")
    return target


__all__ = [
    "INVENTORY_SEAL_SCHEMA", "SHARED_INVENTORY_SCHEMA", "COMPACT_TARGET_SCHEMA",
    "CodebaseInventoryError", "CodebaseInventoryLimits", "InventoryCounters",
    "InventoryMember", "InventorySeal", "ValidatedInventoryEnvelope", "seal_inventory",
    "prepare_inventory_target", "prepare_inventory_target_or_frontier",
    "shared_inventory_envelope", "validate_shared_inventory_envelope",
    "compact_inventory_target", "restore_inventory_target",
]
