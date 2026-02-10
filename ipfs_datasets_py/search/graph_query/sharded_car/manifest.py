from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .bloom import BloomFilter


@dataclass(frozen=True)
class ShardInfo:
    shard_id: str
    car_cid: str
    approx_bytes: int

    # Optional lightweight index blocks (stored separately on IPFS)
    # - headers_cid: JSON mapping entity_id -> header fields
    # - type_index_cid: JSON mapping entity_type -> list[entity_id]
    headers_cid: str | None = None
    type_index_cid: str | None = None

    # Optional neighbors index (stored separately on IPFS)
    # - neighbors_index_cid: JSON mapping entity_id -> CID of that entity's adjacency JSON
    neighbors_index_cid: str | None = None

    # Routing metadata (optional in v1 scaffolding)
    entity_type_bloom: dict[str, Any] | None = None
    relationship_type_bloom: dict[str, Any] | None = None


@dataclass
class GraphShardManifest:
    """Manifest describing a sharded graph stored as CARs on IPFS."""

    version: str = "v1"
    shard_size_limit_bytes: int = 100 * 1024 * 1024
    target_shard_bytes: int = 85 * 1024 * 1024

    # The graph "root" CID of the manifest itself is stored externally.
    shards: list[ShardInfo] = field(default_factory=list)

    # Optional top-level routing blooms (may be redundant with per-shard blooms)
    entity_type_bloom: dict[str, Any] | None = None
    relationship_type_bloom: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "shard_size_limit_bytes": self.shard_size_limit_bytes,
            "target_shard_bytes": self.target_shard_bytes,
            "shards": [
                {
                    "shard_id": s.shard_id,
                    "car_cid": s.car_cid,
                    "approx_bytes": s.approx_bytes,
                    "headers_cid": s.headers_cid,
                    "type_index_cid": s.type_index_cid,
                    "neighbors_index_cid": s.neighbors_index_cid,
                    "entity_type_bloom": s.entity_type_bloom,
                    "relationship_type_bloom": s.relationship_type_bloom,
                }
                for s in self.shards
            ],
            "entity_type_bloom": self.entity_type_bloom,
            "relationship_type_bloom": self.relationship_type_bloom,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "GraphShardManifest":
        shards = [
            ShardInfo(
                shard_id=s["shard_id"],
                car_cid=s["car_cid"],
                approx_bytes=int(s.get("approx_bytes", 0)),
                headers_cid=s.get("headers_cid"),
                type_index_cid=s.get("type_index_cid"),
                neighbors_index_cid=s.get("neighbors_index_cid"),
                entity_type_bloom=s.get("entity_type_bloom"),
                relationship_type_bloom=s.get("relationship_type_bloom"),
            )
            for s in d.get("shards", [])
        ]
        return cls(
            version=d.get("version", "v1"),
            shard_size_limit_bytes=int(d.get("shard_size_limit_bytes", 100 * 1024 * 1024)),
            target_shard_bytes=int(d.get("target_shard_bytes", 85 * 1024 * 1024)),
            shards=shards,
            entity_type_bloom=d.get("entity_type_bloom"),
            relationship_type_bloom=d.get("relationship_type_bloom"),
        )


def build_type_bloom(types: list[str], *, num_bits: int = 8192, num_hashes: int = 7) -> dict[str, Any]:
    bf = BloomFilter.create(num_bits=num_bits, num_hashes=num_hashes)
    for t in types:
        bf.add(t)
    return bf.to_dict()
