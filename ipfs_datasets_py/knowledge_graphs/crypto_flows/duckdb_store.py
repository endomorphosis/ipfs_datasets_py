"""DuckDB-backed durable crypto-flow graph snapshot store (DQK-019).

Replaces process-local :class:`~.store.InMemoryGraphSnapshotStore` with a
durable embedded DuckDB store that:

* Persists immutable :class:`~.model.GraphSnapshot` records with deterministic
  content identities (digest / CID)
* Indexes observed-address vs asserted-entity planes without collapsing them
* Preserves ambiguity, retractions, and reorg lineage as first-class rows so
  history is retained rather than discarded
* Publishes each snapshot in a single transaction so concurrent readers never
  observe partial snapshots

Importing this module does not open DuckDB until a store path is constructed.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Iterator, Optional, Union

from .model import (
    AmbiguityKind,
    CryptoFlowValidationError,
    FinalityStatus,
    GraphPlane,
    GraphSnapshot,
    RetractionStatus,
    merge_provider_ids,
)
from .store import SnapshotStoreError

PathLike = Union[str, Path]

# ---------------------------------------------------------------------------
# Schema pins
# ---------------------------------------------------------------------------

DUCKDB_CRYPTO_FLOW_SNAPSHOT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/crypto-flows-duckdb-snapshot@1"
)
SCHEMA_VERSION: Final[int] = 1

SNAPSHOT_STATUS_PUBLISHED: Final[str] = "published"

CRYPTO_FLOW_SNAPSHOT_TABLES: Final[tuple[str, ...]] = (
    "crypto_flow_meta",
    "crypto_flow_snapshots",
    "crypto_flow_nodes",
    "crypto_flow_edges",
    "crypto_flow_lineage_events",
)

_SCHEMA_SQL: Final[tuple[str, ...]] = (
    """
    CREATE TABLE IF NOT EXISTS crypto_flow_meta (
        key VARCHAR PRIMARY KEY,
        value VARCHAR NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS crypto_flow_snapshots (
        snapshot_id VARCHAR PRIMARY KEY,
        graph_id VARCHAR NOT NULL,
        identity_digest VARCHAR NOT NULL,
        identity_cid VARCHAR NOT NULL,
        graph_digest VARCHAR NOT NULL,
        graph_cid VARCHAR NOT NULL,
        completeness VARCHAR NOT NULL,
        created_at VARCHAR NOT NULL DEFAULT '',
        schema_version VARCHAR NOT NULL,
        status VARCHAR NOT NULL,
        snapshot_json VARCHAR NOT NULL,
        stored_at VARCHAR NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS crypto_flow_nodes (
        snapshot_id VARCHAR NOT NULL,
        node_id VARCHAR NOT NULL,
        plane VARCHAR NOT NULL,
        kind VARCHAR NOT NULL,
        ambiguity VARCHAR NOT NULL,
        retraction VARCHAR NOT NULL,
        finality VARCHAR NOT NULL,
        address_ref VARCHAR NOT NULL DEFAULT '',
        entity_ref VARCHAR NOT NULL DEFAULT '',
        node_json VARCHAR NOT NULL,
        PRIMARY KEY (snapshot_id, node_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS crypto_flow_edges (
        snapshot_id VARCHAR NOT NULL,
        edge_id VARCHAR NOT NULL,
        plane VARCHAR NOT NULL,
        kind VARCHAR NOT NULL,
        ambiguity VARCHAR NOT NULL,
        retraction VARCHAR NOT NULL,
        finality VARCHAR NOT NULL,
        source_node_id VARCHAR NOT NULL,
        target_node_id VARCHAR NOT NULL,
        edge_json VARCHAR NOT NULL,
        PRIMARY KEY (snapshot_id, edge_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS crypto_flow_lineage_events (
        snapshot_id VARCHAR NOT NULL,
        entity_kind VARCHAR NOT NULL,
        entity_id VARCHAR NOT NULL,
        event_kind VARCHAR NOT NULL,
        plane VARCHAR NOT NULL,
        finality VARCHAR NOT NULL,
        retraction VARCHAR NOT NULL,
        ambiguity VARCHAR NOT NULL,
        payload_json VARCHAR NOT NULL,
        PRIMARY KEY (snapshot_id, entity_kind, entity_id, event_kind)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_cf_nodes_plane
        ON crypto_flow_nodes (snapshot_id, plane)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_cf_edges_plane
        ON crypto_flow_edges (snapshot_id, plane)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_cf_edges_retraction
        ON crypto_flow_edges (snapshot_id, retraction)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_cf_edges_finality
        ON crypto_flow_edges (snapshot_id, finality)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_cf_lineage_kind
        ON crypto_flow_lineage_events (event_kind, snapshot_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_cf_snapshots_graph_digest
        ON crypto_flow_snapshots (graph_digest)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_cf_snapshots_status
        ON crypto_flow_snapshots (status)
    """,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_duckdb() -> Any:
    try:
        import duckdb  # type: ignore
    except ImportError as exc:  # pragma: no cover - environment gate
        raise SnapshotStoreError(
            "duckdb package is required for DuckDBGraphSnapshotStore"
        ) from exc
    return duckdb


def _json_dumps(value: Any) -> str:
    """Deterministic JSON encoding for durable rows."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _json_loads(text: str) -> Any:
    return json.loads(text)


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _lineage_event_kinds(
    *,
    finality: FinalityStatus,
    retraction: RetractionStatus,
    ambiguity: AmbiguityKind,
) -> tuple[str, ...]:
    """Return durable history event kinds for a node/edge row.

    Reorg and retraction history must be retained even when a later snapshot
    supersedes an observation: each published snapshot keeps its own lineage
    rows so auditors can reconstruct what was known at each identity.
    """
    kinds: list[str] = []
    if finality is FinalityStatus.REORGED or ambiguity is AmbiguityKind.REORG:
        kinds.append("reorg")
    if (
        finality is FinalityStatus.RETRACTED
        or retraction is RetractionStatus.RETRACTED
    ):
        kinds.append("retraction")
    if retraction is RetractionStatus.SUPERSEDED:
        kinds.append("supersession")
    if ambiguity is not AmbiguityKind.NONE and ambiguity is not AmbiguityKind.REORG:
        kinds.append("ambiguity")
    # De-dupe while preserving order.
    seen: set[str] = set()
    ordered: list[str] = []
    for kind in kinds:
        if kind not in seen:
            seen.add(kind)
            ordered.append(kind)
    return tuple(ordered)


@dataclass(frozen=True, slots=True)
class LineageEvent:
    """Indexed reorg / retraction / ambiguity history row."""

    snapshot_id: str
    entity_kind: str
    entity_id: str
    event_kind: str
    plane: str
    finality: str
    retraction: str
    ambiguity: str
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ambiguity": self.ambiguity,
            "entity_id": self.entity_id,
            "entity_kind": self.entity_kind,
            "event_kind": self.event_kind,
            "finality": self.finality,
            "payload": dict(self.payload),
            "plane": self.plane,
            "retraction": self.retraction,
            "snapshot_id": self.snapshot_id,
        }


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class DuckDBGraphSnapshotStore:
    """Durable immutable GraphSnapshot store backed by DuckDB.

    Implements the :class:`~.store.GraphSnapshotStore` protocol and adds plane
    / lineage query helpers.  Every ``put`` commits nodes, edges, lineage
    events, and the snapshot envelope in one transaction.  Readers only query
    rows with ``status='published'``, so an in-flight write is never visible.
    """

    def __init__(self, path: PathLike = ":memory:") -> None:
        duckdb = _require_duckdb()
        self._path_arg = path
        if path == ":memory:":
            self._path = Path(":memory:")
            connect_path = ":memory:"
        else:
            self._path = Path(path)
            if self._path.parent and str(self._path.parent) not in ("", "."):
                self._path.parent.mkdir(parents=True, exist_ok=True)
            connect_path = str(self._path)
        self._lock = threading.RLock()
        self._conn = duckdb.connect(connect_path)
        self._closed = False
        self._initialize_schema()

    # -- lifecycle -----------------------------------------------------------

    @property
    def path(self) -> Path:
        return self._path

    @property
    def schema_id(self) -> str:
        return DUCKDB_CRYPTO_FLOW_SNAPSHOT_SCHEMA

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            try:
                self._conn.close()
            finally:
                self._closed = True

    def __enter__(self) -> "DuckDBGraphSnapshotStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise SnapshotStoreError("crypto-flow snapshot store is closed")

    def _initialize_schema(self) -> None:
        with self._lock:
            for statement in _SCHEMA_SQL:
                self._conn.execute(statement)
            row = self._conn.execute(
                "SELECT value FROM crypto_flow_meta WHERE key = ?",
                ["schema_version"],
            ).fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO crypto_flow_meta (key, value) VALUES (?, ?), (?, ?)",
                    [
                        "schema_version",
                        str(SCHEMA_VERSION),
                        "schema_id",
                        DUCKDB_CRYPTO_FLOW_SNAPSHOT_SCHEMA,
                    ],
                )
            else:
                applied = int(row[0])
                if applied != SCHEMA_VERSION:
                    raise SnapshotStoreError(
                        f"database schema version {applied} != {SCHEMA_VERSION}"
                    )

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
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

    @contextmanager
    def _read(self) -> Iterator[Any]:
        """Shared read path: lock held so writers cannot interleave mid-read."""
        self._ensure_open()
        with self._lock:
            yield self._conn

    # -- GraphSnapshotStore protocol -----------------------------------------

    def put(self, snapshot: GraphSnapshot, *, overwrite: bool = False) -> str:
        """Persist a snapshot atomically; returns the store key (snapshot_id).

        Nodes, edges, lineage events, and the snapshot envelope are written in
        a single transaction and only become query-visible when the transaction
        commits with ``status='published'``.  Concurrent readers therefore never
        observe a partial snapshot.
        """
        if not isinstance(snapshot, GraphSnapshot):
            raise CryptoFlowValidationError("snapshot must be a GraphSnapshot")

        # Materialize an independent copy and pin content identity.
        stored = GraphSnapshot.from_dict(snapshot.to_dict())
        if stored.identity.digest != snapshot.identity.digest:
            raise CryptoFlowValidationError(
                "snapshot round-trip changed content identity"
            )
        if stored.snapshot_id != snapshot.snapshot_id:
            raise CryptoFlowValidationError("snapshot_id changed during materialization")

        identity = stored.identity
        graph_identity = stored.graph.identity
        snapshot_json = _json_dumps(stored.to_dict())
        stored_at = _utc_now_iso()

        with self._transaction() as conn:
            existing = conn.execute(
                "SELECT snapshot_id FROM crypto_flow_snapshots WHERE snapshot_id = ?",
                [stored.snapshot_id],
            ).fetchone()
            if existing is not None and not overwrite:
                raise SnapshotStoreError(
                    f"snapshot_id already present and immutable: {stored.snapshot_id}"
                )
            if existing is not None and overwrite:
                self._delete_snapshot_rows(conn, stored.snapshot_id)

            # Envelope first with published status only after child rows exist
            # is unnecessary inside one txn; we still insert children before
            # readers can see the commit.  Status is always published on commit.
            conn.execute(
                """
                INSERT INTO crypto_flow_snapshots (
                    snapshot_id, graph_id, identity_digest, identity_cid,
                    graph_digest, graph_cid, completeness, created_at,
                    schema_version, status, snapshot_json, stored_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    stored.snapshot_id,
                    stored.graph.graph_id,
                    identity.digest,
                    identity.cid,
                    graph_identity.digest,
                    graph_identity.cid,
                    stored.completeness.value,
                    stored.created_at,
                    stored.schema_version,
                    SNAPSHOT_STATUS_PUBLISHED,
                    snapshot_json,
                    stored_at,
                ],
            )

            for node in stored.graph.nodes:
                node_payload = node.to_dict()
                conn.execute(
                    """
                    INSERT INTO crypto_flow_nodes (
                        snapshot_id, node_id, plane, kind, ambiguity,
                        retraction, finality, address_ref, entity_ref, node_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        stored.snapshot_id,
                        node.node_id,
                        node.plane.value,
                        node.kind.value,
                        node.ambiguity.value,
                        node.retraction.value,
                        node.finality.value,
                        node.address_ref,
                        node.entity_ref,
                        _json_dumps(node_payload),
                    ],
                )
                for event_kind in _lineage_event_kinds(
                    finality=node.finality,
                    retraction=node.retraction,
                    ambiguity=node.ambiguity,
                ):
                    conn.execute(
                        """
                        INSERT INTO crypto_flow_lineage_events (
                            snapshot_id, entity_kind, entity_id, event_kind,
                            plane, finality, retraction, ambiguity, payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            stored.snapshot_id,
                            "node",
                            node.node_id,
                            event_kind,
                            node.plane.value,
                            node.finality.value,
                            node.retraction.value,
                            node.ambiguity.value,
                            _json_dumps(node_payload),
                        ],
                    )

            for edge in stored.graph.edges:
                edge_payload = edge.to_dict()
                conn.execute(
                    """
                    INSERT INTO crypto_flow_edges (
                        snapshot_id, edge_id, plane, kind, ambiguity,
                        retraction, finality, source_node_id, target_node_id,
                        edge_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        stored.snapshot_id,
                        edge.edge_id,
                        edge.plane.value,
                        edge.kind.value,
                        edge.ambiguity.value,
                        edge.retraction.value,
                        edge.finality.value,
                        edge.source_node_id,
                        edge.target_node_id,
                        _json_dumps(edge_payload),
                    ],
                )
                for event_kind in _lineage_event_kinds(
                    finality=edge.finality,
                    retraction=edge.retraction,
                    ambiguity=edge.ambiguity,
                ):
                    conn.execute(
                        """
                        INSERT INTO crypto_flow_lineage_events (
                            snapshot_id, entity_kind, entity_id, event_kind,
                            plane, finality, retraction, ambiguity, payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            stored.snapshot_id,
                            "edge",
                            edge.edge_id,
                            event_kind,
                            edge.plane.value,
                            edge.finality.value,
                            edge.retraction.value,
                            edge.ambiguity.value,
                            _json_dumps(edge_payload),
                        ],
                    )

        return stored.snapshot_id

    def get(self, snapshot_id: str) -> GraphSnapshot:
        """Fetch a published snapshot by id; fails closed if missing."""
        if not isinstance(snapshot_id, str) or not snapshot_id.strip():
            raise CryptoFlowValidationError("snapshot_id must be a non-empty string")
        with self._read() as conn:
            row = conn.execute(
                """
                SELECT snapshot_json, identity_digest, identity_cid,
                       graph_digest, graph_cid
                FROM crypto_flow_snapshots
                WHERE snapshot_id = ? AND status = ?
                """,
                [snapshot_id, SNAPSHOT_STATUS_PUBLISHED],
            ).fetchone()
        if row is None:
            raise SnapshotStoreError(f"snapshot not found: {snapshot_id}")
        snapshot_json, identity_digest, identity_cid, graph_digest, graph_cid = row
        payload = _json_loads(snapshot_json)
        loaded = GraphSnapshot.from_dict(payload)
        if loaded.identity.digest != identity_digest:
            raise SnapshotStoreError(
                f"stored identity_digest mismatch for {snapshot_id}: "
                f"{loaded.identity.digest} != {identity_digest}"
            )
        if loaded.identity.cid != identity_cid:
            raise SnapshotStoreError(
                f"stored identity_cid mismatch for {snapshot_id}"
            )
        if loaded.graph.identity.digest != graph_digest:
            raise SnapshotStoreError(
                f"stored graph_digest mismatch for {snapshot_id}"
            )
        if loaded.graph.identity.cid != graph_cid:
            raise SnapshotStoreError(
                f"stored graph_cid mismatch for {snapshot_id}"
            )
        return loaded

    def get_by_digest(self, graph_digest: str) -> GraphSnapshot:
        """Fetch the first published snapshot whose graph digest matches."""
        if not isinstance(graph_digest, str) or not graph_digest.strip():
            raise CryptoFlowValidationError("graph_digest must be a non-empty string")
        with self._read() as conn:
            row = conn.execute(
                """
                SELECT snapshot_id
                FROM crypto_flow_snapshots
                WHERE graph_digest = ? AND status = ?
                ORDER BY snapshot_id
                LIMIT 1
                """,
                [graph_digest, SNAPSHOT_STATUS_PUBLISHED],
            ).fetchone()
        if row is None:
            raise SnapshotStoreError(f"no snapshot for graph_digest: {graph_digest}")
        return self.get(row[0])

    def list_ids(self) -> tuple[str, ...]:
        """Return sorted published snapshot identifiers."""
        with self._read() as conn:
            rows = conn.execute(
                """
                SELECT snapshot_id
                FROM crypto_flow_snapshots
                WHERE status = ?
                ORDER BY snapshot_id
                """,
                [SNAPSHOT_STATUS_PUBLISHED],
            ).fetchall()
        return tuple(str(r[0]) for r in rows)

    def contains(self, snapshot_id: str) -> bool:
        if not isinstance(snapshot_id, str) or not snapshot_id:
            return False
        with self._read() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM crypto_flow_snapshots
                WHERE snapshot_id = ? AND status = ?
                LIMIT 1
                """,
                [snapshot_id, SNAPSHOT_STATUS_PUBLISHED],
            ).fetchone()
        return row is not None

    # -- InMemory parity helpers ---------------------------------------------

    def providers_union(self) -> tuple[str, ...]:
        """Union of covered providers across all published snapshots."""
        groups: list[Sequence[str]] = []
        for sid in self.list_ids():
            groups.append(self.get(sid).covered_providers)
        return merge_provider_ids(*groups)

    def completeness_index(self) -> Mapping[str, str]:
        """Map snapshot_id -> completeness status value."""
        with self._read() as conn:
            rows = conn.execute(
                """
                SELECT snapshot_id, completeness
                FROM crypto_flow_snapshots
                WHERE status = ?
                ORDER BY snapshot_id
                """,
                [SNAPSHOT_STATUS_PUBLISHED],
            ).fetchall()
        return {str(r[0]): str(r[1]) for r in rows}

    def identity_index(self) -> Mapping[str, str]:
        """Map snapshot_id -> content identity digest (deterministic)."""
        with self._read() as conn:
            rows = conn.execute(
                """
                SELECT snapshot_id, identity_digest
                FROM crypto_flow_snapshots
                WHERE status = ?
                ORDER BY snapshot_id
                """,
                [SNAPSHOT_STATUS_PUBLISHED],
            ).fetchall()
        return {str(r[0]): str(r[1]) for r in rows}

    # -- Plane / lineage queries ---------------------------------------------

    def list_node_ids_on_plane(
        self, snapshot_id: str, plane: GraphPlane | str
    ) -> tuple[str, ...]:
        plane_value = plane.value if isinstance(plane, GraphPlane) else str(plane)
        with self._read() as conn:
            self._require_published(conn, snapshot_id)
            rows = conn.execute(
                """
                SELECT node_id
                FROM crypto_flow_nodes
                WHERE snapshot_id = ? AND plane = ?
                ORDER BY node_id
                """,
                [snapshot_id, plane_value],
            ).fetchall()
        return tuple(str(r[0]) for r in rows)

    def list_edge_ids_on_plane(
        self, snapshot_id: str, plane: GraphPlane | str
    ) -> tuple[str, ...]:
        plane_value = plane.value if isinstance(plane, GraphPlane) else str(plane)
        with self._read() as conn:
            self._require_published(conn, snapshot_id)
            rows = conn.execute(
                """
                SELECT edge_id
                FROM crypto_flow_edges
                WHERE snapshot_id = ? AND plane = ?
                ORDER BY edge_id
                """,
                [snapshot_id, plane_value],
            ).fetchall()
        return tuple(str(r[0]) for r in rows)

    def list_lineage_events(
        self,
        *,
        snapshot_id: Optional[str] = None,
        event_kind: Optional[str] = None,
    ) -> tuple[LineageEvent, ...]:
        """Return retained reorg / retraction / ambiguity history rows."""
        clauses = ["1=1"]
        params: list[Any] = []
        if snapshot_id is not None:
            clauses.append("snapshot_id = ?")
            params.append(snapshot_id)
        if event_kind is not None:
            clauses.append("event_kind = ?")
            params.append(event_kind)
        sql = f"""
            SELECT snapshot_id, entity_kind, entity_id, event_kind,
                   plane, finality, retraction, ambiguity, payload_json
            FROM crypto_flow_lineage_events
            WHERE {' AND '.join(clauses)}
            ORDER BY snapshot_id, entity_kind, entity_id, event_kind
        """
        with self._read() as conn:
            rows = conn.execute(sql, params).fetchall()
        events: list[LineageEvent] = []
        for row in rows:
            events.append(
                LineageEvent(
                    snapshot_id=str(row[0]),
                    entity_kind=str(row[1]),
                    entity_id=str(row[2]),
                    event_kind=str(row[3]),
                    plane=str(row[4]),
                    finality=str(row[5]),
                    retraction=str(row[6]),
                    ambiguity=str(row[7]),
                    payload=_json_loads(row[8]),
                )
            )
        return tuple(events)

    def list_reorg_history(
        self, *, snapshot_id: Optional[str] = None
    ) -> tuple[LineageEvent, ...]:
        return self.list_lineage_events(snapshot_id=snapshot_id, event_kind="reorg")

    def list_retraction_history(
        self, *, snapshot_id: Optional[str] = None
    ) -> tuple[LineageEvent, ...]:
        return self.list_lineage_events(
            snapshot_id=snapshot_id, event_kind="retraction"
        )

    def list_tables(self) -> list[str]:
        with self._read() as conn:
            rows = conn.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'main'
                ORDER BY table_name
                """
            ).fetchall()
        return [str(r[0]) for r in rows]

    # -- internals -----------------------------------------------------------

    def _require_published(self, conn: Any, snapshot_id: str) -> None:
        row = conn.execute(
            """
            SELECT 1 FROM crypto_flow_snapshots
            WHERE snapshot_id = ? AND status = ?
            LIMIT 1
            """,
            [snapshot_id, SNAPSHOT_STATUS_PUBLISHED],
        ).fetchone()
        if row is None:
            raise SnapshotStoreError(f"snapshot not found: {snapshot_id}")

    @staticmethod
    def _delete_snapshot_rows(conn: Any, snapshot_id: str) -> None:
        conn.execute(
            "DELETE FROM crypto_flow_lineage_events WHERE snapshot_id = ?",
            [snapshot_id],
        )
        conn.execute(
            "DELETE FROM crypto_flow_edges WHERE snapshot_id = ?",
            [snapshot_id],
        )
        conn.execute(
            "DELETE FROM crypto_flow_nodes WHERE snapshot_id = ?",
            [snapshot_id],
        )
        conn.execute(
            "DELETE FROM crypto_flow_snapshots WHERE snapshot_id = ?",
            [snapshot_id],
        )


__all__ = [
    "CRYPTO_FLOW_SNAPSHOT_TABLES",
    "DUCKDB_CRYPTO_FLOW_SNAPSHOT_SCHEMA",
    "SCHEMA_VERSION",
    "DuckDBGraphSnapshotStore",
    "LineageEvent",
]
