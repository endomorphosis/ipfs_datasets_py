"""DuckDB-backed graph catalog with branch-head CAS (DQK-015).

Reimplements the SQLite :class:`~.store.GraphCatalog` control-plane surface
(graphs, branches, revisions, leases, pins, tombstones, idempotency) against
DuckDB while preserving CAS and lease semantics. Graph payloads remain
storage-adapter owned; this module is metadata only.

Importing this module does not open DuckDB until a catalog path is constructed.
"""

from __future__ import annotations

import json
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

_SCHEMA_SQL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS catalog_meta (
        key VARCHAR PRIMARY KEY,
        value VARCHAR NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graphs (
        tenant VARCHAR NOT NULL,
        graph_id VARCHAR NOT NULL,
        storage_profile VARCHAR NOT NULL,
        graph_kind VARCHAR NOT NULL,
        status VARCHAR NOT NULL,
        default_branch VARCHAR NOT NULL,
        created_at VARCHAR NOT NULL,
        updated_at VARCHAR NOT NULL,
        tombstoned_at VARCHAR,
        metadata_json VARCHAR NOT NULL DEFAULT '{}',
        PRIMARY KEY (tenant, graph_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS branches (
        tenant VARCHAR NOT NULL,
        graph_id VARCHAR NOT NULL,
        branch VARCHAR NOT NULL,
        head_revision VARCHAR NOT NULL,
        status VARCHAR NOT NULL,
        created_at VARCHAR NOT NULL,
        updated_at VARCHAR NOT NULL,
        tombstoned_at VARCHAR,
        PRIMARY KEY (tenant, graph_id, branch)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS revisions (
        tenant VARCHAR NOT NULL,
        graph_id VARCHAR NOT NULL,
        revision_id VARCHAR NOT NULL,
        parent_revision VARCHAR,
        storage_profile VARCHAR NOT NULL,
        created_at VARCHAR NOT NULL,
        manifest_cid VARCHAR,
        manifest_json VARCHAR,
        pin_root VARCHAR,
        checksum VARCHAR,
        metadata_json VARCHAR NOT NULL DEFAULT '{}',
        PRIMARY KEY (tenant, graph_id, revision_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS leases (
        tenant VARCHAR NOT NULL,
        graph_id VARCHAR NOT NULL,
        branch VARCHAR NOT NULL,
        lease_id VARCHAR NOT NULL,
        holder VARCHAR NOT NULL,
        epoch INTEGER NOT NULL,
        expires_at VARCHAR NOT NULL,
        created_at VARCHAR NOT NULL,
        renewed_at VARCHAR NOT NULL,
        PRIMARY KEY (tenant, graph_id, branch)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pin_roots (
        pin_id VARCHAR PRIMARY KEY,
        tenant VARCHAR NOT NULL,
        graph_id VARCHAR NOT NULL,
        revision_id VARCHAR NOT NULL,
        root_cid VARCHAR NOT NULL,
        pin_kind VARCHAR NOT NULL,
        created_at VARCHAR NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tombstones (
        tenant VARCHAR NOT NULL,
        graph_id VARCHAR NOT NULL,
        kind VARCHAR NOT NULL,
        name VARCHAR NOT NULL,
        tombstoned_at VARCHAR NOT NULL,
        reason VARCHAR,
        PRIMARY KEY (tenant, graph_id, kind, name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS idempotency_keys (
        key VARCHAR PRIMARY KEY,
        tenant VARCHAR NOT NULL,
        graph_id VARCHAR NOT NULL,
        operation VARCHAR NOT NULL,
        request_hash VARCHAR NOT NULL,
        response_json VARCHAR NOT NULL,
        created_at VARCHAR NOT NULL
    )
    """,
)


def _require_duckdb() -> Any:
    try:
        import duckdb  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise CatalogError(
            "STORAGE",
            "duckdb package is required for DuckDBGraphCatalog",
        ) from exc
    return duckdb


def _row_map(columns: Sequence[str], row: Sequence[Any]) -> dict[str, Any]:
    return {columns[i]: row[i] for i in range(len(columns))}


class DuckDBGraphCatalog:
    """Durable embedded catalog using DuckDB (control metadata only)."""

    def __init__(self, path: PathLike) -> None:
        duckdb = _require_duckdb()
        self._path = Path(path)
        if self._path.parent and str(self._path.parent) not in ("", "."):
            self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = duckdb.connect(str(self._path))
        self._closed = False
        self._initialize_schema()

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

    def __enter__(self) -> "DuckDBGraphCatalog":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise CatalogError("STORAGE", "catalog is closed")

    def _initialize_schema(self) -> None:
        with self._lock:
            for statement in _SCHEMA_SQL:
                self._conn.execute(statement)
            row = self._conn.execute(
                "SELECT value FROM catalog_meta WHERE key = ?",
                ["schema_version"],
            ).fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO catalog_meta (key, value) VALUES (?, ?)",
                    ["schema_version", str(_SCHEMA_VERSION)],
                )
            else:
                version = int(row[0])
                if version > _SCHEMA_VERSION:
                    raise CatalogError(
                        "STORAGE",
                        f"catalog schema version {version} is newer than "
                        f"supported {_SCHEMA_VERSION}",
                    )

    @contextmanager
    def _txn(self) -> Iterator[Any]:
        self._ensure_open()
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                yield self._conn
                self._conn.execute("COMMIT")
            except Exception:
                try:
                    self._conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise

    def _fetchone(
        self, conn: Any, sql: str, params: Sequence[Any] = ()
    ) -> Optional[dict[str, Any]]:
        cur = conn.execute(sql, list(params))
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
        return _row_map(cols, row)

    def _fetchall(
        self, conn: Any, sql: str, params: Sequence[Any] = ()
    ) -> list[dict[str, Any]]:
        cur = conn.execute(sql, list(params))
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        return [_row_map(cols, row) for row in rows]

    def _graph_from_row(self, row: Mapping[str, Any]) -> GraphRecord:
        return GraphRecord(
            tenant=row["tenant"],
            graph_id=row["graph_id"],
            storage_profile=row["storage_profile"],
            graph_kind=row["graph_kind"],
            status=row["status"],
            default_branch=row["default_branch"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            tombstoned_at=row.get("tombstoned_at"),
            metadata=json.loads(row.get("metadata_json") or "{}"),
        )

    def _branch_from_row(self, row: Mapping[str, Any]) -> BranchRecord:
        return BranchRecord(
            tenant=row["tenant"],
            graph_id=row["graph_id"],
            branch=row["branch"],
            head_revision=row["head_revision"] or "",
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            tombstoned_at=row.get("tombstoned_at"),
        )

    def _revision_from_row(self, row: Mapping[str, Any]) -> RevisionRecord:
        return RevisionRecord(
            tenant=row["tenant"],
            graph_id=row["graph_id"],
            revision_id=row["revision_id"],
            parent_revision=row.get("parent_revision"),
            storage_profile=row["storage_profile"],
            created_at=row["created_at"],
            manifest_cid=row.get("manifest_cid"),
            manifest_json=row.get("manifest_json"),
            pin_root=row.get("pin_root"),
            checksum=row.get("checksum"),
            metadata=json.loads(row.get("metadata_json") or "{}"),
        )

    def _get_graph_row(
        self, conn: Any, tenant: str, graph_id: str
    ) -> dict[str, Any]:
        row = self._fetchone(
            conn,
            "SELECT * FROM graphs WHERE tenant = ? AND graph_id = ?",
            [tenant, graph_id],
        )
        if row is None or row["status"] != "active":
            raise CatalogError(
                "NOT_FOUND",
                "graph not found",
                details={"tenant": tenant, "graph_id": graph_id},
            )
        return row

    def _get_branch_row(
        self, conn: Any, tenant: str, graph_id: str, branch: str
    ) -> dict[str, Any]:
        row = self._fetchone(
            conn,
            "SELECT * FROM branches WHERE tenant = ? AND graph_id = ? AND branch = ?",
            [tenant, graph_id, branch],
        )
        if row is None or row["status"] != "active":
            raise CatalogError(
                "NOT_FOUND",
                "branch not found",
                details={
                    "tenant": tenant,
                    "graph_id": graph_id,
                    "branch": branch,
                },
            )
        return row

    def _get_revision_row(
        self, conn: Any, tenant: str, graph_id: str, revision_id: str
    ) -> dict[str, Any]:
        row = self._fetchone(
            conn,
            "SELECT * FROM revisions WHERE tenant = ? AND graph_id = ? AND revision_id = ?",
            [tenant, graph_id, revision_id],
        )
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
        conn: Any,
        key: str,
        *,
        request_hash_value: str,
        operation: str,
    ) -> Optional[dict[str, Any]]:
        row = self._fetchone(
            conn, "SELECT * FROM idempotency_keys WHERE key = ?", [key]
        )
        if row is None:
            return None
        if row["operation"] != operation or row["request_hash"] != request_hash_value:
            raise CatalogError(
                "CONFLICT",
                "idempotency key reuse with different request",
                details={"key": key, "operation": operation},
            )
        return json.loads(row["response_json"])

    def _store_idempotency(
        self,
        conn: Any,
        key: str,
        *,
        tenant: str,
        graph_id: str,
        operation: str,
        request_hash_value: str,
        response: Mapping[str, Any],
    ) -> None:
        conn.execute(
            "INSERT INTO idempotency_keys "
            "(key, tenant, graph_id, operation, request_hash, response_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                key,
                tenant,
                graph_id,
                operation,
                request_hash_value,
                json.dumps(dict(response), sort_keys=True),
                utc_now_iso(),
            ],
        )

    def _assert_lease(
        self,
        conn: Any,
        tenant: str,
        graph_id: str,
        branch: str,
        *,
        lease_id: Optional[str],
        lease_epoch: Optional[int],
    ) -> None:
        if lease_id is None:
            return
        lid = require_lease_id(lease_id)
        row = self._fetchone(
            conn, "SELECT * FROM leases WHERE lease_id = ?", [lid]
        )
        if row is None:
            raise CatalogError(
                "FORBIDDEN",
                "lease is missing or released",
                details={"lease_id": lid},
            )
        if (
            row["tenant"] != tenant
            or row["graph_id"] != graph_id
            or row["branch"] != branch
        ):
            raise CatalogError(
                "FORBIDDEN",
                "lease scope mismatch",
                details={"lease_id": lid},
            )
        if lease_epoch is not None and int(row["epoch"]) != int(lease_epoch):
            raise CatalogError(
                "CONFLICT",
                "lease epoch mismatch",
                details={
                    "lease_id": lid,
                    "expected_epoch": lease_epoch,
                    "current_epoch": row["epoch"],
                },
            )
        if is_expired(row["expires_at"]):
            raise CatalogError(
                "FORBIDDEN",
                "lease expired",
                details={"lease_id": lid, "expires_at": row["expires_at"]},
            )

    def create_graph(
        self,
        tenant: str,
        graph_id: str,
        *,
        storage_profile: str,
        graph_kind: str = "knowledge_graph",
        default_branch: str = DEFAULT_BRANCH,
        metadata: Optional[Mapping[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> GraphRecord:
        tenant = require_slug(tenant, field="tenant")
        graph_id = require_slug(graph_id, field="graph_id")
        storage_profile = require_storage_profile(storage_profile)
        graph_kind = require_graph_kind(graph_kind)
        default_branch = require_slug(default_branch, field="default_branch")
        meta = dict(metadata or {})
        idem_key = (
            require_idempotency_key(idempotency_key)
            if idempotency_key is not None
            else None
        )
        req = {
            "tenant": tenant,
            "graph_id": graph_id,
            "storage_profile": storage_profile,
            "graph_kind": graph_kind,
            "default_branch": default_branch,
            "metadata": meta,
        }
        req_hash = request_hash(req)
        bootstrap = bootstrap_revision_id(tenant, graph_id)
        with self._txn() as conn:
            if idem_key is not None:
                cached = self._lookup_idempotency(
                    conn,
                    idem_key,
                    request_hash_value=req_hash,
                    operation="create_graph",
                )
                if cached is not None:
                    return self._graph_from_row(cached)
            existing = self._fetchone(
                conn,
                "SELECT * FROM graphs WHERE tenant = ? AND graph_id = ?",
                [tenant, graph_id],
            )
            if existing is not None:
                raise CatalogError(
                    "CONFLICT",
                    "graph already exists",
                    details={"tenant": tenant, "graph_id": graph_id},
                )
            now = utc_now_iso()
            conn.execute(
                "INSERT INTO graphs "
                "(tenant, graph_id, storage_profile, graph_kind, status, "
                "default_branch, created_at, updated_at, tombstoned_at, metadata_json) "
                "VALUES (?, ?, ?, ?, 'active', ?, ?, ?, NULL, ?)",
                [
                    tenant,
                    graph_id,
                    storage_profile,
                    graph_kind,
                    default_branch,
                    now,
                    now,
                    json.dumps(meta, sort_keys=True),
                ],
            )
            conn.execute(
                "INSERT INTO revisions "
                "(tenant, graph_id, revision_id, parent_revision, storage_profile, "
                "created_at, manifest_cid, manifest_json, pin_root, checksum, metadata_json) "
                "VALUES (?, ?, ?, NULL, ?, ?, NULL, NULL, NULL, NULL, '{}')",
                [tenant, graph_id, bootstrap, storage_profile, now],
            )
            conn.execute(
                "INSERT INTO branches "
                "(tenant, graph_id, branch, head_revision, status, created_at, "
                "updated_at, tombstoned_at) "
                "VALUES (?, ?, ?, ?, 'active', ?, ?, NULL)",
                [tenant, graph_id, default_branch, bootstrap, now, now],
            )
            row = self._fetchone(
                conn,
                "SELECT * FROM graphs WHERE tenant = ? AND graph_id = ?",
                [tenant, graph_id],
            )
            assert row is not None
            if idem_key is not None:
                self._store_idempotency(
                    conn,
                    idem_key,
                    tenant=tenant,
                    graph_id=graph_id,
                    operation="create_graph",
                    request_hash_value=req_hash,
                    response=row,
                )
            return self._graph_from_row(row)

    def get_graph(self, tenant: str, graph_id: str) -> GraphRecord:
        tenant = require_slug(tenant, field="tenant")
        graph_id = require_slug(graph_id, field="graph_id")
        with self._txn() as conn:
            return self._graph_from_row(self._get_graph_row(conn, tenant, graph_id))

    def put_revision(
        self,
        tenant: str,
        graph_id: str,
        revision_id: str,
        *,
        parent_revision: Optional[str],
        storage_profile: str,
        manifest_cid: Optional[str] = None,
        pin_root: Optional[str] = None,
        checksum: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> RevisionRecord:
        tenant = require_slug(tenant, field="tenant")
        graph_id = require_slug(graph_id, field="graph_id")
        revision_id = require_revision_id(revision_id, field="revision_id")
        storage_profile = require_storage_profile(storage_profile)
        parent = (
            require_revision_id(parent_revision, field="parent_revision")
            if parent_revision
            else None
        )
        meta = dict(metadata or {})
        with self._txn() as conn:
            self._get_graph_row(conn, tenant, graph_id)
            existing = self._fetchone(
                conn,
                "SELECT * FROM revisions WHERE tenant = ? AND graph_id = ? AND revision_id = ?",
                [tenant, graph_id, revision_id],
            )
            if existing is not None:
                return self._revision_from_row(existing)
            if parent is not None:
                self._get_revision_row(conn, tenant, graph_id, parent)
            now = utc_now_iso()
            conn.execute(
                "INSERT INTO revisions "
                "(tenant, graph_id, revision_id, parent_revision, storage_profile, "
                "created_at, manifest_cid, manifest_json, pin_root, checksum, metadata_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)",
                [
                    tenant,
                    graph_id,
                    revision_id,
                    parent,
                    storage_profile,
                    now,
                    manifest_cid,
                    pin_root,
                    checksum,
                    json.dumps(meta, sort_keys=True),
                ],
            )
            row = self._get_revision_row(conn, tenant, graph_id, revision_id)
            return self._revision_from_row(row)

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
        idempotency_key: Optional[str] = None,
    ) -> BranchRecord:
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
        }
        req_hash = request_hash(req)
        with self._txn() as conn:
            if idem_key is not None:
                cached = self._lookup_idempotency(
                    conn,
                    idem_key,
                    request_hash_value=req_hash,
                    operation="cas_set_head",
                )
                if cached is not None:
                    return self._branch_from_row(cached)
            self._get_graph_row(conn, tenant, graph_id)
            brow = self._get_branch_row(conn, tenant, graph_id, branch)
            current = brow["head_revision"] or None
            if current != expected:
                raise CatalogError(
                    "CONFLICT",
                    "branch head CAS conflict",
                    details={
                        "tenant": tenant,
                        "graph_id": graph_id,
                        "branch": branch,
                        "expected_revision": expected,
                        "current_revision": current,
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
            self._get_revision_row(conn, tenant, graph_id, new_rev)
            now = utc_now_iso()
            if expected is None:
                result = conn.execute(
                    "UPDATE branches SET head_revision = ?, updated_at = ? "
                    "WHERE tenant = ? AND graph_id = ? AND branch = ? "
                    "AND status = 'active' "
                    "AND (head_revision IS NULL OR head_revision = '')",
                    [new_rev, now, tenant, graph_id, branch],
                )
            else:
                result = conn.execute(
                    "UPDATE branches SET head_revision = ?, updated_at = ? "
                    "WHERE tenant = ? AND graph_id = ? AND branch = ? "
                    "AND status = 'active' AND head_revision = ?",
                    [new_rev, now, tenant, graph_id, branch, expected],
                )
            # DuckDB may not expose rowcount; re-read and verify.
            updated = self._get_branch_row(conn, tenant, graph_id, branch)
            if (updated["head_revision"] or None) != new_rev:
                raise CatalogError(
                    "CONFLICT",
                    "branch head CAS conflict",
                    details={
                        "tenant": tenant,
                        "graph_id": graph_id,
                        "branch": branch,
                        "expected_revision": expected,
                        "current_revision": updated["head_revision"] or None,
                        "new_revision": new_rev,
                    },
                )
            if idem_key is not None:
                self._store_idempotency(
                    conn,
                    idem_key,
                    tenant=tenant,
                    graph_id=graph_id,
                    operation="cas_set_head",
                    request_hash_value=req_hash,
                    response=updated,
                )
            return self._branch_from_row(updated)


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
        tenant = require_slug(tenant, field="tenant")
        graph_id = require_slug(graph_id, field="graph_id")
        branch = require_slug(branch, field="branch")
        holder = require_holder(holder)
        ttl = require_positive_ttl(ttl_seconds)
        desired_id = require_lease_id(lease_id) if lease_id is not None else new_lease_id()
        with self._txn() as conn:
            self._get_graph_row(conn, tenant, graph_id)
            self._get_branch_row(conn, tenant, graph_id, branch)
            now = utc_now_iso()
            expires = expires_at_from_ttl(ttl)
            row = self._fetchone(
                conn,
                "SELECT * FROM leases WHERE tenant = ? AND graph_id = ? AND branch = ?",
                [tenant, graph_id, branch],
            )
            if row is None:
                epoch = 1
                conn.execute(
                    "INSERT INTO leases "
                    "(tenant, graph_id, branch, lease_id, holder, epoch, "
                    "expires_at, created_at, renewed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [tenant, graph_id, branch, desired_id, holder, epoch, expires, now, now],
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
                conn.execute(
                    "UPDATE leases SET expires_at = ?, renewed_at = ? "
                    "WHERE tenant = ? AND graph_id = ? AND branch = ?",
                    [expires, now, tenant, graph_id, branch],
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
            # Steal expired lease with new epoch/id.
            epoch = int(row["epoch"]) + 1
            conn.execute(
                "UPDATE leases SET lease_id = ?, holder = ?, epoch = ?, "
                "expires_at = ?, created_at = ?, renewed_at = ? "
                "WHERE tenant = ? AND graph_id = ? AND branch = ?",
                [desired_id, holder, epoch, expires, now, now, tenant, graph_id, branch],
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

    def renew_lease(self, lease_id: str, *, ttl_seconds: float) -> LeaseRecord:
        lid = require_lease_id(lease_id)
        ttl = require_positive_ttl(ttl_seconds)
        with self._txn() as conn:
            row = self._fetchone(
                conn, "SELECT * FROM leases WHERE lease_id = ?", [lid]
            )
            if row is None:
                raise CatalogError("NOT_FOUND", "lease not found", details={"lease_id": lid})
            if is_expired(row["expires_at"]):
                raise CatalogError("FORBIDDEN", "lease expired", details={"lease_id": lid})
            now = utc_now_iso()
            expires = expires_at_from_ttl(ttl)
            conn.execute(
                "UPDATE leases SET expires_at = ?, renewed_at = ? WHERE lease_id = ?",
                [expires, now, lid],
            )
            return LeaseRecord(
                tenant=row["tenant"],
                graph_id=row["graph_id"],
                branch=row["branch"],
                lease_id=row["lease_id"],
                holder=row["holder"],
                epoch=int(row["epoch"]),
                expires_at=expires,
                created_at=row["created_at"],
                renewed_at=now,
            )

    def release_lease(self, lease_id: str) -> None:
        lid = require_lease_id(lease_id)
        with self._txn() as conn:
            row = self._fetchone(
                conn, "SELECT * FROM leases WHERE lease_id = ?", [lid]
            )
            if row is None:
                raise CatalogError("NOT_FOUND", "lease not found", details={"lease_id": lid})
            conn.execute(
                "DELETE FROM leases WHERE lease_id = ?",
                [lid],
            )

    def set_pin_root(
        self,
        tenant: str,
        graph_id: str,
        revision_id: str,
        root_cid: str,
        *,
        pin_kind: str = "explicit",
    ) -> PinRootRecord:
        tenant = require_slug(tenant, field="tenant")
        graph_id = require_slug(graph_id, field="graph_id")
        revision_id = require_revision_id(revision_id, field="revision_id")
        if not isinstance(root_cid, str) or not root_cid.strip():
            raise CatalogError("INVALID_REQUEST", "root_cid is required")
        with self._txn() as conn:
            self._get_graph_row(conn, tenant, graph_id)
            self._get_revision_row(conn, tenant, graph_id, revision_id)
            pin_id = new_pin_id()
            now = utc_now_iso()
            conn.execute(
                "INSERT INTO pin_roots "
                "(pin_id, tenant, graph_id, revision_id, root_cid, pin_kind, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [pin_id, tenant, graph_id, revision_id, root_cid.strip(), pin_kind, now],
            )
            return PinRootRecord(
                tenant=tenant,
                graph_id=graph_id,
                revision_id=revision_id,
                root_cid=root_cid.strip(),
                pin_kind=pin_kind,
                created_at=now,
                pin_id=pin_id,
            )

    def list_pin_roots(self, tenant: str, graph_id: str) -> list[PinRootRecord]:
        tenant = require_slug(tenant, field="tenant")
        graph_id = require_slug(graph_id, field="graph_id")
        with self._txn() as conn:
            self._get_graph_row(conn, tenant, graph_id)
            rows = self._fetchall(
                conn,
                "SELECT * FROM pin_roots WHERE tenant = ? AND graph_id = ? "
                "ORDER BY created_at, pin_id",
                [tenant, graph_id],
            )
            return [
                PinRootRecord(
                    tenant=row["tenant"],
                    graph_id=row["graph_id"],
                    revision_id=row["revision_id"],
                    root_cid=row["root_cid"],
                    pin_kind=row["pin_kind"],
                    created_at=row["created_at"],
                    pin_id=row["pin_id"],
                )
                for row in rows
            ]

    def get_idempotency(self, key: str) -> Optional[IdempotencyRecord]:
        key = require_idempotency_key(key)
        with self._txn() as conn:
            row = self._fetchone(
                conn, "SELECT * FROM idempotency_keys WHERE key = ?", [key]
            )
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

    def get_branch(
        self, tenant: str, graph_id: str, branch: str
    ) -> BranchRecord:
        tenant = require_slug(tenant, field="tenant")
        graph_id = require_slug(graph_id, field="graph_id")
        branch = require_slug(branch, field="branch")
        with self._txn() as conn:
            return self._branch_from_row(
                self._get_branch_row(conn, tenant, graph_id, branch)
            )
