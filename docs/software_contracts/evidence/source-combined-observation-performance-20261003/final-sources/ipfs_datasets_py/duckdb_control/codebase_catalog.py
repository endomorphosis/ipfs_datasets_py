"""Durable structural codebase heads on the AST owner's DuckDB transaction.

The caller supplies one native, file-backed owner connection through its AST
store. Workers exchange artifacts and expected-head tokens, never connections.
This domain establishes structural publication order, not semantic extraction
or proof authority. Current source observation remains the wrapper's duty.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ipfs_datasets_py.logic.software_contracts.ast_ir import ASTRecord
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import (
    CodebaseIRManifest, _reconstruct_manifest, _manifest_native_equal,
)
from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes, cid_for_bytes, cid_for_structured, validate_cid,
)
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
    ASTCatalogProjection, DuckDBASTStore, InvalidationRow,
)

SCHEMA = "codebase-control@1"
HEAD_SCHEMA = "codebase-head@1"
RECEIPT_SCHEMA = "codebase-publication-receipt@1"
REQUEST_SCHEMA = "codebase-publication-request@1"
_DDL = (
    "CREATE SCHEMA codebase_control",
    "CREATE TABLE codebase_control.meta (singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_id VARCHAR NOT NULL, schema_cid VARCHAR NOT NULL, catalog_cid VARCHAR NOT NULL, artifact_root VARCHAR NOT NULL)",
    "CREATE TABLE codebase_control.heads (repository_id VARCHAR PRIMARY KEY, generation BIGINT NOT NULL, manifest_cid VARCHAR NOT NULL, snapshot_cid VARCHAR NOT NULL, ast_revision_id VARCHAR NOT NULL, receipt_cid VARCHAR NOT NULL)",
    "CREATE TABLE codebase_control.operations (operation_id VARCHAR PRIMARY KEY, request_cid VARCHAR NOT NULL, receipt_cid VARCHAR UNIQUE NOT NULL, receipt VARCHAR NOT NULL)",
)
_TABLES = {"meta", "heads", "operations"}
_COLUMNS = {
    "heads": (("repository_id", "VARCHAR"), ("generation", "BIGINT"),
              ("manifest_cid", "VARCHAR"), ("snapshot_cid", "VARCHAR"),
              ("ast_revision_id", "VARCHAR"), ("receipt_cid", "VARCHAR")),
    "meta": (("singleton", "INTEGER"), ("schema_id", "VARCHAR"),
             ("schema_cid", "VARCHAR"), ("catalog_cid", "VARCHAR"),
             ("artifact_root", "VARCHAR")),
    "operations": (("operation_id", "VARCHAR"), ("request_cid", "VARCHAR"),
                   ("receipt_cid", "VARCHAR"), ("receipt", "VARCHAR")),
}
_HEAD_FIELDS = {"repository_id", "generation", "manifest_cid", "snapshot_cid", "ast_revision_id", "receipt_cid"}
_RECEIPT_FIELDS = {"operation_id", "request_cid", "previous_head", "repository_id", "generation", "manifest_cid", "snapshot_cid", "ast_revision_id"}


class CodebaseCatalogError(ValueError):
    """Malformed, unbounded or unavailable structural publication evidence."""


class CodebaseHeadConflict(CodebaseCatalogError):
    """The supplied complete expected head is no longer current."""


class CodebaseOperationConflict(CodebaseCatalogError):
    """An operation identifier was already used for another request."""


def _text(value: Any, name: str, maximum: int = 512) -> str:
    if (type(value) is not str or not value or value != value.strip()
            or len(value.encode("utf-8")) > maximum
            or any(ord(character) < 32 for character in value)):
        raise CodebaseCatalogError(f"{name} must be a bounded nonempty string")
    return value


def _generation(value: Any) -> int:
    if type(value) is not int or not 1 <= value < 2**63:
        raise CodebaseCatalogError("generation must be a positive signed 64-bit integer")
    return value


def _cid(value: Any) -> str:
    try:
        return validate_cid(value, codecs={"dag-json"})
    except (TypeError, ValueError) as exc:
        raise CodebaseCatalogError("expected a canonical structured CID") from exc


def _request(repository_id: str, manifest_cid: str, expected_head: CodebaseHead | None) -> str:
    return cid_for_structured({"schema": REQUEST_SCHEMA, "repository_id": repository_id,
                               "manifest_cid": manifest_cid,
                               "expected_head": expected_head.to_dict() if expected_head else None})


@dataclass(frozen=True, slots=True)
class CodebaseHead:
    repository_id: str
    generation: int
    manifest_cid: str
    snapshot_cid: str
    ast_revision_id: str
    receipt_cid: str

    def __post_init__(self) -> None:
        _text(self.repository_id, "repository_id")
        _generation(self.generation)
        for value in (self.manifest_cid, self.snapshot_cid, self.receipt_cid):
            _cid(value)
        if self.ast_revision_id != f"rev:{self.repository_id}:snapshot:{self.snapshot_cid}":
            raise CodebaseCatalogError("head AST revision does not bind its repository snapshot")

    def to_dict(self) -> dict[str, Any]:
        return {"schema": HEAD_SCHEMA, **{name: getattr(self, name) for name in _HEAD_FIELDS}}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CodebaseHead:
        if (not isinstance(value, Mapping) or set(value) != _HEAD_FIELDS | {"schema"}
                or value["schema"] != HEAD_SCHEMA):
            raise CodebaseCatalogError("invalid codebase head fields or schema")
        return cls(**{name: value[name] for name in _HEAD_FIELDS})


@dataclass(frozen=True, slots=True)
class CodebasePublicationReceipt:
    operation_id: str
    request_cid: str
    previous_head: CodebaseHead | None
    repository_id: str
    generation: int
    manifest_cid: str
    snapshot_cid: str
    ast_revision_id: str

    def __post_init__(self) -> None:
        _text(self.operation_id, "operation_id", 256)
        _text(self.repository_id, "repository_id")
        _generation(self.generation)
        for value in (self.request_cid, self.manifest_cid, self.snapshot_cid):
            _cid(value)
        if self.previous_head is not None:
            if type(self.previous_head) is not CodebaseHead or self.previous_head.repository_id != self.repository_id:
                raise CodebaseCatalogError("receipt previous head belongs to another repository")
        if self.generation != (self.previous_head.generation + 1 if self.previous_head else 1):
            raise CodebaseCatalogError("receipt generation does not follow its previous head")
        if self.request_cid != _request(self.repository_id, self.manifest_cid, self.previous_head):
            raise CodebaseCatalogError("receipt request identity does not recompute")
        if self.ast_revision_id != f"rev:{self.repository_id}:snapshot:{self.snapshot_cid}":
            raise CodebaseCatalogError("receipt AST revision does not bind its snapshot")

    def to_dict(self) -> dict[str, Any]:
        result = {"schema": RECEIPT_SCHEMA, **{name: getattr(self, name) for name in _RECEIPT_FIELDS}}
        result["previous_head"] = self.previous_head.to_dict() if self.previous_head else None
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CodebasePublicationReceipt:
        if (not isinstance(value, Mapping) or set(value) != _RECEIPT_FIELDS | {"schema"}
                or value["schema"] != RECEIPT_SCHEMA):
            raise CodebaseCatalogError("invalid codebase receipt fields or schema")
        fields = {name: value[name] for name in _RECEIPT_FIELDS}
        if fields["previous_head"] is not None:
            fields["previous_head"] = CodebaseHead.from_dict(fields["previous_head"])
        return cls(**fields)

    @property
    def cid(self) -> str:
        return cid_for_structured(self.to_dict())

    @property
    def head(self) -> CodebaseHead:
        return CodebaseHead(self.repository_id, self.generation, self.manifest_cid,
                            self.snapshot_cid, self.ast_revision_id, self.cid)


@dataclass(frozen=True, slots=True)
class CodebaseCatalogLimits:
    """Finite local profile; these admission caps do not bound process RSS."""

    max_heads: int = 128
    max_operations: int = 4096
    max_entries: int = 256
    max_manifest_bytes: int = 16 * 1024 * 1024
    max_source_bytes: int = 16 * 1024 * 1024
    max_ast_bytes: int = 64 * 1024 * 1024
    max_receipt_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise CodebaseCatalogError(f"{name} must be a positive exact integer")


class _Replay(Exception):
    def __init__(self, receipt: CodebasePublicationReceipt) -> None:
        self.receipt = receipt


class CodebaseCatalog:
    """A bounded head/operation domain sharing an existing native AST owner.

    The caller must serialize all access to this supplied connection through the
    store; independently managed writers may receive DuckDB transaction conflicts
    and must resolve their operation before retry. Historical operation receipts
    remain historical even when the current head has moved. No automatic pruning
    discards replay protection: reaching a row cap rejects new publications.
    """

    def __init__(self, store: DuckDBASTStore, artifacts: ImmutableCAS, *,
                 limits: CodebaseCatalogLimits | None = None) -> None:
        import duckdb

        if type(store) is not DuckDBASTStore or type(store._connection) is not duckdb.DuckDBPyConnection:
            raise CodebaseCatalogError("catalog requires an exact native DuckDB AST owner")
        if type(artifacts) is not ImmutableCAS:
            raise CodebaseCatalogError("catalog requires the exact immutable artifact owner")
        self.store, self.artifacts = store, artifacts
        self.limits = limits if limits is not None else CodebaseCatalogLimits()
        if type(self.limits) is not CodebaseCatalogLimits:
            raise CodebaseCatalogError("limits must be canonical CodebaseCatalogLimits")
        self._pid = os.getpid()
        self._cx = store._connection
        self._database_name = self._cx.execute("SELECT current_database()").fetchone()[0]
        databases = self._cx.execute("PRAGMA database_list").fetchall()
        matches = [row[2] for row in databases if row[1] == self._database_name]
        if len(matches) != 1 or not matches[0]:
            raise CodebaseCatalogError("catalog requires a file-backed database")
        self._database_path = Path(matches[0]).resolve()
        self._database_identity = self._identity(self._database_path)
        self._artifact_root = artifacts.root.resolve()
        self._artifact_identity = self._identity(self._artifact_root)
        with self.store._lock, self.store._transaction():
            schemas = self._cx.execute("SELECT schema_name FROM information_schema.schemata WHERE catalog_name=current_database() AND schema_name='codebase_control'").fetchall()
            if not schemas:
                for statement in _DDL:
                    self._cx.execute(statement)
                self._cx.execute("INSERT INTO codebase_control.meta VALUES (1, ?, ?, ?, ?)",
                                 [SCHEMA, cid_for_structured(list(_DDL)), self._catalog_identity(), str(self._artifact_root)])
            self._check_schema()
            self._check_counts()

    @staticmethod
    def _identity(path: Path) -> tuple[int, int]:
        try:
            result = path.stat()
        except OSError as exc:
            raise CodebaseCatalogError("owner path is unavailable") from exc
        return result.st_dev, result.st_ino

    def _ensure_owner(self) -> None:
        if os.getpid() != self._pid:
            raise CodebaseCatalogError("inherited catalog connection cannot be used in another process")
        if self.store._connection is not self._cx:
            raise CodebaseCatalogError("catalog AST connection identity changed")
        if (self._identity(self._database_path) != self._database_identity
                or self.artifacts.root.resolve() != self._artifact_root
                or self._identity(self._artifact_root) != self._artifact_identity):
            raise CodebaseCatalogError("catalog database or artifact root identity changed")
        if self._cx.execute("SELECT current_database()").fetchone()[0] != self._database_name:
            raise CodebaseCatalogError("catalog connection changed its current database")

    def _catalog_identity(self) -> str:
        rows = self._cx.execute("SELECT table_name, sql FROM duckdb_tables() WHERE database_name=current_database() AND schema_name='codebase_control' ORDER BY table_name").fetchall()
        return cid_for_structured([list(row) for row in rows])

    def _check_schema(self) -> None:
        rows = self._cx.execute("SELECT table_name, table_type FROM information_schema.tables WHERE table_catalog=current_database() AND table_schema='codebase_control' LIMIT 4").fetchall()
        if set(rows) != {(name, "BASE TABLE") for name in _TABLES}:
            raise CodebaseCatalogError("foreign, incomplete or drifted codebase catalog schema")
        columns = self._cx.execute("SELECT table_name, column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_catalog=current_database() AND table_schema='codebase_control' ORDER BY table_name, ordinal_position LIMIT 16").fetchall()
        expected_columns = [(table, name, kind, "NO", None)
                            for table, fields in sorted(_COLUMNS.items())
                            for name, kind in fields]
        if columns != expected_columns:
            raise CodebaseCatalogError("codebase catalog columns differ from the required schema")
        constraints = self._cx.execute("SELECT table_name, constraint_type, constraint_column_names, expression FROM duckdb_constraints() WHERE database_name=current_database() AND schema_name='codebase_control' LIMIT 21").fetchall()
        actual_constraints = [(table, kind, tuple(names), expression)
                              for table, kind, names, expression in constraints]
        expected_constraints = [(table, "NOT NULL", (name,), None)
                                for table, fields in _COLUMNS.items() for name, _ in fields]
        expected_constraints += [(table, "PRIMARY KEY", (fields[0][0],), None)
                                 for table, fields in _COLUMNS.items()]
        expected_constraints += [("operations", "UNIQUE", ("receipt_cid",), None),
                                 ("meta", "CHECK", ("singleton",), "(singleton = 1)")]
        if (len(actual_constraints) != len(expected_constraints)
                or set(actual_constraints) != set(expected_constraints)):
            raise CodebaseCatalogError("codebase catalog constraints differ from the required schema")
        sizes = self._cx.execute("SELECT octet_length(encode(schema_id)) + octet_length(encode(schema_cid)) + octet_length(encode(catalog_cid)) + octet_length(encode(artifact_root)) FROM codebase_control.meta LIMIT 2").fetchall()
        if len(sizes) != 1 or sizes[0][0] > self.limits.max_receipt_bytes:
            raise CodebaseCatalogError("codebase catalog metadata exceeds its byte bound")
        rows = self._cx.execute("SELECT singleton, schema_id, schema_cid, catalog_cid, artifact_root FROM codebase_control.meta LIMIT 2").fetchall()
        if rows != [(1, SCHEMA, cid_for_structured(list(_DDL)), self._catalog_identity(), str(self._artifact_root))]:
            raise CodebaseCatalogError("codebase catalog schema or artifact root binding changed")

    def _check_counts(self) -> tuple[int, int]:
        heads, operations = self._cx.execute("SELECT (SELECT count(*) FROM codebase_control.heads), (SELECT count(*) FROM codebase_control.operations)").fetchone()
        if heads > self.limits.max_heads or operations > self.limits.max_operations:
            raise CodebaseCatalogError("codebase catalog exceeds configured row bounds")
        return heads, operations

    def _read_receipt(self, column: str, identity: str) -> CodebasePublicationReceipt | None:
        # column is an internal closed choice, never a caller-provided identifier.
        size = self._cx.execute(f"SELECT octet_length(encode(receipt)) FROM codebase_control.operations WHERE {column}=? LIMIT 2", [identity]).fetchall()
        if not size:
            return None
        if len(size) != 1 or not 0 < size[0][0] <= self.limits.max_receipt_bytes:
            raise CodebaseCatalogError("stored operation receipt exceeds its bound or is ambiguous")
        row = self._cx.execute(f"SELECT operation_id, request_cid, receipt_cid, receipt FROM codebase_control.operations WHERE {column}=?", [identity]).fetchone()
        try:
            result = CodebasePublicationReceipt.from_dict(json.loads(row[3]))
            if (row[:3] != (result.operation_id, result.request_cid, result.cid)
                    or row[3].encode("utf-8") != canonical_dag_json_bytes(result.to_dict())):
                raise CodebaseCatalogError("stored receipt identity differs from its canonical payload")
            return result
        except (TypeError, ValueError, KeyError) as exc:
            raise CodebaseCatalogError("stored operation receipt is malformed") from exc

    def _current(self, repository_id: str) -> CodebaseHead | None:
        sizes = self._cx.execute("SELECT octet_length(encode(repository_id)) + octet_length(encode(manifest_cid)) + octet_length(encode(snapshot_cid)) + octet_length(encode(ast_revision_id)) + octet_length(encode(receipt_cid)) FROM codebase_control.heads WHERE repository_id=? LIMIT 2", [repository_id]).fetchall()
        if len(sizes) > 1 or any(row[0] is None or row[0] > self.limits.max_receipt_bytes for row in sizes):
            raise CodebaseCatalogError("stored head exceeds its byte bound or is ambiguous")
        rows = self._cx.execute("SELECT repository_id, generation, manifest_cid, snapshot_cid, ast_revision_id, receipt_cid FROM codebase_control.heads WHERE repository_id=? LIMIT 2", [repository_id]).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise CodebaseCatalogError("ambiguous current head")
        result = CodebaseHead(*rows[0])
        receipt = self._read_receipt("receipt_cid", result.receipt_cid)
        if receipt is None or receipt.head != result:
            raise CodebaseCatalogError("current head does not bind its committed operation receipt")
        return result

    def current(self, repository_id: str) -> CodebaseHead | None:
        _text(repository_id, "repository_id")
        with self.store._lock:
            self._ensure_owner()
            with self.store._transaction():
                self._check_schema()
                return self._current(repository_id)

    @staticmethod
    def request_identity(manifest: CodebaseIRManifest, expected_head: CodebaseHead | None) -> str:
        if type(manifest) is not CodebaseIRManifest:
            raise CodebaseCatalogError("manifest must be canonical CodebaseIRManifest")
        if expected_head is not None and (type(expected_head) is not CodebaseHead
                or expected_head.repository_id != manifest.snapshot.repository_id):
            raise CodebaseCatalogError("expected head belongs to another repository")
        return _request(manifest.snapshot.repository_id, manifest.cid, expected_head)

    def resolve_operation(self, operation_id: str, request_identity: str) -> CodebasePublicationReceipt | None:
        _text(operation_id, "operation_id", 256)
        _cid(request_identity)
        with self.store._lock:
            self._ensure_owner()
            with self.store._transaction():
                self._check_schema()
                result = self._read_receipt("operation_id", operation_id)
                if result is not None and result.request_cid != request_identity:
                    raise CodebaseOperationConflict("operation_id already names another publication request")
                return result

    def _read_artifact(self, cid: str, maximum: int, *, source: bool = False) -> Any:
        # Apply this domain's per-artifact cap as well as the CAS owner's cap,
        # including a concurrently replaced oversized object.
        path = self.artifacts.path_for(cid, source=source)
        try:
            with path.open("rb") as stream:
                raw = stream.read(min(maximum, self.artifacts.max_object_bytes) + 1)
        except OSError as exc:
            raise CodebaseCatalogError("required immutable artifact is unavailable") from exc
        if len(raw) > min(maximum, self.artifacts.max_object_bytes):
            raise CodebaseCatalogError("required immutable artifact exceeds its byte bound")
        if source:
            if cid_for_bytes(raw) != cid:
                raise CodebaseCatalogError("source artifact CID mismatch")
            return raw
        try:
            value = json.loads(raw)
            if canonical_dag_json_bytes(value) != raw or cid_for_structured(value) != cid:
                raise CodebaseCatalogError("structured artifact is not canonical or has a different CID")
            return value
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise CodebaseCatalogError("required immutable artifact is malformed") from exc

    def _validate_candidate(self, manifest: CodebaseIRManifest,
                            projections: Sequence[ASTCatalogProjection],
                            checkpoint: Callable[[], None]) -> None:
        if len(manifest.units) > self.limits.max_entries or len(projections) > self.limits.max_entries:
            raise CodebaseCatalogError("publication exceeds the entry bound")
        manifest_cid = manifest.cid
        sealed = self._read_artifact(manifest_cid, self.limits.max_manifest_bytes)
        reconstructed = _reconstruct_manifest(sealed, manifest_cid)
        # Preserve the post-read candidate fence and the original comparison
        # for any custom/unknown representation or non-affirmative native result.
        if (not _manifest_native_equal(reconstructed, manifest)
                and reconstructed.to_dict() != manifest.to_dict()):
            raise CodebaseCatalogError("manifest does not match its sealed canonical artifact")
        entries = {entry.source_key: entry for entry in manifest.snapshot.entries}
        by_path: dict[str, ASTCatalogProjection] = {}
        total_ast = 0
        for projection in projections:
            checkpoint()
            if type(projection) is not ASTCatalogProjection:
                raise CodebaseCatalogError("publication requires canonical AST projections")
            self.store._validate_projection(projection)
            total_ast += len(projection.ast_blob.payload_json.encode("utf-8"))
            if total_ast > self.limits.max_ast_bytes:
                raise CodebaseCatalogError("publication exceeds the aggregate AST byte bound")
            path = projection.source_file.path
            if path in by_path:
                raise CodebaseCatalogError("publication contains duplicate AST paths")
            by_path[path] = projection
        expected_paths = {entries[unit.source_key].path for unit in manifest.units if unit.ast_cid is not None}
        if set(by_path) != expected_paths:
            raise CodebaseCatalogError("projections do not account for the manifest AST units exactly")
        total_source = 0
        for unit in manifest.units:
            checkpoint()
            entry = entries[unit.source_key]
            if not entry.is_opaque:
                source = self._read_artifact(entry.source_cid, min(manifest.snapshot.max_file_bytes, self.limits.max_source_bytes), source=True)
                total_source += len(source)
                if total_source > self.limits.max_source_bytes:
                    raise CodebaseCatalogError("publication exceeds the aggregate source byte bound")
            if unit.ast_cid is None:
                continue
            projection = by_path[entry.path]
            ast = self._read_artifact(unit.ast_cid, self.limits.max_ast_bytes)
            # Canonical ingestor parser-failure envelopes are checked by the
            # store's canonical re-projection, just like complete ASTRecord IR.
            if json.loads(projection.ast_blob.payload_json) != ast:
                raise CodebaseCatalogError("AST projection differs from its immutable artifact")
            if (projection.ast_cid != unit.ast_cid
                    or projection.source_cid != entry.source_cid
                    or projection.source_revision.repository_id != manifest.snapshot.repository_id
                    or projection.source_revision.revision_id != manifest.ast_revision_id
                    or projection.source_revision.repository_tree_cid != manifest.snapshot.snapshot_cid
                    or projection.ast_blob.parse_status != unit.parse_status):
                raise CodebaseCatalogError("AST projection source, snapshot or parse status binding differs")
            if ast.get("kind") != "parse_failure":
                record = ASTRecord.from_dict(ast)
                if (record.provenance.path != entry.path
                        or record.provenance.source_cid != entry.source_cid):
                    raise CodebaseCatalogError("immutable AST provenance does not match captured source")

    def publish(self, *, operation_id: str, manifest: CodebaseIRManifest,
                expected_head: CodebaseHead | None,
                projections: Sequence[ASTCatalogProjection],
                invalidations: Sequence[InvalidationRow] = (),
                checkpoint: Callable[[], None] | None = None,
                publication_checkpoint: Callable[[], None] | None = None) -> CodebasePublicationReceipt:
        """CAS the head and AST revision atomically; replay never mutates ASTs.

        The catalog derives supersession from durable history. Ingestor-local
        invalidations are intentionally rejected; their selectors can depend on
        warm process state and cannot define a restart-stable operation identity.

        ``checkpoint`` retains per-unit cancellation/deadline checks. The optional
        ``publication_checkpoint`` runs inside the existing transaction before
        AST application and before and after head/operation writes. It permits
        bounded source fences without repeating them for every validated unit.
        An exception rolls back the complete batch; historical replay invokes
        neither callback and does not assert that source is still current.
        """
        _text(operation_id, "operation_id", 256)
        if invalidations:
            raise CodebaseCatalogError("catalog derives invalidations from the durable previous head")
        if checkpoint is not None and not callable(checkpoint):
            raise CodebaseCatalogError("checkpoint must be callable")
        if publication_checkpoint is not None and not callable(publication_checkpoint):
            raise CodebaseCatalogError("publication_checkpoint must be callable")
        check = checkpoint or (lambda: None)
        publication_check = (lambda: None) if publication_checkpoint is None else publication_checkpoint
        request_cid = self.request_identity(manifest, expected_head)
        replay = self.resolve_operation(operation_id, request_cid)
        if replay is not None:
            return replay
        check()
        projections = tuple(projections)
        self._validate_candidate(manifest, projections, check)
        receipt = CodebasePublicationReceipt(
            operation_id, request_cid, expected_head, manifest.snapshot.repository_id,
            expected_head.generation + 1 if expected_head else 1,
            manifest.cid, manifest.snapshot.snapshot_cid, manifest.ast_revision_id,
        )
        encoded = canonical_dag_json_bytes(receipt.to_dict())
        if len(encoded) > self.limits.max_receipt_bytes:
            raise CodebaseCatalogError("publication receipt exceeds its byte bound")
        supersession = ()
        if expected_head is not None and expected_head.ast_revision_id != manifest.ast_revision_id:
            supersession = (InvalidationRow(
                invalidation_id=f"invalidation:{receipt.cid}", blob_id=None, file_id=None,
                revision_id=expected_head.ast_revision_id, reason="revision_superseded",
                actor_id="codebase-catalog", detail=f"superseded by {manifest.ast_revision_id}",
                created_at=time.time(),
            ),)

        def before_apply(connection: Any) -> None:
            self._ensure_owner()
            self._check_schema()
            existing = self._read_receipt("operation_id", operation_id)
            if existing is not None:
                if existing.request_cid != request_cid:
                    raise CodebaseOperationConflict("operation_id already names another publication request")
                raise _Replay(existing)
            check()
            publication_check()
            previous = self._current(manifest.snapshot.repository_id)
            if previous != expected_head:
                raise CodebaseHeadConflict("current head differs from the complete expected head")
            heads, operations = self._check_counts()
            if operations >= self.limits.max_operations or (previous is None and heads >= self.limits.max_heads):
                raise CodebaseCatalogError("publication would exceed the catalog row bound")

        def before_commit(connection: Any) -> None:
            check()
            publication_check()
            head = receipt.head
            connection.execute("INSERT INTO codebase_control.heads VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(repository_id) DO UPDATE SET generation=excluded.generation, manifest_cid=excluded.manifest_cid, snapshot_cid=excluded.snapshot_cid, ast_revision_id=excluded.ast_revision_id, receipt_cid=excluded.receipt_cid",
                               [head.repository_id, head.generation, head.manifest_cid, head.snapshot_cid, head.ast_revision_id, head.receipt_cid])
            connection.execute("INSERT INTO codebase_control.operations VALUES (?, ?, ?, ?)",
                               [operation_id, request_cid, receipt.cid, encoded.decode("utf-8")])
            check()
            publication_check()

        try:
            self.store.apply_batch(projections, supersession,
                                   before_apply=before_apply, before_commit=before_commit)
        except _Replay as replayed:
            return replayed.receipt
        return receipt


__all__ = ["CodebaseCatalog", "CodebaseCatalogLimits", "CodebaseCatalogError",
           "CodebaseHead", "CodebaseHeadConflict", "CodebaseOperationConflict",
           "CodebasePublicationReceipt"]
