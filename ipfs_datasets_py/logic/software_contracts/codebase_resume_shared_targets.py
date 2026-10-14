"""Lossless shared512 transport and receiver-owned native target replay.

This explicitly separate resume profile admits at most 512 captured members.
It never widens the older 256-member inventory transport or replay tokens. A
shared declaration is historical data: its hashes and local tokens establish
no live-source, producer-execution, proof, training or tool authority. The
coordinator and worker separately bind the complete inventory to their root.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import json
from types import MappingProxyType
from typing import Any

from .ast_ir import ASTRecord
from .codebase_ir import CodebaseIRManifest
from .codebase_ir_targets import (
    CODEBASE_TARGET_SCHEMA, CodebaseTargetError, CodebaseTargetLimits, _VALIDATOR,
    _binding, _prepare_bound, _specs,
)
from .codebase_inventory_targets import CodebaseInventoryError
from .codebase_inventory_replay import InventoryReplayCounters, _counters, _exact_json, _freeze
from .content import cid_for_bytes, cid_for_structured
from ..formalization.autoencoder.domain_targets import DomainTargetEnvelope
from ..software_verification.pipeline import ContractSpec

SHARED_INVENTORY_SCHEMA = "codebase-ir-resume-shared-target-inventory@1"
COMPACT_TARGET_SCHEMA = "codebase-ir-resume-compact-native-target@1"
MAX_INVENTORY_ENTRIES = 512
MAX_SOURCE_BYTES = 64 * 1024
MAX_SHARED_BYTES = 16 * 1024 * 1024
MAX_RECEIPT_BYTES = 64 * 1024
MAX_TARGET_BYTES = 4 * 1024 * 1024
_SHARED_FIELDS = frozenset({"schema", "head", "manifest", "publication_receipt", "shared_sha256"})
_COMPACT_FIELDS = frozenset({"schema", "shared_sha256", "target_sha256", "source_digest",
                             "detached_target", "compact_sha256"})
_TOKEN = object()


def _wire(value: Any, maximum: int, what: str) -> bytes:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError, UnicodeError) as exc:
        raise CodebaseInventoryError(f"{what} requires bounded finite JSON") from exc
    if len(raw) > maximum:
        raise CodebaseInventoryError(f"{what} exceeds its serialized byte bound")
    return raw


def _snapshot(value: Any, maximum: int, what: str) -> tuple[bytes, Any]:
    """Refuse primitive normalization, tuples, subclasses and non-string keys."""
    raw = _wire(value, maximum, what)
    try:
        copied = json.loads(raw)
        if not _exact_json(value, _freeze(copied)):
            raise CodebaseInventoryError(f"{what} requires exact canonical JSON primitives")
    except (TypeError, ValueError, RecursionError, UnicodeError) as exc:
        raise CodebaseInventoryError(f"{what} requires bounded finite JSON") from exc
    return raw, copied


def _digest(value: Any, maximum: int, what: str) -> str:
    return hashlib.sha256(_wire(value, maximum, what)).hexdigest()


def _sha(value: Any, what: str) -> str:
    if (type(value) is not str or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)):
        raise CodebaseInventoryError(f"{what} must be a lowercase SHA-256 digest")
    return value


def _publication(head: Any, manifest: Any, receipt: Any,
                 value: dict[str, Any]) -> None:
    """Check independently parsed native records and exact complete ordering."""
    from ipfs_datasets_py.duckdb_control.codebase_catalog import (
        CodebaseHead, CodebasePublicationReceipt,
    )
    if (type(head) is not CodebaseHead or type(manifest) is not CodebaseIRManifest
            or type(receipt) is not CodebasePublicationReceipt):
        raise CodebaseInventoryError("exact native resume publication records required")
    for name, native in (("head", head), ("manifest", manifest),
                         ("publication_receipt", receipt)):
        if not _exact_json(native.to_dict(), _freeze(value[name])):
            raise CodebaseInventoryError("resume native publication is not exact canonical JSON")
    snapshot = manifest.snapshot
    if (manifest.cid != head.manifest_cid or receipt.head != head
            or snapshot.snapshot_cid != head.snapshot_cid
            or snapshot.repository_id != head.repository_id
            or manifest.ast_revision_id != head.ast_revision_id
            or snapshot.max_entries > MAX_INVENTORY_ENTRIES
            or snapshot.max_file_bytes > MAX_SOURCE_BYTES
            or len(snapshot.entries) > MAX_INVENTORY_ENTRIES
            or len(_wire(value["manifest"], MAX_SHARED_BYTES, "resume manifest")) > MAX_SHARED_BYTES
            or len(_wire(value["publication_receipt"], MAX_RECEIPT_BYTES,
                         "resume publication receipt")) > MAX_RECEIPT_BYTES):
        raise CodebaseInventoryError("resume shared native publication binding differs")
    entries = {entry.source_key: entry for entry in snapshot.entries}
    units = {unit.source_key: unit for unit in manifest.units}
    if (len(entries) != len(snapshot.entries) or len(units) != len(manifest.units)
            or set(entries) != set(units)
            or tuple(entries) != tuple(sorted(entries))
            or tuple(units) != tuple(entries)):
        raise CodebaseInventoryError("resume inventory must bind ordered complete exact membership")
    for key, entry in entries.items():
        unit = units[key]
        if (unit.entry_cid != entry.entry_cid
                or (unit.parse_status == "opaque") != entry.is_opaque
                or (not entry.is_opaque and (entry.size_bytes is None
                                             or entry.size_bytes > MAX_SOURCE_BYTES))):
            raise CodebaseInventoryError("resume inventory source/unit membership differs")


@dataclass(frozen=True, slots=True)
class _ValidationSeal:
    canonical_bytes: bytes
    shared_sha256: str
    records: tuple[Any, ...]
    values: tuple[Any, ...]
    marker: object


@dataclass(frozen=True, slots=True)
class ValidatedResumeInventory:
    """Local immutable historical declaration, with no live or proof authority."""

    canonical_bytes: bytes
    shared_sha256: str
    head: Any
    manifest: CodebaseIRManifest
    receipt: Any
    _head_value: Mapping[str, Any] = field(repr=False, compare=False)
    _manifest_value: Mapping[str, Any] = field(repr=False, compare=False)
    _receipt_value: Mapping[str, Any] = field(repr=False, compare=False)
    _seal: _ValidationSeal = field(repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self.canonical_bytes)


def _validated(token: ValidatedResumeInventory) -> ValidatedResumeInventory:
    if type(token) is not ValidatedResumeInventory or type(token._seal) is not _ValidationSeal:
        raise CodebaseInventoryError("boundary-local ValidatedResumeInventory token required")
    seal = token._seal
    if (seal.marker is not _TOKEN or token.canonical_bytes is not seal.canonical_bytes
            or type(token.shared_sha256) is not str or token.shared_sha256 != seal.shared_sha256
            or any(left is not right for left, right in zip(
                (token.head, token.manifest, token.receipt), seal.records))
            or any(left is not right for left, right in zip(
                (token._head_value, token._manifest_value, token._receipt_value), seal.values))):
        raise CodebaseInventoryError("resume inventory token changed after boundary validation")
    return token


def create_resume_shared_inventory(head: Any, manifest: CodebaseIRManifest,
                                   receipt: Any) -> dict[str, Any]:
    """Create a fresh envelope; native receiver validation remains independent."""
    from ipfs_datasets_py.duckdb_control.codebase_catalog import (
        CodebaseHead, CodebasePublicationReceipt,
    )
    if (type(head) is not CodebaseHead or type(manifest) is not CodebaseIRManifest
            or type(receipt) is not CodebasePublicationReceipt):
        raise CodebaseInventoryError("exact native resume publication records required")
    value = {"schema": SHARED_INVENTORY_SCHEMA, "head": head.to_dict(),
             "manifest": manifest.to_dict(), "publication_receipt": receipt.to_dict()}
    value["shared_sha256"] = _digest(value, MAX_SHARED_BYTES, "resume shared inventory")
    # The receiver reparses all three native records, even for this producer API.
    return validate_resume_shared_inventory(value).to_dict()


def validate_resume_shared_inventory(shared: dict[str, Any]) -> ValidatedResumeInventory:
    """Parse the complete bounded declaration once at the receiving boundary."""
    from ipfs_datasets_py.duckdb_control.codebase_catalog import (
        CodebaseHead, CodebasePublicationReceipt,
    )
    if type(shared) is not dict or set(shared) != _SHARED_FIELDS or shared["schema"] != SHARED_INVENTORY_SCHEMA:
        raise CodebaseInventoryError("closed resume shared native inventory envelope required")
    raw, value = _snapshot(shared, MAX_SHARED_BYTES, "resume shared inventory")
    sha = _sha(value["shared_sha256"], "resume shared identity")
    payload = {name: child for name, child in value.items() if name != "shared_sha256"}
    if _digest(payload, MAX_SHARED_BYTES, "resume shared inventory") != sha:
        raise CodebaseInventoryError("resume shared inventory transport identity differs")
    try:
        declared = value["manifest"]["snapshot"]
        if (type(declared) is not dict
                or type(declared["max_entries"]) is not int
                or not 0 < declared["max_entries"] <= MAX_INVENTORY_ENTRIES
                or type(declared["max_file_bytes"]) is not int
                or not 0 < declared["max_file_bytes"] <= MAX_SOURCE_BYTES
                or type(declared["entries"]) is not list
                or len(declared["entries"]) > MAX_INVENTORY_ENTRIES
                or type(value["manifest"]["units"]) is not list
                or len(value["manifest"]["units"]) > MAX_INVENTORY_ENTRIES):
            raise CodebaseInventoryError("resume inventory exceeds its exact capture profile")
        if len(_wire(value["publication_receipt"], MAX_RECEIPT_BYTES,
                     "resume publication receipt")) > MAX_RECEIPT_BYTES:
            raise CodebaseInventoryError("resume publication receipt exceeds its byte bound")
        head = CodebaseHead.from_dict(value["head"])
        manifest = CodebaseIRManifest.from_dict(value["manifest"])
        receipt = CodebasePublicationReceipt.from_dict(value["publication_receipt"])
        _publication(head, manifest, receipt, value)
        values = tuple(_freeze(value[name]) for name in ("head", "manifest", "publication_receipt"))
    except CodebaseTargetError:
        raise
    except (KeyError, TypeError, ValueError, RecursionError, UnicodeError) as exc:
        raise CodebaseInventoryError("malformed resume shared native publication") from exc
    seal = _ValidationSeal(raw, sha, (head, manifest, receipt), values, _TOKEN)
    return ValidatedResumeInventory(raw, sha, head, manifest, receipt, *values, seal)


def _details(value: dict[str, Any]) -> dict[str, Any]:
    if (value.get("domain_id") != "codebase_ir" or type(value.get("validation")) is not list
            or len(value["validation"]) != 1 or type(value["validation"][0]) is not dict
            or value["validation"][0].get("validator_id") != _VALIDATOR
            or type(value["validation"][0].get("details")) is not dict
            or value["validation"][0]["details"].get("target_schema") != CODEBASE_TARGET_SCHEMA):
        raise CodebaseInventoryError("single exact native CodebaseIR target validation required")
    return value["validation"][0]["details"]


def _target_head(details: dict[str, Any]) -> Any:
    binding = details.get("source_binding")
    if type(binding) is not dict:
        raise CodebaseInventoryError("exact native target source binding required")
    return binding.get("head")


def compact_resume_target(target: DomainTargetEnvelope,
                          token: ValidatedResumeInventory) -> dict[str, Any]:
    """Detach exactly manifest and publication receipt; retain every other bit."""
    token = _validated(token)
    if type(target) is not DomainTargetEnvelope or len(target.canonical_bytes) > MAX_TARGET_BYTES:
        raise CodebaseInventoryError("bounded native DomainTargetEnvelope required")
    value = target.to_dict()
    details = _details(value)
    if (not _exact_json(details.get("manifest"), token._manifest_value)
            or not _exact_json(details.get("publication_receipt"), token._receipt_value)
            or not _exact_json(_target_head(details), token._head_value)):
        raise CodebaseInventoryError("target does not bind the resume shared native publication")
    del details["manifest"]
    del details["publication_receipt"]
    compact = {"schema": COMPACT_TARGET_SCHEMA, "shared_sha256": token.shared_sha256,
               "target_sha256": target.digest, "source_digest": target.source_digest,
               "detached_target": value}
    compact["compact_sha256"] = _digest(compact, MAX_TARGET_BYTES, "resume compact native target")
    return json.loads(_wire(compact, MAX_TARGET_BYTES, "resume compact native target"))


def restore_resume_target(token: ValidatedResumeInventory,
                          compact: dict[str, Any]) -> DomainTargetEnvelope:
    """Restore complete bytes; native replay is required before feature use."""
    token = _validated(token)
    if type(compact) is not dict or set(compact) != _COMPACT_FIELDS or compact["schema"] != COMPACT_TARGET_SCHEMA:
        raise CodebaseInventoryError("closed resume compact native target envelope required")
    _, value = _snapshot(compact, MAX_TARGET_BYTES, "resume compact native target")
    payload = {name: child for name, child in value.items() if name != "compact_sha256"}
    if (_digest(payload, MAX_TARGET_BYTES, "resume compact native target")
            != _sha(value["compact_sha256"], "resume compact identity")
            or value["shared_sha256"] != token.shared_sha256):
        raise CodebaseInventoryError("resume compact target transport or shared identity differs")
    original_digest = _sha(value["target_sha256"], "original canonical target identity")
    original_source_digest = _sha(value["source_digest"], "original native target source identity")
    detached = value["detached_target"]
    if type(detached) is not dict:
        raise CodebaseInventoryError("detached resume native target mapping required")
    details = _details(detached)
    if ("manifest" in details or "publication_receipt" in details
            or detached.get("source_digest") != original_source_digest
            or not _exact_json(_target_head(details), token._head_value)):
        raise CodebaseInventoryError("resume compact target changed its exact detached-field boundary")
    details["manifest"] = token.manifest.to_dict()
    details["publication_receipt"] = token.receipt.to_dict()
    full = _wire(detached, MAX_TARGET_BYTES, "restored resume native target")
    if hashlib.sha256(full).hexdigest() != original_digest:
        raise CodebaseInventoryError("restored resume canonical target identity differs")
    try:
        target = DomainTargetEnvelope(full)
    except (TypeError, ValueError, RecursionError, UnicodeError) as exc:
        raise CodebaseInventoryError("restored resume target envelope is invalid") from exc
    if target.source_digest != original_source_digest:
        raise CodebaseInventoryError("restored resume source identity differs")
    return target


@dataclass(frozen=True, slots=True)
class _ReplaySeal:
    shared_sha256: str
    membership_count: int
    fields: tuple[Any, ...]
    marker: object


@dataclass(frozen=True, slots=True)
class NativeResumeReplay:
    """Immutable receiving-operation token; never a source/proof capability."""

    shared_sha256: str
    membership_count: int
    _head: Any = field(repr=False, compare=False)
    _manifest: Any = field(repr=False, compare=False)
    _receipt: Any = field(repr=False, compare=False)
    _head_value: Mapping[str, Any] = field(repr=False, compare=False)
    _manifest_value: Mapping[str, Any] = field(repr=False, compare=False)
    _receipt_value: Mapping[str, Any] = field(repr=False, compare=False)
    _entries: Mapping[str, Any] = field(repr=False, compare=False)
    _units: Mapping[str, Any] = field(repr=False, compare=False)
    _entry_values: Mapping[str, Any] = field(repr=False, compare=False)
    _unit_values: Mapping[str, Any] = field(repr=False, compare=False)
    _seal: _ReplaySeal = field(repr=False, compare=False)


_REPLAY_RECORD_FIELDS = ("_head", "_manifest", "_receipt", "_head_value", "_manifest_value",
                         "_receipt_value", "_entries", "_units", "_entry_values", "_unit_values")


def prepare_resume_replay(token: ValidatedResumeInventory,
                          counters: InventoryReplayCounters | None = None) -> NativeResumeReplay:
    """Reuse independently parsed records only within this receiving operation."""
    counts = _counters(counters)
    token = _validated(token)
    try:
        raw, value = _snapshot(token.to_dict(), MAX_SHARED_BYTES, "resume shared replay snapshot")
        if raw != token.canonical_bytes or value["schema"] != SHARED_INVENTORY_SCHEMA:
            raise CodebaseInventoryError("resume canonical shared snapshot differs")
        payload = {name: child for name, child in value.items() if name != "shared_sha256"}
        if _digest(payload, MAX_SHARED_BYTES, "resume shared replay snapshot") != token.shared_sha256:
            raise CodebaseInventoryError("resume shared replay snapshot identity differs")
        _publication(token.head, token.manifest, token.receipt, value)
        entries = MappingProxyType({entry.source_key: entry for entry in token.manifest.snapshot.entries})
        units = MappingProxyType({unit.source_key: unit for unit in token.manifest.units})
        entry_values = MappingProxyType({key: _freeze(entry.to_dict()) for key, entry in entries.items()})
        unit_values = MappingProxyType({key: _freeze(unit.to_dict()) for key, unit in units.items()})
    except CodebaseTargetError:
        raise
    except (KeyError, TypeError, ValueError, RecursionError, UnicodeError) as exc:
        raise CodebaseInventoryError("malformed resume shared replay snapshot") from exc
    fields = (token.head, token.manifest, token.receipt, token._head_value, token._manifest_value,
              token._receipt_value, entries, units, entry_values, unit_values)
    seal = _ReplaySeal(token.shared_sha256, len(entries), fields, _TOKEN)
    result = NativeResumeReplay(token.shared_sha256, len(entries), *fields, seal)
    if counts is not None:
        counts.shared_replay_preparations += 1
    return result


def _replay(replay: NativeResumeReplay) -> NativeResumeReplay:
    if type(replay) is not NativeResumeReplay or type(replay._seal) is not _ReplaySeal:
        raise CodebaseInventoryError("boundary-local NativeResumeReplay token required")
    seal = replay._seal
    if (seal.marker is not _TOKEN or type(replay.shared_sha256) is not str
            or replay.shared_sha256 != seal.shared_sha256
            or type(replay.membership_count) is not int or replay.membership_count != seal.membership_count
            or any(getattr(replay, name) is not bound for name, bound
                   in zip(_REPLAY_RECORD_FIELDS, seal.fields))):
        raise CodebaseInventoryError("resume replay token changed after boundary preparation")
    return replay


def validate_resume_target(target: DomainTargetEnvelope, replay: NativeResumeReplay,
                           counters: InventoryReplayCounters | None = None) -> DomainTargetEnvelope:
    """Rebuild each complete source/AST/contract target, then compare every byte."""
    counts = _counters(counters)
    replay = _replay(replay)
    if type(target) is not DomainTargetEnvelope or len(target.canonical_bytes) > MAX_TARGET_BYTES:
        raise CodebaseTargetError("bounded native immutable DomainTargetEnvelope required")
    value = target.to_dict()
    _wire(value, MAX_TARGET_BYTES, "resume full native target")
    details = _details(value)
    if counts is not None:
        counts.target_replay_attempts += 1
    try:
        limits = CodebaseTargetLimits(**details["limits"])
        binding = details["source_binding"]
        if (type(binding) is not dict
                or not _exact_json(details["manifest"], replay._manifest_value)
                or not _exact_json(details["publication_receipt"], replay._receipt_value)
                or not _exact_json(binding["head"], replay._head_value)):
            raise CodebaseTargetError("embedded resume shared native inventory binding differs")
        key = binding["source_key"]
        if type(key) is not str or key not in replay._entries:
            raise CodebaseTargetError("embedded source is outside the exact resume inventory")
        entry, unit = replay._entries[key], replay._units[key]
        if (not _exact_json(binding["entry"], replay._entry_values[key])
                or not _exact_json(binding["unit"], replay._unit_values[key])):
            raise CodebaseTargetError("embedded resume source/unit membership differs")
        raw_hex = details["source_bytes_hex"]
        if type(raw_hex) is not str or len(raw_hex) > limits.max_source_bytes * 2:
            raise CodebaseTargetError("bounded exact source hexadecimal required")
        raw = bytes.fromhex(raw_hex)
        if counts is not None:
            counts.source_digest_checks += 1
        if raw.hex() != raw_hex or cid_for_bytes(raw) != entry.source_cid or len(raw) != entry.size_bytes:
            raise CodebaseTargetError("embedded source bytes differ from the captured resume entry")
        expected_binding = _binding(replay._head, replay._manifest, entry, unit, raw)
        if not _exact_json(binding, _freeze(expected_binding)):
            raise CodebaseTargetError("embedded resume source/head/unit binding differs")
        ast_record = None if details["captured_ast"] is None else ASTRecord.from_dict(details["captured_ast"])
        if ast_record is not None:
            if counts is not None:
                counts.ast_digest_checks += 1
            provenance = ast_record.provenance
            if (not _exact_json(details["captured_ast"], _freeze(ast_record.to_dict()))
                    or cid_for_structured(ast_record.to_dict()) != unit.ast_cid
                    or provenance.source_cid != entry.source_cid or provenance.path != entry.path
                    or provenance.repository_id != replay._head.repository_id
                    or provenance.revision != binding["source_revision"]
                    or provenance.repository_tree_cid != replay._head.snapshot_cid):
                raise CodebaseTargetError("embedded AST does not bind the captured resume source")
        elif unit.ast_cid is not None:
            raise CodebaseTargetError("captured AST is missing")
        if counts is not None:
            counts.authored_contract_replays += 1
        specs = _specs([ContractSpec(**row) for row in details["authored_contracts"]], limits)
        if not _exact_json(details["authored_contracts"], _freeze([item.to_dict() for item in specs])):
            raise CodebaseTargetError("authored contract fields are not canonical")
        if counts is not None:
            counts.native_lowering_replays += 1
        rebuilt = _prepare_bound(binding=binding, manifest=replay._manifest, receipt=replay._receipt,
                                 ast_record=ast_record, raw=raw, specs=specs, limits=limits)
    except CodebaseTargetError:
        raise
    except (KeyError, TypeError, ValueError, RecursionError, UnicodeError) as exc:
        raise CodebaseTargetError("malformed native resume CodebaseIR target binding") from exc
    if counts is not None:
        counts.full_target_comparisons += 1
    if rebuilt.canonical_bytes != target.canonical_bytes:
        raise CodebaseTargetError("resume CodebaseIR target native replay differs")
    if counts is not None:
        counts.target_replays += 1
        counts.shared_manifest_parses_avoided += 1
        counts.shared_receipt_parses_avoided += 1
    # Native lowering can leave collectable frame cycles. Release this row's
    # large input and reconstructed dictionaries even if a frame outlives the
    # call; the returned immutable envelope remains owned by the caller.
    try:
        return rebuilt
    finally:
        del target, rebuilt, value, details, binding, expected_binding, ast_record, raw


__all__ = [
    "SHARED_INVENTORY_SCHEMA", "COMPACT_TARGET_SCHEMA", "MAX_INVENTORY_ENTRIES",
    "MAX_SOURCE_BYTES", "MAX_SHARED_BYTES", "MAX_RECEIPT_BYTES", "MAX_TARGET_BYTES",
    "CodebaseInventoryError", "InventoryReplayCounters", "ValidatedResumeInventory",
    "NativeResumeReplay", "create_resume_shared_inventory", "validate_resume_shared_inventory",
    "compact_resume_target", "restore_resume_target", "prepare_resume_replay", "validate_resume_target",
]
