"""Compact, checksummed checkpoints for modal-autoencoder training state.

The format is intentionally small and boring: a canonical JSON manifest, a
compressed canonical table index, and little-endian IEEE-754 numeric columns.
It never imports or executes objects from a checkpoint (unlike pickle), every
byte is checksummed, and all resource sizes are validated before allocation.

Delta logs concatenate independently checksummed containers.  A torn final
append is ignored (and may be truncated during recovery); corruption of a
complete segment is an error.  Each delta binds the base and result digests,
operational revisions, state schema, metric lineage, and full component digest
set, which makes omission and reordering fail closed.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import threading
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .modal_autoencoder_state_version import canonical_digest


MODAL_AUTOENCODER_CHECKPOINT_SCHEMA_VERSION = "modal-autoencoder-checkpoint-v1"
MODAL_AUTOENCODER_DELTA_SCHEMA_VERSION = "modal-autoencoder-checkpoint-delta-v1"
MODAL_AUTOENCODER_TABLE_SCHEMA_VERSION = "modal-autoencoder-numeric-tables-v1"

CHECKPOINT_MAGIC = b"LIRMAECP"
DELTA_MAGIC = b"LIRMAEDL"
CONTAINER_VERSION = 1
_HEADER = struct.Struct(">8sHHIQ32s32s")
_INDEX_LENGTH = struct.Struct(">I")
_FLOAT_FORMATS = {
    "float32": ("<f", 4, 7),
    "float64": ("<d", 8, 15),
}
_MAX_MANIFEST_BYTES = 4 * 1024 * 1024
_MAX_PAYLOAD_BYTES = 8 * 1024 * 1024 * 1024
_MAX_INDEX_BYTES = 512 * 1024 * 1024
_MAX_TABLE_VALUES = 1_000_000_000


class ModalAutoencoderCheckpointError(RuntimeError):
    """Base class for safe checkpoint failures."""


class CheckpointCorruptionError(ModalAutoencoderCheckpointError):
    """Raised when framing, lengths, or checksums are invalid."""


class CheckpointLineageError(ModalAutoencoderCheckpointError):
    """Raised when schema, revision, or identity lineage does not match."""


class UnsupportedCheckpointError(ModalAutoencoderCheckpointError):
    """Raised for a well-framed but unsupported checkpoint version."""


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_copy(value: Any) -> Any:
    """Copy supported JSON data while rejecting executable/custom values."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("checkpoint numeric values must be finite")
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_copy(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return [_canonical_copy(item) for item in value]
    raise TypeError(f"unsupported checkpoint value: {type(value).__name__}")


def _quantized_copy(value: Any, precision: str) -> Any:
    if isinstance(value, float):
        return quantize_float(value, precision)
    if isinstance(value, Mapping):
        return {str(key): _quantized_copy(item, precision) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_quantized_copy(item, precision) for item in value]
    return _canonical_copy(value)


def quantize_float(value: float, precision: str = "float64") -> float:
    """Return the exact value represented by the declared storage precision."""

    try:
        fmt, _width, _digits = _FLOAT_FORMATS[precision]
    except KeyError as exc:
        raise ValueError(f"unsupported float precision: {precision!r}") from exc
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("checkpoint numeric values must be finite")
    try:
        return struct.unpack(fmt, struct.pack(fmt, number))[0]
    except OverflowError as exc:
        raise ValueError(f"value {number!r} cannot be represented as {precision}") from exc


def _numeric_shape(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    if not value:
        return "empty_mapping"
    values = list(value.values())
    if all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in values):
        return "keyed_scalars"
    if all(
        isinstance(item, Sequence)
        and not isinstance(item, (str, bytes, bytearray))
        and all(isinstance(number, (int, float)) and not isinstance(number, bool) for number in item)
        for item in values
    ):
        return "keyed_vectors"
    if all(isinstance(item, Mapping) for item in values):
        leaves = list(_mapping_numeric_leaves(value))
        if leaves or all(not item for item in values):
            return "path_scalars"
    return ""


def _mapping_numeric_leaves(
    value: Mapping[str, Any],
    prefix: Tuple[str, ...] = (),
) -> Iterable[Tuple[Tuple[str, ...], float]]:
    for raw_key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
        path = (*prefix, str(raw_key))
        if isinstance(item, Mapping):
            yield from _mapping_numeric_leaves(item, path)
        elif isinstance(item, (int, float)) and not isinstance(item, bool):
            yield path, float(item)
        else:
            raise TypeError(f"non-numeric table leaf at {'.'.join(path)}")


def _mapping_empty_paths(
    value: Mapping[str, Any],
    prefix: Tuple[str, ...] = (),
) -> Iterable[Tuple[str, ...]]:
    for raw_key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
        path = (*prefix, str(raw_key))
        if isinstance(item, Mapping):
            if item:
                yield from _mapping_empty_paths(item, path)
            else:
                yield path


def _encode_state_payload(
    state_data: Mapping[str, Any],
    *,
    precision: str,
    component_digests: Mapping[str, str],
    include_components: Optional[Sequence[str]] = None,
) -> tuple[bytes, List[Dict[str, Any]]]:
    fmt, width, digits = _FLOAT_FORMATS.get(precision, (None, None, None))
    if fmt is None:
        raise ValueError(f"unsupported float precision: {precision!r}")
    selected = None if include_components is None else set(include_components)
    metadata: Dict[str, Any] = {}
    tables: List[Dict[str, Any]] = []
    numeric = bytearray()

    for name, raw_value in sorted(state_data.items()):
        if selected is not None and name not in selected:
            continue
        value = _canonical_copy(raw_value)
        shape = _numeric_shape(value)
        if not shape or shape == "empty_mapping":
            metadata[name] = value
            continue

        descriptor: Dict[str, Any] = {
            "byte_length": 0,
            "byte_offset": len(numeric),
            "dtype": precision,
            "encoding": shape,
            "field": name,
            "precision_digits": digits,
            "value_count": 0,
        }
        values: List[float]
        if shape == "keyed_scalars":
            descriptor["keys"] = [str(key) for key in sorted(value)]
            values = [float(value[key]) for key in sorted(value)]
        elif shape == "keyed_vectors":
            keys = [str(key) for key in sorted(value)]
            rows = [value[key] for key in sorted(value)]
            descriptor["keys"] = keys
            descriptor["row_lengths"] = [len(row) for row in rows]
            values = [float(number) for row in rows for number in row]
        else:
            leaves = list(_mapping_numeric_leaves(value))
            descriptor["paths"] = [list(path) for path, _number in leaves]
            descriptor["empty_paths"] = [
                list(path) for path in _mapping_empty_paths(value)
            ]
            values = [number for _path, number in leaves]

        packed = bytearray()
        for number in values:
            quantized = quantize_float(number, precision)
            packed.extend(struct.pack(fmt, quantized))
        descriptor["value_count"] = len(values)
        descriptor["byte_length"] = len(packed)
        numeric.extend(packed)
        tables.append(descriptor)

    index = {
        "component_digests": dict(sorted(component_digests.items())),
        "metadata": metadata,
        "schema_version": MODAL_AUTOENCODER_TABLE_SCHEMA_VERSION,
        "tables": tables,
    }
    index_bytes = _json_bytes(index)
    if len(index_bytes) > _MAX_INDEX_BYTES:
        raise ValueError("checkpoint table index exceeds safety limit")
    raw_payload = _INDEX_LENGTH.pack(len(index_bytes)) + index_bytes + bytes(numeric)
    return zlib.compress(raw_payload, level=9), tables


def _decode_state_payload(
    compressed: bytes,
    manifest: Mapping[str, Any],
) -> tuple[Dict[str, Any], Dict[str, str]]:
    try:
        raw = zlib.decompress(compressed)
    except zlib.error as exc:
        raise CheckpointCorruptionError("checkpoint payload is not valid zlib data") from exc
    if len(raw) < _INDEX_LENGTH.size:
        raise CheckpointCorruptionError("checkpoint payload is truncated")
    (index_length,) = _INDEX_LENGTH.unpack_from(raw)
    if index_length > _MAX_INDEX_BYTES or len(raw) < _INDEX_LENGTH.size + index_length:
        raise CheckpointCorruptionError("checkpoint table index length is invalid")
    index_start = _INDEX_LENGTH.size
    try:
        index = json.loads(raw[index_start : index_start + index_length])
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CheckpointCorruptionError("checkpoint table index is invalid JSON") from exc
    if not isinstance(index, Mapping) or index.get("schema_version") != MODAL_AUTOENCODER_TABLE_SCHEMA_VERSION:
        raise UnsupportedCheckpointError("unsupported checkpoint table schema")
    metadata = index.get("metadata")
    tables = index.get("tables")
    component_digests = index.get("component_digests")
    if not isinstance(metadata, Mapping) or not isinstance(tables, list) or not isinstance(component_digests, Mapping):
        raise CheckpointCorruptionError("checkpoint table index has invalid fields")
    result = _canonical_copy(metadata)
    numeric_start = index_start + index_length
    ranges: List[Tuple[int, int]] = []

    for descriptor in tables:
        if not isinstance(descriptor, Mapping):
            raise CheckpointCorruptionError("invalid numeric table descriptor")
        field_name = str(descriptor.get("field") or "")
        precision = str(descriptor.get("dtype") or "")
        if not field_name or field_name in result or precision not in _FLOAT_FORMATS:
            raise CheckpointCorruptionError("invalid or duplicate numeric table field")
        fmt, width, _digits = _FLOAT_FORMATS[precision]
        count = int(descriptor.get("value_count", -1))
        offset = int(descriptor.get("byte_offset", -1))
        byte_length = int(descriptor.get("byte_length", -1))
        if count < 0 or count > _MAX_TABLE_VALUES or offset < 0 or byte_length != count * width:
            raise CheckpointCorruptionError(f"invalid numeric table bounds for {field_name}")
        start = numeric_start + offset
        end = start + byte_length
        if end > len(raw):
            raise CheckpointCorruptionError(f"truncated numeric table {field_name}")
        ranges.append((offset, offset + byte_length))
        values = [item[0] for item in struct.iter_unpack(fmt, raw[start:end])]
        encoding = descriptor.get("encoding")
        if encoding == "keyed_scalars":
            keys = descriptor.get("keys")
            if not isinstance(keys, list) or len(keys) != count:
                raise CheckpointCorruptionError(f"invalid keys for {field_name}")
            result[field_name] = {str(key): value for key, value in zip(keys, values)}
        elif encoding == "keyed_vectors":
            keys = descriptor.get("keys")
            lengths = descriptor.get("row_lengths")
            if not isinstance(keys, list) or not isinstance(lengths, list) or len(keys) != len(lengths):
                raise CheckpointCorruptionError(f"invalid rows for {field_name}")
            rows: Dict[str, List[float]] = {}
            position = 0
            for key, raw_length in zip(keys, lengths):
                length = int(raw_length)
                if length < 0 or position + length > count:
                    raise CheckpointCorruptionError(f"invalid row length for {field_name}")
                rows[str(key)] = values[position : position + length]
                position += length
            if position != count:
                raise CheckpointCorruptionError(f"unassigned values in {field_name}")
            result[field_name] = rows
        elif encoding == "path_scalars":
            paths = descriptor.get("paths")
            empty_paths = descriptor.get("empty_paths", [])
            if (
                not isinstance(paths, list)
                or len(paths) != count
                or not isinstance(empty_paths, list)
            ):
                raise CheckpointCorruptionError(f"invalid paths for {field_name}")
            root: Dict[str, Any] = {}
            for raw_path in empty_paths:
                if not isinstance(raw_path, list) or not raw_path:
                    raise CheckpointCorruptionError(f"invalid empty path for {field_name}")
                cursor = root
                for key in raw_path:
                    child = cursor.setdefault(str(key), {})
                    if not isinstance(child, dict):
                        raise CheckpointCorruptionError(f"overlapping path in {field_name}")
                    cursor = child
            for raw_path, value in zip(paths, values):
                if not isinstance(raw_path, list) or not raw_path:
                    raise CheckpointCorruptionError(f"invalid path for {field_name}")
                cursor = root
                for key in raw_path[:-1]:
                    child = cursor.setdefault(str(key), {})
                    if not isinstance(child, dict):
                        raise CheckpointCorruptionError(f"overlapping path in {field_name}")
                    cursor = child
                leaf = str(raw_path[-1])
                if leaf in cursor:
                    raise CheckpointCorruptionError(f"duplicate path in {field_name}")
                cursor[leaf] = value
            result[field_name] = root
        else:
            raise UnsupportedCheckpointError(f"unsupported numeric table encoding: {encoding!r}")

    if ranges:
        ordered = sorted(ranges)
        position = 0
        for start, end in ordered:
            if start != position:
                raise CheckpointCorruptionError("numeric table payload has gaps or overlaps")
            position = end
        if numeric_start + position != len(raw):
            raise CheckpointCorruptionError("numeric table payload has trailing bytes")
    elif numeric_start != len(raw):
        raise CheckpointCorruptionError("checkpoint payload has unindexed numeric bytes")

    expected_table_count = int(manifest.get("table_count", -1))
    expected_value_count = int(manifest.get("numeric_value_count", -1))
    if expected_table_count != len(tables) or expected_value_count != sum(
        int(table.get("value_count", 0)) for table in tables
    ):
        raise CheckpointCorruptionError("manifest numeric table summary mismatch")
    return result, {str(key): str(value) for key, value in component_digests.items()}


def _container_bytes(magic: bytes, manifest: Mapping[str, Any], payload: bytes) -> bytes:
    manifest_bytes = _json_bytes(manifest)
    if len(manifest_bytes) > _MAX_MANIFEST_BYTES or len(payload) > _MAX_PAYLOAD_BYTES:
        raise ValueError("checkpoint container exceeds safety limit")
    header = _HEADER.pack(
        magic,
        CONTAINER_VERSION,
        0,
        len(manifest_bytes),
        len(payload),
        hashlib.sha256(manifest_bytes).digest(),
        hashlib.sha256(payload).digest(),
    )
    return header + manifest_bytes + payload


def _parse_container(
    data: bytes,
    *,
    offset: int = 0,
    expected_magic: Optional[bytes] = None,
) -> tuple[Dict[str, Any], bytes, int]:
    if offset < 0 or len(data) - offset < _HEADER.size:
        raise CheckpointCorruptionError("checkpoint container header is truncated")
    magic, version, flags, manifest_length, payload_length, manifest_hash, payload_hash = _HEADER.unpack_from(data, offset)
    if expected_magic is not None and magic != expected_magic:
        raise UnsupportedCheckpointError("unexpected checkpoint container kind")
    if magic not in (CHECKPOINT_MAGIC, DELTA_MAGIC):
        raise UnsupportedCheckpointError("unrecognized checkpoint magic")
    if version != CONTAINER_VERSION or flags != 0:
        raise UnsupportedCheckpointError(f"unsupported checkpoint container version {version}")
    if manifest_length > _MAX_MANIFEST_BYTES or payload_length > _MAX_PAYLOAD_BYTES:
        raise CheckpointCorruptionError("checkpoint container declares unsafe lengths")
    end = offset + _HEADER.size + manifest_length + payload_length
    if end > len(data):
        raise CheckpointCorruptionError("checkpoint container is truncated")
    manifest_start = offset + _HEADER.size
    manifest_bytes = data[manifest_start : manifest_start + manifest_length]
    payload = data[manifest_start + manifest_length : end]
    if hashlib.sha256(manifest_bytes).digest() != manifest_hash:
        raise CheckpointCorruptionError("checkpoint manifest checksum mismatch")
    if hashlib.sha256(payload).digest() != payload_hash:
        raise CheckpointCorruptionError("checkpoint payload checksum mismatch")
    try:
        manifest = json.loads(manifest_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CheckpointCorruptionError("checkpoint manifest is invalid JSON") from exc
    if not isinstance(manifest, dict):
        raise CheckpointCorruptionError("checkpoint manifest must be an object")
    return manifest, payload, end


def _state_class() -> Any:
    # Local import avoids a cycle when ModalAutoencoderTrainingState.load_json
    # dispatches to this module for binary checkpoints.
    from .modal_autoencoder import ModalAutoencoderTrainingState

    return ModalAutoencoderTrainingState


def _state_data(state: Any) -> Dict[str, Any]:
    if isinstance(state, Mapping):
        return _canonical_copy(state)
    # Packed tensor state deliberately writes the rollout-compatible legacy
    # map envelope.  This keeps existing readers operational while migration
    # code can immediately re-pack the decoded object.
    checkpoint_dict = getattr(state, "to_checkpoint_dict", None)
    if callable(checkpoint_dict):
        value = checkpoint_dict()
        if not isinstance(value, Mapping):
            raise TypeError("state.to_checkpoint_dict() must return a mapping")
        return _canonical_copy(value)
    to_dict = getattr(state, "to_dict", None)
    if not callable(to_dict):
        raise TypeError(f"unsupported checkpoint state: {type(state).__name__}")
    value = to_dict()
    if not isinstance(value, Mapping):
        raise TypeError("state.to_dict() must return a mapping")
    return _canonical_copy(value)


def _identity_record(state: Any, metric_lineage: Any) -> tuple[str, int, str, Dict[str, str], str]:
    if isinstance(state, Mapping):
        # A current JSON-style state mapping has the same semantics as the
        # typed state object.  Normalize it through the strict public loader so
        # its schema-bound identity is identical after checkpoint decoding.
        state = _state_from_data(state)
    elif callable(getattr(state, "to_checkpoint_dict", None)):
        # Bind tensor-rollout checkpoints to the exact same component and
        # lineage identity as the current CPU state representation.
        revision = int(getattr(state, "state_revision", 0))
        state = _state_from_data(state.to_checkpoint_dict())
        _restore_revision(state, revision)
    record_method = getattr(state, "state_identity_record", None)
    if callable(record_method):
        record = record_method(metric_lineage=metric_lineage)
        return (
            str(record.digest),
            int(record.revision),
            str(record.metric_lineage_digest),
            {str(key): str(value) for key, value in record.component_digests.items()},
            str(record.state_schema_version),
        )
    data = _state_data(state)
    state_schema = str(data.get("schema_version") or "")
    component_digests = {
        key: canonical_digest(value)
        for key, value in data.items()
        if key not in {"schema_version", "proof_auxiliary_head_schema_version"}
    }
    lineage_digest = canonical_digest(metric_lineage)
    digest = canonical_digest(
        {
            "component_digests": component_digests,
            "metric_lineage": metric_lineage,
            "state_schema_version": state_schema,
        }
    )
    return digest, 0, lineage_digest, component_digests, state_schema


def _restore_revision(state: Any, revision: int) -> None:
    tracker = getattr(state, "_state_identity_tracker", None)
    restore = getattr(tracker, "restore_revision", None)
    if callable(restore):
        restore(int(revision))
        return
    restore = getattr(state, "restore_revision", None)
    if callable(restore):
        restore(int(revision))


@dataclass(frozen=True)
class CheckpointManifest:
    """Validated public metadata for one full checkpoint or delta."""

    schema_version: str
    kind: str
    state_schema_version: str
    state_digest: str
    revision: int
    metric_lineage_digest: str
    metric_lineage: Any
    float_precision: str
    payload_checksum: str
    checkpoint_id: str
    base_state_digest: str = ""
    base_revision: int = -1
    changed_components: Tuple[str, ...] = ()
    table_count: int = 0
    numeric_value_count: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CheckpointManifest":
        schema = str(value.get("schema_version") or "")
        if schema not in (
            MODAL_AUTOENCODER_CHECKPOINT_SCHEMA_VERSION,
            MODAL_AUTOENCODER_DELTA_SCHEMA_VERSION,
        ):
            raise UnsupportedCheckpointError(f"unsupported checkpoint schema: {schema!r}")
        precision = str(value.get("float_precision") or "")
        if precision not in _FLOAT_FORMATS:
            raise UnsupportedCheckpointError(f"unsupported float precision: {precision!r}")
        return cls(
            schema_version=schema,
            kind=str(value.get("kind") or ""),
            state_schema_version=str(value.get("state_schema_version") or ""),
            state_digest=str(value.get("state_digest") or ""),
            revision=int(value.get("revision", -1)),
            metric_lineage_digest=str(value.get("metric_lineage_digest") or ""),
            metric_lineage=_canonical_copy(value.get("metric_lineage")),
            float_precision=precision,
            payload_checksum=str(value.get("payload_checksum") or ""),
            checkpoint_id=str(value.get("checkpoint_id") or ""),
            base_state_digest=str(value.get("base_state_digest") or ""),
            base_revision=int(value.get("base_revision", -1)),
            changed_components=tuple(str(item) for item in value.get("changed_components", [])),
            table_count=int(value.get("table_count", 0)),
            numeric_value_count=int(value.get("numeric_value_count", 0)),
            metadata=_canonical_copy(value.get("metadata") or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "checkpoint_id": self.checkpoint_id,
            "compression": "zlib",
            "float_precision": self.float_precision,
            "kind": self.kind,
            "metadata": _canonical_copy(self.metadata),
            "metric_lineage_digest": self.metric_lineage_digest,
            "metric_lineage": _canonical_copy(self.metric_lineage),
            "numeric_value_count": self.numeric_value_count,
            "payload_checksum": self.payload_checksum,
            "revision": self.revision,
            "schema_version": self.schema_version,
            "state_digest": self.state_digest,
            "state_schema_version": self.state_schema_version,
            "table_count": self.table_count,
            "table_schema_version": MODAL_AUTOENCODER_TABLE_SCHEMA_VERSION,
        }
        if self.kind == "delta":
            result.update(
                {
                    "base_revision": self.base_revision,
                    "base_state_digest": self.base_state_digest,
                    "changed_components": list(self.changed_components),
                }
            )
        return result


@dataclass(frozen=True)
class CheckpointLoadResult:
    state: Any
    manifest: CheckpointManifest
    format: str
    applied_delta_count: int = 0
    recovered_tail_bytes: int = 0
    delta_manifests: Tuple[CheckpointManifest, ...] = ()


def serialize_checkpoint(
    state: Any,
    *,
    float_precision: str = "float64",
    metric_lineage: Any = None,
    metadata: Optional[Mapping[str, Any]] = None,
    revision: Optional[int] = None,
) -> bytes:
    """Serialize a full state into the safe compact binary format."""

    source_data = _state_data(state)
    _source_digest, source_revision, _source_lineage, _source_components, _source_schema = _identity_record(
        state, metric_lineage
    )
    effective_revision = source_revision if revision is None else int(revision)
    data = _quantized_copy(source_data, float_precision)
    persisted_state = _state_from_data(data)
    _restore_revision(persisted_state, effective_revision)
    digest, _persisted_revision, lineage_digest, component_digests, state_schema = _identity_record(
        persisted_state, metric_lineage
    )
    payload, tables = _encode_state_payload(
        data,
        precision=float_precision,
        component_digests=component_digests,
    )
    payload_checksum = _sha256(payload)
    checkpoint_id = "lir-mae-checkpoint-" + canonical_digest(
        {
            "metric_lineage_digest": lineage_digest,
            "payload_checksum": payload_checksum,
            "revision": effective_revision,
            "state_digest": digest,
            "state_schema_version": state_schema,
        }
    )[:32]
    manifest = CheckpointManifest(
        schema_version=MODAL_AUTOENCODER_CHECKPOINT_SCHEMA_VERSION,
        kind="full",
        state_schema_version=state_schema,
        state_digest=digest,
        revision=effective_revision,
        metric_lineage_digest=lineage_digest,
        metric_lineage=_canonical_copy(metric_lineage),
        float_precision=float_precision,
        payload_checksum=payload_checksum,
        checkpoint_id=checkpoint_id,
        table_count=len(tables),
        numeric_value_count=sum(int(table["value_count"]) for table in tables),
        metadata=_canonical_copy(metadata or {}),
    )
    return _container_bytes(CHECKPOINT_MAGIC, manifest.to_dict(), payload)


def serialize_delta(
    base_state: Any,
    state: Any,
    *,
    float_precision: str = "float64",
    metric_lineage: Any = None,
    metadata: Optional[Mapping[str, Any]] = None,
    base_revision: Optional[int] = None,
    revision: Optional[int] = None,
) -> bytes:
    """Serialize whole replacements for only the components that changed."""

    _source_base_digest, source_base_revision, _source_base_lineage, _source_base_components, _source_base_schema = _identity_record(
        base_state, metric_lineage
    )
    _source_digest, source_revision, _source_lineage, _source_components, _source_schema = _identity_record(
        state, metric_lineage
    )
    base_data = _quantized_copy(_state_data(base_state), float_precision)
    data = _quantized_copy(_state_data(state), float_precision)
    persisted_base = _state_from_data(base_data)
    persisted_state = _state_from_data(data)
    effective_base_revision = source_base_revision if base_revision is None else int(base_revision)
    effective_revision = source_revision if revision is None else int(revision)
    _restore_revision(persisted_base, effective_base_revision)
    _restore_revision(persisted_state, effective_revision)
    base_digest, _base_revision, base_lineage, base_components, base_schema = _identity_record(
        persisted_base, metric_lineage
    )
    digest, _revision, lineage_digest, components, state_schema = _identity_record(
        persisted_state, metric_lineage
    )
    if state_schema != base_schema or lineage_digest != base_lineage:
        raise CheckpointLineageError("delta endpoints have different schema or metric lineage")
    if effective_revision < effective_base_revision:
        raise CheckpointLineageError("delta revision precedes its base revision")
    changed = tuple(
        sorted(
            name
            for name in set(base_components) | set(components)
            if base_components.get(name) != components.get(name)
        )
    )
    if effective_revision == effective_base_revision and changed:
        raise CheckpointLineageError("changed delta must advance the state revision")
    missing = [name for name in changed if name not in data]
    if missing:
        raise CheckpointLineageError(f"delta deletes unsupported state components: {missing}")
    payload, tables = _encode_state_payload(
        data,
        precision=float_precision,
        component_digests=components,
        include_components=changed,
    )
    payload_checksum = _sha256(payload)
    delta_id = "lir-mae-delta-" + canonical_digest(
        {
            "base_revision": effective_base_revision,
            "base_state_digest": base_digest,
            "payload_checksum": payload_checksum,
            "revision": effective_revision,
            "state_digest": digest,
        }
    )[:32]
    manifest = CheckpointManifest(
        schema_version=MODAL_AUTOENCODER_DELTA_SCHEMA_VERSION,
        kind="delta",
        state_schema_version=state_schema,
        state_digest=digest,
        revision=effective_revision,
        metric_lineage_digest=lineage_digest,
        metric_lineage=_canonical_copy(metric_lineage),
        float_precision=float_precision,
        payload_checksum=payload_checksum,
        checkpoint_id=delta_id,
        base_state_digest=base_digest,
        base_revision=effective_base_revision,
        changed_components=changed,
        table_count=len(tables),
        numeric_value_count=sum(int(table["value_count"]) for table in tables),
        metadata=_canonical_copy(metadata or {}),
    )
    return _container_bytes(DELTA_MAGIC, manifest.to_dict(), payload)


def _validate_manifest_payload(manifest: CheckpointManifest, payload: bytes, *, kind: str) -> None:
    if manifest.kind != kind or manifest.revision < 0:
        raise CheckpointCorruptionError(f"invalid {kind} checkpoint manifest")
    if manifest.payload_checksum != _sha256(payload):
        raise CheckpointCorruptionError("manifest payload checksum mismatch")
    if not manifest.state_schema_version or not manifest.state_digest or not manifest.metric_lineage_digest:
        raise CheckpointCorruptionError("checkpoint lineage fields are incomplete")


def _state_from_data(data: Mapping[str, Any], state_factory: Any = None) -> Any:
    factory = state_factory or _state_class()
    from_dict = getattr(factory, "from_dict", None)
    if callable(from_dict):
        return from_dict(data)
    if callable(factory):
        return factory(data)
    raise TypeError("state_factory must be callable or expose from_dict")


def deserialize_checkpoint(
    data: bytes,
    *,
    expected_state_schema_version: Optional[str] = None,
    expected_metric_lineage: Any = None,
    expected_revision: Optional[int] = None,
    state_factory: Any = None,
) -> CheckpointLoadResult:
    manifest_data, payload, end = _parse_container(data, expected_magic=CHECKPOINT_MAGIC)
    if end != len(data):
        raise CheckpointCorruptionError("full checkpoint has trailing bytes")
    manifest = CheckpointManifest.from_dict(manifest_data)
    _validate_manifest_payload(manifest, payload, kind="full")
    state_data, stored_components = _decode_state_payload(payload, manifest_data)
    state = _state_from_data(state_data, state_factory)
    _restore_revision(state, manifest.revision)
    _verify_loaded_state(
        state,
        manifest,
        stored_components,
        expected_state_schema_version=expected_state_schema_version,
        expected_metric_lineage=expected_metric_lineage,
        expected_revision=expected_revision,
    )
    return CheckpointLoadResult(state=state, manifest=manifest, format="compact")


def _verify_loaded_state(
    state: Any,
    manifest: CheckpointManifest,
    stored_components: Mapping[str, str],
    *,
    expected_state_schema_version: Optional[str],
    expected_metric_lineage: Any,
    expected_revision: Optional[int],
) -> None:
    if expected_state_schema_version is not None and manifest.state_schema_version != expected_state_schema_version:
        raise CheckpointLineageError(
            f"state schema mismatch: expected {expected_state_schema_version!r}, got {manifest.state_schema_version!r}"
        )
    if expected_revision is not None and manifest.revision != int(expected_revision):
        raise CheckpointLineageError(
            f"state revision mismatch: expected {expected_revision}, got {manifest.revision}"
        )
    effective_metric_lineage = (
        manifest.metric_lineage
        if expected_metric_lineage is None
        else expected_metric_lineage
    )
    digest, revision, lineage_digest, components, schema = _identity_record(
        state, effective_metric_lineage
    )
    if schema != manifest.state_schema_version:
        raise CheckpointLineageError("decoded state schema does not match checkpoint lineage")
    if lineage_digest != manifest.metric_lineage_digest:
        raise CheckpointLineageError("metric lineage does not match checkpoint")
    if revision != manifest.revision:
        raise CheckpointLineageError("decoded operational revision mismatch")
    if dict(components) != dict(stored_components):
        raise CheckpointCorruptionError("decoded component digests do not match payload")
    if digest != manifest.state_digest:
        raise CheckpointCorruptionError("decoded state digest does not match manifest")


def _json_load_result(
    raw: bytes,
    *,
    expected_state_schema_version: Optional[str],
    expected_metric_lineage: Any,
    expected_revision: Optional[int],
    state_factory: Any,
) -> CheckpointLoadResult:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CheckpointCorruptionError("legacy state is invalid JSON") from exc
    if not isinstance(value, Mapping):
        raise CheckpointCorruptionError("legacy JSON state must be an object")
    state = _state_from_data(value, state_factory)
    digest, revision, lineage_digest, components, schema = _identity_record(state, expected_metric_lineage)
    if expected_state_schema_version is not None and schema != expected_state_schema_version:
        raise CheckpointLineageError("legacy JSON state schema mismatch")
    if expected_revision is not None and revision != int(expected_revision):
        raise CheckpointLineageError("legacy JSON has no matching durable revision")
    payload_checksum = _sha256(raw)
    manifest = CheckpointManifest(
        schema_version=MODAL_AUTOENCODER_CHECKPOINT_SCHEMA_VERSION,
        kind="full",
        state_schema_version=schema,
        state_digest=digest,
        revision=revision,
        metric_lineage_digest=lineage_digest,
        metric_lineage=_canonical_copy(expected_metric_lineage),
        float_precision="float64",
        payload_checksum=payload_checksum,
        checkpoint_id="lir-mae-json-" + payload_checksum[:32],
        table_count=0,
        numeric_value_count=0,
        metadata={"legacy_json": True, "component_digest": canonical_digest(components)},
    )
    return CheckpointLoadResult(state=state, manifest=manifest, format="json")


def iter_delta_segments(data: bytes, *, recover_truncated_tail: bool = True) -> tuple[List[tuple[CheckpointManifest, bytes]], int, int]:
    """Decode complete delta frames and report valid offset/recovered bytes."""

    segments: List[tuple[CheckpointManifest, bytes]] = []
    offset = 0
    while offset < len(data):
        remaining = len(data) - offset
        if remaining < _HEADER.size:
            if recover_truncated_tail:
                return segments, offset, remaining
            raise CheckpointCorruptionError("delta log has a truncated header")
        try:
            manifest_data, payload, end = _parse_container(
                data, offset=offset, expected_magic=DELTA_MAGIC
            )
        except CheckpointCorruptionError as exc:
            # Only a declared frame extending beyond EOF is a recoverable torn
            # append.  Complete frames with bad checksums remain hard failures.
            if recover_truncated_tail and "is truncated" in str(exc):
                return segments, offset, len(data) - offset
            raise
        manifest = CheckpointManifest.from_dict(manifest_data)
        _validate_manifest_payload(manifest, payload, kind="delta")
        segments.append((manifest, payload))
        offset = end
    return segments, offset, 0


def _apply_delta(
    state: Any,
    current_manifest: CheckpointManifest,
    delta_manifest: CheckpointManifest,
    payload: bytes,
    *,
    metric_lineage: Any,
) -> Any:
    if delta_manifest.state_schema_version != current_manifest.state_schema_version:
        raise CheckpointLineageError("delta state schema lineage mismatch")
    if delta_manifest.metric_lineage_digest != current_manifest.metric_lineage_digest:
        raise CheckpointLineageError("delta metric lineage mismatch")
    if delta_manifest.base_revision != current_manifest.revision:
        raise CheckpointLineageError(
            f"delta revision gap: expected base {current_manifest.revision}, got {delta_manifest.base_revision}"
        )
    if delta_manifest.base_state_digest != current_manifest.state_digest:
        raise CheckpointLineageError("delta base state digest mismatch")
    if delta_manifest.revision < delta_manifest.base_revision:
        raise CheckpointLineageError("delta revision moves backwards")
    patch, stored_components = _decode_state_payload(payload, delta_manifest.to_dict())
    if set(patch) != set(delta_manifest.changed_components):
        raise CheckpointCorruptionError("delta changed-component declaration mismatch")
    data = _state_data(state)
    data.update(patch)
    next_state = _state_from_data(data)
    _restore_revision(next_state, delta_manifest.revision)
    _verify_loaded_state(
        next_state,
        delta_manifest,
        stored_components,
        expected_state_schema_version=current_manifest.state_schema_version,
        expected_metric_lineage=metric_lineage,
        expected_revision=delta_manifest.revision,
    )
    if not delta_manifest.changed_components and delta_manifest.state_digest != current_manifest.state_digest:
        raise CheckpointCorruptionError("metadata-only delta changes state identity")
    return next_state


def load_checkpoint(
    path: str | Path,
    *,
    delta_path: str | Path | None = None,
    expected_state_schema_version: Optional[str] = None,
    expected_metric_lineage: Any = None,
    expected_revision: Optional[int] = None,
    allow_json: bool = True,
    recover: bool = True,
    state_factory: Any = None,
) -> CheckpointLoadResult:
    """Load a compact checkpoint or current JSON state and apply valid deltas."""

    source = Path(path)
    raw = source.read_bytes()
    if raw.startswith(CHECKPOINT_MAGIC):
        loaded = deserialize_checkpoint(
            raw,
            expected_state_schema_version=expected_state_schema_version,
            expected_metric_lineage=expected_metric_lineage,
            expected_revision=None if delta_path is not None else expected_revision,
            state_factory=state_factory,
        )
    elif allow_json and raw.lstrip().startswith(b"{"):
        loaded = _json_load_result(
            raw,
            expected_state_schema_version=expected_state_schema_version,
            expected_metric_lineage=expected_metric_lineage,
            expected_revision=None if delta_path is not None else expected_revision,
            state_factory=state_factory,
        )
    else:
        raise UnsupportedCheckpointError(f"unsupported state file: {source}")

    if delta_path is None or not Path(delta_path).exists():
        return loaded
    delta_source = Path(delta_path)
    delta_bytes = delta_source.read_bytes()
    segments, valid_offset, recovered = iter_delta_segments(
        delta_bytes, recover_truncated_tail=recover
    )
    state = loaded.state
    current = loaded.manifest
    applied: List[CheckpointManifest] = []
    started = False
    for delta_manifest, payload in segments:
        # Logs may retain segments preceding a newer periodic full checkpoint.
        # Ignore only segments wholly superseded by that checkpoint.  A segment
        # at or ahead of the current revision that names another base is a real
        # lineage gap and must fail closed.
        if not started and (
            delta_manifest.base_revision != current.revision
            or delta_manifest.base_state_digest != current.state_digest
        ):
            if delta_manifest.revision <= current.revision:
                continue
            _apply_delta(
                state,
                current,
                delta_manifest,
                payload,
                metric_lineage=expected_metric_lineage,
            )
            raise CheckpointLineageError("delta does not descend from checkpoint")
        started = True
        state = _apply_delta(
            state,
            current,
            delta_manifest,
            payload,
            metric_lineage=expected_metric_lineage,
        )
        current = delta_manifest
        applied.append(delta_manifest)
    if expected_revision is not None and current.revision != int(expected_revision):
        raise CheckpointLineageError(
            f"final state revision mismatch: expected {expected_revision}, got {current.revision}"
        )
    if recovered and recover:
        with delta_source.open("r+b") as handle:
            handle.truncate(valid_offset)
            handle.flush()
            os.fsync(handle.fileno())
    return CheckpointLoadResult(
        state=state,
        manifest=current,
        format=loaded.format,
        applied_delta_count=len(applied),
        recovered_tail_bytes=recovered,
        delta_manifests=tuple(applied),
    )


def write_checkpoint_atomic(
    path: str | Path,
    state: Any,
    **kwargs: Any,
) -> CheckpointManifest:
    """Write a full checkpoint with replace atomicity and directory durability."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = serialize_checkpoint(state, **kwargs)
    manifest_data, _payload, _end = _parse_container(encoded, expected_magic=CHECKPOINT_MAGIC)
    temporary = destination.with_name(
        f".{destination.name}.tmp-{os.getpid()}-{threading.get_ident()}"
    )
    try:
        with temporary.open("wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        if os.name != "nt":
            fd = os.open(str(destination.parent), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return CheckpointManifest.from_dict(manifest_data)


def append_delta_segment(
    path: str | Path,
    segment: bytes,
    *,
    fsync: bool = True,
) -> int:
    """Append one delta idempotently, repairing only a torn final append."""

    manifest_data, _payload, end = _parse_container(segment, expected_magic=DELTA_MAGIC)
    if end != len(segment):
        raise CheckpointCorruptionError("delta segment has trailing bytes")
    incoming = CheckpointManifest.from_dict(manifest_data)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    existing = destination.read_bytes() if destination.exists() else b""
    segments, valid_offset, recovered = iter_delta_segments(existing, recover_truncated_tail=True)
    if any(manifest.checkpoint_id == incoming.checkpoint_id for manifest, _ in segments):
        return 0
    flags = os.O_CREAT | os.O_RDWR
    fd = os.open(str(destination), flags, 0o644)
    try:
        if recovered:
            os.ftruncate(fd, valid_offset)
        os.lseek(fd, 0, os.SEEK_END)
        written = 0
        while written < len(segment):
            written += os.write(fd, segment[written:])
        if fsync:
            os.fsync(fd)
    finally:
        os.close(fd)
    return written


def append_state_delta(
    path: str | Path,
    base_state: Any,
    state: Any,
    **kwargs: Any,
) -> CheckpointManifest:
    segment = serialize_delta(base_state, state, **kwargs)
    manifest_data, _payload, _end = _parse_container(segment, expected_magic=DELTA_MAGIC)
    append_delta_segment(path, segment)
    return CheckpointManifest.from_dict(manifest_data)


# Explicit aliases make the module convenient to use from persistence layers
# while retaining names that describe the artifact rather than its transport.
save_checkpoint = write_checkpoint_atomic
load_state_checkpoint = load_checkpoint
serialize_full_checkpoint = serialize_checkpoint


__all__ = [
    "CHECKPOINT_MAGIC",
    "DELTA_MAGIC",
    "MODAL_AUTOENCODER_CHECKPOINT_SCHEMA_VERSION",
    "MODAL_AUTOENCODER_DELTA_SCHEMA_VERSION",
    "MODAL_AUTOENCODER_TABLE_SCHEMA_VERSION",
    "CheckpointCorruptionError",
    "CheckpointLineageError",
    "CheckpointLoadResult",
    "CheckpointManifest",
    "ModalAutoencoderCheckpointError",
    "UnsupportedCheckpointError",
    "append_delta_segment",
    "append_state_delta",
    "deserialize_checkpoint",
    "iter_delta_segments",
    "load_checkpoint",
    "load_state_checkpoint",
    "quantize_float",
    "save_checkpoint",
    "serialize_checkpoint",
    "serialize_delta",
    "serialize_full_checkpoint",
    "write_checkpoint_atomic",
]
