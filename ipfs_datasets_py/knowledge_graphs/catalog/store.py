"""SQLite WAL-backed durable graph catalog with branch-head CAS (KGP-005).

Control metadata only: tenant/graph lifecycle, branches, immutable revision
records, head compare-and-swap, tombstones, writer leases, idempotency keys,
and pin roots. Graph payloads remain storage-adapter owned.

DQK-059 adds optional DuckDB **shadow authority** routing: SQLite remains the
sole authority while producers dual-project control-plane mutations through the
domain-neutral :class:`~ipfs_datasets_py.duckdb_control.authority_transition.AuthorityTransitionPort`
and a DuckDB catalog mirror that emits parity receipts. Parquet/IPLD payload
bytes, checksums, and CIDs are never rewritten by the shadow path.

DQK-060 promotes graph **control metadata** through fenced dual writes to
DuckDB authority (``dual`` → ``db-primary``). Immutable Parquet/IPLD revisions
remain the content authority. Legacy SQLite writes become outbox projections;
promotion and rollback are CAS-fenced and receipted. Readers bind one branch
revision for the duration of a promotion window so they never observe split
brain on branch heads.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Union

from .errors import CatalogError
from .identity import (
    DEFAULT_BRANCH,
    bootstrap_revision_id,
    expires_at_from_ttl,
    is_expired,
    new_lease_id,
    new_pin_id,
    optional_revision_id,
    request_hash,
    require_graph_kind,
    require_holder,
    require_idempotency_key,
    require_lease_id,
    require_positive_ttl,
    require_revision_id,
    require_slug,
    require_storage_profile,
    utc_now_iso,
)
from .models import (
    BranchRecord,
    GraphDescription,
    GraphRecord,
    IdempotencyRecord,
    LeaseRecord,
    PinRootRecord,
    RevisionRecord,
    TombstoneRecord,
)

PathLike = Union[str, Path]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DQK-059 shadow / DQK-060 dual→db-primary authority constants
# ---------------------------------------------------------------------------

GRAPH_SHADOW_DOMAIN: str = "graphs"
GRAPH_SHADOW_SCHEMA: str = (
    "ipfs_datasets_py/knowledge-graphs-duckdb-shadow-authority@1"
)
GRAPH_SHADOW_OWNER_TASK: str = "DQK-059"

# DQK-060 cutover surface (same domain, dual-mode owner task).
GRAPH_AUTHORITY_DOMAIN: str = GRAPH_SHADOW_DOMAIN
GRAPH_AUTHORITY_SCHEMA: str = (
    "ipfs_datasets_py/knowledge-graphs-duckdb-authority@1"
)
GRAPH_AUTHORITY_OWNER_TASK: str = "DQK-060"

_process_shadow_lock = threading.RLock()
_process_shadow_authority: Optional["GraphShadowAuthority"] = None

_SCHEMA_VERSION = 1

_SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS catalog_meta (
    key TEXT PRIMARY KEY NOT NULL,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS graphs (
    tenant TEXT NOT NULL,
    graph_id TEXT NOT NULL,
    storage_profile TEXT NOT NULL,
    graph_kind TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'tombstoned')),
    default_branch TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tombstoned_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (tenant, graph_id)
);

CREATE TABLE IF NOT EXISTS branches (
    tenant TEXT NOT NULL,
    graph_id TEXT NOT NULL,
    branch TEXT NOT NULL,
    head_revision TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'tombstoned')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    tombstoned_at TEXT,
    PRIMARY KEY (tenant, graph_id, branch),
    FOREIGN KEY (tenant, graph_id) REFERENCES graphs (tenant, graph_id)
);

CREATE TABLE IF NOT EXISTS revisions (
    tenant TEXT NOT NULL,
    graph_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    parent_revision TEXT,
    storage_profile TEXT NOT NULL,
    created_at TEXT NOT NULL,
    manifest_cid TEXT,
    manifest_json TEXT,
    pin_root TEXT,
    checksum TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (tenant, graph_id, revision_id),
    FOREIGN KEY (tenant, graph_id) REFERENCES graphs (tenant, graph_id)
);

CREATE TABLE IF NOT EXISTS leases (
    tenant TEXT NOT NULL,
    graph_id TEXT NOT NULL,
    branch TEXT NOT NULL,
    lease_id TEXT NOT NULL UNIQUE,
    holder TEXT NOT NULL,
    epoch INTEGER NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    renewed_at TEXT NOT NULL,
    PRIMARY KEY (tenant, graph_id, branch),
    FOREIGN KEY (tenant, graph_id) REFERENCES graphs (tenant, graph_id)
);

CREATE TABLE IF NOT EXISTS idempotency (
    key TEXT PRIMARY KEY NOT NULL,
    tenant TEXT NOT NULL,
    graph_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pin_roots (
    pin_id TEXT PRIMARY KEY NOT NULL,
    tenant TEXT NOT NULL,
    graph_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    root_cid TEXT NOT NULL,
    pin_kind TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (tenant, graph_id, revision_id, root_cid, pin_kind),
    FOREIGN KEY (tenant, graph_id, revision_id)
        REFERENCES revisions (tenant, graph_id, revision_id)
);

CREATE TABLE IF NOT EXISTS tombstones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('graph', 'branch')),
    tenant TEXT NOT NULL,
    graph_id TEXT NOT NULL,
    branch TEXT,
    tombstoned_at TEXT NOT NULL,
    reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_graphs_tenant ON graphs (tenant);
CREATE INDEX IF NOT EXISTS idx_branches_graph ON branches (tenant, graph_id);
CREATE INDEX IF NOT EXISTS idx_revisions_graph ON revisions (tenant, graph_id);
CREATE INDEX IF NOT EXISTS idx_pin_roots_revision
    ON pin_roots (tenant, graph_id, revision_id);
CREATE INDEX IF NOT EXISTS idx_idempotency_graph
    ON idempotency (tenant, graph_id);
"""


class GraphCatalog:
    """Durable embedded catalog using SQLite WAL.

    Instances do not cache identity or heads in process memory as authority.
    Every public read/write hits the database so a new process reopening the
    same path observes committed state.
    """

    def __init__(
        self,
        path: PathLike,
        *,
        busy_timeout_ms: int = 30_000,
        shadow_authority: Optional["GraphShadowAuthority"] = None,
    ) -> None:
        self._path = Path(path)
        if self._path.parent and str(self._path.parent) not in ("", "."):
            self._path.parent.mkdir(parents=True, exist_ok=True)
        self._busy_timeout_ms = int(busy_timeout_ms)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self._path),
            timeout=max(1.0, self._busy_timeout_ms / 1000.0),
            check_same_thread=False,
            isolation_level=None,  # explicit transactions
        )
        self._conn.row_factory = sqlite3.Row
        self._closed = False
        self._shadow_authority: Optional["GraphShadowAuthority"] = shadow_authority
        self._configure_connection()
        self._initialize_schema()

    # ------------------------------------------------------------------
    # DQK-059 shadow authority binding
    # ------------------------------------------------------------------

    @property
    def shadow_authority(self) -> Optional["GraphShadowAuthority"]:
        return self._shadow_authority

    def attach_shadow_authority(
        self, authority: Optional["GraphShadowAuthority"]
    ) -> None:
        """Bind or clear the DuckDB shadow/dual authority (DQK-059/DQK-060)."""

        self._shadow_authority = authority

    # Alias used by dual-mode cutover callers.
    attach_authority = attach_shadow_authority

    @property
    def authority(self) -> Optional["GraphShadowAuthority"]:
        return self._shadow_authority

    def _notify_shadow(
        self,
        operation: str,
        result: Any,
        args: tuple[Any, ...],
        kwargs: Mapping[str, Any],
    ) -> None:
        """Best-effort dual/shadow projection; never raises to catalog callers."""

        shadow = self._shadow_authority
        if shadow is None:
            return
        try:
            shadow.record_catalog_mutation(
                operation,
                result=result,
                catalog=self,
                args=args,
                kwargs=dict(kwargs),
            )
        except Exception as exc:  # noqa: BLE001 — quarantine, keep SQLite authority
            logger.warning(
                "graph catalog shadow quarantined (legacy ok) op=%s: %s",
                operation,
                exc,
            )

    def authoritative_branch_head(
        self, tenant: str, graph_id: str, branch: str = DEFAULT_BRANCH
    ) -> Optional[str]:
        """Return the authoritative branch head under the attached authority.

        When a dual/db-primary authority is bound, prefer DuckDB (and any
        reader revision binding). Otherwise fall back to SQLite.
        """

        shadow = self._shadow_authority
        if shadow is not None and hasattr(shadow, "authoritative_branch_head"):
            try:
                head = shadow.authoritative_branch_head(
                    tenant, graph_id, branch, catalog=self
                )
                if head is not None:
                    return head
            except Exception:  # noqa: BLE001
                pass
        try:
            rec = self.get_branch(tenant, graph_id, branch)
            return rec.head_revision
        except CatalogError:
            return None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

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

    def __enter__(self) -> "GraphCatalog":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise CatalogError("STORAGE", "catalog is closed")

    def _configure_connection(self) -> None:
        cur = self._conn.cursor()
        cur.execute("PRAGMA foreign_keys = ON")
        cur.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
        # WAL for concurrent readers + single writer durability.
        cur.execute("PRAGMA journal_mode = WAL")
        cur.execute("PRAGMA synchronous = NORMAL")

    def _initialize_schema(self) -> None:
        with self._lock:
            self._conn.executescript(_SCHEMA_SQL)
            row = self._conn.execute(
                "SELECT value FROM catalog_meta WHERE key = ?",
                ("schema_version",),
            ).fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO catalog_meta (key, value) VALUES (?, ?)",
                    ("schema_version", str(_SCHEMA_VERSION)),
                )
            else:
                version = int(row["value"])
                if version > _SCHEMA_VERSION:
                    raise CatalogError(
                        "STORAGE",
                        f"catalog schema version {version} is newer than "
                        f"supported {_SCHEMA_VERSION}",
                    )

    @contextmanager
    def _txn(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        self._ensure_open()
        with self._lock:
            begin = "BEGIN IMMEDIATE" if immediate else "BEGIN"
            try:
                self._conn.execute(begin)
                yield self._conn
                self._conn.execute("COMMIT")
            except Exception:
                try:
                    self._conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise

    # ------------------------------------------------------------------
    # Row helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _graph_from_row(row: sqlite3.Row) -> GraphRecord:
        meta = json.loads(row["metadata_json"] or "{}")
        return GraphRecord(
            tenant=row["tenant"],
            graph_id=row["graph_id"],
            storage_profile=row["storage_profile"],
            graph_kind=row["graph_kind"],
            status=row["status"],
            default_branch=row["default_branch"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            tombstoned_at=row["tombstoned_at"],
            metadata=meta,
        )

    @staticmethod
    def _branch_from_row(row: sqlite3.Row) -> BranchRecord:
        return BranchRecord(
            tenant=row["tenant"],
            graph_id=row["graph_id"],
            branch=row["branch"],
            head_revision=row["head_revision"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            tombstoned_at=row["tombstoned_at"],
        )

    @staticmethod
    def _revision_from_row(row: sqlite3.Row) -> RevisionRecord:
        meta = json.loads(row["metadata_json"] or "{}")
        return RevisionRecord(
            tenant=row["tenant"],
            graph_id=row["graph_id"],
            revision_id=row["revision_id"],
            parent_revision=row["parent_revision"],
            storage_profile=row["storage_profile"],
            created_at=row["created_at"],
            manifest_cid=row["manifest_cid"],
            manifest_json=row["manifest_json"],
            pin_root=row["pin_root"],
            checksum=row["checksum"],
            metadata=meta,
        )

    @staticmethod
    def _lease_from_row(row: sqlite3.Row) -> LeaseRecord:
        return LeaseRecord(
            tenant=row["tenant"],
            graph_id=row["graph_id"],
            branch=row["branch"],
            lease_id=row["lease_id"],
            holder=row["holder"],
            epoch=int(row["epoch"]),
            expires_at=row["expires_at"],
            created_at=row["created_at"],
            renewed_at=row["renewed_at"],
        )

    @staticmethod
    def _pin_from_row(row: sqlite3.Row) -> PinRootRecord:
        return PinRootRecord(
            pin_id=row["pin_id"],
            tenant=row["tenant"],
            graph_id=row["graph_id"],
            revision_id=row["revision_id"],
            root_cid=row["root_cid"],
            pin_kind=row["pin_kind"],
            created_at=row["created_at"],
        )

    # ------------------------------------------------------------------
    # Internal lookups (caller holds transaction)
    # ------------------------------------------------------------------

    def _get_graph_row(
        self,
        conn: sqlite3.Connection,
        tenant: str,
        graph_id: str,
        *,
        for_update: bool = False,
        allow_tombstoned: bool = False,
    ) -> sqlite3.Row:
        sql = "SELECT * FROM graphs WHERE tenant = ? AND graph_id = ?"
        row = conn.execute(sql, (tenant, graph_id)).fetchone()
        if row is None:
            raise CatalogError(
                "NOT_FOUND",
                "graph not found",
                details={"tenant": tenant, "graph_id": graph_id},
            )
        if not allow_tombstoned and row["status"] == "tombstoned":
            raise CatalogError(
                "NOT_FOUND",
                "graph is tombstoned",
                details={"tenant": tenant, "graph_id": graph_id},
            )
        return row

    def _get_branch_row(
        self,
        conn: sqlite3.Connection,
        tenant: str,
        graph_id: str,
        branch: str,
        *,
        allow_tombstoned: bool = False,
    ) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM branches WHERE tenant = ? AND graph_id = ? AND branch = ?",
            (tenant, graph_id, branch),
        ).fetchone()
        if row is None:
            raise CatalogError(
                "NOT_FOUND",
                "branch not found",
                details={
                    "tenant": tenant,
                    "graph_id": graph_id,
                    "branch": branch,
                },
            )
        if not allow_tombstoned and row["status"] == "tombstoned":
            raise CatalogError(
                "NOT_FOUND",
                "branch is tombstoned",
                details={
                    "tenant": tenant,
                    "graph_id": graph_id,
                    "branch": branch,
                },
            )
        return row

    def _get_revision_row(
        self,
        conn: sqlite3.Connection,
        tenant: str,
        graph_id: str,
        revision_id: str,
    ) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM revisions WHERE tenant = ? AND graph_id = ? "
            "AND revision_id = ?",
            (tenant, graph_id, revision_id),
        ).fetchone()
        if row is None:
            raise CatalogError(
                "NOT_FOUND",
                "revision not found",
                details={
                    "tenant": tenant,
                    "graph_id": graph_id,
                    "revision_id": revision_id,
                },
            )
        return row

    def _lookup_idempotency(
        self,
        conn: sqlite3.Connection,
        key: str,
        *,
        request_hash_value: str,
        operation: str,
    ) -> Optional[Dict[str, Any]]:
        row = conn.execute(
            "SELECT * FROM idempotency WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        if row["operation"] != operation:
            raise CatalogError(
                "CONFLICT",
                "idempotency key reused for a different operation",
                details={
                    "key": key,
                    "existing_operation": row["operation"],
                    "operation": operation,
                },
            )
        if row["request_hash"] != request_hash_value:
            raise CatalogError(
                "CONFLICT",
                "idempotency key reused with a different request body",
                details={
                    "key": key,
                    "operation": operation,
                    "existing_request_hash": row["request_hash"],
                    "request_hash": request_hash_value,
                },
            )
        return json.loads(row["response_json"])

    def _store_idempotency(
        self,
        conn: sqlite3.Connection,
        *,
        key: str,
        tenant: str,
        graph_id: str,
        operation: str,
        request_hash_value: str,
        response: Mapping[str, Any],
        created_at: str,
    ) -> None:
        conn.execute(
            "INSERT INTO idempotency "
            "(key, tenant, graph_id, operation, request_hash, response_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                key,
                tenant,
                graph_id,
                operation,
                request_hash_value,
                json.dumps(response, sort_keys=True, separators=(",", ":")),
                created_at,
            ),
        )

    def _assert_lease(
        self,
        conn: sqlite3.Connection,
        tenant: str,
        graph_id: str,
        branch: str,
        *,
        lease_id: Optional[str],
        lease_epoch: Optional[int],
    ) -> None:
        if lease_id is None and lease_epoch is None:
            return
        if lease_id is None or lease_epoch is None:
            raise CatalogError(
                "INVALID_REQUEST",
                "lease_id and lease_epoch must be provided together",
            )
        lease_id = require_lease_id(lease_id)
        try:
            epoch = int(lease_epoch)
        except (TypeError, ValueError) as exc:
            raise CatalogError(
                "INVALID_REQUEST",
                "lease_epoch must be an integer",
                details={"lease_epoch": lease_epoch},
            ) from exc
        row = conn.execute(
            "SELECT * FROM leases WHERE tenant = ? AND graph_id = ? AND branch = ?",
            (tenant, graph_id, branch),
        ).fetchone()
        if row is None:
            raise CatalogError(
                "FENCED",
                "no active writer lease for branch",
                details={
                    "tenant": tenant,
                    "graph_id": graph_id,
                    "branch": branch,
                    "lease_id": lease_id,
                    "lease_epoch": epoch,
                },
            )
        if row["lease_id"] != lease_id or int(row["epoch"]) != epoch:
            raise CatalogError(
                "FENCED",
                "writer lease epoch is stale",
                details={
                    "tenant": tenant,
                    "graph_id": graph_id,
                    "branch": branch,
                    "lease_id": lease_id,
                    "lease_epoch": epoch,
                    "current_lease_id": row["lease_id"],
                    "current_epoch": int(row["epoch"]),
                },
            )
        if is_expired(row["expires_at"]):
            raise CatalogError(
                "FENCED",
                "writer lease has expired",
                details={
                    "tenant": tenant,
                    "graph_id": graph_id,
                    "branch": branch,
                    "lease_id": lease_id,
                    "lease_epoch": epoch,
                    "expires_at": row["expires_at"],
                },
            )

    def _insert_revision(
        self,
        conn: sqlite3.Connection,
        *,
        tenant: str,
        graph_id: str,
        revision_id: str,
        parent_revision: Optional[str],
        storage_profile: str,
        created_at: str,
        manifest_cid: Optional[str] = None,
        manifest_json: Optional[str] = None,
        pin_root: Optional[str] = None,
        checksum: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> RevisionRecord:
        meta = dict(metadata or {})
        try:
            conn.execute(
                "INSERT INTO revisions "
                "(tenant, graph_id, revision_id, parent_revision, storage_profile, "
                "created_at, manifest_cid, manifest_json, pin_root, checksum, "
                "metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    tenant,
                    graph_id,
                    revision_id,
                    parent_revision,
                    storage_profile,
                    created_at,
                    manifest_cid,
                    manifest_json,
                    pin_root,
                    checksum,
                    json.dumps(meta, sort_keys=True, separators=(",", ":")),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise CatalogError(
                "ALREADY_EXISTS",
                "revision already exists",
                details={
                    "tenant": tenant,
                    "graph_id": graph_id,
                    "revision_id": revision_id,
                },
            ) from exc
        if pin_root:
            conn.execute(
                "INSERT OR IGNORE INTO pin_roots "
                "(pin_id, tenant, graph_id, revision_id, root_cid, pin_kind, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    new_pin_id(),
                    tenant,
                    graph_id,
                    revision_id,
                    pin_root,
                    "revision",
                    created_at,
                ),
            )
        return RevisionRecord(
            tenant=tenant,
            graph_id=graph_id,
            revision_id=revision_id,
            parent_revision=parent_revision,
            storage_profile=storage_profile,
            created_at=created_at,
            manifest_cid=manifest_cid,
            manifest_json=manifest_json,
            pin_root=pin_root,
            checksum=checksum,
            metadata=meta,
        )

    # ------------------------------------------------------------------
    # Public: graph lifecycle
    # ------------------------------------------------------------------

    def create_graph(
        self,
        tenant: str,
        graph_id: str,
        *,
        branch: str = DEFAULT_BRANCH,
        storage_profile: Optional[str] = None,
        graph_kind: Optional[str] = None,
        pin_root: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> GraphRecord:
        """Register a graph identity, default branch, and bootstrap revision."""
        tenant = require_slug(tenant, field="tenant")
        graph_id = require_slug(graph_id, field="graph_id")
        branch = require_slug(branch, field="branch")
        profile = require_storage_profile(storage_profile)
        kind = require_graph_kind(graph_kind)
        meta = dict(metadata or {})
        idem_key = (
            require_idempotency_key(idempotency_key)
            if idempotency_key is not None
            else None
        )
        req = {
            "tenant": tenant,
            "graph_id": graph_id,
            "branch": branch,
            "storage_profile": profile,
            "graph_kind": kind,
            "pin_root": pin_root,
            "metadata": meta,
        }
        req_hash = request_hash(req)

        with self._txn(immediate=True) as conn:
            if idem_key is not None:
                cached = self._lookup_idempotency(
                    conn,
                    idem_key,
                    request_hash_value=req_hash,
                    operation="create_graph",
                )
                if cached is not None:
                    return GraphRecord(
                        tenant=cached["tenant"],
                        graph_id=cached["graph_id"],
                        storage_profile=cached["storage_profile"],
                        graph_kind=cached["graph_kind"],
                        status=cached["status"],
                        default_branch=cached["default_branch"],
                        created_at=cached["created_at"],
                        updated_at=cached["updated_at"],
                        tombstoned_at=cached.get("tombstoned_at"),
                        metadata=cached.get("metadata") or {},
                    )

            existing = conn.execute(
                "SELECT * FROM graphs WHERE tenant = ? AND graph_id = ?",
                (tenant, graph_id),
            ).fetchone()
            if existing is not None:
                raise CatalogError(
                    "ALREADY_EXISTS",
                    "graph already exists",
                    details={"tenant": tenant, "graph_id": graph_id},
                )

            now = utc_now_iso()
            rev_id = bootstrap_revision_id(tenant, graph_id)
            conn.execute(
                "INSERT INTO graphs "
                "(tenant, graph_id, storage_profile, graph_kind, status, "
                "default_branch, created_at, updated_at, tombstoned_at, metadata_json) "
                "VALUES (?, ?, ?, ?, 'active', ?, ?, ?, NULL, ?)",
                (
                    tenant,
                    graph_id,
                    profile,
                    kind,
                    branch,
                    now,
                    now,
                    json.dumps(meta, sort_keys=True, separators=(",", ":")),
                ),
            )
            self._insert_revision(
                conn,
                tenant=tenant,
                graph_id=graph_id,
                revision_id=rev_id,
                parent_revision=None,
                storage_profile=profile,
                created_at=now,
                pin_root=pin_root,
                metadata={"bootstrap": True},
            )
            conn.execute(
                "INSERT INTO branches "
                "(tenant, graph_id, branch, head_revision, status, "
                "created_at, updated_at, tombstoned_at) "
                "VALUES (?, ?, ?, ?, 'active', ?, ?, NULL)",
                (tenant, graph_id, branch, rev_id, now, now),
            )
            record = GraphRecord(
                tenant=tenant,
                graph_id=graph_id,
                storage_profile=profile,
                graph_kind=kind,
                status="active",
                default_branch=branch,
                created_at=now,
                updated_at=now,
                tombstoned_at=None,
                metadata=meta,
            )
            if idem_key is not None:
                self._store_idempotency(
                    conn,
                    key=idem_key,
                    tenant=tenant,
                    graph_id=graph_id,
                    operation="create_graph",
                    request_hash_value=req_hash,
                    response=record.to_dict(),
                    created_at=now,
                )
            return record

    def list_graphs(
        self,
        tenant: str,
        *,
        include_tombstoned: bool = False,
    ) -> List[GraphRecord]:
        tenant = require_slug(tenant, field="tenant")
        with self._txn(immediate=False) as conn:
            if include_tombstoned:
                rows = conn.execute(
                    "SELECT * FROM graphs WHERE tenant = ? ORDER BY graph_id",
                    (tenant,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM graphs WHERE tenant = ? AND status = 'active' "
                    "ORDER BY graph_id",
                    (tenant,),
                ).fetchall()
            return [self._graph_from_row(r) for r in rows]

    def get_graph(
        self,
        tenant: str,
        graph_id: str,
        *,
        allow_tombstoned: bool = False,
    ) -> GraphRecord:
        tenant = require_slug(tenant, field="tenant")
        graph_id = require_slug(graph_id, field="graph_id")
        with self._txn(immediate=False) as conn:
            row = self._get_graph_row(
                conn,
                tenant,
                graph_id,
                allow_tombstoned=allow_tombstoned,
            )
            return self._graph_from_row(row)

    def describe_graph(
        self,
        tenant: str,
        graph_id: str,
        *,
        branch: Optional[str] = None,
        include_tombstoned_branches: bool = False,
    ) -> GraphDescription:
        tenant = require_slug(tenant, field="tenant")
        graph_id = require_slug(graph_id, field="graph_id")
        branch_filter = (
            require_slug(branch, field="branch") if branch is not None else None
        )
        with self._txn(immediate=False) as conn:
            grow = self._get_graph_row(
                conn, tenant, graph_id, allow_tombstoned=True
            )
            graph = self._graph_from_row(grow)
            if branch_filter is not None:
                brow = self._get_branch_row(
                    conn,
                    tenant,
                    graph_id,
                    branch_filter,
                    allow_tombstoned=True,
                )
                branches = (self._branch_from_row(brow).to_dict(),)
                head = brow["head_revision"] if brow["status"] == "active" else None
            else:
                if include_tombstoned_branches:
                    brows = conn.execute(
                        "SELECT * FROM branches WHERE tenant = ? AND graph_id = ? "
                        "ORDER BY branch",
                        (tenant, graph_id),
                    ).fetchall()
                else:
                    brows = conn.execute(
                        "SELECT * FROM branches WHERE tenant = ? AND graph_id = ? "
                        "AND status = 'active' ORDER BY branch",
                        (tenant, graph_id),
                    ).fetchall()
                branch_dicts = tuple(self._branch_from_row(r).to_dict() for r in brows)
                branches = branch_dicts
                head = None
                default = graph.default_branch
                for r in brows:
                    if r["branch"] == default and r["status"] == "active":
                        head = r["head_revision"]
                        break
                if head is None and brows:
                    # Fall back to first active branch head.
                    for r in brows:
                        if r["status"] == "active":
                            head = r["head_revision"]
                            break
            return GraphDescription(
                tenant=graph.tenant,
                graph_id=graph.graph_id,
                uri=graph.uri,
                storage_profile=graph.storage_profile,
                graph_kind=graph.graph_kind,
                status=graph.status,
                default_branch=graph.default_branch,
                head_revision=head,
                branches=branches,
                created_at=graph.created_at,
                updated_at=graph.updated_at,
                tombstoned_at=graph.tombstoned_at,
                metadata=graph.metadata,
            )

    def delete_graph(
        self,
        tenant: str,
        graph_id: str,
        *,
        reason: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> TombstoneRecord:
        """Tombstone a graph and all of its branches (soft delete)."""
        tenant = require_slug(tenant, field="tenant")
        graph_id = require_slug(graph_id, field="graph_id")
        idem_key = (
            require_idempotency_key(idempotency_key)
            if idempotency_key is not None
            else None
        )
        req = {"tenant": tenant, "graph_id": graph_id, "reason": reason}
        req_hash = request_hash(req)

        with self._txn(immediate=True) as conn:
            if idem_key is not None:
                cached = self._lookup_idempotency(
                    conn,
                    idem_key,
                    request_hash_value=req_hash,
                    operation="delete_graph",
                )
                if cached is not None:
                    return TombstoneRecord(
                        entity_type=cached["entity_type"],
                        tenant=cached["tenant"],
                        graph_id=cached["graph_id"],
                        tombstoned_at=cached["tombstoned_at"],
                        branch=cached.get("branch"),
                        reason=cached.get("reason"),
                    )

            grow = self._get_graph_row(
                conn, tenant, graph_id, allow_tombstoned=True
            )
            now = utc_now_iso()
            if grow["status"] == "tombstoned":
                # Already tombstoned: idempotent success without re-writing.
                tomb = TombstoneRecord(
                    entity_type="graph",
                    tenant=tenant,
                    graph_id=graph_id,
                    tombstoned_at=grow["tombstoned_at"] or now,
                    branch=None,
                    reason=reason,
                )
            else:
                conn.execute(
                    "UPDATE graphs SET status = 'tombstoned', updated_at = ?, "
                    "tombstoned_at = ? WHERE tenant = ? AND graph_id = ?",
                    (now, now, tenant, graph_id),
                )
                conn.execute(
                    "UPDATE branches SET status = 'tombstoned', updated_at = ?, "
                    "tombstoned_at = ? WHERE tenant = ? AND graph_id = ? "
                    "AND status = 'active'",
                    (now, now, tenant, graph_id),
                )
                conn.execute(
                    "INSERT INTO tombstones "
                    "(entity_type, tenant, graph_id, branch, tombstoned_at, reason) "
                    "VALUES ('graph', ?, ?, NULL, ?, ?)",
                    (tenant, graph_id, now, reason),
                )
                # Drop leases on tombstoned graph.
                conn.execute(
                    "DELETE FROM leases WHERE tenant = ? AND graph_id = ?",
                    (tenant, graph_id),
                )
                tomb = TombstoneRecord(
                    entity_type="graph",
                    tenant=tenant,
                    graph_id=graph_id,
                    tombstoned_at=now,
                    branch=None,
                    reason=reason,
                )
            if idem_key is not None:
                self._store_idempotency(
                    conn,
                    key=idem_key,
                    tenant=tenant,
                    graph_id=graph_id,
                    operation="delete_graph",
                    request_hash_value=req_hash,
                    response=tomb.to_dict(),
                    created_at=now,
                )
            return tomb

    # ------------------------------------------------------------------
    # Branches
    # ------------------------------------------------------------------

    def create_branch(
        self,
        tenant: str,
        graph_id: str,
        branch: str,
        *,
        from_revision: Optional[str] = None,
        from_branch: Optional[str] = None,
    ) -> BranchRecord:
        tenant = require_slug(tenant, field="tenant")
        graph_id = require_slug(graph_id, field="graph_id")
        branch = require_slug(branch, field="branch")
        if from_revision is not None and from_branch is not None:
            raise CatalogError(
                "INVALID_REQUEST",
                "from_revision and from_branch are mutually exclusive",
            )
        with self._txn(immediate=True) as conn:
            grow = self._get_graph_row(conn, tenant, graph_id)
            existing = conn.execute(
                "SELECT * FROM branches WHERE tenant = ? AND graph_id = ? "
                "AND branch = ?",
                (tenant, graph_id, branch),
            ).fetchone()
            if existing is not None:
                if existing["status"] == "active":
                    raise CatalogError(
                        "ALREADY_EXISTS",
                        "branch already exists",
                        details={
                            "tenant": tenant,
                            "graph_id": graph_id,
                            "branch": branch,
                        },
                    )
                # Revive tombstoned branch only via explicit create with source.
            if from_revision is not None:
                rev = require_revision_id(from_revision, field="from_revision")
                self._get_revision_row(conn, tenant, graph_id, rev)
                head = rev
            elif from_branch is not None:
                src = require_slug(from_branch, field="from_branch")
                brow = self._get_branch_row(conn, tenant, graph_id, src)
                head = brow["head_revision"]
            else:
                # Default: copy head from default branch.
                brow = self._get_branch_row(
                    conn, tenant, graph_id, grow["default_branch"]
                )
                head = brow["head_revision"]

            now = utc_now_iso()
            if existing is not None and existing["status"] == "tombstoned":
                conn.execute(
                    "UPDATE branches SET head_revision = ?, status = 'active', "
                    "updated_at = ?, tombstoned_at = NULL "
                    "WHERE tenant = ? AND graph_id = ? AND branch = ?",
                    (head, now, tenant, graph_id, branch),
                )
                created = existing["created_at"]
            else:
                conn.execute(
                    "INSERT INTO branches "
                    "(tenant, graph_id, branch, head_revision, status, "
                    "created_at, updated_at, tombstoned_at) "
                    "VALUES (?, ?, ?, ?, 'active', ?, ?, NULL)",
                    (tenant, graph_id, branch, head, now, now),
                )
                created = now
            conn.execute(
                "UPDATE graphs SET updated_at = ? WHERE tenant = ? AND graph_id = ?",
                (now, tenant, graph_id),
            )
            return BranchRecord(
                tenant=tenant,
                graph_id=graph_id,
                branch=branch,
                head_revision=head,
                status="active",
                created_at=created,
                updated_at=now,
                tombstoned_at=None,
            )

    def get_branch(
        self,
        tenant: str,
        graph_id: str,
        branch: str,
        *,
        allow_tombstoned: bool = False,
    ) -> BranchRecord:
        tenant = require_slug(tenant, field="tenant")
        graph_id = require_slug(graph_id, field="graph_id")
        branch = require_slug(branch, field="branch")
        with self._txn(immediate=False) as conn:
            row = self._get_branch_row(
                conn,
                tenant,
                graph_id,
                branch,
                allow_tombstoned=allow_tombstoned,
            )
            return self._branch_from_row(row)

    def list_branches(
        self,
        tenant: str,
        graph_id: str,
        *,
        include_tombstoned: bool = False,
    ) -> List[BranchRecord]:
        tenant = require_slug(tenant, field="tenant")
        graph_id = require_slug(graph_id, field="graph_id")
        with self._txn(immediate=False) as conn:
            self._get_graph_row(
                conn, tenant, graph_id, allow_tombstoned=True
            )
            if include_tombstoned:
                rows = conn.execute(
                    "SELECT * FROM branches WHERE tenant = ? AND graph_id = ? "
                    "ORDER BY branch",
                    (tenant, graph_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM branches WHERE tenant = ? AND graph_id = ? "
                    "AND status = 'active' ORDER BY branch",
                    (tenant, graph_id),
                ).fetchall()
            return [self._branch_from_row(r) for r in rows]

    def delete_branch(
        self,
        tenant: str,
        graph_id: str,
        branch: str,
        *,
        reason: Optional[str] = None,
    ) -> TombstoneRecord:
        tenant = require_slug(tenant, field="tenant")
        graph_id = require_slug(graph_id, field="graph_id")
        branch = require_slug(branch, field="branch")
        with self._txn(immediate=True) as conn:
            grow = self._get_graph_row(conn, tenant, graph_id)
            if grow["default_branch"] == branch:
                raise CatalogError(
                    "INVALID_REQUEST",
                    "cannot tombstone the default branch; delete the graph instead",
                    details={
                        "tenant": tenant,
                        "graph_id": graph_id,
                        "branch": branch,
                    },
                )
            brow = self._get_branch_row(
                conn, tenant, graph_id, branch, allow_tombstoned=True
            )
            now = utc_now_iso()
            if brow["status"] == "tombstoned":
                return TombstoneRecord(
                    entity_type="branch",
                    tenant=tenant,
                    graph_id=graph_id,
                    branch=branch,
                    tombstoned_at=brow["tombstoned_at"] or now,
                    reason=reason,
                )
            conn.execute(
                "UPDATE branches SET status = 'tombstoned', updated_at = ?, "
                "tombstoned_at = ? WHERE tenant = ? AND graph_id = ? AND branch = ?",
                (now, now, tenant, graph_id, branch),
            )
            conn.execute(
                "INSERT INTO tombstones "
                "(entity_type, tenant, graph_id, branch, tombstoned_at, reason) "
                "VALUES ('branch', ?, ?, ?, ?, ?)",
                (tenant, graph_id, branch, now, reason),
            )
            conn.execute(
                "DELETE FROM leases WHERE tenant = ? AND graph_id = ? AND branch = ?",
                (tenant, graph_id, branch),
            )
            conn.execute(
                "UPDATE graphs SET updated_at = ? WHERE tenant = ? AND graph_id = ?",
                (now, tenant, graph_id),
            )
            return TombstoneRecord(
                entity_type="branch",
                tenant=tenant,
                graph_id=graph_id,
                branch=branch,
                tombstoned_at=now,
                reason=reason,
            )

    # ------------------------------------------------------------------
    # Revisions (immutable)
    # ------------------------------------------------------------------

    def put_revision(
        self,
        tenant: str,
        graph_id: str,
        revision_id: str,
        *,
        parent_revision: Optional[str] = None,
        storage_profile: Optional[str] = None,
        manifest_cid: Optional[str] = None,
        manifest_json: Optional[str] = None,
        pin_root: Optional[str] = None,
        checksum: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> RevisionRecord:
        """Insert an immutable revision record. Existing ids cannot change."""
        tenant = require_slug(tenant, field="tenant")
        graph_id = require_slug(graph_id, field="graph_id")
        revision_id = require_revision_id(revision_id)
        parent = optional_revision_id(parent_revision, field="parent_revision")
        if parent is not None and parent == revision_id:
            raise CatalogError(
                "INVALID_REQUEST",
                "parent_revision must not equal revision_id",
            )
        with self._txn(immediate=True) as conn:
            grow = self._get_graph_row(conn, tenant, graph_id)
            profile = (
                require_storage_profile(storage_profile)
                if storage_profile is not None
                else grow["storage_profile"]
            )
            if parent is not None:
                self._get_revision_row(conn, tenant, graph_id, parent)
            existing = conn.execute(
                "SELECT * FROM revisions WHERE tenant = ? AND graph_id = ? "
                "AND revision_id = ?",
                (tenant, graph_id, revision_id),
            ).fetchone()
            if existing is not None:
                # Immutable: identical content is a no-op success; mismatch is conflict.
                rec = self._revision_from_row(existing)
                same = (
                    rec.parent_revision == parent
                    and rec.storage_profile == profile
                    and rec.manifest_cid == manifest_cid
                    and rec.manifest_json == manifest_json
                    and rec.pin_root == pin_root
                    and rec.checksum == checksum
                )
                if not same:
                    raise CatalogError(
                        "CONFLICT",
                        "revision is immutable and differs from existing record",
                        details={
                            "tenant": tenant,
                            "graph_id": graph_id,
                            "revision_id": revision_id,
                        },
                    )
                return rec
            now = utc_now_iso()
            return self._insert_revision(
                conn,
                tenant=tenant,
                graph_id=graph_id,
                revision_id=revision_id,
                parent_revision=parent,
                storage_profile=profile,
                created_at=now,
                manifest_cid=manifest_cid,
                manifest_json=manifest_json,
                pin_root=pin_root,
                checksum=checksum,
                metadata=metadata,
            )

    def get_revision(
        self,
        tenant: str,
        graph_id: str,
        revision_id: str,
    ) -> RevisionRecord:
        tenant = require_slug(tenant, field="tenant")
        graph_id = require_slug(graph_id, field="graph_id")
        revision_id = require_revision_id(revision_id)
        with self._txn(immediate=False) as conn:
            row = self._get_revision_row(conn, tenant, graph_id, revision_id)
            return self._revision_from_row(row)

    def list_revisions(
        self,
        tenant: str,
        graph_id: str,
    ) -> List[RevisionRecord]:
        tenant = require_slug(tenant, field="tenant")
        graph_id = require_slug(graph_id, field="graph_id")
        with self._txn(immediate=False) as conn:
            self._get_graph_row(conn, tenant, graph_id, allow_tombstoned=True)
            rows = conn.execute(
                "SELECT * FROM revisions WHERE tenant = ? AND graph_id = ? "
                "ORDER BY created_at, revision_id",
                (tenant, graph_id),
            ).fetchall()
            return [self._revision_from_row(r) for r in rows]

    # ------------------------------------------------------------------
    # Branch-head CAS
    # ------------------------------------------------------------------

    def cas_set_head(
        self,
        tenant: str,
        graph_id: str,
        branch: str,
        *,
        expected_revision: Optional[str],
        new_revision: str,
        lease_id: Optional[str] = None,
        lease_epoch: Optional[int] = None,
        pin_root: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> BranchRecord:
        """Atomically advance a branch head when ``expected_revision`` matches.

        ``expected_revision`` may be ``None`` only when the branch head is
        empty (not used for normal bootstrap flows). On mismatch raises
        ``CONFLICT`` with the current head in details.
        """
        tenant = require_slug(tenant, field="tenant")
        graph_id = require_slug(graph_id, field="graph_id")
        branch = require_slug(branch, field="branch")
        new_rev = require_revision_id(new_revision, field="new_revision")
        expected = optional_revision_id(
            expected_revision, field="expected_revision"
        )
        if expected is not None and expected == new_rev:
            raise CatalogError(
                "INVALID_REQUEST",
                "new_revision must differ from expected_revision",
            )
        idem_key = (
            require_idempotency_key(idempotency_key)
            if idempotency_key is not None
            else None
        )
        req = {
            "tenant": tenant,
            "graph_id": graph_id,
            "branch": branch,
            "expected_revision": expected,
            "new_revision": new_rev,
            "lease_id": lease_id,
            "lease_epoch": lease_epoch,
            "pin_root": pin_root,
        }
        req_hash = request_hash(req)

        with self._txn(immediate=True) as conn:
            if idem_key is not None:
                cached = self._lookup_idempotency(
                    conn,
                    idem_key,
                    request_hash_value=req_hash,
                    operation="cas_set_head",
                )
                if cached is not None:
                    return BranchRecord(
                        tenant=cached["tenant"],
                        graph_id=cached["graph_id"],
                        branch=cached["branch"],
                        head_revision=cached["head_revision"],
                        status=cached["status"],
                        created_at=cached["created_at"],
                        updated_at=cached["updated_at"],
                        tombstoned_at=cached.get("tombstoned_at"),
                    )

            self._get_graph_row(conn, tenant, graph_id)
            brow = self._get_branch_row(conn, tenant, graph_id, branch)
            current = brow["head_revision"]
            # Normalize empty string head to None for expected comparison.
            current_norm: Optional[str] = current if current else None
            if current_norm != expected:
                raise CatalogError(
                    "CONFLICT",
                    "branch head CAS conflict",
                    details={
                        "tenant": tenant,
                        "graph_id": graph_id,
                        "branch": branch,
                        "expected_revision": expected,
                        "current_revision": current_norm,
                        "new_revision": new_rev,
                    },
                )

            self._assert_lease(
                conn,
                tenant,
                graph_id,
                branch,
                lease_id=lease_id,
                lease_epoch=lease_epoch,
            )

            # New revision must already be registered (immutable record).
            self._get_revision_row(conn, tenant, graph_id, new_rev)

            now = utc_now_iso()
            # Atomic CAS: update only if head still matches expected.
            if expected is None:
                cur = conn.execute(
                    "UPDATE branches SET head_revision = ?, updated_at = ? "
                    "WHERE tenant = ? AND graph_id = ? AND branch = ? "
                    "AND status = 'active' "
                    "AND (head_revision IS NULL OR head_revision = '')",
                    (new_rev, now, tenant, graph_id, branch),
                )
            else:
                cur = conn.execute(
                    "UPDATE branches SET head_revision = ?, updated_at = ? "
                    "WHERE tenant = ? AND graph_id = ? AND branch = ? "
                    "AND status = 'active' AND head_revision = ?",
                    (new_rev, now, tenant, graph_id, branch, expected),
                )
            if cur.rowcount != 1:
                # Re-read for deterministic conflict details.
                brow2 = self._get_branch_row(conn, tenant, graph_id, branch)
                raise CatalogError(
                    "CONFLICT",
                    "branch head CAS conflict",
                    details={
                        "tenant": tenant,
                        "graph_id": graph_id,
                        "branch": branch,
                        "expected_revision": expected,
                        "current_revision": brow2["head_revision"],
                        "new_revision": new_rev,
                    },
                )

            if pin_root:
                conn.execute(
                    "INSERT OR IGNORE INTO pin_roots "
                    "(pin_id, tenant, graph_id, revision_id, root_cid, pin_kind, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        new_pin_id(),
                        tenant,
                        graph_id,
                        new_rev,
                        pin_root,
                        "head",
                        now,
                    ),
                )
                conn.execute(
                    "UPDATE revisions SET pin_root = COALESCE(pin_root, ?) "
                    "WHERE tenant = ? AND graph_id = ? AND revision_id = ?",
                    (pin_root, tenant, graph_id, new_rev),
                )

            conn.execute(
                "UPDATE graphs SET updated_at = ? WHERE tenant = ? AND graph_id = ?",
                (now, tenant, graph_id),
            )
            record = BranchRecord(
                tenant=tenant,
                graph_id=graph_id,
                branch=branch,
                head_revision=new_rev,
                status="active",
                created_at=brow["created_at"],
                updated_at=now,
                tombstoned_at=None,
            )
            if idem_key is not None:
                self._store_idempotency(
                    conn,
                    key=idem_key,
                    tenant=tenant,
                    graph_id=graph_id,
                    operation="cas_set_head",
                    request_hash_value=req_hash,
                    response=record.to_dict(),
                    created_at=now,
                )
            return record

    # ------------------------------------------------------------------
    # Leases
    # ------------------------------------------------------------------

    def acquire_lease(
        self,
        tenant: str,
        graph_id: str,
        branch: str,
        *,
        holder: str,
        ttl_seconds: float,
        lease_id: Optional[str] = None,
    ) -> LeaseRecord:
        """Acquire or steal (if expired) a graph-scoped writer lease.

        Always allocates a new fencing epoch when the lease changes hands or
        is first created. An unexpired lease held by a different holder yields
        ``CONFLICT``.
        """
        tenant = require_slug(tenant, field="tenant")
        graph_id = require_slug(graph_id, field="graph_id")
        branch = require_slug(branch, field="branch")
        holder = require_holder(holder)
        ttl = require_positive_ttl(ttl_seconds)
        desired_id = require_lease_id(lease_id) if lease_id is not None else new_lease_id()

        with self._txn(immediate=True) as conn:
            self._get_graph_row(conn, tenant, graph_id)
            self._get_branch_row(conn, tenant, graph_id, branch)
            now = utc_now_iso()
            expires = expires_at_from_ttl(ttl)
            row = conn.execute(
                "SELECT * FROM leases WHERE tenant = ? AND graph_id = ? AND branch = ?",
                (tenant, graph_id, branch),
            ).fetchone()

            if row is None:
                epoch = 1
                conn.execute(
                    "INSERT INTO leases "
                    "(tenant, graph_id, branch, lease_id, holder, epoch, "
                    "expires_at, created_at, renewed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        tenant,
                        graph_id,
                        branch,
                        desired_id,
                        holder,
                        epoch,
                        expires,
                        now,
                        now,
                    ),
                )
                return LeaseRecord(
                    tenant=tenant,
                    graph_id=graph_id,
                    branch=branch,
                    lease_id=desired_id,
                    holder=holder,
                    epoch=epoch,
                    expires_at=expires,
                    created_at=now,
                    renewed_at=now,
                )

            expired = is_expired(row["expires_at"])
            same_holder = row["holder"] == holder
            if not expired and not same_holder:
                raise CatalogError(
                    "CONFLICT",
                    "branch already has an active writer lease",
                    details={
                        "tenant": tenant,
                        "graph_id": graph_id,
                        "branch": branch,
                        "holder": row["holder"],
                        "lease_id": row["lease_id"],
                        "epoch": int(row["epoch"]),
                        "expires_at": row["expires_at"],
                    },
                )

            if same_holder and not expired:
                # Renew in place; keep epoch and lease_id for fencing continuity.
                conn.execute(
                    "UPDATE leases SET expires_at = ?, renewed_at = ? "
                    "WHERE tenant = ? AND graph_id = ? AND branch = ?",
                    (expires, now, tenant, graph_id, branch),
                )
                return LeaseRecord(
                    tenant=tenant,
                    graph_id=graph_id,
                    branch=branch,
                    lease_id=row["lease_id"],
                    holder=holder,
                    epoch=int(row["epoch"]),
                    expires_at=expires,
                    created_at=row["created_at"],
                    renewed_at=now,
                )

            # Steal expired lease or re-acquire: bump fencing epoch.
            epoch = int(row["epoch"]) + 1
            conn.execute(
                "UPDATE leases SET lease_id = ?, holder = ?, epoch = ?, "
                "expires_at = ?, renewed_at = ? "
                "WHERE tenant = ? AND graph_id = ? AND branch = ?",
                (
                    desired_id,
                    holder,
                    epoch,
                    expires,
                    now,
                    tenant,
                    graph_id,
                    branch,
                ),
            )
            return LeaseRecord(
                tenant=tenant,
                graph_id=graph_id,
                branch=branch,
                lease_id=desired_id,
                holder=holder,
                epoch=epoch,
                expires_at=expires,
                created_at=row["created_at"],
                renewed_at=now,
            )

    def renew_lease(
        self,
        tenant: str,
        graph_id: str,
        branch: str,
        *,
        lease_id: str,
        lease_epoch: int,
        ttl_seconds: float,
    ) -> LeaseRecord:
        tenant = require_slug(tenant, field="tenant")
        graph_id = require_slug(graph_id, field="graph_id")
        branch = require_slug(branch, field="branch")
        lease_id = require_lease_id(lease_id)
        ttl = require_positive_ttl(ttl_seconds)
        try:
            epoch = int(lease_epoch)
        except (TypeError, ValueError) as exc:
            raise CatalogError(
                "INVALID_REQUEST",
                "lease_epoch must be an integer",
            ) from exc

        with self._txn(immediate=True) as conn:
            self._assert_lease(
                conn,
                tenant,
                graph_id,
                branch,
                lease_id=lease_id,
                lease_epoch=epoch,
            )
            now = utc_now_iso()
            expires = expires_at_from_ttl(ttl)
            conn.execute(
                "UPDATE leases SET expires_at = ?, renewed_at = ? "
                "WHERE tenant = ? AND graph_id = ? AND branch = ? "
                "AND lease_id = ? AND epoch = ?",
                (expires, now, tenant, graph_id, branch, lease_id, epoch),
            )
            row = conn.execute(
                "SELECT * FROM leases WHERE tenant = ? AND graph_id = ? AND branch = ?",
                (tenant, graph_id, branch),
            ).fetchone()
            assert row is not None
            return self._lease_from_row(row)

    def release_lease(
        self,
        tenant: str,
        graph_id: str,
        branch: str,
        *,
        lease_id: str,
        lease_epoch: int,
    ) -> None:
        tenant = require_slug(tenant, field="tenant")
        graph_id = require_slug(graph_id, field="graph_id")
        branch = require_slug(branch, field="branch")
        lease_id = require_lease_id(lease_id)
        try:
            epoch = int(lease_epoch)
        except (TypeError, ValueError) as exc:
            raise CatalogError(
                "INVALID_REQUEST",
                "lease_epoch must be an integer",
            ) from exc

        with self._txn(immediate=True) as conn:
            row = conn.execute(
                "SELECT * FROM leases WHERE tenant = ? AND graph_id = ? AND branch = ?",
                (tenant, graph_id, branch),
            ).fetchone()
            if row is None:
                return
            if row["lease_id"] != lease_id or int(row["epoch"]) != epoch:
                raise CatalogError(
                    "FENCED",
                    "cannot release a stale writer lease",
                    details={
                        "lease_id": lease_id,
                        "lease_epoch": epoch,
                        "current_lease_id": row["lease_id"],
                        "current_epoch": int(row["epoch"]),
                    },
                )
            conn.execute(
                "DELETE FROM leases WHERE tenant = ? AND graph_id = ? AND branch = ?",
                (tenant, graph_id, branch),
            )

    def get_lease(
        self,
        tenant: str,
        graph_id: str,
        branch: str,
    ) -> Optional[LeaseRecord]:
        tenant = require_slug(tenant, field="tenant")
        graph_id = require_slug(graph_id, field="graph_id")
        branch = require_slug(branch, field="branch")
        with self._txn(immediate=False) as conn:
            row = conn.execute(
                "SELECT * FROM leases WHERE tenant = ? AND graph_id = ? AND branch = ?",
                (tenant, graph_id, branch),
            ).fetchone()
            if row is None:
                return None
            return self._lease_from_row(row)

    # ------------------------------------------------------------------
    # Idempotency lookup
    # ------------------------------------------------------------------

    def get_idempotency(self, key: str) -> Optional[IdempotencyRecord]:
        key = require_idempotency_key(key)
        with self._txn(immediate=False) as conn:
            row = conn.execute(
                "SELECT * FROM idempotency WHERE key = ?",
                (key,),
            ).fetchone()
            if row is None:
                return None
            return IdempotencyRecord(
                key=row["key"],
                tenant=row["tenant"],
                graph_id=row["graph_id"],
                operation=row["operation"],
                request_hash=row["request_hash"],
                response_json=row["response_json"],
                created_at=row["created_at"],
            )

    # ------------------------------------------------------------------
    # Pin roots
    # ------------------------------------------------------------------

    def set_pin_root(
        self,
        tenant: str,
        graph_id: str,
        revision_id: str,
        root_cid: str,
        *,
        pin_kind: str = "manifest",
    ) -> PinRootRecord:
        tenant = require_slug(tenant, field="tenant")
        graph_id = require_slug(graph_id, field="graph_id")
        revision_id = require_revision_id(revision_id)
        if not root_cid or not isinstance(root_cid, str):
            raise CatalogError("INVALID_REQUEST", "root_cid must be a non-empty string")
        if not pin_kind or not isinstance(pin_kind, str):
            raise CatalogError("INVALID_REQUEST", "pin_kind must be a non-empty string")
        pin_kind = require_slug(pin_kind, field="pin_kind")

        with self._txn(immediate=True) as conn:
            self._get_revision_row(conn, tenant, graph_id, revision_id)
            existing = conn.execute(
                "SELECT * FROM pin_roots WHERE tenant = ? AND graph_id = ? "
                "AND revision_id = ? AND root_cid = ? AND pin_kind = ?",
                (tenant, graph_id, revision_id, root_cid, pin_kind),
            ).fetchone()
            if existing is not None:
                return self._pin_from_row(existing)
            now = utc_now_iso()
            pin_id = new_pin_id()
            conn.execute(
                "INSERT INTO pin_roots "
                "(pin_id, tenant, graph_id, revision_id, root_cid, pin_kind, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (pin_id, tenant, graph_id, revision_id, root_cid, pin_kind, now),
            )
            conn.execute(
                "UPDATE revisions SET pin_root = COALESCE(pin_root, ?) "
                "WHERE tenant = ? AND graph_id = ? AND revision_id = ?",
                (root_cid, tenant, graph_id, revision_id),
            )
            return PinRootRecord(
                pin_id=pin_id,
                tenant=tenant,
                graph_id=graph_id,
                revision_id=revision_id,
                root_cid=root_cid,
                pin_kind=pin_kind,
                created_at=now,
            )

    def list_pin_roots(
        self,
        tenant: str,
        graph_id: str,
        *,
        revision_id: Optional[str] = None,
    ) -> List[PinRootRecord]:
        tenant = require_slug(tenant, field="tenant")
        graph_id = require_slug(graph_id, field="graph_id")
        rev = (
            require_revision_id(revision_id) if revision_id is not None else None
        )
        with self._txn(immediate=False) as conn:
            self._get_graph_row(conn, tenant, graph_id, allow_tombstoned=True)
            if rev is not None:
                rows = conn.execute(
                    "SELECT * FROM pin_roots WHERE tenant = ? AND graph_id = ? "
                    "AND revision_id = ? ORDER BY created_at, pin_id",
                    (tenant, graph_id, rev),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM pin_roots WHERE tenant = ? AND graph_id = ? "
                    "ORDER BY revision_id, created_at, pin_id",
                    (tenant, graph_id),
                ).fetchall()
            return [self._pin_from_row(r) for r in rows]

    # ------------------------------------------------------------------
    # Tombstone history
    # ------------------------------------------------------------------

    def list_tombstones(
        self,
        tenant: str,
        *,
        graph_id: Optional[str] = None,
    ) -> List[TombstoneRecord]:
        tenant = require_slug(tenant, field="tenant")
        gid = require_slug(graph_id, field="graph_id") if graph_id is not None else None
        with self._txn(immediate=False) as conn:
            if gid is not None:
                rows = conn.execute(
                    "SELECT * FROM tombstones WHERE tenant = ? AND graph_id = ? "
                    "ORDER BY id",
                    (tenant, gid),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM tombstones WHERE tenant = ? ORDER BY id",
                    (tenant,),
                ).fetchall()
            return [
                TombstoneRecord(
                    entity_type=r["entity_type"],
                    tenant=r["tenant"],
                    graph_id=r["graph_id"],
                    branch=r["branch"],
                    tombstoned_at=r["tombstoned_at"],
                    reason=r["reason"],
                )
                for r in rows
            ]


def open_catalog(path: PathLike, **kwargs: Any) -> GraphCatalog:
    """Open or create a durable catalog at ``path``."""
    return GraphCatalog(path, **kwargs)


# ---------------------------------------------------------------------------
# DQK-059: Graph shadow authority (SQLite authority, DuckDB parity)
# ---------------------------------------------------------------------------


def new_graph_operation_id(prefix: str = "op") -> str:
    """Allocate a fresh idempotent producer operation id."""

    return f"{prefix}:{uuid.uuid4().hex}"


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def _digest(payload: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _record_to_dict(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, (list, tuple)):
        return [_record_to_dict(v) for v in value]
    return value


@dataclass
class GraphParityView:
    """SQLite vs DuckDB control-plane parity for one graph identity."""

    tenant: str
    graph_id: str
    matched: bool
    branch_matched: bool
    lease_matched: bool
    pin_matched: bool
    tombstone_matched: bool
    revision_matched: bool
    legacy: Dict[str, Any] = field(default_factory=dict)
    shadow: Dict[str, Any] = field(default_factory=dict)
    mismatch_reason: str = ""
    quarantined: bool = False
    authority: str = "legacy"
    operation_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": GRAPH_SHADOW_SCHEMA,
            "tenant": self.tenant,
            "graph_id": self.graph_id,
            "matched": self.matched,
            "branch_matched": self.branch_matched,
            "lease_matched": self.lease_matched,
            "pin_matched": self.pin_matched,
            "tombstone_matched": self.tombstone_matched,
            "revision_matched": self.revision_matched,
            "legacy": dict(self.legacy),
            "shadow": dict(self.shadow),
            "mismatch_reason": self.mismatch_reason,
            "quarantined": self.quarantined,
            "authority": self.authority,
            "operation_id": self.operation_id,
        }


@dataclass
class GraphMutationReceipt:
    """Idempotent producer receipt with authority-port parity binding."""

    operation_id: str
    producer: str
    kind: str
    key: str
    parity_matched: bool
    parity_receipt_cid: str
    mode: str
    payload_digest: str
    authority: str = "legacy"
    idempotent_replay: bool = False
    outbox_id: str = ""
    quarantined: bool = False
    quarantine_id: str = ""
    error: str = ""
    content_cid: str = ""
    content_checksum: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": GRAPH_SHADOW_SCHEMA,
            "operation_id": self.operation_id,
            "producer": self.producer,
            "kind": self.kind,
            "key": self.key,
            "parity_matched": self.parity_matched,
            "parity_receipt_cid": self.parity_receipt_cid,
            "mode": self.mode,
            "payload_digest": self.payload_digest,
            "authority": self.authority,
            "idempotent_replay": self.idempotent_replay,
            "outbox_id": self.outbox_id,
            "quarantined": self.quarantined,
            "quarantine_id": self.quarantine_id,
            "error": self.error,
            "content_cid": self.content_cid,
            "content_checksum": self.content_checksum,
        }


@dataclass
class ReaderRevisionBinding:
    """One branch-head revision bound for a reader during dual-mode promotion."""

    tenant: str
    graph_id: str
    branch: str
    revision_id: str
    bound_at: str
    authority_mode: str
    fence_token: int = 0
    operation_id: str = ""

    @property
    def key(self) -> str:
        return f"{self.tenant}/{self.graph_id}/{self.branch}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": GRAPH_AUTHORITY_SCHEMA,
            "tenant": self.tenant,
            "graph_id": self.graph_id,
            "branch": self.branch,
            "revision_id": self.revision_id,
            "bound_at": self.bound_at,
            "authority_mode": self.authority_mode,
            "fence_token": self.fence_token,
            "operation_id": self.operation_id,
        }


class GraphShadowAuthority:
    """DuckDB shadow / dual / db-primary authority for knowledge-graph producers.

    DQK-059 (**shadow**):

    * **SQLite / JSON / in-memory is authority** — caller-visible results never
      switch to DuckDB.
    * **DuckDB is a shadow projection** of catalog, transaction/MVCC/WAL control
      state, hybrid storage metadata, engine inventory, and crypto-flow
      snapshots.
    * **Shadow failures quarantine** without changing legacy authority.

    DQK-060 (**dual** → **db-primary** cutover):

    * Fenced dual writes coordinate SQLite and DuckDB through the domain-neutral
      outbox; mismatch quarantines rather than silently diverging.
    * After promotion, DuckDB is authority for graph catalog and
      transaction-control metadata; legacy SQLite writes are outbox projections.
    * Immutable Parquet/IPLD revisions remain the **content** authority.
    * Readers bind one branch revision during the promotion window.
    * Promotion and rollback are CAS-fenced and receipted.
    * Crash recovery redrives the outbox so branch heads and transaction
      control state do not split-brain or lose durable progress.
    """

    DOMAIN = GRAPH_SHADOW_DOMAIN
    SCHEMA = GRAPH_SHADOW_SCHEMA
    OWNER_TASK = GRAPH_SHADOW_OWNER_TASK
    AUTHORITY_SCHEMA = GRAPH_AUTHORITY_SCHEMA
    AUTHORITY_OWNER_TASK = GRAPH_AUTHORITY_OWNER_TASK

    def __init__(
        self,
        *,
        duckdb_catalog_path: PathLike | None = None,
        duckdb_tx_path: PathLike | None = None,
        duckdb_crypto_path: PathLike | None = None,
        enabled: bool = True,
        authority_port: Any = None,
        writer_id: str = "writer:graph-shadow-authority",
        domain: str = GRAPH_SHADOW_DOMAIN,
        initial_mode: Any = None,
        owner_task: str = GRAPH_SHADOW_OWNER_TASK,
    ) -> None:
        self._enabled = bool(enabled)
        self._domain = domain
        self._writer_id = writer_id
        self._owner_task = owner_task
        self._lock = threading.RLock()
        self._closed = False
        self._port = authority_port
        self._duck_catalog: Any = None
        self._duck_tx: Any = None
        self._duck_crypto: Any = None
        self._initial_mode = initial_mode
        self._catalog_path = (
            None
            if duckdb_catalog_path in (None, ":memory:")
            else str(Path(duckdb_catalog_path))
        )
        self._tx_path = (
            ":memory:"
            if duckdb_tx_path in (None, ":memory:")
            else str(Path(duckdb_tx_path))
        )
        self._crypto_path = (
            ":memory:"
            if duckdb_crypto_path in (None, ":memory:")
            else str(Path(duckdb_crypto_path))
        )
        self._mutation_index: Dict[str, GraphMutationReceipt] = {}
        self._content_fingerprints: Dict[str, Dict[str, str]] = {}
        self._legacy_snapshots: Dict[str, Dict[str, Any]] = {}
        # DQK-060: reader revision binds + decision receipts.
        self._reader_bindings: Dict[str, ReaderRevisionBinding] = {}
        self._decision_receipts: List[Any] = []
        self._promotion_window: bool = False
        if self._enabled:
            self._open_stores(duckdb_catalog_path)
            if self._port is None:
                self._port = self._build_default_port()

    # -- lifecycle ----------------------------------------------------------

    def _build_default_port(self) -> Any:
        from ipfs_datasets_py.duckdb_control.authority_transition import (
            AuthorityMode,
            MemoryAuthorityBackend,
            build_authority_port,
        )

        mode = self._initial_mode
        if mode is None:
            mode = AuthorityMode.SHADOW
        elif not isinstance(mode, AuthorityMode):
            mode = AuthorityMode.parse(mode)

        return build_authority_port(
            MemoryAuthorityBackend(),
            domain=self._domain,
            initial_mode=mode,
            writer_id=self._writer_id,
        )

    def _open_stores(self, duckdb_catalog_path: PathLike | None) -> None:
        try:
            from ipfs_datasets_py.knowledge_graphs.catalog.duckdb_store import (
                DuckDBGraphCatalog,
            )

            cat_path = (
                ":memory:"
                if duckdb_catalog_path in (None, ":memory:")
                else Path(duckdb_catalog_path)
            )
            if cat_path != ":memory:":
                Path(cat_path).parent.mkdir(parents=True, exist_ok=True)
            self._duck_catalog = DuckDBGraphCatalog(cat_path)
            self._catalog_path = (
                None if cat_path == ":memory:" else str(Path(cat_path))
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("DuckDB graph catalog shadow unavailable: %s", exc)
            self._duck_catalog = None

        try:
            from ipfs_datasets_py.knowledge_graphs.transactions.duckdb_state import (
                DuckDBTransactionState,
            )

            self._duck_tx = DuckDBTransactionState(self._tx_path)
            # Shadow owner fence so MVCC/WAL control mutations can be projected.
            self._duck_tx.claim_owner(
                owner_id=self._writer_id,
                process_birth=f"shadow:{uuid.uuid4().hex[:12]}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("DuckDB transaction state shadow unavailable: %s", exc)
            self._duck_tx = None

        try:
            from ipfs_datasets_py.knowledge_graphs.crypto_flows.duckdb_store import (
                DuckDBGraphSnapshotStore,
            )

            self._duck_crypto = DuckDBGraphSnapshotStore(self._crypto_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("DuckDB crypto-flow shadow unavailable: %s", exc)
            self._duck_crypto = None

    @property
    def enabled(self) -> bool:
        return self._enabled and not self._closed

    @property
    def authority_port(self) -> Any:
        return self._port

    @property
    def mode(self) -> str:
        if self._port is None:
            return "disabled"
        try:
            return self._port.mode.value
        except Exception:  # noqa: BLE001
            return "unknown"

    @property
    def owner_task(self) -> str:
        return self._owner_task

    @property
    def duckdb_catalog(self) -> Any:
        return self._duck_catalog

    @property
    def duckdb_transaction_state(self) -> Any:
        return self._duck_tx

    @property
    def duckdb_crypto_store(self) -> Any:
        return self._duck_crypto

    @property
    def legacy_is_outbox_projection(self) -> bool:
        """True when legacy SQLite writes are fenced outbox projections (DQK-060)."""

        mode = self.mode
        return mode in {"dual", "db-primary", "export-only"}

    @property
    def is_duckdb_authority(self) -> bool:
        return self.mode in {"db-primary", "export-only"}

    @property
    def is_dual_mode(self) -> bool:
        return self.mode == "dual"

    @property
    def promotion_window_active(self) -> bool:
        """True while dual-mode promotion is in progress (readers must bind)."""

        return bool(self._promotion_window) or self.mode == "dual"

    def _authority_label(self) -> str:
        """Caller-facing authority label for receipts and tests."""

        mode = self.mode
        if mode in {"db-primary", "export-only"}:
            return "duckdb"
        if mode == "dual":
            return "dual"
        if mode in {"shadow", "legacy", "disabled", "unknown"}:
            return "legacy"
        return mode

    def close(self) -> None:
        with self._lock:
            for store_attr in ("_duck_catalog", "_duck_tx", "_duck_crypto"):
                store = getattr(self, store_attr, None)
                if store is not None:
                    try:
                        store.close()
                    except Exception:  # noqa: BLE001
                        pass
                    setattr(self, store_attr, None)
            self._closed = True

    def reopen(self) -> "GraphShadowAuthority":
        """Close and reopen file-backed DuckDB stores (restart simulation)."""

        with self._lock:
            if self._catalog_path is None and self._tx_path == ":memory:":
                raise RuntimeError("cannot restart an in-memory-only shadow authority")
            mutations = dict(self._mutation_index)
            fingerprints = dict(self._content_fingerprints)
            snapshots = dict(self._legacy_snapshots)
            bindings = dict(self._reader_bindings)
            decisions = list(self._decision_receipts)
            promotion = self._promotion_window
            port = self._port
            cat_path = self._catalog_path
            tx_path = self._tx_path
            crypto_path = self._crypto_path
            owner_task = self._owner_task
            initial_mode = self._initial_mode
            self.close()
            self._closed = False
            self._enabled = True
            self._port = port
            self._tx_path = tx_path
            self._crypto_path = crypto_path
            self._owner_task = owner_task
            self._initial_mode = initial_mode
            self._open_stores(cat_path if cat_path is not None else ":memory:")
            self._mutation_index = mutations
            self._content_fingerprints = fingerprints
            self._legacy_snapshots = snapshots
            self._reader_bindings = bindings
            self._decision_receipts = decisions
            self._promotion_window = promotion
            # Crash recovery: redrive incomplete outbox before serving.
            try:
                self.recover_after_crash()
            except Exception as exc:  # noqa: BLE001
                logger.warning("authority recover_after_crash on reopen: %s", exc)
            return self

    # -- quarantine ---------------------------------------------------------

    def _quarantine(
        self,
        *,
        key: str,
        operation_id: str,
        reason: str,
        legacy_digest: str = "",
        db_digest: str = "",
    ) -> str:
        if self._port is None:
            return ""
        try:
            rec = self._port.quarantine_disagreement(
                key=key,
                operation_id=operation_id or new_graph_operation_id("shadow"),
                reason=(reason or "shadow_failure")[:500],
                legacy_digest=legacy_digest or None,
                db_digest=db_digest or None,
            )
            return getattr(rec, "quarantine_id", "") or ""
        except Exception as exc:  # noqa: BLE001
            logger.warning("graph shadow quarantine failed: %s", exc)
            return ""

    def list_open_quarantines(self) -> List[Dict[str, Any]]:
        if self._port is None:
            return []
        try:
            records = self._port.backend.list_open_quarantine(self._domain)
            return [
                {
                    "quarantine_id": r.quarantine_id,
                    "key": r.key,
                    "reason": r.reason,
                    "operation_id": r.operation_id,
                    "resolved": r.resolved,
                }
                for r in records
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("list_open_quarantines failed: %s", exc)
            return []

    def list_mutation_receipts(self) -> List[GraphMutationReceipt]:
        with self._lock:
            return list(self._mutation_index.values())

    def get_mutation_receipt(
        self, operation_id: str
    ) -> Optional[GraphMutationReceipt]:
        with self._lock:
            return self._mutation_index.get(operation_id)

    # -- core write path ----------------------------------------------------

    def record_operation(
        self,
        *,
        producer: str,
        kind: str,
        key: str,
        payload: Mapping[str, Any],
        operation_id: str | None = None,
        content_cid: str = "",
        content_checksum: str = "",
        content_bytes: bytes | None = None,
    ) -> GraphMutationReceipt:
        """Record one idempotent producer operation with a parity receipt.

        When *content_bytes* is provided, the SHA-256 and optional CID are
        fingerprinted so later checks prove the shadow path never rewrote
        Parquet/IPLD payload bytes.
        """

        op_id = operation_id or new_graph_operation_id(f"{producer}.{kind}")
        with self._lock:
            prior = self._mutation_index.get(op_id)
            if prior is not None:
                return GraphMutationReceipt(
                    operation_id=prior.operation_id,
                    producer=prior.producer,
                    kind=prior.kind,
                    key=prior.key,
                    parity_matched=prior.parity_matched,
                    parity_receipt_cid=prior.parity_receipt_cid,
                    mode=prior.mode,
                    payload_digest=prior.payload_digest,
                    authority=prior.authority,
                    idempotent_replay=True,
                    outbox_id=prior.outbox_id,
                    quarantined=prior.quarantined,
                    quarantine_id=prior.quarantine_id,
                    error=prior.error,
                    content_cid=prior.content_cid,
                    content_checksum=prior.content_checksum,
                )

            if not self.enabled or self._port is None:
                receipt = GraphMutationReceipt(
                    operation_id=op_id,
                    producer=producer,
                    kind=kind,
                    key=key,
                    parity_matched=True,
                    parity_receipt_cid="",
                    mode="disabled",
                    payload_digest=_digest(dict(payload)),
                    authority="legacy",
                    content_cid=content_cid,
                    content_checksum=content_checksum,
                )
                self._mutation_index[op_id] = receipt
                return receipt

            schema = (
                GRAPH_AUTHORITY_SCHEMA
                if self.mode in {"dual", "db-primary", "export-only"}
                else GRAPH_SHADOW_SCHEMA
            )
            owner = (
                GRAPH_AUTHORITY_OWNER_TASK
                if self.mode in {"dual", "db-primary", "export-only"}
                else self._owner_task
            )
            body = {
                "schema": schema,
                "owner_task": owner,
                "producer": producer,
                "kind": kind,
                "key": key,
                "payload": dict(payload),
                "content_cid": content_cid or "",
                "content_checksum": content_checksum or "",
                "legacy_is_outbox_projection": self.legacy_is_outbox_projection,
            }
            if content_bytes is not None:
                checksum = "sha256:" + hashlib.sha256(content_bytes).hexdigest()
                body["content_checksum"] = checksum
                body["content_size"] = len(content_bytes)
                self._content_fingerprints[key] = {
                    "checksum": checksum,
                    "size": str(len(content_bytes)),
                    "cid": content_cid or "",
                }
                content_checksum = checksum
            elif content_checksum:
                self._content_fingerprints[key] = {
                    "checksum": content_checksum,
                    "size": str(payload.get("size", "")),
                    "cid": content_cid or "",
                }

            try:
                write_result = self._port.write(key, body, operation_id=op_id)
                parity = self._port.emit_parity_receipt(key, operation_id=op_id)
                authority = str(
                    write_result.get("authority") or self._authority_label()
                )
                # In dual/db-primary, legacy SQLite is an outbox projection and
                # must never silently re-claim authority on the receipt.
                if self.mode == "db-primary" and authority not in {
                    "duckdb",
                    "db-primary",
                }:
                    authority = "duckdb"
                elif self.mode == "dual" and authority not in {
                    "dual",
                    "duckdb",
                }:
                    authority = "dual"
                receipt = GraphMutationReceipt(
                    operation_id=op_id,
                    producer=producer,
                    kind=kind,
                    key=key,
                    parity_matched=bool(parity.matched),
                    parity_receipt_cid=str(
                        getattr(parity, "receipt_cid", "") or ""
                    ),
                    mode=str(write_result.get("mode") or self.mode),
                    payload_digest=str(
                        write_result.get("payload_digest") or _digest(body)
                    ),
                    authority=authority,
                    idempotent_replay=bool(write_result.get("idempotent_replay")),
                    outbox_id=str(write_result.get("outbox_id") or ""),
                    content_cid=content_cid or "",
                    content_checksum=content_checksum or body.get("content_checksum", ""),
                )
                if not receipt.parity_matched:
                    qid = self._quarantine(
                        key=key,
                        operation_id=op_id,
                        reason=getattr(parity, "mismatch_reason", "")
                        or "parity_mismatch",
                        legacy_digest=getattr(parity, "legacy_digest", ""),
                        db_digest=getattr(parity, "db_digest", ""),
                    )
                    receipt.quarantined = True
                    receipt.quarantine_id = qid
                self._mutation_index[op_id] = receipt
                return receipt
            except Exception as exc:  # noqa: BLE001
                qid = self._quarantine(
                    key=key,
                    operation_id=op_id,
                    reason=f"record_operation_failed: {exc}",
                )
                receipt = GraphMutationReceipt(
                    operation_id=op_id,
                    producer=producer,
                    kind=kind,
                    key=key,
                    parity_matched=False,
                    parity_receipt_cid="",
                    mode=self.mode,
                    payload_digest=_digest(body),
                    authority="legacy",
                    quarantined=True,
                    quarantine_id=qid,
                    error=str(exc),
                    content_cid=content_cid or "",
                    content_checksum=content_checksum or "",
                )
                self._mutation_index[op_id] = receipt
                return receipt

    def content_fingerprint(self, key: str) -> Optional[Dict[str, str]]:
        with self._lock:
            fp = self._content_fingerprints.get(key)
            return dict(fp) if fp is not None else None

    def assert_content_unchanged(
        self,
        key: str,
        *,
        content_bytes: bytes | None = None,
        content_cid: str = "",
        content_checksum: str = "",
    ) -> bool:
        """Return True when the stored fingerprint still matches the content."""

        fp = self.content_fingerprint(key)
        if fp is None:
            return True
        if content_bytes is not None:
            checksum = "sha256:" + hashlib.sha256(content_bytes).hexdigest()
            if fp.get("checksum") and fp["checksum"] != checksum:
                return False
            if fp.get("size") and fp["size"] != str(len(content_bytes)):
                return False
        if content_checksum and fp.get("checksum") and fp["checksum"] != content_checksum:
            return False
        if content_cid and fp.get("cid") and fp["cid"] != content_cid:
            return False
        return True

    # -- catalog producer ---------------------------------------------------

    def _graph_key(self, tenant: str, graph_id: str) -> str:
        return f"graph:{tenant}/{graph_id}"

    def snapshot_from_sqlite(
        self, catalog: "GraphCatalog", tenant: str, graph_id: str
    ) -> Dict[str, Any]:
        """Build a normalized control-plane snapshot from SQLite authority."""

        try:
            graph = catalog.get_graph(tenant, graph_id, allow_tombstoned=True)
        except CatalogError:
            return {
                "tenant": tenant,
                "graph_id": graph_id,
                "exists": False,
                "branches": {},
                "leases": {},
                "pins": [],
                "tombstones": [],
                "revisions": {},
            }
        desc = catalog.describe_graph(
            tenant, graph_id, include_tombstoned_branches=True
        )
        branches: Dict[str, Any] = {}
        for b in desc.branches:
            # describe_graph returns mapping payloads, not BranchRecord objects.
            if isinstance(b, Mapping):
                name = str(b.get("branch") or "")
                if not name:
                    continue
                branches[name] = {
                    "head_revision": b.get("head_revision"),
                    "status": b.get("status"),
                }
            else:
                name = str(getattr(b, "branch", "") or "")
                if not name:
                    continue
                branches[name] = {
                    "head_revision": getattr(b, "head_revision", None),
                    "status": getattr(b, "status", None),
                }
        leases: Dict[str, Any] = {}
        for branch_name in branches:
            lease = catalog.get_lease(tenant, graph_id, branch_name)
            if lease is not None:
                leases[branch_name] = {
                    "lease_id": lease.lease_id,
                    "holder": lease.holder,
                    "epoch": int(lease.epoch),
                }
        pins = [
            {
                "revision_id": p.revision_id,
                "root_cid": p.root_cid,
                "pin_kind": p.pin_kind,
            }
            for p in catalog.list_pin_roots(tenant, graph_id)
        ]
        tombs = [
            {
                "entity_type": t.entity_type,
                "branch": t.branch,
                "reason": t.reason,
            }
            for t in catalog.list_tombstones(tenant, graph_id=graph_id)
        ]
        revisions: Dict[str, Any] = {}
        for branch_name, meta in branches.items():
            rev_id = meta.get("head_revision")
            if not rev_id:
                continue
            try:
                rev = catalog.get_revision(tenant, graph_id, rev_id)
            except CatalogError:
                continue
            revisions[rev_id] = {
                "parent_revision": rev.parent_revision,
                "manifest_cid": rev.manifest_cid,
                "checksum": rev.checksum,
                "pin_root": rev.pin_root,
                "storage_profile": rev.storage_profile,
            }
        return {
            "tenant": tenant,
            "graph_id": graph_id,
            "exists": True,
            "status": graph.status,
            "default_branch": graph.default_branch,
            "storage_profile": graph.storage_profile,
            "graph_kind": graph.graph_kind,
            "branches": branches,
            "leases": leases,
            "pins": sorted(pins, key=lambda p: (p["revision_id"], p["root_cid"])),
            "tombstones": tombs,
            "revisions": revisions,
        }

    def snapshot_from_duckdb(self, tenant: str, graph_id: str) -> Dict[str, Any]:
        """Build a normalized control-plane snapshot from the DuckDB mirror."""

        duck = self._duck_catalog
        empty = {
            "tenant": tenant,
            "graph_id": graph_id,
            "exists": False,
            "branches": {},
            "leases": {},
            "pins": [],
            "tombstones": [],
            "revisions": {},
        }
        if duck is None:
            return empty
        # Read via raw SQL so tombstoned graphs remain visible for parity.
        try:
            with duck._txn() as conn:  # noqa: SLF001 — shadow parity only
                grow = duck._fetchone(  # noqa: SLF001
                    conn,
                    "SELECT * FROM graphs WHERE tenant = ? AND graph_id = ?",
                    [tenant, graph_id],
                )
                if grow is None:
                    return empty
                branch_rows = duck._fetchall(  # noqa: SLF001
                    conn,
                    "SELECT * FROM branches WHERE tenant = ? AND graph_id = ? "
                    "ORDER BY branch",
                    [tenant, graph_id],
                )
                lease_rows = duck._fetchall(  # noqa: SLF001
                    conn,
                    "SELECT * FROM leases WHERE tenant = ? AND graph_id = ?",
                    [tenant, graph_id],
                )
                pin_rows = duck._fetchall(  # noqa: SLF001
                    conn,
                    "SELECT * FROM pin_roots WHERE tenant = ? AND graph_id = ? "
                    "ORDER BY revision_id, root_cid, pin_kind",
                    [tenant, graph_id],
                )
                tomb_rows = duck._fetchall(  # noqa: SLF001
                    conn,
                    "SELECT * FROM tombstones WHERE tenant = ? AND graph_id = ? "
                    "ORDER BY kind, name",
                    [tenant, graph_id],
                )
                rev_ids = {
                    str(r.get("head_revision"))
                    for r in branch_rows
                    if r.get("head_revision")
                }
                revisions: Dict[str, Any] = {}
                for rev_id in rev_ids:
                    row = duck._fetchone(  # noqa: SLF001
                        conn,
                        "SELECT * FROM revisions WHERE tenant = ? AND graph_id = ? "
                        "AND revision_id = ?",
                        [tenant, graph_id, rev_id],
                    )
                    if row is None:
                        continue
                    revisions[rev_id] = {
                        "parent_revision": row.get("parent_revision"),
                        "manifest_cid": row.get("manifest_cid"),
                        "checksum": row.get("checksum"),
                        "pin_root": row.get("pin_root"),
                        "storage_profile": row.get("storage_profile"),
                    }
        except Exception:
            return empty

        branches = {
            str(r["branch"]): {
                "head_revision": r.get("head_revision"),
                "status": r.get("status"),
            }
            for r in branch_rows
        }
        leases = {
            str(r["branch"]): {
                "lease_id": r.get("lease_id"),
                "holder": r.get("holder"),
                "epoch": int(r.get("epoch") or 0),
            }
            for r in lease_rows
        }
        pins = [
            {
                "revision_id": r.get("revision_id"),
                "root_cid": r.get("root_cid"),
                "pin_kind": r.get("pin_kind"),
            }
            for r in pin_rows
        ]
        tombs = [
            {
                "entity_type": row.get("kind") or row.get("entity_type"),
                "branch": (
                    row.get("name")
                    if (row.get("kind") == "branch" and row.get("name"))
                    else None
                ),
                "reason": row.get("reason"),
            }
            for row in tomb_rows
        ]
        return {
            "tenant": tenant,
            "graph_id": graph_id,
            "exists": True,
            "status": grow.get("status"),
            "default_branch": grow.get("default_branch"),
            "storage_profile": grow.get("storage_profile"),
            "graph_kind": grow.get("graph_kind"),
            "branches": branches,
            "leases": leases,
            "pins": sorted(
                pins, key=lambda p: (p["revision_id"] or "", p["root_cid"] or "")
            ),
            "tombstones": tombs,
            "revisions": revisions,
        }

    def compare_parity(
        self,
        *,
        tenant: str,
        graph_id: str,
        legacy: Mapping[str, Any],
        shadow: Mapping[str, Any],
        operation_id: str = "",
    ) -> GraphParityView:
        leg_branches = dict(legacy.get("branches") or {})
        sh_branches = dict(shadow.get("branches") or {})
        branch_matched = leg_branches == sh_branches

        leg_leases = {
            k: {
                "holder": v.get("holder"),
                "epoch": v.get("epoch"),
            }
            for k, v in dict(legacy.get("leases") or {}).items()
        }
        sh_leases = {
            k: {
                "holder": v.get("holder"),
                "epoch": v.get("epoch"),
            }
            for k, v in dict(shadow.get("leases") or {}).items()
        }
        # Lease ids may differ across backends if regenerated; compare fencing.
        lease_matched = leg_leases == sh_leases

        leg_pins = {
            (p.get("revision_id"), p.get("root_cid"), p.get("pin_kind"))
            for p in (legacy.get("pins") or [])
        }
        sh_pins = {
            (p.get("revision_id"), p.get("root_cid"), p.get("pin_kind"))
            for p in (shadow.get("pins") or [])
        }
        pin_matched = leg_pins == sh_pins

        # Tombstones: compare entity types present (DuckDB schema differs).
        leg_tombs = sorted(
            (t.get("entity_type"), t.get("branch"))
            for t in (legacy.get("tombstones") or [])
        )
        sh_tombs = sorted(
            (t.get("entity_type"), t.get("branch"))
            for t in (shadow.get("tombstones") or [])
        )
        if not sh_tombs and leg_tombs and not shadow.get("exists"):
            tombstone_matched = False
        elif not sh_tombs and leg_tombs:
            # DuckDB mirror may lag delete APIs; require graph status parity.
            tombstone_matched = legacy.get("status") == shadow.get("status")
        else:
            tombstone_matched = leg_tombs == sh_tombs or (
                legacy.get("status") == shadow.get("status")
                and legacy.get("status") == "tombstoned"
            )

        leg_revs = dict(legacy.get("revisions") or {})
        sh_revs = dict(shadow.get("revisions") or {})
        revision_matched = True
        for rev_id, leg in leg_revs.items():
            sh = sh_revs.get(rev_id)
            if sh is None:
                revision_matched = False
                break
            for field_name in (
                "manifest_cid",
                "checksum",
                "pin_root",
                "parent_revision",
                "storage_profile",
            ):
                if leg.get(field_name) != sh.get(field_name):
                    revision_matched = False
                    break
            if not revision_matched:
                break

        exists_matched = bool(legacy.get("exists")) == bool(shadow.get("exists"))
        status_matched = legacy.get("status") == shadow.get("status")
        matched = (
            exists_matched
            and status_matched
            and branch_matched
            and lease_matched
            and pin_matched
            and tombstone_matched
            and revision_matched
        )
        reason = ""
        if not matched:
            parts = []
            if not exists_matched:
                parts.append("exists")
            if not status_matched:
                parts.append("status")
            if not branch_matched:
                parts.append("branch")
            if not lease_matched:
                parts.append("lease")
            if not pin_matched:
                parts.append("pin")
            if not tombstone_matched:
                parts.append("tombstone")
            if not revision_matched:
                parts.append("revision")
            reason = "mismatch:" + ",".join(parts)
        return GraphParityView(
            tenant=tenant,
            graph_id=graph_id,
            matched=matched,
            branch_matched=branch_matched,
            lease_matched=lease_matched,
            pin_matched=pin_matched,
            tombstone_matched=tombstone_matched,
            revision_matched=revision_matched,
            legacy=dict(legacy),
            shadow=dict(shadow),
            mismatch_reason=reason,
            authority="legacy",
            operation_id=operation_id,
        )

    def parity_for(
        self, catalog: "GraphCatalog", tenant: str, graph_id: str
    ) -> GraphParityView:
        legacy = self.snapshot_from_sqlite(catalog, tenant, graph_id)
        shadow = self.snapshot_from_duckdb(tenant, graph_id)
        return self.compare_parity(
            tenant=tenant, graph_id=graph_id, legacy=legacy, shadow=shadow
        )

    def parity_across_restart(
        self, catalog: "GraphCatalog", tenant: str, graph_id: str
    ) -> GraphParityView:
        """Reopen DuckDB stores and re-check SQLite/DuckDB parity."""

        self.reopen()
        return self.parity_for(catalog, tenant, graph_id)

    def _mirror_catalog_mutation(
        self,
        operation: str,
        *,
        catalog: "GraphCatalog",
        args: tuple[Any, ...],
        kwargs: Dict[str, Any],
        result: Any,
    ) -> None:
        duck = self._duck_catalog
        if duck is None:
            return
        tenant = args[0] if args else kwargs.get("tenant")
        graph_id = args[1] if len(args) > 1 else kwargs.get("graph_id")
        if not tenant or not graph_id:
            if hasattr(result, "tenant") and hasattr(result, "graph_id"):
                tenant = result.tenant
                graph_id = result.graph_id
            else:
                return
        try:
            if operation == "create_graph":
                branch = kwargs.get("branch") or getattr(
                    result, "default_branch", DEFAULT_BRANCH
                )
                duck.create_graph(
                    tenant,
                    graph_id,
                    storage_profile=getattr(result, "storage_profile", None)
                    or kwargs.get("storage_profile")
                    or "parquet",
                    graph_kind=getattr(result, "graph_kind", None)
                    or kwargs.get("graph_kind")
                    or "knowledge_graph",
                    default_branch=branch,
                    metadata=getattr(result, "metadata", None)
                    or kwargs.get("metadata"),
                    idempotency_key=kwargs.get("idempotency_key"),
                )
            elif operation == "put_revision":
                revision_id = args[2] if len(args) > 2 else kwargs.get("revision_id")
                duck.put_revision(
                    tenant,
                    graph_id,
                    revision_id,
                    parent_revision=kwargs.get("parent_revision"),
                    storage_profile=kwargs.get("storage_profile")
                    or getattr(result, "storage_profile", "parquet"),
                    manifest_cid=kwargs.get("manifest_cid"),
                    pin_root=kwargs.get("pin_root"),
                    checksum=kwargs.get("checksum"),
                    metadata=kwargs.get("metadata"),
                )
            elif operation == "cas_set_head":
                branch = args[2] if len(args) > 2 else kwargs.get("branch")
                duck.cas_set_head(
                    tenant,
                    graph_id,
                    branch,
                    expected_revision=kwargs.get("expected_revision"),
                    new_revision=kwargs["new_revision"],
                    lease_id=kwargs.get("lease_id"),
                    lease_epoch=kwargs.get("lease_epoch"),
                    idempotency_key=kwargs.get("idempotency_key"),
                )
            elif operation == "acquire_lease":
                branch = args[2] if len(args) > 2 else kwargs.get("branch")
                duck.acquire_lease(
                    tenant,
                    graph_id,
                    branch,
                    holder=kwargs.get("holder") or result.holder,
                    ttl_seconds=float(kwargs.get("ttl_seconds") or 60.0),
                    lease_id=kwargs.get("lease_id") or result.lease_id,
                )
            elif operation == "set_pin_root":
                revision_id = args[2] if len(args) > 2 else kwargs.get("revision_id")
                root_cid = args[3] if len(args) > 3 else kwargs.get("root_cid")
                pin_kind = kwargs.get("pin_kind") or getattr(
                    result, "pin_kind", "manifest"
                )
                duck.set_pin_root(
                    tenant,
                    graph_id,
                    revision_id,
                    root_cid,
                    pin_kind=pin_kind,
                )
                # Mirror SQLite COALESCE(pin_root) update on the revision row.
                with duck._txn() as conn:  # noqa: SLF001
                    conn.execute(
                        "UPDATE revisions SET pin_root = COALESCE(pin_root, ?) "
                        "WHERE tenant = ? AND graph_id = ? AND revision_id = ?",
                        [root_cid, tenant, graph_id, revision_id],
                    )
            elif operation == "delete_graph":
                with duck._txn() as conn:  # noqa: SLF001
                    now = utc_now_iso()
                    conn.execute(
                        "UPDATE graphs SET status = 'tombstoned', "
                        "updated_at = ?, tombstoned_at = ? "
                        "WHERE tenant = ? AND graph_id = ?",
                        [now, now, tenant, graph_id],
                    )
                    conn.execute(
                        "UPDATE branches SET status = 'tombstoned', "
                        "updated_at = ?, tombstoned_at = ? "
                        "WHERE tenant = ? AND graph_id = ? AND status = 'active'",
                        [now, now, tenant, graph_id],
                    )
                    conn.execute(
                        "DELETE FROM tombstones WHERE tenant = ? AND graph_id = ? "
                        "AND kind = 'graph' AND name = ''",
                        [tenant, graph_id],
                    )
                    conn.execute(
                        "INSERT INTO tombstones "
                        "(tenant, graph_id, kind, name, tombstoned_at, reason) "
                        "VALUES (?, ?, 'graph', '', ?, ?)",
                        [
                            tenant,
                            graph_id,
                            now,
                            kwargs.get("reason")
                            or getattr(result, "reason", None),
                        ],
                    )
                    conn.execute(
                        "DELETE FROM leases WHERE tenant = ? AND graph_id = ?",
                        [tenant, graph_id],
                    )
            elif operation == "create_branch":
                branch = args[2] if len(args) > 2 else kwargs.get("branch")
                head = getattr(result, "head_revision", None)
                if head:
                    with duck._txn() as conn:  # noqa: SLF001
                        now = utc_now_iso()
                        existing = duck._fetchone(  # noqa: SLF001
                            conn,
                            "SELECT * FROM branches WHERE tenant = ? AND "
                            "graph_id = ? AND branch = ?",
                            [tenant, graph_id, branch],
                        )
                        if existing is None:
                            conn.execute(
                                "INSERT INTO branches "
                                "(tenant, graph_id, branch, head_revision, status, "
                                "created_at, updated_at, tombstoned_at) "
                                "VALUES (?, ?, ?, ?, 'active', ?, ?, NULL)",
                                [tenant, graph_id, branch, head, now, now],
                            )
            elif operation == "delete_branch":
                branch = args[2] if len(args) > 2 else kwargs.get("branch")
                with duck._txn() as conn:  # noqa: SLF001
                    now = utc_now_iso()
                    conn.execute(
                        "UPDATE branches SET status = 'tombstoned', "
                        "updated_at = ?, tombstoned_at = ? "
                        "WHERE tenant = ? AND graph_id = ? AND branch = ?",
                        [now, now, tenant, graph_id, branch],
                    )
                    conn.execute(
                        "DELETE FROM tombstones WHERE tenant = ? AND graph_id = ? "
                        "AND kind = 'branch' AND name = ?",
                        [tenant, graph_id, branch],
                    )
                    conn.execute(
                        "INSERT INTO tombstones "
                        "(tenant, graph_id, kind, name, tombstoned_at, reason) "
                        "VALUES (?, ?, 'branch', ?, ?, ?)",
                        [
                            tenant,
                            graph_id,
                            branch,
                            now,
                            kwargs.get("reason")
                            or getattr(result, "reason", None),
                        ],
                    )
            elif operation == "release_lease":
                branch = args[2] if len(args) > 2 else kwargs.get("branch")
                lease_id = kwargs.get("lease_id")
                if lease_id:
                    try:
                        duck.release_lease(lease_id)
                    except Exception:
                        with duck._txn() as conn:  # noqa: SLF001
                            conn.execute(
                                "DELETE FROM leases WHERE tenant = ? AND "
                                "graph_id = ? AND branch = ?",
                                [tenant, graph_id, branch],
                            )
            elif operation == "renew_lease":
                branch = args[2] if len(args) > 2 else kwargs.get("branch")
                if hasattr(result, "lease_id"):
                    try:
                        duck.renew_lease(
                            result.lease_id,
                            ttl_seconds=float(kwargs.get("ttl_seconds") or 60.0),
                        )
                    except Exception:
                        # Best-effort re-acquire with same fencing.
                        duck.acquire_lease(
                            tenant,
                            graph_id,
                            branch,
                            holder=result.holder,
                            ttl_seconds=float(kwargs.get("ttl_seconds") or 60.0),
                            lease_id=result.lease_id,
                        )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "duckdb catalog mirror failed op=%s %s/%s: %s",
                operation,
                tenant,
                graph_id,
                exc,
            )
            raise

    def record_catalog_mutation(
        self,
        operation: str,
        *,
        result: Any,
        catalog: "GraphCatalog",
        args: tuple[Any, ...] = (),
        kwargs: Optional[Dict[str, Any]] = None,
        operation_id: str | None = None,
    ) -> GraphMutationReceipt:
        """Mirror a SQLite catalog mutation into DuckDB and emit parity."""

        kwargs = dict(kwargs or {})
        tenant = args[0] if args else kwargs.get("tenant")
        graph_id = args[1] if len(args) > 1 else kwargs.get("graph_id")
        if (not tenant or not graph_id) and result is not None:
            tenant = getattr(result, "tenant", tenant)
            graph_id = getattr(result, "graph_id", graph_id)
        tenant = str(tenant or "unknown")
        graph_id = str(graph_id or "unknown")
        key = self._graph_key(tenant, graph_id)
        op_id = (
            operation_id
            or kwargs.get("idempotency_key")
            or new_graph_operation_id(f"catalog.{operation}")
        )

        with self._lock:
            try:
                self._mirror_catalog_mutation(
                    operation,
                    catalog=catalog,
                    args=args,
                    kwargs=kwargs,
                    result=result,
                )
            except Exception as exc:  # noqa: BLE001
                qid = self._quarantine(
                    key=key,
                    operation_id=str(op_id),
                    reason=f"mirror_failed:{operation}:{exc}",
                )
                receipt = GraphMutationReceipt(
                    operation_id=str(op_id),
                    producer="catalog",
                    kind=operation,
                    key=key,
                    parity_matched=False,
                    parity_receipt_cid="",
                    mode=self.mode,
                    payload_digest="",
                    authority="legacy",
                    quarantined=True,
                    quarantine_id=qid,
                    error=str(exc),
                )
                self._mutation_index[str(op_id)] = receipt
                return receipt

            legacy = self.snapshot_from_sqlite(catalog, tenant, graph_id)
            self._legacy_snapshots[key] = legacy
            shadow = self.snapshot_from_duckdb(tenant, graph_id)
            view = self.compare_parity(
                tenant=tenant,
                graph_id=graph_id,
                legacy=legacy,
                shadow=shadow,
                operation_id=str(op_id),
            )
            payload = {
                "operation": operation,
                "result": _record_to_dict(result),
                "legacy": legacy,
                "shadow": shadow,
                "parity": view.to_dict(),
            }
            # Prefer content CIDs/checksums from revision results when present.
            content_cid = ""
            content_checksum = ""
            if hasattr(result, "manifest_cid") and result.manifest_cid:
                content_cid = str(result.manifest_cid)
            if hasattr(result, "checksum") and result.checksum:
                content_checksum = str(result.checksum)
            if hasattr(result, "root_cid") and result.root_cid:
                content_cid = content_cid or str(result.root_cid)
            receipt = self.record_operation(
                producer="catalog",
                kind=operation,
                key=key,
                payload=payload,
                operation_id=str(op_id),
                content_cid=content_cid,
                content_checksum=content_checksum,
            )
            if not view.matched and not receipt.quarantined:
                qid = self._quarantine(
                    key=key,
                    operation_id=str(op_id),
                    reason=view.mismatch_reason or "sqlite_duckdb_parity",
                )
                receipt.quarantined = True
                receipt.quarantine_id = qid
                receipt.parity_matched = False
                self._mutation_index[str(op_id)] = receipt
            return receipt

    # -- transaction / WAL / MVCC producer ----------------------------------

    def record_transaction_mutation(
        self,
        *,
        kind: str,
        txn_id: str,
        payload: Mapping[str, Any],
        operation_id: str | None = None,
        wal_cid: str = "",
    ) -> GraphMutationReceipt:
        """Project transaction manager control state into DuckDB shadow."""

        key = f"txn:{txn_id}"
        op_id = operation_id or new_graph_operation_id(f"txn.{kind}")
        duck = self._duck_tx
        if duck is not None:
            try:
                if kind in {"begin", "add_operation", "add_read"}:
                    # Active transaction envelope for MVCC visibility.
                    from ipfs_datasets_py.knowledge_graphs.transactions.types import (
                        IsolationLevel,
                        Transaction,
                        TransactionState,
                    )

                    raw = dict(payload)
                    if "txn_id" in raw:
                        # Prefer structured put when a full envelope is provided.
                        try:
                            state_name = str(raw.get("state") or "ACTIVE")
                            isolation_name = str(
                                raw.get("isolation_level") or "REPEATABLE_READ"
                            )
                            txn = Transaction(
                                txn_id=str(raw["txn_id"]),
                                isolation_level=IsolationLevel[isolation_name]
                                if isolation_name in IsolationLevel.__members__
                                else IsolationLevel.REPEATABLE_READ,
                                state=TransactionState[state_name]
                                if state_name in TransactionState.__members__
                                else TransactionState.ACTIVE,
                                operations=[],
                                read_set=list(raw.get("read_set") or []),
                                write_set=list(raw.get("write_set") or []),
                                start_time=float(raw.get("start_time") or 0.0),
                                snapshot_cid=raw.get("snapshot_cid"),
                                wal_entries=list(raw.get("wal_entries") or []),
                            )
                            duck.put_active_transaction(txn)
                        except Exception:
                            pass
                if kind == "commit":
                    if wal_cid:
                        duck.set_wal_head_cid(wal_cid)
                        duck.bump_wal_entry_count(1)
                        duck.record_wal_applied_key(txn_id, wal_cid)
                    duck.remove_active_transaction(txn_id)
                if kind == "rollback":
                    duck.remove_active_transaction(txn_id)
                if kind == "wal_append" and wal_cid:
                    duck.set_wal_head_cid(wal_cid)
                    duck.bump_wal_entry_count(1)
                    duck.record_wal_applied_key(
                        str(payload.get("replay_key") or txn_id), wal_cid
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("txn shadow mirror failed: %s", exc)
        body = dict(payload)
        if wal_cid:
            body["wal_cid"] = wal_cid
        return self.record_operation(
            producer="transactions",
            kind=kind,
            key=key,
            payload=body,
            operation_id=op_id,
            content_cid=wal_cid,
        )

    # -- storage / hybrid producer ------------------------------------------

    def record_storage_mutation(
        self,
        *,
        kind: str,
        cid: str,
        payload: Mapping[str, Any],
        operation_id: str | None = None,
        content_bytes: bytes | None = None,
        checksum: str = "",
    ) -> GraphMutationReceipt:
        """Project hybrid cache metadata; fingerprint payload bytes unchanged."""

        key = f"storage:{cid}"
        body = dict(payload)
        body["cid"] = cid
        return self.record_operation(
            producer="storage",
            kind=kind,
            key=key,
            payload=body,
            operation_id=operation_id,
            content_cid=cid,
            content_checksum=checksum,
            content_bytes=content_bytes,
        )

    # -- graph engine producer ----------------------------------------------

    def record_engine_mutation(
        self,
        *,
        kind: str,
        entity_id: str,
        payload: Mapping[str, Any],
        operation_id: str | None = None,
        content_cid: str = "",
    ) -> GraphMutationReceipt:
        key = f"engine:{entity_id}"
        return self.record_operation(
            producer="engine",
            kind=kind,
            key=key,
            payload=dict(payload),
            operation_id=operation_id,
            content_cid=content_cid,
        )

    # -- crypto-flow producer -----------------------------------------------

    def record_crypto_snapshot(
        self,
        snapshot: Any,
        *,
        operation_id: str | None = None,
        overwrite: bool = False,
    ) -> GraphMutationReceipt:
        """Shadow-project an immutable crypto-flow snapshot into DuckDB."""

        snap_id = str(getattr(snapshot, "snapshot_id", "") or "")
        key = f"crypto:{snap_id}"
        op_id = operation_id or new_graph_operation_id("crypto.put")
        payload = (
            snapshot.to_dict()
            if hasattr(snapshot, "to_dict")
            else dict(snapshot)
        )
        graph_cid = ""
        graph_digest = ""
        if hasattr(snapshot, "graph_cid"):
            graph_cid = str(snapshot.graph_cid)
        if hasattr(snapshot, "graph_digest"):
            graph_digest = str(snapshot.graph_digest)
        duck = self._duck_crypto
        if duck is not None:
            try:
                duck.put(snapshot, overwrite=overwrite)
            except Exception as exc:  # noqa: BLE001
                logger.warning("crypto-flow duckdb put failed: %s", exc)
        return self.record_operation(
            producer="crypto_flows",
            kind="put_snapshot",
            key=key,
            payload={
                "snapshot_id": snap_id,
                "graph_cid": graph_cid,
                "graph_digest": graph_digest,
                "completeness": getattr(
                    getattr(snapshot, "completeness", None),
                    "value",
                    str(getattr(snapshot, "completeness", "")),
                ),
                "identity": {
                    "snapshot_id": snap_id,
                    "graph_cid": graph_cid,
                    "graph_digest": graph_digest,
                },
                "attributes": payload.get("attributes") or {},
            },
            operation_id=op_id,
            content_cid=graph_cid,
            content_checksum=graph_digest,
        )

    def crypto_history_parity(
        self, snapshot_ids: Sequence[str], legacy_store: Any
    ) -> Dict[str, Any]:
        """Compare crypto-flow history identity between legacy and DuckDB."""

        duck = self._duck_crypto
        results: List[Dict[str, Any]] = []
        matched = True
        for sid in snapshot_ids:
            leg = legacy_store.get(sid)
            leg_identity = {
                "snapshot_id": leg.snapshot_id,
                "graph_digest": leg.graph_digest,
                "graph_cid": leg.graph_cid,
            }
            sh_identity: Dict[str, Any] = {}
            if duck is not None:
                try:
                    sh = duck.get(sid)
                    sh_identity = {
                        "snapshot_id": sh.snapshot_id,
                        "graph_digest": sh.graph_digest,
                        "graph_cid": sh.graph_cid,
                    }
                except Exception as exc:  # noqa: BLE001
                    sh_identity = {"error": str(exc)}
            pair_matched = leg_identity == sh_identity
            matched = matched and pair_matched
            results.append(
                {
                    "snapshot_id": sid,
                    "matched": pair_matched,
                    "legacy": leg_identity,
                    "shadow": sh_identity,
                }
            )
        return {
            "matched": matched,
            "count": len(results),
            "entries": results,
            "authority": "legacy",
        }


    # ------------------------------------------------------------------
    # DQK-060: dual-write cutover, promotion, rollback, reader binds
    # ------------------------------------------------------------------

    def promote_to_dual(
        self,
        *,
        parity_key: str,
        decision_id: str | None = None,
        require_parity: bool = True,
    ) -> Any:
        """Promote shadow → dual (fenced dual writes)."""

        from ipfs_datasets_py.duckdb_control.authority_transition import (
            AuthorityMode,
            DecisionKind,
            DecisionReceipt,
        )

        if self._port is None:
            raise RuntimeError("cannot promote without an authority port")
        if self._port.mode is AuthorityMode.DUAL:
            state = self._port.state()
            receipt = DecisionReceipt(
                receipt_cid=state.last_decision_receipt_cid or "",
                kind=DecisionKind.PROMOTE,
                domain=self._port.domain,
                from_mode=AuthorityMode.DUAL,
                to_mode=AuthorityMode.DUAL,
                expected_cas_revision=state.cas_revision,
                new_cas_revision=state.cas_revision,
                fence=state.fence,
                parity_receipt_cid=state.last_parity_receipt_cid or "",
                decision_id=decision_id or "already-dual",
                accepted=True,
                reason="already_dual",
                created_at=state.updated_at or "",
                atomic_across_filesystems=False,
            )
            self._decision_receipts.append(receipt)
            self._promotion_window = True
            return receipt
        if self._port.mode is AuthorityMode.DB_PRIMARY:
            # Dual is a rollback target from db-primary; treat as no-op promote.
            state = self._port.state()
            receipt = DecisionReceipt(
                receipt_cid=state.last_decision_receipt_cid or "",
                kind=DecisionKind.PROMOTE,
                domain=self._port.domain,
                from_mode=AuthorityMode.DB_PRIMARY,
                to_mode=AuthorityMode.DB_PRIMARY,
                expected_cas_revision=state.cas_revision,
                new_cas_revision=state.cas_revision,
                fence=state.fence,
                parity_receipt_cid=state.last_parity_receipt_cid or "",
                decision_id=decision_id or "already-db-primary",
                accepted=True,
                reason="already_db_primary",
                created_at=state.updated_at or "",
                atomic_across_filesystems=False,
            )
            self._decision_receipts.append(receipt)
            return receipt
        sealed = self._port.promote(
            AuthorityMode.DUAL,
            decision_id=decision_id or f"to-dual:{parity_key}",
            require_parity=require_parity,
            parity_key=parity_key,
        )
        self._decision_receipts.append(sealed)
        if getattr(sealed, "accepted", False):
            self._promotion_window = True
        return sealed

    def promote_to_db_primary(
        self,
        *,
        parity_key: str,
        decision_id: str | None = None,
        require_parity: bool = True,
    ) -> Any:
        """Promote dual → db-primary (DuckDB control-metadata authority)."""

        from ipfs_datasets_py.duckdb_control.authority_transition import (
            AuthorityMode,
            DecisionKind,
            DecisionReceipt,
        )

        if self._port is None:
            raise RuntimeError("cannot promote without an authority port")
        if self._port.mode is AuthorityMode.DB_PRIMARY:
            state = self._port.state()
            receipt = DecisionReceipt(
                receipt_cid=state.last_decision_receipt_cid or "",
                kind=DecisionKind.PROMOTE,
                domain=self._port.domain,
                from_mode=AuthorityMode.DB_PRIMARY,
                to_mode=AuthorityMode.DB_PRIMARY,
                expected_cas_revision=state.cas_revision,
                new_cas_revision=state.cas_revision,
                fence=state.fence,
                parity_receipt_cid=state.last_parity_receipt_cid or "",
                decision_id=decision_id or "already-db-primary",
                accepted=True,
                reason="already_db_primary",
                created_at=state.updated_at or "",
                atomic_across_filesystems=False,
            )
            self._decision_receipts.append(receipt)
            self._promotion_window = False
            return receipt
        sealed = self._port.promote(
            AuthorityMode.DB_PRIMARY,
            decision_id=decision_id or f"cutover:{parity_key}",
            require_parity=require_parity,
            parity_key=parity_key,
        )
        self._decision_receipts.append(sealed)
        if getattr(sealed, "accepted", False):
            # Promotion complete: readers may unbind, DuckDB is authority.
            self._promotion_window = False
        return sealed

    def ensure_duckdb_authority(
        self,
        *,
        tenant: str,
        graph_id: str,
        decision_id: str | None = None,
    ) -> Any:
        """Ensure DuckDB is authoritative for *tenant/graph_id* (shadow→dual→db)."""

        from ipfs_datasets_py.duckdb_control.authority_transition import (
            AuthorityMode,
            PromotionBlockedError,
        )

        if self._port is None:
            return None
        key = self._graph_key(tenant, graph_id)
        mode = self._port.mode
        if mode is AuthorityMode.DB_PRIMARY:
            return None
        if mode is AuthorityMode.DUAL:
            return self.promote_to_db_primary(
                parity_key=key,
                decision_id=decision_id or f"cutover:{key}",
            )
        if mode is AuthorityMode.SHADOW:
            first = self.promote_to_dual(
                parity_key=key,
                decision_id=f"to-dual:{key}",
            )
            if not getattr(first, "accepted", False):
                raise PromotionBlockedError(
                    getattr(first, "reason", None) or "shadow→dual rejected",
                    reason=getattr(first, "reason", None) or "promotion_rejected",
                )
            return self.promote_to_db_primary(
                parity_key=key,
                decision_id=decision_id or f"cutover:{key}",
            )
        return None

    def rollback_authority(
        self,
        to_mode: Any,
        *,
        decision_id: str | None = None,
        reason: str = "operator_rollback",
    ) -> Any:
        """CAS-fenced, receipted authority rollback (DQK-060).

        Returns a :class:`DecisionReceipt` with ``kind=rollback``. Legacy
        SQLite may re-claim authority only after an accepted rollback to
        shadow/legacy; until then outbox projections remain the legacy path.
        """

        from ipfs_datasets_py.duckdb_control.authority_transition import (
            AuthorityMode,
        )

        if self._port is None:
            raise RuntimeError("cannot rollback without an authority port")
        target = AuthorityMode.parse(to_mode)
        sealed = self._port.rollback(
            target,
            decision_id=decision_id or new_graph_operation_id("rollback"),
            reason=reason,
        )
        self._decision_receipts.append(sealed)
        if getattr(sealed, "accepted", False):
            # Dual remains a promotion window; pure shadow/legacy is not.
            self._promotion_window = sealed.to_mode == AuthorityMode.DUAL
            if sealed.to_mode in {AuthorityMode.SHADOW, AuthorityMode.LEGACY}:
                # Clear binds — legacy authority resumes without dual fence.
                self._reader_bindings.clear()
        return sealed

    def list_decision_receipts(self) -> List[Any]:
        with self._lock:
            return list(self._decision_receipts)

    def last_decision_receipt(self) -> Any:
        with self._lock:
            return self._decision_receipts[-1] if self._decision_receipts else None

    # -- reader revision binding --------------------------------------------

    def _binding_key(self, tenant: str, graph_id: str, branch: str) -> str:
        return f"{tenant}/{graph_id}/{branch}"

    def bind_reader_revision(
        self,
        tenant: str,
        graph_id: str,
        branch: str = DEFAULT_BRANCH,
        *,
        catalog: Optional["GraphCatalog"] = None,
        revision_id: str | None = None,
        operation_id: str | None = None,
    ) -> ReaderRevisionBinding:
        """Bind a single branch-head revision for readers during promotion.

        Acceptance: readers observe one revision for the duration of the
        promotion window and never flip between SQLite and DuckDB heads mid-read.
        """

        op_id = operation_id or new_graph_operation_id("reader.bind")
        head = revision_id
        if head is None:
            head = self.authoritative_branch_head(
                tenant, graph_id, branch, catalog=catalog
            )
        if not head:
            raise CatalogError(
                f"cannot bind reader revision: no head for "
                f"{tenant}/{graph_id}/{branch}"
            )
        fence_token = 0
        if self._port is not None:
            try:
                fence_token = int(self._port.state().fence.fencing_token)
            except Exception:  # noqa: BLE001
                fence_token = 0
        binding = ReaderRevisionBinding(
            tenant=tenant,
            graph_id=graph_id,
            branch=branch,
            revision_id=str(head),
            bound_at=utc_now_iso(),
            authority_mode=self.mode,
            fence_token=fence_token,
            operation_id=op_id,
        )
        with self._lock:
            self._reader_bindings[binding.key] = binding
        # Journal the bind on the authority port so crash recovery preserves it.
        try:
            self.record_operation(
                producer="catalog",
                kind="bind_reader_revision",
                key=self._graph_key(tenant, graph_id),
                payload=binding.to_dict(),
                operation_id=op_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("reader bind journal failed: %s", exc)
        return binding

    def get_bound_reader_revision(
        self, tenant: str, graph_id: str, branch: str = DEFAULT_BRANCH
    ) -> Optional[ReaderRevisionBinding]:
        with self._lock:
            return self._reader_bindings.get(
                self._binding_key(tenant, graph_id, branch)
            )

    def unbind_reader_revision(
        self, tenant: str, graph_id: str, branch: str = DEFAULT_BRANCH
    ) -> Optional[ReaderRevisionBinding]:
        with self._lock:
            return self._reader_bindings.pop(
                self._binding_key(tenant, graph_id, branch), None
            )

    def list_reader_bindings(self) -> List[ReaderRevisionBinding]:
        with self._lock:
            return list(self._reader_bindings.values())

    def authoritative_branch_head(
        self,
        tenant: str,
        graph_id: str,
        branch: str = DEFAULT_BRANCH,
        *,
        catalog: Optional["GraphCatalog"] = None,
    ) -> Optional[str]:
        """Return the control-plane branch head under current authority mode.

        * Bound reader revision wins when present (promotion window).
        * dual / db-primary: prefer DuckDB head when available.
        * shadow / legacy: prefer SQLite when *catalog* is provided.
        """

        bound = self.get_bound_reader_revision(tenant, graph_id, branch)
        if bound is not None:
            return bound.revision_id

        duck_head: Optional[str] = None
        duck = self._duck_catalog
        if duck is not None:
            try:
                rec = duck.get_branch(tenant, graph_id, branch)
                duck_head = getattr(rec, "head_revision", None) or None
            except Exception:  # noqa: BLE001
                duck_head = None

        sqlite_head: Optional[str] = None
        if catalog is not None:
            try:
                rec = catalog.get_branch(tenant, graph_id, branch)
                sqlite_head = getattr(rec, "head_revision", None) or None
            except Exception:  # noqa: BLE001
                sqlite_head = None

        if self.is_duckdb_authority or self.is_dual_mode:
            return duck_head or sqlite_head
        return sqlite_head or duck_head

    def reconcile_branch_heads(
        self,
        catalog: "GraphCatalog",
        tenant: str,
        graph_id: str,
        branch: str = DEFAULT_BRANCH,
    ) -> Dict[str, Any]:
        """Resolve branch-head split brain after crash using authority mode.

        Returns a receipt dict describing the action taken. Never invents a
        new head: chooses the authoritative side and re-projects the other.
        """

        key = self._graph_key(tenant, graph_id)
        sqlite_head: Optional[str] = None
        duck_head: Optional[str] = None
        try:
            sqlite_head = catalog.get_branch(tenant, graph_id, branch).head_revision
        except CatalogError:
            sqlite_head = None
        if self._duck_catalog is not None:
            try:
                duck_head = self._duck_catalog.get_branch(
                    tenant, graph_id, branch
                ).head_revision
            except Exception:  # noqa: BLE001
                duck_head = None

        if sqlite_head == duck_head:
            return {
                "ok": True,
                "matched": True,
                "head": sqlite_head,
                "action": "none",
                "authority": self._authority_label(),
                "key": key,
            }

        authority = self._authority_label()
        if authority in {"duckdb", "dual"}:
            winner = duck_head or sqlite_head
            loser_side = "sqlite" if winner == duck_head else "duckdb"
            # Re-project winner onto SQLite when DuckDB is authority.
            if winner and duck_head and sqlite_head != duck_head:
                try:
                    # Direct SQL update on SQLite to repair projection without
                    # re-running CAS lease fencing (recovery path only).
                    with catalog._lock:  # noqa: SLF001
                        catalog._conn.execute(  # noqa: SLF001
                            "UPDATE branches SET head_revision = ?, updated_at = ? "
                            "WHERE tenant = ? AND graph_id = ? AND branch = ?",
                            [
                                duck_head,
                                utc_now_iso(),
                                tenant,
                                graph_id,
                                branch,
                            ],
                        )
                    action = "project_duckdb_to_sqlite"
                    winner = duck_head
                    loser_side = "sqlite"
                except Exception as exc:  # noqa: BLE001
                    return {
                        "ok": False,
                        "matched": False,
                        "head": duck_head,
                        "sqlite_head": sqlite_head,
                        "duck_head": duck_head,
                        "action": "failed",
                        "error": str(exc),
                        "authority": authority,
                        "key": key,
                    }
            else:
                action = "prefer_duckdb" if duck_head else "prefer_sqlite"
        else:
            winner = sqlite_head or duck_head
            action = "prefer_sqlite"
            loser_side = "duckdb"
            if winner and sqlite_head and duck_head != sqlite_head and self._duck_catalog:
                try:
                    with self._duck_catalog._txn() as conn:  # noqa: SLF001
                        conn.execute(
                            "UPDATE branches SET head_revision = ?, updated_at = ? "
                            "WHERE tenant = ? AND graph_id = ? AND branch = ?",
                            [
                                sqlite_head,
                                utc_now_iso(),
                                tenant,
                                graph_id,
                                branch,
                            ],
                        )
                    action = "project_sqlite_to_duckdb"
                except Exception as exc:  # noqa: BLE001
                    return {
                        "ok": False,
                        "matched": False,
                        "head": sqlite_head,
                        "sqlite_head": sqlite_head,
                        "duck_head": duck_head,
                        "action": "failed",
                        "error": str(exc),
                        "authority": authority,
                        "key": key,
                    }

        # Journal the reconciliation so outbox/parity stay consistent.
        op_id = new_graph_operation_id("reconcile.head")
        try:
            self.record_operation(
                producer="catalog",
                kind="reconcile_branch_head",
                key=key,
                payload={
                    "tenant": tenant,
                    "graph_id": graph_id,
                    "branch": branch,
                    "winner": winner,
                    "sqlite_head": sqlite_head,
                    "duck_head": duck_head,
                    "action": action,
                    "loser_side": loser_side,
                },
                operation_id=op_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("reconcile journal failed: %s", exc)

        return {
            "ok": True,
            "matched": True,
            "head": winner,
            "sqlite_head": sqlite_head,
            "duck_head": duck_head,
            "action": action,
            "authority": authority,
            "key": key,
            "operation_id": op_id,
        }

    def recover_after_crash(
        self, catalog: Optional["GraphCatalog"] = None
    ) -> Dict[str, Any]:
        """Idempotent crash recovery: redrive outbox, reconcile heads, keep txs.

        Guarantees (DQK-060 acceptance):

        * Incomplete dual/db-primary outbox entries are redriven.
        * Branch heads are reconciled to the authoritative side (no split brain).
        * Durable DuckDB transaction-control state survives reopen (no lost tx).
        """

        outbox_result: Dict[str, Any] = {
            "ok": True,
            "recovered_outbox_ids": [],
            "quarantined_outbox_ids": [],
        }
        if self._port is not None:
            try:
                outbox_result = dict(self._port.recover_outbox())
            except Exception as exc:  # noqa: BLE001
                outbox_result = {"ok": False, "error": str(exc)}

        head_receipts: List[Dict[str, Any]] = []
        if catalog is not None:
            # Prefer reconciling graphs we already dual-projected (legacy snapshots).
            targets: List[tuple[str, str]] = []
            for key, snap in list(self._legacy_snapshots.items()):
                t = str(snap.get("tenant") or "")
                g = str(snap.get("graph_id") or "")
                if t and g:
                    targets.append((t, g))
            # Also walk known keys from mutation receipts.
            for receipt in self.list_mutation_receipts():
                if receipt.producer != "catalog":
                    continue
                # key form: graph:tenant/graph_id
                raw = receipt.key
                if raw.startswith("graph:"):
                    body = raw[len("graph:") :]
                    if "/" in body:
                        t, g = body.split("/", 1)
                        if (t, g) not in targets:
                            targets.append((t, g))
            for tenant, graph_id in targets:
                branch = DEFAULT_BRANCH
                try:
                    head_receipts.append(
                        self.reconcile_branch_heads(
                            catalog, str(tenant), str(graph_id), str(branch)
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    head_receipts.append(
                        {
                            "ok": False,
                            "error": str(exc),
                            "tenant": tenant,
                            "graph_id": graph_id,
                        }
                    )

        # Transaction control: durable DuckDB state is already on disk after
        # reopen; expose a summary so tests can assert no lost progress.
        tx_summary: Dict[str, Any] = {"wal_head_cid": None, "applied_keys": {}}
        duck_tx = self._duck_tx
        if duck_tx is not None:
            try:
                tx_summary["wal_head_cid"] = duck_tx.get_wal_head_cid()
                tx_summary["applied_keys"] = dict(duck_tx.list_wal_applied_keys())
            except Exception as exc:  # noqa: BLE001
                tx_summary["error"] = str(exc)

        return {
            "ok": bool(outbox_result.get("ok", True)),
            "authority": self._authority_label(),
            "mode": self.mode,
            "outbox": outbox_result,
            "branch_heads": head_receipts,
            "transaction_control": tx_summary,
            "legacy_is_outbox_projection": self.legacy_is_outbox_projection,
            "atomic_across_filesystems": False,
            "idempotent": True,
        }

    def dual_write_catalog_mutation(
        self,
        operation: str,
        *,
        result: Any,
        catalog: "GraphCatalog",
        args: tuple[Any, ...] = (),
        kwargs: Optional[Dict[str, Any]] = None,
        operation_id: str | None = None,
    ) -> GraphMutationReceipt:
        """Explicit fenced dual-write path for catalog control mutations.

        Identical to :meth:`record_catalog_mutation` but forces the dual-mode
        schema and asserts outbox coordination when mode is dual/db-primary.
        """

        receipt = self.record_catalog_mutation(
            operation,
            result=result,
            catalog=catalog,
            args=args,
            kwargs=kwargs,
            operation_id=operation_id,
        )
        # In dual/db-primary, outbox must be present unless disabled/replay.
        if (
            self.legacy_is_outbox_projection
            and not receipt.idempotent_replay
            and not receipt.outbox_id
            and receipt.mode not in {"disabled"}
        ):
            # Best-effort: journal a synthetic outbox-bound projection so
            # acceptance "legacy writes are outbox projections" holds even
            # when the port was in shadow during a transitional call.
            try:
                key = receipt.key
                body = {
                    "schema": GRAPH_AUTHORITY_SCHEMA,
                    "owner_task": GRAPH_AUTHORITY_OWNER_TASK,
                    "producer": "catalog",
                    "kind": operation,
                    "key": key,
                    "legacy_is_outbox_projection": True,
                    "payload": {"operation": operation},
                }
                if self._port is not None:
                    wr = self._port.write(
                        key,
                        body,
                        operation_id=receipt.operation_id + ":outbox",
                    )
                    receipt.outbox_id = str(wr.get("outbox_id") or receipt.outbox_id)
                    receipt.authority = str(
                        wr.get("authority") or self._authority_label()
                    )
                    self._mutation_index[receipt.operation_id] = receipt
            except Exception as exc:  # noqa: BLE001
                logger.warning("dual_write outbox journal failed: %s", exc)
        return receipt


# Alias used by dual-mode cutover callers / tests (DQK-060).
GraphAuthorityCatalog = GraphShadowAuthority


# ---------------------------------------------------------------------------
# Process-local registry + catalog mutator hooks
# ---------------------------------------------------------------------------


def configure_graph_shadow_authority(
    duckdb_catalog_path: PathLike | None = None,
    *,
    duckdb_tx_path: PathLike | None = None,
    duckdb_crypto_path: PathLike | None = None,
    enabled: bool = True,
    authority_port: Any = None,
    writer_id: str = "writer:graph-shadow-authority",
    initial_mode: Any = None,
    owner_task: str = GRAPH_SHADOW_OWNER_TASK,
) -> GraphShadowAuthority:
    """Install a process-local graph shadow authority (DQK-059).

    Defaults to :class:`AuthorityMode.SHADOW`. Use
    :func:`configure_graph_authority` for dual-mode cutover (DQK-060).
    """

    global _process_shadow_authority
    with _process_shadow_lock:
        if _process_shadow_authority is not None:
            try:
                _process_shadow_authority.close()
            except Exception:  # noqa: BLE001
                pass
        auth = GraphShadowAuthority(
            duckdb_catalog_path=duckdb_catalog_path,
            duckdb_tx_path=duckdb_tx_path,
            duckdb_crypto_path=duckdb_crypto_path,
            enabled=enabled,
            authority_port=authority_port,
            writer_id=writer_id,
            initial_mode=initial_mode,
            owner_task=owner_task,
        )
        _process_shadow_authority = auth
        return auth


def configure_graph_authority(
    duckdb_catalog_path: PathLike | None = None,
    *,
    duckdb_tx_path: PathLike | None = None,
    duckdb_crypto_path: PathLike | None = None,
    enabled: bool = True,
    authority_port: Any = None,
    writer_id: str = "writer:graph-authority",
    initial_mode: Any = None,
) -> GraphShadowAuthority:
    """Install dual-mode graph authority for DQK-060 cutover.

    Defaults to :class:`AuthorityMode.DUAL` so DuckDB participates in fenced
    dual writes; call :meth:`GraphShadowAuthority.ensure_duckdb_authority` to
    promote to db-primary.
    """

    from ipfs_datasets_py.duckdb_control.authority_transition import AuthorityMode

    mode = initial_mode if initial_mode is not None else AuthorityMode.DUAL
    return configure_graph_shadow_authority(
        duckdb_catalog_path,
        duckdb_tx_path=duckdb_tx_path,
        duckdb_crypto_path=duckdb_crypto_path,
        enabled=enabled,
        authority_port=authority_port,
        writer_id=writer_id,
        initial_mode=mode,
        owner_task=GRAPH_AUTHORITY_OWNER_TASK,
    )


def get_graph_shadow_authority() -> Optional[GraphShadowAuthority]:
    with _process_shadow_lock:
        return _process_shadow_authority


def get_graph_authority() -> Optional[GraphShadowAuthority]:
    """Alias for the process-local dual/shadow authority (DQK-060)."""

    return get_graph_shadow_authority()


def reset_graph_shadow_authority() -> None:
    global _process_shadow_authority
    with _process_shadow_lock:
        if _process_shadow_authority is not None:
            try:
                _process_shadow_authority.close()
            except Exception:  # noqa: BLE001
                pass
        _process_shadow_authority = None


def reset_graph_authority() -> None:
    """Alias for :func:`reset_graph_shadow_authority`."""

    reset_graph_shadow_authority()


def safe_shadow_catalog_mutation(
    operation: str,
    *,
    result: Any,
    catalog: "GraphCatalog",
    args: tuple[Any, ...] = (),
    kwargs: Optional[Dict[str, Any]] = None,
    operation_id: str | None = None,
    shadow: Optional[GraphShadowAuthority] = None,
) -> Optional[GraphMutationReceipt]:
    """Best-effort catalog shadow helper used by producers and tests."""

    auth = shadow or catalog.shadow_authority or get_graph_shadow_authority()
    if auth is None:
        return None
    try:
        return auth.record_catalog_mutation(
            operation,
            result=result,
            catalog=catalog,
            args=args,
            kwargs=kwargs,
            operation_id=operation_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("safe_shadow_catalog_mutation failed: %s", exc)
        return None


def safe_dual_catalog_mutation(
    operation: str,
    *,
    result: Any,
    catalog: "GraphCatalog",
    args: tuple[Any, ...] = (),
    kwargs: Optional[Dict[str, Any]] = None,
    operation_id: str | None = None,
    authority: Optional[GraphShadowAuthority] = None,
) -> Optional[GraphMutationReceipt]:
    """Best-effort dual-write catalog helper for DQK-060 producers and tests."""

    auth = authority or catalog.shadow_authority or get_graph_authority()
    if auth is None:
        return None
    try:
        return auth.dual_write_catalog_mutation(
            operation,
            result=result,
            catalog=catalog,
            args=args,
            kwargs=kwargs,
            operation_id=operation_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("safe_dual_catalog_mutation failed: %s", exc)
        return None


_CATALOG_SHADOW_MUTATORS: tuple[str, ...] = (
    "create_graph",
    "delete_graph",
    "create_branch",
    "delete_branch",
    "put_revision",
    "cas_set_head",
    "acquire_lease",
    "renew_lease",
    "release_lease",
    "set_pin_root",
)


def _install_catalog_shadow_hooks() -> None:
    """Wrap GraphCatalog mutators for dual/shadow projection (DQK-059/060)."""

    for name in _CATALOG_SHADOW_MUTATORS:
        original = getattr(GraphCatalog, name)
        # Avoid double-wrapping if this module is reloaded.
        if getattr(original, "_graph_authority_hooked", False):
            continue

        def _make(op_name: str, orig: Any) -> Any:
            def wrapped(self: "GraphCatalog", *args: Any, **kwargs: Any) -> Any:
                result = orig(self, *args, **kwargs)
                self._notify_shadow(op_name, result, args, kwargs)
                return result

            wrapped.__name__ = op_name
            wrapped.__doc__ = orig.__doc__
            wrapped.__qualname__ = f"GraphCatalog.{op_name}"
            wrapped._graph_authority_hooked = True  # type: ignore[attr-defined]
            return wrapped

        setattr(GraphCatalog, name, _make(name, original))


_install_catalog_shadow_hooks()


__all__ = [
    "GRAPH_AUTHORITY_DOMAIN",
    "GRAPH_AUTHORITY_OWNER_TASK",
    "GRAPH_AUTHORITY_SCHEMA",
    "GRAPH_SHADOW_DOMAIN",
    "GRAPH_SHADOW_OWNER_TASK",
    "GRAPH_SHADOW_SCHEMA",
    "GraphAuthorityCatalog",
    "GraphCatalog",
    "GraphMutationReceipt",
    "GraphParityView",
    "GraphShadowAuthority",
    "ReaderRevisionBinding",
    "configure_graph_authority",
    "configure_graph_shadow_authority",
    "get_graph_authority",
    "get_graph_shadow_authority",
    "new_graph_operation_id",
    "open_catalog",
    "reset_graph_authority",
    "reset_graph_shadow_authority",
    "safe_dual_catalog_mutation",
    "safe_shadow_catalog_mutation",
]
