"""Sharded CAR graph storage (v1 scaffolding).

This package intentionally starts as data-model + routing primitives.
The actual CAR packing/unpacking + IPLD index pages are implemented next.
"""

from .manifest import GraphShardManifest, ShardInfo
from .ipfs import load_manifest_from_ipfs, sharded_car_backend_from_manifest_cid
from .publish import (
	PublishedShardedGraph,
	ShardingReport,
	publish_knowledge_graph_sharded_to_ipfs,
	publish_sharded_graph_to_ipfs,
	shard_knowledge_graph_deterministic,
	validate_deterministic_shard_routing,
)

__all__ = [
	"GraphShardManifest",
	"ShardInfo",
	"load_manifest_from_ipfs",
	"sharded_car_backend_from_manifest_cid",
	"PublishedShardedGraph",
	"publish_sharded_graph_to_ipfs",
	"publish_knowledge_graph_sharded_to_ipfs",
	"ShardingReport",
	"shard_knowledge_graph_deterministic",
	"validate_deterministic_shard_routing",
]
