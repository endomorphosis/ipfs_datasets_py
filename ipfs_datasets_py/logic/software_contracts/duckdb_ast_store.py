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
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Protocol, runtime_checkable

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
                    + (f" as {item.local_name}" if item.local_name and item.local_name != item.imported_name else "")
                )
            else:
                imports.append(
                    f"import {item.module}"
                    + (f" as {item.local_name}" if item.local_name else "")
                )
        calls = [
            f"{item.scope_id}->{item.callee_name}" for item in self.calls
        ]
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
            "symbol_lines": {
                key: symbol_lines[key] for key in sorted(symbol_lines)
            },
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
    if span is not None and any(value is None for value in span_columns.to_dict().values()):
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
        parse_status=ParseStatus.OK.value,
        parse_error="",
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
            diagnostic_row_id=_row_id(
                blob_id, "diagnostic", f"{index}:{item.code}"
            ),
            blob_id=blob_id,
            file_id=file_id,
            revision_id=revision_id,
            code=item.code,
            severity=item.severity,
            message=item.message,
            is_parse_failure=False,
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
    module_nodes = [
        node for node in projection.nodes if node.node_kind == "module"
    ]
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

    def put(self, record: ASTRecord, *, created_at: float | None = None) -> ASTCatalogProjection: ...

    def put_projection(self, projection: ASTCatalogProjection) -> ASTCatalogProjection: ...

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
    """In-process AST catalog store with optional DuckDB schema install.

    Entries are keyed by blob identity (``blob:<ast_cid>``).  Lookups and
    diagnostics queries are process-local; when a DuckDB connection is
    provided the catalog DDL is installed for durable backends.
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
        """Apply asts-catalog DDL on a DuckDB-like connection."""

        if connection is None:
            raise DuckDBASTStoreError("connection is required to install schema")
        for statement in ASTS_CATALOG_DDL.split(";"):
            body = statement.strip()
            if body:
                connection.execute(body)

    def catalog_tables(self) -> tuple[str, ...]:
        return ASTS_CATALOG_TABLES

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                **self._stats,
                "size": len(self._by_blob),
                "invalidation_count": len(self._invalidations),
            }

    def put(
        self, record: ASTRecord, *, created_at: float | None = None
    ) -> ASTCatalogProjection:
        projection = project_ast_record(record, created_at=created_at)
        return self.put_projection(projection)

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
        with self._lock:
            self._stats["parse_failures"] += 1
        return self.put_projection(projection)

    def put_projection(
        self, projection: ASTCatalogProjection
    ) -> ASTCatalogProjection:
        if type(projection) is not ASTCatalogProjection:
            raise DuckDBASTStoreError(
                "put_projection requires an exact ASTCatalogProjection"
            )
        if projection.ast_blob.store_schema_version != DUCKDB_AST_STORE_SCHEMA_VERSION:
            raise DuckDBASTStoreError(
                "unsupported AST store schema version on projection"
            )
        if projection.ast_blob.ast_schema_identifier != AST_IR_SCHEMA_VERSION.identifier:
            raise DuckDBASTStoreError(
                "projection must bind the shared software-contract AST IR schema"
            )
        # Reject unknown catalog families — datasets/supervisor must not invent
        # incompatible table sets.
        counts = projection.table_row_counts()
        if set(counts) != set(ASTS_CATALOG_TABLES):
            raise DuckDBASTStoreError(
                "projection table family is not the closed asts catalog"
            )
        with self._lock:
            previous = self._by_file.get(projection.source_file.file_id)
            if previous is not None and previous != projection.blob_id:
                # Supersede prior blob for the same revision path.
                self._invalidate_locked(
                    blob_id=previous,
                    file_id=projection.source_file.file_id,
                    revision_id=projection.source_revision.revision_id,
                    reason="blob_replaced",
                    actor_id="duckdb-ast-store",
                    detail=f"replaced by {projection.blob_id}",
                )
            self._by_blob[projection.blob_id] = projection
            self._by_ast_cid[projection.ast_cid] = projection.blob_id
            self._by_file[projection.source_file.file_id] = projection.blob_id
            for item in projection.invalidations:
                self._invalidations.append(item)
                self._stats["invalidations"] += 1
            self._stats["puts"] += 1
            if self._connection is not None:
                self._persist_projection(projection)
            return projection

    def get(self, blob_id: str) -> ASTCatalogProjection | None:
        key = _text(blob_id, "blob_id")
        with self._lock:
            self._stats["lookups"] += 1
            found = self._by_blob.get(key)
            if found is None:
                self._stats["misses"] += 1
            return found

    def get_by_ast_cid(self, ast_cid: str) -> ASTCatalogProjection | None:
        key = _text(ast_cid, "ast_cid")
        with self._lock:
            self._stats["lookups"] += 1
            blob_id = self._by_ast_cid.get(key)
            if blob_id is None:
                self._stats["misses"] += 1
                return None
            return self._by_blob.get(blob_id)

    def get_by_file_id(self, file_id: str) -> ASTCatalogProjection | None:
        key = _text(file_id, "file_id")
        with self._lock:
            self._stats["lookups"] += 1
            blob_id = self._by_file.get(key)
            if blob_id is None:
                self._stats["misses"] += 1
                return None
            return self._by_blob.get(blob_id)

    def query_diagnostics(
        self,
        *,
        blob_id: str | None = None,
        revision_id: str | None = None,
        parse_failures_only: bool = False,
    ) -> tuple[DiagnosticRow, ...]:
        with self._lock:
            rows: list[DiagnosticRow] = []
            for projection in self._by_blob.values():
                if blob_id is not None and projection.blob_id != blob_id:
                    continue
                if (
                    revision_id is not None
                    and projection.source_revision.revision_id != revision_id
                ):
                    continue
                for diagnostic in projection.diagnostics:
                    if parse_failures_only and not diagnostic.is_parse_failure:
                        continue
                    rows.append(diagnostic)
            return tuple(rows)

    def query_parse_failures(
        self, *, revision_id: str | None = None, path: str | None = None
    ) -> tuple[DiagnosticRow, ...]:
        with self._lock:
            rows: list[DiagnosticRow] = []
            for projection in self._by_blob.values():
                if projection.ast_blob.parse_status != ParseStatus.FAILED.value:
                    # Still surface diagnostics marked as parse failures.
                    failures = [
                        item
                        for item in projection.diagnostics
                        if item.is_parse_failure
                    ]
                    if not failures:
                        continue
                else:
                    failures = [
                        item
                        for item in projection.diagnostics
                        if item.is_parse_failure
                    ] or list(projection.diagnostics)
                if (
                    revision_id is not None
                    and projection.source_revision.revision_id != revision_id
                ):
                    continue
                if path is not None and projection.source_file.path != path:
                    continue
                rows.extend(failures)
            return tuple(rows)

    def list_invalidations(
        self, *, blob_id: str | None = None
    ) -> tuple[InvalidationRow, ...]:
        with self._lock:
            if blob_id is None:
                return tuple(self._invalidations)
            return tuple(
                item
                for item in self._invalidations
                if item.blob_id == blob_id
            )

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
        with self._lock:
            return self._invalidate_locked(
                blob_id=blob_id,
                file_id=file_id,
                revision_id=revision_id,
                reason=reason,
                actor_id=actor_id,
                detail=detail,
                created_at=created_at,
            )

    def _invalidate_locked(
        self,
        *,
        blob_id: str | None,
        file_id: str | None,
        revision_id: str | None,
        reason: str,
        actor_id: str,
        detail: str,
        created_at: float | None = None,
    ) -> InvalidationRow:
        reason_text = _choice(reason, "reason", INVALIDATION_REASONS)
        now = time.time() if created_at is None else float(created_at)
        invalidation_id = (
            f"inv:{blob_id or file_id or revision_id or 'global'}:"
            f"{reason_text}:{int(now * 1_000_000)}"
        )
        row = InvalidationRow(
            invalidation_id=invalidation_id,
            blob_id=blob_id,
            file_id=file_id,
            revision_id=revision_id,
            reason=reason_text,
            actor_id=_text(actor_id, "actor_id"),
            detail=_text(detail, "detail", allow_empty=True),
            created_at=now,
        )
        if blob_id is not None and blob_id in self._by_blob:
            projection = self._by_blob.pop(blob_id)
            self._by_ast_cid.pop(projection.ast_cid, None)
            mapped = self._by_file.get(projection.source_file.file_id)
            if mapped == blob_id:
                self._by_file.pop(projection.source_file.file_id, None)
        self._invalidations.append(row)
        self._stats["invalidations"] += 1
        if self._connection is not None:
            self._persist_invalidation(row)
        return row

    def clear(self) -> None:
        with self._lock:
            self._by_blob.clear()
            self._by_ast_cid.clear()
            self._by_file.clear()
            self._invalidations.clear()

    # -- optional DuckDB persistence ----------------------------------------

    def _persist_projection(self, projection: ASTCatalogProjection) -> None:
        connection = self._connection
        if connection is None:
            return
        rev = projection.source_revision
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
            INSERT OR REPLACE INTO ast_blobs VALUES (
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
        for node in projection.nodes:
            connection.execute(
                """
                INSERT OR REPLACE INTO ast_nodes VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
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
                ],
            )
        for item in projection.scopes:
            connection.execute(
                """
                INSERT OR REPLACE INTO scopes VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
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
                ],
            )
        for item in projection.symbols:
            connection.execute(
                """
                INSERT OR REPLACE INTO symbols VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
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
                ],
            )
        for item in projection.imports:
            connection.execute(
                """
                INSERT OR REPLACE INTO imports VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
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
                ],
            )
        for item in projection.references:
            connection.execute(
                """
                INSERT OR REPLACE INTO "references" VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
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
                ],
            )
        for item in projection.calls:
            connection.execute(
                """
                INSERT OR REPLACE INTO calls VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
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
                ],
            )
        for item in projection.effects:
            connection.execute(
                """
                INSERT OR REPLACE INTO effects VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
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
                ],
            )
        for item in projection.interfaces:
            connection.execute(
                """
                INSERT OR REPLACE INTO interfaces VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
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
                ],
            )
        for item in projection.diagnostics:
            connection.execute(
                """
                INSERT OR REPLACE INTO diagnostics VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
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
                ],
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
    "project_ast_record",
    "project_parse_failure",
    "spans_survive_projection",
]
