"""Portable, checksummed postimages for accepted sparse training mutations.

Only touched rows and replaced components are serialized. Values use a closed
typed JSON encoding: float64 bits, typed keys, mapping order and absent/empty
distinctions survive without pickle or imports supplied by an artifact. Base
and result identities use the existing normalized state-identity contract;
they are not hashes of JSON checkpoint bytes. The caller additionally binds
the immutable base version and verifies the complete candidate during rollout.

Existing state identity calculation may hash entire dirty components. Encoding
is proportional to the patch; replay explicitly performs that identity work.
No file writes, training, database registration or admission occurs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
import math
import re
import struct
import time
from typing import Any, Mapping

from .modal_autoencoder_state_transaction import (
    MODAL_AUTOENCODER_STATE_TRANSACTION_SCHEMA_VERSION,
    ModalAutoencoderStatePatch,
    TouchedComponent,
    TouchedRow,
)


SCHEMA = "modal-autoencoder-accepted-row-postimages/v1"
IDENTITY_PROFILE = "existing-normalized-component-state-identity"
MAX_PATCH_BYTES = 64 * 1024 * 1024
MAX_VALUE_DEPTH = 64
MAX_PATCH_ENTRIES = 1_000_000
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class PatchCodecError(ValueError):
    """Unsupported, malformed, corrupt or stale sparse patch."""


def _json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, allow_nan=False,
                      sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value)).hexdigest()


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise PatchCodecError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _integer(value: Any, label: str) -> int:
    if type(value) is not int or not 0 <= value < 2**63:
        raise PatchCodecError(f"{label} must be a nonnegative int64")
    return value


def _keys(value: Any, expected: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise PatchCodecError(f"{label} has missing or unknown fields")
    return value


@lru_cache(maxsize=1)
def _components() -> frozenset[str]:
    # Lazy to avoid importing the optimizer while its sink is being defined.
    from .modal_autoencoder import MODAL_AUTOENCODER_STATE_COMPONENT_FIELDS
    return frozenset(MODAL_AUTOENCODER_STATE_COMPONENT_FIELDS)


def _component(value: Any) -> str:
    if not isinstance(value, str) or value not in _components():
        raise PatchCodecError("unknown state component")
    return value


def _encode_value(value: Any, depth: int = 0) -> list[Any]:
    if depth > MAX_VALUE_DEPTH:
        raise PatchCodecError("value exceeds maximum nesting depth")
    if value is None:
        return ["null"]
    if type(value) is bool:
        return ["bool", value]
    if type(value) is int:
        if value.bit_length() > 4096:
            raise PatchCodecError("integer value exceeds bound")
        return ["int", str(value)]
    if type(value) is float:
        if not math.isfinite(value):
            raise PatchCodecError("non-finite floats are unsupported")
        return ["float64", struct.pack(">d", value).hex()]
    if type(value) is str:
        return ["str", value]
    if isinstance(value, Mapping):
        return ["dict", [[_encode_value(key, depth + 1), _encode_value(item, depth + 1)]
                         for key, item in value.items()]]
    if isinstance(value, (list, tuple)):
        return ["tuple" if isinstance(value, tuple) else "list",
                [_encode_value(item, depth + 1) for item in value]]
    raise PatchCodecError(f"unsupported value type: {type(value).__name__}")


def _decode_value(value: Any, depth: int = 0) -> Any:
    if depth > MAX_VALUE_DEPTH or not isinstance(value, list) or not value:
        raise PatchCodecError("invalid typed value or nesting depth")
    kind = value[0]
    if kind == "null" and len(value) == 1:
        return None
    if len(value) != 2:
        raise PatchCodecError("invalid typed value arity")
    raw = value[1]
    if kind == "bool" and type(raw) is bool:
        return raw
    if kind == "str" and type(raw) is str:
        return raw
    if kind == "int" and type(raw) is str and len(raw) <= 1235:
        if re.fullmatch(r"0|-?[1-9][0-9]*", raw):
            number = int(raw)
            if number.bit_length() <= 4096:
                return number
    if kind == "float64" and type(raw) is str and re.fullmatch(r"[0-9a-f]{16}", raw):
        number = struct.unpack(">d", bytes.fromhex(raw))[0]
        if math.isfinite(number):
            return number
    if kind in ("list", "tuple") and isinstance(raw, list):
        values = [_decode_value(item, depth + 1) for item in raw]
        return tuple(values) if kind == "tuple" else values
    if kind == "dict" and isinstance(raw, list):
        result = {}
        for pair in raw:
            if not isinstance(pair, list) or len(pair) != 2:
                raise PatchCodecError("invalid mapping entry")
            key = _decode_value(pair[0], depth + 1)
            try:
                if key in result:
                    raise PatchCodecError("duplicate decoded mapping key")
                result[key] = _decode_value(pair[1], depth + 1)
            except TypeError as exc:
                raise PatchCodecError("unhashable mapping key") from exc
        return result
    raise PatchCodecError("invalid or unsupported typed value")


def _before_digest(exists: bool, value: Any) -> str:
    return _digest([exists, _encode_value(value) if exists else ["null"]])


@dataclass(frozen=True)
class PortableStatePatch:
    """A decoded, identity-bound postimage segment; before values are hashes."""

    base_version_id: str
    sequence: int
    base_state_identity: str
    result_state_identity: str
    patch: ModalAutoencoderStatePatch
    before_row_digests: tuple[str, ...]
    before_component_digests: tuple[str, ...]
    provenance: Mapping[str, Any]
    payload_sha256: str


def _payload(segment: PortableStatePatch) -> dict[str, Any]:
    patch = segment.patch
    if patch.schema_version != MODAL_AUTOENCODER_STATE_TRANSACTION_SCHEMA_VERSION:
        raise PatchCodecError("unsupported transaction schema")
    if not isinstance(segment.base_version_id, str) or not 1 <= len(segment.base_version_id) <= 256:
        raise PatchCodecError("base_version_id must be a bounded nonempty string")
    _integer(segment.sequence, "sequence")
    _sha(segment.base_state_identity, "base_state_identity")
    _sha(segment.result_state_identity, "result_state_identity")
    _integer(patch.base_revision, "base_revision")
    _integer(patch.result_revision, "result_revision")
    if patch.result_revision < patch.base_revision:
        raise PatchCodecError("result revision precedes base revision")
    if not patch.rows and not patch.components and patch.result_revision != patch.base_revision:
        raise PatchCodecError("empty patch cannot advance the revision")
    if len(patch.rows) + len(patch.components) > MAX_PATCH_ENTRIES:
        raise PatchCodecError("patch entry count exceeds bound")
    if len(patch.rows) != len(segment.before_row_digests) or len(patch.components) != len(segment.before_component_digests):
        raise PatchCodecError("before digest count differs from patch entries")
    seen_components: set[str] = set()
    components = []
    for change, before in zip(patch.components, segment.before_component_digests):
        name = _component(change.component)
        if name in seen_components or change.prior_revision != patch.base_revision:
            raise PatchCodecError("duplicate component or inconsistent prior revision")
        seen_components.add(name)
        components.append({"component": name, "before_sha256": _sha(before, "before_sha256"),
                           "after_value": _encode_value(change.after_value)})
    seen_rows = set()
    rows = []
    for change, before in zip(patch.rows, segment.before_row_digests):
        name = _component(change.component)
        if name in seen_components or change.prior_revision != patch.base_revision:
            raise PatchCodecError("overlapping component/row or inconsistent prior revision")
        try:
            marker = (name, change.key)
            if marker in seen_rows:
                raise PatchCodecError("duplicate row")
            seen_rows.add(marker)
        except TypeError as exc:
            raise PatchCodecError("unhashable row key") from exc
        if type(change.before_exists) is not bool or type(change.after_exists) is not bool:
            raise PatchCodecError("row presence must be boolean")
        if not change.after_exists and change.after_value is not None:
            raise PatchCodecError("deleted row has an after value")
        rows.append({"component": name, "key": _encode_value(change.key),
                     "before_exists": change.before_exists, "before_sha256": _sha(before, "before_sha256"),
                     "after_exists": change.after_exists, "after_value": _encode_value(change.after_value)})
    if not isinstance(segment.provenance, Mapping):
        raise PatchCodecError("provenance must be a mapping")
    return {"schema": SCHEMA, "identity_profile": IDENTITY_PROFILE,
            "transaction_schema": patch.schema_version,
            "base_version_id": segment.base_version_id, "sequence": segment.sequence,
            "base_state_identity": segment.base_state_identity, "result_state_identity": segment.result_state_identity,
            "base_revision": patch.base_revision, "result_revision": patch.result_revision,
            "rows": rows, "components": components, "provenance": _encode_value(segment.provenance)}


def encode_patch(
    patch: ModalAutoencoderStatePatch, *, base_state_identity: str,
    result_state_identity: str, base_version_id: str, sequence: int,
    provenance: Mapping[str, Any] | None = None,
) -> bytes:
    """Encode touched postimages without cloning, diffing or hashing a state."""
    if not isinstance(patch, ModalAutoencoderStatePatch):
        raise PatchCodecError("expected a captured state patch")
    segment = PortableStatePatch(
        base_version_id, sequence, base_state_identity, result_state_identity, patch,
        tuple(_before_digest(row.before_exists, row.before_value) for row in patch.rows),
        tuple(_before_digest(True, component.before_value) for component in patch.components),
        provenance if provenance is not None else {}, "",
    )
    payload = _payload(segment)
    result = _json({"payload": payload, "payload_sha256": _digest(payload)})
    if len(result) > MAX_PATCH_BYTES:
        raise PatchCodecError("encoded patch exceeds byte bound")
    return result


def _unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise PatchCodecError("duplicate JSON field")
        result[key] = value
    return result


def decode_patch(data: bytes) -> PortableStatePatch:
    """Validate framing, checksum, safe types and closed component vocabulary."""
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_PATCH_BYTES:
        raise PatchCodecError("patch must be bounded nonempty bytes")
    try:
        envelope = json.loads(data, object_pairs_hook=_unique_fields,
                              parse_constant=lambda _: (_ for _ in ()).throw(PatchCodecError("non-finite JSON")))
        _keys(envelope, {"payload", "payload_sha256"}, "envelope")
        if _json(envelope) != data:
            raise PatchCodecError("patch is not canonically encoded")
        payload = _keys(envelope["payload"], {
            "schema", "identity_profile", "transaction_schema", "base_version_id", "sequence",
            "base_state_identity", "result_state_identity", "base_revision", "result_revision",
            "rows", "components", "provenance",
        }, "payload")
        digest = _sha(envelope["payload_sha256"], "payload_sha256")
        if _digest(payload) != digest:
            raise PatchCodecError("patch checksum mismatch")
        if payload["schema"] != SCHEMA or payload["identity_profile"] != IDENTITY_PROFILE:
            raise PatchCodecError("unsupported patch schema or identity profile")
        rows, components = payload["rows"], payload["components"]
        if not isinstance(rows, list) or not isinstance(components, list):
            raise PatchCodecError("patch entries must be arrays")
        if len(rows) + len(components) > MAX_PATCH_ENTRIES:
            raise PatchCodecError("patch entry count exceeds bound")
        row_changes, component_changes, row_digests, component_digests = [], [], [], []
        revision = _integer(payload["base_revision"], "base_revision")
        for raw in rows:
            row = _keys(raw, {"component", "key", "before_exists", "before_sha256", "after_exists", "after_value"}, "row")
            row_changes.append(TouchedRow(row["component"], _decode_value(row["key"]), row["before_exists"],
                                          None, row["after_exists"], _decode_value(row["after_value"]), revision))
            row_digests.append(row["before_sha256"])
        for raw in components:
            component = _keys(raw, {"component", "before_sha256", "after_value"}, "component")
            component_changes.append(TouchedComponent(component["component"], None,
                                                       _decode_value(component["after_value"]), revision))
            component_digests.append(component["before_sha256"])
        patch = ModalAutoencoderStatePatch(revision, payload["result_revision"], tuple(row_changes),
                                          tuple(component_changes), payload["transaction_schema"])
        segment = PortableStatePatch(payload["base_version_id"], payload["sequence"], payload["base_state_identity"],
                                     payload["result_state_identity"], patch, tuple(row_digests), tuple(component_digests),
                                     _decode_value(payload["provenance"]), digest)
        if _payload(segment) != payload:
            raise PatchCodecError("noncanonical typed payload")
        return segment
    except (UnicodeError, json.JSONDecodeError, RecursionError, OverflowError) as exc:
        raise PatchCodecError("invalid JSON patch") from exc


def replay_patch(
    state: Any, segment: PortableStatePatch | bytes, *, expected_base_version_id: str,
    expected_sequence: int | None = None,
) -> dict[str, Any]:
    """Replay exact postimages transactionally after identity/before checks.

    The revision is never silently rebased. A fresh JSON base must have the same
    initial revision used by the worker, or prior segments must reconstruct it.
    Raises on any mismatch; the caller retains the full candidate qualification
    check because the existing logical identity normalizes some components.
    """
    if isinstance(segment, bytes):
        segment = decode_patch(segment)
    if not isinstance(segment, PortableStatePatch):
        raise PatchCodecError("expected a portable state patch")
    if _digest(_payload(segment)) != segment.payload_sha256:
        raise PatchCodecError("decoded patch was mutated")
    if segment.base_version_id != expected_base_version_id:
        raise PatchCodecError("base version mismatch")
    if expected_sequence is not None and segment.sequence != expected_sequence:
        raise PatchCodecError("patch sequence mismatch")
    patch = segment.patch
    hashing_seconds = 0.0
    transaction = state.transaction(label=f"portable-patch-replay:{segment.sequence}").begin()
    try:
        if state.state_revision != patch.base_revision:
            raise PatchCodecError("base revision mismatch")
        started = time.perf_counter()
        identity = state.state_identity()
        hashing_seconds += time.perf_counter() - started
        if identity != segment.base_state_identity:
            raise PatchCodecError("base state identity mismatch")
        for row, before in zip(patch.rows, segment.before_row_digests):
            mapping = getattr(state, row.component)
            if not isinstance(mapping, Mapping):
                raise PatchCodecError("row component is not a mapping")
            exists = row.key in mapping
            if exists != row.before_exists or _before_digest(exists, mapping[row.key] if exists else None) != before:
                raise PatchCodecError("row before-image mismatch")
        for component, before in zip(patch.components, segment.before_component_digests):
            if _before_digest(True, getattr(state, component.component)) != before:
                raise PatchCodecError("component before-image mismatch")
        patch.apply(transaction)
        # Check exact postimages as well as the existing normalized identity.
        for row in patch.rows:
            mapping = getattr(state, row.component)
            exists = row.key in mapping
            if exists != row.after_exists or _before_digest(exists, mapping[row.key] if exists else None) != _before_digest(row.after_exists, row.after_value):
                raise PatchCodecError("row after-image mismatch")
        for component in patch.components:
            if _before_digest(True, getattr(state, component.component)) != _before_digest(True, component.after_value):
                raise PatchCodecError("component after-image mismatch")
        started = time.perf_counter()
        result_identity = state.state_identity()
        hashing_seconds += time.perf_counter() - started
        if result_identity != segment.result_state_identity or state.state_revision != patch.result_revision:
            raise PatchCodecError("result state identity or revision mismatch")
        transaction.commit()
    except BaseException:
        if transaction.active:
            transaction.rollback()
        raise
    return {"schema": SCHEMA, "sequence": segment.sequence, "payload_sha256": segment.payload_sha256,
            "base_state_identity": segment.base_state_identity, "result_state_identity": result_identity,
            "base_revision": patch.base_revision, "result_revision": patch.result_revision,
            "touched_row_count": len(patch.rows), "touched_component_count": len(patch.components),
            "identity_hashing_seconds": hashing_seconds, "identity_hashing_scope": "dirty_components_not_touched_rows",
            "admitted": False}


__all__ = ["SCHEMA", "IDENTITY_PROFILE", "MAX_PATCH_BYTES", "PatchCodecError",
           "PortableStatePatch", "encode_patch", "decode_patch", "replay_patch"]
