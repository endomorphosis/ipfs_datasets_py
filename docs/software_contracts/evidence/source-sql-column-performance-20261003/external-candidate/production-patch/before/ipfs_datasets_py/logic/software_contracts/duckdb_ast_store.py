"""Normalized DuckDB AST / code-evidence catalog schema (DQK-031).

Projects the canonical software-contract :class:`~.ast_ir.ASTRecord` IR into
the control-plane ``asts`` catalog:

* ``source_revisions``, ``source_files``, ``ast_blobs``, ``ast_nodes``
* ``scopes``, ``symbols``, ``imports``, ``references``, ``calls``
* ``effects``, ``interfaces``, ``diagnostics``, ``invalidations``

Source spans and content identities (source CID + AST IR CID) survive
projection as first-class columns.  Parse failures are durable, queryable
facts in ``diagnostics`` (and optional ``invalidations``).

This module deliberately reuses supervisor code-evidence concepts
(blob identity, parse_error, interfaces, symbol/import/call sets, line
spans) without inventing a second AST schema: every structural fact is a
closed projection of the shared AST IR.  Importing this module is inert —
no DuckDB, network, or filesystem I/O.
"""

from __future__ import annotations

import json
import math
import threading
import time
from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable, Final, Protocol, runtime_checkable

from ipfs_datasets_py.logic.software_contracts.ast_ir import (
    ASTIRValidationError,
    ASTRecord,
    ModuleDefinition,
    SourceProvenance,
    SourceSpan,
    SymbolDefinition,
)
from ipfs_datasets_py.logic.software_contracts.schema_versions import (
    AST_IR_SCHEMA_VERSION,
)

# ---------------------------------------------------------------------------
# Schema / interface pins
# ---------------------------------------------------------------------------

DUCKDB_AST_STORE_INTERFACE: Final = "DuckDBASTStore@1"
DUCKDB_AST_STORE_SCHEMA_VERSION: Final = "duckdb-ast-store/v1"
ASTS_CATALOG_NAME: Final = "asts"

# Bound individual lookups and diagnostic/history queries. Large callers can
# narrow queries by revision/blob rather than hydrating the entire catalog.
MAX_STORED_PAYLOAD_BYTES: Final = 16 * 1024 * 1024
MAX_BATCH_PAYLOAD_BYTES: Final = 64 * 1024 * 1024
MAX_QUERY_ROWS: Final = 100_000
# Bound SQL planning and additional argument residency independently of the
# already validated projection payload. One valid oversized row is preserved
# as a singleton, rather than tightening the existing payload contract.
_INSERT_BATCH_ROWS: Final = 128
_INSERT_BATCH_PARAMETER_BYTES: Final = 256 * 1024

# Closed catalog table family declared by the control-plane plan (DQK-G600).
ASTS_CATALOG_TABLES: Final[tuple[str, ...]] = (
    "source_revisions",
    "source_files",
    "ast_blobs",
    "ast_nodes",
    "scopes",
    "symbols",
    "imports",
    "references",
    "calls",
    "effects",
    "interfaces",
    "diagnostics",
    "invalidations",
)

# Span-bearing entity kinds projected into ``ast_nodes`` (closed vocabulary).
AST_NODE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "module",
        "scope",
        "symbol",
        "import",
        "reference",
        "call",
        "effect",
        "unsupported",
        "diagnostic",
        "interface",
    }
)

# Interface kinds projected from symbol facts (aligned with SYMBOL_KINDS).
INTERFACE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "interface",
        "protocol",
        "class",
        "function",
        "method",
        "constructor",
        "module",
        "unknown",
    }
)

# Invalidation reasons (closed).
INVALIDATION_REASONS: Final[frozenset[str]] = frozenset(
    {
        "source_changed",
        "blob_replaced",
        "parse_failure",
        "revision_superseded",
        "path_removed",
        "manual",
        "unknown",
    }
)

# Parse-failure diagnostic codes reused by frontends and the supervisor
# code-evidence plane.  New codes may be added only via explicit schema bump.
PARSE_FAILURE_DIAGNOSTIC_CODE: Final = "ast.parse_failure"
PARSE_FAILURE_NODE_KIND: Final = "diagnostic"


def _is_parse_failure(diagnostic: Any) -> bool:
    return (
        diagnostic.severity == "fatal"
        or diagnostic.code == PARSE_FAILURE_DIAGNOSTIC_CODE
        or diagnostic.code.endswith(
            (".parse_error", ".invalid_encoding", ".resource_limit")
        )
    )


# Supervisor-compatible evidence fields projected alongside the relational
# schema so datasets and accelerate do not invent incompatible AST payloads.
SUPERVISOR_BLOB_SUMMARY_SCHEMA: Final = (
    "ipfs_accelerate_py/agent-supervisor/ast-blob-record@1"
)

# SQL DDL for the asts catalog.  Applied only when an explicit connection is
# provided; unit tests exercise the pure-Python store without DuckDB.
ASTS_CATALOG_DDL: Final[str] = """
CREATE TABLE IF NOT EXISTS source_revisions (
    revision_id VARCHAR PRIMARY KEY,
    repository_id VARCHAR NOT NULL,
    revision VARCHAR NOT NULL,
    repository_tree_cid VARCHAR,
    schema_version VARCHAR NOT NULL,
    created_at DOUBLE NOT NULL
);

CREATE TABLE IF NOT EXISTS source_files (
    file_id VARCHAR PRIMARY KEY,
    revision_id VARCHAR NOT NULL,
    path VARCHAR NOT NULL,
    source_cid VARCHAR NOT NULL,
    language VARCHAR NOT NULL,
    created_at DOUBLE NOT NULL
);

CREATE TABLE IF NOT EXISTS ast_blobs (
    blob_id VARCHAR PRIMARY KEY,
    file_id VARCHAR NOT NULL,
    revision_id VARCHAR NOT NULL,
    source_cid VARCHAR NOT NULL,
    ast_cid VARCHAR NOT NULL,
    language VARCHAR NOT NULL,
    frontend_name VARCHAR NOT NULL,
    frontend_version VARCHAR NOT NULL,
    frontend_toolchain_cid VARCHAR NOT NULL,
    ast_schema_identifier VARCHAR NOT NULL,
    store_schema_version VARCHAR NOT NULL,
    parse_status VARCHAR NOT NULL,
    parse_error VARCHAR NOT NULL,
    payload_json VARCHAR NOT NULL,
    created_at DOUBLE NOT NULL
);

CREATE TABLE IF NOT EXISTS ast_nodes (
    node_id VARCHAR PRIMARY KEY,
    blob_id VARCHAR NOT NULL,
    file_id VARCHAR NOT NULL,
    revision_id VARCHAR NOT NULL,
    node_kind VARCHAR NOT NULL,
    record_id VARCHAR NOT NULL,
    parent_node_id VARCHAR,
    start_byte BIGINT NOT NULL,
    end_byte BIGINT NOT NULL,
    start_line INTEGER NOT NULL,
    start_column INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    end_column INTEGER NOT NULL,
    label VARCHAR NOT NULL,
    payload_json VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS scopes (
    scope_row_id VARCHAR PRIMARY KEY,
    blob_id VARCHAR NOT NULL,
    scope_id VARCHAR NOT NULL,
    kind VARCHAR NOT NULL,
    parent_scope_id VARCHAR,
    owner_symbol_id VARCHAR,
    start_byte BIGINT NOT NULL,
    end_byte BIGINT NOT NULL,
    start_line INTEGER NOT NULL,
    start_column INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    end_column INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS symbols (
    symbol_row_id VARCHAR PRIMARY KEY,
    blob_id VARCHAR NOT NULL,
    symbol_id VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    qualified_name VARCHAR NOT NULL,
    kind VARCHAR NOT NULL,
    scope_id VARCHAR NOT NULL,
    definition_ordinal INTEGER NOT NULL,
    visibility VARCHAR NOT NULL,
    signature_json VARCHAR,
    decorator_names_json VARCHAR NOT NULL,
    flags_json VARCHAR NOT NULL,
    start_byte BIGINT NOT NULL,
    end_byte BIGINT NOT NULL,
    start_line INTEGER NOT NULL,
    start_column INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    end_column INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS imports (
    import_row_id VARCHAR PRIMARY KEY,
    blob_id VARCHAR NOT NULL,
    import_id VARCHAR NOT NULL,
    scope_id VARCHAR NOT NULL,
    module VARCHAR NOT NULL,
    kind VARCHAR NOT NULL,
    imported_name VARCHAR,
    local_name VARCHAR,
    is_type_only BOOLEAN NOT NULL,
    start_byte BIGINT NOT NULL,
    end_byte BIGINT NOT NULL,
    start_line INTEGER NOT NULL,
    start_column INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    end_column INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS "references" (
    reference_row_id VARCHAR PRIMARY KEY,
    blob_id VARCHAR NOT NULL,
    reference_id VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    scope_id VARCHAR NOT NULL,
    context VARCHAR NOT NULL,
    is_qualified BOOLEAN NOT NULL,
    start_byte BIGINT NOT NULL,
    end_byte BIGINT NOT NULL,
    start_line INTEGER NOT NULL,
    start_column INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    end_column INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS calls (
    call_row_id VARCHAR PRIMARY KEY,
    blob_id VARCHAR NOT NULL,
    call_id VARCHAR NOT NULL,
    scope_id VARCHAR NOT NULL,
    callee_name VARCHAR NOT NULL,
    kind VARCHAR NOT NULL,
    argument_count INTEGER NOT NULL,
    callee_reference_id VARCHAR,
    named_argument_names_json VARCHAR NOT NULL,
    is_awaited BOOLEAN NOT NULL,
    start_byte BIGINT NOT NULL,
    end_byte BIGINT NOT NULL,
    start_line INTEGER NOT NULL,
    start_column INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    end_column INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS effects (
    effect_row_id VARCHAR PRIMARY KEY,
    blob_id VARCHAR NOT NULL,
    effect_id VARCHAR NOT NULL,
    scope_id VARCHAR NOT NULL,
    kind VARCHAR NOT NULL,
    operation VARCHAR NOT NULL,
    subject VARCHAR NOT NULL,
    start_byte BIGINT NOT NULL,
    end_byte BIGINT NOT NULL,
    start_line INTEGER NOT NULL,
    start_column INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    end_column INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS interfaces (
    interface_row_id VARCHAR PRIMARY KEY,
    blob_id VARCHAR NOT NULL,
    interface_id VARCHAR NOT NULL,
    symbol_id VARCHAR,
    name VARCHAR NOT NULL,
    qualified_name VARCHAR NOT NULL,
    kind VARCHAR NOT NULL,
    signature_text VARCHAR NOT NULL,
    start_byte BIGINT NOT NULL,
    end_byte BIGINT NOT NULL,
    start_line INTEGER NOT NULL,
    start_column INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    end_column INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS diagnostics (
    diagnostic_row_id VARCHAR PRIMARY KEY,
    blob_id VARCHAR NOT NULL,
    file_id VARCHAR NOT NULL,
    revision_id VARCHAR NOT NULL,
    code VARCHAR NOT NULL,
    severity VARCHAR NOT NULL,
    message VARCHAR NOT NULL,
    is_parse_failure BOOLEAN NOT NULL,
    start_byte BIGINT,
    end_byte BIGINT,
    start_line INTEGER,
    start_column INTEGER,
    end_line INTEGER,
    end_column INTEGER,
    created_at DOUBLE NOT NULL
);

CREATE TABLE IF NOT EXISTS invalidations (
    invalidation_id VARCHAR PRIMARY KEY,
    blob_id VARCHAR,
    file_id VARCHAR,
    revision_id VARCHAR,
    reason VARCHAR NOT NULL,
    actor_id VARCHAR NOT NULL,
    detail VARCHAR NOT NULL,
    created_at DOUBLE NOT NULL
);
""".strip()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class DuckDBASTStoreError(ValueError):
    """Raised when an AST store input, projection, or operation is invalid."""


class DuckDBASTStoreIntegrityError(DuckDBASTStoreError):
    """Raised when a stored projection fails identity rehash."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text(value: object, field_name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise DuckDBASTStoreError(f"{field_name} must be a string")
    if value != value.strip() and value:
        raise DuckDBASTStoreError(
            f"{field_name} must not contain surrounding whitespace"
        )
    if not allow_empty and not value:
        raise DuckDBASTStoreError(f"{field_name} must not be empty")
    if "\x00" in value:
        raise DuckDBASTStoreError(f"{field_name} must not contain NUL")
    return value


def _choice(value: object, field_name: str, allowed: frozenset[str]) -> str:
    result = _text(value, field_name)
    if result not in allowed:
        raise DuckDBASTStoreError(
            f"{field_name} must be one of {sorted(allowed)}, got {result!r}"
        )
    return result


def _json_dumps(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _span_tuple(span: SourceSpan | None) -> tuple[int | None, ...]:
    if span is None:
        return (None, None, None, None, None, None)
    return (
        span.start_byte,
        span.end_byte,
        span.start_line,
        span.start_column,
        span.end_line,
        span.end_column,
    )


def _require_span(span: SourceSpan, field_name: str) -> SourceSpan:
    if type(span) is not SourceSpan:
        raise DuckDBASTStoreError(f"{field_name} must be an exact SourceSpan")
    return span


def _row_id(blob_id: str, *parts: str) -> str:
    return ":".join((blob_id, *parts))


# ---------------------------------------------------------------------------
# Row records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceRevisionRow:
    revision_id: str
    repository_id: str
    revision: str
    repository_tree_cid: str | None
    schema_version: str
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision_id": self.revision_id,
            "repository_id": self.repository_id,
            "revision": self.revision,
            "repository_tree_cid": self.repository_tree_cid,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class SourceFileRow:
    file_id: str
    revision_id: str
    path: str
    source_cid: str
    language: str
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_id": self.file_id,
            "revision_id": self.revision_id,
            "path": self.path,
            "source_cid": self.source_cid,
            "language": self.language,
            "created_at": self.created_at,
        }


class ParseStatus(StrEnum):
    """Parse outcome retained as a durable catalog fact."""

    OK = "ok"
    FAILED = "failed"
    PARTIAL = "partial"


def classify_parse_status(record: ASTRecord) -> str:
    """Classify frontend diagnostics consistently for ingest and storage.

    A failed parse may still retain partial symbols. Their presence never
    overrides explicit parser failures or fatal diagnostics.
    """
    if type(record) is not ASTRecord:
        raise DuckDBASTStoreError("parse classification requires an exact ASTRecord")
    if any(_is_parse_failure(item) for item in record.diagnostics):
        return ParseStatus.FAILED.value
    if any(item.severity == "error" for item in record.diagnostics):
        return ParseStatus.PARTIAL.value
    return ParseStatus.OK.value


@dataclass(frozen=True, slots=True)
class ASTBlobRow:
    blob_id: str
    file_id: str
    revision_id: str
    source_cid: str
    ast_cid: str
    language: str
    frontend_name: str
    frontend_version: str
    frontend_toolchain_cid: str
    ast_schema_identifier: str
    store_schema_version: str
    parse_status: str
    parse_error: str
    payload_json: str
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "blob_id": self.blob_id,
            "file_id": self.file_id,
            "revision_id": self.revision_id,
            "source_cid": self.source_cid,
            "ast_cid": self.ast_cid,
            "language": self.language,
            "frontend_name": self.frontend_name,
            "frontend_version": self.frontend_version,
            "frontend_toolchain_cid": self.frontend_toolchain_cid,
            "ast_schema_identifier": self.ast_schema_identifier,
            "store_schema_version": self.store_schema_version,
            "parse_status": self.parse_status,
            "parse_error": self.parse_error,
            "payload_json": self.payload_json,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class SpanColumns:
    """Half-open UTF-8 span columns shared by projected fact tables."""

    start_byte: int | None
    end_byte: int | None
    start_line: int | None
    start_column: int | None
    end_line: int | None
    end_column: int | None

    @classmethod
    def from_span(cls, span: SourceSpan | None) -> "SpanColumns":
        values = _span_tuple(span)
        return cls(*values)

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_byte": self.start_byte,
            "end_byte": self.end_byte,
            "start_line": self.start_line,
            "start_column": self.start_column,
            "end_line": self.end_line,
            "end_column": self.end_column,
        }

    def matches(self, span: SourceSpan | None) -> bool:
        return _span_tuple(span) == (
            self.start_byte,
            self.end_byte,
            self.start_line,
            self.start_column,
            self.end_line,
            self.end_column,
        )


@dataclass(frozen=True, slots=True)
class ASTNodeRow:
    node_id: str
    blob_id: str
    file_id: str
    revision_id: str
    node_kind: str
    record_id: str
    parent_node_id: str | None
    span: SpanColumns
    label: str
    payload_json: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "blob_id": self.blob_id,
            "file_id": self.file_id,
            "revision_id": self.revision_id,
            "node_kind": self.node_kind,
            "record_id": self.record_id,
            "parent_node_id": self.parent_node_id,
            **self.span.to_dict(),
            "label": self.label,
            "payload_json": self.payload_json,
        }


@dataclass(frozen=True, slots=True)
class ScopeRow:
    scope_row_id: str
    blob_id: str
    scope_id: str
    kind: str
    parent_scope_id: str | None
    owner_symbol_id: str | None
    span: SpanColumns

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope_row_id": self.scope_row_id,
            "blob_id": self.blob_id,
            "scope_id": self.scope_id,
            "kind": self.kind,
            "parent_scope_id": self.parent_scope_id,
            "owner_symbol_id": self.owner_symbol_id,
            **self.span.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class SymbolRow:
    symbol_row_id: str
    blob_id: str
    symbol_id: str
    name: str
    qualified_name: str
    kind: str
    scope_id: str
    definition_ordinal: int
    visibility: str
    signature_json: str | None
    decorator_names_json: str
    flags_json: str
    span: SpanColumns

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol_row_id": self.symbol_row_id,
            "blob_id": self.blob_id,
            "symbol_id": self.symbol_id,
            "name": self.name,
            "qualified_name": self.qualified_name,
            "kind": self.kind,
            "scope_id": self.scope_id,
            "definition_ordinal": self.definition_ordinal,
            "visibility": self.visibility,
            "signature_json": self.signature_json,
            "decorator_names_json": self.decorator_names_json,
            "flags_json": self.flags_json,
            **self.span.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ImportRow:
    import_row_id: str
    blob_id: str
    import_id: str
    scope_id: str
    module: str
    kind: str
    imported_name: str | None
    local_name: str | None
    is_type_only: bool
    span: SpanColumns

    def to_dict(self) -> dict[str, Any]:
        return {
            "import_row_id": self.import_row_id,
            "blob_id": self.blob_id,
            "import_id": self.import_id,
            "scope_id": self.scope_id,
            "module": self.module,
            "kind": self.kind,
            "imported_name": self.imported_name,
            "local_name": self.local_name,
            "is_type_only": self.is_type_only,
            **self.span.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ReferenceRow:
    reference_row_id: str
    blob_id: str
    reference_id: str
    name: str
    scope_id: str
    context: str
    is_qualified: bool
    span: SpanColumns

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_row_id": self.reference_row_id,
            "blob_id": self.blob_id,
            "reference_id": self.reference_id,
            "name": self.name,
            "scope_id": self.scope_id,
            "context": self.context,
            "is_qualified": self.is_qualified,
            **self.span.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class CallRow:
    call_row_id: str
    blob_id: str
    call_id: str
    scope_id: str
    callee_name: str
    kind: str
    argument_count: int
    callee_reference_id: str | None
    named_argument_names_json: str
    is_awaited: bool
    span: SpanColumns

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_row_id": self.call_row_id,
            "blob_id": self.blob_id,
            "call_id": self.call_id,
            "scope_id": self.scope_id,
            "callee_name": self.callee_name,
            "kind": self.kind,
            "argument_count": self.argument_count,
            "callee_reference_id": self.callee_reference_id,
            "named_argument_names_json": self.named_argument_names_json,
            "is_awaited": self.is_awaited,
            **self.span.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class EffectRow:
    effect_row_id: str
    blob_id: str
    effect_id: str
    scope_id: str
    kind: str
    operation: str
    subject: str
    span: SpanColumns

    def to_dict(self) -> dict[str, Any]:
        return {
            "effect_row_id": self.effect_row_id,
            "blob_id": self.blob_id,
            "effect_id": self.effect_id,
            "scope_id": self.scope_id,
            "kind": self.kind,
            "operation": self.operation,
            "subject": self.subject,
            **self.span.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class InterfaceRow:
    interface_row_id: str
    blob_id: str
    interface_id: str
    symbol_id: str | None
    name: str
    qualified_name: str
    kind: str
    signature_text: str
    span: SpanColumns

    def to_dict(self) -> dict[str, Any]:
        return {
            "interface_row_id": self.interface_row_id,
            "blob_id": self.blob_id,
            "interface_id": self.interface_id,
            "symbol_id": self.symbol_id,
            "name": self.name,
            "qualified_name": self.qualified_name,
            "kind": self.kind,
            "signature_text": self.signature_text,
            **self.span.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class DiagnosticRow:
    diagnostic_row_id: str
    blob_id: str
    file_id: str
    revision_id: str
    code: str
    severity: str
    message: str
    is_parse_failure: bool
    span: SpanColumns
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnostic_row_id": self.diagnostic_row_id,
            "blob_id": self.blob_id,
            "file_id": self.file_id,
            "revision_id": self.revision_id,
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "is_parse_failure": self.is_parse_failure,
            **self.span.to_dict(),
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class InvalidationRow:
    invalidation_id: str
    blob_id: str | None
    file_id: str | None
    revision_id: str | None
    reason: str
    actor_id: str
    detail: str
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "invalidation_id": self.invalidation_id,
            "blob_id": self.blob_id,
            "file_id": self.file_id,
            "revision_id": self.revision_id,
            "reason": self.reason,
            "actor_id": self.actor_id,
            "detail": self.detail,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Full projection bundle
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ASTCatalogProjection:
    """Closed relational projection of one AST blob / parse result."""

    source_revision: SourceRevisionRow
    source_file: SourceFileRow
    ast_blob: ASTBlobRow
    nodes: tuple[ASTNodeRow, ...]
    scopes: tuple[ScopeRow, ...]
    symbols: tuple[SymbolRow, ...]
    imports: tuple[ImportRow, ...]
    references: tuple[ReferenceRow, ...]
    calls: tuple[CallRow, ...]
    effects: tuple[EffectRow, ...]
    interfaces: tuple[InterfaceRow, ...]
    diagnostics: tuple[DiagnosticRow, ...]
    invalidations: tuple[InvalidationRow, ...] = ()

    @property
    def blob_id(self) -> str:
        return self.ast_blob.blob_id

    @property
    def ast_cid(self) -> str:
        return self.ast_blob.ast_cid

    @property
    def source_cid(self) -> str:
        return self.ast_blob.source_cid

    def table_row_counts(self) -> dict[str, int]:
        return {
            "source_revisions": 1,
            "source_files": 1,
            "ast_blobs": 1,
            "ast_nodes": len(self.nodes),
            "scopes": len(self.scopes),
            "symbols": len(self.symbols),
            "imports": len(self.imports),
            "references": len(self.references),
            "calls": len(self.calls),
            "effects": len(self.effects),
            "interfaces": len(self.interfaces),
            "diagnostics": len(self.diagnostics),
            "invalidations": len(self.invalidations),
        }

    def to_supervisor_blob_summary(self) -> dict[str, Any]:
        """Project supervisor-compatible code-evidence blob fields.

        Field names align with accelerate
        :class:`ASTBlobRecord` so datasets and the supervisor share one
        evidence vocabulary without a second AST schema.
        """

        symbol_lines: dict[str, list[int]] = {}
        for symbol in self.symbols:
            if symbol.span.start_line is not None and symbol.span.end_line is not None:
                symbol_lines[symbol.qualified_name] = [
                    int(symbol.span.start_line),
                    int(symbol.span.end_line),
                ]
        imports = []
        for item in self.imports:
            if item.imported_name:
                imports.append(
                    f"from {item.module} import {item.imported_name}"
                    + (
                        f" as {item.local_name}"
                        if item.local_name and item.local_name != item.imported_name
                        else ""
                    )
                )
            else:
                imports.append(
                    f"import {item.module}"
                    + (f" as {item.local_name}" if item.local_name else "")
                )
        calls = [f"{item.scope_id}->{item.callee_name}" for item in self.calls]
        interfaces = [
            item.signature_text or item.qualified_name for item in self.interfaces
        ]
        return {
            "schema": SUPERVISOR_BLOB_SUMMARY_SCHEMA,
            "blob_identity": self.ast_blob.source_cid,
            "source_sha256": self.ast_blob.source_cid,
            "language": self.ast_blob.language,
            "qualified_symbols": sorted({item.qualified_name for item in self.symbols}),
            "imports": sorted(set(imports)),
            "calls": sorted(set(calls)),
            "interfaces": sorted(set(interfaces)),
            "symbol_lines": {key: symbol_lines[key] for key in sorted(symbol_lines)},
            "parse_error": self.ast_blob.parse_error,
            "ast_cid": self.ast_cid,
            "ast_schema": self.ast_blob.ast_schema_identifier,
        }

    def verify_identity(self, record: ASTRecord | None = None) -> str:
        """Fail closed when stored identity drifts from the AST IR CID."""

        if self.ast_blob.ast_schema_identifier != AST_IR_SCHEMA_VERSION.identifier:
            raise DuckDBASTStoreIntegrityError(
                "projected AST schema identifier is not the shared AST IR schema"
            )
        if record is not None:
            if type(record) is not ASTRecord:
                raise DuckDBASTStoreError("record must be an exact ASTRecord")
            if record.cid != self.ast_cid:
                raise DuckDBASTStoreIntegrityError(
                    "projected ast_cid does not match ASTRecord.cid"
                )
            if record.provenance.source_cid != self.source_cid:
                raise DuckDBASTStoreIntegrityError(
                    "projected source_cid does not match provenance.source_cid"
                )
        return self.ast_cid


# ---------------------------------------------------------------------------
# Projection builders
# ---------------------------------------------------------------------------


def _revision_id(provenance: SourceProvenance) -> str:
    return f"rev:{provenance.repository_id}:{provenance.revision}"


def _file_id(provenance: SourceProvenance) -> str:
    return f"file:{provenance.repository_id}:{provenance.revision}:{provenance.path}"


def _blob_id(ast_cid: str) -> str:
    return f"blob:{ast_cid}"


def _signature_text(symbol: SymbolDefinition) -> str:
    if symbol.signature is None:
        return symbol.qualified_name
    parameters = ", ".join(
        f"{parameter.name}:{parameter.kind}"
        for parameter in symbol.signature.parameters
    )
    prefix = "async " if symbol.signature.is_async else ""
    returns = (
        f" -> {symbol.signature.return_annotation}"
        if symbol.signature.return_annotation
        else ""
    )
    return f"{prefix}{symbol.kind} {symbol.qualified_name}({parameters}){returns}"


def _project_interfaces(
    *,
    blob_id: str,
    symbols: Sequence[SymbolDefinition],
    module: ModuleDefinition,
) -> tuple[InterfaceRow, ...]:
    rows: list[InterfaceRow] = []
    for symbol in symbols:
        is_interface_kind = symbol.kind in {"interface", "protocol"}
        is_public_callable = (
            symbol.kind in {"function", "method", "constructor", "class"}
            and symbol.visibility in {"public", "unspecified"}
            and (symbol.signature is not None or symbol.kind == "class")
        )
        if not (is_interface_kind or is_public_callable):
            continue
        kind = symbol.kind if symbol.kind in INTERFACE_KINDS else "unknown"
        signature = _signature_text(symbol)
        interface_id = f"interface:{symbol.symbol_id}"
        rows.append(
            InterfaceRow(
                interface_row_id=_row_id(blob_id, "interface", symbol.symbol_id),
                blob_id=blob_id,
                interface_id=interface_id,
                symbol_id=symbol.symbol_id,
                name=symbol.name,
                qualified_name=symbol.qualified_name,
                kind=kind,
                signature_text=signature,
                span=SpanColumns.from_span(symbol.span),
            )
        )
    # Module export surface is also an interface fact for code-evidence.
    if module.export_names:
        rows.append(
            InterfaceRow(
                interface_row_id=_row_id(blob_id, "interface", "module-exports"),
                blob_id=blob_id,
                interface_id=f"interface:module:{module.module_id}",
                symbol_id=None,
                name=module.name,
                qualified_name=module.name,
                kind="module",
                signature_text=(
                    f"module {module.name} exports "
                    f"({','.join(module.export_names)})"
                ),
                span=SpanColumns.from_span(module.span),
            )
        )
    return tuple(rows)


def _node(
    *,
    blob_id: str,
    file_id: str,
    revision_id: str,
    node_kind: str,
    record_id: str,
    label: str,
    span: SourceSpan | None,
    parent_node_id: str | None = None,
    payload: Mapping[str, Any] | None = None,
) -> ASTNodeRow:
    if node_kind not in AST_NODE_KINDS:
        raise DuckDBASTStoreError(f"unknown node kind: {node_kind}")
    span_columns = SpanColumns.from_span(span)
    if span is not None and any(
        value is None for value in span_columns.to_dict().values()
    ):
        raise DuckDBASTStoreError("span columns must be fully populated")
    if span is None:
        # Nodes without spans use zeroed half-open sentinel at origin.
        span_columns = SpanColumns(0, 0, 1, 0, 1, 0)
    return ASTNodeRow(
        node_id=_row_id(blob_id, "node", node_kind, record_id),
        blob_id=blob_id,
        file_id=file_id,
        revision_id=revision_id,
        node_kind=node_kind,
        record_id=record_id,
        parent_node_id=parent_node_id,
        span=span_columns,
        label=label,
        payload_json=_json_dumps(dict(payload or {})),
    )


def project_ast_record(
    record: ASTRecord,
    *,
    created_at: float | None = None,
) -> ASTCatalogProjection:
    """Project a validated :class:`ASTRecord` into closed catalog rows.

    Identity and source spans are preserved verbatim: ``ast_cid`` equals
    ``record.cid`` and every span column mirrors the IR :class:`SourceSpan`.
    """

    if type(record) is not ASTRecord:
        raise DuckDBASTStoreError("project_ast_record requires an exact ASTRecord")
    try:
        # Re-validate closed IR contract so the store never accepts a partial
        # mapping that happens to look like an ASTRecord.
        if record.schema_version != AST_IR_SCHEMA_VERSION:
            raise DuckDBASTStoreError(
                "ASTRecord schema_version is not the shared AST IR schema"
            )
    except ASTIRValidationError as error:
        raise DuckDBASTStoreError(str(error)) from error

    now = time.time() if created_at is None else float(created_at)
    provenance = record.provenance
    frontend = record.frontend
    module = record.module
    revision_id = _revision_id(provenance)
    file_id = _file_id(provenance)
    ast_cid = record.cid
    blob_id = _blob_id(ast_cid)

    source_revision = SourceRevisionRow(
        revision_id=revision_id,
        repository_id=provenance.repository_id,
        revision=provenance.revision,
        repository_tree_cid=provenance.repository_tree_cid,
        schema_version=DUCKDB_AST_STORE_SCHEMA_VERSION,
        created_at=now,
    )
    source_file = SourceFileRow(
        file_id=file_id,
        revision_id=revision_id,
        path=provenance.path,
        source_cid=provenance.source_cid,
        language=frontend.language,
        created_at=now,
    )
    payload_json = _json_dumps(record.to_dict())
    failures = tuple(item for item in record.diagnostics if _is_parse_failure(item))
    incomplete = tuple(item for item in record.diagnostics if item.severity == "error")
    ast_blob = ASTBlobRow(
        blob_id=blob_id,
        file_id=file_id,
        revision_id=revision_id,
        source_cid=provenance.source_cid,
        ast_cid=ast_cid,
        language=frontend.language,
        frontend_name=frontend.frontend_name,
        frontend_version=frontend.frontend_version,
        frontend_toolchain_cid=frontend.toolchain_cid,
        ast_schema_identifier=AST_IR_SCHEMA_VERSION.identifier,
        store_schema_version=DUCKDB_AST_STORE_SCHEMA_VERSION,
        parse_status=classify_parse_status(record),
        parse_error="; ".join(item.message for item in failures or incomplete),
        payload_json=payload_json,
        created_at=now,
    )

    scope_rows = tuple(
        ScopeRow(
            scope_row_id=_row_id(blob_id, "scope", item.scope_id),
            blob_id=blob_id,
            scope_id=item.scope_id,
            kind=item.kind,
            parent_scope_id=item.parent_scope_id,
            owner_symbol_id=item.owner_symbol_id,
            span=SpanColumns.from_span(item.span),
        )
        for item in record.scopes
    )
    symbol_rows = tuple(
        SymbolRow(
            symbol_row_id=_row_id(blob_id, "symbol", item.symbol_id),
            blob_id=blob_id,
            symbol_id=item.symbol_id,
            name=item.name,
            qualified_name=item.qualified_name,
            kind=item.kind,
            scope_id=item.scope_id,
            definition_ordinal=item.definition_ordinal,
            visibility=item.visibility,
            signature_json=(
                None
                if item.signature is None
                else _json_dumps(item.signature.to_dict())
            ),
            decorator_names_json=_json_dumps(list(item.decorator_names)),
            flags_json=_json_dumps(list(item.flags)),
            span=SpanColumns.from_span(item.span),
        )
        for item in record.symbols
    )
    import_rows = tuple(
        ImportRow(
            import_row_id=_row_id(blob_id, "import", item.import_id),
            blob_id=blob_id,
            import_id=item.import_id,
            scope_id=item.scope_id,
            module=item.module,
            kind=item.kind,
            imported_name=item.imported_name,
            local_name=item.local_name,
            is_type_only=item.is_type_only,
            span=SpanColumns.from_span(item.span),
        )
        for item in record.imports
    )
    reference_rows = tuple(
        ReferenceRow(
            reference_row_id=_row_id(blob_id, "reference", item.reference_id),
            blob_id=blob_id,
            reference_id=item.reference_id,
            name=item.name,
            scope_id=item.scope_id,
            context=item.context,
            is_qualified=item.is_qualified,
            span=SpanColumns.from_span(item.span),
        )
        for item in record.references
    )
    call_rows = tuple(
        CallRow(
            call_row_id=_row_id(blob_id, "call", item.call_id),
            blob_id=blob_id,
            call_id=item.call_id,
            scope_id=item.scope_id,
            callee_name=item.callee_name,
            kind=item.kind,
            argument_count=item.argument_count,
            callee_reference_id=item.callee_reference_id,
            named_argument_names_json=_json_dumps(list(item.named_argument_names)),
            is_awaited=item.is_awaited,
            span=SpanColumns.from_span(item.span),
        )
        for item in record.calls
    )
    effect_rows = tuple(
        EffectRow(
            effect_row_id=_row_id(blob_id, "effect", item.effect_id),
            blob_id=blob_id,
            effect_id=item.effect_id,
            scope_id=item.scope_id,
            kind=item.kind,
            operation=item.operation,
            subject=item.subject,
            span=SpanColumns.from_span(item.span),
        )
        for item in record.effects
    )
    interface_rows = _project_interfaces(
        blob_id=blob_id, symbols=record.symbols, module=module
    )

    diagnostic_rows = tuple(
        DiagnosticRow(
            diagnostic_row_id=_row_id(blob_id, "diagnostic", f"{index}:{item.code}"),
            blob_id=blob_id,
            file_id=file_id,
            revision_id=revision_id,
            code=item.code,
            severity=item.severity,
            message=item.message,
            is_parse_failure=_is_parse_failure(item),
            span=SpanColumns.from_span(item.span),
            created_at=now,
        )
        for index, item in enumerate(record.diagnostics)
    )

    module_node_id = _row_id(blob_id, "node", "module", module.module_id)
    nodes: list[ASTNodeRow] = [
        _node(
            blob_id=blob_id,
            file_id=file_id,
            revision_id=revision_id,
            node_kind="module",
            record_id=module.module_id,
            label=module.name,
            span=module.span,
            payload=module.to_dict(),
        )
    ]
    scope_node_ids = {
        item.scope_id: _row_id(blob_id, "node", "scope", item.scope_id)
        for item in record.scopes
    }
    for item in record.scopes:
        parent = (
            None
            if item.parent_scope_id is None
            else scope_node_ids.get(item.parent_scope_id, module_node_id)
        )
        nodes.append(
            _node(
                blob_id=blob_id,
                file_id=file_id,
                revision_id=revision_id,
                node_kind="scope",
                record_id=item.scope_id,
                label=item.kind,
                span=item.span,
                parent_node_id=parent,
                payload=item.to_dict(),
            )
        )
    for item in record.symbols:
        nodes.append(
            _node(
                blob_id=blob_id,
                file_id=file_id,
                revision_id=revision_id,
                node_kind="symbol",
                record_id=item.symbol_id,
                label=item.qualified_name,
                span=item.span,
                parent_node_id=scope_node_ids.get(item.scope_id),
                payload=item.to_dict(),
            )
        )
    for item in record.imports:
        nodes.append(
            _node(
                blob_id=blob_id,
                file_id=file_id,
                revision_id=revision_id,
                node_kind="import",
                record_id=item.import_id,
                label=item.module,
                span=item.span,
                parent_node_id=scope_node_ids.get(item.scope_id),
                payload=item.to_dict(),
            )
        )
    for item in record.references:
        nodes.append(
            _node(
                blob_id=blob_id,
                file_id=file_id,
                revision_id=revision_id,
                node_kind="reference",
                record_id=item.reference_id,
                label=item.name,
                span=item.span,
                parent_node_id=scope_node_ids.get(item.scope_id),
                payload=item.to_dict(),
            )
        )
    for item in record.calls:
        nodes.append(
            _node(
                blob_id=blob_id,
                file_id=file_id,
                revision_id=revision_id,
                node_kind="call",
                record_id=item.call_id,
                label=item.callee_name,
                span=item.span,
                parent_node_id=scope_node_ids.get(item.scope_id),
                payload=item.to_dict(),
            )
        )
    for item in record.effects:
        nodes.append(
            _node(
                blob_id=blob_id,
                file_id=file_id,
                revision_id=revision_id,
                node_kind="effect",
                record_id=item.effect_id,
                label=item.kind,
                span=item.span,
                parent_node_id=scope_node_ids.get(item.scope_id),
                payload=item.to_dict(),
            )
        )
    for item in record.unsupported:
        nodes.append(
            _node(
                blob_id=blob_id,
                file_id=file_id,
                revision_id=revision_id,
                node_kind="unsupported",
                record_id=item.unsupported_id,
                label=item.construct,
                span=item.span,
                payload=item.to_dict(),
            )
        )
    for item in interface_rows:
        nodes.append(
            _node(
                blob_id=blob_id,
                file_id=file_id,
                revision_id=revision_id,
                node_kind="interface",
                record_id=item.interface_id,
                label=item.qualified_name,
                span=SourceSpan(
                    start_byte=int(item.span.start_byte or 0),
                    end_byte=int(item.span.end_byte or 0),
                    start_line=int(item.span.start_line or 1),
                    start_column=int(item.span.start_column or 0),
                    end_line=int(item.span.end_line or 1),
                    end_column=int(item.span.end_column or 0),
                ),
                payload=item.to_dict(),
            )
        )

    projection = ASTCatalogProjection(
        source_revision=source_revision,
        source_file=source_file,
        ast_blob=ast_blob,
        nodes=tuple(nodes),
        scopes=scope_rows,
        symbols=symbol_rows,
        imports=import_rows,
        references=reference_rows,
        calls=call_rows,
        effects=effect_rows,
        interfaces=interface_rows,
        diagnostics=diagnostic_rows,
    )
    projection.verify_identity(record)
    return projection


def project_parse_failure(
    *,
    provenance: SourceProvenance,
    language: str,
    message: str,
    code: str = PARSE_FAILURE_DIAGNOSTIC_CODE,
    severity: str = "error",
    frontend_name: str = "unknown",
    frontend_version: str = "unknown",
    frontend_toolchain_cid: str | None = None,
    span: SourceSpan | None = None,
    created_at: float | None = None,
    actor_id: str = "parser",
) -> ASTCatalogProjection:
    """Project a parse failure as durable queryable diagnostic facts.

    The resulting blob has empty structural collections, ``parse_status=
    failed``, and at least one diagnostic with ``is_parse_failure=True``.
    An invalidation row records the failure for incremental consumers.
    """

    if type(provenance) is not SourceProvenance:
        raise DuckDBASTStoreError("provenance must be an exact SourceProvenance")
    message_text = _text(message, "message")
    language_text = _text(language, "language")
    severity_text = _choice(
        severity, "severity", frozenset({"info", "warning", "error", "fatal"})
    )
    code_text = _text(code, "code")
    now = time.time() if created_at is None else float(created_at)
    revision_id = _revision_id(provenance)
    file_id = _file_id(provenance)
    # Identity is source-bound: failed parses have no AST IR CID, so the
    # blob identity is derived from source + path + failure code.
    failure_payload = {
        "schema": DUCKDB_AST_STORE_SCHEMA_VERSION,
        "kind": "parse_failure",
        "source_cid": provenance.source_cid,
        "path": provenance.path,
        "repository_id": provenance.repository_id,
        "revision": provenance.revision,
        "code": code_text,
        "message": message_text,
        "language": language_text,
    }
    # Stable synthetic identity without requiring structured CID tooling at
    # projection time: hash canonical JSON via the shared content module when
    # available, otherwise use a deterministic fallback digest.
    try:
        from ipfs_datasets_py.logic.software_contracts.content import (
            cid_for_structured,
        )

        failure_cid = cid_for_structured(failure_payload)
    except Exception:
        import hashlib

        failure_cid = (
            "sha256:"
            + hashlib.sha256(_json_dumps(failure_payload).encode("utf-8")).hexdigest()
        )
    blob_id = _blob_id(failure_cid)
    toolchain = frontend_toolchain_cid or provenance.source_cid

    source_revision = SourceRevisionRow(
        revision_id=revision_id,
        repository_id=provenance.repository_id,
        revision=provenance.revision,
        repository_tree_cid=provenance.repository_tree_cid,
        schema_version=DUCKDB_AST_STORE_SCHEMA_VERSION,
        created_at=now,
    )
    source_file = SourceFileRow(
        file_id=file_id,
        revision_id=revision_id,
        path=provenance.path,
        source_cid=provenance.source_cid,
        language=language_text,
        created_at=now,
    )
    ast_blob = ASTBlobRow(
        blob_id=blob_id,
        file_id=file_id,
        revision_id=revision_id,
        source_cid=provenance.source_cid,
        ast_cid=failure_cid,
        language=language_text,
        frontend_name=_text(frontend_name, "frontend_name"),
        frontend_version=_text(frontend_version, "frontend_version"),
        frontend_toolchain_cid=_text(toolchain, "frontend_toolchain_cid"),
        ast_schema_identifier=AST_IR_SCHEMA_VERSION.identifier,
        store_schema_version=DUCKDB_AST_STORE_SCHEMA_VERSION,
        parse_status=ParseStatus.FAILED.value,
        parse_error=message_text,
        payload_json=_json_dumps(failure_payload),
        created_at=now,
    )
    diagnostic = DiagnosticRow(
        diagnostic_row_id=_row_id(blob_id, "diagnostic", "parse_failure"),
        blob_id=blob_id,
        file_id=file_id,
        revision_id=revision_id,
        code=code_text,
        severity=severity_text,
        message=message_text,
        is_parse_failure=True,
        span=SpanColumns.from_span(span),
        created_at=now,
    )
    nodes = (
        _node(
            blob_id=blob_id,
            file_id=file_id,
            revision_id=revision_id,
            node_kind=PARSE_FAILURE_NODE_KIND,
            record_id="parse_failure",
            label=code_text,
            span=span,
            payload={"code": code_text, "message": message_text},
        ),
    )
    invalidation = InvalidationRow(
        invalidation_id=_row_id(blob_id, "invalidation", "parse_failure"),
        blob_id=blob_id,
        file_id=file_id,
        revision_id=revision_id,
        reason="parse_failure",
        actor_id=_text(actor_id, "actor_id"),
        detail=message_text,
        created_at=now,
    )
    return ASTCatalogProjection(
        source_revision=source_revision,
        source_file=source_file,
        ast_blob=ast_blob,
        nodes=nodes,
        scopes=(),
        symbols=(),
        imports=(),
        references=(),
        calls=(),
        effects=(),
        interfaces=(),
        diagnostics=(diagnostic,),
        invalidations=(invalidation,),
    )


def spans_survive_projection(
    record: ASTRecord, projection: ASTCatalogProjection
) -> bool:
    """Return True when every IR span is present unchanged in the projection."""

    by_scope = {item.scope_id: item for item in projection.scopes}
    for scope in record.scopes:
        row = by_scope.get(scope.scope_id)
        if row is None or not row.span.matches(scope.span):
            return False
    by_symbol = {item.symbol_id: item for item in projection.symbols}
    for symbol in record.symbols:
        row = by_symbol.get(symbol.symbol_id)
        if row is None or not row.span.matches(symbol.span):
            return False
    by_import = {item.import_id: item for item in projection.imports}
    for item in record.imports:
        row = by_import.get(item.import_id)
        if row is None or not row.span.matches(item.span):
            return False
    by_ref = {item.reference_id: item for item in projection.references}
    for item in record.references:
        row = by_ref.get(item.reference_id)
        if row is None or not row.span.matches(item.span):
            return False
    by_call = {item.call_id: item for item in projection.calls}
    for item in record.calls:
        row = by_call.get(item.call_id)
        if row is None or not row.span.matches(item.span):
            return False
    by_effect = {item.effect_id: item for item in projection.effects}
    for item in record.effects:
        row = by_effect.get(item.effect_id)
        if row is None or not row.span.matches(item.span):
            return False
    module_nodes = [node for node in projection.nodes if node.node_kind == "module"]
    if not module_nodes or not module_nodes[0].span.matches(record.module.span):
        return False
    return True


# ---------------------------------------------------------------------------
# Store protocol and implementation
# ---------------------------------------------------------------------------


@runtime_checkable
class DuckDBASTStoreProtocol(Protocol):
    """Protocol surface for DuckDBASTStore@1."""

    @property
    def interface(self) -> str: ...

    @property
    def schema_version(self) -> str: ...

    def catalog_tables(self) -> tuple[str, ...]: ...

    def put(
        self, record: ASTRecord, *, created_at: float | None = None
    ) -> ASTCatalogProjection: ...

    def put_projection(
        self, projection: ASTCatalogProjection
    ) -> ASTCatalogProjection: ...

    def apply_batch(
        self,
        projections: Sequence[ASTCatalogProjection],
        invalidations: Sequence[InvalidationRow] = (),
        *,
        before_apply: Callable[[Any], None] | None = None,
        before_commit: Callable[[Any], None] | None = None,
    ) -> tuple[tuple[ASTCatalogProjection, ...], tuple[InvalidationRow, ...]]: ...

    def get(self, blob_id: str) -> ASTCatalogProjection | None: ...

    def get_by_ast_cid(self, ast_cid: str) -> ASTCatalogProjection | None: ...

    def query_parse_failures(
        self, *, revision_id: str | None = None, path: str | None = None
    ) -> tuple[DiagnosticRow, ...]: ...

    def invalidate(
        self,
        *,
        blob_id: str | None = None,
        file_id: str | None = None,
        revision_id: str | None = None,
        reason: str = "manual",
        actor_id: str = "system",
        detail: str = "",
    ) -> InvalidationRow: ...


class DuckDBASTStore:
    """AST catalog with optional durable, transactional DuckDB authority.

    Without a connection, retain the process-local store. With a connection,
    exact reads reconstruct and verify only the requested projection; startup
    never hydrates the catalog. Mutations own a transaction on the supplied
    connection, which must not already be in a caller-owned transaction.
    Invalidation removes active projections and retains its audit rows.
    """

    def __init__(self, *, connection: Any | None = None) -> None:
        self._connection = connection
        self._lock = threading.RLock()
        self._by_blob: OrderedDict[str, ASTCatalogProjection] = OrderedDict()
        self._by_ast_cid: dict[str, str] = {}
        self._by_file: dict[str, str] = {}
        self._invalidations: list[InvalidationRow] = []
        self._stats = {
            "puts": 0,
            "parse_failures": 0,
            "invalidations": 0,
            "lookups": 0,
            "misses": 0,
        }
        if connection is not None:
            self.install_schema(connection)

    @property
    def interface(self) -> str:
        return DUCKDB_AST_STORE_INTERFACE

    @property
    def schema_version(self) -> str:
        return DUCKDB_AST_STORE_SCHEMA_VERSION

    @staticmethod
    def install_schema(connection: Any) -> None:
        if connection is None:
            raise DuckDBASTStoreError("connection is required to install schema")
        for statement in ASTS_CATALOG_DDL.split(";"):
            body = statement.strip()
            if body:
                connection.execute(body)

    def catalog_tables(self) -> tuple[str, ...]:
        return ASTS_CATALOG_TABLES

    @contextmanager
    def _transaction(self):
        connection = self._connection
        if connection is None:
            yield
            return
        # BEGIN stays outside the try: a nested transaction rejection must not
        # roll back a transaction owned by the caller.
        connection.execute("BEGIN TRANSACTION")
        try:
            yield
            connection.execute("COMMIT")
        except BaseException:
            try:
                connection.execute("ROLLBACK")
            except Exception:
                pass
            raise

    def _rows(
        self,
        table: str,
        where: str = "",
        parameters: Sequence[Any] = (),
        *,
        columns: str = "*",
    ) -> list[dict[str, Any]]:
        assert self._connection is not None
        if table not in ASTS_CATALOG_TABLES:
            raise DuckDBASTStoreError("unknown catalog table")
        cursor = self._connection.execute(
            f'SELECT {columns} FROM "{table}"'
            + (" WHERE " + where if where else "")
            + f" LIMIT {MAX_QUERY_ROWS + 1}",
            list(parameters),
        )
        names = [column[0] for column in cursor.description]
        raw = cursor.fetchall()
        if len(raw) > MAX_QUERY_ROWS:
            raise DuckDBASTStoreError(
                "query row bound exceeded; narrow by revision or blob"
            )
        return [dict(zip(names, row)) for row in raw]

    @staticmethod
    def _one(rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
        if len(rows) != 1:
            raise DuckDBASTStoreIntegrityError(
                f"expected one {label} row, found {len(rows)}"
            )
        return rows[0]

    @staticmethod
    def _rebuild(
        blob: Mapping[str, Any],
        revision: Mapping[str, Any],
        diagnostics: Sequence[Mapping[str, Any]],
        invalidations: Sequence[Mapping[str, Any]],
    ) -> ASTCatalogProjection:
        """Reproject canonical payload bytes instead of trusting stored facts."""
        try:
            payload = blob["payload_json"]
            if (
                type(payload) is not str
                or len(payload.encode("utf-8")) > MAX_STORED_PAYLOAD_BYTES
            ):
                raise ValueError("stored AST payload exceeds byte bound")
            timestamp = blob["created_at"]
            if type(timestamp) not in (int, float) or not math.isfinite(timestamp):
                raise ValueError("invalid projection timestamp")
            if (
                blob["parse_status"] == ParseStatus.FAILED.value
                and json.loads(payload).get("kind") == "parse_failure"
            ):
                data = json.loads(payload)
                diagnostic = DuckDBASTStore._one(
                    list(diagnostics), "parse-failure diagnostic"
                )
                invalidation = DuckDBASTStore._one(
                    list(invalidations), "parse-failure invalidation"
                )
                spans = {
                    name: diagnostic[name] for name in SpanColumns.__dataclass_fields__
                }
                span = (
                    None
                    if all(value is None for value in spans.values())
                    else SourceSpan(**spans)
                )
                return project_parse_failure(
                    provenance=SourceProvenance(
                        source_cid=data["source_cid"],
                        path=data["path"],
                        repository_id=data["repository_id"],
                        revision=data["revision"],
                        repository_tree_cid=revision["repository_tree_cid"],
                    ),
                    language=data["language"],
                    message=data["message"],
                    code=data["code"],
                    severity=diagnostic["severity"],
                    span=span,
                    frontend_name=blob["frontend_name"],
                    frontend_version=blob["frontend_version"],
                    frontend_toolchain_cid=blob["frontend_toolchain_cid"],
                    actor_id=invalidation["actor_id"],
                    created_at=timestamp,
                )
            if blob["parse_status"] not in {item.value for item in ParseStatus}:
                raise ValueError("unsupported persisted parse status")
            return project_ast_record(
                ASTRecord.from_json(payload), created_at=timestamp
            )
        except (
            AttributeError,
            KeyError,
            TypeError,
            ValueError,
            RecursionError,
        ) as error:
            raise DuckDBASTStoreIntegrityError(
                f"invalid stored AST projection: {error}"
            ) from error

    @classmethod
    def _validate_projection(
        cls, projection: ASTCatalogProjection, *, canonical: bool = True
    ) -> None:
        if type(projection) is not ASTCatalogProjection:
            raise DuckDBASTStoreError(
                "put_projection requires an exact ASTCatalogProjection"
            )
        if projection.ast_blob.store_schema_version != DUCKDB_AST_STORE_SCHEMA_VERSION:
            raise DuckDBASTStoreError(
                "unsupported AST store schema version on projection"
            )
        if (
            projection.ast_blob.ast_schema_identifier
            != AST_IR_SCHEMA_VERSION.identifier
        ):
            raise DuckDBASTStoreError(
                "projection must bind the shared software-contract AST IR schema"
            )
        if not canonical:
            # Preserve the existing hermetic row-fixture surface. Durable
            # publication always requires the complete canonical AST payload.
            return
        expected = cls._rebuild(
            projection.ast_blob.to_dict(),
            projection.source_revision.to_dict(),
            [row.to_dict() for row in projection.diagnostics],
            [row.to_dict() for row in projection.invalidations],
        )
        if expected != projection:
            raise DuckDBASTStoreIntegrityError(
                "projection rows differ from canonical AST payload"
            )

    def _load(self, blob_id: str) -> ASTCatalogProjection | None:
        blobs = self._rows("ast_blobs", "blob_id=?", [blob_id])
        if not blobs:
            return None
        blob = self._one(blobs, "AST blob")
        revision = self._one(
            self._rows("source_revisions", "revision_id=?", [blob["revision_id"]]),
            "revision",
        )
        source_file = self._one(
            self._rows("source_files", "file_id=?", [blob["file_id"]]), "source file"
        )
        diagnostics = self._rows("diagnostics", "blob_id=?", [blob_id])
        intrinsic = (
            self._rows(
                "invalidations",
                "invalidation_id=?",
                [_row_id(blob_id, "invalidation", "parse_failure")],
            )
            if blob["parse_status"] == ParseStatus.FAILED.value
            else []
        )
        expected = self._rebuild(blob, revision, diagnostics, intrinsic)
        if (
            expected.ast_blob.to_dict() != blob
            or expected.source_file.to_dict() != source_file
        ):
            raise DuckDBASTStoreIntegrityError(
                "stored AST/source identity or payload mismatch"
            )
        # The revision is shared across files, whose acquisition timestamps may
        # differ. Its identity fields must still match every projection.
        if {
            k: v
            for k, v in expected.source_revision.to_dict().items()
            if k != "created_at"
        } != {k: v for k, v in revision.items() if k != "created_at"}:
            raise DuckDBASTStoreIntegrityError("stored revision identity mismatch")
        if type(revision["created_at"]) not in (int, float) or not math.isfinite(
            revision["created_at"]
        ):
            raise DuckDBASTStoreIntegrityError("invalid revision timestamp")
        for table, attribute in (
            ("ast_nodes", "nodes"),
            ("scopes", "scopes"),
            ("symbols", "symbols"),
            ("imports", "imports"),
            ("references", "references"),
            ("calls", "calls"),
            ("effects", "effects"),
            ("interfaces", "interfaces"),
            ("diagnostics", "diagnostics"),
            ("invalidations", "invalidations"),
        ):
            actual = (
                diagnostics
                if table == "diagnostics"
                else (
                    intrinsic
                    if table == "invalidations"
                    else self._rows(table, "blob_id=?", [blob_id])
                )
            )
            wanted = [row.to_dict() for row in getattr(expected, attribute)]
            if sorted(map(_json_dumps, actual)) != sorted(map(_json_dumps, wanted)):
                raise DuckDBASTStoreIntegrityError(
                    f"stored {table} rows differ from canonical AST payload"
                )
        return expected

    def stats(self) -> dict[str, int]:
        with self._lock:
            if self._connection is None:
                size, invalidations = len(self._by_blob), len(self._invalidations)
            else:
                size, invalidations = self._connection.execute(
                    "SELECT (SELECT count(*) FROM ast_blobs), (SELECT count(*) FROM invalidations)"
                ).fetchone()
            return {**self._stats, "size": size, "invalidation_count": invalidations}

    def put(
        self, record: ASTRecord, *, created_at: float | None = None
    ) -> ASTCatalogProjection:
        return self.put_projection(project_ast_record(record, created_at=created_at))

    def put_parse_failure(
        self,
        *,
        provenance: SourceProvenance,
        language: str,
        message: str,
        code: str = PARSE_FAILURE_DIAGNOSTIC_CODE,
        severity: str = "error",
        frontend_name: str = "unknown",
        frontend_version: str = "unknown",
        frontend_toolchain_cid: str | None = None,
        span: SourceSpan | None = None,
        created_at: float | None = None,
        actor_id: str = "parser",
    ) -> ASTCatalogProjection:
        projection = project_parse_failure(
            provenance=provenance,
            language=language,
            message=message,
            code=code,
            severity=severity,
            frontend_name=frontend_name,
            frontend_version=frontend_version,
            frontend_toolchain_cid=frontend_toolchain_cid,
            span=span,
            created_at=created_at,
            actor_id=actor_id,
        )
        result = self.put_projection(projection)
        with self._lock:
            self._stats["parse_failures"] += 1
        return result

    def put_projection(self, projection: ASTCatalogProjection) -> ASTCatalogProjection:
        return self.apply_batch((projection,), ())[0][0]

    def apply_batch(
        self,
        projections: Sequence[ASTCatalogProjection],
        invalidations: Sequence[InvalidationRow] = (),
        *,
        before_apply: Callable[[Any], None] | None = None,
        before_commit: Callable[[Any], None] | None = None,
    ) -> tuple[tuple[ASTCatalogProjection, ...], tuple[InvalidationRow, ...]]:
        """Publish a bounded batch and invalidations atomically.

        Supplied invalidations run after projections, matching revision ingest.
        The returned invalidations include only the supplied rows; implicit
        replacement and parse-failure audit rows remain queryable in the store.
        No memory or operation counters publish before SQL commit succeeds.
        The optional trusted-owner callbacks share this lock and transaction:
        they must not start another transaction or publish external side effects.
        An exception from either callback rolls the complete batch back. They
        permit a control-domain compare-and-swap to commit with its AST rows.
        """
        if any(hook is not None and not callable(hook)
               for hook in (before_apply, before_commit)):
            raise DuckDBASTStoreError("transaction hooks must be callable")
        if len(projections) + len(invalidations) > MAX_QUERY_ROWS:
            raise DuckDBASTStoreError("publication batch exceeds row bound")
        projections, invalidations = tuple(projections), tuple(invalidations)
        payload_bytes = 0
        for projection in projections:
            self._validate_projection(
                projection, canonical=self._connection is not None
            )
            payload_bytes += len(projection.ast_blob.payload_json.encode("utf-8"))
            if payload_bytes > MAX_BATCH_PAYLOAD_BYTES:
                raise DuckDBASTStoreError(
                    "publication batch exceeds payload byte bound"
                )
        for row in invalidations:
            self._validate_invalidation(row)
        with self._lock:
            snapshot = (
                self._by_blob.copy(),
                self._by_ast_cid.copy(),
                self._by_file.copy(),
                list(self._invalidations),
            )
            invalidation_count = 0
            try:
                with self._transaction():
                    if before_apply is not None:
                        before_apply(self._connection)
                    for projection in projections:
                        if self._connection is None:
                            previous = self._by_file.get(projection.source_file.file_id)
                        else:
                            found = self._rows(
                                "ast_blobs",
                                "file_id=?",
                                [projection.source_file.file_id],
                                columns="blob_id",
                            )
                            previous = (
                                self._one(found, "active file blob")["blob_id"]
                                if found
                                else None
                            )
                        if previous is not None and previous != projection.blob_id:
                            row = self._make_invalidation(
                                blob_id=previous,
                                file_id=projection.source_file.file_id,
                                revision_id=projection.source_revision.revision_id,
                                reason="blob_replaced",
                                actor_id="duckdb-ast-store",
                                detail=f"replaced by {projection.blob_id}",
                            )
                            self._apply_invalidation(row)
                            invalidation_count += 1
                        if self._connection is None:
                            self._by_blob[projection.blob_id] = projection
                            self._by_ast_cid[projection.ast_cid] = projection.blob_id
                            self._by_file[projection.source_file.file_id] = (
                                projection.blob_id
                            )
                            self._invalidations.extend(projection.invalidations)
                        else:
                            self._delete_projection_rows(
                                "blob_id=?", [projection.blob_id]
                            )
                            self._persist_projection(projection)
                        invalidation_count += len(projection.invalidations)
                    for row in invalidations:
                        self._apply_invalidation(row)
                        invalidation_count += 1
                    if before_commit is not None:
                        before_commit(self._connection)
            except BaseException:
                self._by_blob, self._by_ast_cid, self._by_file, self._invalidations = (
                    snapshot
                )
                raise
            self._stats["puts"] += len(projections)
            self._stats["invalidations"] += invalidation_count
            return projections, invalidations

    def _lookup(self, column: str, key: str) -> ASTCatalogProjection | None:
        with self._lock:
            self._stats["lookups"] += 1
            if self._connection is None:
                blob_id = (
                    key
                    if column == "blob_id"
                    else (
                        self._by_ast_cid if column == "ast_cid" else self._by_file
                    ).get(key)
                )
                found = self._by_blob.get(blob_id)
            else:
                with self._transaction():
                    rows = self._rows(
                        "ast_blobs", f"{column}=?", [key], columns="blob_id"
                    )
                    found = (
                        self._load(self._one(rows, "lookup blob")["blob_id"])
                        if rows
                        else None
                    )
            if found is None:
                self._stats["misses"] += 1
            return found

    def get(self, blob_id: str) -> ASTCatalogProjection | None:
        return self._lookup("blob_id", _text(blob_id, "blob_id"))

    def get_by_ast_cid(self, ast_cid: str) -> ASTCatalogProjection | None:
        return self._lookup("ast_cid", _text(ast_cid, "ast_cid"))

    def get_by_file_id(self, file_id: str) -> ASTCatalogProjection | None:
        return self._lookup("file_id", _text(file_id, "file_id"))

    def _diagnostic_projections(
        self, *, blob_id=None, revision_id=None, path=None, failures=False
    ):
        if self._connection is None:
            return tuple(self._by_blob.values())
        conditions, parameters = [], []
        for name, value in (("blob_id", blob_id), ("revision_id", revision_id)):
            if value is not None:
                conditions.append(name + "=?")
                parameters.append(_text(value, name))
        if path is not None:
            conditions.append(
                "file_id IN (SELECT file_id FROM source_files WHERE path=?)"
            )
            parameters.append(_text(path, "path"))
        if failures:
            conditions.append(
                "(parse_status='failed' OR blob_id IN (SELECT blob_id FROM diagnostics WHERE is_parse_failure))"
            )
        else:
            conditions.append("blob_id IN (SELECT blob_id FROM diagnostics)")
        rows = self._rows(
            "ast_blobs", " AND ".join(conditions), parameters, columns="blob_id"
        )
        return (self._load(row["blob_id"]) for row in rows)

    def query_diagnostics(
        self,
        *,
        blob_id: str | None = None,
        revision_id: str | None = None,
        parse_failures_only: bool = False,
    ) -> tuple[DiagnosticRow, ...]:
        with self._lock, self._transaction():
            rows = []
            for projection in self._diagnostic_projections(
                blob_id=blob_id, revision_id=revision_id, failures=parse_failures_only
            ):
                if blob_id is not None and projection.blob_id != blob_id:
                    continue
                if (
                    revision_id is not None
                    and projection.source_revision.revision_id != revision_id
                ):
                    continue
                rows.extend(
                    item
                    for item in projection.diagnostics
                    if not parse_failures_only or item.is_parse_failure
                )
            return tuple(rows)

    def query_parse_failures(
        self, *, revision_id: str | None = None, path: str | None = None
    ) -> tuple[DiagnosticRow, ...]:
        with self._lock, self._transaction():
            rows = []
            for projection in self._diagnostic_projections(
                revision_id=revision_id, path=path, failures=True
            ):
                if (
                    revision_id is not None
                    and projection.source_revision.revision_id != revision_id
                ):
                    continue
                if path is not None and projection.source_file.path != path:
                    continue
                failures = [
                    item for item in projection.diagnostics if item.is_parse_failure
                ]
                if projection.ast_blob.parse_status == ParseStatus.FAILED.value:
                    failures = failures or list(projection.diagnostics)
                rows.extend(failures)
            return tuple(rows)

    @staticmethod
    def _validate_invalidation(row: InvalidationRow) -> None:
        if type(row) is not InvalidationRow:
            raise DuckDBASTStoreError("invalidation requires an exact InvalidationRow")
        _text(row.invalidation_id, "invalidation_id")
        _choice(row.reason, "reason", INVALIDATION_REASONS)
        _text(row.actor_id, "actor_id")
        _text(row.detail, "detail", allow_empty=True)
        for name in ("blob_id", "file_id", "revision_id"):
            value = getattr(row, name)
            if value is not None:
                _text(value, name)
        if type(row.created_at) not in (int, float) or not math.isfinite(
            row.created_at
        ):
            raise DuckDBASTStoreError("invalid invalidation timestamp")

    def list_invalidations(
        self, *, blob_id: str | None = None
    ) -> tuple[InvalidationRow, ...]:
        with self._lock:
            if self._connection is None:
                return tuple(
                    row
                    for row in self._invalidations
                    if blob_id is None or row.blob_id == blob_id
                )
            values = self._rows(
                "invalidations",
                "blob_id=?" if blob_id is not None else "",
                [_text(blob_id, "blob_id")] if blob_id is not None else [],
            )
            try:
                rows = tuple(InvalidationRow(**value) for value in values)
                for row in rows:
                    self._validate_invalidation(row)
            except (TypeError, ValueError) as error:
                raise DuckDBASTStoreIntegrityError(
                    f"invalid stored invalidation: {error}"
                ) from error
            return tuple(
                sorted(rows, key=lambda row: (row.created_at, row.invalidation_id))
            )

    @staticmethod
    def _make_invalidation(
        *,
        blob_id=None,
        file_id=None,
        revision_id=None,
        reason="manual",
        actor_id="system",
        detail="",
        created_at=None,
    ) -> InvalidationRow:
        now = time.time() if created_at is None else float(created_at)
        row = InvalidationRow(
            f"inv:{blob_id or file_id or revision_id or 'global'}:{reason}:{int(now * 1_000_000)}",
            blob_id,
            file_id,
            revision_id,
            reason,
            actor_id,
            detail,
            now,
        )
        DuckDBASTStore._validate_invalidation(row)
        return row

    def invalidate(
        self,
        *,
        blob_id: str | None = None,
        file_id: str | None = None,
        revision_id: str | None = None,
        reason: str = "manual",
        actor_id: str = "system",
        detail: str = "",
        created_at: float | None = None,
    ) -> InvalidationRow:
        row = self._make_invalidation(
            blob_id=blob_id,
            file_id=file_id,
            revision_id=revision_id,
            reason=reason,
            actor_id=actor_id,
            detail=detail,
            created_at=created_at,
        )
        self.apply_batch((), (row,))
        return row

    def _apply_invalidation(self, row: InvalidationRow) -> None:
        # Most specific selector wins: additional file/revision fields are
        # provenance for a blob invalidation, not an OR over unrelated blobs.
        selector = next(
            (
                name
                for name in ("blob_id", "file_id", "revision_id")
                if getattr(row, name) is not None
            ),
            None,
        )
        if self._connection is not None:
            self._persist_invalidation(row)
            if selector is not None:
                self._delete_projection_rows(selector + "=?", [getattr(row, selector)])
            return
        for key, projection in tuple(self._by_blob.items()):
            value = (
                projection.blob_id
                if selector == "blob_id"
                else (
                    projection.source_file.file_id
                    if selector == "file_id"
                    else projection.source_revision.revision_id
                )
            )
            if selector is not None and value == getattr(row, selector):
                del self._by_blob[key]
                self._by_ast_cid.pop(projection.ast_cid, None)
                if self._by_file.get(projection.source_file.file_id) == key:
                    self._by_file.pop(projection.source_file.file_id, None)
        self._invalidations.append(row)

    def _delete_projection_rows(self, where: str, parameters: Sequence[Any]) -> None:
        for table in (
            "ast_nodes",
            "scopes",
            "symbols",
            "imports",
            "references",
            "calls",
            "effects",
            "interfaces",
            "diagnostics",
        ):
            self._connection.execute(
                f'DELETE FROM "{table}" WHERE blob_id IN (SELECT blob_id FROM ast_blobs WHERE {where})',
                list(parameters),
            )
        self._connection.execute(
            "DELETE FROM ast_blobs WHERE " + where, list(parameters)
        )

    def clear(self) -> None:
        with self._lock, self._transaction():
            if self._connection is not None:
                for table in ASTS_CATALOG_TABLES:
                    self._connection.execute(f'DELETE FROM "{table}"')
            self._by_blob.clear()
            self._by_ast_cid.clear()
            self._by_file.clear()
            self._invalidations.clear()

    # -- DuckDB persistence (caller holds the transaction) ------------------

    def _insert_rows(self, statement: str, rows: Iterable[Sequence[Any]]) -> None:
        """Stream canonical fact rows into bounded parameterized INSERTs.

        Statements and column order are the fixed literals below. Only VALUES
        placeholders are repeated; source-derived text is always a parameter.
        The caller's existing transaction owns every chunk, rollback and hooks.
        """
        prefix, _, placeholders = statement.partition("VALUES")
        width = placeholders.count("?")
        batch: list[Any] = []
        count = size = 0

        def flush() -> None:
            self._connection.execute(
                prefix + "VALUES " + ",".join([placeholders.strip()] * count), batch
            )

        for row in rows:
            if len(row) != width:
                raise DuckDBASTStoreError("fact row differs from INSERT column layout")
            row_bytes = sum(len(value.encode("utf-8")) if type(value) is str else 8
                            for value in row)
            if count and (count >= _INSERT_BATCH_ROWS
                          or size + row_bytes > _INSERT_BATCH_PARAMETER_BYTES):
                flush()
                batch, count, size = [], 0, 0
            batch.extend(row)
            count += 1
            size += row_bytes
        if count:
            flush()

    def _persist_projection(self, projection: ASTCatalogProjection) -> None:
        connection = self._connection
        if connection is None:
            return
        # apply_batch has cleared every row owned by this blob in the same
        # transaction. Plain INSERT avoids DuckDB conflict-update buffering
        # per tiny row; shared source identities and audit rows still upsert.
        rev = projection.source_revision
        existing = self._rows("source_revisions", "revision_id=?", [rev.revision_id])
        if existing:
            previous = self._one(existing, "revision")
            if {
                key: value for key, value in previous.items() if key != "created_at"
            } != {
                key: value
                for key, value in rev.to_dict().items()
                if key != "created_at"
            }:
                raise DuckDBASTStoreIntegrityError(
                    "revision identity conflicts with persisted source"
                )
        connection.execute(
            """
            INSERT OR REPLACE INTO source_revisions VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                rev.revision_id,
                rev.repository_id,
                rev.revision,
                rev.repository_tree_cid,
                rev.schema_version,
                rev.created_at,
            ],
        )
        file_row = projection.source_file
        connection.execute(
            """
            INSERT OR REPLACE INTO source_files VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                file_row.file_id,
                file_row.revision_id,
                file_row.path,
                file_row.source_cid,
                file_row.language,
                file_row.created_at,
            ],
        )
        blob = projection.ast_blob
        connection.execute(
            """
            INSERT INTO ast_blobs VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [
                blob.blob_id,
                blob.file_id,
                blob.revision_id,
                blob.source_cid,
                blob.ast_cid,
                blob.language,
                blob.frontend_name,
                blob.frontend_version,
                blob.frontend_toolchain_cid,
                blob.ast_schema_identifier,
                blob.store_schema_version,
                blob.parse_status,
                blob.parse_error,
                blob.payload_json,
                blob.created_at,
            ],
        )
        self._insert_rows(
            """
            INSERT INTO ast_nodes VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                [
                    node.node_id,
                    node.blob_id,
                    node.file_id,
                    node.revision_id,
                    node.node_kind,
                    node.record_id,
                    node.parent_node_id,
                    node.span.start_byte,
                    node.span.end_byte,
                    node.span.start_line,
                    node.span.start_column,
                    node.span.end_line,
                    node.span.end_column,
                    node.label,
                    node.payload_json,
                ]
                for node in projection.nodes
            ),
        )
        self._insert_rows(
            """
            INSERT INTO scopes VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                [
                    item.scope_row_id,
                    item.blob_id,
                    item.scope_id,
                    item.kind,
                    item.parent_scope_id,
                    item.owner_symbol_id,
                    item.span.start_byte,
                    item.span.end_byte,
                    item.span.start_line,
                    item.span.start_column,
                    item.span.end_line,
                    item.span.end_column,
                ]
                for item in projection.scopes
            ),
        )
        self._insert_rows(
            """
            INSERT INTO symbols VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                [
                    item.symbol_row_id,
                    item.blob_id,
                    item.symbol_id,
                    item.name,
                    item.qualified_name,
                    item.kind,
                    item.scope_id,
                    item.definition_ordinal,
                    item.visibility,
                    item.signature_json,
                    item.decorator_names_json,
                    item.flags_json,
                    item.span.start_byte,
                    item.span.end_byte,
                    item.span.start_line,
                    item.span.start_column,
                    item.span.end_line,
                    item.span.end_column,
                ]
                for item in projection.symbols
            ),
        )
        self._insert_rows(
            """
            INSERT INTO imports VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                [
                    item.import_row_id,
                    item.blob_id,
                    item.import_id,
                    item.scope_id,
                    item.module,
                    item.kind,
                    item.imported_name,
                    item.local_name,
                    item.is_type_only,
                    item.span.start_byte,
                    item.span.end_byte,
                    item.span.start_line,
                    item.span.start_column,
                    item.span.end_line,
                    item.span.end_column,
                ]
                for item in projection.imports
            ),
        )
        self._insert_rows(
            """
            INSERT INTO "references" VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                [
                    item.reference_row_id,
                    item.blob_id,
                    item.reference_id,
                    item.name,
                    item.scope_id,
                    item.context,
                    item.is_qualified,
                    item.span.start_byte,
                    item.span.end_byte,
                    item.span.start_line,
                    item.span.start_column,
                    item.span.end_line,
                    item.span.end_column,
                ]
                for item in projection.references
            ),
        )
        self._insert_rows(
            """
            INSERT INTO calls VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                [
                    item.call_row_id,
                    item.blob_id,
                    item.call_id,
                    item.scope_id,
                    item.callee_name,
                    item.kind,
                    item.argument_count,
                    item.callee_reference_id,
                    item.named_argument_names_json,
                    item.is_awaited,
                    item.span.start_byte,
                    item.span.end_byte,
                    item.span.start_line,
                    item.span.start_column,
                    item.span.end_line,
                    item.span.end_column,
                ]
                for item in projection.calls
            ),
        )
        self._insert_rows(
            """
            INSERT INTO effects VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                [
                    item.effect_row_id,
                    item.blob_id,
                    item.effect_id,
                    item.scope_id,
                    item.kind,
                    item.operation,
                    item.subject,
                    item.span.start_byte,
                    item.span.end_byte,
                    item.span.start_line,
                    item.span.start_column,
                    item.span.end_line,
                    item.span.end_column,
                ]
                for item in projection.effects
            ),
        )
        self._insert_rows(
            """
            INSERT INTO interfaces VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                [
                    item.interface_row_id,
                    item.blob_id,
                    item.interface_id,
                    item.symbol_id,
                    item.name,
                    item.qualified_name,
                    item.kind,
                    item.signature_text,
                    item.span.start_byte,
                    item.span.end_byte,
                    item.span.start_line,
                    item.span.start_column,
                    item.span.end_line,
                    item.span.end_column,
                ]
                for item in projection.interfaces
            ),
        )
        self._insert_rows(
            """
            INSERT INTO diagnostics VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                [
                    item.diagnostic_row_id,
                    item.blob_id,
                    item.file_id,
                    item.revision_id,
                    item.code,
                    item.severity,
                    item.message,
                    item.is_parse_failure,
                    item.span.start_byte,
                    item.span.end_byte,
                    item.span.start_line,
                    item.span.start_column,
                    item.span.end_line,
                    item.span.end_column,
                    item.created_at,
                ]
                for item in projection.diagnostics
            ),
        )
        for item in projection.invalidations:
            self._persist_invalidation(item)

    def _persist_invalidation(self, item: InvalidationRow) -> None:
        connection = self._connection
        if connection is None:
            return
        connection.execute(
            """
            INSERT OR REPLACE INTO invalidations VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [
                item.invalidation_id,
                item.blob_id,
                item.file_id,
                item.revision_id,
                item.reason,
                item.actor_id,
                item.detail,
                item.created_at,
            ],
        )


def build_duckdb_ast_store(*, connection: Any | None = None) -> DuckDBASTStore:
    """Construct a :class:`DuckDBASTStore` with standard defaults."""

    return DuckDBASTStore(connection=connection)


def ast_store_schema_descriptor() -> dict[str, Any]:
    """Return a deterministic machine-readable catalog/schema statement."""

    return {
        "interface": DUCKDB_AST_STORE_INTERFACE,
        "store_schema_version": DUCKDB_AST_STORE_SCHEMA_VERSION,
        "catalog": ASTS_CATALOG_NAME,
        "tables": list(ASTS_CATALOG_TABLES),
        "ast_ir_schema": AST_IR_SCHEMA_VERSION.to_dict(),
        "supervisor_blob_summary_schema": SUPERVISOR_BLOB_SUMMARY_SCHEMA,
        "node_kinds": sorted(AST_NODE_KINDS),
        "interface_kinds": sorted(INTERFACE_KINDS),
        "invalidation_reasons": sorted(INVALIDATION_REASONS),
        "guarantees": {
            "ast_ir_identity_survives_projection": True,
            "source_spans_survive_projection": True,
            "parse_failures_are_queryable": True,
            "no_second_ast_schema": True,
            "import_inert": True,
        },
    }


__all__ = [
    "ASTBlobRow",
    "ASTCatalogProjection",
    "ASTNodeRow",
    "ASTS_CATALOG_DDL",
    "ASTS_CATALOG_NAME",
    "ASTS_CATALOG_TABLES",
    "AST_NODE_KINDS",
    "CallRow",
    "DUCKDB_AST_STORE_INTERFACE",
    "DUCKDB_AST_STORE_SCHEMA_VERSION",
    "DiagnosticRow",
    "DuckDBASTStore",
    "DuckDBASTStoreError",
    "DuckDBASTStoreIntegrityError",
    "DuckDBASTStoreProtocol",
    "EffectRow",
    "INTERFACE_KINDS",
    "INVALIDATION_REASONS",
    "ImportRow",
    "InterfaceRow",
    "InvalidationRow",
    "PARSE_FAILURE_DIAGNOSTIC_CODE",
    "ParseStatus",
    "ReferenceRow",
    "SUPERVISOR_BLOB_SUMMARY_SCHEMA",
    "ScopeRow",
    "SourceFileRow",
    "SourceRevisionRow",
    "SpanColumns",
    "SymbolRow",
    "ast_store_schema_descriptor",
    "build_duckdb_ast_store",
    "classify_parse_status",
    "project_ast_record",
    "project_parse_failure",
    "spans_survive_projection",
]
