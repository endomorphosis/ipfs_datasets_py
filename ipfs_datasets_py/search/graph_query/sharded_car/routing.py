from __future__ import annotations

import hashlib


def stable_shard_index(entity_id: str, *, num_shards: int) -> int:
    """Deterministic sharding: sha256(entity_id) mod N."""

    if num_shards <= 0:
        raise ValueError("num_shards must be > 0")
    digest = hashlib.sha256(entity_id.encode("utf-8", errors="strict")).digest()
    value = int.from_bytes(digest[:8], "big", signed=False)
    return value % num_shards
