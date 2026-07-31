"""Sharded graph storage: v2 manifests, routing, publish, and cross-shard query.

KGP-013: :mod:`manifest` — bounded virtual/physical descriptors, rendezvous,
cross-shard adjacency schema.

KGP-014: :mod:`routing`, :mod:`publish`, :mod:`blocks`, :mod:`runtime` —
deterministic routing, CAR + index-bucket publishing, verified fetch,
prefetch budgets, and typed partial/failure policy for missing/corrupt/slow
shards.
"""

from __future__ import annotations

from ipfs_datasets_py.knowledge_graphs.storage.sharding.blocks import (
    BlockStore,
    FileBlockStore,
    MemoryBlockStore,
    ShardBlockError,
    verify_block,
)
from ipfs_datasets_py.knowledge_graphs.storage.sharding.manifest import (
    ROUTING_HASH_MODULO,
    ROUTING_RENDEZVOUS_HRW,
    SHARD_MANIFEST_V1,
    SHARD_MANIFEST_V2,
    BloomFilterDescriptor,
    CrossShardAdjacencyDescriptor,
    IndexBucketDescriptor,
    PhysicalShardDescriptor,
    RendezvousRoutingDescriptor,
    ShardStatistics,
    ShardedGraphManifest,
    VirtualShardDescriptor,
    build_sharded_graph_manifest,
    build_virtual_to_physical_table,
    load_sharded_graph_manifest,
    stable_shard_index,
    virtual_shard_index,
)
from ipfs_datasets_py.knowledge_graphs.storage.sharding.models import (
    EntityRecord,
    GraphFragment,
    RelationshipRecord,
)
from ipfs_datasets_py.knowledge_graphs.storage.sharding.publish import (
    PublishedShardedGraphV2,
    decode_car_payload,
    publish_entities_relationships_v2,
    publish_sharded_graph_v2,
)
from ipfs_datasets_py.knowledge_graphs.storage.sharding.routing import (
    RebalanceReport,
    RouteAssignment,
    ShardRouter,
    expected_max_movement_ratio,
    measure_rebalance_movement,
)
from ipfs_datasets_py.knowledge_graphs.storage.sharding.runtime import (
    FailurePolicy,
    NeighborEdge,
    PrefetchBudget,
    PrefetchStats,
    QueryResult,
    ShardFailure,
    ShardedQueryError,
    ShardedQueryRuntime,
    open_sharded_query,
)

__all__ = [
    # Manifest (KGP-013)
    "SHARD_MANIFEST_V1",
    "SHARD_MANIFEST_V2",
    "ROUTING_HASH_MODULO",
    "ROUTING_RENDEZVOUS_HRW",
    "BloomFilterDescriptor",
    "CrossShardAdjacencyDescriptor",
    "IndexBucketDescriptor",
    "PhysicalShardDescriptor",
    "RendezvousRoutingDescriptor",
    "ShardStatistics",
    "ShardedGraphManifest",
    "VirtualShardDescriptor",
    "build_sharded_graph_manifest",
    "build_virtual_to_physical_table",
    "load_sharded_graph_manifest",
    "stable_shard_index",
    "virtual_shard_index",
    # Models / publish / routing / runtime (KGP-014)
    "EntityRecord",
    "GraphFragment",
    "RelationshipRecord",
    "PublishedShardedGraphV2",
    "publish_sharded_graph_v2",
    "publish_entities_relationships_v2",
    "decode_car_payload",
    "RouteAssignment",
    "RebalanceReport",
    "ShardRouter",
    "measure_rebalance_movement",
    "expected_max_movement_ratio",
    "BlockStore",
    "MemoryBlockStore",
    "FileBlockStore",
    "ShardBlockError",
    "verify_block",
    "FailurePolicy",
    "NeighborEdge",
    "PrefetchBudget",
    "PrefetchStats",
    "QueryResult",
    "ShardFailure",
    "ShardedQueryError",
    "ShardedQueryRuntime",
    "open_sharded_query",
]
