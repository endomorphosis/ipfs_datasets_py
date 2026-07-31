"""KGP-013: Sharded graph manifest v2 unit tests.

Covers bounded virtual/physical shards, rendezvous routing, cross-shard
adjacency, schema/index versions, statistics, checksums/CIDs, bloom/index
buckets, codecs, provenance, deterministic golden serialization, and v1
read compatibility with search.graph_query.sharded_car GraphShardManifest.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from ipfs_datasets_py.knowledge_graphs.contracts.manifest import (
    ContentChecksum,
    ProvenanceDescriptor,
)
from ipfs_datasets_py.knowledge_graphs.storage.sharding.manifest import (
    ADJACENCY_DIRECTIONS,
    DEFAULT_SHARD_SIZE_LIMIT_BYTES,
    DEFAULT_TARGET_SHARD_BYTES,
    INDEX_BUCKET_KINDS,
    ROUTING_HASH_MODULO,
    ROUTING_RENDEZVOUS_HRW,
    SHARD_CODECS,
    SHARD_MANIFEST_V1,
    SHARD_MANIFEST_V2,
    BloomFilterDescriptor,
    CrossShardAdjacencyDescriptor,
    IndexBucketDescriptor,
    PhysicalShardDescriptor,
    RendezvousRoutingDescriptor,
    ShardManifestIntegrityError,
    ShardManifestValidationError,
    ShardStatistics,
    ShardedGraphManifest,
    VirtualShardDescriptor,
    build_sharded_graph_manifest,
    build_virtual_to_physical_table,
    canonical_json_bytes,
    hash_modulo_index,
    load_sharded_graph_manifest,
    physical_shard_for_virtual,
    rendezvous_pick,
    rendezvous_score,
    stable_shard_index,
    virtual_shard_id_for_index,
    virtual_shard_index,
)

# ---------------------------------------------------------------------------
# Golden fixture expectations (deterministic identity of _golden_manifest())
# ---------------------------------------------------------------------------

GOLDEN_CHECKSUM_HEX = "adb427f293d81ccee9cbc14a5025110a09a16a0e37a7131cf3a37cab4319441f"
GOLDEN_ROOT_CID = "bafkreifnwqt7fe6ydthots6bjjickeikbgqwudrxu4jrz45dpsvuggked4"

# v1 GraphShardManifest-compatible fixture (legacy shape).
V1_GOLDEN_SHARDS = (
    {
        "shard_id": "S0",
        "car_cid": "bafkreibst5xyhfsdclsu5vzpbi5wsiy2kda2qdf2k5xcxkrsa5yluzrptu",
        "approx_bytes": 10,
        "headers_cid": None,
        "type_index_cid": None,
        "neighbors_index_cid": None,
        "entity_type_bloom": {
            "num_bits": 64,
            "num_hashes": 3,
            "bits_hex": "0000000000000000",
        },
        "relationship_type_bloom": None,
    },
    {
        "shard_id": "S1",
        "car_cid": "bafkreifb7tsdmocu76eiz72lrz4hlvqayjuchecbfkgppgzx2cyrcsfq7i",
        "approx_bytes": 20,
        "headers_cid": None,
        "type_index_cid": None,
        "neighbors_index_cid": None,
        "entity_type_bloom": None,
        "relationship_type_bloom": None,
    },
)


def _ck(data: bytes) -> ContentChecksum:
    return ContentChecksum.of_bytes(data)


def _provenance(**overrides: Any) -> ProvenanceDescriptor:
    base: dict[str, Any] = dict(
        producer_id="producer:kg-shard-publisher",
        producer_version="2.0.0",
        source="unit-fixture",
        created_at="2026-07-29T12:00:00Z",
        repository_revision="commit:abc",
        extra={"pipeline": "kgp-013"},
    )
    base.update(overrides)
    return ProvenanceDescriptor(**base)


def _golden_manifest() -> ShardedGraphManifest:
    """Canonical v2 fixture used for golden checksum/serialization tests."""
    routing = RendezvousRoutingDescriptor(
        algorithm=ROUTING_RENDEZVOUS_HRW,
        hash_function="sha256",
        virtual_shard_count=4,
        seed="fixture-seed",
    )
    virtual = build_virtual_to_physical_table(
        virtual_shard_count=4,
        physical_shard_ids=("phys-a", "phys-b"),
        algorithm=ROUTING_RENDEZVOUS_HRW,
        seed="fixture-seed",
    )
    groups: dict[str, list[str]] = defaultdict(list)
    for v in virtual:
        groups[v.physical_shard_id].append(v.virtual_shard_id)

    phys: list[PhysicalShardDescriptor] = []
    for pid, vids in sorted(groups.items()):
        pck = _ck(f"car-{pid}".encode())
        bloom = BloomFilterDescriptor(num_bits=64, num_hashes=3, bits_hex="00" * 8)
        bucket = IndexBucketDescriptor(
            bucket_id=f"bkt-{pid}",
            kind="bloom_entity_type",
            codec="bloom-v1",
            checksum=_ck(b"bloom-" + pid.encode()),
            size_bytes=8,
            fields=("entity_type",),
            path=f"indexes/{pid}/entity_type.bloom",
            bloom=bloom,
            schema_version="1",
        )
        phys.append(
            PhysicalShardDescriptor(
                physical_shard_id=pid,
                codec="car",
                checksum=pck,
                size_bytes=100,
                statistics=ShardStatistics(
                    entity_count=5,
                    relationship_count=3,
                    approx_bytes=100,
                    virtual_shard_count=len(vids),
                    physical_shard_count=1,
                ),
                path=f"shards/{pid}.car",
                car_cid=pck.as_cid(),
                virtual_shard_ids=tuple(sorted(vids)),
                index_buckets=(bucket,),
                schema_version="1",
                index_version="1",
                entity_type_bloom=bloom,
            )
        )

    adj_ck = _ck(b"xadj")
    adj = CrossShardAdjacencyDescriptor(
        adjacency_id="adj-a-b",
        source_physical_shard_id="phys-a",
        target_physical_shard_id="phys-b",
        direction="outgoing",
        edge_count=2,
        codec="json",
        checksum=adj_ck,
        path="adjacency/a-b.json",
        cid=adj_ck.as_cid(),
    )
    return build_sharded_graph_manifest(
        routing=routing,
        schema_version="2",
        index_version="2",
        codec="dag-cbor",
        physical_shards=phys,
        virtual_shards=virtual,
        cross_shard_adjacency=(adj,),
        provenance=_provenance(),
    )


def _v1_dict() -> dict[str, Any]:
    return {
        "version": "v1",
        "shard_size_limit_bytes": DEFAULT_SHARD_SIZE_LIMIT_BYTES,
        "target_shard_bytes": DEFAULT_TARGET_SHARD_BYTES,
        "shards": [dict(s) for s in V1_GOLDEN_SHARDS],
        "entity_type_bloom": None,
        "relationship_type_bloom": None,
    }


# ---------------------------------------------------------------------------
# Constants / surface
# ---------------------------------------------------------------------------


def test_manifest_versions_and_closed_enumerations() -> None:
    assert SHARD_MANIFEST_V1 == "v1"
    assert SHARD_MANIFEST_V2 == "kg-shard-manifest/v2"
    assert ROUTING_RENDEZVOUS_HRW in {"rendezvous-hrw"}
    assert ROUTING_HASH_MODULO in {"hash-modulo"}
    assert "car" in SHARD_CODECS
    assert "bloom-v1" in SHARD_CODECS
    assert "dag-cbor" in SHARD_CODECS
    assert "bloom_entity_type" in INDEX_BUCKET_KINDS
    assert "outgoing" in ADJACENCY_DIRECTIONS


# ---------------------------------------------------------------------------
# Golden deterministic serialization
# ---------------------------------------------------------------------------


def test_golden_v2_checksum_and_root_cid() -> None:
    manifest = _golden_manifest()
    assert manifest.version == SHARD_MANIFEST_V2
    assert manifest.checksum.algorithm == "sha256"
    assert manifest.checksum.hex_digest == GOLDEN_CHECKSUM_HEX
    assert manifest.root_cid == GOLDEN_ROOT_CID
    # Rebuilding yields the same identity.
    again = _golden_manifest()
    assert again.checksum.hex_digest == GOLDEN_CHECKSUM_HEX
    assert again.root_cid == GOLDEN_ROOT_CID
    assert again.to_json() == manifest.to_json()


def test_golden_canonical_json_is_compact_and_key_sorted() -> None:
    manifest = _golden_manifest()
    encoded = manifest.to_json()
    parsed = json.loads(encoded)
    reencoded = json.dumps(
        parsed,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert encoded == reencoded
    # Identity bytes hash to declared checksum.
    identity = manifest.identity_bytes()
    assert hashlib.sha256(identity).hexdigest() == GOLDEN_CHECKSUM_HEX
    assert canonical_json_bytes({"b": 1, "a": 2}) == b'{"a":2,"b":1}'


def test_golden_round_trip_dict_and_json() -> None:
    manifest = _golden_manifest()
    restored = ShardedGraphManifest.from_json(manifest.to_json())
    assert restored.checksum == manifest.checksum
    assert restored.root_cid == manifest.root_cid
    assert restored.to_dict() == manifest.to_dict()
    assert restored.routing.algorithm == ROUTING_RENDEZVOUS_HRW
    assert len(restored.physical_shards) == 2
    assert len(restored.virtual_shards) == 4
    assert len(restored.cross_shard_adjacency) == 1
    assert restored.schema_version == "2"
    assert restored.index_version == "2"
    assert restored.codec == "dag-cbor"
    assert restored.statistics.entity_count == 10
    assert restored.statistics.cross_shard_out_edges == 2
    assert restored.provenance.producer_id == "producer:kg-shard-publisher"

    with pytest.raises(FrozenInstanceError):
        manifest.schema_version = "mutated"  # type: ignore[misc]


def test_golden_descriptor_surface_covers_acceptance() -> None:
    payload = _golden_manifest().to_dict()
    for key in (
        "version",
        "routing",
        "schema_version",
        "index_version",
        "codec",
        "physical_shards",
        "virtual_shards",
        "cross_shard_adjacency",
        "statistics",
        "provenance",
        "checksum",
        "root_cid",
        "shard_size_limit_bytes",
        "target_shard_bytes",
    ):
        assert key in payload
    phys = payload["physical_shards"][0]
    assert "checksum" in phys and "car_cid" in phys
    assert "index_buckets" in phys
    assert phys["index_buckets"][0]["kind"] == "bloom_entity_type"
    assert "bloom" in phys["index_buckets"][0]
    assert payload["routing"]["algorithm"] == ROUTING_RENDEZVOUS_HRW
    assert payload["cross_shard_adjacency"][0]["direction"] == "outgoing"
    assert payload["provenance"]["source"] == "unit-fixture"


# ---------------------------------------------------------------------------
# Routing: rendezvous + v1 hash-modulo parity
# ---------------------------------------------------------------------------


def test_stable_shard_index_matches_sha256_mod() -> None:
    entity_id = "alice"
    digest = hashlib.sha256(entity_id.encode("utf-8")).digest()
    expected = int.from_bytes(digest[:8], "big") % 7
    assert stable_shard_index(entity_id, num_shards=7) == expected
    assert hash_modulo_index(entity_id.encode("utf-8"), modulus=7) == expected


def test_rendezvous_pick_is_deterministic_and_stable_under_add() -> None:
    key = b"entity-42"
    nodes = ("n1", "n2", "n3")
    pick = rendezvous_pick(key, nodes, seed="s")
    assert pick in nodes
    assert rendezvous_pick(key, nodes, seed="s") == pick
    # Adding a node moves at most this key or leaves it (HRW property for one key).
    pick2 = rendezvous_pick(key, nodes + ("n4",), seed="s")
    assert pick2 in nodes + ("n4",)
    # Scores are total-ordered.
    scores = [rendezvous_score(key, n, seed="s") for n in nodes]
    assert len(set(scores)) == len(nodes)


def test_virtual_to_physical_rendezvous_table() -> None:
    table = build_virtual_to_physical_table(
        virtual_shard_count=8,
        physical_shard_ids=("p-b", "p-a"),
        algorithm=ROUTING_RENDEZVOUS_HRW,
        seed="seed",
    )
    assert len(table) == 8
    assert table[0].virtual_shard_id == virtual_shard_id_for_index(0)
    assert {t.physical_shard_id for t in table} <= {"p-a", "p-b"}
    # Physical assignment for each virtual index is rendezvous.
    for row in table:
        assert row.physical_shard_id == physical_shard_for_virtual(
            row.index,
            ("p-a", "p-b"),
            seed="seed",
            algorithm=ROUTING_RENDEZVOUS_HRW,
        )


def test_route_entity_on_golden_manifest() -> None:
    manifest = _golden_manifest()
    # Virtual index 0 -> phys-b, 2 -> phys-a (from golden mapping).
    assert virtual_shard_index("entity-1", virtual_shard_count=4, seed="fixture-seed") == 0
    assert manifest.route_entity("entity-1") == "phys-b"
    assert virtual_shard_index("entity-2", virtual_shard_count=4, seed="fixture-seed") == 2
    assert manifest.route_entity("entity-2") == "phys-a"


def test_v1_hash_modulo_routing_parity() -> None:
    manifest = load_sharded_graph_manifest(_v1_dict())
    assert manifest.version == SHARD_MANIFEST_V1
    assert manifest.routing.algorithm == ROUTING_HASH_MODULO
    ordered = sorted(manifest.physical_shard_ids())
    for entity_id in ("alice", "bob", "entity-99", "x"):
        idx = stable_shard_index(entity_id, num_shards=len(ordered))
        assert manifest.route_entity(entity_id) == ordered[idx]


# ---------------------------------------------------------------------------
# v1 read compatibility
# ---------------------------------------------------------------------------


def test_v1_read_compatibility_round_trip_projection() -> None:
    raw = _v1_dict()
    loaded = load_sharded_graph_manifest(raw)
    assert loaded.version == SHARD_MANIFEST_V1
    assert len(loaded.physical_shards) == 2
    assert len(loaded.virtual_shards) == 2
    assert loaded.shard_size_limit_bytes == DEFAULT_SHARD_SIZE_LIMIT_BYTES
    assert loaded.target_shard_bytes == DEFAULT_TARGET_SHARD_BYTES
    # Per-shard blooms preserved.
    by_id = loaded.physical_by_id()
    assert by_id["S0"].entity_type_bloom is not None
    assert by_id["S0"].entity_type_bloom.num_bits == 64
    assert by_id["S0"].car_cid == V1_GOLDEN_SHARDS[0]["car_cid"]

    projected = loaded.to_v1_dict()
    assert projected["version"] == "v1"
    assert len(projected["shards"]) == 2
    shard_ids = {s["shard_id"] for s in projected["shards"]}
    assert shard_ids == {"S0", "S1"}
    # Re-load projected v1.
    again = ShardedGraphManifest.from_dict(projected)
    assert again.version == SHARD_MANIFEST_V1
    assert set(again.physical_shard_ids()) == {"S0", "S1"}


def test_from_dict_dispatches_v1_and_v2() -> None:
    v2 = _golden_manifest()
    assert ShardedGraphManifest.from_dict(v2.to_dict()).checksum == v2.checksum
    v1 = load_sharded_graph_manifest(_v1_dict())
    assert ShardedGraphManifest.from_dict(_v1_dict()).physical_shard_ids() == v1.physical_shard_ids()


def test_v1_bloom_dict_accepted() -> None:
    bloom = BloomFilterDescriptor.from_v1_bloom_dict(
        {"num_bits": 32, "num_hashes": 2, "bits_hex": "00" * 4}
    )
    assert bloom.num_bits == 32
    assert bloom.bits_hex == "00000000"


# ---------------------------------------------------------------------------
# Validation / rejection
# ---------------------------------------------------------------------------


def test_rejects_unknown_routing_algorithm() -> None:
    with pytest.raises(ShardManifestValidationError) as excinfo:
        RendezvousRoutingDescriptor(
            algorithm="consistent-hash-ring",
            hash_function="sha256",
            virtual_shard_count=4,
        )
    assert excinfo.value.code == "NONCANONICAL_VALUE"


def test_rejects_unknown_codec_and_bucket_kind() -> None:
    with pytest.raises(ShardManifestValidationError) as excinfo:
        PhysicalShardDescriptor(
            physical_shard_id="p1",
            codec="protobuf",
            checksum=_ck(b"p"),
            size_bytes=1,
            statistics=ShardStatistics(),
            path="shards/p1.car",
        )
    assert excinfo.value.code == "NONCANONICAL_VALUE"

    with pytest.raises(ShardManifestValidationError) as excinfo:
        IndexBucketDescriptor(
            bucket_id="b1",
            kind="mystery",
            codec="bloom-v1",
            checksum=_ck(b"b"),
            size_bytes=1,
            path="indexes/b1",
        )
    assert excinfo.value.code == "NONCANONICAL_VALUE"


def test_rejects_unsafe_paths() -> None:
    with pytest.raises(ShardManifestValidationError) as excinfo:
        PhysicalShardDescriptor(
            physical_shard_id="p1",
            codec="car",
            checksum=_ck(b"p"),
            size_bytes=1,
            statistics=ShardStatistics(),
            path="../escape.car",
        )
    assert excinfo.value.code == "UNSAFE_PATH"


def test_rejects_cross_shard_same_physical() -> None:
    with pytest.raises(ShardManifestValidationError) as excinfo:
        CrossShardAdjacencyDescriptor(
            adjacency_id="a1",
            source_physical_shard_id="p1",
            target_physical_shard_id="p1",
            direction="outgoing",
            edge_count=1,
            codec="json",
            checksum=_ck(b"a"),
            path="adj/a1.json",
        )
    assert excinfo.value.code == "AMBIGUOUS_ID"


def test_rejects_checksum_mismatch_on_manifest() -> None:
    manifest = _golden_manifest()
    payload = manifest.to_dict()
    payload["checksum"] = {
        "algorithm": "sha256",
        "hex_digest": "0" * 64,
    }
    with pytest.raises(ShardManifestIntegrityError) as excinfo:
        ShardedGraphManifest.from_dict(payload)
    assert excinfo.value.code == "CHECKSUM_CID_MISMATCH"


def test_rejects_index_bucket_cid_mismatch() -> None:
    with pytest.raises(ShardManifestIntegrityError) as excinfo:
        IndexBucketDescriptor(
            bucket_id="b1",
            kind="headers",
            codec="json",
            checksum=_ck(b"payload"),
            size_bytes=7,
            path="indexes/b1.json",
            cid=_ck(b"other").as_cid(),
        )
    assert excinfo.value.code == "CHECKSUM_CID_MISMATCH"


def test_rejects_virtual_unknown_physical() -> None:
    routing = RendezvousRoutingDescriptor(
        algorithm=ROUTING_HASH_MODULO,
        hash_function="sha256",
        virtual_shard_count=1,
    )
    pck = _ck(b"car")
    phys = PhysicalShardDescriptor(
        physical_shard_id="only",
        codec="car",
        checksum=pck,
        size_bytes=1,
        statistics=ShardStatistics(physical_shard_count=1, virtual_shard_count=1),
        car_cid=pck.as_cid(),
        virtual_shard_ids=("vs-00000000",),
    )
    with pytest.raises(ShardManifestValidationError) as excinfo:
        build_sharded_graph_manifest(
            routing=routing,
            schema_version="1",
            index_version="1",
            codec="json",
            physical_shards=(phys,),
            virtual_shards=(
                VirtualShardDescriptor(
                    virtual_shard_id="vs-00000000",
                    index=0,
                    physical_shard_id="missing",
                ),
            ),
            provenance=_provenance(),
        )
    assert excinfo.value.code == "AMBIGUOUS_ID"


def test_rejects_target_bytes_exceeding_limit() -> None:
    routing = RendezvousRoutingDescriptor(
        algorithm=ROUTING_HASH_MODULO,
        hash_function="sha256",
        virtual_shard_count=1,
    )
    pck = _ck(b"car")
    phys = PhysicalShardDescriptor(
        physical_shard_id="only",
        codec="car",
        checksum=pck,
        size_bytes=1,
        statistics=ShardStatistics(physical_shard_count=1, virtual_shard_count=1),
        car_cid=pck.as_cid(),
        virtual_shard_ids=("vs-00000000",),
    )
    with pytest.raises(ShardManifestValidationError) as excinfo:
        build_sharded_graph_manifest(
            routing=routing,
            schema_version="1",
            index_version="1",
            codec="json",
            physical_shards=(phys,),
            virtual_shards=(
                VirtualShardDescriptor(
                    virtual_shard_id="vs-00000000",
                    index=0,
                    physical_shard_id="only",
                ),
            ),
            provenance=_provenance(),
            shard_size_limit_bytes=100,
            target_shard_bytes=200,
        )
    assert excinfo.value.code == "INVALID_COUNT"


def test_rejects_unsorted_physical_shards_on_construct() -> None:
    routing = RendezvousRoutingDescriptor(
        algorithm=ROUTING_HASH_MODULO,
        hash_function="sha256",
        virtual_shard_count=2,
    )
    a = PhysicalShardDescriptor(
        physical_shard_id="b-shard",
        codec="car",
        checksum=_ck(b"b"),
        size_bytes=1,
        statistics=ShardStatistics(),
        path="shards/b.car",
        virtual_shard_ids=(),
    )
    b = PhysicalShardDescriptor(
        physical_shard_id="a-shard",
        codec="car",
        checksum=_ck(b"a"),
        size_bytes=1,
        statistics=ShardStatistics(),
        path="shards/a.car",
        virtual_shard_ids=(),
    )
    # Direct constructor requires pre-sorted lists.
    with pytest.raises(ShardManifestValidationError) as excinfo:
        ShardedGraphManifest(
            version=SHARD_MANIFEST_V2,
            routing=routing,
            schema_version="1",
            index_version="1",
            codec="json",
            physical_shards=(a, b),  # wrong order
            virtual_shards=(),
            cross_shard_adjacency=(),
            statistics=ShardStatistics(physical_shard_count=2),
            provenance=_provenance(),
            checksum=_ck(b"x"),
            _skip_identity_checksum=True,
        )
    assert excinfo.value.code == "NONCANONICAL_VALUE"

    # build_ helper sorts.
    built = build_sharded_graph_manifest(
        routing=routing,
        schema_version="1",
        index_version="1",
        codec="json",
        physical_shards=(a, b),
        provenance=_provenance(),
    )
    assert [p.physical_shard_id for p in built.physical_shards] == ["a-shard", "b-shard"]


def test_optional_root_cid_can_be_omitted() -> None:
    routing = RendezvousRoutingDescriptor(
        algorithm=ROUTING_HASH_MODULO,
        hash_function="sha256",
        virtual_shard_count=1,
    )
    pck = _ck(b"car-only")
    phys = PhysicalShardDescriptor(
        physical_shard_id="only",
        codec="car",
        checksum=pck,
        size_bytes=3,
        statistics=ShardStatistics(physical_shard_count=1, virtual_shard_count=1),
        car_cid=pck.as_cid(),
        virtual_shard_ids=("vs-00000000",),
    )
    manifest = build_sharded_graph_manifest(
        routing=routing,
        schema_version="1",
        index_version="1",
        codec="json",
        physical_shards=(phys,),
        virtual_shards=(
            VirtualShardDescriptor(
                virtual_shard_id="vs-00000000",
                index=0,
                physical_shard_id="only",
            ),
        ),
        provenance=_provenance(),
        include_root_cid=False,
    )
    assert manifest.root_cid is None
    assert len(manifest.checksum.hex_digest) == 64
    restored = ShardedGraphManifest.from_dict(manifest.to_dict())
    assert restored.root_cid is None
    assert restored.checksum == manifest.checksum


def test_build_classmethod_matches_function() -> None:
    via_fn = _golden_manifest()
    via_cls = ShardedGraphManifest.build(
        routing=via_fn.routing,
        schema_version=via_fn.schema_version,
        index_version=via_fn.index_version,
        codec=via_fn.codec,
        physical_shards=via_fn.physical_shards,
        virtual_shards=via_fn.virtual_shards,
        cross_shard_adjacency=via_fn.cross_shard_adjacency,
        provenance=via_fn.provenance,
        statistics=via_fn.statistics,
        shard_size_limit_bytes=via_fn.shard_size_limit_bytes,
        target_shard_bytes=via_fn.target_shard_bytes,
    )
    assert via_fn.checksum == via_cls.checksum
    assert via_fn.root_cid == via_cls.root_cid
