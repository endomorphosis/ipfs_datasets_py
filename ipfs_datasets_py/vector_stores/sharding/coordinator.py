"""
Shard Coordinator for Distributed Vector Storage.

Implements consistent hashing-based sharding for horizontal scaling.
"""

import hashlib
import logging
import bisect
from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class ShardMetadata:
    """Metadata for a shard."""
    shard_id: str
    node_id: str
    vector_count: int = 0
    size_bytes: int = 0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    root_cid: Optional[str] = None
    healthy: bool = True
    replicas: List[str] = field(default_factory=list)


class ConsistentHashRing:
    """Consistent hashing ring with virtual nodes."""
    
    def __init__(self, virtual_nodes: int = 150):
        self.virtual_nodes = virtual_nodes
        self.ring: List[int] = []
        self.ring_map: Dict[int, str] = {}
        self.nodes: Set[str] = set()
    
    def _hash(self, key: str) -> int:
        return int(hashlib.md5(key.encode()).hexdigest(), 16)
    
    def add_node(self, node_id: str) -> None:
        if node_id in self.nodes:
            return
        self.nodes.add(node_id)
        for i in range(self.virtual_nodes):
            virtual_key = f"{node_id}:{i}"
            hash_value = self._hash(virtual_key)
            self.ring_map[hash_value] = node_id
            bisect.insort(self.ring, hash_value)
    
    def remove_node(self, node_id: str) -> None:
        if node_id not in self.nodes:
            return
        self.nodes.remove(node_id)
        for i in range(self.virtual_nodes):
            virtual_key = f"{node_id}:{i}"
            hash_value = self._hash(virtual_key)
            if hash_value in self.ring_map:
                del self.ring_map[hash_value]
                self.ring.remove(hash_value)
    
    def get_node(self, key: str) -> Optional[str]:
        if not self.ring:
            return None
        hash_value = self._hash(key)
        idx = bisect.bisect_right(self.ring, hash_value)
        if idx == len(self.ring):
            idx = 0
        return self.ring_map[self.ring[idx]]
    
    def get_nodes(self, key: str, count: int = 1) -> List[str]:
        if not self.ring or count < 1:
            return []
        hash_value = self._hash(key)
        idx = bisect.bisect_right(self.ring, hash_value)
        nodes = []
        seen = set()
        for i in range(len(self.ring)):
            pos = (idx + i) % len(self.ring)
            node_id = self.ring_map[self.ring[pos]]
            if node_id not in seen:
                nodes.append(node_id)
                seen.add(node_id)
            if len(nodes) >= count:
                break
        return nodes


class ShardRegistry:
    """Registry for tracking shards."""
    
    def __init__(self):
        self.shards: Dict[str, ShardMetadata] = {}
        self.vector_to_shard: Dict[str, str] = {}
        self.node_to_shards: Dict[str, Set[str]] = {}
    
    def register_shard(self, shard: ShardMetadata) -> None:
        self.shards[shard.shard_id] = shard
        if shard.node_id not in self.node_to_shards:
            self.node_to_shards[shard.node_id] = set()
        self.node_to_shards[shard.node_id].add(shard.shard_id)
    
    def assign_vector(self, vector_id: str, shard_id: str) -> None:
        self.vector_to_shard[vector_id] = shard_id
        if shard_id in self.shards:
            self.shards[shard_id].vector_count += 1
    
    def find_shard(self, vector_id: str) -> Optional[str]:
        return self.vector_to_shard.get(vector_id)
    
    def get_shards_for_node(self, node_id: str) -> List[ShardMetadata]:
        if node_id not in self.node_to_shards:
            return []
        return [
            self.shards[shard_id]
            for shard_id in self.node_to_shards[node_id]
            if shard_id in self.shards
        ]
    
    def get_all_shards(self) -> List[ShardMetadata]:
        return list(self.shards.values())


class ShardCoordinator:
    """Coordinates vector distribution across shards."""
    
    def __init__(self, replication_factor: int = 3, shard_size: int = 100000):
        self.replication_factor = replication_factor
        self.shard_size = shard_size
        self.hash_ring = ConsistentHashRing()
        self.registry = ShardRegistry()
    
    def add_node(self, node_id: str) -> None:
        self.hash_ring.add_node(node_id)
    
    async def assign_shards(self, vector_id: str) -> List[str]:
        nodes = self.hash_ring.get_nodes(vector_id, self.replication_factor)
        if not nodes:
            raise ValueError("No nodes available")
        shard_ids = []
        for node_id in nodes:
            shard_id = f"{node_id}:shard_0"
            if shard_id not in self.registry.shards:
                shard = ShardMetadata(shard_id=shard_id, node_id=node_id)
                self.registry.register_shard(shard)
            self.registry.assign_vector(vector_id, shard_id)
            shard_ids.append(shard_id)
        return shard_ids
    
    async def find_shard(self, vector_id: str) -> Optional[str]:
        return self.registry.find_shard(vector_id)
    
    async def get_all_shards(self) -> List[ShardMetadata]:
        return self.registry.get_all_shards()
