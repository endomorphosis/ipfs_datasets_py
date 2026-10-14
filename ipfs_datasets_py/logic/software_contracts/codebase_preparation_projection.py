"""Bounded complete AST projection bodies for durable preparation pages.

The existing authority serializer defines the field vocabulary. Only its
known relational clock fields change to canonical hexadecimal strings for
the DAG-JSON profile. Decoding rebuilds every canonical row and compares the
complete envelope; these bodies grant no active catalog or proof authority.
"""
from __future__ import annotations

import json
import math
from typing import Any

from .content import canonical_dag_json_bytes, validate_cid
from .duckdb_ast_store import ASTCatalogProjection, DuckDBASTStore
from .repository import projection_to_authority_payload

MAX_PREPARATION_PROJECTION_BYTES = 1024 * 1024
_FIELDS = frozenset({
    "schema", "interface", "owner_task_id", "kind", "identity",
    "source_revision", "source_file", "ast_blob", "nodes", "scopes", "symbols",
    "imports", "references", "calls", "effects", "interfaces", "diagnostics",
    "invalidations", "supervisor_blob_summary", "table_row_counts",
})
_ROW_LISTS = (
    "nodes", "scopes", "symbols", "imports", "references", "calls", "effects",
    "interfaces", "diagnostics", "invalidations",
)
_CLOCK_ROWS = ("source_revision", "source_file", "ast_blob")
_CLOCK_LISTS = ("diagnostics", "invalidations")


class CodebasePreparationProjectionError(ValueError):
    """A preparation projection body is incomplete, corrupt or oversized."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CodebasePreparationProjectionError(message)


def _shape(value: Any) -> None:
    _require(type(value) is dict and set(value) == _FIELDS,
             "preparation projection requires the complete closed authority envelope")
    for name in (*_CLOCK_ROWS, "identity", "supervisor_blob_summary", "table_row_counts"):
        _require(type(value[name]) is dict, "projection header must be an exact native object")
    for name in _ROW_LISTS:
        rows = value[name]
        _require(type(rows) is list and len(rows) <= MAX_PREPARATION_PROJECTION_BYTES,
                 "projection family must be a bounded native row list")
        _require(all(type(row) is dict for row in rows),
                 "projection rows must be exact native objects")


def _wire(value: Any) -> bytes:
    try:
        raw = canonical_dag_json_bytes(value)
    except (ValueError, TypeError, RecursionError, OverflowError) as error:
        raise CodebasePreparationProjectionError("projection body is outside canonical DAG-JSON") from error
    _require(0 < len(raw) <= MAX_PREPARATION_PROJECTION_BYTES,
             "preparation projection exceeds its one-MiB body bound")
    return raw


def _clock_to_hex(value: Any) -> str:
    _require(type(value) in (int, float), "projection clock must be an exact native number")
    try:
        result = float(value)
    except (ValueError, OverflowError) as error:
        raise CodebasePreparationProjectionError("projection clock is not finite") from error
    _require(math.isfinite(result), "projection clock is not finite")
    return result.hex()


def _clock_from_hex(value: Any) -> float:
    _require(type(value) is str and 0 < len(value) <= 64,
             "projection clock must be a canonical hexadecimal string")
    try:
        result = float.fromhex(value)
    except (ValueError, OverflowError) as error:
        raise CodebasePreparationProjectionError("projection clock does not verify") from error
    _require(math.isfinite(result) and result.hex() == value,
             "projection clock does not verify")
    return result


def _clock_row(row: dict[str, Any], *, restoring: bool) -> dict[str, Any]:
    source, target = ("created_at_hex", "created_at") if restoring else ("created_at", "created_at_hex")
    _require(source in row and target not in row, "projection clock fields must be exact")
    result = dict(row)
    value = result.pop(source)
    result[target] = _clock_from_hex(value) if restoring else _clock_to_hex(value)
    return result


def _clocks(value: dict[str, Any], *, restoring: bool) -> dict[str, Any]:
    _shape(value)
    result = dict(value)
    for name in _CLOCK_ROWS:
        result[name] = _clock_row(value[name], restoring=restoring)
    for name in _CLOCK_LISTS:
        result[name] = [_clock_row(row, restoring=restoring) for row in value[name]]
    return result


def _reconstruct(value: dict[str, Any], raw: bytes) -> ASTCatalogProjection:
    try:
        native = _clocks(value, restoring=True)
        projection = DuckDBASTStore._rebuild(
            native["ast_blob"], native["source_revision"],
            native["diagnostics"], native["invalidations"],
        )
        validate_cid(projection.source_cid, codecs={"raw"})
        validate_cid(projection.ast_cid, codecs={"dag-json"})
        expected = _clocks(projection_to_authority_payload(projection), restoring=False)
        _require(_wire(expected) == raw,
                 "projection envelope differs from its complete canonical reconstruction")
        return projection
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError) as error:
        if type(error) is CodebasePreparationProjectionError:
            raise
        raise CodebasePreparationProjectionError("preparation projection does not verify") from error


def encode_preparation_projection(projection: ASTCatalogProjection) -> dict[str, Any]:
    """Return detached, bounded full projection fields with reviewed clocks."""
    _require(type(projection) is ASTCatalogProjection, "an exact AST projection is required")
    try:
        value = _clocks(projection_to_authority_payload(projection), restoring=False)
        raw = _wire(value)
        detached = json.loads(raw)
        _reconstruct(detached, raw)
        return detached
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError) as error:
        if type(error) is CodebasePreparationProjectionError:
            raise
        raise CodebasePreparationProjectionError("preparation projection cannot be encoded") from error


def decode_preparation_projection(value: dict[str, Any]) -> ASTCatalogProjection:
    """Rebuild and verify every row from an independently admitted page body."""
    _shape(value)
    raw = _wire(value)
    return _reconstruct(json.loads(raw), raw)


def _decode_preparation_projection_with_raw(
    value: dict[str, Any],
) -> tuple[ASTCatalogProjection, bytes]:
    """Keep the verified canonical bytes for this member's final size check."""
    _shape(value)
    raw = _wire(value)
    return _reconstruct(json.loads(raw), raw), raw


def _verified_preparation_projection_size(
    projection: ASTCatalogProjection, verified_raw: bytes,
) -> int:
    """Check a decoded member against its own bytes after context callbacks.

    The private caller must obtain these bytes from the full decoder in the
    same member verification. This is a consistency check, not admission of
    caller-supplied bytes. Rechecking every serialized field preserves the
    final mutation fence without rebuilding the AST a second time.
    """
    _require(type(projection) is ASTCatalogProjection, "an exact AST projection is required")
    _require(type(verified_raw) is bytes and 0 < len(verified_raw) <= MAX_PREPARATION_PROJECTION_BYTES,
             "bounded verified projection bytes are required")
    try:
        current = _clocks(projection_to_authority_payload(projection), restoring=False)
        _require(_wire(current) == verified_raw, "projection changed after canonical decoding")
        return len(verified_raw)
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError) as error:
        if type(error) is CodebasePreparationProjectionError:
            raise
        raise CodebasePreparationProjectionError("decoded projection size does not verify") from error
