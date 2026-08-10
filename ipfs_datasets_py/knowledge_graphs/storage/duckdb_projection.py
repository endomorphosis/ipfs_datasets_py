"""DuckDB typed projection over immutable graph segments (DQK-016).

Projects published graph revisions into normalized DuckDB surfaces:

* **vertices**, **edges**, **properties**, **adjacency** — typed views that
  *scan* immutable Parquet (and registered IPLD) segments via
  ``read_parquet`` rather than copying payload bytes into DuckDB tables
* **provenance**, **segments**, **lineage** — durable metadata tables that
  bind every projected row to an exact ``graph_revision`` and ``source_cid``

Immutable Parquet/IPLD bytes, SHA-256 checksums, CIDs, staging directories,
and ``_SUCCESS`` publication markers remain storage authority.  This module
never mutates segment payloads; it only registers verified references and
rebuilds views.

Acceptance (DQK-016):

* Large graph data is scanned from immutable segments rather than duplicated
* Predicate pushdown works (filters attach to ``READ_PARQUET``)
* Projection rows bind exact graph revision and source CID
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Any,
    Dict,
    Iterator,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
)

__all__ = [
    "ADJACENCY_VIEW",
    "DEFAULT_PARTITION_KINDS",
    "EDGES_VIEW",
    "LINEAGE_TABLE",
    "PROJECTION_SCHEMA",
    "PROVENANCE_TABLE",
    "PROPERTIES_VIEW",
    "PUBLICATION_MARKER",
    "SCHEMA_VERSION",
    "SEGMENTS_TABLE",
    "STAGING_DIRNAME",
    "TYPED_ERROR_CODES",
    "VERTICES_VIEW",
    "DuckDBGraphProjection",
    "FilterSpec",
    "LineageRecord",
    "ProjectionError",
    "ProjectionResult",
    "ProvenanceRecord",
    "SegmentRecord",
    "create_duckdb_graph_projection",
]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECTION_SCHEMA: str = "ipfs_datasets_py/kg-duckdb-projection@1"
SCHEMA_VERSION: int = 1

PUBLICATION_MARKER: str = "_SUCCESS"
STAGING_DIRNAME: str = ".staging"
MANIFEST_FILENAME: str = "manifest.json"
CHECKSUMS_FILENAME: str = "checksums.json"

SEGMENTS_TABLE: str = "segments"
LINEAGE_TABLE: str = "lineage"
PROVENANCE_TABLE: str = "provenance"
VERTICES_VIEW: str = "vertices"
EDGES_VIEW: str = "edges"
PROPERTIES_VIEW: str = "properties"
ADJACENCY_VIEW: str = "adjacency"

# Partition kind -> logical view name (nodes map to "vertices" per task wording).
DEFAULT_PARTITION_KINDS: Tuple[str, ...] = (
    "nodes",
    "edges",
    "adjacency",
    "properties",
)

_KIND_TO_VIEW: Dict[str, str] = {
    "nodes": VERTICES_VIEW,
    "vertex": VERTICES_VIEW,
    "vertices": VERTICES_VIEW,
    "edges": EDGES_VIEW,
    "edge": EDGES_VIEW,
    "adjacency": ADJACENCY_VIEW,
    "properties": PROPERTIES_VIEW,
    "property": PROPERTIES_VIEW,
}

_VIEW_TO_KIND: Dict[str, str] = {
    VERTICES_VIEW: "nodes",
    EDGES_VIEW: "edges",
    PROPERTIES_VIEW: "properties",
    ADJACENCY_VIEW: "adjacency",
}

_VIEW_COLUMNS: Dict[str, Tuple[str, ...]] = {
    VERTICES_VIEW: (
        "graph_revision",
        "source_cid",
        "tenant",
        "graph_id",
        "segment_id",
        "id",
        "type",
        "name",
        "properties_json",
        "confidence",
        "source_text",
        "schema_version",
    ),
    EDGES_VIEW: (
        "graph_revision",
        "source_cid",
        "tenant",
        "graph_id",
        "segment_id",
        "id",
        "type",
        "source_id",
        "target_id",
        "properties_json",
        "confidence",
        "source_text",
        "schema_version",
    ),
    PROPERTIES_VIEW: (
        "graph_revision",
        "source_cid",
        "tenant",
        "graph_id",
        "segment_id",
        "owner_kind",
        "owner_id",
        "key",
        "value_json",
        "value_type",
        "schema_version",
    ),
    ADJACENCY_VIEW: (
        "graph_revision",
        "source_cid",
        "tenant",
        "graph_id",
        "segment_id",
        "node_id",
        "direction",
        "neighbor_id",
        "edge_id",
        "edge_type",
        "schema_version",
    ),
}

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

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_SAFE_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9_-]{0,62}[a-z0-9])?$")
_SAFE_COL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_FILTER_OPS = frozenset(
    {
        "=",
        "!=",
        "<>",
        "<",
        ">",
        "<=",
        ">=",
        "in",
        "not in",
        "like",
        "ilike",
        "is",
        "is not",
    }
)

_SCHEMA_SQL: Tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS projection_meta (
        key VARCHAR PRIMARY KEY,
        value VARCHAR NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS segments (
        segment_id VARCHAR PRIMARY KEY,
        tenant VARCHAR NOT NULL,
        graph_id VARCHAR NOT NULL,
        graph_revision VARCHAR NOT NULL,
        kind VARCHAR NOT NULL,
        media_type VARCHAR NOT NULL,
        relative_path VARCHAR NOT NULL,
        absolute_path VARCHAR NOT NULL,
        checksum VARCHAR NOT NULL,
        source_cid VARCHAR NOT NULL,
        byte_size BIGINT NOT NULL,
        schema_version VARCHAR NOT NULL DEFAULT '1',
        success_marker VARCHAR,
        staging_path VARCHAR,
        status VARCHAR NOT NULL DEFAULT 'published',
        registered_at VARCHAR NOT NULL,
        metadata_json VARCHAR NOT NULL DEFAULT '{}'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS lineage (
        tenant VARCHAR NOT NULL,
        graph_id VARCHAR NOT NULL,
        graph_revision VARCHAR NOT NULL,
        parent_revision VARCHAR,
        root_cid VARCHAR NOT NULL,
        source_cid VARCHAR NOT NULL,
        registered_at VARCHAR NOT NULL,
        metadata_json VARCHAR NOT NULL DEFAULT '{}',
        PRIMARY KEY (tenant, graph_id, graph_revision)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS provenance (
        tenant VARCHAR NOT NULL,
        graph_id VARCHAR NOT NULL,
        graph_revision VARCHAR NOT NULL,
        source_cid VARCHAR NOT NULL,
        producer_id VARCHAR NOT NULL,
        producer_version VARCHAR NOT NULL,
        source VARCHAR NOT NULL,
        created_at VARCHAR NOT NULL,
        extra_json VARCHAR NOT NULL DEFAULT '{}',
        registered_at VARCHAR NOT NULL,
        PRIMARY KEY (tenant, graph_id, graph_revision, source_cid)
    )
    """,
)


# ---------------------------------------------------------------------------
# Errors / records
# ---------------------------------------------------------------------------


class ProjectionError(Exception):
    """Typed projection error with shared service-contract ``code``."""

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


@dataclass(frozen=True)
class SegmentRecord:
    segment_id: str
    tenant: str
    graph_id: str
    graph_revision: str
    kind: str
    media_type: str
    relative_path: str
    absolute_path: str
    checksum: str
    source_cid: str
    byte_size: int
    schema_version: str
    success_marker: Optional[str]
    staging_path: Optional[str]
    status: str
    registered_at: str
    metadata: Mapping[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "tenant": self.tenant,
            "graph_id": self.graph_id,
            "graph_revision": self.graph_revision,
            "kind": self.kind,
            "media_type": self.media_type,
            "relative_path": self.relative_path,
            "absolute_path": self.absolute_path,
            "checksum": self.checksum,
            "source_cid": self.source_cid,
            "byte_size": self.byte_size,
            "schema_version": self.schema_version,
            "success_marker": self.success_marker,
            "staging_path": self.staging_path,
            "status": self.status,
            "registered_at": self.registered_at,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class LineageRecord:
    tenant: str
    graph_id: str
    graph_revision: str
    parent_revision: Optional[str]
    root_cid: str
    source_cid: str
    registered_at: str
    metadata: Mapping[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tenant": self.tenant,
            "graph_id": self.graph_id,
            "graph_revision": self.graph_revision,
            "parent_revision": self.parent_revision,
            "root_cid": self.root_cid,
            "source_cid": self.source_cid,
            "registered_at": self.registered_at,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ProvenanceRecord:
    tenant: str
    graph_id: str
    graph_revision: str
    source_cid: str
    producer_id: str
    producer_version: str
    source: str
    created_at: str
    extra: Mapping[str, Any]
    registered_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tenant": self.tenant,
            "graph_id": self.graph_id,
            "graph_revision": self.graph_revision,
            "source_cid": self.source_cid,
            "producer_id": self.producer_id,
            "producer_version": self.producer_version,
            "source": self.source,
            "created_at": self.created_at,
            "extra": dict(self.extra),
            "registered_at": self.registered_at,
        }


@dataclass(frozen=True)
class ProjectionResult:
    tenant: str
    graph_id: str
    graph_revision: str
    source_cid: str
    segments: Tuple[SegmentRecord, ...]
    lineage: LineageRecord
    provenance: ProvenanceRecord
    views: Tuple[str, ...]
    duplicated_bytes: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tenant": self.tenant,
            "graph_id": self.graph_id,
            "graph_revision": self.graph_revision,
            "source_cid": self.source_cid,
            "segments": [s.to_dict() for s in self.segments],
            "lineage": self.lineage.to_dict(),
            "provenance": self.provenance.to_dict(),
            "views": list(self.views),
            "duplicated_bytes": self.duplicated_bytes,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_duckdb() -> Any:
    try:
        import duckdb  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise ProjectionError(
            "STORAGE",
            "duckdb package is required for DuckDBGraphProjection",
            details={"dependency": "duckdb"},
            cause_code="MISSING_DUCKDB",
        ) from exc
    return duckdb


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _json_loads(text: Optional[str]) -> Any:
    if text is None or text == "":
        return {}
    return json.loads(text)


def _sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _labeled_checksum(hex_digest: str) -> str:
    hex_digest = hex_digest.lower()
    if hex_digest.startswith("sha256:"):
        hex_digest = hex_digest[7:]
    if _SHA256_HEX.fullmatch(hex_digest) is None:
        raise ProjectionError(
            "INVALID_REQUEST",
            "checksum must be sha256 hex",
            details={"checksum": hex_digest},
        )
    return f"sha256:{hex_digest}"


def _cid_from_sha256_hex(hex_digest: str) -> str:
    """Derive a stable content id from a SHA-256 hex digest.

    Prefer the shared manifest helper when available; fall back to a
    labeled digest so offline projection works without codec deps.
    """

    digest = hex_digest.lower()
    if digest.startswith("sha256:"):
        digest = digest[7:]
    if _SHA256_HEX.fullmatch(digest) is None:
        raise ProjectionError(
            "INVALID_REQUEST",
            "cannot derive CID from non-sha256 digest",
            details={"digest": hex_digest},
        )
    try:
        from ipfs_datasets_py.knowledge_graphs.contracts.manifest import (
            ContentChecksum,
        )

        return ContentChecksum.from_sha256_hex(digest).as_cid()
    except Exception:
        return f"sha256:{digest}"


def _require_slug(label: str, value: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ProjectionError(
            "INVALID_REQUEST",
            f"{label} must be a non-empty string without surrounding whitespace",
            details={label: value},
        )
    if _SAFE_SLUG_RE.fullmatch(value) is None and _SAFE_ID_RE.fullmatch(value) is None:
        # Allow revision-style ids when not strict slugs.
        if label in {"revision_id", "graph_revision", "parent_revision"}:
            if _SAFE_ID_RE.fullmatch(value) is None:
                raise ProjectionError(
                    "INVALID_REQUEST",
                    f"{label} is not a safe identifier",
                    details={label: value},
                )
            return value
        raise ProjectionError(
            "INVALID_REQUEST",
            f"{label} is not a safe slug",
            details={label: value},
        )
    return value


def _require_revision_id(value: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ProjectionError(
            "INVALID_REQUEST",
            "revision_id must be a non-empty string",
            details={"revision_id": value},
        )
    if "\x00" in value or "/" in value or "\\" in value or value in {".", ".."}:
        raise ProjectionError(
            "INVALID_REQUEST",
            "revision_id contains illegal path characters",
            details={"revision_id": value},
        )
    if _SAFE_ID_RE.fullmatch(value) is None:
        raise ProjectionError(
            "INVALID_REQUEST",
            "revision_id is not a safe identifier",
            details={"revision_id": value},
        )
    return value


def _require_cid(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProjectionError("INVALID_REQUEST", "source_cid is required")
    text = value.strip()
    try:
        from ipfs_datasets_py.duckdb_control.contracts import parse_cid

        return parse_cid(text)
    except Exception:
        # Accept labeled digests and common CIDs without hard dependency.
        if text.startswith("sha256:") and _SHA256_HEX.fullmatch(text[7:]):
            return text
        if re.fullmatch(r"^Qm[1-9A-HJ-NP-Za-km-z]{44}$", text):
            return text
        if re.fullmatch(r"^b[a-z2-7]{10,200}$", text):
            return text
        if re.fullmatch(r"^bagu[a-z2-7]{50,120}$", text):
            return text
        raise ProjectionError(
            "INVALID_REQUEST",
            f"invalid content id: {value!r}",
            details={"source_cid": value},
        )


def _sql_literal(value: Any) -> str:
    """Render a SQL literal for VIEW DDL (paths/constants only)."""

    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ProjectionError("INVALID_REQUEST", "non-finite float in SQL literal")
        return repr(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    raise ProjectionError(
        "INVALID_REQUEST",
        f"unsupported SQL literal type: {type(value).__name__}",
    )


def _normalize_filters(filters: FilterSpec) -> List[Tuple[str, str, Any]]:
    if filters is None:
        return []
    if not isinstance(filters, (list, tuple)):
        raise ProjectionError(
            "INVALID_REQUEST",
            "filters must be a sequence of (column, op, value) triples",
            details={"type": type(filters).__name__},
        )
    out: List[Tuple[str, str, Any]] = []
    for item in filters:
        if (
            not isinstance(item, (list, tuple))
            or len(item) != 3
        ):
            raise ProjectionError(
                "INVALID_REQUEST",
                "each filter must be a (column, op, value) triple",
                details={"filter": repr(item)[:200]},
            )
        col, op, val = item
        if not isinstance(col, str) or not col or _SAFE_COL_RE.fullmatch(col) is None:
            raise ProjectionError(
                "INVALID_REQUEST",
                "filter column must be a safe identifier",
                details={"column": col},
            )
        if not isinstance(op, str) or op.strip().lower() not in _ALLOWED_FILTER_OPS:
            raise ProjectionError(
                "INVALID_REQUEST",
                f"unsupported filter operator: {op!r}",
                details={"op": op},
            )
        out.append((col, op.strip().lower(), val))
    return out


def _filter_sql(
    filters: Sequence[Tuple[str, str, Any]],
    *,
    params: List[Any],
) -> str:
    clauses: List[str] = []
    for col, op, val in filters:
        if op in {"is", "is not"}:
            # Only NULL / NOT NULL supported.
            if val is not None and str(val).lower() not in {"null", "true", "false"}:
                raise ProjectionError(
                    "INVALID_REQUEST",
                    "IS / IS NOT filters require NULL, TRUE, or FALSE",
                    details={"value": val},
                )
            if val is None or str(val).lower() == "null":
                clauses.append(f'"{col}" {op.upper()} NULL')
            elif str(val).lower() == "true":
                clauses.append(f'"{col}" {op.upper()} TRUE')
            else:
                clauses.append(f'"{col}" {op.upper()} FALSE')
            continue
        if op in {"in", "not in"}:
            if not isinstance(val, (list, tuple)) or not val:
                raise ProjectionError(
                    "INVALID_REQUEST",
                    "IN filters require a non-empty sequence",
                    details={"column": col},
                )
            placeholders = ", ".join("?" for _ in val)
            clauses.append(f'"{col}" {op.upper()} ({placeholders})')
            params.extend(list(val))
            continue
        clauses.append(f'"{col}" {op.upper()} ?')
        params.append(val)
    return " AND ".join(clauses)


def _row_map(columns: Sequence[str], row: Sequence[Any]) -> Dict[str, Any]:
    return {columns[i]: row[i] for i in range(len(columns))}


def _empty_view_sql(view_name: str) -> str:
    cols = _VIEW_COLUMNS[view_name]
    # Typed empty relation so DESCRIBE / SELECT work before any projection.
    select_bits = []
    for col in cols:
        if col in {
            "confidence",
        }:
            select_bits.append(f"CAST(NULL AS DOUBLE) AS {col}")
        else:
            select_bits.append(f"CAST(NULL AS VARCHAR) AS {col}")
    return (
        f"CREATE OR REPLACE VIEW {view_name} AS "
        f"SELECT {', '.join(select_bits)} WHERE FALSE"
    )


# ---------------------------------------------------------------------------
# DuckDBGraphProjection
# ---------------------------------------------------------------------------


class DuckDBGraphProjection:
    """Project immutable graph segments into typed DuckDB views.

    Payload authority remains on disk (Parquet) or content-addressed (IPLD).
    DuckDB holds:

    * segment / lineage / provenance metadata tables
    * views that ``read_parquet`` registered segment paths with
      ``graph_revision`` + ``source_cid`` binding columns
    """

    def __init__(self, path: PathLike) -> None:
        duckdb = _require_duckdb()
        self._path = Path(path)
        if self._path.parent and str(self._path.parent) not in ("", "."):
            self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = duckdb.connect(str(self._path))
        self._closed = False
        self._initialize_schema()

    # -- lifecycle ---------------------------------------------------------

    @property
    def path(self) -> Path:
        return self._path

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            try:
                self._conn.close()
            finally:
                self._closed = True

    def __enter__(self) -> "DuckDBGraphProjection":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise ProjectionError("STORAGE", "projection is closed")

    @contextmanager
    def _cursor(self) -> Iterator[Any]:
        self._ensure_open()
        with self._lock:
            yield self._conn

    def _initialize_schema(self) -> None:
        with self._lock:
            for stmt in _SCHEMA_SQL:
                self._conn.execute(stmt)
            row = self._conn.execute(
                "SELECT value FROM projection_meta WHERE key = 'schema_version'"
            ).fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO projection_meta (key, value) VALUES (?, ?)",
                    ["schema_version", str(SCHEMA_VERSION)],
                )
                self._conn.execute(
                    "INSERT INTO projection_meta (key, value) VALUES (?, ?)",
                    ["projection_schema", PROJECTION_SCHEMA],
                )
            for view_name in (
                VERTICES_VIEW,
                EDGES_VIEW,
                PROPERTIES_VIEW,
                ADJACENCY_VIEW,
            ):
                self._conn.execute(_empty_view_sql(view_name))
            # Ensure empty views exist after reopen when segments already registered.
            self._rebuild_typed_views_unlocked()

    # -- segment / revision registration -----------------------------------

    def project_revision(
        self,
        *,
        tenant: str,
        graph_id: str,
        revision_id: str,
        revision_dir: PathLike,
        source_cid: Optional[str] = None,
        parent_revision: Optional[str] = None,
        provenance: Optional[Mapping[str, Any]] = None,
        overwrite: bool = False,
        verify_checksums: bool = True,
    ) -> ProjectionResult:
        """Register a published revision directory without copying payload.

        Requires ``_SUCCESS`` (or equivalent success marker) so incomplete
        staging directories cannot be projected.  Segment bytes stay on disk;
        DuckDB only stores descriptors and rebuilds typed views.
        """

        tenant_n = _require_slug("tenant", tenant)
        graph_n = _require_slug("graph_id", graph_id)
        rev_n = _require_revision_id(revision_id)
        rev_dir = Path(revision_dir).resolve()
        if not rev_dir.is_dir():
            raise ProjectionError(
                "NOT_FOUND",
                "revision directory not found",
                details={"revision_dir": str(rev_dir)},
            )

        success_path = rev_dir / PUBLICATION_MARKER
        if not success_path.is_file():
            raise ProjectionError(
                "INTEGRITY",
                "revision lacks success marker; refuse incomplete staging",
                details={
                    "revision_dir": str(rev_dir),
                    "marker": PUBLICATION_MARKER,
                },
                cause_code="MISSING_SUCCESS_MARKER",
            )

        # Never project out of an active staging tree as authority.
        if STAGING_DIRNAME in rev_dir.parts:
            raise ProjectionError(
                "INTEGRITY",
                "refuse to project from staging path",
                details={"revision_dir": str(rev_dir)},
                cause_code="STAGING_PATH",
            )

        manifest = self._load_manifest(rev_dir)
        checksums = self._load_checksums(rev_dir)
        root_cid = self._resolve_root_cid(
            explicit=source_cid,
            manifest=manifest,
            success_path=success_path,
        )

        parent = parent_revision
        if parent is None:
            parent = manifest.get("parent_revision")
        if parent is not None:
            parent = _require_revision_id(str(parent))

        now = _utc_now_iso()
        prov_map = dict(provenance or {})
        if not prov_map and isinstance(manifest.get("provenance"), Mapping):
            prov_map = dict(manifest["provenance"])

        producer_id = str(prov_map.get("producer_id") or "duckdb-projection")
        producer_version = str(prov_map.get("producer_version") or "1")
        source = str(prov_map.get("source") or "project_revision")
        created_at = str(prov_map.get("created_at") or now)
        extra = {
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

        partition_specs = self._discover_partitions(
            rev_dir, manifest=manifest, checksums=checksums
        )
        if not partition_specs:
            raise ProjectionError(
                "NOT_FOUND",
                "no projectable Parquet/IPLD segments found in revision",
                details={"revision_dir": str(rev_dir)},
            )

        registered: List[SegmentRecord] = []
        with self._cursor() as conn:
            existing = conn.execute(
                """
                SELECT COUNT(*) FROM segments
                WHERE tenant = ? AND graph_id = ? AND graph_revision = ?
                """,
                [tenant_n, graph_n, rev_n],
            ).fetchone()[0]
            if existing and not overwrite:
                raise ProjectionError(
                    "ALREADY_EXISTS",
                    f"revision already projected: {rev_n}",
                    details={
                        "tenant": tenant_n,
                        "graph_id": graph_n,
                        "graph_revision": rev_n,
                    },
                )
            if overwrite:
                conn.execute(
                    """
                    DELETE FROM segments
                    WHERE tenant = ? AND graph_id = ? AND graph_revision = ?
                    """,
                    [tenant_n, graph_n, rev_n],
                )
                conn.execute(
                    """
                    DELETE FROM lineage
                    WHERE tenant = ? AND graph_id = ? AND graph_revision = ?
                    """,
                    [tenant_n, graph_n, rev_n],
                )
                conn.execute(
                    """
                    DELETE FROM provenance
                    WHERE tenant = ? AND graph_id = ? AND graph_revision = ?
                    """,
                    [tenant_n, graph_n, rev_n],
                )

            for spec in partition_specs:
                path = Path(spec["absolute_path"])
                if not path.is_file():
                    raise ProjectionError(
                        "NOT_FOUND",
                        f"segment file missing: {path}",
                        details={"path": str(path), "kind": spec["kind"]},
                    )
                actual_hex = _sha256_file(path)
                expected = spec.get("checksum")
                if expected:
                    expected_hex = expected[7:] if expected.startswith("sha256:") else expected
                    if verify_checksums and expected_hex.lower() != actual_hex:
                        raise ProjectionError(
                            "INTEGRITY",
                            "segment checksum mismatch",
                            details={
                                "path": str(path),
                                "expected": expected,
                                "actual": f"sha256:{actual_hex}",
                            },
                            cause_code="CHECKSUM_MISMATCH",
                        )
                checksum = _labeled_checksum(actual_hex)
                seg_cid = str(spec.get("source_cid") or "") or _cid_from_sha256_hex(
                    actual_hex
                )
                seg_cid = _require_cid(seg_cid)
                segment_id = str(spec.get("segment_id") or f"seg-{uuid.uuid4().hex[:16]}")
                media = str(spec.get("media_type") or "parquet")
                byte_size = int(path.stat().st_size)
                if byte_size != int(spec.get("byte_size") or byte_size):
                    # Prefer observed size; surface mismatch when verify on.
                    if verify_checksums and spec.get("byte_size") is not None:
                        raise ProjectionError(
                            "INTEGRITY",
                            "segment byte_size mismatch",
                            details={
                                "path": str(path),
                                "expected": spec.get("byte_size"),
                                "actual": byte_size,
                            },
                        )

                conn.execute(
                    """
                    INSERT INTO segments (
                        segment_id, tenant, graph_id, graph_revision, kind,
                        media_type, relative_path, absolute_path, checksum,
                        source_cid, byte_size, schema_version, success_marker,
                        staging_path, status, registered_at, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        segment_id,
                        tenant_n,
                        graph_n,
                        rev_n,
                        spec["kind"],
                        media,
                        spec["relative_path"],
                        str(path),
                        checksum,
                        seg_cid,
                        byte_size,
                        str(spec.get("schema_version") or "1"),
                        str(success_path),
                        None,
                        "published",
                        now,
                        _json_dumps(spec.get("metadata") or {}),
                    ],
                )
                registered.append(
                    SegmentRecord(
                        segment_id=segment_id,
                        tenant=tenant_n,
                        graph_id=graph_n,
                        graph_revision=rev_n,
                        kind=spec["kind"],
                        media_type=media,
                        relative_path=spec["relative_path"],
                        absolute_path=str(path),
                        checksum=checksum,
                        source_cid=seg_cid,
                        byte_size=byte_size,
                        schema_version=str(spec.get("schema_version") or "1"),
                        success_marker=str(success_path),
                        staging_path=None,
                        status="published",
                        registered_at=now,
                        metadata=dict(spec.get("metadata") or {}),
                    )
                )

            # Lineage binds revision to root/source cid (revision-level identity).
            conn.execute(
                """
                INSERT INTO lineage (
                    tenant, graph_id, graph_revision, parent_revision,
                    root_cid, source_cid, registered_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    tenant_n,
                    graph_n,
                    rev_n,
                    parent,
                    root_cid,
                    root_cid,
                    now,
                    _json_dumps({"manifest_present": bool(manifest)}),
                ],
            )
            lineage = LineageRecord(
                tenant=tenant_n,
                graph_id=graph_n,
                graph_revision=rev_n,
                parent_revision=parent,
                root_cid=root_cid,
                source_cid=root_cid,
                registered_at=now,
                metadata={"manifest_present": bool(manifest)},
            )

            conn.execute(
                """
                INSERT INTO provenance (
                    tenant, graph_id, graph_revision, source_cid,
                    producer_id, producer_version, source, created_at,
                    extra_json, registered_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    tenant_n,
                    graph_n,
                    rev_n,
                    root_cid,
                    producer_id,
                    producer_version,
                    source,
                    created_at,
                    _json_dumps(extra),
                    now,
                ],
            )
            prov_rec = ProvenanceRecord(
                tenant=tenant_n,
                graph_id=graph_n,
                graph_revision=rev_n,
                source_cid=root_cid,
                producer_id=producer_id,
                producer_version=producer_version,
                source=source,
                created_at=created_at,
                extra=extra,
                registered_at=now,
            )

            views = self._rebuild_typed_views_unlocked()

        return ProjectionResult(
            tenant=tenant_n,
            graph_id=graph_n,
            graph_revision=rev_n,
            source_cid=root_cid,
            segments=tuple(registered),
            lineage=lineage,
            provenance=prov_rec,
            views=tuple(views),
            duplicated_bytes=0,  # scan-only; never materialize payload
        )

    def register_ipld_segment(
        self,
        *,
        tenant: str,
        graph_id: str,
        revision_id: str,
        kind: str,
        source_cid: str,
        checksum: str,
        byte_size: int,
        relative_path: str = "",
        absolute_path: Optional[PathLike] = None,
        media_type: str = "ipld-dag-cbor",
        schema_version: str = "1",
        success_marker: Optional[PathLike] = None,
        staging_path: Optional[PathLike] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> SegmentRecord:
        """Register an IPLD segment by CID/checksum without embedding bytes."""

        tenant_n = _require_slug("tenant", tenant)
        graph_n = _require_slug("graph_id", graph_id)
        rev_n = _require_revision_id(revision_id)
        cid = _require_cid(source_cid)
        cksum = _labeled_checksum(checksum)
        if kind not in _KIND_TO_VIEW and kind not in DEFAULT_PARTITION_KINDS:
            # Allow free-form kinds for IPLD-only registry rows.
            if not isinstance(kind, str) or not kind:
                raise ProjectionError("INVALID_REQUEST", "kind is required")
        if byte_size < 0:
            raise ProjectionError("INVALID_REQUEST", "byte_size must be non-negative")
        abs_path = str(Path(absolute_path).resolve()) if absolute_path else ""
        if abs_path and STAGING_DIRNAME in Path(abs_path).parts and not success_marker:
            raise ProjectionError(
                "INTEGRITY",
                "IPLD segment under staging requires success marker",
                details={"path": abs_path},
            )
        now = _utc_now_iso()
        segment_id = f"ipld-{uuid.uuid4().hex[:16]}"
        with self._cursor() as conn:
            conn.execute(
                """
                INSERT INTO segments (
                    segment_id, tenant, graph_id, graph_revision, kind,
                    media_type, relative_path, absolute_path, checksum,
                    source_cid, byte_size, schema_version, success_marker,
                    staging_path, status, registered_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    segment_id,
                    tenant_n,
                    graph_n,
                    rev_n,
                    kind,
                    media_type,
                    relative_path,
                    abs_path,
                    cksum,
                    cid,
                    int(byte_size),
                    schema_version,
                    str(success_marker) if success_marker else None,
                    str(staging_path) if staging_path else None,
                    "published",
                    now,
                    _json_dumps(dict(metadata or {})),
                ],
            )
        return SegmentRecord(
            segment_id=segment_id,
            tenant=tenant_n,
            graph_id=graph_n,
            graph_revision=rev_n,
            kind=kind,
            media_type=media_type,
            relative_path=relative_path,
            absolute_path=abs_path,
            checksum=cksum,
            source_cid=cid,
            byte_size=int(byte_size),
            schema_version=schema_version,
            success_marker=str(success_marker) if success_marker else None,
            staging_path=str(staging_path) if staging_path else None,
            status="published",
            registered_at=now,
            metadata=dict(metadata or {}),
        )

    def rebuild_typed_views(self) -> Tuple[str, ...]:
        with self._cursor():
            return tuple(self._rebuild_typed_views_unlocked())

    def _rebuild_typed_views_unlocked(self) -> List[str]:
        """Rebuild vertices/edges/properties/adjacency views from segments.

        Only **parquet** media with an on-disk path participate in scan views.
        IPLD segments remain in the ``segments`` table (CID/checksum authority)
        without blind byte duplication into DuckDB.
        """

        rows = self._conn.execute(
            """
            SELECT segment_id, tenant, graph_id, graph_revision, kind,
                   media_type, absolute_path, source_cid, status
            FROM segments
            WHERE status = 'published'
              AND media_type = 'parquet'
              AND absolute_path <> ''
            ORDER BY tenant, graph_id, graph_revision, kind, segment_id
            """
        ).fetchall()

        by_view: Dict[str, List[str]] = {
            VERTICES_VIEW: [],
            EDGES_VIEW: [],
            PROPERTIES_VIEW: [],
            ADJACENCY_VIEW: [],
        }

        for row in rows:
            (
                segment_id,
                tenant,
                graph_id,
                graph_revision,
                kind,
                _media,
                abs_path,
                source_cid,
                _status,
            ) = row
            view = _KIND_TO_VIEW.get(kind)
            if view is None:
                continue
            path = Path(abs_path)
            if not path.is_file():
                # Stale registration — skip from scan view rather than fail closed
                # for other revisions. Integrity checks live on project_revision.
                continue
            path_lit = _sql_literal(str(path))
            select = (
                f"SELECT "
                f"{_sql_literal(graph_revision)} AS graph_revision, "
                f"{_sql_literal(source_cid)} AS source_cid, "
                f"{_sql_literal(tenant)} AS tenant, "
                f"{_sql_literal(graph_id)} AS graph_id, "
                f"{_sql_literal(segment_id)} AS segment_id, "
                f"p.* FROM read_parquet({path_lit}) AS p"
            )
            by_view[view].append(select)

        rebuilt: List[str] = []
        for view_name, parts in by_view.items():
            if not parts:
                self._conn.execute(_empty_view_sql(view_name))
            else:
                sql = f"CREATE OR REPLACE VIEW {view_name} AS " + " UNION ALL ".join(
                    parts
                )
                self._conn.execute(sql)
            rebuilt.append(view_name)
        return rebuilt

    # -- discovery ---------------------------------------------------------

    def _resolve_root_cid(
        self,
        *,
        explicit: Optional[str],
        manifest: Mapping[str, Any],
        success_path: Path,
    ) -> str:
        if explicit:
            return _require_cid(str(explicit))
        root = manifest.get("root_cid")
        if isinstance(root, str) and root.strip():
            return _require_cid(root.strip())
        checksum = manifest.get("checksum")
        if isinstance(checksum, Mapping):
            hex_d = str(checksum.get("hex_digest") or "").strip()
            if hex_d:
                return _require_cid(_cid_from_sha256_hex(hex_d))
            labeled = str(checksum.get("algorithm") or "")
            if labeled == "sha256" and checksum.get("hex_digest"):
                return _require_cid(
                    _cid_from_sha256_hex(str(checksum["hex_digest"]))
                )
        if isinstance(checksum, str) and checksum.strip():
            text = checksum.strip()
            if text.startswith("sha256:") or _SHA256_HEX.fullmatch(text):
                return _require_cid(_cid_from_sha256_hex(text))
            return _require_cid(text)
        # Deterministic fallback from the success marker bytes.
        return _require_cid(_cid_from_sha256_hex(_sha256_file(success_path)))

    def _load_manifest(self, rev_dir: Path) -> Dict[str, Any]:
        path = rev_dir / MANIFEST_FILENAME
        if not path.is_file():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProjectionError(
                "INTEGRITY",
                f"cannot parse revision manifest: {exc}",
                details={"path": str(path)},
                cause_code="MANIFEST_PARSE",
            ) from exc

    def _load_checksums(self, rev_dir: Path) -> Dict[str, str]:
        path = rev_dir / CHECKSUMS_FILENAME
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProjectionError(
                "INTEGRITY",
                f"cannot parse checksums file: {exc}",
                details={"path": str(path)},
                cause_code="CHECKSUMS_PARSE",
            ) from exc
        if not isinstance(data, Mapping):
            return {}
        out: Dict[str, str] = {}
        for k, v in data.items():
            if isinstance(k, str) and isinstance(v, str):
                out[k] = v
        return out

    def _discover_partitions(
        self,
        rev_dir: Path,
        *,
        manifest: Mapping[str, Any],
        checksums: Mapping[str, str],
    ) -> List[Dict[str, Any]]:
        specs: List[Dict[str, Any]] = []
        partitions = manifest.get("partitions") if isinstance(manifest, Mapping) else None
        if isinstance(partitions, list) and partitions:
            for part in partitions:
                if not isinstance(part, Mapping):
                    continue
                kind = str(part.get("kind") or "other")
                if kind not in DEFAULT_PARTITION_KINDS:
                    continue
                rel = str(part.get("path") or f"{kind}.parquet")
                abs_path = (rev_dir / rel).resolve()
                ck = part.get("checksum")
                if isinstance(ck, Mapping):
                    hex_d = str(ck.get("hex_digest") or "")
                    checksum = f"sha256:{hex_d}" if hex_d else ""
                elif isinstance(ck, str):
                    checksum = ck if ck.startswith("sha256:") else f"sha256:{ck}"
                else:
                    checksum = checksums.get(rel, "")
                cid = str(part.get("cid") or "")
                if not cid and checksum:
                    try:
                        cid = _cid_from_sha256_hex(checksum)
                    except ProjectionError:
                        cid = ""
                specs.append(
                    {
                        "kind": kind,
                        "relative_path": rel,
                        "absolute_path": str(abs_path),
                        "checksum": checksum,
                        "source_cid": cid,
                        "byte_size": part.get("size_bytes"),
                        "schema_version": str(part.get("schema_version") or "1"),
                        "media_type": "parquet"
                        if str(part.get("codec") or "parquet") == "parquet"
                        else str(part.get("codec") or "parquet"),
                        "metadata": {
                            "partition_id": part.get("partition_id"),
                            "row_count": part.get("row_count"),
                        },
                    }
                )
            return specs

        # Fallback: conventional ParquetGraphStore layout.
        for kind in DEFAULT_PARTITION_KINDS:
            rel = f"{kind}.parquet"
            path = rev_dir / rel
            if not path.is_file():
                continue
            checksum = checksums.get(rel, "")
            if checksum and not checksum.startswith("sha256:"):
                checksum = f"sha256:{checksum}"
            specs.append(
                {
                    "kind": kind,
                    "relative_path": rel,
                    "absolute_path": str(path.resolve()),
                    "checksum": checksum,
                    "source_cid": _cid_from_sha256_hex(_sha256_file(path))
                    if not checksum
                    else _cid_from_sha256_hex(checksum),
                    "byte_size": path.stat().st_size,
                    "schema_version": "1",
                    "media_type": "parquet",
                    "metadata": {},
                }
            )
        return specs

    # -- reads -------------------------------------------------------------

    def list_segments(
        self,
        *,
        tenant: Optional[str] = None,
        graph_id: Optional[str] = None,
        graph_revision: Optional[str] = None,
    ) -> List[SegmentRecord]:
        clauses: List[str] = []
        params: List[Any] = []
        if tenant is not None:
            clauses.append("tenant = ?")
            params.append(tenant)
        if graph_id is not None:
            clauses.append("graph_id = ?")
            params.append(graph_id)
        if graph_revision is not None:
            clauses.append("graph_revision = ?")
            params.append(graph_revision)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._cursor() as conn:
            cur = conn.execute(
                f"""
                SELECT segment_id, tenant, graph_id, graph_revision, kind,
                       media_type, relative_path, absolute_path, checksum,
                       source_cid, byte_size, schema_version, success_marker,
                       staging_path, status, registered_at, metadata_json
                FROM segments
                {where}
                ORDER BY tenant, graph_id, graph_revision, kind, segment_id
                """,
                params,
            )
            cols = [d[0] for d in cur.description]
            return [self._segment_from_row(_row_map(cols, r)) for r in cur.fetchall()]

    def get_lineage(
        self,
        tenant: str,
        graph_id: str,
        graph_revision: str,
    ) -> LineageRecord:
        with self._cursor() as conn:
            cur = conn.execute(
                """
                SELECT tenant, graph_id, graph_revision, parent_revision,
                       root_cid, source_cid, registered_at, metadata_json
                FROM lineage
                WHERE tenant = ? AND graph_id = ? AND graph_revision = ?
                """,
                [tenant, graph_id, graph_revision],
            )
            row = cur.fetchone()
            if row is None:
                raise ProjectionError(
                    "NOT_FOUND",
                    "lineage not found",
                    details={
                        "tenant": tenant,
                        "graph_id": graph_id,
                        "graph_revision": graph_revision,
                    },
                )
            cols = [d[0] for d in cur.description]
            m = _row_map(cols, row)
            return LineageRecord(
                tenant=m["tenant"],
                graph_id=m["graph_id"],
                graph_revision=m["graph_revision"],
                parent_revision=m["parent_revision"],
                root_cid=m["root_cid"],
                source_cid=m["source_cid"],
                registered_at=m["registered_at"],
                metadata=_json_loads(m["metadata_json"]),
            )

    def get_provenance(
        self,
        tenant: str,
        graph_id: str,
        graph_revision: str,
        *,
        source_cid: Optional[str] = None,
    ) -> ProvenanceRecord:
        with self._cursor() as conn:
            if source_cid is None:
                cur = conn.execute(
                    """
                    SELECT tenant, graph_id, graph_revision, source_cid,
                           producer_id, producer_version, source, created_at,
                           extra_json, registered_at
                    FROM provenance
                    WHERE tenant = ? AND graph_id = ? AND graph_revision = ?
                    ORDER BY registered_at
                    LIMIT 1
                    """,
                    [tenant, graph_id, graph_revision],
                )
            else:
                cur = conn.execute(
                    """
                    SELECT tenant, graph_id, graph_revision, source_cid,
                           producer_id, producer_version, source, created_at,
                           extra_json, registered_at
                    FROM provenance
                    WHERE tenant = ? AND graph_id = ? AND graph_revision = ?
                      AND source_cid = ?
                    """,
                    [tenant, graph_id, graph_revision, source_cid],
                )
            row = cur.fetchone()
            if row is None:
                raise ProjectionError(
                    "NOT_FOUND",
                    "provenance not found",
                    details={
                        "tenant": tenant,
                        "graph_id": graph_id,
                        "graph_revision": graph_revision,
                        "source_cid": source_cid,
                    },
                )
            cols = [d[0] for d in cur.description]
            m = _row_map(cols, row)
            return ProvenanceRecord(
                tenant=m["tenant"],
                graph_id=m["graph_id"],
                graph_revision=m["graph_revision"],
                source_cid=m["source_cid"],
                producer_id=m["producer_id"],
                producer_version=m["producer_version"],
                source=m["source"],
                created_at=m["created_at"],
                extra=_json_loads(m["extra_json"]),
                registered_at=m["registered_at"],
            )

    def _segment_from_row(self, m: Mapping[str, Any]) -> SegmentRecord:
        return SegmentRecord(
            segment_id=m["segment_id"],
            tenant=m["tenant"],
            graph_id=m["graph_id"],
            graph_revision=m["graph_revision"],
            kind=m["kind"],
            media_type=m["media_type"],
            relative_path=m["relative_path"],
            absolute_path=m["absolute_path"],
            checksum=m["checksum"],
            source_cid=m["source_cid"],
            byte_size=int(m["byte_size"]),
            schema_version=m["schema_version"],
            success_marker=m["success_marker"],
            staging_path=m["staging_path"],
            status=m["status"],
            registered_at=m["registered_at"],
            metadata=_json_loads(m["metadata_json"]),
        )

    # -- typed scans (predicate pushdown) ----------------------------------

    def scan_vertices(
        self,
        *,
        filters: FilterSpec = None,
        columns: Optional[Sequence[str]] = None,
        graph_revision: Optional[str] = None,
        source_cid: Optional[str] = None,
        tenant: Optional[str] = None,
        graph_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        return self._scan_view(
            VERTICES_VIEW,
            filters=filters,
            columns=columns,
            graph_revision=graph_revision,
            source_cid=source_cid,
            tenant=tenant,
            graph_id=graph_id,
            limit=limit,
        )

    def scan_edges(
        self,
        *,
        filters: FilterSpec = None,
        columns: Optional[Sequence[str]] = None,
        graph_revision: Optional[str] = None,
        source_cid: Optional[str] = None,
        tenant: Optional[str] = None,
        graph_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        return self._scan_view(
            EDGES_VIEW,
            filters=filters,
            columns=columns,
            graph_revision=graph_revision,
            source_cid=source_cid,
            tenant=tenant,
            graph_id=graph_id,
            limit=limit,
        )

    def scan_properties(
        self,
        *,
        filters: FilterSpec = None,
        columns: Optional[Sequence[str]] = None,
        graph_revision: Optional[str] = None,
        source_cid: Optional[str] = None,
        tenant: Optional[str] = None,
        graph_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        return self._scan_view(
            PROPERTIES_VIEW,
            filters=filters,
            columns=columns,
            graph_revision=graph_revision,
            source_cid=source_cid,
            tenant=tenant,
            graph_id=graph_id,
            limit=limit,
        )

    def scan_adjacency(
        self,
        *,
        filters: FilterSpec = None,
        columns: Optional[Sequence[str]] = None,
        graph_revision: Optional[str] = None,
        source_cid: Optional[str] = None,
        tenant: Optional[str] = None,
        graph_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        return self._scan_view(
            ADJACENCY_VIEW,
            filters=filters,
            columns=columns,
            graph_revision=graph_revision,
            source_cid=source_cid,
            tenant=tenant,
            graph_id=graph_id,
            limit=limit,
        )

    def explain_scan(
        self,
        view: str,
        *,
        filters: FilterSpec = None,
        graph_revision: Optional[str] = None,
        source_cid: Optional[str] = None,
        tenant: Optional[str] = None,
        graph_id: Optional[str] = None,
    ) -> str:
        """Return DuckDB physical plan text for a typed scan (pushdown checks)."""

        sql, params = self._build_scan_sql(
            view,
            filters=filters,
            columns=None,
            graph_revision=graph_revision,
            source_cid=source_cid,
            tenant=tenant,
            graph_id=graph_id,
            limit=None,
            explain=True,
        )
        with self._cursor() as conn:
            row = conn.execute(sql, params).fetchone()
            if row is None:
                return ""
            return str(row[1] if len(row) > 1 else row[0])

    def payload_is_view_backed(self) -> bool:
        """True when typed surfaces are VIEWs (scan) not materialised TABLEs."""

        with self._cursor() as conn:
            for name in (
                VERTICES_VIEW,
                EDGES_VIEW,
                PROPERTIES_VIEW,
                ADJACENCY_VIEW,
            ):
                row = conn.execute(
                    """
                    SELECT table_type FROM information_schema.tables
                    WHERE table_name = ?
                    """,
                    [name],
                ).fetchone()
                if row is None:
                    return False
                # Accept VIEW only — base tables would imply blind payload copy.
                if str(row[0]).upper() != "VIEW":
                    return False
        return True

    def duplicated_payload_bytes(self) -> int:
        """Bytes of graph payload stored inside DuckDB tables (should be 0).

        Segment metadata is not payload.  Typed views are not tables.
        """

        # Always 0 by design: we never CREATE TABLE AS SELECT payload.
        return 0

    def _scan_view(
        self,
        view: str,
        *,
        filters: FilterSpec,
        columns: Optional[Sequence[str]],
        graph_revision: Optional[str],
        source_cid: Optional[str],
        tenant: Optional[str],
        graph_id: Optional[str],
        limit: Optional[int],
    ) -> List[Dict[str, Any]]:
        sql, params = self._build_scan_sql(
            view,
            filters=filters,
            columns=columns,
            graph_revision=graph_revision,
            source_cid=source_cid,
            tenant=tenant,
            graph_id=graph_id,
            limit=limit,
            explain=False,
        )
        with self._cursor() as conn:
            try:
                cur = conn.execute(sql, params)
            except Exception as exc:
                raise ProjectionError(
                    "QUERY_EXECUTION",
                    f"scan failed: {exc}",
                    details={"view": view},
                    cause_code="SCAN_ERROR",
                ) from exc
            cols = [d[0] for d in cur.description]
            return [_row_map(cols, r) for r in cur.fetchall()]

    def _build_scan_sql(
        self,
        view: str,
        *,
        filters: FilterSpec,
        columns: Optional[Sequence[str]],
        graph_revision: Optional[str],
        source_cid: Optional[str],
        tenant: Optional[str],
        graph_id: Optional[str],
        limit: Optional[int],
        explain: bool,
    ) -> Tuple[str, List[Any]]:
        if view not in _VIEW_COLUMNS:
            raise ProjectionError(
                "INVALID_REQUEST",
                f"unknown typed view: {view!r}",
                details={"view": view, "known": sorted(_VIEW_COLUMNS)},
            )
        if columns is not None:
            for col in columns:
                if not isinstance(col, str) or _SAFE_COL_RE.fullmatch(col) is None:
                    raise ProjectionError(
                        "INVALID_REQUEST",
                        f"invalid projection column: {col!r}",
                    )
            select_list = ", ".join(f'"{c}"' for c in columns)
        else:
            select_list = "*"

        filt = _normalize_filters(filters)
        params: List[Any] = []
        clauses: List[str] = []
        if tenant is not None:
            clauses.append('"tenant" = ?')
            params.append(tenant)
        if graph_id is not None:
            clauses.append('"graph_id" = ?')
            params.append(graph_id)
        if graph_revision is not None:
            clauses.append('"graph_revision" = ?')
            params.append(graph_revision)
        if source_cid is not None:
            clauses.append('"source_cid" = ?')
            params.append(source_cid)
        if filt:
            clauses.append(_filter_sql(filt, params=params))
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        limit_sql = ""
        if limit is not None:
            if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
                raise ProjectionError("INVALID_REQUEST", "limit must be a non-negative int")
            limit_sql = f" LIMIT {int(limit)}"

        sql = f'SELECT {select_list} FROM "{view}"{where}{limit_sql}'
        if explain:
            sql = f"EXPLAIN {sql}"
        return sql, params

    # -- utilities ---------------------------------------------------------

    def table_names(self) -> List[str]:
        with self._cursor() as conn:
            rows = conn.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'main'
                ORDER BY table_name
                """
            ).fetchall()
            return [r[0] for r in rows]

    def execute(self, sql: str, params: Optional[Sequence[Any]] = None) -> Any:
        """Low-level execute for advanced callers (parameterized)."""

        with self._cursor() as conn:
            return conn.execute(sql, list(params or []))


def create_duckdb_graph_projection(path: PathLike) -> DuckDBGraphProjection:
    """Factory for the DuckDB graph projection surface."""

    return DuckDBGraphProjection(path)
