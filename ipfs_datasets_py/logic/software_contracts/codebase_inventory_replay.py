"""Exact native target replay with one receiver-owned inventory snapshot.

This additive path reuses the native manifest, publication receipt and indexed
membership already independently validated at the receiving boundary.  Source
bytes, AST provenance, authored contracts, native lowering, bridge results,
frontiers and the complete canonical target are still replayed for every row.
The token is local to one bounded operation; it establishes no live-source,
producer-execution, semantic, proof, training or tool authority.
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
    CodebaseTargetError, CodebaseTargetLimits, _VALIDATOR, _binding,
    _prepare_bound, _specs, _wire,
)
from .codebase_inventory_targets import (
    CodebaseInventoryError, CodebaseInventoryLimits, ValidatedInventoryEnvelope, _validated,
)
from .content import cid_for_bytes, cid_for_structured
from ..formalization.autoencoder.domain_targets import DomainTargetEnvelope
from ..software_verification.pipeline import ContractSpec

_TOKEN = object()
_MAX_SHARED_BYTES = 16 * 1024 * 1024
_SHARED_FIELDS = frozenset({"schema", "head", "manifest", "publication_receipt", "shared_sha256"})


@dataclass(slots=True)
class InventoryReplayCounters:
    """Observed operations; counters do not attest original producer execution.

    Avoided parse counts compare completed rows with the unchanged single-row
    native validator.  They exclude the initial shared transport validation.
    Lowering and full-target comparisons count attempted operations; completed
    target replay is counted only after canonical equality succeeds.
    """

    shared_replay_preparations: int = 0
    target_replay_attempts: int = 0
    target_replays: int = 0
    source_digest_checks: int = 0
    ast_digest_checks: int = 0
    authored_contract_replays: int = 0
    native_lowering_replays: int = 0
    full_target_comparisons: int = 0
    shared_manifest_parses_avoided: int = 0
    shared_receipt_parses_avoided: int = 0

    def to_dict(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


def _counters(value: InventoryReplayCounters | None) -> InventoryReplayCounters | None:
    if value is not None and (type(value) is not InventoryReplayCounters
            or any(type(getattr(value, name)) is not int or getattr(value, name) < 0
                   for name in InventoryReplayCounters.__dataclass_fields__)):
        raise CodebaseInventoryError("native nonnegative exact inventory replay counters required")
    return value


def _freeze(value: Any) -> Any:
    if type(value) is dict:
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if type(value) is list:
        return tuple(_freeze(child) for child in value)
    return value


def _exact_json(actual: Any, expected: Any) -> bool:
    """Compare canonical primitive types as well as values without reserializing.

    Python equality treats ``False == 0`` and ``1 == 1.0`` as true.  The shared
    declaration is immutable canonical JSON, so those changes must be refused.
    The caller already bounded the serialized input before this traversal.
    """
    pending = [(actual, expected)]
    while pending:
        left, right = pending.pop()
        if isinstance(right, Mapping):
            if type(left) is not dict or left.keys() != right.keys():
                return False
            pending.extend((left[key], child) for key, child in right.items())
        elif type(right) is tuple:
            if type(left) is not list or len(left) != len(right):
                return False
            pending.extend(zip(left, right))
        elif type(left) is not type(right) or left != right:
            return False
    return True


@dataclass(frozen=True, slots=True)
class NativeInventoryReplay:
    """Boundary-local token backed by immutable native records and JSON bytes."""

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
    _token: object = field(repr=False, compare=False)


def prepare_inventory_replay(
    shared: ValidatedInventoryEnvelope, *, counters: InventoryReplayCounters | None = None,
) -> NativeInventoryReplay:
    """Reuse exactly one independently validated native receiver declaration.

    Arbitrary public dataclass construction cannot supply the private transport
    token.  Detached transport dictionaries are not retained.  The native
    records have frozen dataclasses, tuples and recursively frozen metadata;
    the canonical snapshot is checked against them before reuse.
    """
    from ipfs_datasets_py.duckdb_control.codebase_catalog import (
        CodebaseHead, CodebasePublicationReceipt,
    )
    counts = _counters(counters)
    if type(shared) is not ValidatedInventoryEnvelope:
        raise CodebaseInventoryError("boundary-local ValidatedInventoryEnvelope required")
    token = _validated(shared)
    if (type(token.head) is not CodebaseHead or type(token.manifest) is not CodebaseIRManifest
            or type(token.receipt) is not CodebasePublicationReceipt):
        raise CodebaseInventoryError("independently validated exact native shared records required")
    raw = token.canonical_bytes
    if type(raw) is not bytes or len(raw) > _MAX_SHARED_BYTES:
        raise CodebaseInventoryError("bounded canonical shared inventory snapshot required")
    try:
        value = json.loads(raw)
        if (type(value) is not dict or set(value) != _SHARED_FIELDS
                or value["schema"] != "codebase-ir-shared-target-inventory@1"
                or _wire(value, _MAX_SHARED_BYTES) != raw
                or value["shared_sha256"] != token.shared_sha256):
            raise CodebaseInventoryError("shared inventory snapshot changed after boundary validation")
        payload = {name: child for name, child in value.items() if name != "shared_sha256"}
        if hashlib.sha256(_wire(payload, _MAX_SHARED_BYTES)).hexdigest() != token.shared_sha256:
            raise CodebaseInventoryError("shared inventory snapshot identity differs")
        for name, native in (("head", token.head), ("manifest", token.manifest),
                             ("publication_receipt", token.receipt)):
            if _wire(native.to_dict(), _MAX_SHARED_BYTES) != _wire(value[name], _MAX_SHARED_BYTES):
                raise CodebaseInventoryError("shared native records differ from their canonical snapshot")
        bounds = CodebaseInventoryLimits()
        if (token.manifest.cid != token.head.manifest_cid or token.receipt.head != token.head
                or token.manifest.snapshot.snapshot_cid != token.head.snapshot_cid
                or token.manifest.snapshot.repository_id != token.head.repository_id
                or token.manifest.ast_revision_id != token.head.ast_revision_id
                or token.manifest.snapshot.max_entries > bounds.max_entries
                or token.manifest.snapshot.max_file_bytes > bounds.max_source_bytes
                or len(token.manifest.snapshot.entries) > bounds.max_entries
                or len(_wire(value["publication_receipt"], _MAX_SHARED_BYTES)) > bounds.max_receipt_bytes):
            raise CodebaseInventoryError("shared native inventory publication binding differs")
        entries = {entry.source_key: entry for entry in token.manifest.snapshot.entries}
        units = {unit.source_key: unit for unit in token.manifest.units}
        if len(entries) != len(token.manifest.snapshot.entries) or set(entries) != set(units):
            raise CodebaseInventoryError("shared inventory does not bind complete exact membership")
        entry_values = {key: _freeze(entry.to_dict()) for key, entry in entries.items()}
        unit_values = {key: _freeze(unit.to_dict()) for key, unit in units.items()}
    except CodebaseTargetError:
        raise
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise CodebaseInventoryError("malformed canonical shared inventory snapshot") from exc
    result = NativeInventoryReplay(
        token.shared_sha256, len(entries), token.head, token.manifest, token.receipt,
        _freeze(value["head"]), _freeze(value["manifest"]), _freeze(value["publication_receipt"]),
        MappingProxyType(entries), MappingProxyType(units), MappingProxyType(entry_values),
        MappingProxyType(unit_values), _TOKEN,
    )
    if counts is not None:
        counts.shared_replay_preparations += 1
    return result


def validate_inventory_codebase_target(
    target: DomainTargetEnvelope, replay: NativeInventoryReplay, *,
    counters: InventoryReplayCounters | None = None,
) -> DomainTargetEnvelope:
    """Run unchanged native lowering and complete equality for one captured row.

    Shared native parsing and linear inventory membership scans are replaced by
    comparisons with the receiver-owned canonical snapshot and exact keyed
    membership.  Every row still reconstructs its complete native target.
    """
    counts = _counters(counters)
    if type(replay) is not NativeInventoryReplay or replay._token is not _TOKEN:
        raise CodebaseInventoryError("boundary-local native inventory replay token required")
    if type(target) is not DomainTargetEnvelope:
        raise CodebaseTargetError("native immutable DomainTargetEnvelope required")
    value = target.to_dict()
    _wire(value)
    if (value["domain_id"] != "codebase_ir" or len(value["validation"]) != 1
            or value["validation"][0].get("validator_id") != _VALIDATOR):
        raise CodebaseTargetError("exact native CodebaseIR target profile required")
    if counts is not None:
        counts.target_replay_attempts += 1
    details = value["validation"][0]["details"]
    try:
        limits = CodebaseTargetLimits(**details["limits"])
        binding = details["source_binding"]
        if (type(binding) is not dict
                or not _exact_json(details["manifest"], replay._manifest_value)
                or not _exact_json(details["publication_receipt"], replay._receipt_value)
                or not _exact_json(binding["head"], replay._head_value)):
            raise CodebaseTargetError("embedded shared native inventory binding differs")
        key = binding["source_key"]
        if type(key) is not str or key not in replay._entries:
            raise CodebaseTargetError("embedded source is outside the exact inventory")
        entry, unit = replay._entries[key], replay._units[key]
        if (not _exact_json(binding["entry"], replay._entry_values[key])
                or not _exact_json(binding["unit"], replay._unit_values[key])):
            raise CodebaseTargetError("embedded exact source/unit membership differs")
        raw_hex = details["source_bytes_hex"]
        if type(raw_hex) is not str or len(raw_hex) > limits.max_source_bytes * 2:
            raise CodebaseTargetError("bounded exact source hexadecimal required")
        raw = bytes.fromhex(raw_hex)
        if counts is not None:
            counts.source_digest_checks += 1
        if raw.hex() != raw_hex or cid_for_bytes(raw) != entry.source_cid or len(raw) != entry.size_bytes:
            raise CodebaseTargetError("embedded source bytes differ from the captured entry")
        expected_binding = _binding(replay._head, replay._manifest, entry, unit, raw)
        if _wire(expected_binding) != _wire(binding):
            raise CodebaseTargetError("embedded source/head/unit binding differs")
        ast_record = None if details["captured_ast"] is None else ASTRecord.from_dict(details["captured_ast"])
        if ast_record is not None:
            if counts is not None:
                counts.ast_digest_checks += 1
            provenance = ast_record.provenance
            if (cid_for_structured(ast_record.to_dict()) != unit.ast_cid
                    or provenance.source_cid != entry.source_cid or provenance.path != entry.path
                    or provenance.repository_id != replay._head.repository_id
                    or provenance.revision != binding["source_revision"]
                    or provenance.repository_tree_cid != replay._head.snapshot_cid):
                raise CodebaseTargetError("embedded AST does not bind the captured source")
        elif unit.ast_cid is not None:
            raise CodebaseTargetError("captured AST is missing")
        if counts is not None:
            counts.authored_contract_replays += 1
        specs = _specs([ContractSpec(**row) for row in details["authored_contracts"]], limits)
        if _wire([item.to_dict() for item in specs]) != _wire(details["authored_contracts"]):
            raise CodebaseTargetError("authored contract fields are not canonical")
        if counts is not None:
            counts.native_lowering_replays += 1
        rebuilt = _prepare_bound(binding=binding, manifest=replay._manifest, receipt=replay._receipt,
                                 ast_record=ast_record, raw=raw, specs=specs, limits=limits)
    except CodebaseTargetError:
        raise
    except (KeyError, TypeError, ValueError, UnicodeError) as exc:
        raise CodebaseTargetError("malformed native CodebaseIR target binding") from exc
    if counts is not None:
        counts.full_target_comparisons += 1
    if rebuilt.canonical_bytes != target.canonical_bytes:
        raise CodebaseTargetError("CodebaseIR target native replay differs")
    if counts is not None:
        counts.target_replays += 1
        counts.shared_manifest_parses_avoided += 1
        counts.shared_receipt_parses_avoided += 1
    return rebuilt


__all__ = ["InventoryReplayCounters", "NativeInventoryReplay", "prepare_inventory_replay",
           "validate_inventory_codebase_target"]
