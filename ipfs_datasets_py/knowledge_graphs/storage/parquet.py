"""Versioned Parquet GraphStore (KGP-009).

Production storage profile ``parquet`` for knowledge-graph revisions:

* Normalized **nodes**, **edges**, **adjacency**, **properties**, and
  **indexes** as versioned Parquet datasets under immutable revision
  directories
* **Schema versions** on every partition (column + file metadata)
* **Bounded row groups**, written with statistics enabled
* Per-file **SHA-256 checksums** recorded in the revision manifest
* **Predicate pushdown** via PyArrow Parquet filters
* **Schema evolution** (additive nullable columns; older revisions remain
  readable under a newer reader schema)
* **Atomic temp / fsync / rename** publication of whole revision directories
* **Restart verification** of published revisions after process reopen
* **Corrupt / truncated** file detection (magic, footer, size, checksum)

Catalog control metadata is intentionally **not** stored here; only payload
and the revision manifest (partition/index descriptors) live under the
revision directory. Branch heads remain a catalog concern (KGP-005).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STORAGE_PROFILE: str = "parquet"
DEFAULT_CODEC: str = "parquet"
DEFAULT_SCHEMA_ID: str = "kg-parquet-graph"
DEFAULT_SCHEMA_VERSION: str = "1"
DEFAULT_GRAPH_KIND: str = "knowledge"
DEFAULT_ONTOLOGY_ID: str = "none"
DEFAULT_ONTOLOGY_VERSION: str = "0"
DEFAULT_ROW_GROUP_SIZE: int = 65_536
MAX_ROW_GROUP_SIZE: int = 256_000
MIN_ROW_GROUP_SIZE: int = 1
PARQUET_MAGIC: bytes = b"PAR1"
PARQUET_COMPRESSION: str = "zstd"
PUBLICATION_MARKER: str = "_SUCCESS"
MANIFEST_FILENAME: str = "manifest.json"
STATS_FILENAME: str = "statistics.json"
CHECKSUMS_FILENAME: str = "checksums.json"
STAGING_DIRNAME: str = ".staging"

PARTITION_NODES: str = "nodes"
PARTITION_EDGES: str = "edges"
PARTITION_ADJACENCY: str = "adjacency"
PARTITION_PROPERTIES: str = "properties"
INDEX_DIRNAME: str = "indexes"

# Shared typed-error vocabulary (kg-service-contract/v1 §6.2).
TYPED_ERROR_CODES = frozenset(
    {
        "INVALID_REQUEST",
        "INVALID_TARGET",
        "NOT_FOUND",
        "ALREADY_EXISTS",
        "CONFLICT",
        "FENCED",
        "UNAUTHORIZED",
        "FORBIDDEN",
        "BUDGET_EXCEEDED",
        "QUERY_PARSE",
        "QUERY_EXECUTION",
        "STORAGE",
        "INTEGRITY",
        "NOT_IMPLEMENTED",
        "INTERNAL",
    }
)

PathLike = Union[str, Path]
FilterSpec = Union[
    Sequence[Tuple[str, str, Any]],
    List[Any],
    Tuple[Any, ...],
    None,
]
CancelCheck = Callable[[], None]

# Logical dataset schema versions (partition-level).
DATASET_SCHEMA_VERSIONS: Dict[str, str] = {
    PARTITION_NODES: "1",
    PARTITION_EDGES: "1",
    PARTITION_ADJACENCY: "1",
    PARTITION_PROPERTIES: "1",
    "index": "1",
}


# ---------------------------------------------------------------------------
# Optional dependencies
# ---------------------------------------------------------------------------

try:
    import pyarrow as pa  # type: ignore[import]
    import pyarrow.compute as pc  # type: ignore[import]
    import pyarrow.parquet as pq  # type: ignore[import]

    _HAVE_PYARROW = True
except Exception:  # pragma: no cover - optional at import time
    pa = None  # type: ignore[assignment]
    pc = None  # type: ignore[assignment]
    pq = None  # type: ignore[assignment]
    _HAVE_PYARROW = False


# ---------------------------------------------------------------------------
# Typed errors
# ---------------------------------------------------------------------------


class GraphStoreError(Exception):
    """Storage adapter error with a shared service-contract ``code``."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: Optional[Mapping[str, Any]] = None,
        cause_code: Optional[str] = None,
    ) -> None:
        if code not in TYPED_ERROR_CODES:
            raise ValueError(f"unknown typed error code: {code!r}")
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = bool(retryable)
        self.details: Dict[str, Any] = dict(details or {})
        self.cause_code = cause_code

    def to_typed_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": dict(self.details),
            "cause_code": self.cause_code,
        }

    def __str__(self) -> str:
        if self.details:
            extra = ", ".join(f"{k}={v!r}" for k, v in self.details.items())
            return f"[{self.code}] {self.message} ({extra})"
        return f"[{self.code}] {self.message}"


def _require_pyarrow() -> None:
    if not _HAVE_PYARROW:
        raise GraphStoreError(
            "STORAGE",
            "pyarrow is required for the Parquet GraphStore",
            retryable=False,
            details={"dependency": "pyarrow"},
            cause_code="MISSING_PYARROW",
        )


# ---------------------------------------------------------------------------
# Schemas (versioned, evolution-friendly)
# ---------------------------------------------------------------------------


def _nodes_schema_v1() -> "pa.Schema":
    _require_pyarrow()
    return pa.schema(
        [
            ("id", pa.string()),
            ("type", pa.string()),
            ("name", pa.string()),
            ("properties_json", pa.string()),
            ("confidence", pa.float64()),
            ("source_text", pa.string()),
            ("schema_version", pa.string()),
        ]
    )


def _edges_schema_v1() -> "pa.Schema":
    _require_pyarrow()
    return pa.schema(
        [
            ("id", pa.string()),
            ("type", pa.string()),
            ("source_id", pa.string()),
            ("target_id", pa.string()),
            ("properties_json", pa.string()),
            ("confidence", pa.float64()),
            ("source_text", pa.string()),
            ("schema_version", pa.string()),
        ]
    )


def _adjacency_schema_v1() -> "pa.Schema":
    _require_pyarrow()
    return pa.schema(
        [
            ("node_id", pa.string()),
            ("direction", pa.string()),  # out | in
            ("neighbor_id", pa.string()),
            ("edge_id", pa.string()),
            ("edge_type", pa.string()),
            ("schema_version", pa.string()),
        ]
    )


def _properties_schema_v1() -> "pa.Schema":
    _require_pyarrow()
    return pa.schema(
        [
            ("owner_kind", pa.string()),  # node | edge
            ("owner_id", pa.string()),
            ("key", pa.string()),
            ("value_json", pa.string()),
            ("value_type", pa.string()),
            ("schema_version", pa.string()),
        ]
    )


def _index_schema_v1() -> "pa.Schema":
    _require_pyarrow()
    return pa.schema(
        [
            ("index_id", pa.string()),
            ("kind", pa.string()),
            ("key", pa.string()),
            ("value_json", pa.string()),
            ("refs_json", pa.string()),
            ("schema_version", pa.string()),
        ]
    )


# Evolution registry: version string -> schema builder. Newer versions must be
# supersets of older ones with additive nullable fields only.
_SCHEMA_BUILDERS: Dict[str, Dict[str, Callable[[], "pa.Schema"]]] = {
    PARTITION_NODES: {"1": _nodes_schema_v1},
    PARTITION_EDGES: {"1": _edges_schema_v1},
    PARTITION_ADJACENCY: {"1": _adjacency_schema_v1},
    PARTITION_PROPERTIES: {"1": _properties_schema_v1},
    "index": {"1": _index_schema_v1},
}

# Declared evolution path for nodes: v1 -> v2 adds optional label column.
def _nodes_schema_v2() -> "pa.Schema":
    _require_pyarrow()
    base = list(_nodes_schema_v1())
    base.append(pa.field("label", pa.string(), nullable=True))
    return pa.schema(base)


_SCHEMA_BUILDERS[PARTITION_NODES]["2"] = _nodes_schema_v2
DATASET_SCHEMA_VERSIONS[PARTITION_NODES] = "1"  # default write version


def get_partition_schema(
    kind: str,
    schema_version: Optional[str] = None,
) -> "pa.Schema":
    """Return the Arrow schema for a partition kind and schema version."""
    _require_pyarrow()
    versions = _SCHEMA_BUILDERS.get(kind)
    if versions is None:
        raise GraphStoreError(
            "INVALID_REQUEST",
            f"unknown partition kind for schema: {kind!r}",
            details={"kind": kind},
        )
    ver = schema_version or DATASET_SCHEMA_VERSIONS.get(kind, "1")
    builder = versions.get(str(ver))
    if builder is None:
        # Fallback: highest available version for forward compatibility.
        if ver not in versions:
            # Try to use latest known version and evolve.
            latest = max(versions.keys(), key=lambda v: int(v) if v.isdigit() else 0)
            if int(ver) if ver.isdigit() else 0 > int(latest) if latest.isdigit() else 0:
                # Unknown future version — use latest builder as base.
                builder = versions[latest]
            else:
                raise GraphStoreError(
                    "INVALID_REQUEST",
                    f"unsupported schema version {ver!r} for {kind}",
                    details={"kind": kind, "schema_version": ver, "known": sorted(versions)},
                )
    assert builder is not None
    return builder()


def evolve_table_to_schema(table: "pa.Table", target: "pa.Schema") -> "pa.Table":
    """Project ``table`` onto ``target`` with null-filled additive columns.

    Columns present in the table but absent from the target are dropped.
    Missing target columns are filled with typed nulls (schema evolution).
    """
    _require_pyarrow()
    columns: List["pa.Array"] = []
    names: List[str] = []
    for field in target:
        names.append(field.name)
        if field.name in table.column_names:
            col = table.column(field.name)
            if col.type != field.type:
                try:
                    col = pc.cast(col, field.type)
                except Exception as exc:
                    raise GraphStoreError(
                        "INTEGRITY",
                        f"cannot cast column {field.name!r} from {col.type} to {field.type}",
                        details={"column": field.name, "error": str(exc)[:300]},
                        cause_code="SCHEMA_CAST",
                    ) from exc
            columns.append(col)
        else:
            columns.append(pa.nulls(table.num_rows, type=field.type))
    return pa.Table.from_arrays(columns, schema=target)


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _json_loads(text: Optional[str]) -> Any:
    if text is None or text == "":
        return None
    return json.loads(text)


def _safe_slug(label: str, value: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise GraphStoreError(
            "INVALID_REQUEST",
            f"{label} must be a non-empty string without surrounding whitespace",
            details={label: value},
        )
    if "\x00" in value or "/" in value or "\\" in value or ".." in value:
        raise GraphStoreError(
            "INVALID_REQUEST",
            f"{label} contains illegal path characters",
            details={label: value},
        )
    return value


def _safe_revision_id(value: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise GraphStoreError(
            "INVALID_REQUEST",
            "revision_id must be a non-empty string",
            details={"revision_id": value},
        )
    if "\x00" in value or "/" in value or "\\" in value or value in {".", ".."}:
        raise GraphStoreError(
            "INVALID_REQUEST",
            "revision_id contains illegal path characters",
            details={"revision_id": value},
        )
    return value


def _sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _value_type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, (list, tuple)):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__


def normalize_node(node: Mapping[str, Any], *, schema_version: str) -> Dict[str, Any]:
    if not isinstance(node, Mapping):
        raise GraphStoreError(
            "INVALID_REQUEST",
            "node must be a mapping",
            details={"type": type(node).__name__},
        )
    node_id = node.get("id") or node.get("entity_id") or node.get("node_id")
    if not isinstance(node_id, str) or not node_id:
        raise GraphStoreError("INVALID_REQUEST", "node requires non-empty string id")
    props = node.get("properties") if "properties" in node else {}
    if props is None:
        props = {}
    if not isinstance(props, Mapping):
        raise GraphStoreError("INVALID_REQUEST", "node.properties must be a mapping")
    conf = node.get("confidence", 1.0)
    try:
        conf_f = float(conf) if conf is not None else 1.0
    except (TypeError, ValueError) as exc:
        raise GraphStoreError(
            "INVALID_REQUEST", "node.confidence must be numeric"
        ) from exc
    row: Dict[str, Any] = {
        "id": node_id,
        "type": str(node.get("type") or node.get("entity_type") or "entity"),
        "name": str(node.get("name") or ""),
        "properties_json": _json_dumps(dict(props)),
        "confidence": conf_f,
        "source_text": node.get("source_text"),
        "schema_version": schema_version,
    }
    if "label" in node:
        row["label"] = node.get("label")
    return row


def normalize_edge(edge: Mapping[str, Any], *, schema_version: str) -> Dict[str, Any]:
    if not isinstance(edge, Mapping):
        raise GraphStoreError(
            "INVALID_REQUEST",
            "edge must be a mapping",
            details={"type": type(edge).__name__},
        )
    edge_id = edge.get("id") or edge.get("relationship_id") or edge.get("edge_id")
    if not isinstance(edge_id, str) or not edge_id:
        raise GraphStoreError("INVALID_REQUEST", "edge requires non-empty string id")
    source_id = edge.get("source_id") or edge.get("source") or edge.get("start")
    target_id = edge.get("target_id") or edge.get("target") or edge.get("end")
    if not isinstance(source_id, str) or not source_id:
        raise GraphStoreError("INVALID_REQUEST", "edge requires source_id")
    if not isinstance(target_id, str) or not target_id:
        raise GraphStoreError("INVALID_REQUEST", "edge requires target_id")
    props = edge.get("properties") if "properties" in edge else {}
    if props is None:
        props = {}
    if not isinstance(props, Mapping):
        raise GraphStoreError("INVALID_REQUEST", "edge.properties must be a mapping")
    conf = edge.get("confidence", 1.0)
    try:
        conf_f = float(conf) if conf is not None else 1.0
    except (TypeError, ValueError) as exc:
        raise GraphStoreError(
            "INVALID_REQUEST", "edge.confidence must be numeric"
        ) from exc
    return {
        "id": edge_id,
        "type": str(edge.get("type") or edge.get("relationship_type") or "related_to"),
        "source_id": source_id,
        "target_id": target_id,
        "properties_json": _json_dumps(dict(props)),
        "confidence": conf_f,
        "source_text": edge.get("source_text"),
        "schema_version": schema_version,
    }


def expand_properties(
    owner_kind: str,
    owner_id: str,
    properties: Mapping[str, Any],
    *,
    schema_version: str,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for key, value in properties.items():
        if not isinstance(key, str) or not key:
            raise GraphStoreError("INVALID_REQUEST", "property key must be non-empty string")
        rows.append(
            {
                "owner_kind": owner_kind,
                "owner_id": owner_id,
                "key": key,
                "value_json": _json_dumps(value),
                "value_type": _value_type_name(value),
                "schema_version": schema_version,
            }
        )
    return rows


def build_adjacency_rows(
    edges: Sequence[Mapping[str, Any]],
    *,
    schema_version: str,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for edge in edges:
        edge_id = edge["id"]
        edge_type = edge["type"]
        source_id = edge["source_id"]
        target_id = edge["target_id"]
        rows.append(
            {
                "node_id": source_id,
                "direction": "out",
                "neighbor_id": target_id,
                "edge_id": edge_id,
                "edge_type": edge_type,
                "schema_version": schema_version,
            }
        )
        rows.append(
            {
                "node_id": target_id,
                "direction": "in",
                "neighbor_id": source_id,
                "edge_id": edge_id,
                "edge_type": edge_type,
                "schema_version": schema_version,
            }
        )
    return rows


def build_type_index_rows(
    nodes: Sequence[Mapping[str, Any]],
    *,
    schema_version: str,
    index_id: str = "idx-type",
) -> List[Dict[str, Any]]:
    buckets: Dict[str, List[str]] = {}
    for node in nodes:
        buckets.setdefault(str(node["type"]), []).append(str(node["id"]))
    rows: List[Dict[str, Any]] = []
    for key in sorted(buckets):
        refs = sorted(buckets[key])
        rows.append(
            {
                "index_id": index_id,
                "kind": "type",
                "key": key,
                "value_json": _json_dumps({"count": len(refs)}),
                "refs_json": _json_dumps(refs),
                "schema_version": schema_version,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Atomic filesystem helpers
# ---------------------------------------------------------------------------


def _fsync_path(path: Path) -> None:
    """fsync a file (or best-effort a directory)."""
    flags = os.O_RDONLY
    if path.is_file():
        flags = os.O_RDONLY
    elif path.is_dir():
        flags = os.O_RDONLY
    else:
        return
    try:
        fd = os.open(str(path), flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        # Some platforms reject directory fsync; ignore.
        pass
    finally:
        os.close(fd)


def _fsync_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _fsync_path(path)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write bytes via temp file + fsync + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(str(tmp), str(path))
        _fsync_directory(path.parent)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _atomic_write_text(path: Path, text: str) -> None:
    _atomic_write_bytes(path, text.encode("utf-8"))


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    text = json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n"
    _atomic_write_text(path, text)


def write_parquet_atomic(
    path: Path,
    table: "pa.Table",
    *,
    row_group_size: int,
    compression: str = PARQUET_COMPRESSION,
    schema_version: str,
    dataset_kind: str,
) -> Dict[str, Any]:
    """Atomically write a Parquet file with bounded row groups and statistics.

    Returns metadata: row_count, size_bytes, num_row_groups, checksum, path.
    """
    _require_pyarrow()
    if row_group_size < MIN_ROW_GROUP_SIZE or row_group_size > MAX_ROW_GROUP_SIZE:
        raise GraphStoreError(
            "INVALID_REQUEST",
            f"row_group_size must be in [{MIN_ROW_GROUP_SIZE}, {MAX_ROW_GROUP_SIZE}]",
            details={"row_group_size": row_group_size},
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    metadata = {
        b"kg.storage_profile": STORAGE_PROFILE.encode("utf-8"),
        b"kg.dataset_kind": dataset_kind.encode("utf-8"),
        b"kg.schema_version": schema_version.encode("utf-8"),
    }
    try:
        pq.write_table(
            table,
            tmp,
            compression=compression,
            row_group_size=row_group_size,
            use_dictionary=True,
            write_statistics=True,
            data_page_version="1.0",
            # Store custom key/value metadata on the schema.
            # pyarrow accepts schema with metadata; set on table schema.
        )
        # Re-write with schema metadata (write_table doesn't take metadata kw on all versions).
        # Ensure metadata is embedded via table.replace_schema_metadata.
    except TypeError:
        # Older pyarrow — retry without data_page_version.
        pq.write_table(
            table,
            tmp,
            compression=compression,
            row_group_size=row_group_size,
            use_dictionary=True,
            write_statistics=True,
        )
    except Exception as exc:
        if tmp.exists():
            tmp.unlink(missing_ok=True)  # type: ignore[arg-type]
        raise GraphStoreError(
            "STORAGE",
            f"failed to write parquet: {exc}",
            details={"path": str(path), "error_class": type(exc).__name__},
            cause_code="PARQUET_WRITE",
        ) from exc

    # Prefer a second write with embedded schema metadata when possible.
    try:
        table_meta = table.replace_schema_metadata(
            {
                **(table.schema.metadata or {}),
                **metadata,
            }
        )
        pq.write_table(
            table_meta,
            tmp,
            compression=compression,
            row_group_size=row_group_size,
            use_dictionary=True,
            write_statistics=True,
            data_page_version="1.0",
        )
    except Exception:
        # Keep first successful write if metadata rewrite fails.
        if not tmp.exists():
            raise

    # fsync temp then rename.
    try:
        with open(tmp, "rb+") as fh:
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(str(tmp), str(path))
        _fsync_directory(path.parent)
    except Exception as exc:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise GraphStoreError(
            "STORAGE",
            f"atomic rename failed for parquet: {exc}",
            details={"path": str(path)},
            cause_code="ATOMIC_RENAME",
        ) from exc

    size_bytes = path.stat().st_size
    checksum = _sha256_file(path)
    try:
        pf = pq.ParquetFile(path)
        num_row_groups = pf.metadata.num_row_groups
        # Enforce bounded row groups (except possibly the last group).
        for i in range(num_row_groups):
            rg_rows = pf.metadata.row_group(i).num_rows
            if i < num_row_groups - 1 and rg_rows > row_group_size:
                raise GraphStoreError(
                    "INTEGRITY",
                    "row group exceeds configured bound",
                    details={
                        "path": str(path),
                        "row_group": i,
                        "rows": rg_rows,
                        "bound": row_group_size,
                    },
                    cause_code="ROW_GROUP_BOUND",
                )
        row_count = pf.metadata.num_rows
    except GraphStoreError:
        raise
    except Exception as exc:
        raise GraphStoreError(
            "INTEGRITY",
            f"failed to read back written parquet: {exc}",
            details={"path": str(path)},
            cause_code="PARQUET_READBACK",
        ) from exc

    return {
        "path": str(path),
        "row_count": int(row_count),
        "size_bytes": int(size_bytes),
        "num_row_groups": int(num_row_groups),
        "checksum": checksum,
        "schema_version": schema_version,
        "dataset_kind": dataset_kind,
    }


# ---------------------------------------------------------------------------
# Integrity / corrupt detection
# ---------------------------------------------------------------------------


def detect_parquet_corruption(path: Path, *, expected_size: Optional[int] = None) -> Optional[str]:
    """Return a cause_code string if the file is corrupt/truncated, else None."""
    if not path.is_file():
        return "MISSING_FILE"
    size = path.stat().st_size
    if expected_size is not None and size != expected_size:
        return "SIZE_MISMATCH"
    # Minimal parquet: magic(4) + footer len(4) + magic(4) = 12 bytes absolute min,
    # real files are larger; treat tiny files as truncated.
    if size < 12:
        return "TRUNCATED"
    try:
        with open(path, "rb") as fh:
            head = fh.read(4)
            if head != PARQUET_MAGIC:
                return "BAD_MAGIC_HEADER"
            fh.seek(-4, os.SEEK_END)
            tail = fh.read(4)
            if tail != PARQUET_MAGIC:
                return "BAD_MAGIC_FOOTER"
            # Footer length is little-endian uint32 just before trailing magic.
            fh.seek(-8, os.SEEK_END)
            footer_len_bytes = fh.read(4)
            footer_len = int.from_bytes(footer_len_bytes, "little")
            if footer_len <= 0 or footer_len + 8 > size:
                return "TRUNCATED_FOOTER"
    except OSError:
        return "IO_ERROR"

    # Attempt full open via pyarrow when available.
    if _HAVE_PYARROW:
        try:
            pf = pq.ParquetFile(path)
            _ = pf.metadata.num_rows
            # Touch first row group statistics if present.
            if pf.metadata.num_row_groups > 0:
                _ = pf.metadata.row_group(0).num_rows
        except Exception:
            return "PARQUET_UNREADABLE"
    return None


def verify_parquet_file(
    path: Path,
    *,
    expected_checksum: Optional[str] = None,
    expected_size: Optional[int] = None,
    expected_rows: Optional[int] = None,
) -> Dict[str, Any]:
    """Verify magic, readability, size, optional checksum/rows; return stats."""
    cause = detect_parquet_corruption(path, expected_size=expected_size)
    if cause is not None:
        raise GraphStoreError(
            "INTEGRITY",
            f"parquet file failed integrity check: {cause}",
            retryable=False,
            details={"path": str(path), "cause": cause},
            cause_code=cause,
        )
    checksum = _sha256_file(path)
    if expected_checksum is not None and checksum != expected_checksum:
        raise GraphStoreError(
            "INTEGRITY",
            "parquet checksum mismatch",
            retryable=False,
            details={
                "path": str(path),
                "expected": expected_checksum,
                "actual": checksum,
            },
            cause_code="CHECKSUM_MISMATCH",
        )
    _require_pyarrow()
    pf = pq.ParquetFile(path)
    row_count = int(pf.metadata.num_rows)
    if expected_rows is not None and row_count != expected_rows:
        raise GraphStoreError(
            "INTEGRITY",
            "parquet row count mismatch",
            details={
                "path": str(path),
                "expected_rows": expected_rows,
                "actual_rows": row_count,
            },
            cause_code="ROW_COUNT_MISMATCH",
        )
    # Collect lightweight statistics from row-group metadata.
    column_stats: Dict[str, Any] = {}
    for rg_i in range(pf.metadata.num_row_groups):
        rg = pf.metadata.row_group(rg_i)
        for col_i in range(rg.num_columns):
            col = rg.column(col_i)
            name = col.path_in_schema
            entry = column_stats.setdefault(
                name,
                {"null_count": 0, "num_values": 0, "row_groups": 0},
            )
            entry["null_count"] += int(col.statistics.null_count) if col.statistics else 0
            entry["num_values"] += int(col.statistics.num_values) if col.statistics else 0
            entry["row_groups"] += 1
            if col.statistics is not None:
                try:
                    if col.statistics.has_min_max:
                        entry["has_min_max"] = True
                except Exception:
                    pass
    return {
        "path": str(path),
        "checksum": checksum,
        "size_bytes": path.stat().st_size,
        "row_count": row_count,
        "num_row_groups": pf.metadata.num_row_groups,
        "column_stats": column_stats,
        "schema_names": list(pf.schema_arrow.names) if hasattr(pf, "schema_arrow") else [],
    }


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def collect_table_statistics(table: "pa.Table", *, kind: str) -> Dict[str, Any]:
    """In-memory column statistics for a partition table."""
    _require_pyarrow()
    cols: Dict[str, Any] = {}
    for name in table.column_names:
        col = table.column(name)
        null_count = pc.sum(pc.is_null(col)).as_py() if table.num_rows else 0
        info: Dict[str, Any] = {
            "null_count": int(null_count or 0),
            "num_values": int(table.num_rows),
            "type": str(col.type),
        }
        # Min/max for string/numeric columns.
        try:
            if pa.types.is_floating(col.type) or pa.types.is_integer(col.type):
                info["min"] = pc.min(col).as_py()
                info["max"] = pc.max(col).as_py()
            elif pa.types.is_string(col.type) or pa.types.is_large_string(col.type):
                # Only compute when small enough to stay cheap.
                if table.num_rows <= 100_000:
                    info["min"] = pc.min(col).as_py()
                    info["max"] = pc.max(col).as_py()
        except Exception:
            pass
        cols[name] = info
    return {
        "kind": kind,
        "row_count": int(table.num_rows),
        "columns": cols,
    }


# ---------------------------------------------------------------------------
# Predicate pushdown
# ---------------------------------------------------------------------------


def _normalize_filters(filters: FilterSpec) -> Optional[List[Tuple[str, str, Any]]]:
    if filters is None:
        return None
    if not isinstance(filters, (list, tuple)):
        raise GraphStoreError(
            "INVALID_REQUEST",
            "filters must be a sequence of (column, op, value) triples",
            details={"type": type(filters).__name__},
        )
    if len(filters) == 0:
        return None
    # Nested DNF form [[(...), ...], ...] — pass through for pyarrow.
    if filters and isinstance(filters[0], (list, tuple)) and filters[0] and isinstance(
        filters[0][0], (list, tuple)
    ):
        return filters  # type: ignore[return-value]
    out: List[Tuple[str, str, Any]] = []
    for item in filters:
        if not isinstance(item, (list, tuple)) or len(item) != 3:
            raise GraphStoreError(
                "INVALID_REQUEST",
                "each filter must be a (column, op, value) triple",
                details={"filter": repr(item)[:200]},
            )
        col, op, val = item
        if not isinstance(col, str) or not col:
            raise GraphStoreError("INVALID_REQUEST", "filter column must be non-empty string")
        if not isinstance(op, str) or not op:
            raise GraphStoreError("INVALID_REQUEST", "filter op must be non-empty string")
        out.append((col, op, val))
    return out


def read_parquet_filtered(
    path: Path,
    *,
    filters: FilterSpec = None,
    columns: Optional[Sequence[str]] = None,
    target_schema: Optional["pa.Schema"] = None,
) -> "pa.Table":
    """Read a Parquet file with optional predicate pushdown and schema evolution."""
    _require_pyarrow()
    if not path.is_file():
        raise GraphStoreError(
            "NOT_FOUND",
            f"parquet partition not found: {path}",
            details={"path": str(path)},
        )
    cause = detect_parquet_corruption(path)
    if cause is not None:
        raise GraphStoreError(
            "INTEGRITY",
            f"cannot read corrupt parquet: {cause}",
            details={"path": str(path)},
            cause_code=cause,
        )
    filt = _normalize_filters(filters)
    try:
        table = pq.read_table(path, filters=filt, columns=list(columns) if columns else None)
    except GraphStoreError:
        raise
    except Exception as exc:
        # Some pyarrow builds reject certain filter ops; surface as invalid.
        msg = str(exc).lower()
        if "filter" in msg or "predicate" in msg or "invalid" in msg:
            raise GraphStoreError(
                "INVALID_REQUEST",
                f"predicate pushdown failed: {exc}",
                details={"path": str(path), "filters": filt},
                cause_code="FILTER_ERROR",
            ) from exc
        raise GraphStoreError(
            "STORAGE",
            f"failed to read parquet: {exc}",
            details={"path": str(path)},
            cause_code="PARQUET_READ",
        ) from exc
    if target_schema is not None:
        # When columns were projected, only evolve among requested fields.
        if columns is not None:
            fields = [target_schema.field(n) for n in columns if n in target_schema.names]
            # Keep any selected columns that exist only on disk.
            for n in table.column_names:
                if n not in {f.name for f in fields}:
                    fields.append(table.schema.field(n))
            target_schema = pa.schema(fields)
        table = evolve_table_to_schema(table, target_schema)
    return table


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PartitionWriteResult:
    kind: str
    relative_path: str
    row_count: int
    size_bytes: int
    num_row_groups: int
    checksum: str
    schema_version: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "relative_path": self.relative_path,
            "row_count": self.row_count,
            "size_bytes": self.size_bytes,
            "num_row_groups": self.num_row_groups,
            "checksum": self.checksum,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class PublishResult:
    tenant: str
    graph_id: str
    revision_id: str
    path: str
    manifest: Dict[str, Any]
    partitions: Dict[str, PartitionWriteResult]
    indexes: Dict[str, PartitionWriteResult]
    statistics: Dict[str, Any]
    checksums: Dict[str, str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tenant": self.tenant,
            "graph_id": self.graph_id,
            "revision_id": self.revision_id,
            "path": self.path,
            "manifest": self.manifest,
            "partitions": {k: v.to_dict() for k, v in self.partitions.items()},
            "indexes": {k: v.to_dict() for k, v in self.indexes.items()},
            "statistics": self.statistics,
            "checksums": dict(self.checksums),
        }


@dataclass
class RevisionHandle:
    """Opened, verified revision for scan operations."""

    store: "ParquetGraphStore"
    tenant: str
    graph_id: str
    revision_id: str
    revision_dir: Path
    manifest: Dict[str, Any]
    checksums: Dict[str, str]
    statistics: Dict[str, Any]

    def scan_nodes(
        self,
        *,
        filters: FilterSpec = None,
        columns: Optional[Sequence[str]] = None,
        schema_version: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return self.store.scan_nodes(
            self.tenant,
            self.graph_id,
            self.revision_id,
            filters=filters,
            columns=columns,
            schema_version=schema_version,
        )

    def scan_edges(
        self,
        *,
        filters: FilterSpec = None,
        columns: Optional[Sequence[str]] = None,
        schema_version: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return self.store.scan_edges(
            self.tenant,
            self.graph_id,
            self.revision_id,
            filters=filters,
            columns=columns,
            schema_version=schema_version,
        )

    def scan_adjacency(
        self,
        *,
        filters: FilterSpec = None,
        columns: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        return self.store.scan_adjacency(
            self.tenant,
            self.graph_id,
            self.revision_id,
            filters=filters,
            columns=columns,
        )

    def scan_properties(
        self,
        *,
        filters: FilterSpec = None,
        columns: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        return self.store.scan_properties(
            self.tenant,
            self.graph_id,
            self.revision_id,
            filters=filters,
            columns=columns,
        )

    def scan_index(
        self,
        index_id: str,
        *,
        filters: FilterSpec = None,
        columns: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        return self.store.scan_index(
            self.tenant,
            self.graph_id,
            self.revision_id,
            index_id,
            filters=filters,
            columns=columns,
        )


# ---------------------------------------------------------------------------
# ParquetGraphStore
# ---------------------------------------------------------------------------


class ParquetGraphStore:
    """Versioned local Parquet GraphStore (storage profile ``parquet``).

    Layout (immutable revision directories)::

        <root>/<tenant>/<graph_id>/revisions/<revision_id>/
            _SUCCESS
            manifest.json
            statistics.json
            checksums.json
            nodes.parquet
            edges.parquet
            adjacency.parquet
            properties.parquet
            indexes/<index_id>.parquet

    Publication stages under ``<root>/.staging/<uuid>/`` and atomically
    renames the completed directory into place after fsync.
    """

    storage_profile: str = STORAGE_PROFILE

    def __init__(
        self,
        root_dir: PathLike,
        *,
        row_group_size: int = DEFAULT_ROW_GROUP_SIZE,
        max_row_group_size: int = MAX_ROW_GROUP_SIZE,
        compression: str = PARQUET_COMPRESSION,
        cancel_check: Optional[CancelCheck] = None,
        verify_on_open: bool = True,
    ) -> None:
        _require_pyarrow()
        if row_group_size < MIN_ROW_GROUP_SIZE or row_group_size > max_row_group_size:
            raise GraphStoreError(
                "INVALID_REQUEST",
                "row_group_size out of bounds",
                details={
                    "row_group_size": row_group_size,
                    "max_row_group_size": max_row_group_size,
                },
            )
        if max_row_group_size > MAX_ROW_GROUP_SIZE:
            raise GraphStoreError(
                "INVALID_REQUEST",
                f"max_row_group_size cannot exceed {MAX_ROW_GROUP_SIZE}",
                details={"max_row_group_size": max_row_group_size},
            )
        self.root_dir = Path(root_dir).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.row_group_size = int(row_group_size)
        self.max_row_group_size = int(max_row_group_size)
        self.compression = compression
        self._cancel_check = cancel_check
        self.verify_on_open = verify_on_open
        self._lock = threading.RLock()
        self._closed = False

    # -- lifecycle ---------------------------------------------------------

    @classmethod
    def open(cls, root_dir: PathLike, **kwargs: Any) -> "ParquetGraphStore":
        return cls(root_dir, **kwargs)

    def close(self) -> None:
        self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise GraphStoreError("STORAGE", "ParquetGraphStore is closed")

    def _check_cancelled(self) -> None:
        if self._cancel_check is not None:
            self._cancel_check()

    # -- paths -------------------------------------------------------------

    def graph_dir(self, tenant: str, graph_id: str) -> Path:
        t = _safe_slug("tenant", tenant)
        g = _safe_slug("graph_id", graph_id)
        return self.root_dir / t / g

    def revisions_dir(self, tenant: str, graph_id: str) -> Path:
        return self.graph_dir(tenant, graph_id) / "revisions"

    def revision_dir(self, tenant: str, graph_id: str, revision_id: str) -> Path:
        r = _safe_revision_id(revision_id)
        return self.revisions_dir(tenant, graph_id) / r

    def staging_root(self) -> Path:
        return self.root_dir / STAGING_DIRNAME

    # -- listing -----------------------------------------------------------

    def list_revisions(self, tenant: str, graph_id: str) -> List[str]:
        self._ensure_open()
        base = self.revisions_dir(tenant, graph_id)
        if not base.is_dir():
            return []
        out: List[str] = []
        for child in sorted(base.iterdir()):
            if child.is_dir() and (child / PUBLICATION_MARKER).is_file():
                out.append(child.name)
        return out

    def has_revision(self, tenant: str, graph_id: str, revision_id: str) -> bool:
        d = self.revision_dir(tenant, graph_id, revision_id)
        return d.is_dir() and (d / PUBLICATION_MARKER).is_file()

    # -- publish -----------------------------------------------------------

    def publish_revision(
        self,
        *,
        tenant: str,
        graph_id: str,
        revision_id: str,
        nodes: Optional[Sequence[Mapping[str, Any]]] = None,
        edges: Optional[Sequence[Mapping[str, Any]]] = None,
        properties: Optional[Sequence[Mapping[str, Any]]] = None,
        indexes: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None,
        adjacency: Optional[Sequence[Mapping[str, Any]]] = None,
        parent_revision: Optional[str] = None,
        schema_id: str = DEFAULT_SCHEMA_ID,
        schema_version: str = DEFAULT_SCHEMA_VERSION,
        graph_kind: str = DEFAULT_GRAPH_KIND,
        ontology_id: str = DEFAULT_ONTOLOGY_ID,
        ontology_version: str = DEFAULT_ONTOLOGY_VERSION,
        partition_schema_versions: Optional[Mapping[str, str]] = None,
        build_type_index: bool = True,
        provenance: Optional[Mapping[str, Any]] = None,
        overwrite: bool = False,
    ) -> PublishResult:
        """Normalize graph data and publish an immutable revision directory.

        Atomicity: data is written under ``.staging/<uuid>/`` with per-file
        temp/fsync/rename, the staging directory is fsynced, then the whole
        directory is ``os.replace``d into
        ``<tenant>/<graph_id>/revisions/<revision_id>/``. Readers only see
        the revision after ``_SUCCESS`` exists (written last inside staging
        before the directory rename).
        """
        self._ensure_open()
        self._check_cancelled()
        _require_pyarrow()

        tenant_n = _safe_slug("tenant", tenant)
        graph_n = _safe_slug("graph_id", graph_id)
        rev_n = _safe_revision_id(revision_id)

        final_dir = self.revision_dir(tenant_n, graph_n, rev_n)
        if final_dir.exists():
            if not overwrite:
                if (final_dir / PUBLICATION_MARKER).is_file():
                    raise GraphStoreError(
                        "ALREADY_EXISTS",
                        f"revision already published: {rev_n}",
                        details={
                            "tenant": tenant_n,
                            "graph_id": graph_n,
                            "revision_id": rev_n,
                        },
                    )
                # Incomplete prior publish — remove and rewrite.
                shutil.rmtree(final_dir)
            else:
                shutil.rmtree(final_dir)

        part_versions = {
            PARTITION_NODES: DATASET_SCHEMA_VERSIONS[PARTITION_NODES],
            PARTITION_EDGES: DATASET_SCHEMA_VERSIONS[PARTITION_EDGES],
            PARTITION_ADJACENCY: DATASET_SCHEMA_VERSIONS[PARTITION_ADJACENCY],
            PARTITION_PROPERTIES: DATASET_SCHEMA_VERSIONS[PARTITION_PROPERTIES],
            "index": DATASET_SCHEMA_VERSIONS["index"],
        }
        if partition_schema_versions:
            for k, v in partition_schema_versions.items():
                part_versions[str(k)] = str(v)

        nodes_in = list(nodes or [])
        edges_in = list(edges or [])

        node_rows = [
            normalize_node(n, schema_version=part_versions[PARTITION_NODES]) for n in nodes_in
        ]
        edge_rows = [
            normalize_edge(e, schema_version=part_versions[PARTITION_EDGES]) for e in edges_in
        ]

        # Normalized property rows (explicit + expanded from node/edge maps).
        prop_rows: List[Dict[str, Any]] = []
        if properties:
            for p in properties:
                if not isinstance(p, Mapping):
                    raise GraphStoreError("INVALID_REQUEST", "property row must be a mapping")
                prop_rows.append(
                    {
                        "owner_kind": str(p.get("owner_kind") or "node"),
                        "owner_id": str(p["owner_id"]),
                        "key": str(p["key"]),
                        "value_json": p.get("value_json")
                        if "value_json" in p
                        else _json_dumps(p.get("value")),
                        "value_type": str(
                            p.get("value_type") or _value_type_name(p.get("value"))
                        ),
                        "schema_version": part_versions[PARTITION_PROPERTIES],
                    }
                )
        else:
            for n in node_rows:
                props = _json_loads(n["properties_json"]) or {}
                prop_rows.extend(
                    expand_properties(
                        "node",
                        n["id"],
                        props,
                        schema_version=part_versions[PARTITION_PROPERTIES],
                    )
                )
            for e in edge_rows:
                props = _json_loads(e["properties_json"]) or {}
                prop_rows.extend(
                    expand_properties(
                        "edge",
                        e["id"],
                        props,
                        schema_version=part_versions[PARTITION_PROPERTIES],
                    )
                )

        if adjacency is not None:
            adj_rows = []
            for a in adjacency:
                if not isinstance(a, Mapping):
                    raise GraphStoreError("INVALID_REQUEST", "adjacency row must be a mapping")
                adj_rows.append(
                    {
                        "node_id": str(a["node_id"]),
                        "direction": str(a.get("direction") or "out"),
                        "neighbor_id": str(a["neighbor_id"]),
                        "edge_id": str(a.get("edge_id") or ""),
                        "edge_type": str(a.get("edge_type") or ""),
                        "schema_version": part_versions[PARTITION_ADJACENCY],
                    }
                )
        else:
            adj_rows = build_adjacency_rows(
                edge_rows, schema_version=part_versions[PARTITION_ADJACENCY]
            )

        index_payloads: Dict[str, List[Dict[str, Any]]] = {}
        if indexes:
            for iid, rows in indexes.items():
                if not isinstance(iid, str) or not iid:
                    raise GraphStoreError("INVALID_REQUEST", "index_id must be non-empty")
                _safe_revision_id(iid)  # same path safety rules
                normalized_idx: List[Dict[str, Any]] = []
                for row in rows:
                    if not isinstance(row, Mapping):
                        raise GraphStoreError("INVALID_REQUEST", "index row must be a mapping")
                    normalized_idx.append(
                        {
                            "index_id": str(row.get("index_id") or iid),
                            "kind": str(row.get("kind") or "other"),
                            "key": str(row.get("key") or ""),
                            "value_json": row.get("value_json")
                            if "value_json" in row
                            else _json_dumps(row.get("value")),
                            "refs_json": row.get("refs_json")
                            if "refs_json" in row
                            else _json_dumps(row.get("refs") or []),
                            "schema_version": part_versions["index"],
                        }
                    )
                index_payloads[iid] = normalized_idx
        elif build_type_index:
            index_payloads["idx-type"] = build_type_index_rows(
                node_rows, schema_version=part_versions["index"]
            )

        # Build Arrow tables with (possibly evolved) schemas.
        node_schema = get_partition_schema(
            PARTITION_NODES, part_versions[PARTITION_NODES]
        )
        edge_schema = get_partition_schema(
            PARTITION_EDGES, part_versions[PARTITION_EDGES]
        )
        adj_schema = get_partition_schema(
            PARTITION_ADJACENCY, part_versions[PARTITION_ADJACENCY]
        )
        prop_schema = get_partition_schema(
            PARTITION_PROPERTIES, part_versions[PARTITION_PROPERTIES]
        )
        index_schema = get_partition_schema("index", part_versions["index"])

        nodes_table = self._rows_to_table(node_rows, node_schema)
        edges_table = self._rows_to_table(edge_rows, edge_schema)
        adj_table = self._rows_to_table(adj_rows, adj_schema)
        props_table = self._rows_to_table(prop_rows, prop_schema)

        staging_id = uuid.uuid4().hex
        staging_dir = self.staging_root() / staging_id
        try:
            with self._lock:
                staging_dir.mkdir(parents=True, exist_ok=False)
                partition_results: Dict[str, PartitionWriteResult] = {}
                index_results: Dict[str, PartitionWriteResult] = {}
                checksums: Dict[str, str] = {}
                statistics: Dict[str, Any] = {"partitions": {}, "indexes": {}}

                def _write_partition(
                    kind: str,
                    relative: str,
                    table: "pa.Table",
                    schema_ver: str,
                ) -> PartitionWriteResult:
                    self._check_cancelled()
                    target = staging_dir / relative
                    meta = write_parquet_atomic(
                        target,
                        table,
                        row_group_size=self.row_group_size,
                        compression=self.compression,
                        schema_version=schema_ver,
                        dataset_kind=kind,
                    )
                    # Enforce max bound.
                    if meta["num_row_groups"] > 0:
                        pf = pq.ParquetFile(target)
                        for i in range(pf.metadata.num_row_groups - 1):
                            if pf.metadata.row_group(i).num_rows > self.max_row_group_size:
                                raise GraphStoreError(
                                    "INTEGRITY",
                                    "row group exceeds max bound",
                                    details={
                                        "kind": kind,
                                        "rows": pf.metadata.row_group(i).num_rows,
                                        "max": self.max_row_group_size,
                                    },
                                    cause_code="ROW_GROUP_BOUND",
                                )
                    checksums[relative] = meta["checksum"]
                    statistics["partitions"][kind] = collect_table_statistics(
                        table, kind=kind
                    )
                    statistics["partitions"][kind]["num_row_groups"] = meta["num_row_groups"]
                    return PartitionWriteResult(
                        kind=kind,
                        relative_path=relative,
                        row_count=meta["row_count"],
                        size_bytes=meta["size_bytes"],
                        num_row_groups=meta["num_row_groups"],
                        checksum=meta["checksum"],
                        schema_version=schema_ver,
                    )

                partition_results[PARTITION_NODES] = _write_partition(
                    PARTITION_NODES,
                    f"{PARTITION_NODES}.parquet",
                    nodes_table,
                    part_versions[PARTITION_NODES],
                )
                partition_results[PARTITION_EDGES] = _write_partition(
                    PARTITION_EDGES,
                    f"{PARTITION_EDGES}.parquet",
                    edges_table,
                    part_versions[PARTITION_EDGES],
                )
                partition_results[PARTITION_ADJACENCY] = _write_partition(
                    PARTITION_ADJACENCY,
                    f"{PARTITION_ADJACENCY}.parquet",
                    adj_table,
                    part_versions[PARTITION_ADJACENCY],
                )
                partition_results[PARTITION_PROPERTIES] = _write_partition(
                    PARTITION_PROPERTIES,
                    f"{PARTITION_PROPERTIES}.parquet",
                    props_table,
                    part_versions[PARTITION_PROPERTIES],
                )

                (staging_dir / INDEX_DIRNAME).mkdir(parents=True, exist_ok=True)
                for iid, rows in index_payloads.items():
                    idx_table = self._rows_to_table(rows, index_schema)
                    rel = f"{INDEX_DIRNAME}/{iid}.parquet"
                    result = _write_partition(
                        "index",
                        rel,
                        idx_table,
                        part_versions["index"],
                    )
                    # re-tag kind for indexes map
                    index_results[iid] = PartitionWriteResult(
                        kind=str(rows[0]["kind"]) if rows else "other",
                        relative_path=rel,
                        row_count=result.row_count,
                        size_bytes=result.size_bytes,
                        num_row_groups=result.num_row_groups,
                        checksum=result.checksum,
                        schema_version=result.schema_version,
                    )
                    statistics["indexes"][iid] = collect_table_statistics(
                        idx_table, kind=f"index:{iid}"
                    )

                # Build KGP-004 revision manifest (payload descriptors only).
                manifest = self._build_manifest(
                    tenant=tenant_n,
                    graph_id=graph_n,
                    revision_id=rev_n,
                    parent_revision=parent_revision,
                    schema_id=schema_id,
                    schema_version=schema_version,
                    graph_kind=graph_kind,
                    ontology_id=ontology_id,
                    ontology_version=ontology_version,
                    partition_results=partition_results,
                    index_results=index_results,
                    node_count=len(node_rows),
                    edge_count=len(edge_rows),
                    provenance=provenance,
                )
                manifest_dict = (
                    manifest.to_dict()
                    if hasattr(manifest, "to_dict")
                    else dict(manifest)
                )
                _atomic_write_json(staging_dir / MANIFEST_FILENAME, manifest_dict)
                checksums[MANIFEST_FILENAME] = _sha256_file(staging_dir / MANIFEST_FILENAME)

                stats_payload = {
                    "tenant": tenant_n,
                    "graph_id": graph_n,
                    "revision_id": rev_n,
                    "schema_version": schema_version,
                    "row_group_size": self.row_group_size,
                    "partitions": statistics["partitions"],
                    "indexes": statistics["indexes"],
                }
                _atomic_write_json(staging_dir / STATS_FILENAME, stats_payload)
                checksums[STATS_FILENAME] = _sha256_file(staging_dir / STATS_FILENAME)

                _atomic_write_json(staging_dir / CHECKSUMS_FILENAME, checksums)

                # Publication marker last inside staging.
                _atomic_write_text(
                    staging_dir / PUBLICATION_MARKER,
                    _json_dumps(
                        {
                            "tenant": tenant_n,
                            "graph_id": graph_n,
                            "revision_id": rev_n,
                            "storage_profile": STORAGE_PROFILE,
                            "published": True,
                        }
                    )
                    + "\n",
                )

                # Fsync staging directory tree entries, then atomic publish.
                _fsync_directory(staging_dir)
                _fsync_directory(staging_dir / INDEX_DIRNAME)
                final_parent = final_dir.parent
                final_parent.mkdir(parents=True, exist_ok=True)
                _fsync_directory(final_parent)
                # Directory rename is atomic when dest does not exist.
                os.replace(str(staging_dir), str(final_dir))
                _fsync_directory(final_parent)
        except GraphStoreError:
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)
            raise
        except Exception as exc:
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)
            # Manifest contract errors are client/input problems, not storage I/O.
            exc_name = type(exc).__name__
            if "Manifest" in exc_name or getattr(exc, "code", None):
                code = "INVALID_REQUEST"
                if "Integrity" in exc_name:
                    code = "INTEGRITY"
                raise GraphStoreError(
                    code,
                    f"publish_revision failed: {exc}",
                    details={
                        "tenant": tenant_n,
                        "graph_id": graph_n,
                        "revision_id": rev_n,
                        "error_class": exc_name,
                        "manifest_code": getattr(exc, "code", None),
                    },
                    cause_code=str(getattr(exc, "code", "PUBLISH_FAILED")),
                ) from exc
            raise GraphStoreError(
                "STORAGE",
                f"publish_revision failed: {exc}",
                details={
                    "tenant": tenant_n,
                    "graph_id": graph_n,
                    "revision_id": rev_n,
                    "error_class": exc_name,
                },
                cause_code="PUBLISH_FAILED",
            ) from exc
        finally:
            # Clean orphaned staging if somehow left behind.
            if staging_dir.exists() and not final_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)

        # Post-publish verification (restart-style integrity).
        self.verify_revision(tenant_n, graph_n, rev_n)

        return PublishResult(
            tenant=tenant_n,
            graph_id=graph_n,
            revision_id=rev_n,
            path=str(final_dir),
            manifest=manifest_dict,
            partitions=partition_results,
            indexes=index_results,
            statistics=stats_payload,
            checksums=checksums,
        )

    def _rows_to_table(
        self,
        rows: Sequence[Mapping[str, Any]],
        schema: "pa.Schema",
    ) -> "pa.Table":
        _require_pyarrow()
        if not rows:
            return schema.empty_table()
        # Align rows to schema field order; fill missing with None.
        columns: Dict[str, List[Any]] = {f.name: [] for f in schema}
        for row in rows:
            for f in schema:
                columns[f.name].append(row.get(f.name))
        arrays = []
        for f in schema:
            arrays.append(pa.array(columns[f.name], type=f.type))
        return pa.Table.from_arrays(arrays, schema=schema)

    def _build_manifest(
        self,
        *,
        tenant: str,
        graph_id: str,
        revision_id: str,
        parent_revision: Optional[str],
        schema_id: str,
        schema_version: str,
        graph_kind: str,
        ontology_id: str,
        ontology_version: str,
        partition_results: Mapping[str, PartitionWriteResult],
        index_results: Mapping[str, PartitionWriteResult],
        node_count: int,
        edge_count: int,
        provenance: Optional[Mapping[str, Any]],
    ) -> Any:
        from ipfs_datasets_py.knowledge_graphs.contracts.manifest import (
            ContentChecksum,
            GraphCounts,
            IndexDescriptor,
            PartitionDescriptor,
            ProvenanceDescriptor,
            build_graph_revision_manifest,
        )

        partitions = []
        for kind, result in sorted(partition_results.items(), key=lambda kv: f"part-{kv[0]}"):
            partitions.append(
                PartitionDescriptor(
                    partition_id=f"part-{kind}",
                    kind=kind if kind in {
                        "nodes", "edges", "adjacency", "properties",
                        "documents", "vectors", "postings", "communities", "other",
                    } else "other",
                    path=result.relative_path,
                    codec=DEFAULT_CODEC,
                    checksum=ContentChecksum.from_sha256_hex(result.checksum),
                    row_count=result.row_count,
                    size_bytes=result.size_bytes,
                    cid=ContentChecksum.from_sha256_hex(result.checksum).as_cid(),
                    schema_version=result.schema_version,
                )
            )
        partitions.sort(key=lambda p: p.partition_id)

        index_descs = []
        for iid, result in sorted(index_results.items(), key=lambda kv: kv[0]):
            kind = result.kind if result.kind in {
                "btree", "hash", "bloom", "vector", "fulltext",
                "type", "adjacency", "composite", "other",
            } else "other"
            index_descs.append(
                IndexDescriptor(
                    index_id=iid,
                    kind=kind,
                    path=result.relative_path,
                    codec=DEFAULT_CODEC,
                    checksum=ContentChecksum.from_sha256_hex(result.checksum),
                    fields=self._index_fields_for_kind(kind),
                    size_bytes=result.size_bytes,
                    cid=ContentChecksum.from_sha256_hex(result.checksum).as_cid(),
                    schema_version=result.schema_version,
                )
            )
        index_descs.sort(key=lambda i: i.index_id)

        prov_map = dict(provenance or {})
        prov = ProvenanceDescriptor(
            producer_id=str(prov_map.get("producer_id") or "parquet-graph-store"),
            producer_version=str(prov_map.get("producer_version") or "1"),
            source=str(prov_map.get("source") or "publish_revision"),
            created_at=str(prov_map.get("created_at") or "1970-01-01T00:00:00Z"),
            extra={
                k: v
                for k, v in prov_map.items()
                if k
                not in {
                    "producer_id",
                    "producer_version",
                    "source",
                    "created_at",
                }
                and isinstance(v, (str, int, float, bool, type(None)))
            }
            or None,
        )

        return build_graph_revision_manifest(
            tenant=tenant,
            graph_id=graph_id,
            revision_id=revision_id,
            parent_revision=parent_revision,
            schema_id=schema_id,
            schema_version=schema_version,
            ontology_id=ontology_id,
            ontology_version=ontology_version,
            graph_kind=graph_kind,
            storage_profile=STORAGE_PROFILE,
            codec=DEFAULT_CODEC,
            counts=GraphCounts(
                node_count=node_count,
                edge_count=edge_count,
                document_count=0,
            ),
            partitions=partitions,
            indexes=index_descs,
            provenance=prov,
            include_root_cid=True,
        )

    @staticmethod
    def _index_fields_for_kind(kind: str) -> Tuple[str, ...]:
        if kind == "type":
            return ("type",)
        if kind == "adjacency":
            return ("node_id", "direction")
        if kind == "btree":
            return ("key",)
        return ("key",)

    # -- open / verify -----------------------------------------------------

    def get_manifest(
        self,
        tenant: str,
        graph_id: str,
        revision_id: str,
    ) -> Dict[str, Any]:
        self._ensure_open()
        path = self.revision_dir(tenant, graph_id, revision_id) / MANIFEST_FILENAME
        if not path.is_file():
            raise GraphStoreError(
                "NOT_FOUND",
                "revision manifest not found",
                details={
                    "tenant": tenant,
                    "graph_id": graph_id,
                    "revision_id": revision_id,
                },
            )
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def get_statistics(
        self,
        tenant: str,
        graph_id: str,
        revision_id: str,
    ) -> Dict[str, Any]:
        self._ensure_open()
        path = self.revision_dir(tenant, graph_id, revision_id) / STATS_FILENAME
        if not path.is_file():
            raise GraphStoreError(
                "NOT_FOUND",
                "revision statistics not found",
                details={
                    "tenant": tenant,
                    "graph_id": graph_id,
                    "revision_id": revision_id,
                },
            )
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def get_checksums(
        self,
        tenant: str,
        graph_id: str,
        revision_id: str,
    ) -> Dict[str, str]:
        self._ensure_open()
        path = self.revision_dir(tenant, graph_id, revision_id) / CHECKSUMS_FILENAME
        if not path.is_file():
            raise GraphStoreError(
                "NOT_FOUND",
                "revision checksums not found",
                details={
                    "tenant": tenant,
                    "graph_id": graph_id,
                    "revision_id": revision_id,
                },
            )
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return {str(k): str(v) for k, v in data.items()}

    def verify_revision(
        self,
        tenant: str,
        graph_id: str,
        revision_id: str,
    ) -> Dict[str, Any]:
        """Full integrity verification: marker, magic, size, checksums, rows."""
        self._ensure_open()
        rev_dir = self.revision_dir(tenant, graph_id, revision_id)
        if not rev_dir.is_dir():
            raise GraphStoreError(
                "NOT_FOUND",
                "revision directory not found",
                details={
                    "tenant": tenant,
                    "graph_id": graph_id,
                    "revision_id": revision_id,
                },
            )
        marker = rev_dir / PUBLICATION_MARKER
        if not marker.is_file():
            raise GraphStoreError(
                "INTEGRITY",
                "revision missing publication marker (incomplete publish)",
                details={"path": str(rev_dir)},
                cause_code="MISSING_SUCCESS_MARKER",
            )

        checksums = self.get_checksums(tenant, graph_id, revision_id)
        manifest = self.get_manifest(tenant, graph_id, revision_id)
        verified_files: Dict[str, Any] = {}

        # Verify every checksums.json entry that points at a relative path.
        for rel, expected in checksums.items():
            if rel in {CHECKSUMS_FILENAME}:
                continue
            path = rev_dir / rel
            if rel.endswith(".parquet"):
                # Look up expected size/rows from manifest partitions/indexes.
                expected_rows = None
                expected_size = None
                for part in manifest.get("partitions") or []:
                    if part.get("path") == rel:
                        expected_rows = part.get("row_count")
                        expected_size = part.get("size_bytes")
                        break
                for idx in manifest.get("indexes") or []:
                    if idx.get("path") == rel:
                        expected_size = idx.get("size_bytes")
                        break
                info = verify_parquet_file(
                    path,
                    expected_checksum=expected,
                    expected_size=expected_size,
                    expected_rows=expected_rows,
                )
                verified_files[rel] = info
            else:
                if not path.is_file():
                    raise GraphStoreError(
                        "INTEGRITY",
                        f"missing revision file: {rel}",
                        details={"path": str(path)},
                        cause_code="MISSING_FILE",
                    )
                actual = _sha256_file(path)
                if actual != expected:
                    raise GraphStoreError(
                        "INTEGRITY",
                        f"checksum mismatch for {rel}",
                        details={"expected": expected, "actual": actual},
                        cause_code="CHECKSUM_MISMATCH",
                    )
                verified_files[rel] = {
                    "path": str(path),
                    "checksum": actual,
                    "size_bytes": path.stat().st_size,
                }

        return {
            "tenant": tenant,
            "graph_id": graph_id,
            "revision_id": revision_id,
            "ok": True,
            "files": verified_files,
            "manifest_revision_id": manifest.get("revision_id"),
        }

    def open_revision(
        self,
        tenant: str,
        graph_id: str,
        revision_id: str,
        *,
        verify: Optional[bool] = None,
    ) -> RevisionHandle:
        self._ensure_open()
        do_verify = self.verify_on_open if verify is None else bool(verify)
        if do_verify:
            self.verify_revision(tenant, graph_id, revision_id)
        elif not self.has_revision(tenant, graph_id, revision_id):
            raise GraphStoreError(
                "NOT_FOUND",
                "revision not found or incomplete",
                details={
                    "tenant": tenant,
                    "graph_id": graph_id,
                    "revision_id": revision_id,
                },
            )
        return RevisionHandle(
            store=self,
            tenant=tenant,
            graph_id=graph_id,
            revision_id=revision_id,
            revision_dir=self.revision_dir(tenant, graph_id, revision_id),
            manifest=self.get_manifest(tenant, graph_id, revision_id),
            checksums=self.get_checksums(tenant, graph_id, revision_id),
            statistics=self.get_statistics(tenant, graph_id, revision_id),
        )

    # -- scans (predicate pushdown) ----------------------------------------

    def _partition_path(
        self,
        tenant: str,
        graph_id: str,
        revision_id: str,
        relative: str,
    ) -> Path:
        return self.revision_dir(tenant, graph_id, revision_id) / relative

    def _table_to_dicts(self, table: "pa.Table") -> List[Dict[str, Any]]:
        if table.num_rows == 0:
            return []
        # Convert column-wise for predictable types.
        cols = {name: table.column(name).to_pylist() for name in table.column_names}
        rows: List[Dict[str, Any]] = []
        for i in range(table.num_rows):
            rows.append({name: cols[name][i] for name in table.column_names})
        return rows

    def scan_nodes(
        self,
        tenant: str,
        graph_id: str,
        revision_id: str,
        *,
        filters: FilterSpec = None,
        columns: Optional[Sequence[str]] = None,
        schema_version: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        self._ensure_open()
        self._check_cancelled()
        path = self._partition_path(
            tenant, graph_id, revision_id, f"{PARTITION_NODES}.parquet"
        )
        target = None
        if schema_version is not None:
            target = get_partition_schema(PARTITION_NODES, schema_version)
        table = read_parquet_filtered(
            path, filters=filters, columns=columns, target_schema=target
        )
        return self._table_to_dicts(table)

    def scan_edges(
        self,
        tenant: str,
        graph_id: str,
        revision_id: str,
        *,
        filters: FilterSpec = None,
        columns: Optional[Sequence[str]] = None,
        schema_version: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        self._ensure_open()
        self._check_cancelled()
        path = self._partition_path(
            tenant, graph_id, revision_id, f"{PARTITION_EDGES}.parquet"
        )
        target = None
        if schema_version is not None:
            target = get_partition_schema(PARTITION_EDGES, schema_version)
        table = read_parquet_filtered(
            path, filters=filters, columns=columns, target_schema=target
        )
        return self._table_to_dicts(table)

    def scan_adjacency(
        self,
        tenant: str,
        graph_id: str,
        revision_id: str,
        *,
        filters: FilterSpec = None,
        columns: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        self._ensure_open()
        self._check_cancelled()
        path = self._partition_path(
            tenant, graph_id, revision_id, f"{PARTITION_ADJACENCY}.parquet"
        )
        table = read_parquet_filtered(path, filters=filters, columns=columns)
        return self._table_to_dicts(table)

    def scan_properties(
        self,
        tenant: str,
        graph_id: str,
        revision_id: str,
        *,
        filters: FilterSpec = None,
        columns: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        self._ensure_open()
        self._check_cancelled()
        path = self._partition_path(
            tenant, graph_id, revision_id, f"{PARTITION_PROPERTIES}.parquet"
        )
        table = read_parquet_filtered(path, filters=filters, columns=columns)
        return self._table_to_dicts(table)

    def scan_index(
        self,
        tenant: str,
        graph_id: str,
        revision_id: str,
        index_id: str,
        *,
        filters: FilterSpec = None,
        columns: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        self._ensure_open()
        self._check_cancelled()
        _safe_revision_id(index_id)
        path = self._partition_path(
            tenant, graph_id, revision_id, f"{INDEX_DIRNAME}/{index_id}.parquet"
        )
        table = read_parquet_filtered(path, filters=filters, columns=columns)
        return self._table_to_dicts(table)

    def row_group_stats(
        self,
        tenant: str,
        graph_id: str,
        revision_id: str,
        partition: str = PARTITION_NODES,
    ) -> List[Dict[str, Any]]:
        """Return per-row-group statistics for a partition (bounded groups)."""
        self._ensure_open()
        _require_pyarrow()
        if partition == "index" or partition.startswith("indexes/"):
            rel = partition if partition.endswith(".parquet") else f"{partition}.parquet"
        else:
            rel = f"{partition}.parquet"
        path = self._partition_path(tenant, graph_id, revision_id, rel)
        cause = detect_parquet_corruption(path)
        if cause is not None:
            raise GraphStoreError(
                "INTEGRITY",
                f"corrupt partition: {cause}",
                details={"path": str(path)},
                cause_code=cause,
            )
        pf = pq.ParquetFile(path)
        out: List[Dict[str, Any]] = []
        for i in range(pf.metadata.num_row_groups):
            rg = pf.metadata.row_group(i)
            out.append(
                {
                    "row_group": i,
                    "num_rows": rg.num_rows,
                    "total_byte_size": rg.total_byte_size,
                    "num_columns": rg.num_columns,
                }
            )
        return out


def create_parquet_graph_store(
    root_dir: PathLike,
    **kwargs: Any,
) -> ParquetGraphStore:
    """Factory for the ``parquet`` storage profile GraphStore."""
    return ParquetGraphStore.open(root_dir, **kwargs)


__all__ = [
    "STORAGE_PROFILE",
    "DEFAULT_ROW_GROUP_SIZE",
    "MAX_ROW_GROUP_SIZE",
    "PARQUET_MAGIC",
    "TYPED_ERROR_CODES",
    "DATASET_SCHEMA_VERSIONS",
    "GraphStoreError",
    "PartitionWriteResult",
    "PublishResult",
    "RevisionHandle",
    "ParquetGraphStore",
    "create_parquet_graph_store",
    "normalize_node",
    "normalize_edge",
    "build_adjacency_rows",
    "build_type_index_rows",
    "get_partition_schema",
    "evolve_table_to_schema",
    "write_parquet_atomic",
    "detect_parquet_corruption",
    "verify_parquet_file",
    "read_parquet_filtered",
    "collect_table_statistics",
]
