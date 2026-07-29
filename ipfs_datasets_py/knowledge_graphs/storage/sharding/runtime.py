"""Cross-shard traversal, verified fetch, prefetch budgets, failure policy (KGP-014).

The runtime loads a v2 :class:`ShardedGraphManifest`, verifies every fetched
block, routes entity ids deterministically, expands neighbors including
cross-shard edges, and prefetches peer shards within a byte/count/time budget.
Missing, corrupt, and slow shards are surfaced as typed failures; callers choose
``fail_fast`` or ``partial`` policy.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional, Sequence

from ipfs_datasets_py.knowledge_graphs.contracts.manifest import ContentChecksum
from ipfs_datasets_py.knowledge_graphs.storage.sharding.blocks import (
    BlockStore,
    ShardBlockError,
    decode_json_block,
    verify_block,
)
from ipfs_datasets_py.knowledge_graphs.storage.sharding.manifest import (
    CrossShardAdjacencyDescriptor,
    PhysicalShardDescriptor,
    ShardedGraphManifest,
)
from ipfs_datasets_py.knowledge_graphs.storage.sharding.models import (
    EntityRecord,
    GraphFragment,
    RelationshipRecord,
)
from ipfs_datasets_py.knowledge_graphs.storage.sharding.publish import decode_car_payload
from ipfs_datasets_py.knowledge_graphs.storage.sharding.routing import ShardRouter


# ---------------------------------------------------------------------------
# Failure policy + result types
# ---------------------------------------------------------------------------


class FailurePolicy(str, Enum):
    """How the runtime reacts to missing/corrupt/slow shards."""

    FAIL_FAST = "fail_fast"
    """Raise on the first hard failure."""

    PARTIAL = "partial"
    """Return available results plus typed warnings/failures."""

    SKIP_CORRUPT = "skip_corrupt"
    """Treat INTEGRITY failures as skippable; still fail on budget/timeouts
    only when no partial data can be produced."""


@dataclass(frozen=True, slots=True)
class ShardFailure:
    """One typed shard-level failure."""

    code: str
    message: str
    physical_shard_id: Optional[str] = None
    cid: Optional[str] = None
    path: Optional[str] = None
    retryable: bool = False
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "physical_shard_id": self.physical_shard_id,
            "cid": self.cid,
            "path": self.path,
            "retryable": self.retryable,
            "details": dict(self.details),
        }

    @classmethod
    def from_block_error(
        cls,
        exc: ShardBlockError,
        *,
        physical_shard_id: Optional[str] = None,
    ) -> "ShardFailure":
        return cls(
            code=exc.code,
            message=exc.message,
            physical_shard_id=physical_shard_id or exc.physical_shard_id,
            cid=exc.cid,
            path=exc.path,
            retryable=exc.retryable,
            details=dict(exc.details),
        )


class ShardedQueryError(Exception):
    """Hard failure under fail-fast (or unrecoverable) policy."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        failures: Sequence[ShardFailure] = (),
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.code = code
        self.message = message
        self.failures = tuple(failures)
        self.details = dict(details or {})
        super().__init__(f"[{code}] {message}")


@dataclass(frozen=True, slots=True)
class PrefetchBudget:
    """Limits for proactive shard/index fetches."""

    max_shards: int = 8
    max_bytes: int = 16 * 1024 * 1024
    max_blocks: int = 64
    max_seconds: float = 5.0

    def __post_init__(self) -> None:
        if self.max_shards < 0 or self.max_bytes < 0 or self.max_blocks < 0:
            raise ValueError("prefetch budget limits must be >= 0")
        if self.max_seconds < 0:
            raise ValueError("max_seconds must be >= 0")


@dataclass
class PrefetchStats:
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    bytes_fetched: int = 0
    blocks_fetched: int = 0
    budget_exhausted: bool = False
    elapsed_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class NeighborEdge:
    """One adjacency edge returned by the runtime."""

    relationship_id: str
    relationship_type: str
    source_id: str
    target_id: str
    direction: str  # outgoing | incoming
    cross_shard: bool = False
    peer_physical_shard_id: Optional[str] = None
    properties: Mapping[str, Any] = field(default_factory=dict)

    def other_id(self, entity_id: str) -> str:
        if entity_id == self.source_id:
            return self.target_id
        return self.source_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "relationship_id": self.relationship_id,
            "relationship_type": self.relationship_type,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "direction": self.direction,
            "cross_shard": self.cross_shard,
            "peer_physical_shard_id": self.peer_physical_shard_id,
            "properties": dict(self.properties) if self.properties else None,
        }


@dataclass
class QueryResult:
    """Envelope for lookups and traversals under partial/failure policy."""

    ok: bool
    partial: bool = False
    entities: dict[str, EntityRecord] = field(default_factory=dict)
    edges: list[NeighborEdge] = field(default_factory=list)
    failures: list[ShardFailure] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "partial": self.partial,
            "entities": {k: v.to_dict() for k, v in self.entities.items()},
            "edges": [e.to_dict() for e in self.edges],
            "failures": [f.to_dict() for f in self.failures],
            "warnings": list(self.warnings),
            "stats": dict(self.stats),
        }


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------


class ShardedQueryRuntime:
    """Verified reader over a published v2 sharded graph."""

    def __init__(
        self,
        manifest: ShardedGraphManifest,
        store: BlockStore,
        *,
        failure_policy: FailurePolicy | str = FailurePolicy.PARTIAL,
        prefetch_budget: PrefetchBudget | None = None,
        shard_fetch_timeout_seconds: float = 2.0,
    ) -> None:
        if not manifest.physical_shards:
            raise ValueError("manifest must contain at least one physical shard")
        self.manifest = manifest
        self.store = store
        self.router = ShardRouter.from_manifest(manifest)
        self.failure_policy = FailurePolicy(failure_policy)
        self.prefetch_budget = prefetch_budget or PrefetchBudget()
        self.shard_fetch_timeout_seconds = float(shard_fetch_timeout_seconds)

        self._physical = {p.physical_shard_id: p for p in manifest.physical_shards}
        self._fragment_cache: dict[str, GraphFragment] = {}
        self._neighbors_cache: dict[str, dict[str, dict[str, Any]]] = {}
        self._headers_cache: dict[str, dict[str, EntityRecord]] = {}
        self._bytes_fetched: int = 0
        self._blocks_fetched: int = 0

    # -- low-level verified fetch -------------------------------------------

    def _handle_failure(
        self,
        failure: ShardFailure,
        *,
        accum: list[ShardFailure],
    ) -> None:
        accum.append(failure)
        hard = failure.code in {"INTEGRITY", "NOT_FOUND", "TIMEOUT", "STORAGE", "BUDGET_EXCEEDED"}
        skippable_integrity = (
            self.failure_policy == FailurePolicy.SKIP_CORRUPT
            and failure.code == "INTEGRITY"
        )
        if self.failure_policy == FailurePolicy.FAIL_FAST and hard:
            raise ShardedQueryError(
                failure.code,
                failure.message,
                failures=tuple(accum),
            )
        if (
            self.failure_policy == FailurePolicy.SKIP_CORRUPT
            and hard
            and not skippable_integrity
            and failure.code not in {"NOT_FOUND"}
        ):
            # SKIP_CORRUPT still fails fast on timeout/storage when explicitly hard.
            if failure.code in {"TIMEOUT", "BUDGET_EXCEEDED"}:
                raise ShardedQueryError(
                    failure.code,
                    failure.message,
                    failures=tuple(accum),
                )

    def fetch_block(
        self,
        *,
        cid: Optional[str] = None,
        path: Optional[str] = None,
        checksum: Optional[ContentChecksum] = None,
        physical_shard_id: Optional[str] = None,
        label: str = "block",
        timeout_seconds: Optional[float] = None,
    ) -> bytes:
        """Fetch and verify a block; always verifies integrity."""
        timeout = (
            self.shard_fetch_timeout_seconds
            if timeout_seconds is None
            else float(timeout_seconds)
        )
        started = time.monotonic()
        try:
            # Store-level latency injection simulates slow shards; enforce timeout.
            data = self.store.get(
                cid=cid,
                path=path,
                checksum=checksum,
                label=label,
            )
        except ShardBlockError as exc:
            if physical_shard_id and not exc.physical_shard_id:
                exc.physical_shard_id = physical_shard_id
            raise
        except Exception as exc:  # pragma: no cover
            raise ShardBlockError(
                "STORAGE",
                f"{label}: store error: {exc}",
                cid=cid,
                path=path,
                physical_shard_id=physical_shard_id,
                retryable=True,
            ) from exc

        elapsed = time.monotonic() - started
        if timeout > 0 and elapsed > timeout:
            raise ShardBlockError(
                "TIMEOUT",
                f"{label}: shard fetch exceeded {timeout}s (took {elapsed:.3f}s)",
                cid=cid,
                path=path,
                physical_shard_id=physical_shard_id,
                retryable=True,
                details={"elapsed_seconds": elapsed, "timeout_seconds": timeout},
            )

        # Explicit second verification pass (acceptance: verify all fetched blocks).
        verify_block(
            data,
            checksum=checksum,
            cid=cid,
            label=label,
        )
        self._bytes_fetched += len(data)
        self._blocks_fetched += 1
        return data

    def load_physical_shard(
        self,
        physical_shard_id: str,
        *,
        failures: Optional[list[ShardFailure]] = None,
    ) -> Optional[GraphFragment]:
        """Load and verify a physical CAR shard into a :class:`GraphFragment`."""
        if physical_shard_id in self._fragment_cache:
            return self._fragment_cache[physical_shard_id]

        phys = self._physical.get(physical_shard_id)
        if phys is None:
            failure = ShardFailure(
                code="NOT_FOUND",
                message=f"unknown physical shard {physical_shard_id!r}",
                physical_shard_id=physical_shard_id,
            )
            if failures is not None:
                self._handle_failure(failure, accum=failures)
            elif self.failure_policy == FailurePolicy.FAIL_FAST:
                raise ShardedQueryError(failure.code, failure.message, failures=(failure,))
            return None

        try:
            car_bytes = self.fetch_block(
                cid=phys.car_cid,
                path=phys.path,
                checksum=phys.checksum,
                physical_shard_id=physical_shard_id,
                label=f"car:{physical_shard_id}",
            )
            payload = decode_car_payload(car_bytes)
            frag = GraphFragment.from_payload_dict(payload)
            self._fragment_cache[physical_shard_id] = frag
            return frag
        except ShardBlockError as exc:
            failure = ShardFailure.from_block_error(
                exc, physical_shard_id=physical_shard_id
            )
            if failures is not None:
                self._handle_failure(failure, accum=failures)
                return None
            raise ShardedQueryError(
                failure.code,
                failure.message,
                failures=(failure,),
            ) from exc

    # -- indexes ------------------------------------------------------------

    def _load_neighbors_index(
        self,
        phys: PhysicalShardDescriptor,
        *,
        failures: list[ShardFailure],
    ) -> dict[str, dict[str, Any]]:
        if phys.physical_shard_id in self._neighbors_cache:
            return self._neighbors_cache[phys.physical_shard_id]

        if not phys.neighbors_index_cid:
            return {}

        try:
            raw = self.fetch_block(
                cid=phys.neighbors_index_cid,
                physical_shard_id=phys.physical_shard_id,
                label=f"neighbors:{phys.physical_shard_id}",
            )
            obj = decode_json_block(raw)
        except ShardBlockError as exc:
            self._handle_failure(
                ShardFailure.from_block_error(exc, physical_shard_id=phys.physical_shard_id),
                accum=failures,
            )
            return {}

        result: dict[str, dict[str, Any]] = {}
        if not isinstance(obj, dict):
            return result

        if int(obj.get("v", 1)) == 2:
            prefix_len = int(obj.get("prefix_len") or 0)
            buckets = obj.get("buckets") or {}
            # Load all buckets (bounded by index_buckets descriptors).
            for _bkey, bcid in buckets.items():
                if not isinstance(bcid, str):
                    continue
                try:
                    braw = self.fetch_block(
                        cid=bcid,
                        physical_shard_id=phys.physical_shard_id,
                        label=f"neighbors-bucket:{phys.physical_shard_id}",
                    )
                    bucket = decode_json_block(braw)
                    if isinstance(bucket, dict):
                        for eid, adj in bucket.items():
                            if isinstance(adj, dict):
                                result[str(eid)] = adj
                except ShardBlockError as exc:
                    self._handle_failure(
                        ShardFailure.from_block_error(
                            exc, physical_shard_id=phys.physical_shard_id
                        ),
                        accum=failures,
                    )
            _ = prefix_len  # retained for API symmetry / future selective fetch
        else:
            for eid, adj in obj.items():
                if isinstance(adj, dict) and (
                    "outgoing" in adj or "incoming" in adj
                ):
                    result[str(eid)] = adj

        self._neighbors_cache[phys.physical_shard_id] = result
        return result

    def _load_headers(
        self,
        phys: PhysicalShardDescriptor,
        *,
        failures: list[ShardFailure],
    ) -> dict[str, EntityRecord]:
        if phys.physical_shard_id in self._headers_cache:
            return self._headers_cache[phys.physical_shard_id]

        if not phys.headers_cid:
            return {}

        try:
            raw = self.fetch_block(
                cid=phys.headers_cid,
                physical_shard_id=phys.physical_shard_id,
                label=f"headers:{phys.physical_shard_id}",
            )
            obj = decode_json_block(raw)
        except ShardBlockError as exc:
            self._handle_failure(
                ShardFailure.from_block_error(exc, physical_shard_id=phys.physical_shard_id),
                accum=failures,
            )
            return {}

        headers: dict[str, EntityRecord] = {}
        if not isinstance(obj, dict):
            return headers

        if int(obj.get("v", 1)) == 2:
            buckets = obj.get("buckets") or {}
            for _bkey, bcid in buckets.items():
                if not isinstance(bcid, str):
                    continue
                try:
                    braw = self.fetch_block(
                        cid=bcid,
                        physical_shard_id=phys.physical_shard_id,
                        label=f"headers-bucket:{phys.physical_shard_id}",
                    )
                    bucket = decode_json_block(braw)
                    if isinstance(bucket, dict):
                        for eid, h in bucket.items():
                            if isinstance(h, dict):
                                headers[str(eid)] = EntityRecord(
                                    entity_id=str(eid),
                                    entity_type=str(h.get("type") or ""),
                                    name=h.get("name"),
                                    properties=(
                                        dict(h["properties"])
                                        if isinstance(h.get("properties"), Mapping)
                                        else {}
                                    ),
                                    cid=h.get("cid"),
                                )
                except ShardBlockError as exc:
                    self._handle_failure(
                        ShardFailure.from_block_error(
                            exc, physical_shard_id=phys.physical_shard_id
                        ),
                        accum=failures,
                    )
        else:
            for eid, h in obj.items():
                if isinstance(h, dict):
                    headers[str(eid)] = EntityRecord(
                        entity_id=str(eid),
                        entity_type=str(h.get("type") or ""),
                        name=h.get("name"),
                        properties=(
                            dict(h["properties"])
                            if isinstance(h.get("properties"), Mapping)
                            else {}
                        ),
                        cid=h.get("cid"),
                    )

        self._headers_cache[phys.physical_shard_id] = headers
        return headers

    # -- public query API ---------------------------------------------------

    def route_entity(self, entity_id: str) -> str:
        return self.router.route(entity_id)

    def get_entities(self, entity_ids: Sequence[str]) -> QueryResult:
        """Lookup entity headers (and full records when CAR is available)."""
        failures: list[ShardFailure] = []
        entities: dict[str, EntityRecord] = {}
        by_shard: dict[str, list[str]] = {}
        for eid in entity_ids:
            by_shard.setdefault(self.route_entity(eid), []).append(eid)

        for pid, eids in by_shard.items():
            phys = self._physical.get(pid)
            if phys is None:
                self._handle_failure(
                    ShardFailure(
                        code="NOT_FOUND",
                        message=f"unknown physical shard {pid!r}",
                        physical_shard_id=pid,
                    ),
                    accum=failures,
                )
                continue

            headers = self._load_headers(phys, failures=failures)
            for eid in eids:
                if eid in headers:
                    entities[eid] = headers[eid]

            missing = [eid for eid in eids if eid not in entities]
            if missing:
                frag = self.load_physical_shard(pid, failures=failures)
                if frag is not None:
                    for eid in missing:
                        if eid in frag.entities:
                            entities[eid] = frag.entities[eid]

        partial = bool(failures) and bool(entities)
        ok = bool(entities) and (
            not failures or self.failure_policy != FailurePolicy.FAIL_FAST
        )
        if not entities and failures and self.failure_policy == FailurePolicy.FAIL_FAST:
            raise ShardedQueryError(
                failures[0].code,
                failures[0].message,
                failures=tuple(failures),
            )
        return QueryResult(
            ok=ok or bool(entities),
            partial=partial or (bool(failures) and bool(entities)),
            entities=entities,
            failures=failures,
            stats={
                "requested": len(entity_ids),
                "found": len(entities),
                "bytes_fetched": self._bytes_fetched,
                "blocks_fetched": self._blocks_fetched,
            },
        )

    def neighbors(
        self,
        entity_id: str,
        *,
        direction: str = "both",
        relationship_types: Optional[Sequence[str]] = None,
        include_cross_shard: bool = True,
        prefetch: bool = True,
    ) -> QueryResult:
        """Return neighbors of *entity_id*, including cross-shard edges.

        When ``prefetch`` is true, peer physical shards referenced by
        cross-shard edges are prefetched within :class:`PrefetchBudget`.
        """
        if direction not in {"outgoing", "incoming", "both"}:
            raise ShardedQueryError(
                "INVALID_REQUEST",
                f"invalid direction {direction!r}",
            )

        failures: list[ShardFailure] = []
        pid = self.route_entity(entity_id)
        phys = self._physical.get(pid)
        edges: list[NeighborEdge] = []
        entities: dict[str, EntityRecord] = {}
        type_filter = set(relationship_types) if relationship_types else None

        if phys is None:
            failure = ShardFailure(
                code="NOT_FOUND",
                message=f"unknown physical shard for entity {entity_id!r}",
                physical_shard_id=pid,
            )
            if self.failure_policy == FailurePolicy.FAIL_FAST:
                raise ShardedQueryError(failure.code, failure.message, failures=(failure,))
            return QueryResult(ok=False, partial=False, failures=[failure])

        # Seed entity header
        headers = self._load_headers(phys, failures=failures)
        if entity_id in headers:
            entities[entity_id] = headers[entity_id]

        nindex = self._load_neighbors_index(phys, failures=failures)
        adj = nindex.get(entity_id)

        if adj is None:
            # Fallback: reconstruct from CAR fragment + cross-shard adjacency descriptors.
            frag = self.load_physical_shard(pid, failures=failures)
            adj = {"outgoing": [], "incoming": []}
            if frag is not None:
                if entity_id in frag.entities:
                    entities[entity_id] = frag.entities[entity_id]
                for rel in frag.iter_relationships():
                    if rel.source_id == entity_id:
                        adj["outgoing"].append(rel.to_neighbor_dict(cross_shard=False))
                    if rel.target_id == entity_id:
                        adj["incoming"].append(rel.to_neighbor_dict(cross_shard=False))
                # Merge explicit cross-shard adjacency for this entity.
                for cross in self._cross_edges_for_entity(entity_id, pid, failures=failures):
                    d = cross["direction"]
                    adj.setdefault(d, []).append(cross["edge"])

        def _accept(raw: Mapping[str, Any], dir_name: str) -> Optional[NeighborEdge]:
            rtype = str(raw.get("relationship_type") or "")
            if type_filter is not None and rtype not in type_filter:
                return None
            is_cross = bool(raw.get("cross_shard"))
            if is_cross and not include_cross_shard:
                return None
            return NeighborEdge(
                relationship_id=str(raw.get("relationship_id") or ""),
                relationship_type=rtype,
                source_id=str(raw.get("source_id") or ""),
                target_id=str(raw.get("target_id") or ""),
                direction=dir_name,
                cross_shard=is_cross,
                peer_physical_shard_id=raw.get("peer_physical_shard_id"),
                properties=(
                    dict(raw["properties"])
                    if isinstance(raw.get("properties"), Mapping)
                    else {}
                ),
            )

        if direction in {"outgoing", "both"}:
            for raw in adj.get("outgoing") or []:
                if isinstance(raw, Mapping):
                    edge = _accept(raw, "outgoing")
                    if edge is not None:
                        edges.append(edge)
        if direction in {"incoming", "both"}:
            for raw in adj.get("incoming") or []:
                if isinstance(raw, Mapping):
                    edge = _accept(raw, "incoming")
                    if edge is not None:
                        edges.append(edge)

        # Prefetch peer shards for cross-shard edges.
        prefetch_stats: Optional[PrefetchStats] = None
        if prefetch:
            peer_ids = sorted(
                {
                    e.peer_physical_shard_id
                    for e in edges
                    if e.cross_shard and e.peer_physical_shard_id
                }
            )
            if peer_ids:
                prefetch_stats = self.prefetch_shards(peer_ids, failures=failures)

        # Resolve neighbor entity headers from home shards.
        neighbor_ids = []
        for e in edges:
            neighbor_ids.append(e.other_id(entity_id))
        if neighbor_ids:
            got = self.get_entities(neighbor_ids)
            entities.update(got.entities)
            failures.extend(got.failures)

        partial = bool(failures)
        return QueryResult(
            ok=True if edges or entity_id in entities else not failures,
            partial=partial,
            entities=entities,
            edges=edges,
            failures=failures,
            stats={
                "home_shard": pid,
                "edge_count": len(edges),
                "cross_shard_edges": sum(1 for e in edges if e.cross_shard),
                "bytes_fetched": self._bytes_fetched,
                "blocks_fetched": self._blocks_fetched,
                "prefetch": None if prefetch_stats is None else {
                    "attempted": prefetch_stats.attempted,
                    "succeeded": prefetch_stats.succeeded,
                    "failed": prefetch_stats.failed,
                    "bytes_fetched": prefetch_stats.bytes_fetched,
                    "blocks_fetched": prefetch_stats.blocks_fetched,
                    "budget_exhausted": prefetch_stats.budget_exhausted,
                    "elapsed_seconds": prefetch_stats.elapsed_seconds,
                },
            },
        )

    def _cross_edges_for_entity(
        self,
        entity_id: str,
        home_pid: str,
        *,
        failures: list[ShardFailure],
    ) -> list[dict[str, Any]]:
        """Load cross-shard adjacency descriptors touching *entity_id*."""
        out: list[dict[str, Any]] = []
        for desc in self.manifest.cross_shard_adjacency:
            if (
                desc.source_physical_shard_id != home_pid
                and desc.target_physical_shard_id != home_pid
            ):
                continue
            try:
                raw = self.fetch_block(
                    cid=desc.cid,
                    path=desc.path,
                    checksum=desc.checksum,
                    physical_shard_id=home_pid,
                    label=f"xadj:{desc.adjacency_id}",
                )
                payload = decode_json_block(raw)
            except ShardBlockError as exc:
                self._handle_failure(
                    ShardFailure.from_block_error(exc, physical_shard_id=home_pid),
                    accum=failures,
                )
                continue

            for edge_raw in payload.get("edges") or []:
                if not isinstance(edge_raw, Mapping):
                    continue
                src = str(edge_raw.get("source_id") or "")
                tgt = str(edge_raw.get("target_id") or "")
                if entity_id not in (src, tgt):
                    continue
                if entity_id == src:
                    direction = "outgoing"
                    peer = desc.target_physical_shard_id
                else:
                    direction = "incoming"
                    peer = desc.source_physical_shard_id
                rel = RelationshipRecord.from_dict(edge_raw)
                out.append(
                    {
                        "direction": direction,
                        "edge": rel.to_neighbor_dict(
                            cross_shard=True,
                            peer_physical_shard_id=peer,
                        ),
                    }
                )
        return out

    def prefetch_shards(
        self,
        physical_shard_ids: Sequence[str],
        *,
        failures: Optional[list[ShardFailure]] = None,
    ) -> PrefetchStats:
        """Prefetch CAR + primary indexes for *physical_shard_ids* within budget."""
        budget = self.prefetch_budget
        stats = PrefetchStats()
        started = time.monotonic()
        accum = failures if failures is not None else []
        bytes_before = self._bytes_fetched
        blocks_before = self._blocks_fetched

        for i, pid in enumerate(physical_shard_ids):
            if i >= budget.max_shards:
                stats.budget_exhausted = True
                break
            if stats.bytes_fetched >= budget.max_bytes:
                stats.budget_exhausted = True
                break
            if stats.blocks_fetched >= budget.max_blocks:
                stats.budget_exhausted = True
                break
            if (time.monotonic() - started) > budget.max_seconds:
                stats.budget_exhausted = True
                failure = ShardFailure(
                    code="BUDGET_EXCEEDED",
                    message="prefetch time budget exhausted",
                    details={"max_seconds": budget.max_seconds},
                )
                self._handle_failure(failure, accum=accum)
                break

            stats.attempted += 1
            frag = self.load_physical_shard(pid, failures=accum)
            phys = self._physical.get(pid)
            if phys is not None:
                self._load_headers(phys, failures=accum)
                self._load_neighbors_index(phys, failures=accum)

            stats.bytes_fetched = self._bytes_fetched - bytes_before
            stats.blocks_fetched = self._blocks_fetched - blocks_before
            if frag is not None:
                stats.succeeded += 1
            else:
                stats.failed += 1

            if stats.bytes_fetched > budget.max_bytes:
                stats.budget_exhausted = True
                failure = ShardFailure(
                    code="BUDGET_EXCEEDED",
                    message="prefetch byte budget exceeded",
                    physical_shard_id=pid,
                    details={
                        "max_bytes": budget.max_bytes,
                        "bytes_fetched": stats.bytes_fetched,
                    },
                )
                # Soft: record only under PARTIAL; FAIL_FAST raises.
                if self.failure_policy == FailurePolicy.FAIL_FAST:
                    self._handle_failure(failure, accum=accum)
                else:
                    accum.append(failure)
                break

        stats.elapsed_seconds = time.monotonic() - started
        return stats

    def traverse_paths(
        self,
        seed_id: str,
        *,
        max_depth: int = 2,
        max_fan_out: int = 32,
        relationship_types: Optional[Sequence[str]] = None,
    ) -> QueryResult:
        """Bounded BFS over local + cross-shard edges."""
        if max_depth < 0:
            raise ShardedQueryError("INVALID_REQUEST", "max_depth must be >= 0")

        failures: list[ShardFailure] = []
        entities: dict[str, EntityRecord] = {}
        all_edges: list[NeighborEdge] = []
        seen_nodes = {seed_id}
        frontier = [seed_id]

        seed = self.get_entities([seed_id])
        entities.update(seed.entities)
        failures.extend(seed.failures)

        for depth in range(max_depth):
            next_frontier: list[str] = []
            for nid in frontier:
                res = self.neighbors(
                    nid,
                    direction="both",
                    relationship_types=relationship_types,
                    include_cross_shard=True,
                    prefetch=True,
                )
                failures.extend(res.failures)
                entities.update(res.entities)
                # Cap fan-out per node.
                for edge in res.edges[: max(0, max_fan_out)]:
                    all_edges.append(edge)
                    other = edge.other_id(nid)
                    if other not in seen_nodes:
                        seen_nodes.add(other)
                        next_frontier.append(other)
            frontier = next_frontier
            if not frontier:
                break
            _ = depth

        return QueryResult(
            ok=True,
            partial=bool(failures),
            entities=entities,
            edges=all_edges,
            failures=failures,
            stats={
                "seed": seed_id,
                "nodes_visited": len(seen_nodes),
                "edge_count": len(all_edges),
                "max_depth": max_depth,
                "bytes_fetched": self._bytes_fetched,
                "blocks_fetched": self._blocks_fetched,
            },
        )

    def list_cross_shard_adjacency(self) -> tuple[CrossShardAdjacencyDescriptor, ...]:
        return self.manifest.cross_shard_adjacency


def open_sharded_query(
    published: Any = None,
    *,
    manifest: Optional[ShardedGraphManifest] = None,
    store: Optional[BlockStore] = None,
    **kwargs: Any,
) -> ShardedQueryRuntime:
    """Open a runtime from a :class:`PublishedShardedGraphV2` or explicit parts."""
    if published is not None:
        manifest = getattr(published, "manifest", manifest)
        store = getattr(published, "store", store)
    if manifest is None or store is None:
        raise ValueError("manifest and store are required")
    return ShardedQueryRuntime(manifest, store, **kwargs)


__all__ = [
    "FailurePolicy",
    "ShardFailure",
    "ShardedQueryError",
    "PrefetchBudget",
    "PrefetchStats",
    "NeighborEdge",
    "QueryResult",
    "ShardedQueryRuntime",
    "open_sharded_query",
]
