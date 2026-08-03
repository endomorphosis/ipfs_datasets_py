"""KGP-047: surface-level guarantees of the supported v1 sharded-CAR reader.

Covers stable routing parity, shard scope allowlists, and header stats over the
frozen v1 fixture graph.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict

import pytest

from ipfs_datasets_py.knowledge_graphs.storage.sharding.manifest import (
    load_sharded_graph_manifest,
)
from ipfs_datasets_py.search.graph_query.backends.sharded_car import ShardedCARBackend
from ipfs_datasets_py.search.graph_query.sharded_car.manifest import (
    GraphShardManifest,
    ShardInfo,
)
from ipfs_datasets_py.search.graph_query.sharded_car.routing import stable_shard_index


def test_hash_modulo_routing_is_sha256_stable() -> None:
    entity_id = "e07"
    digest = hashlib.sha256(entity_id.encode("utf-8")).digest()
    expected = int.from_bytes(digest[:8], "big", signed=False) % 3
    assert stable_shard_index(entity_id, num_shards=3) == expected


def test_v1_and_compatibility_reader_agree_on_routes(
    v1_manifest_dict: Dict[str, Any],
    v1_graph_manifest: GraphShardManifest,
    v1_expected_identity: Dict[str, Any],
) -> None:
    compat = load_sharded_graph_manifest(v1_manifest_dict)
    legacy_ids = sorted(s.shard_id for s in v1_graph_manifest.shards)
    for eid, meta in v1_expected_identity["entities"].items():
        legacy_route = legacy_ids[
            stable_shard_index(eid, num_shards=len(legacy_ids))
        ]
        assert legacy_route == meta["shard_id"]
        assert compat.route_entity(eid) == meta["shard_id"]


def test_shard_info_frozen_fields() -> None:
    info = ShardInfo(shard_id="S0", car_cid="bafkreiabc", approx_bytes=1)
    assert info.shard_id == "S0"
    assert info.headers_cid is None
    with pytest.raises(Exception):
        info.shard_id = "S1"  # type: ignore[misc]


def test_backend_scope_allowlist(
    v1_backend: ShardedCARBackend, v1_expected_identity: Dict[str, Any]
) -> None:
    s0_persons = sorted(
        eid
        for eid, meta in v1_expected_identity["entities"].items()
        if meta["type"] == "Person" and meta["shard_id"] == "S0"
    )
    page = v1_backend.scan_type("Person", scope=["S0"], limit=100)
    assert sorted(page.entity_ids) == s0_persons
    assert set(page.shards_touched_ids).issubset({"S0"})


def test_get_entity_headers_with_stats_counts_shards(
    v1_backend: ShardedCARBackend, v1_expected_identity: Dict[str, Any]
) -> None:
    eids = list(v1_expected_identity["entities"])
    headers, shards_touched = v1_backend.get_entity_headers_with_stats(eids)
    assert len(headers) == len(eids)
    assert shards_touched == v1_expected_identity["num_shards"]
