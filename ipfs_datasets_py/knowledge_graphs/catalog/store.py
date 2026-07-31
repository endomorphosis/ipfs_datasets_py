"""SQLite WAL-backed durable graph catalog with branch-head CAS (KGP-005).

Control metadata only: tenant/graph lifecycle, branches, immutable revision
records, head compare-and-swap, tombstones, writer leases, idempotency keys,
and pin roots. Graph payloads remain storage-adapter owned.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
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
        self._configure_connection()
        self._initialize_schema()

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


__all__ = [
    "GraphCatalog",
    "open_catalog",
]
