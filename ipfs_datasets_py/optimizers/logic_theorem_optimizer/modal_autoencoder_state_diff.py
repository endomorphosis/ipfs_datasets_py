"""Bounded, exact endpoint diffs for privately owned native training states.

This is shadow evidence, not mutation capture or candidate authority. The caller
must exclusively own the endpoints. Active transactions and observed revision
changes reject capture; these checks are not synchronization against arbitrary
concurrent or untracked writes. Native identity hashing may populate its cache.

All 38 raw fields are charged in the patch codec's typed JSON representation,
including every repeated occurrence. One component is limited to 64 MiB and one
state to 256 MiB. These are encoded-size/work bounds, not an RSS guarantee. The
existing patch codec additionally limits the emitted artifact to 64 MiB and its
changed entries to one million. No global cache, file IO, or supplied-state
mutation/replay occurs here. Existing patch and sparse-checkpoint schemas stay
unchanged.
"""

from __future__ import annotations

import hashlib
import math
import struct
import time
from dataclasses import dataclass
from typing import Any, Mapping

from . import modal_autoencoder_patch_codec as codec
from .modal_autoencoder_state_transaction import (
    ModalAutoencoderStatePatch, TouchedComponent, TouchedRow,
)
from .modal_autoencoder_state_version import _TrackedDict, _TrackedList


PROFILE = "modal-autoencoder-raw-typed-endpoints-v1"
MAX_COMPONENT_BYTES = 64 * 1024 * 1024
MAX_STATE_BYTES = 256 * 1024 * 1024


class StateDiffError(ValueError):
    """An unsupported, changing, or over-budget endpoint cannot be captured."""


@dataclass(frozen=True)
class EndpointPatch:
    data: bytes
    report: dict[str, Any]


class _TypedCopy:
    """Copy native values while emitting exactly codec._json(_encode_value())."""

    def __init__(self, maximum: int, *, copy_values: bool):
        self.maximum = maximum
        self.copy_values = copy_values
        self.data = bytearray()

    def emit(self, value: bytes) -> None:
        if len(value) > self.maximum - len(self.data):
            raise StateDiffError("typed component/state byte bound exceeded")
        self.data.extend(value)

    def string(self, value: str) -> None:
        # Chunking avoids first allocating a potentially six-times-expanded
        # escaped string before checking its encoded byte budget.
        self.emit(b'"')
        for offset in range(0, len(value), 4096):
            self.emit(codec._json(value[offset:offset + 4096])[1:-1])
        self.emit(b'"')

    def visit(self, value: Any, depth: int = 0) -> Any:
        if depth > codec.MAX_VALUE_DEPTH:
            raise StateDiffError("typed value exceeds maximum nesting depth")
        kind = type(value)
        if value is None:
            self.emit(b'["null"]')
        elif kind is bool:
            self.emit(b'["bool",true]' if value else b'["bool",false]')
        elif kind is int:
            if value.bit_length() > 4096:
                raise StateDiffError("integer value exceeds bound")
            self.emit(b'["int","' + str(value).encode("ascii") + b'"]')
        elif kind is float:
            if not math.isfinite(value):
                raise StateDiffError("non-finite floats are unsupported")
            self.emit(b'["float64","' + struct.pack(">d", value).hex().encode("ascii") + b'"]')
        elif kind is str:
            self.emit(b'["str",')
            self.string(value)
            self.emit(b']')
        elif kind in (dict, _TrackedDict):
            self.emit(b'["dict",[')
            result = {} if self.copy_values else None
            for index, (key, item) in enumerate(dict.items(value)):
                if index:
                    self.emit(b',')
                self.emit(b'[')
                copied_key = self.visit(key, depth + 1)
                self.emit(b',')
                copied_item = self.visit(item, depth + 1)
                self.emit(b']')
                if self.copy_values:
                    result[copied_key] = copied_item
            self.emit(b']]')
            return result
        elif kind in (list, _TrackedList, tuple):
            self.emit(b'["tuple",[' if kind is tuple else b'["list",[')
            result = [] if self.copy_values else None
            for index, item in enumerate(value):
                if index:
                    self.emit(b',')
                copied = self.visit(item, depth + 1)
                if self.copy_values:
                    result.append(copied)
            self.emit(b']]')
            return tuple(result) if self.copy_values and kind is tuple else result
        else:
            raise StateDiffError(f"unsupported native field value: {kind.__name__}")
        return value if self.copy_values else None


def _native_fields(state: Any) -> tuple[str, ...]:
    from .modal_autoencoder import (
        MODAL_AUTOENCODER_STATE_COMPONENT_FIELDS, ModalAutoencoderTrainingState,
    )
    if type(state) is not ModalAutoencoderTrainingState:
        raise StateDiffError("endpoint must be an exact native training state")
    names = tuple(MODAL_AUTOENCODER_STATE_COMPONENT_FIELDS)
    if len(names) != 38 or len(set(names)) != 38 or not set(names) <= vars(state).keys():
        raise StateDiffError("native component inventory differs from the 38-field profile")
    return names


def _guard(state: Any, revision: int | None = None) -> int:
    if vars(state).get("_active_state_transaction") is not None:
        raise StateDiffError("endpoint has an active transaction")
    current = state.state_revision
    if type(current) is not int or not 0 <= current < 2**63:
        raise StateDiffError("endpoint revision must be a nonnegative int64")
    if revision is not None and current != revision:
        raise StateDiffError("endpoint mutated during capture")
    return current


def _snapshot(state: Any) -> tuple[dict, float]:
    names = _native_fields(state)
    revision = _guard(state)
    components = {}
    total = 0
    hash_seconds = 0.0
    try:
        for name in names:
            encoder = _TypedCopy(min(MAX_COMPONENT_BYTES, MAX_STATE_BYTES - total),
                                 copy_values=False)
            encoder.visit(vars(state)[name])
            size = len(encoder.data)
            started = time.perf_counter()
            digest = hashlib.sha256(encoder.data).hexdigest()
            hash_seconds += time.perf_counter() - started
            components[name] = {"sha256": digest, "encoded_bytes": size}
            total += size
            _guard(state, revision)
        plain = state.state_identity_record().to_dict()
        _guard(state, revision)
        if plain["revision"] != revision or set(plain["component_digests"]) != set(names):
            raise StateDiffError("native identity inventory or revision differs")
        raw_identity = {"profile": PROFILE, "components": components}
        snapshot = {"profile": PROFILE, "component_fields": list(names),
                    "component_count": len(names), "components": components,
                    "total_encoded_bytes": total, "state_revision": revision,
                    "plain_identity": plain,
                    "raw_state_sha256": hashlib.sha256(codec._json(raw_identity)).hexdigest()}
        return snapshot, hash_seconds
    except (RuntimeError, RecursionError) as exc:
        raise StateDiffError("endpoint changed or exceeded traversal bounds") from exc


def exact_state_snapshot(state: Any) -> dict[str, Any]:
    """Return deterministic raw typed identities, sizes, and native identity.

    Raw hashes include key types/order and float bits. They deliberately do not
    use the native proof-head normalizer. The raw aggregate excludes revision;
    the separately recorded revision and complete snapshot bind that counter.
    """
    return _snapshot(state)[0]


def _typed(value: Any) -> bytearray:
    encoder = _TypedCopy(MAX_COMPONENT_BYTES, copy_values=False)
    encoder.visit(value)
    return encoder.data


def capture_endpoint_patch(
    base: Any, result: Any, *, base_version_id: str, sequence: int = 0,
    provenance: Mapping[str, Any] | None = None,
) -> EndpointPatch:
    """Diff endpoints without mutating either; encode the existing v1 patch.

    This captures the difference of sealed endpoints, not an intervening write
    history. A revision-only transition carries an unchanged architecture field
    witness because existing empty patches cannot advance revisions. The report
    distinguishes that witness from actually changed components.
    """
    started = time.perf_counter()
    if type(base_version_id) is not str or not 1 <= len(base_version_id) <= 256:
        raise StateDiffError("base_version_id must be a bounded nonempty string")
    if type(sequence) is not int or not 0 <= sequence < 2**63:
        raise StateDiffError("sequence must be a nonnegative int64")
    if provenance is not None and type(provenance) is not dict:
        raise StateDiffError("provenance must be a native dict")
    provenance_copy = _TypedCopy(codec.MAX_PATCH_BYTES, copy_values=True)
    sealed_provenance = provenance_copy.visit(provenance if provenance is not None else {})
    del provenance_copy
    _native_fields(base)
    _native_fields(result)
    base_revision, result_revision = _guard(base), _guard(result)
    if result_revision < base_revision:
        raise StateDiffError("result revision precedes base revision")
    scan_started = time.perf_counter()
    before, before_hash = _snapshot(base)
    after, after_hash = _snapshot(result)
    scan_seconds = time.perf_counter() - scan_started
    _guard(base, base_revision)
    _guard(result, result_revision)
    diff_started = time.perf_counter()
    rows, components, changed, row_names, replacements = [], [], [], [], []

    def append_row(row: TouchedRow) -> None:
        if len(rows) + len(components) >= codec.MAX_PATCH_ENTRIES:
            raise StateDiffError("patch entry count exceeds bound")
        rows.append(row)

    for name in before["component_fields"]:
        if before["components"][name] == after["components"][name]:
            continue
        changed.append(name)
        old, new = vars(base)[name], vars(result)[name]
        use_rows = type(old) in (dict, _TrackedDict) and type(new) in (dict, _TrackedDict)
        if use_rows:
            # Assignment retains the actual old key object for equal keys.
            # Thus this also catches aliases such as int1/boolTrue or +/-0.
            predicted = [key for key in old if key in new]
            predicted.extend(key for key in new if key not in old)
            use_rows = _typed(predicted) == _typed(list(new))
        if not use_rows:
            components.append(TouchedComponent(name, old, new, base_revision))
            replacements.append(name)
        else:
            row_names.append(name)
            for key, value in old.items():
                if key not in new:
                    append_row(TouchedRow(name, key, True, value, False, None, base_revision))
            for key, value in new.items():
                existed = key in old
                if not existed or _typed(old[key]) != _typed(value):
                    append_row(TouchedRow(name, key, existed, old[key] if existed else None,
                                          True, value, base_revision))
        if len(rows) + len(components) > codec.MAX_PATCH_ENTRIES:
            raise StateDiffError("patch entry count exceeds bound")
    revision_only = not changed and result_revision != base_revision
    witness = "architecture_version" if revision_only else None
    if witness:
        components.append(TouchedComponent(witness, vars(base)[witness],
                                           vars(result)[witness], base_revision))
    diff_seconds = time.perf_counter() - diff_started
    patch = ModalAutoencoderStatePatch(base_revision, result_revision, tuple(rows), tuple(components))
    encode_started = time.perf_counter()
    data = codec.encode_patch(patch, base_state_identity=before["plain_identity"]["digest"],
                              result_state_identity=after["plain_identity"]["digest"],
                              base_version_id=base_version_id, sequence=sequence,
                              provenance=sealed_provenance)
    encode_seconds = time.perf_counter() - encode_started
    _guard(base, base_revision)
    _guard(result, result_revision)
    report = {"profile": PROFILE, "base_snapshot": before, "result_snapshot": after,
              "changed_components": changed, "row_component_names": row_names,
              "component_replacements": replacements, "revision_only": revision_only,
              "revision_witness_component": witness,
              "counts": {"changed_component_count": len(changed),
                         "touched_row_count": len(rows), "touched_component_count": len(components),
                         "inserted_rows": sum(not row.before_exists for row in rows),
                         "deleted_rows": sum(not row.after_exists for row in rows),
                         "revision_witness_count": int(revision_only)},
              "patch_sha256": hashlib.sha256(data).hexdigest(), "patch_bytes": len(data),
              "limits": {"max_component_bytes": MAX_COMPONENT_BYTES,
                         "max_state_bytes": MAX_STATE_BYTES,
                         "max_patch_bytes": codec.MAX_PATCH_BYTES,
                         "max_patch_entries": codec.MAX_PATCH_ENTRIES,
                         "max_value_depth": codec.MAX_VALUE_DEPTH},
              "timings": {"scan_seconds": scan_seconds, "hash_seconds": before_hash + after_hash,
                          "diff_seconds": diff_seconds, "encode_seconds": encode_seconds,
                          "total_seconds": time.perf_counter() - started,
                          "hash_seconds_are_subset_of_scan_seconds": True},
              "scope": "endpoint_shadow_only", "admitted": False}
    return EndpointPatch(data, report)


__all__ = ["PROFILE", "MAX_COMPONENT_BYTES", "MAX_STATE_BYTES", "StateDiffError",
           "EndpointPatch", "exact_state_snapshot", "capture_endpoint_patch"]
