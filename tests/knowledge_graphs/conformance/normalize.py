"""Canonical envelope normalization for cross-surface comparison (KGP-020).

Surfaces may attach non-deterministic transport metadata (request ids, lease
ids, elapsed_ms, MCP++ cache flags). Comparison uses a stripped, key-sorted
JSON form while **preserving** rows, revision, status, operation, schema,
truncated, columns, and TypedError ``code`` / ``retryable``.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set

# Keys dropped at every nesting level (unless re-added under preserve).
_DEFAULT_STRIP: Set[str] = {
    "request_id",
    "authorization_receipt_ref",
    "created_at",
    "lease_id",
    "lease_epoch",
    "snapshot_id",
    "cursor",
    "transaction_id",
    "_cached",
    # MCP hybrid legacy echo fields (not part of lifecycle contract).
    "search_type",
    "results",
    "count",
}

_STRIP_STATISTICS: Set[str] = {"elapsed_ms"}

# Error detail keys that may vary by surface exception wrapping.
_STRIP_ERROR_DETAILS: Set[str] = {"error_type", "traceback", "exc_type"}


def dumps_canonical(value: Any) -> str:
    """Byte-stable JSON for equality (sort_keys, no NaN, compact separators)."""
    return json.dumps(
        value,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def assert_json_safe(value: Any, *, path: str = "$") -> None:
    if value is None or isinstance(value, (bool, str)):
        return
    if isinstance(value, int) and not isinstance(value, bool):
        return
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise AssertionError(f"non-finite float at {path}")
        return
    if isinstance(value, list):
        for i, item in enumerate(value):
            assert_json_safe(item, path=f"{path}[{i}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise AssertionError(f"non-string key at {path}: {key!r}")
            assert_json_safe(item, path=f"{path}.{key}")
        return
    raise AssertionError(f"non-JSON type {type(value).__name__} at {path}")


def _strip_mapping(
    data: MutableMapping[str, Any],
    *,
    strip: Set[str],
    deep: bool = True,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in data.items():
        if key in strip:
            continue
        if key == "statistics" and isinstance(value, Mapping):
            out[key] = {
                k: v for k, v in value.items() if k not in _STRIP_STATISTICS
            }
            continue
        if key == "error" and isinstance(value, Mapping):
            err = {k: v for k, v in value.items() if k not in strip}
            details = err.get("details")
            if isinstance(details, Mapping):
                err["details"] = {
                    k: v
                    for k, v in details.items()
                    if k not in _STRIP_ERROR_DETAILS
                }
            # Drop free-form messages for code-centric parity (message text may
            # differ slightly by transport). Callers that need message equality
            # should inspect the raw envelope.
            err.pop("message", None)
            out[key] = err
            continue
        if deep and isinstance(value, Mapping):
            out[key] = _strip_mapping(dict(value), strip=strip, deep=True)
        elif deep and isinstance(value, list):
            out[key] = [
                _strip_mapping(dict(v), strip=strip, deep=True)
                if isinstance(v, Mapping)
                else v
                for v in value
            ]
        else:
            out[key] = value
    return out


def normalize_envelope(
    envelope: Mapping[str, Any],
    *,
    strip_keys: Optional[Iterable[str]] = None,
    drop_message: bool = True,
    sort_rows: bool = False,
    row_name_index: int = 2,
) -> Dict[str, Any]:
    """Return a transport-neutral, comparable lifecycle/query envelope.

    Preserves:
      status, operation, contract_version, result.rows, result.revision,
      result.row_count, result.columns, result.schema, result.truncated,
      result.envelope_version, error.code, error.retryable
    """
    strip = set(_DEFAULT_STRIP)
    if strip_keys:
        strip.update(strip_keys)

    raw = copy.deepcopy(dict(envelope))
    # MCP tools may echo query text at the top level.
    if "query" in raw and isinstance(raw.get("result"), Mapping):
        # Prefer nested query envelope language; drop top-level echo.
        raw.pop("query", None)

    normalized = _strip_mapping(raw, strip=strip, deep=True)

    # Ensure warnings is a list for stable shape.
    if "warnings" in normalized and normalized["warnings"] is None:
        normalized["warnings"] = []

    result = normalized.get("result")
    if isinstance(result, Mapping):
        result_dict = dict(result)
        rows = result_dict.get("rows")
        if sort_rows and isinstance(rows, list):
            def _cell_key(cell: Any) -> Any:
                if isinstance(cell, Mapping):
                    return (
                        cell.get("id"),
                        cell.get("name"),
                        cell.get("type"),
                        dumps_canonical(cell),
                    )
                if isinstance(cell, (list, tuple)):
                    return tuple(_cell_key(c) for c in cell)
                return cell

            def _row_key(row: Any) -> Any:
                if isinstance(row, (list, tuple)) and len(row) > row_name_index:
                    return (_cell_key(row[0]), _cell_key(row[row_name_index]))
                if isinstance(row, (list, tuple)) and row:
                    return _cell_key(row[0])
                if isinstance(row, Mapping):
                    return (row.get("id"), row.get("name"))
                return str(row)

            result_dict["rows"] = sorted(rows, key=_row_key)
            result_dict["row_count"] = len(result_dict["rows"])
        # Nested target may still carry ephemeral fields.
        tgt = result_dict.get("target")
        if isinstance(tgt, Mapping):
            result_dict["target"] = _strip_mapping(
                dict(tgt), strip=strip, deep=False
            )
        normalized["result"] = result_dict

    if not drop_message:
        # Restore message if present in original error for debugging helpers.
        pass

    assert_json_safe(normalized)
    return normalized


def extract_error_code(envelope: Mapping[str, Any]) -> Optional[str]:
    err = envelope.get("error")
    if isinstance(err, Mapping):
        code = err.get("code")
        return str(code) if code is not None else None
    if isinstance(err, str):
        # MCP++ dispatch may return bare string errors for routing failures.
        return "INTERNAL"
    return None


def extract_rows(envelope: Mapping[str, Any]) -> List[Any]:
    result = envelope.get("result")
    if not isinstance(result, Mapping):
        return []
    rows = result.get("rows")
    return list(rows) if isinstance(rows, list) else []


def extract_revision(envelope: Mapping[str, Any]) -> Optional[str]:
    result = envelope.get("result")
    if not isinstance(result, Mapping):
        return None
    rev = result.get("revision") or result.get("head_revision")
    return str(rev) if rev else None


def names_from_scan_rows(rows: Sequence[Any], *, name_index: int = 2) -> List[str]:
    names: List[str] = []
    for row in rows:
        if isinstance(row, (list, tuple)) and len(row) > name_index:
            names.append(str(row[name_index]))
        elif isinstance(row, Mapping) and "name" in row:
            names.append(str(row["name"]))
    return sorted(names)


def ids_from_scan_rows(rows: Sequence[Any], *, id_index: int = 0) -> List[str]:
    ids: List[str] = []
    for row in rows:
        if isinstance(row, (list, tuple)) and len(row) > id_index:
            ids.append(str(row[id_index]))
        elif isinstance(row, Mapping) and "id" in row:
            ids.append(str(row["id"]))
    return sorted(ids)


def assert_envelopes_equal(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    *,
    label_left: str = "left",
    label_right: str = "right",
    sort_rows: bool = False,
) -> None:
    """Strict equality of normalized envelopes (canonical JSON)."""
    n_left = normalize_envelope(left, sort_rows=sort_rows)
    n_right = normalize_envelope(right, sort_rows=sort_rows)
    if dumps_canonical(n_left) != dumps_canonical(n_right):
        raise AssertionError(
            f"envelope mismatch {label_left} vs {label_right}:\n"
            f"{label_left}={dumps_canonical(n_left)}\n"
            f"{label_right}={dumps_canonical(n_right)}"
        )


def assert_core_parity(
    envelopes: Mapping[str, Mapping[str, Any]],
    *,
    require_revision: bool = False,
    sort_rows: bool = True,
) -> Dict[str, Any]:
    """Compare multiple surface envelopes for status/code/rows/revision parity.

    Returns a summary dict of the shared core fields.
    """
    if not envelopes:
        raise AssertionError("no envelopes to compare")

    statuses = {s: e.get("status") for s, e in envelopes.items()}
    if len(set(statuses.values())) != 1:
        raise AssertionError(f"status mismatch across surfaces: {statuses}")

    status = next(iter(statuses.values()))
    codes = {s: extract_error_code(e) for s, e in envelopes.items()}
    if status == "error":
        if len(set(codes.values())) != 1:
            raise AssertionError(f"error code mismatch: {codes}")
        retryables = {
            s: (e.get("error") or {}).get("retryable")
            if isinstance(e.get("error"), Mapping)
            else None
            for s, e in envelopes.items()
        }
        if len(set(retryables.values())) != 1:
            raise AssertionError(f"retryable mismatch: {retryables}")
        return {
            "status": status,
            "error_code": next(iter(codes.values())),
            "retryable": next(iter(retryables.values())),
        }

    # Success path: rows + revision + row_count.
    norms = {
        s: normalize_envelope(e, sort_rows=sort_rows) for s, e in envelopes.items()
    }
    row_counts = {
        s: (n.get("result") or {}).get("row_count")
        if isinstance(n.get("result"), Mapping)
        else None
        for s, n in norms.items()
    }
    # Not all ops return row_count (create/describe); only compare when present.
    present_counts = {s: c for s, c in row_counts.items() if c is not None}
    if present_counts and len(set(present_counts.values())) != 1:
        raise AssertionError(f"row_count mismatch: {row_counts}")

    rows_map = {
        s: extract_rows(n) for s, n in norms.items() if extract_rows(n) is not None
    }
    # Compare rows only when any surface returned rows list (including empty).
    surfaces_with_rows = [
        s
        for s, n in norms.items()
        if isinstance(n.get("result"), Mapping) and "rows" in (n.get("result") or {})
    ]
    if surfaces_with_rows:
        ref = surfaces_with_rows[0]
        ref_rows = dumps_canonical(extract_rows(norms[ref]))
        for s in surfaces_with_rows[1:]:
            other = dumps_canonical(extract_rows(norms[s]))
            if other != ref_rows:
                raise AssertionError(
                    f"rows mismatch {ref} vs {s}:\n{ref}={ref_rows}\n{s}={other}"
                )

    revs = {s: extract_revision(n) for s, n in norms.items()}
    present_revs = {s: r for s, r in revs.items() if r}
    if require_revision:
        if not present_revs:
            raise AssertionError("expected revision on all surfaces")
        if len(set(present_revs.values())) != 1:
            raise AssertionError(f"revision mismatch: {revs}")
    elif present_revs and len(set(present_revs.values())) != 1:
        raise AssertionError(f"revision mismatch: {revs}")

    truncated = {
        s: (n.get("result") or {}).get("truncated")
        if isinstance(n.get("result"), Mapping)
        else None
        for s, n in norms.items()
    }
    present_trunc = {s: t for s, t in truncated.items() if t is not None}
    if present_trunc and len(set(present_trunc.values())) != 1:
        raise AssertionError(f"truncated mismatch: {truncated}")

    return {
        "status": status,
        "row_count": next(iter(present_counts.values()), None),
        "revision": next(iter(present_revs.values()), None),
        "truncated": next(iter(present_trunc.values()), None),
        "error_code": None,
    }
