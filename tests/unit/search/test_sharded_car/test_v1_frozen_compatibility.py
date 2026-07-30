"""KGP-047: frozen v1 manifest/CAR fixtures preserve identity through the reader.

Acceptance covered here:
* graph identity (manifest version, shard CIDs, root CIDs, frozen digests)
* shard membership (routing + entity placement)
* node/edge content (headers index + CAR payload)
* explicit errors for empty/missing CAR data at the supported reader surface

Fixtures use binary ``.car`` payloads under the task artifact envelope
(``allow_binary: true``) with SHA-256 digests pinned in expected_identity.json.
"""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any, Dict

import pytest

from ipfs_datasets_py.knowledge_graphs.storage.sharding.manifest import (
    SHARD_MANIFEST_V1,
    load_sharded_graph_manifest,
)
from ipfs_datasets_py.search.graph_query.backends.sharded_car import (
    CARBytesShardLoader,
    InMemoryCarFetcher,
    ShardedCARBackend,
)
from ipfs_datasets_py.search.graph_query.sharded_car.manifest import GraphShardManifest
from ipfs_datasets_py.search.graph_query.sharded_car.routing import stable_shard_index

from .conftest import MappingBytesFetcher


def test_frozen_fixture_files_present(v1_fixture_dir: Path) -> None:
    required = [
        "manifest.json",
        "expected_identity.json",
        "index_blobs.json",
        # Frozen binary CAR payloads (KGP-047 envelope allow_binary=true path set).
        "S0.car",
        "S1.car",
        "S2.car",
        "indexes/S0_headers.json",
        "indexes/S0_type_index.json",
        "indexes/S1_headers.json",
        "indexes/S1_type_index.json",
        "indexes/S2_headers.json",
        "indexes/S2_type_index.json",
    ]
    for rel in required:
        path = v1_fixture_dir / rel
        assert path.is_file(), f"missing frozen fixture: {rel}"
        assert path.stat().st_size > 0


def test_frozen_car_digests_match_identity(
    v1_car_bytes: Dict[str, bytes], v1_expected_identity: Dict[str, Any]
) -> None:
    for shard_id, data in v1_car_bytes.items():
        digest = hashlib.sha256(data).hexdigest()
        assert digest == v1_expected_identity["car_sha256"][shard_id]
        assert len(data) > 0


def test_frozen_manifest_is_v1(v1_manifest_dict: Dict[str, Any]) -> None:
    assert v1_manifest_dict["version"] == "v1"
    shards = v1_manifest_dict["shards"]
    assert len(shards) == 3
    for shard in shards:
        assert shard["shard_id"]
        assert shard["car_cid"].startswith("baf")
        assert shard["headers_cid"]
        assert shard["type_index_cid"]
        bloom = shard["entity_type_bloom"]
        assert isinstance(bloom, dict)
        assert bloom["num_bits"] > 0


def test_graph_shard_manifest_preserves_identity(
    v1_manifest_dict: Dict[str, Any],
    v1_graph_manifest: GraphShardManifest,
    v1_expected_identity: Dict[str, Any],
    v1_car_bytes: Dict[str, bytes],
) -> None:
    assert v1_graph_manifest.version == "v1"
    assert (
        v1_graph_manifest.shard_size_limit_bytes
        == v1_expected_identity["shard_size_limit_bytes"]
    )
    assert (
        v1_graph_manifest.target_shard_bytes
        == v1_expected_identity["target_shard_bytes"]
    )
    assert [s.shard_id for s in v1_graph_manifest.shards] == v1_expected_identity[
        "shard_ids_sorted"
    ] or set(s.shard_id for s in v1_graph_manifest.shards) == set(
        v1_expected_identity["shard_ids_sorted"]
    )
    by_id = {s.shard_id: s for s in v1_graph_manifest.shards}
    for shard_id, car_cid in v1_expected_identity["car_cids"].items():
        assert by_id[shard_id].car_cid == car_cid
        assert by_id[shard_id].approx_bytes == len(v1_car_bytes[shard_id])
        assert (
            by_id[shard_id].headers_cid
            == v1_expected_identity["index_cids"][shard_id]["headers_cid"]
        )
        assert (
            by_id[shard_id].type_index_cid
            == v1_expected_identity["index_cids"][shard_id]["type_index_cid"]
        )


def test_manifest_round_trip_preserves_identity(
    v1_manifest_dict: Dict[str, Any], v1_graph_manifest: GraphShardManifest
) -> None:
    again = GraphShardManifest.from_dict(v1_graph_manifest.to_dict())
    assert again.version == v1_graph_manifest.version == "v1"
    assert [s.shard_id for s in again.shards] == [
        s.shard_id for s in v1_graph_manifest.shards
    ]
    assert [s.car_cid for s in again.shards] == [
        s.car_cid for s in v1_graph_manifest.shards
    ]
    restored = GraphShardManifest.from_dict(copy.deepcopy(v1_manifest_dict))
    assert restored.to_dict()["version"] == "v1"
    assert len(restored.shards) == len(v1_manifest_dict["shards"])


def test_v2_compatibility_reader_preserves_graph_identity(
    v1_manifest_dict: Dict[str, Any], v1_expected_identity: Dict[str, Any]
) -> None:
    """ShardedGraphManifest.from_v1_dict is the supported cross-version reader."""
    loaded = load_sharded_graph_manifest(v1_manifest_dict)
    assert loaded.version == SHARD_MANIFEST_V1 == "v1"
    assert loaded.schema_version == "1"
    assert loaded.index_version == "1"
    assert loaded.routing.algorithm == "hash-modulo"
    assert set(loaded.physical_shard_ids()) == set(
        v1_expected_identity["shard_ids_sorted"]
    )
    assert loaded.provenance.source == "search.graph_query.sharded_car"
    assert loaded.provenance.extra.get("imported_version") == "v1"

    for phys in loaded.physical_shards:
        assert phys.car_cid == v1_expected_identity["car_cids"][phys.physical_shard_id]
        assert phys.codec == "car"

    projected = loaded.to_v1_dict()
    assert projected["version"] == "v1"
    projected_cids = {s["shard_id"]: s["car_cid"] for s in projected["shards"]}
    assert projected_cids == v1_expected_identity["car_cids"]


def test_shard_membership_matches_stable_routing(
    v1_expected_identity: Dict[str, Any],
) -> None:
    num_shards = v1_expected_identity["num_shards"]
    shard_ids = v1_expected_identity["shard_ids_sorted"]
    membership = v1_expected_identity["membership"]
    for eid, meta in v1_expected_identity["entities"].items():
        idx = stable_shard_index(eid, num_shards=num_shards)
        assert shard_ids[idx] == meta["shard_id"]
        assert membership[eid] == meta["shard_id"]


def test_backend_routes_to_membership_shards(
    v1_backend: ShardedCARBackend, v1_expected_identity: Dict[str, Any]
) -> None:
    for eid, meta in v1_expected_identity["entities"].items():
        assert v1_backend._route_entity(eid) == meta["shard_id"]
        assert v1_backend.seed_exists(eid) is True
    assert v1_backend.seed_exists("definitely-missing-entity") is False


def test_car_loader_places_entities_on_declared_shards(
    v1_backend: ShardedCARBackend, v1_expected_identity: Dict[str, Any]
) -> None:
    membership = v1_expected_identity["membership"]
    by_shard: Dict[str, set[str]] = {}
    for eid, sid in membership.items():
        by_shard.setdefault(sid, set()).add(eid)

    seen: set[str] = set()
    for sid, members in sorted(by_shard.items()):
        kg = v1_backend._get_kg(sid)
        loaded = set(kg.entities.keys())
        assert loaded == members
        assert loaded.isdisjoint(seen)
        seen |= loaded
    assert seen == set(membership)


def test_headers_index_preserves_node_content(
    v1_backend: ShardedCARBackend, v1_expected_identity: Dict[str, Any]
) -> None:
    entity_ids = sorted(v1_expected_identity["entities"])
    headers = v1_backend.get_entity_headers(entity_ids)
    assert set(headers) == set(entity_ids)
    for eid, header in headers.items():
        expected = v1_expected_identity["entities"][eid]
        assert header.id == eid
        assert header.type == expected["type"]
        assert header.name == expected["name"]
        assert header.properties == expected["properties"]


def test_car_payload_preserves_node_content(
    v1_backend: ShardedCARBackend, v1_expected_identity: Dict[str, Any]
) -> None:
    for eid, expected in v1_expected_identity["entities"].items():
        shard_id = expected["shard_id"]
        kg = v1_backend._get_kg(shard_id)
        ent = kg.entities.get(eid)
        assert ent is not None, f"missing entity {eid} in shard {shard_id}"
        assert ent.type == expected["type"]
        assert ent.name == expected["name"]
        assert (dict(ent.properties) if ent.properties else None) == expected[
            "properties"
        ]


def test_car_payload_preserves_edge_content(
    v1_backend: ShardedCARBackend, v1_expected_identity: Dict[str, Any]
) -> None:
    for shard_id in v1_expected_identity["shard_ids_sorted"]:
        kg = v1_backend._get_kg(shard_id)
        expected_edges = v1_expected_identity["edges_by_shard"][shard_id]
        assert len(kg.relationships) == len(expected_edges)
        by_id = {str(r.id): r for r in kg.relationships.values()}
        for exp in expected_edges:
            rel = by_id.get(exp["relationship_id"])
            assert rel is not None, (
                f"edge mismatch on {shard_id}: missing {exp['relationship_id']}; "
                f"expected {exp}"
            )
            assert rel.type == exp["type"]
            assert str(rel.source_id) == exp["source_id"]
            assert str(rel.target_id) == exp["target_id"]
            props = dict(rel.properties) if rel.properties else None
            assert props == exp["properties"]


def test_scan_type_respects_membership_and_types(
    v1_backend: ShardedCARBackend, v1_expected_identity: Dict[str, Any]
) -> None:
    expected_ids = sorted(
        eid
        for eid, meta in v1_expected_identity["entities"].items()
        if meta["type"] == "Person"
    )
    page = v1_backend.scan_type("Person", limit=100)
    assert sorted(page.entity_ids) == expected_ids
    assert page.shards_touched > 0
    assert set(page.shards_touched_ids).issubset(
        set(v1_expected_identity["shard_ids_sorted"])
    )


def test_backend_refuses_empty_manifest(
    v1_manifest_dict: Dict[str, Any], v1_car_map: Dict[str, bytes]
) -> None:
    empty = copy.deepcopy(v1_manifest_dict)
    empty["shards"] = []
    with pytest.raises(ValueError, match="at least one shard"):
        ShardedCARBackend(
            GraphShardManifest.from_dict(empty),
            loader=CARBytesShardLoader(InMemoryCarFetcher(v1_car_map)),
        )


def test_missing_car_raises_explicit_error(
    v1_graph_manifest: GraphShardManifest, v1_index_blobs: Dict[str, bytes]
) -> None:
    backend = ShardedCARBackend(
        v1_graph_manifest,
        loader=CARBytesShardLoader(InMemoryCarFetcher({})),
        index_fetcher=MappingBytesFetcher(v1_index_blobs),
    )
    with pytest.raises(KeyError, match="No CAR bytes"):
        backend._get_kg("S0")


def test_fixture_identity_counts(v1_expected_identity: Dict[str, Any]) -> None:
    assert v1_expected_identity["fixture_id"] == "kgp-047-frozen-v1"
    assert v1_expected_identity["graph_name"] == "kgp-047-frozen-v1"
    assert v1_expected_identity["entity_count"] == len(v1_expected_identity["entities"])
    assert v1_expected_identity["edge_count"] == sum(
        len(edges) for edges in v1_expected_identity["edges_by_shard"].values()
    )
    assert v1_expected_identity["entity_count"] == len(
        v1_expected_identity["membership"]
    )
    packaging = v1_expected_identity.get("packaging") or {}
    assert packaging.get("car_encoding") == "binary"
    assert packaging.get("task_id") == "KGP-047"
    assert packaging.get("allow_binary") is True
