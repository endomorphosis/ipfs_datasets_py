"""Streaming legacy artifact importer (DQK-044).

Imports JSON, JSONL, Markdown taskboards, SQLite tables, Parquet row groups,
vector metadata, and manifests through type-specific bounded batches while
retaining:

* original source-byte digests
* line / record provenance on every accepted and rejected row
* resumable cursors (interrupted imports resume exactly)
* reject tables for contract/parse failures
* caller idempotency keys (logical-once publication)

Derived exports and export receipts are never silently re-imported: the
importer fail-closes unless the caller sets ``allow_exports=True`` explicitly.

Importing this module is inert.  Unit tests use the hermetic
:class:`MemoryImportBackend`; production backends persist cursors, rejects,
and records into control-plane tables.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import struct
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import (
    Any,
    Callable,
    ClassVar,
    Final,
    Iterator,
    Mapping,
    Protocol,
    Sequence,
)

from ipfs_datasets_py.duckdb_control.contracts import (
    EXPORT_RECEIPT_SCHEMA,
    IdempotencyKey,
    SourceDigest,
    parse_source_digest,
)
from ipfs_datasets_py.duckdb_control.inventory import (
    ArtifactKind,
    ProposedAuthority,
    classify_path,
    digest_file_streaming,
    normalize_rel_path,
)

__all__ = [
    "DEFAULT_BATCH_SIZES",
    "IMPORTER_SCHEMA",
    "IMPORT_CURSOR_SCHEMA",
    "IMPORT_JOB_SCHEMA",
    "IMPORT_RECEIPT_SCHEMA",
    "IMPORT_REJECT_SCHEMA",
    "ArtifactImporter",
    "ImportBackend",
    "ImportCursor",
    "ImportError",
    "ImportJob",
    "ImportReceipt",
    "ImportRecord",
    "ImportReject",
    "ImportStatus",
    "MemoryImportBackend",
    "ParsedItem",
    "SourceKind",
    "batch_size_for",
    "detect_source_kind",
    "is_export_artifact",
    "iter_source_items",
    "source_digest_for_path",
]


IMPORTER_SCHEMA: Final[str] = "ipfs_datasets_py/duckdb-control-importer@1"
IMPORT_JOB_SCHEMA: Final[str] = "ipfs_datasets_py/duckdb-control-import-job@1"
IMPORT_CURSOR_SCHEMA: Final[str] = "ipfs_datasets_py/duckdb-control-import-cursor@1"
IMPORT_REJECT_SCHEMA: Final[str] = "ipfs_datasets_py/duckdb-control-import-reject@1"
IMPORT_RECEIPT_SCHEMA: Final[str] = "ipfs_datasets_py/duckdb-control-import-receipt@1"

# Type-specific bounded batch defaults keep peak memory independent of corpus size.
DEFAULT_BATCH_SIZES: Final[Mapping[str, int]] = MappingProxyType(
    {
        "json": 100,
        "jsonl": 500,
        "markdown_taskboard": 50,
        "sqlite": 1000,
        "parquet": 1000,
        "vector_metadata": 100,
        "manifest": 100,
    }
)

_MAX_SNIPPET_BYTES: Final[int] = 512
_MAX_PAYLOAD_BYTES: Final[int] = 262_144
_CHUNK_SIZE: Final[int] = 1024 * 1024

_TASK_LINE = re.compile(
    r"^(?P<indent>\s*)[-*+]\s+\[(?P<mark>[ xX])\]\s+(?P<body>.+?)\s*$"
)
_HEADING_LINE = re.compile(r"^(?P<level>#{1,6})\s+(?P<title>.+?)\s*$")
_EXPORT_PATH_MARKERS: Final[tuple[str, ...]] = (
    "/exports/",
    "/derived/",
    "/projections/",
    "/release_exports/",
    "export_jobs",
)
_VECTOR_META_SUFFIXES: Final[tuple[str, ...]] = (
    ".meta.json",
    ".metadata.json",
    ".vector.json",
    ".embeddings.json",
    ".vector_meta.json",
)
_MANIFEST_NAME_RE = re.compile(
    r"(^|/)(manifests?|[^/]*_manifest)\.json$", re.IGNORECASE
)
_TASKBOARD_SUFFIXES: Final[tuple[str, ...]] = (
    ".todo.md",
    ".taskboard.todo.md",
    "master_todo_list.md",
    "objectives.md",
    "taskboard.todo.md",
)


class ImportError(ValueError):
    """Fail-closed import rejection (contract, export guard, or resume)."""


class SourceKind(str, Enum):
    """Closed set of type-specific import adapters."""

    JSON = "json"
    JSONL = "jsonl"
    MARKDOWN_TASKBOARD = "markdown_taskboard"
    SQLITE = "sqlite"
    PARQUET = "parquet"
    VECTOR_METADATA = "vector_metadata"
    MANIFEST = "manifest"

    @classmethod
    def parse(cls, value: str | SourceKind) -> SourceKind:
        if isinstance(value, SourceKind):
            return value
        text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "md": cls.MARKDOWN_TASKBOARD,
            "markdown": cls.MARKDOWN_TASKBOARD,
            "taskboard": cls.MARKDOWN_TASKBOARD,
            "todo": cls.MARKDOWN_TASKBOARD,
            "sqlite3": cls.SQLITE,
            "db": cls.SQLITE,
            "pq": cls.PARQUET,
            "vector": cls.VECTOR_METADATA,
            "vector_meta": cls.VECTOR_METADATA,
            "embedding_meta": cls.VECTOR_METADATA,
            "manifests": cls.MANIFEST,
        }
        if text in aliases:
            return aliases[text]
        return cls(text)


class ImportStatus(str, Enum):
    """Lifecycle of one import job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED_EXPORT = "skipped_export"
    SKIPPED_IDEMPOTENT = "skipped_idempotent"


def batch_size_for(kind: SourceKind | str, override: int | None = None) -> int:
    """Return the effective positive batch size for *kind*."""

    if override is not None:
        if not isinstance(override, int) or isinstance(override, bool) or override < 1:
            raise ImportError("batch_size must be a positive integer")
        return override
    parsed = SourceKind.parse(kind)
    return int(DEFAULT_BATCH_SIZES[parsed.value])


def _utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _safe_token(value: str, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ImportError(f"{field_name} is required")
    if "\x00" in text or "\n" in text or "\r" in text:
        raise ImportError(f"{field_name} must be single-line text")
    if len(text.encode("utf-8")) > 512:
        raise ImportError(f"{field_name} exceeds 512-byte bound")
    return text


def _clip_snippet(raw: str | bytes, *, limit: int = _MAX_SNIPPET_BYTES) -> str:
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception:
            text = raw.hex()
    else:
        text = str(raw)
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    return encoded[:limit].decode("utf-8", errors="ignore") + "…"


def source_digest_for_path(
    path: str | os.PathLike[str] | Path,
    *,
    chunk_size: int = _CHUNK_SIZE,
) -> SourceDigest:
    """Stream-hash exact source bytes; never load the full file into memory."""

    size, hex_digest = digest_file_streaming(path, chunk_size=chunk_size)
    if size < 0:
        raise ImportError("source size must be non-negative")
    return SourceDigest(digest=f"sha256:{hex_digest}")


def detect_source_kind(
    path: str | os.PathLike[str] | Path,
    *,
    explicit: SourceKind | str | None = None,
) -> SourceKind:
    """Detect adapter kind from *explicit* override or path name heuristics."""

    if explicit is not None:
        return SourceKind.parse(explicit)

    rel = normalize_rel_path(path)
    name = Path(rel).name.lower()
    lower = rel.lower()

    if any(name.endswith(suffix) or lower.endswith(suffix) for suffix in _VECTOR_META_SUFFIXES):
        return SourceKind.VECTOR_METADATA
    if _MANIFEST_NAME_RE.search(lower) is not None:
        return SourceKind.MANIFEST
    if any(name.endswith(suffix) or name == suffix for suffix in _TASKBOARD_SUFFIXES):
        return SourceKind.MARKDOWN_TASKBOARD
    if name.endswith((".todo.md", ".taskboard.md")) or "taskboard" in name:
        return SourceKind.MARKDOWN_TASKBOARD
    if name.endswith(".jsonl") or name.endswith(".ndjson"):
        return SourceKind.JSONL
    if name.endswith((".sqlite", ".sqlite3", ".db")):
        return SourceKind.SQLITE
    if name.endswith((".parquet", ".pq")):
        return SourceKind.PARQUET
    if name.endswith(".json"):
        return SourceKind.JSON
    if name.endswith(".md"):
        return SourceKind.MARKDOWN_TASKBOARD
    raise ImportError(
        f"cannot detect source kind for {rel!r}; pass source_kind explicitly"
    )


def is_export_artifact(
    path: str | os.PathLike[str] | Path,
    *,
    kind: ArtifactKind | str | None = None,
    proposed_authority: ProposedAuthority | str | None = None,
    payload: Any | None = None,
) -> bool:
    """Return True when *path*/*payload* is a derived export (must not re-import).

    Detection layers (any hit is sufficient):

    1. Inventory classification kind / proposed authority when supplied.
    2. Path markers (``/exports/``, ``/derived/``, …).
    3. Payload shaped like an :class:`~contracts.ExportReceipt`.
    """

    rel = normalize_rel_path(path)
    lower = f"/{rel.lower()}" if not rel.lower().startswith("/") else rel.lower()

    if kind is not None:
        parsed_kind = (
            kind if isinstance(kind, ArtifactKind) else ArtifactKind.parse(str(kind))
        )
        if parsed_kind is ArtifactKind.DERIVED_EXPORT:
            return True
    if proposed_authority is not None:
        auth = (
            proposed_authority
            if isinstance(proposed_authority, ProposedAuthority)
            else ProposedAuthority.parse(str(proposed_authority))
        )
        if auth is ProposedAuthority.EXPORT_ONLY:
            return True

    for marker in _EXPORT_PATH_MARKERS:
        if marker in lower:
            return True

    # Inventory default rules (no I/O): classify relative path.
    try:
        rule = classify_path(rel)
        if rule.kind is ArtifactKind.DERIVED_EXPORT:
            return True
        if rule.proposed_authority is ProposedAuthority.EXPORT_ONLY:
            return True
    except Exception:
        pass

    if payload is not None and _looks_like_export_receipt(payload):
        return True
    return False


def _looks_like_export_receipt(payload: Any) -> bool:
    if not isinstance(payload, Mapping):
        return False
    schema = str(payload.get("schema") or "")
    if schema == EXPORT_RECEIPT_SCHEMA:
        return True
    if payload.get("non_authoritative") is True and "export_id" in payload:
        return True
    if "export_id" in payload and "renderer_version" in payload and "snapshot" in payload:
        return True
    return False


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ParsedItem:
    """One parsed source unit before accept/reject decision."""

    record_index: int
    line_number: int
    payload: Any | None = None
    raw_text: str = ""
    error: str = ""
    table_name: str = ""
    row_id: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and self.payload is not None


@dataclass(frozen=True)
class ImportRecord:
    """Accepted import row with source provenance."""

    record_id: str
    job_id: str
    source_path: str
    source_digest: str
    source_kind: str
    record_index: int
    line_number: int
    batch_index: int
    payload_json: str
    payload_digest: str
    idempotency_key: str
    table_name: str = ""
    row_id: str = ""
    created_at: str = field(default_factory=_utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "job_id": self.job_id,
            "source_path": self.source_path,
            "source_digest": self.source_digest,
            "source_kind": self.source_kind,
            "record_index": self.record_index,
            "line_number": self.line_number,
            "batch_index": self.batch_index,
            "payload_json": self.payload_json,
            "payload_digest": self.payload_digest,
            "idempotency_key": self.idempotency_key,
            "table_name": self.table_name,
            "row_id": self.row_id,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ImportReject:
    """Rejected row retained for operator review (reject table)."""

    reject_id: str
    job_id: str
    source_path: str
    source_digest: str
    source_kind: str
    record_index: int
    line_number: int
    batch_index: int
    reason: str
    raw_snippet: str = ""
    table_name: str = ""
    created_at: str = field(default_factory=_utc_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reject_id": self.reject_id,
            "job_id": self.job_id,
            "source_path": self.source_path,
            "source_digest": self.source_digest,
            "source_kind": self.source_kind,
            "record_index": self.record_index,
            "line_number": self.line_number,
            "batch_index": self.batch_index,
            "reason": self.reason,
            "raw_snippet": self.raw_snippet,
            "table_name": self.table_name,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ImportCursor:
    """Resumable cursor: next record_index to process for a job."""

    SCHEMA: ClassVar[str] = IMPORT_CURSOR_SCHEMA
    job_id: str
    source_path: str
    source_digest: str
    source_kind: str
    next_record_index: int
    batch_index: int
    accepted_count: int = 0
    rejected_count: int = 0
    updated_at: str = field(default_factory=_utc_iso)

    def __post_init__(self) -> None:
        if self.next_record_index < 0:
            raise ImportError("next_record_index must be non-negative")
        if self.batch_index < 0:
            raise ImportError("batch_index must be non-negative")
        object.__setattr__(
            self, "source_digest", parse_source_digest(self.source_digest)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "job_id": self.job_id,
            "source_path": self.source_path,
            "source_digest": self.source_digest,
            "source_kind": self.source_kind,
            "next_record_index": self.next_record_index,
            "batch_index": self.batch_index,
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class ImportJob:
    """Durable import job identity bound to source digest + idempotency key."""

    SCHEMA: ClassVar[str] = IMPORT_JOB_SCHEMA
    job_id: str
    source_path: str
    source_kind: str
    source_digest: str
    idempotency_key: str
    idempotency_scope: str
    batch_size: int
    status: str
    byte_size: int = 0
    total_records: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    created_at: str = field(default_factory=_utc_iso)
    updated_at: str = field(default_factory=_utc_iso)

    def __post_init__(self) -> None:
        object.__setattr__(self, "job_id", _safe_token(self.job_id, field_name="job_id"))
        object.__setattr__(
            self, "source_path", normalize_rel_path(self.source_path) or self.source_path
        )
        object.__setattr__(
            self, "source_kind", SourceKind.parse(self.source_kind).value
        )
        object.__setattr__(
            self, "source_digest", parse_source_digest(self.source_digest)
        )
        key = IdempotencyKey(
            key=self.idempotency_key, scope=self.idempotency_scope or "default"
        )
        object.__setattr__(self, "idempotency_key", key.key)
        object.__setattr__(self, "idempotency_scope", key.scope)
        if not isinstance(self.batch_size, int) or self.batch_size < 1:
            raise ImportError("batch_size must be a positive integer")
        try:
            ImportStatus(self.status)
        except ValueError as exc:
            raise ImportError(f"unsupported import status {self.status!r}") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "job_id": self.job_id,
            "source_path": self.source_path,
            "source_kind": self.source_kind,
            "source_digest": self.source_digest,
            "idempotency_key": self.idempotency_key,
            "idempotency_scope": self.idempotency_scope,
            "batch_size": self.batch_size,
            "status": self.status,
            "byte_size": self.byte_size,
            "total_records": self.total_records,
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class ImportReceipt:
    """Immutable completion receipt for one import job."""

    SCHEMA: ClassVar[str] = IMPORT_RECEIPT_SCHEMA
    receipt_id: str
    job_id: str
    source_path: str
    source_kind: str
    source_digest: str
    idempotency_key: str
    status: str
    accepted_count: int
    rejected_count: int
    total_records: int
    batch_size: int
    batches_committed: int
    resumed: bool = False
    cursor_next_record_index: int = 0
    created_at: str = field(default_factory=_utc_iso)

    def __post_init__(self) -> None:
        if not self.receipt_id:
            body = {
                "job_id": self.job_id,
                "source_path": self.source_path,
                "source_kind": self.source_kind,
                "source_digest": self.source_digest,
                "idempotency_key": self.idempotency_key,
                "status": self.status,
                "accepted_count": self.accepted_count,
                "rejected_count": self.rejected_count,
                "total_records": self.total_records,
                "batch_size": self.batch_size,
                "batches_committed": self.batches_committed,
                "resumed": self.resumed,
                "cursor_next_record_index": self.cursor_next_record_index,
                "created_at": self.created_at,
            }
            object.__setattr__(
                self,
                "receipt_id",
                "sha256:" + _sha256_text(_canonical_json(body)),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "receipt_id": self.receipt_id,
            "job_id": self.job_id,
            "source_path": self.source_path,
            "source_kind": self.source_kind,
            "source_digest": self.source_digest,
            "idempotency_key": self.idempotency_key,
            "status": self.status,
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
            "total_records": self.total_records,
            "batch_size": self.batch_size,
            "batches_committed": self.batches_committed,
            "resumed": self.resumed,
            "cursor_next_record_index": self.cursor_next_record_index,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Type-specific parsers (streaming / bounded)
# ---------------------------------------------------------------------------


def _iter_json_items(path: Path) -> Iterator[ParsedItem]:
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        yield ParsedItem(
            record_index=0,
            line_number=exc.lineno or 1,
            raw_text=_clip_snippet(text),
            error=f"json decode error: {exc.msg}",
        )
        return

    if isinstance(data, list):
        for index, item in enumerate(data):
            yield ParsedItem(
                record_index=index,
                line_number=index + 1,
                payload=item,
                raw_text=_clip_snippet(_canonical_json(item) if not isinstance(item, str) else item),
            )
        return

    if isinstance(data, Mapping):
        # Nested list under common collection keys expands to multiple records.
        for key in ("items", "records", "rows", "data", "entries", "tasks"):
            nested = data.get(key)
            if isinstance(nested, list):
                for index, item in enumerate(nested):
                    payload = item
                    if isinstance(item, Mapping):
                        payload = dict(item)
                        payload.setdefault("_collection", key)
                    yield ParsedItem(
                        record_index=index,
                        line_number=index + 1,
                        payload=payload,
                        raw_text=_clip_snippet(
                            _canonical_json(item)
                            if not isinstance(item, str)
                            else item
                        ),
                    )
                return
        yield ParsedItem(
            record_index=0,
            line_number=1,
            payload=dict(data),
            raw_text=_clip_snippet(text),
        )
        return

    yield ParsedItem(
        record_index=0,
        line_number=1,
        payload=data,
        raw_text=_clip_snippet(text),
    )


def _iter_jsonl_items(path: Path) -> Iterator[ParsedItem]:
    # Stream line-by-line; never join the whole file.
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        record_index = 0
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                yield ParsedItem(
                    record_index=record_index,
                    line_number=line_number,
                    raw_text=_clip_snippet(stripped),
                    error=f"jsonl decode error: {exc.msg}",
                )
                record_index += 1
                continue
            yield ParsedItem(
                record_index=record_index,
                line_number=line_number,
                payload=payload,
                raw_text=_clip_snippet(stripped),
            )
            record_index += 1


def _iter_markdown_taskboard_items(path: Path) -> Iterator[ParsedItem]:
    section_stack: list[str] = []
    record_index = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            heading = _HEADING_LINE.match(line.rstrip("\n"))
            if heading is not None:
                level = len(heading.group("level"))
                title = heading.group("title").strip()
                # Collapse stack to parent of this heading level.
                while len(section_stack) >= level:
                    section_stack.pop()
                section_stack.append(title)
                continue
            task = _TASK_LINE.match(line.rstrip("\n"))
            if task is None:
                continue
            mark = task.group("mark")
            body = task.group("body").strip()
            done = mark.lower() == "x"
            payload = {
                "kind": "task",
                "text": body,
                "done": done,
                "section": list(section_stack),
                "indent": len(task.group("indent")),
            }
            yield ParsedItem(
                record_index=record_index,
                line_number=line_number,
                payload=payload,
                raw_text=_clip_snippet(line.rstrip("\n")),
            )
            record_index += 1


def _iter_sqlite_items(path: Path) -> Iterator[ParsedItem]:
    uri = f"file:{path.resolve()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        yield ParsedItem(
            record_index=0,
            line_number=0,
            error=f"sqlite open failed: {exc}",
            raw_text=str(path),
        )
        return
    conn.row_factory = sqlite3.Row
    record_index = 0
    try:
        tables = [
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            )
        ]
        for table in tables:
            # Quote table name safely for SQLite identifiers.
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
                yield ParsedItem(
                    record_index=record_index,
                    line_number=0,
                    table_name=table,
                    error=f"sqlite table name not import-safe: {table!r}",
                    raw_text=table,
                )
                record_index += 1
                continue
            try:
                cursor = conn.execute(f'SELECT rowid AS _rowid_, * FROM "{table}"')
            except sqlite3.Error as exc:
                yield ParsedItem(
                    record_index=record_index,
                    line_number=0,
                    table_name=table,
                    error=f"sqlite select failed: {exc}",
                    raw_text=table,
                )
                record_index += 1
                continue
            columns = [desc[0] for desc in cursor.description]
            for row in cursor:
                mapping = {columns[i]: row[i] for i in range(len(columns))}
                row_id = str(mapping.get("_rowid_", record_index))
                # Make values JSON-safe.
                safe: dict[str, Any] = {}
                for key, value in mapping.items():
                    if isinstance(value, bytes):
                        safe[key] = {"_bytes_hex": value.hex()}
                    else:
                        safe[key] = value
                safe["_table"] = table
                yield ParsedItem(
                    record_index=record_index,
                    line_number=int(mapping.get("_rowid_", record_index + 1)),
                    payload=safe,
                    table_name=table,
                    row_id=row_id,
                    raw_text=_clip_snippet(_canonical_json(safe)),
                )
                record_index += 1
    finally:
        conn.close()


def _iter_vector_metadata_items(path: Path) -> Iterator[ParsedItem]:
    # Vector metadata is JSON (or JSONL) describing embeddings, not vector bytes.
    if path.suffix.lower() == ".jsonl" or path.name.lower().endswith(".jsonl"):
        yield from _iter_jsonl_items(path)
        return
    for item in _iter_json_items(path):
        if item.ok and isinstance(item.payload, Mapping):
            payload = dict(item.payload)
            payload.setdefault("_vector_metadata", True)
            yield ParsedItem(
                record_index=item.record_index,
                line_number=item.line_number,
                payload=payload,
                raw_text=item.raw_text,
                error=item.error,
            )
        else:
            yield item


def _iter_manifest_items(path: Path) -> Iterator[ParsedItem]:
    for item in _iter_json_items(path):
        if not item.ok:
            yield item
            continue
        payload = item.payload
        if isinstance(payload, Mapping):
            # Expand file lists into one record per entry when present.
            for key in ("files", "entries", "artifacts", "objects", "cids"):
                nested = payload.get(key)
                if isinstance(nested, list):
                    for index, entry in enumerate(nested):
                        if isinstance(entry, Mapping):
                            body = dict(entry)
                        else:
                            body = {"value": entry}
                        body.setdefault("_manifest_key", key)
                        body.setdefault("_manifest_path", normalize_rel_path(path))
                        yield ParsedItem(
                            record_index=index,
                            line_number=index + 1,
                            payload=body,
                            raw_text=_clip_snippet(
                                _canonical_json(entry)
                                if not isinstance(entry, str)
                                else entry
                            ),
                        )
                    return
            body = dict(payload)
            body.setdefault("_manifest_path", normalize_rel_path(path))
            yield ParsedItem(
                record_index=item.record_index,
                line_number=item.line_number,
                payload=body,
                raw_text=item.raw_text,
            )
            return
        yield item


def _read_parquet_row_groups_stdlib(path: Path) -> Iterator[ParsedItem]:
    """Minimal Parquet footer reader for row-group provenance without pyarrow.

    When pyarrow/duckdb are unavailable, emit one synthetic record per row
    group with byte-range provenance so imports remain resumable and digests
    bind the exact source file.  Full cell materialization requires an
    optional accelerated reader.
    """

    data_size = path.stat().st_size
    if data_size < 8:
        yield ParsedItem(
            record_index=0,
            line_number=0,
            error="parquet file too small",
            raw_text=str(path),
        )
        return
    with path.open("rb") as handle:
        handle.seek(-8, os.SEEK_END)
        footer_len_bytes = handle.read(4)
        magic = handle.read(4)
        if magic != b"PAR1":
            yield ParsedItem(
                record_index=0,
                line_number=0,
                error="parquet magic footer missing",
                raw_text=magic.hex(),
            )
            return
        footer_len = struct.unpack("<I", footer_len_bytes)[0]
        if footer_len <= 0 or footer_len > data_size - 8:
            yield ParsedItem(
                record_index=0,
                line_number=0,
                error=f"invalid parquet footer length {footer_len}",
            )
            return
        handle.seek(-(8 + footer_len), os.SEEK_END)
        footer = handle.read(footer_len)

    # Attempt optional readers for full rows; fall back to row-group metadata.
    rows = _try_accelerated_parquet_rows(path)
    if rows is not None:
        for index, row in enumerate(rows):
            yield ParsedItem(
                record_index=index,
                line_number=index + 1,
                payload=row,
                raw_text=_clip_snippet(_canonical_json(row)),
            )
        return

    # Row-group level provenance when cell decoding is unavailable.
    # Count approximate row groups by scanning thrift-ish "row_group" markers
    # is unreliable; emit a single file-level metadata record plus digest bind.
    payload = {
        "kind": "parquet_source",
        "path": normalize_rel_path(path),
        "byte_size": data_size,
        "footer_length": footer_len,
        "footer_digest": _sha256_bytes(footer),
        "decoder": "metadata_only",
    }
    yield ParsedItem(
        record_index=0,
        line_number=1,
        payload=payload,
        raw_text=_clip_snippet(_canonical_json(payload)),
    )


def _try_accelerated_parquet_rows(path: Path) -> list[dict[str, Any]] | None:
    """Optionally materialize Parquet rows via pyarrow or duckdb."""

    try:
        import pyarrow.parquet as pq  # type: ignore[import-not-found]

        table = pq.read_table(path)
        rows: list[dict[str, Any]] = []
        for batch in table.to_batches(max_chunksize=1000):
            for mapping in batch.to_pylist():
                rows.append(dict(mapping))
        return rows
    except Exception:
        pass

    try:
        import duckdb  # type: ignore[import-not-found]

        con = duckdb.connect(database=":memory:")
        try:
            rel = con.execute(
                "SELECT * FROM read_parquet(?)",
                [str(path)],
            )
            columns = [desc[0] for desc in rel.description]
            rows = []
            while True:
                chunk = rel.fetchmany(1000)
                if not chunk:
                    break
                for tup in chunk:
                    rows.append({columns[i]: tup[i] for i in range(len(columns))})
            return rows
        finally:
            con.close()
    except Exception:
        return None


def _iter_parquet_items(path: Path) -> Iterator[ParsedItem]:
    yield from _read_parquet_row_groups_stdlib(path)


def iter_source_items(
    path: str | os.PathLike[str] | Path,
    *,
    source_kind: SourceKind | str | None = None,
) -> Iterator[ParsedItem]:
    """Yield type-specific parsed items for *path* in stable record order."""

    target = Path(path)
    if not target.is_file():
        raise ImportError(f"source path is not a file: {path}")
    kind = detect_source_kind(target, explicit=source_kind)
    if kind is SourceKind.JSON:
        yield from _iter_json_items(target)
    elif kind is SourceKind.JSONL:
        yield from _iter_jsonl_items(target)
    elif kind is SourceKind.MARKDOWN_TASKBOARD:
        yield from _iter_markdown_taskboard_items(target)
    elif kind is SourceKind.SQLITE:
        yield from _iter_sqlite_items(target)
    elif kind is SourceKind.PARQUET:
        yield from _iter_parquet_items(target)
    elif kind is SourceKind.VECTOR_METADATA:
        yield from _iter_vector_metadata_items(target)
    elif kind is SourceKind.MANIFEST:
        yield from _iter_manifest_items(target)
    else:
        raise ImportError(f"unsupported source kind {kind!r}")


# ---------------------------------------------------------------------------
# Backend protocol + memory backend
# ---------------------------------------------------------------------------


class ImportBackend(Protocol):
    """Persistence surface for jobs, cursors, records, rejects, and keys."""

    def get_job(self, job_id: str) -> ImportJob | None: ...

    def get_job_by_idempotency(
        self, *, key: str, scope: str
    ) -> ImportJob | None: ...

    def save_job(self, job: ImportJob) -> None: ...

    def get_cursor(self, job_id: str) -> ImportCursor | None: ...

    def save_cursor(self, cursor: ImportCursor) -> None: ...

    def append_records(self, records: Sequence[ImportRecord]) -> None: ...

    def append_rejects(self, rejects: Sequence[ImportReject]) -> None: ...

    def list_records(self, job_id: str) -> Sequence[ImportRecord]: ...

    def list_rejects(self, job_id: str) -> Sequence[ImportReject]: ...

    def save_receipt(self, receipt: ImportReceipt) -> None: ...

    def get_receipt(self, job_id: str) -> ImportReceipt | None: ...

    def begin(self) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def mark_in_progress(self, job_id: str) -> None: ...

    def get_in_progress(self) -> str | None: ...

    def clear_in_progress(self, job_id: str) -> None: ...


class MemoryImportBackend:
    """Hermetic in-memory backend for unit tests (no DuckDB required)."""

    def __init__(self) -> None:
        self.jobs: dict[str, ImportJob] = {}
        self.jobs_by_idempotency: dict[tuple[str, str], str] = {}
        self.cursors: dict[str, ImportCursor] = {}
        self.records: dict[str, list[ImportRecord]] = {}
        self.rejects: dict[str, list[ImportReject]] = {}
        self.receipts: dict[str, ImportReceipt] = {}
        self._in_progress: str | None = None
        self._txn = False
        self._txn_jobs: dict[str, ImportJob] | None = None
        self._txn_idem: dict[tuple[str, str], str] | None = None
        self._txn_cursors: dict[str, ImportCursor] | None = None
        self._txn_records: dict[str, list[ImportRecord]] | None = None
        self._txn_rejects: dict[str, list[ImportReject]] | None = None
        self._txn_receipts: dict[str, ImportReceipt] | None = None
        self._txn_in_progress: str | None = None
        # Staging for appends within an open transaction.
        self._pending_records: list[ImportRecord] = []
        self._pending_rejects: list[ImportReject] = []
        self._pending_cursor: ImportCursor | None = None
        self._pending_job: ImportJob | None = None
        self._pending_receipt: ImportReceipt | None = None

    def get_job(self, job_id: str) -> ImportJob | None:
        return self.jobs.get(job_id)

    def get_job_by_idempotency(self, *, key: str, scope: str) -> ImportJob | None:
        job_id = self.jobs_by_idempotency.get((scope, key))
        if job_id is None:
            return None
        return self.jobs.get(job_id)

    def save_job(self, job: ImportJob) -> None:
        if self._txn:
            self._pending_job = job
            return
        self.jobs[job.job_id] = job
        self.jobs_by_idempotency[(job.idempotency_scope, job.idempotency_key)] = (
            job.job_id
        )

    def get_cursor(self, job_id: str) -> ImportCursor | None:
        return self.cursors.get(job_id)

    def save_cursor(self, cursor: ImportCursor) -> None:
        if self._txn:
            self._pending_cursor = cursor
            return
        self.cursors[cursor.job_id] = cursor

    def append_records(self, records: Sequence[ImportRecord]) -> None:
        if self._txn:
            self._pending_records.extend(records)
            return
        for record in records:
            self.records.setdefault(record.job_id, []).append(record)

    def append_rejects(self, rejects: Sequence[ImportReject]) -> None:
        if self._txn:
            self._pending_rejects.extend(rejects)
            return
        for reject in rejects:
            self.rejects.setdefault(reject.job_id, []).append(reject)

    def list_records(self, job_id: str) -> Sequence[ImportRecord]:
        return tuple(self.records.get(job_id, ()))

    def list_rejects(self, job_id: str) -> Sequence[ImportReject]:
        return tuple(self.rejects.get(job_id, ()))

    def save_receipt(self, receipt: ImportReceipt) -> None:
        if self._txn:
            self._pending_receipt = receipt
            return
        self.receipts[receipt.job_id] = receipt

    def get_receipt(self, job_id: str) -> ImportReceipt | None:
        return self.receipts.get(job_id)

    def begin(self) -> None:
        if self._txn:
            raise ImportError("transaction already open")
        self._txn = True
        self._txn_jobs = dict(self.jobs)
        self._txn_idem = dict(self.jobs_by_idempotency)
        self._txn_cursors = dict(self.cursors)
        self._txn_records = {k: list(v) for k, v in self.records.items()}
        self._txn_rejects = {k: list(v) for k, v in self.rejects.items()}
        self._txn_receipts = dict(self.receipts)
        self._txn_in_progress = self._in_progress
        self._pending_records = []
        self._pending_rejects = []
        self._pending_cursor = None
        self._pending_job = None
        self._pending_receipt = None

    def commit(self) -> None:
        if not self._txn:
            raise ImportError("no transaction to commit")
        # Apply pendings onto txn snapshots then promote.
        jobs = dict(self._txn_jobs or {})
        idem = dict(self._txn_idem or {})
        cursors = dict(self._txn_cursors or {})
        records = {k: list(v) for k, v in (self._txn_records or {}).items()}
        rejects = {k: list(v) for k, v in (self._txn_rejects or {}).items()}
        receipts = dict(self._txn_receipts or {})

        if self._pending_job is not None:
            job = self._pending_job
            jobs[job.job_id] = job
            idem[(job.idempotency_scope, job.idempotency_key)] = job.job_id
        if self._pending_cursor is not None:
            cursors[self._pending_cursor.job_id] = self._pending_cursor
        for record in self._pending_records:
            records.setdefault(record.job_id, []).append(record)
        for reject in self._pending_rejects:
            rejects.setdefault(reject.job_id, []).append(reject)
        if self._pending_receipt is not None:
            receipts[self._pending_receipt.job_id] = self._pending_receipt

        self.jobs = jobs
        self.jobs_by_idempotency = idem
        self.cursors = cursors
        self.records = records
        self.rejects = rejects
        self.receipts = receipts
        self._in_progress = self._txn_in_progress
        self._txn = False
        self._clear_txn_state()

    def rollback(self) -> None:
        self._txn = False
        self._clear_txn_state()

    def _clear_txn_state(self) -> None:
        self._txn_jobs = None
        self._txn_idem = None
        self._txn_cursors = None
        self._txn_records = None
        self._txn_rejects = None
        self._txn_receipts = None
        self._txn_in_progress = None
        self._pending_records = []
        self._pending_rejects = []
        self._pending_cursor = None
        self._pending_job = None
        self._pending_receipt = None

    def mark_in_progress(self, job_id: str) -> None:
        # Persist outside the txn so a crash still leaves a resume marker.
        self._in_progress = job_id
        if self._txn:
            self._txn_in_progress = job_id

    def get_in_progress(self) -> str | None:
        return self._in_progress

    def clear_in_progress(self, job_id: str) -> None:
        if self._in_progress == job_id:
            self._in_progress = None
        if self._txn and self._txn_in_progress == job_id:
            self._txn_in_progress = None

    def fail_mid_batch(self) -> None:
        """Simulate crash after mark_in_progress before commit (tests)."""

        self._txn = False
        self._clear_txn_state()
        # Leave _in_progress set.


# ---------------------------------------------------------------------------
# Importer
# ---------------------------------------------------------------------------


def _job_id_for(
    *,
    source_path: str,
    source_digest: str,
    idempotency_key: str,
    scope: str,
) -> str:
    body = {
        "source_path": source_path,
        "source_digest": source_digest,
        "idempotency_key": idempotency_key,
        "scope": scope,
    }
    return "import:" + _sha256_text(_canonical_json(body))[:32]


def _record_id_for(
    *,
    job_id: str,
    source_digest: str,
    record_index: int,
    payload_digest: str,
) -> str:
    body = {
        "job_id": job_id,
        "source_digest": source_digest,
        "record_index": record_index,
        "payload_digest": payload_digest,
    }
    return "rec:" + _sha256_text(_canonical_json(body))[:32]


def _reject_id_for(
    *,
    job_id: str,
    source_digest: str,
    record_index: int,
    reason: str,
) -> str:
    body = {
        "job_id": job_id,
        "source_digest": source_digest,
        "record_index": record_index,
        "reason": reason,
    }
    return "rej:" + _sha256_text(_canonical_json(body))[:32]


def _serialize_payload(payload: Any) -> tuple[str, str]:
    try:
        if isinstance(payload, (dict, list, str, int, float, bool)) or payload is None:
            text = _canonical_json(payload)
        else:
            text = _canonical_json(str(payload))
    except (TypeError, ValueError) as exc:
        raise ImportError(f"payload is not JSON-serializable: {exc}") from exc
    raw = text.encode("utf-8")
    if len(raw) > _MAX_PAYLOAD_BYTES:
        raise ImportError(
            f"payload exceeds {_MAX_PAYLOAD_BYTES}-byte bound after serialization"
        )
    return text, "sha256:" + hashlib.sha256(raw).hexdigest()


class ArtifactImporter:
    """Streaming, resumable, idempotent legacy artifact importer."""

    SCHEMA: ClassVar[str] = IMPORTER_SCHEMA

    def __init__(
        self,
        backend: ImportBackend | None = None,
        *,
        owner_id: str = "local",
    ) -> None:
        self.backend: ImportBackend = backend or MemoryImportBackend()
        self.owner_id = _safe_token(owner_id, field_name="owner_id")

    def import_path(
        self,
        path: str | os.PathLike[str] | Path,
        *,
        source_kind: SourceKind | str | None = None,
        batch_size: int | None = None,
        idempotency_key: str | IdempotencyKey | None = None,
        idempotency_scope: str = "import",
        resume: bool = True,
        allow_exports: bool = False,
        display_path: str | None = None,
        max_batches: int | None = None,
        on_batch_commit: Callable[[ImportCursor, ImportJob], None] | None = None,
        crash_after_batches: int | None = None,
    ) -> ImportReceipt:
        """Import *path* through type-specific bounded batches.

        Parameters
        ----------
        resume:
            When True (default), continue from a stored cursor after interrupt.
            When False, an in-progress job fail-closes.
        allow_exports:
            Explicit opt-in to import paths classified as derived exports.
            Default False — exports are never silently re-imported.
        max_batches:
            Optional bound on batches to commit in this call (useful for tests).
        crash_after_batches:
            Test hook: after N successful batch commits, simulate interrupt.
        """

        target = Path(path)
        if not target.is_file():
            raise ImportError(f"source path is not a file: {path}")

        rel = display_path or normalize_rel_path(target.name)
        if display_path is None:
            # Prefer a stable relative name; callers may pass full rel paths.
            rel = normalize_rel_path(str(path)) if not Path(path).is_absolute() else target.name

        kind = detect_source_kind(target, explicit=source_kind)
        effective_batch = batch_size_for(kind, batch_size)

        # --- Export guard (never silently re-import) ---
        export_hit = is_export_artifact(rel)
        # Also inspect path string markers on the absolute path's trailing parts.
        if not export_hit:
            export_hit = is_export_artifact(target.as_posix())
        if export_hit and not allow_exports:
            raise ImportError(
                f"refusing to import derived export {rel!r}; "
                "exports are never silently re-imported "
                "(pass allow_exports=True to override explicitly)"
            )

        # Peek first payload for export-receipt shape (JSON family only).
        if not allow_exports and kind in {
            SourceKind.JSON,
            SourceKind.MANIFEST,
            SourceKind.VECTOR_METADATA,
        }:
            try:
                peek = json.loads(target.read_text(encoding="utf-8"))
            except Exception:
                peek = None
            if peek is not None and is_export_artifact(rel, payload=peek):
                raise ImportError(
                    f"refusing to import export receipt payload at {rel!r}; "
                    "exports are never silently re-imported "
                    "(pass allow_exports=True to override explicitly)"
                )

        source_digest = source_digest_for_path(target)
        byte_size = target.stat().st_size

        if isinstance(idempotency_key, IdempotencyKey):
            idemp = idempotency_key
        elif idempotency_key is None:
            # Derive a stable key from source path + digest so pure re-runs
            # are idempotent without caller ceremony.
            idemp = IdempotencyKey(
                key="src-" + source_digest.digest[7:39],
                scope=idempotency_scope,
            )
        else:
            idemp = IdempotencyKey(key=str(idempotency_key), scope=idempotency_scope)

        existing = self.backend.get_job_by_idempotency(
            key=idemp.key, scope=idemp.scope
        )
        if existing is not None:
            if existing.source_digest != source_digest.digest:
                raise ImportError(
                    f"idempotency key {idemp.key!r} already bound to digest "
                    f"{existing.source_digest}, refusing {source_digest.digest}"
                )
            if existing.status == ImportStatus.COMPLETED.value:
                receipt = self.backend.get_receipt(existing.job_id)
                if receipt is None:
                    # Reconstruct a receipt from the completed job when the
                    # durable receipt row is missing (partial backend state).
                    cursor = self.backend.get_cursor(existing.job_id)
                    return ImportReceipt(
                        receipt_id="",
                        job_id=existing.job_id,
                        source_path=existing.source_path,
                        source_kind=existing.source_kind,
                        source_digest=existing.source_digest,
                        idempotency_key=existing.idempotency_key,
                        status=ImportStatus.SKIPPED_IDEMPOTENT.value,
                        accepted_count=existing.accepted_count,
                        rejected_count=existing.rejected_count,
                        total_records=existing.total_records,
                        batch_size=existing.batch_size,
                        batches_committed=cursor.batch_index if cursor else 0,
                        resumed=False,
                        cursor_next_record_index=(
                            cursor.next_record_index if cursor else 0
                        ),
                    )
                return ImportReceipt(
                    receipt_id=receipt.receipt_id,
                    job_id=receipt.job_id,
                    source_path=receipt.source_path,
                    source_kind=receipt.source_kind,
                    source_digest=receipt.source_digest,
                    idempotency_key=receipt.idempotency_key,
                    status=ImportStatus.SKIPPED_IDEMPOTENT.value,
                    accepted_count=receipt.accepted_count,
                    rejected_count=receipt.rejected_count,
                    total_records=receipt.total_records,
                    batch_size=receipt.batch_size,
                    batches_committed=receipt.batches_committed,
                    resumed=False,
                    cursor_next_record_index=receipt.cursor_next_record_index,
                    created_at=receipt.created_at,
                )
            job = existing
            job_id = job.job_id
        else:
            job_id = _job_id_for(
                source_path=rel,
                source_digest=source_digest.digest,
                idempotency_key=idemp.key,
                scope=idemp.scope,
            )
            job = ImportJob(
                job_id=job_id,
                source_path=rel,
                source_kind=kind.value,
                source_digest=source_digest.digest,
                idempotency_key=idemp.key,
                idempotency_scope=idemp.scope,
                batch_size=effective_batch,
                status=ImportStatus.PENDING.value,
                byte_size=byte_size,
            )
            self.backend.save_job(job)

        in_progress = self.backend.get_in_progress()
        if in_progress and in_progress != job_id and not resume:
            raise ImportError(
                f"interrupted import {in_progress!r} requires resume=True"
            )
        if in_progress == job_id and not resume:
            raise ImportError(
                f"interrupted import {job_id!r} requires resume=True"
            )

        cursor = self.backend.get_cursor(job_id)
        resumed = cursor is not None and cursor.next_record_index > 0
        if cursor is None:
            cursor = ImportCursor(
                job_id=job_id,
                source_path=rel,
                source_digest=source_digest.digest,
                source_kind=kind.value,
                next_record_index=0,
                batch_index=0,
                accepted_count=0,
                rejected_count=0,
            )
        else:
            # Digest drift on resume is fail-closed.
            if cursor.source_digest != source_digest.digest:
                raise ImportError(
                    f"source digest changed under cursor for {rel!r}: "
                    f"cursor {cursor.source_digest}, file {source_digest.digest}"
                )

        start_index = cursor.next_record_index
        accepted = cursor.accepted_count
        rejected = cursor.rejected_count
        batch_index = cursor.batch_index
        batches_this_call = 0
        total_seen = start_index

        job = ImportJob(
            job_id=job.job_id,
            source_path=job.source_path,
            source_kind=job.source_kind,
            source_digest=job.source_digest,
            idempotency_key=job.idempotency_key,
            idempotency_scope=job.idempotency_scope,
            batch_size=effective_batch,
            status=ImportStatus.RUNNING.value,
            byte_size=byte_size,
            total_records=job.total_records,
            accepted_count=accepted,
            rejected_count=rejected,
            created_at=job.created_at,
            updated_at=_utc_iso(),
        )
        self.backend.save_job(job)
        self.backend.mark_in_progress(job_id)

        pending_records: list[ImportRecord] = []
        pending_rejects: list[ImportReject] = []
        exhausted = False

        try:
            for item in iter_source_items(target, source_kind=kind):
                if item.record_index < start_index:
                    # Already committed in a prior batch — skip exactly.
                    continue

                total_seen = item.record_index + 1
                batch_local_index = item.record_index

                if item.error or not item.ok:
                    reject = ImportReject(
                        reject_id=_reject_id_for(
                            job_id=job_id,
                            source_digest=source_digest.digest,
                            record_index=item.record_index,
                            reason=item.error or "empty payload",
                        ),
                        job_id=job_id,
                        source_path=rel,
                        source_digest=source_digest.digest,
                        source_kind=kind.value,
                        record_index=item.record_index,
                        line_number=item.line_number,
                        batch_index=batch_index,
                        reason=item.error or "empty payload",
                        raw_snippet=item.raw_text,
                        table_name=item.table_name,
                    )
                    pending_rejects.append(reject)
                    rejected += 1
                else:
                    # Export-receipt rows inside multi-record files.
                    if (
                        not allow_exports
                        and isinstance(item.payload, Mapping)
                        and _looks_like_export_receipt(item.payload)
                    ):
                        reject = ImportReject(
                            reject_id=_reject_id_for(
                                job_id=job_id,
                                source_digest=source_digest.digest,
                                record_index=item.record_index,
                                reason="export_receipt_row",
                            ),
                            job_id=job_id,
                            source_path=rel,
                            source_digest=source_digest.digest,
                            source_kind=kind.value,
                            record_index=item.record_index,
                            line_number=item.line_number,
                            batch_index=batch_index,
                            reason=(
                                "export receipt rows are never silently "
                                "re-imported"
                            ),
                            raw_snippet=item.raw_text,
                            table_name=item.table_name,
                        )
                        pending_rejects.append(reject)
                        rejected += 1
                    else:
                        try:
                            payload_json, payload_digest = _serialize_payload(
                                item.payload
                            )
                        except ImportError as exc:
                            reject = ImportReject(
                                reject_id=_reject_id_for(
                                    job_id=job_id,
                                    source_digest=source_digest.digest,
                                    record_index=item.record_index,
                                    reason=str(exc),
                                ),
                                job_id=job_id,
                                source_path=rel,
                                source_digest=source_digest.digest,
                                source_kind=kind.value,
                                record_index=item.record_index,
                                line_number=item.line_number,
                                batch_index=batch_index,
                                reason=str(exc),
                                raw_snippet=item.raw_text,
                                table_name=item.table_name,
                            )
                            pending_rejects.append(reject)
                            rejected += 1
                        else:
                            record = ImportRecord(
                                record_id=_record_id_for(
                                    job_id=job_id,
                                    source_digest=source_digest.digest,
                                    record_index=item.record_index,
                                    payload_digest=payload_digest,
                                ),
                                job_id=job_id,
                                source_path=rel,
                                source_digest=source_digest.digest,
                                source_kind=kind.value,
                                record_index=item.record_index,
                                line_number=item.line_number,
                                batch_index=batch_index,
                                payload_json=payload_json,
                                payload_digest=payload_digest,
                                idempotency_key=idemp.key,
                                table_name=item.table_name,
                                row_id=item.row_id,
                            )
                            pending_records.append(record)
                            accepted += 1

                flush_due = (len(pending_records) + len(pending_rejects)) >= effective_batch
                if flush_due:
                    next_index = batch_local_index + 1
                    cursor = self._commit_batch(
                        job=job,
                        cursor_base=cursor,
                        next_record_index=next_index,
                        batch_index=batch_index,
                        accepted=accepted,
                        rejected=rejected,
                        total_records=total_seen,
                        pending_records=pending_records,
                        pending_rejects=pending_rejects,
                        byte_size=byte_size,
                        effective_batch=effective_batch,
                    )
                    job = self.backend.get_job(job_id) or job
                    pending_records = []
                    pending_rejects = []
                    batch_index += 1
                    batches_this_call += 1
                    if on_batch_commit is not None:
                        on_batch_commit(cursor, job)
                    if (
                        crash_after_batches is not None
                        and batches_this_call >= crash_after_batches
                    ):
                        # Leave in_progress set; do not clear cursor mid-flight.
                        if isinstance(self.backend, MemoryImportBackend):
                            self.backend.fail_mid_batch()
                        raise ImportError(
                            f"simulated interrupt after {batches_this_call} batch(es); "
                            "resume=True to continue"
                        )
                    if max_batches is not None and batches_this_call >= max_batches:
                        # Partial progress — still running, cursor advanced.
                        return self._running_receipt(
                            job=job,
                            cursor=cursor,
                            resumed=resumed,
                            batches_committed=batches_this_call,
                        )

            exhausted = True
            # Final partial batch.
            if pending_records or pending_rejects or (
                cursor.next_record_index == start_index and total_seen == start_index
            ):
                # Empty file still produces a completed job with zero records.
                next_index = total_seen
                cursor = self._commit_batch(
                    job=job,
                    cursor_base=cursor,
                    next_record_index=next_index,
                    batch_index=batch_index,
                    accepted=accepted,
                    rejected=rejected,
                    total_records=total_seen,
                    pending_records=pending_records,
                    pending_rejects=pending_rejects,
                    byte_size=byte_size,
                    effective_batch=effective_batch,
                    final=True,
                )
                batches_this_call += 1 if (pending_records or pending_rejects or total_seen == start_index) else 0
                job = self.backend.get_job(job_id) or job
            elif cursor.next_record_index < total_seen:
                # All items were skipped (already imported) — mark complete.
                cursor = self._commit_batch(
                    job=job,
                    cursor_base=cursor,
                    next_record_index=total_seen,
                    batch_index=batch_index,
                    accepted=accepted,
                    rejected=rejected,
                    total_records=total_seen,
                    pending_records=(),
                    pending_rejects=(),
                    byte_size=byte_size,
                    effective_batch=effective_batch,
                    final=True,
                )
                job = self.backend.get_job(job_id) or job
            else:
                # Cursor already covers the stream; finalize.
                cursor = self._commit_batch(
                    job=job,
                    cursor_base=cursor,
                    next_record_index=total_seen,
                    batch_index=batch_index,
                    accepted=accepted,
                    rejected=rejected,
                    total_records=total_seen,
                    pending_records=(),
                    pending_rejects=(),
                    byte_size=byte_size,
                    effective_batch=effective_batch,
                    final=True,
                )
                job = self.backend.get_job(job_id) or job

        except ImportError:
            raise
        except Exception as exc:
            failed = ImportJob(
                job_id=job.job_id,
                source_path=job.source_path,
                source_kind=job.source_kind,
                source_digest=job.source_digest,
                idempotency_key=job.idempotency_key,
                idempotency_scope=job.idempotency_scope,
                batch_size=job.batch_size,
                status=ImportStatus.FAILED.value,
                byte_size=byte_size,
                total_records=total_seen,
                accepted_count=accepted,
                rejected_count=rejected,
                created_at=job.created_at,
                updated_at=_utc_iso(),
            )
            self.backend.save_job(failed)
            raise ImportError(f"import failed: {exc}") from exc

        if not exhausted:
            return self._running_receipt(
                job=job,
                cursor=cursor,
                resumed=resumed,
                batches_committed=batches_this_call,
            )

        self.backend.clear_in_progress(job_id)
        completed = ImportJob(
            job_id=job.job_id,
            source_path=job.source_path,
            source_kind=job.source_kind,
            source_digest=job.source_digest,
            idempotency_key=job.idempotency_key,
            idempotency_scope=job.idempotency_scope,
            batch_size=job.batch_size,
            status=ImportStatus.COMPLETED.value,
            byte_size=byte_size,
            total_records=total_seen,
            accepted_count=accepted,
            rejected_count=rejected,
            created_at=job.created_at,
            updated_at=_utc_iso(),
        )
        self.backend.save_job(completed)

        receipt = ImportReceipt(
            receipt_id="",
            job_id=job_id,
            source_path=rel,
            source_kind=kind.value,
            source_digest=source_digest.digest,
            idempotency_key=idemp.key,
            status=ImportStatus.COMPLETED.value,
            accepted_count=accepted,
            rejected_count=rejected,
            total_records=total_seen,
            batch_size=effective_batch,
            batches_committed=max(batches_this_call, cursor.batch_index),
            resumed=resumed,
            cursor_next_record_index=cursor.next_record_index,
        )
        self.backend.save_receipt(receipt)
        return receipt

    def _running_receipt(
        self,
        *,
        job: ImportJob,
        cursor: ImportCursor,
        resumed: bool,
        batches_committed: int,
    ) -> ImportReceipt:
        return ImportReceipt(
            receipt_id="",
            job_id=job.job_id,
            source_path=job.source_path,
            source_kind=job.source_kind,
            source_digest=job.source_digest,
            idempotency_key=job.idempotency_key,
            status=ImportStatus.RUNNING.value,
            accepted_count=cursor.accepted_count,
            rejected_count=cursor.rejected_count,
            total_records=job.total_records,
            batch_size=job.batch_size,
            batches_committed=batches_committed,
            resumed=resumed,
            cursor_next_record_index=cursor.next_record_index,
        )

    def _commit_batch(
        self,
        *,
        job: ImportJob,
        cursor_base: ImportCursor,
        next_record_index: int,
        batch_index: int,
        accepted: int,
        rejected: int,
        total_records: int,
        pending_records: Sequence[ImportRecord],
        pending_rejects: Sequence[ImportReject],
        byte_size: int,
        effective_batch: int,
        final: bool = False,
    ) -> ImportCursor:
        self.backend.begin()
        try:
            self.backend.mark_in_progress(job.job_id)
            if pending_records:
                self.backend.append_records(pending_records)
            if pending_rejects:
                self.backend.append_rejects(pending_rejects)
            # Advance batch slot after every successful commit so resume
            # continues at the next bounded window.
            if final:
                advanced_batch = batch_index + (
                    1 if (pending_records or pending_rejects) else 0
                )
            else:
                advanced_batch = batch_index + 1
            new_cursor = ImportCursor(
                job_id=job.job_id,
                source_path=job.source_path,
                source_digest=job.source_digest,
                source_kind=job.source_kind,
                next_record_index=next_record_index,
                batch_index=advanced_batch,
                accepted_count=accepted,
                rejected_count=rejected,
                updated_at=_utc_iso(),
            )
            self.backend.save_cursor(new_cursor)
            updated_job = ImportJob(
                job_id=job.job_id,
                source_path=job.source_path,
                source_kind=job.source_kind,
                source_digest=job.source_digest,
                idempotency_key=job.idempotency_key,
                idempotency_scope=job.idempotency_scope,
                batch_size=effective_batch,
                status=(
                    ImportStatus.COMPLETED.value
                    if final
                    else ImportStatus.RUNNING.value
                ),
                byte_size=byte_size,
                total_records=total_records,
                accepted_count=accepted,
                rejected_count=rejected,
                created_at=job.created_at,
                updated_at=_utc_iso(),
            )
            self.backend.save_job(updated_job)
            self.backend.commit()
            return new_cursor
        except Exception:
            self.backend.rollback()
            raise


def import_file(
    path: str | os.PathLike[str] | Path,
    *,
    backend: ImportBackend | None = None,
    **kwargs: Any,
) -> ImportReceipt:
    """Module-level convenience wrapper around :class:`ArtifactImporter`."""

    return ArtifactImporter(backend=backend).import_path(path, **kwargs)
