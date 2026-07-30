"""KGP-047: frozen v1 manifest/CAR fixtures preserve identity through the reader.

Acceptance covered here:
* graph identity (manifest version, shard CIDs, root CIDs, frozen digests)
* shard membership (routing + entity placement)
* node/edge content (headers index + CAR-decoded KG)
* v1 remains loadable via GraphShardManifest and the v2 compatibility reader
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


# ---------------------------------------------------------------------------
# Frozen fixture integrity
# ---------------------------------------------------------------------------


def test_frozen_fixture_files_present(v1_fixture_dir: Path) -> None:
    required = [
        "manifest.json",
        "expected_identity.json",
        "index_blobs.json",
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
    for sid, data in v1_car_bytes.items():
        assert hashlib.sha256(data).hexdigest() == v1_expected_identity["car_sha256"][sid]
        assert len(data) > 0


def test_frozen_manifest_is_v1(v1_manifest_dict: Dict[str, Any]) -> None:
    assert v1_manifest_dict["version"] == "v1"
    assert len(v1_manifest_dict["shards"]) == 3
    for shard in v1_manifest_dict["shards"]:
        assert shard["shard_id"] in {"S0", "S1", "S2"}
        assert shard["car_cid"].startswith("baf")
        assert shard["headers_cid"].startswith("baf")
        assert shard["type_index_cid"].startswith("baf")
        assert isinstance(shard["entity_type_bloom"], dict)
        assert shard["entity_type_bloom"]["num_bits"] > 0


# ---------------------------------------------------------------------------
# Graph identity
# ---------------------------------------------------------------------------


def test_graph_shard_manifest_preserves_identity(
    v1_manifest_dict: Dict[str, Any],
    v1_graph_manifest: GraphShardManifest,
    v1_expected_identity: Dict[str, Any],
    v1_car_bytes: Dict[str, bytes],
) -> None:
    assert v1_graph_manifest.version == "v1"
    assert v1_graph_manifest.shard_size_limit_bytes == v1_manifest_dict["shard_size_limit_bytes"]
    assert v1_graph_manifest.target_shard_bytes == v1_manifest_dict["target_shard_bytes"]

    by_id = {s.shard_id: s for s in v1_graph_manifest.shards}
    assert set(by_id) == set(v1_expected_identity["shard_ids_sorted"])
    for sid, car_cid in v1_expected_identity["car_cids"].items():
        assert by_id[sid].car_cid == car_cid
        assert by_id[sid].approx_bytes == len(v1_car_bytes[sid])
        idx = v1_expected_identity["index_cids"][sid]
        assert by_id[sid].headers_cid == idx["headers_cid"]
        assert by_id[sid].type_index_cid == idx["type_index_cid"]


def test_manifest_round_trip_preserves_identity(
    v1_manifest_dict: Dict[str, Any], v1_graph_manifest: GraphShardManifest
) -> None:
    again = GraphShardManifest.from_dict(v1_graph_manifest.to_dict())
    assert again.version == v1_graph_manifest.version
    assert [s.shard_id for s in again.shards] == [
        s.shard_id for s in v1_graph_manifest.shards
    ]
    assert [s.car_cid for s in again.shards] == [
        s.car_cid for s in v1_graph_manifest.shards
    ]
    # Canonical dict equality for the on-disk frozen shape.
    loaded = GraphShardManifest.from_dict(copy.deepcopy(v1_manifest_dict))
    assert loaded.to_dict()["version"] == "v1"
    assert {s["shard_id"] for s in loaded.to_dict()["shards"]} == {
        s["shard_id"] for s in v1_manifest_dict["shards"]
    }


def test_v2_compatibility_reader_preserves_graph_identity(
    v1_manifest_dict: Dict[str, Any], v1_expected_identity: Dict[str, Any]
) -> None:
    """ShardedGraphManifest.from_v1_dict is the supported cross-version reader."""
    loaded = load_sharded_graph_manifest(v1_manifest_dict)
    assert loaded.version == SHARD_MANIFEST_V1
    assert loaded.version == "v1"
    assert loaded.schema_version == "1"
    assert loaded.index_version == "1"
    assert loaded.routing.algorithm == "hash-modulo"
    assert set(loaded.physical_shard_ids()) == set(
        v1_expected_identity["shard_ids_sorted"]
    )
    assert loaded.provenance.source == "search.graph_query.sharded_car"
    assert loaded.provenance.extra.get("imported_version") == "v1"

    physical = loaded.physical_by_id()
    for sid, car_cid in v1_expected_identity["car_cids"].items():
        assert physical[sid].car_cid == car_cid
        assert physical[sid].codec == "car"
        assert physical[sid].schema_version == "1"

    # Projection back to v1 shape retains shard addressing.
    projected = loaded.to_v1_dict()
    assert projected["version"] == "v1"
    projected_cids = {s["shard_id"]: s["car_cid"] for s in projected["shards"]}
    assert projected_cids == v1_expected_identity["car_cids"]


# ---------------------------------------------------------------------------
# Shard membership
# ---------------------------------------------------------------------------


def test_shard_membership_matches_stable_routing(
    v1_expected_identity: Dict[str, Any],
) -> None:
    n = v1_expected_identity["num_shards"]
    ordered = v1_expected_identity["shard_ids_sorted"]
    for eid, meta in v1_expected_identity["entities"].items():
        idx = stable_shard_index(eid, num_shards=n)
        assert ordered[idx] == meta["shard_id"]
        assert eid in v1_expected_identity["membership"][meta["shard_id"]]


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
    for sid, members in v1_expected_identity["membership"].items():
        kg = v1_backend._get_kg(sid)
        assert sorted(kg.entities.keys()) == sorted(members)
        # No entity from another shard leaks into this CAR.
        foreign = {
            e
            for other, ids in v1_expected_identity["membership"].items()
            if other != sid
            for e in ids
        }
        assert foreign.isdisjoint(kg.entities.keys())


# ---------------------------------------------------------------------------
# Node / edge content
# ---------------------------------------------------------------------------


def test_headers_index_preserves_node_content(
    v1_backend: ShardedCARBackend, v1_expected_identity: Dict[str, Any]
) -> None:
    entity_ids = sorted(v1_expected_identity["entities"])
    headers = v1_backend.get_entity_headers(entity_ids)
    assert set(headers) == set(entity_ids)
    for eid, header in headers.items():
        exp = v1_expected_identity["entities"][eid]
        assert header.id == eid
        assert header.type == exp["type"]
        assert header.name == exp["name"]
        assert header.cid == exp["cid"]
        assert header.properties == exp["properties"]


def test_car_payload_preserves_node_content(
    v1_backend: ShardedCARBackend, v1_expected_identity: Dict[str, Any]
) -> None:
    for eid, exp in v1_expected_identity["entities"].items():
        kg = v1_backend._get_kg(exp["shard_id"])
        ent = kg.get_entity(eid)
        assert ent is not None, f"missing entity {eid} in shard {exp['shard_id']}"
        assert ent.type == exp["type"]
        assert ent.name == exp["name"]
        assert dict(ent.properties or {}) == exp["properties"]
        assert ent.cid == exp["cid"]


def test_car_payload_preserves_edge_content(
    v1_backend: ShardedCARBackend, v1_expected_identity: Dict[str, Any]
) -> None:
    for sid in v1_expected_identity["shard_ids_sorted"]:
        kg = v1_backend._get_kg(sid)
        expected = [
            e for e in v1_expected_identity["edges"].values() if e["shard_id"] == sid
        ]
        found = {
            (r.type, r.source_id, r.target_id, tuple(sorted((r.properties or {}).items())))
            for r in kg.relationships.values()
        }
        want = {
            (
                e["type"],
                e["source_id"],
                e["target_id"],
                tuple(sorted(e["properties"].items())),
            )
            for e in expected
        }
        assert found == want, f"edge mismatch on {sid}: {found ^ want}"
        assert len(kg.relationships) == len(expected)


def test_scan_type_respects_membership_and_types(
    v1_backend: ShardedCARBackend, v1_expected_identity: Dict[str, Any]
) -> None:
    for entity_type in ("Person", "Org"):
        expected_ids = sorted(
            eid
            for eid, meta in v1_expected_identity["entities"].items()
            if meta["type"] == entity_type
        )
        page = v1_backend.scan_type(entity_type, limit=100)
        assert sorted(page.entity_ids) == expected_ids
        assert page.shards_touched >= 1
        assert set(page.shards_touched_ids) <= set(
            v1_expected_identity["shard_ids_sorted"]
        )


def test_backend_refuses_empty_manifest(
    v1_manifest_dict: Dict[str, Any],
    v1_car_map: Dict[str, bytes],
) -> None:
    empty = GraphShardManifest.from_dict(
        {**v1_manifest_dict, "shards": []}
    )
    with pytest.raises(ValueError, match="at least one shard"):
        ShardedCARBackend(
            empty,
            loader=CARBytesShardLoader(fetcher=InMemoryCarFetcher(cars=v1_car_map)),
        )


def test_missing_car_raises_explicit_error(
    v1_graph_manifest: GraphShardManifest,
    v1_index_blobs: Dict[str, bytes],
) -> None:
    from tests.unit.search.test_sharded_car.conftest import MappingBytesFetcher

    backend = ShardedCARBackend(
        v1_graph_manifest,
        loader=CARBytesShardLoader(fetcher=InMemoryCarFetcher(cars={})),
        index_fetcher=MappingBytesFetcher(v1_index_blobs),
    )
    # Headers index still works without CARs.
    any_id = next(iter(v1_graph_manifest.shards)).shard_id
    # Force CAR load for a known entity route.
    # Pick entity from identity via first shard members is hard; use scan fallback
    # by clearing type index path: call _get_kg directly.
    with pytest.raises(KeyError, match="No CAR bytes"):
        backend._get_kg(any_id)


def test_fixture_identity_counts(v1_expected_identity: Dict[str, Any]) -> None:
    assert v1_expected_identity["fixture_id"] == "kgp-047-frozen-v1"
    assert v1_expected_identity["graph_name"] == "kgp-047-frozen-v1"
    assert v1_expected_identity["entity_count"] == 12
    assert v1_expected_identity["edge_count"] == 13
    assert sum(len(v) for v in v1_expected_identity["membership"].values()) == 12
