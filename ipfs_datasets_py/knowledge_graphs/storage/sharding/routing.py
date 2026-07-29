"""v2 deterministic routing and rebalance analysis (KGP-014).

Routing primitives live on :mod:`manifest` (rendezvous, virtual shards,
hash-modulo). This module provides the operational router used by the publisher
and query runtime, plus helpers that quantify entity movement when the physical
shard count changes while the virtual shard count stays fixed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence

from ipfs_datasets_py.knowledge_graphs.storage.sharding.manifest import (
    ROUTING_HASH_MODULO,
    ROUTING_RENDEZVOUS_HRW,
    RendezvousRoutingDescriptor,
    ShardedGraphManifest,
    build_virtual_to_physical_table,
    normalize_routing_key,
    physical_shard_for_virtual,
    stable_shard_index,
    virtual_shard_id_for_index,
    virtual_shard_index,
)


@dataclass(frozen=True, slots=True)
class RouteAssignment:
    """Full route for one normalized entity id."""

    entity_id: str
    routing_key_hex: str
    virtual_index: int
    virtual_shard_id: str
    physical_shard_id: str


@dataclass(frozen=True, slots=True)
class RebalanceReport:
    """How many entities move when physical shard membership changes."""

    entity_count: int
    moved_count: int
    stayed_count: int
    movement_ratio: float
    from_physical_count: int
    to_physical_count: int
    virtual_shard_count: int
    moved_entity_ids: tuple[str, ...]

    @property
    def limited_movement(self) -> bool:
        """True when fewer than half the entities move (virtual-stable rebalance)."""
        if self.entity_count == 0:
            return True
        return self.movement_ratio < 0.5


class ShardRouter:
    """Deterministic entity → virtual → physical router.

    Prefer constructing from a :class:`ShardedGraphManifest` so published
    virtual tables are honored exactly. When built from a routing descriptor +
    physical ids only, sparse/virtual-fold mapping matches
    :meth:`ShardedGraphManifest.route_entity`.
    """

    def __init__(
        self,
        *,
        routing: RendezvousRoutingDescriptor,
        physical_shard_ids: Sequence[str],
        virtual_to_physical: Optional[Mapping[int, str]] = None,
    ) -> None:
        if not physical_shard_ids:
            raise ValueError("physical_shard_ids must be non-empty")
        self.routing = routing
        self.physical_shard_ids = tuple(sorted(physical_shard_ids))
        self._virtual_to_physical: dict[int, str] = dict(virtual_to_physical or {})

    @classmethod
    def from_manifest(cls, manifest: ShardedGraphManifest) -> "ShardRouter":
        vmap = {vs.index: vs.physical_shard_id for vs in manifest.virtual_shards}
        return cls(
            routing=manifest.routing,
            physical_shard_ids=manifest.physical_shard_ids(),
            virtual_to_physical=vmap,
        )

    def normalize_id(self, entity_id: str) -> bytes:
        return normalize_routing_key(
            entity_id,
            normalization=self.routing.key_normalization,
        )

    def virtual_index_for(self, entity_id: str) -> int:
        return virtual_shard_index(
            entity_id,
            virtual_shard_count=self.routing.virtual_shard_count,
            normalization=self.routing.key_normalization,
            seed=self.routing.seed,
        )

    def physical_for_virtual(self, virtual_index: int) -> str:
        if virtual_index in self._virtual_to_physical:
            return self._virtual_to_physical[virtual_index]
        return physical_shard_for_virtual(
            virtual_index,
            self.physical_shard_ids,
            seed=self.routing.seed,
            algorithm=self.routing.algorithm,
        )

    def route(self, entity_id: str) -> str:
        """Return the physical_shard_id that owns ``entity_id``."""
        # Classic v1 hash-modulo when virtual count equals physical count.
        if (
            self.routing.algorithm == ROUTING_HASH_MODULO
            and self.routing.virtual_shard_count == len(self.physical_shard_ids)
            and not self._virtual_to_physical
        ):
            idx = stable_shard_index(entity_id, num_shards=len(self.physical_shard_ids))
            return self.physical_shard_ids[idx]

        v_idx = self.virtual_index_for(entity_id)
        return self.physical_for_virtual(v_idx)

    def assign(self, entity_id: str) -> RouteAssignment:
        key = self.normalize_id(entity_id)
        v_idx = self.virtual_index_for(entity_id)
        return RouteAssignment(
            entity_id=entity_id,
            routing_key_hex=key.hex(),
            virtual_index=v_idx,
            virtual_shard_id=virtual_shard_id_for_index(v_idx),
            physical_shard_id=self.physical_for_virtual(v_idx),
        )

    def route_many(self, entity_ids: Iterable[str]) -> dict[str, str]:
        return {eid: self.route(eid) for eid in entity_ids}


def measure_rebalance_movement(
    entity_ids: Sequence[str],
    *,
    routing: RendezvousRoutingDescriptor,
    from_physical_ids: Sequence[str],
    to_physical_ids: Sequence[str],
    materialize_virtual_table: bool = True,
) -> RebalanceReport:
    """Compare physical placement before/after a physical-shard count change.

    Virtual shard count and seed stay fixed; only the virtual→physical map is
    rebuilt. With rendezvous-HRW, expected movement approaches
    ``|N_new - N_old| / N_new`` (limited reshuffle), not a full reshuffle.
    """
    from_ids = tuple(sorted(from_physical_ids))
    to_ids = tuple(sorted(to_physical_ids))
    if not from_ids or not to_ids:
        raise ValueError("physical id lists must be non-empty")

    if materialize_virtual_table:
        from_table = build_virtual_to_physical_table(
            virtual_shard_count=routing.virtual_shard_count,
            physical_shard_ids=from_ids,
            algorithm=routing.algorithm,
            seed=routing.seed,
        )
        to_table = build_virtual_to_physical_table(
            virtual_shard_count=routing.virtual_shard_count,
            physical_shard_ids=to_ids,
            algorithm=routing.algorithm,
            seed=routing.seed,
        )
        from_router = ShardRouter(
            routing=routing,
            physical_shard_ids=from_ids,
            virtual_to_physical={r.index: r.physical_shard_id for r in from_table},
        )
        to_router = ShardRouter(
            routing=routing,
            physical_shard_ids=to_ids,
            virtual_to_physical={r.index: r.physical_shard_id for r in to_table},
        )
    else:
        from_router = ShardRouter(routing=routing, physical_shard_ids=from_ids)
        to_router = ShardRouter(routing=routing, physical_shard_ids=to_ids)

    moved: list[str] = []
    stayed = 0
    for eid in entity_ids:
        a = from_router.route(eid)
        b = to_router.route(eid)
        # Movement is about ownership change; physical id strings differ by design
        # when the set changes, so compare virtual index stability via... actually
        # when physical sets differ, all entity physical ids may change labels.
        # We measure whether the *relative* placement among shared ids stays:
        # an entity "stays" if it still maps to a physical shard that existed in
        # the old set under the same virtual→old-physical mapping identity when
        # the old physical is still present in the new set.
        if a == b:
            stayed += 1
        else:
            # For pure renames (same set re-labeled) a!=b always; for count
            # changes, compare virtual stability: same virtual index always.
            # Movement = virtual index reassigned to a different physical that
            # is not a mere rename. Since we rebuild with sorted ids, adding a
            # shard keeps most virtuals on the same physical id string when that
            # id remains.
            moved.append(eid)

    n = len(entity_ids)
    moved_count = len(moved)
    stayed_count = n - moved_count
    ratio = (moved_count / n) if n else 0.0
    return RebalanceReport(
        entity_count=n,
        moved_count=moved_count,
        stayed_count=stayed_count,
        movement_ratio=ratio,
        from_physical_count=len(from_ids),
        to_physical_count=len(to_ids),
        virtual_shard_count=routing.virtual_shard_count,
        moved_entity_ids=tuple(moved),
    )


def expected_max_movement_ratio(*, from_count: int, to_count: int) -> float:
    """Upper bound heuristic for HRW rebalance movement ratio.

    When growing from N to M (M > N), roughly ``(M - N) / M`` of keys move to
    new nodes. When shrinking, roughly ``(N - M) / N`` leave removed nodes.
    """
    if from_count <= 0 or to_count <= 0:
        raise ValueError("counts must be positive")
    if from_count == to_count:
        return 0.0
    if to_count > from_count:
        return (to_count - from_count) / float(to_count)
    return (from_count - to_count) / float(from_count)


__all__ = [
    "RouteAssignment",
    "RebalanceReport",
    "ShardRouter",
    "measure_rebalance_movement",
    "expected_max_movement_ratio",
    "ROUTING_HASH_MODULO",
    "ROUTING_RENDEZVOUS_HRW",
    "normalize_routing_key",
    "stable_shard_index",
    "virtual_shard_index",
    "physical_shard_for_virtual",
    "build_virtual_to_physical_table",
]
