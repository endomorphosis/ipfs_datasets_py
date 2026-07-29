"""Publish bounded CAR shards, index buckets, and cross-shard adjacency (KGP-014).

Pipeline:
1. Route every entity id onto a virtual shard, then a physical shard (rendezvous).
2. Place entities into physical shard fragments; keep **intra-shard** relationships
   inside the CAR payload.
3. Retain **incoming/outgoing cross-shard** edges in per-pair adjacency blocks
   and in per-entity neighbor index buckets on both endpoint shards.
4. Emit bounded index buckets (headers, type_index, neighbors, blooms).
5. Build a validated :class:`ShardedGraphManifest` v2 with checksums/CIDs.
"""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

from ipfs_datasets_py.knowledge_graphs.contracts.manifest import (
    ContentChecksum,
    ProvenanceDescriptor,
)
from ipfs_datasets_py.knowledge_graphs.storage.sharding.blocks import (
    BlockStore,
    MemoryBlockStore,
    encode_json_block,
)
from ipfs_datasets_py.knowledge_graphs.storage.sharding.manifest import (
    DEFAULT_SHARD_SIZE_LIMIT_BYTES,
    DEFAULT_TARGET_SHARD_BYTES,
    DEFAULT_VIRTUAL_SHARD_COUNT,
    ROUTING_RENDEZVOUS_HRW,
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
    virtual_shard_id_for_index,
)
from ipfs_datasets_py.knowledge_graphs.storage.sharding.models import (
    EntityRecord,
    GraphFragment,
    RelationshipRecord,
)
from ipfs_datasets_py.knowledge_graphs.storage.sharding.routing import ShardRouter


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PublishedShardedGraphV2:
    """Result of a successful v2 publish."""

    manifest: ShardedGraphManifest
    store: BlockStore
    physical_shard_ids: tuple[str, ...]
    entity_counts: Mapping[str, int]
    relationship_counts: Mapping[str, int]
    cross_shard_edge_count: int
    car_paths: Mapping[str, str]


@dataclass
class _ShardBuildState:
    physical_shard_id: str
    fragment: GraphFragment = field(default_factory=GraphFragment)
    # entity_id -> list of neighbor edge dicts
    outgoing: dict[str, list[dict[str, Any]]] = field(default_factory=lambda: defaultdict(list))
    incoming: dict[str, list[dict[str, Any]]] = field(default_factory=lambda: defaultdict(list))
    virtual_shard_ids: set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# Bloom helpers (inline bits for entity-type filters)
# ---------------------------------------------------------------------------


def _bloom_add(bits: bytearray, *, num_bits: int, num_hashes: int, key: str) -> None:
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    for i in range(num_hashes):
        # Derive positions from successive 4-byte windows (wrap).
        offset = (i * 4) % (len(digest) - 3)
        pos = int.from_bytes(digest[offset : offset + 4], "big") % num_bits
        bits[pos // 8] |= 1 << (pos % 8)


def build_type_bloom_descriptor(
    types: Sequence[str],
    *,
    num_bits: int = 8192,
    num_hashes: int = 7,
) -> BloomFilterDescriptor:
    if num_bits < 8:
        num_bits = 8
    nbytes = (num_bits + 7) // 8
    bits = bytearray(nbytes)
    for t in types:
        if t:
            _bloom_add(bits, num_bits=num_bits, num_hashes=num_hashes, key=str(t))
    return BloomFilterDescriptor(
        num_bits=num_bits,
        num_hashes=num_hashes,
        bits_hex=bits.hex(),
    )


def _auto_prefix_len(
    num_items: int,
    *,
    target_bucket_size: int = 5000,
    max_prefix_len: int = 8,
) -> int:
    n = int(num_items)
    target = max(1, int(target_bucket_size))
    if n <= target:
        return 0
    buckets_needed = int(math.ceil(n / float(target)))
    prefix_len = 0
    capacity = 1
    while capacity < buckets_needed and prefix_len < int(max_prefix_len):
        prefix_len += 1
        capacity *= 16
    return max(1, prefix_len)


def _entity_bucket_key(entity_id: str, *, prefix_len: int) -> str:
    digest = hashlib.sha256(entity_id.encode("utf-8", errors="strict")).hexdigest()
    return digest[: max(1, int(prefix_len))]


# ---------------------------------------------------------------------------
# Partitioning
# ---------------------------------------------------------------------------


def partition_graph_v2(
    graph: GraphFragment,
    *,
    router: ShardRouter,
) -> tuple[dict[str, _ShardBuildState], list[tuple[RelationshipRecord, str, str]]]:
    """Split *graph* into per-physical build states + cross-shard edge list.

    Cross-shard edges are retained on **both** endpoint shards' neighbor maps
    (outgoing on source, incoming on target) and listed for adjacency blocks.
    """
    states: dict[str, _ShardBuildState] = {
        pid: _ShardBuildState(physical_shard_id=pid, fragment=GraphFragment(name=pid))
        for pid in router.physical_shard_ids
    }

    entity_home: dict[str, str] = {}
    for ent in graph.iter_entities():
        assignment = router.assign(ent.entity_id)
        pid = assignment.physical_shard_id
        entity_home[ent.entity_id] = pid
        st = states[pid]
        st.fragment.entities[ent.entity_id] = ent
        st.virtual_shard_ids.add(assignment.virtual_shard_id)

    cross: list[tuple[RelationshipRecord, str, str]] = []
    for rel in graph.iter_relationships():
        src_pid = entity_home.get(rel.source_id)
        tgt_pid = entity_home.get(rel.target_id)
        if src_pid is None or tgt_pid is None:
            # Orphan endpoints: drop edge (publisher requires known endpoints).
            continue
        if src_pid == tgt_pid:
            states[src_pid].fragment.relationships[rel.relationship_id] = rel
            states[src_pid].outgoing[rel.source_id].append(
                rel.to_neighbor_dict(cross_shard=False)
            )
            states[src_pid].incoming[rel.target_id].append(
                rel.to_neighbor_dict(cross_shard=False)
            )
        else:
            cross.append((rel, src_pid, tgt_pid))
            states[src_pid].outgoing[rel.source_id].append(
                rel.to_neighbor_dict(
                    cross_shard=True,
                    peer_physical_shard_id=tgt_pid,
                )
            )
            states[tgt_pid].incoming[rel.target_id].append(
                rel.to_neighbor_dict(
                    cross_shard=True,
                    peer_physical_shard_id=src_pid,
                )
            )

    # Stable sort neighbor lists by relationship_id.
    for st in states.values():
        for eid, edges in st.outgoing.items():
            edges.sort(key=lambda e: e.get("relationship_id") or "")
        for eid, edges in st.incoming.items():
            edges.sort(key=lambda e: e.get("relationship_id") or "")

    return states, cross


# ---------------------------------------------------------------------------
# Index bucket publishers
# ---------------------------------------------------------------------------


def _put_json(
    store: BlockStore,
    obj: Any,
    *,
    path: str,
    codec: str = "json",
) -> tuple[ContentChecksum, str, int]:
    data = encode_json_block(obj)
    stored = store.put(data, path=path, codec=codec)
    return stored.checksum, stored.cid, stored.size_bytes


def _publish_headers_buckets(
    store: BlockStore,
    st: _ShardBuildState,
    *,
    prefix_len: int,
    schema_version: str,
) -> tuple[list[IndexBucketDescriptor], Optional[str]]:
    headers: dict[str, dict[str, Any]] = {}
    for ent in st.fragment.iter_entities():
        headers[ent.entity_id] = {
            "type": ent.entity_type,
            "name": ent.name,
            "cid": ent.cid,
            "properties": dict(ent.properties) if ent.properties else None,
        }

    buckets: list[IndexBucketDescriptor] = []
    headers_cid: Optional[str] = None

    if prefix_len <= 0:
        path = f"indexes/{st.physical_shard_id}/headers.json"
        checksum, cid, size = _put_json(store, headers, path=path)
        headers_cid = cid
        buckets.append(
            IndexBucketDescriptor(
                bucket_id=f"{st.physical_shard_id}-headers",
                kind="headers",
                codec="json",
                checksum=checksum,
                size_bytes=size,
                fields=("entity_id", "name", "type"),
                path=path,
                cid=cid,
                schema_version=schema_version,
            )
        )
        return buckets, headers_cid

    grouped: dict[str, dict[str, Any]] = defaultdict(dict)
    for eid, header in headers.items():
        grouped[_entity_bucket_key(eid, prefix_len=prefix_len)][eid] = header

    bucket_cids: dict[str, str] = {}
    for bkey in sorted(grouped.keys()):
        path = f"indexes/{st.physical_shard_id}/headers/{bkey}.json"
        checksum, cid, size = _put_json(store, grouped[bkey], path=path)
        bucket_cids[bkey] = cid
        buckets.append(
            IndexBucketDescriptor(
                bucket_id=f"{st.physical_shard_id}-headers-{bkey}",
                kind="headers",
                codec="json",
                checksum=checksum,
                size_bytes=size,
                fields=("entity_id", "name", "type"),
                path=path,
                cid=cid,
                schema_version=schema_version,
            )
        )

    meta = {"v": 2, "prefix_len": prefix_len, "buckets": bucket_cids}
    meta_path = f"indexes/{st.physical_shard_id}/headers.meta.json"
    _checksum, meta_cid, _size = _put_json(store, meta, path=meta_path)
    headers_cid = meta_cid
    return buckets, headers_cid


def _publish_type_index(
    store: BlockStore,
    st: _ShardBuildState,
    *,
    schema_version: str,
) -> tuple[list[IndexBucketDescriptor], Optional[str]]:
    type_idx: dict[str, list[str]] = defaultdict(list)
    for ent in st.fragment.iter_entities():
        if ent.entity_type:
            type_idx[ent.entity_type].append(ent.entity_id)
    for t in list(type_idx.keys()):
        type_idx[t] = sorted(set(type_idx[t]))

    path = f"indexes/{st.physical_shard_id}/type_index.json"
    checksum, cid, size = _put_json(store, dict(type_idx), path=path)
    bucket = IndexBucketDescriptor(
        bucket_id=f"{st.physical_shard_id}-type-index",
        kind="type_index",
        codec="json",
        checksum=checksum,
        size_bytes=size,
        fields=("entity_id", "entity_type"),
        path=path,
        cid=cid,
        schema_version=schema_version,
    )
    return [bucket], cid


def _publish_neighbors_buckets(
    store: BlockStore,
    st: _ShardBuildState,
    *,
    prefix_len: int,
    schema_version: str,
) -> tuple[list[IndexBucketDescriptor], Optional[str]]:
    entity_ids = set(st.fragment.entities.keys()) | set(st.outgoing.keys()) | set(
        st.incoming.keys()
    )
    per_entity: dict[str, dict[str, Any]] = {}
    for eid in sorted(entity_ids):
        per_entity[eid] = {
            "v": 1,
            "outgoing": list(st.outgoing.get(eid, [])),
            "incoming": list(st.incoming.get(eid, [])),
        }

    buckets: list[IndexBucketDescriptor] = []
    if prefix_len <= 0:
        # Single neighbors map: entity_id -> adjacency object (inline for small shards).
        path = f"indexes/{st.physical_shard_id}/neighbors.json"
        checksum, cid, size = _put_json(store, per_entity, path=path)
        buckets.append(
            IndexBucketDescriptor(
                bucket_id=f"{st.physical_shard_id}-neighbors",
                kind="neighbors",
                codec="json",
                checksum=checksum,
                size_bytes=size,
                fields=("entity_id", "incoming", "outgoing"),
                path=path,
                cid=cid,
                schema_version=schema_version,
            )
        )
        return buckets, cid

    grouped: dict[str, dict[str, Any]] = defaultdict(dict)
    for eid, adj in per_entity.items():
        grouped[_entity_bucket_key(eid, prefix_len=prefix_len)][eid] = adj

    bucket_cids: dict[str, str] = {}
    for bkey in sorted(grouped.keys()):
        path = f"indexes/{st.physical_shard_id}/neighbors/{bkey}.json"
        checksum, cid, size = _put_json(store, grouped[bkey], path=path)
        bucket_cids[bkey] = cid
        buckets.append(
            IndexBucketDescriptor(
                bucket_id=f"{st.physical_shard_id}-neighbors-{bkey}",
                kind="neighbors",
                codec="json",
                checksum=checksum,
                size_bytes=size,
                fields=("entity_id", "incoming", "outgoing"),
                path=path,
                cid=cid,
                schema_version=schema_version,
            )
        )

    meta = {"v": 2, "prefix_len": prefix_len, "buckets": bucket_cids}
    meta_path = f"indexes/{st.physical_shard_id}/neighbors.meta.json"
    _checksum, meta_cid, _size = _put_json(store, meta, path=meta_path)
    return buckets, meta_cid


def _publish_bloom_bucket(
    store: BlockStore,
    st: _ShardBuildState,
    *,
    schema_version: str,
) -> tuple[list[IndexBucketDescriptor], BloomFilterDescriptor]:
    types = st.fragment.entity_types()
    bloom = build_type_bloom_descriptor(types, num_bits=1024, num_hashes=5)
    # Also store bits as a CID-backed object for fetch/verify demos.
    bits = bytes.fromhex(bloom.bits_hex or "")
    path = f"indexes/{st.physical_shard_id}/entity_type.bloom"
    stored = store.put(bits, path=path, codec="bloom-v1")
    bloom_with_cid = BloomFilterDescriptor(
        num_bits=bloom.num_bits,
        num_hashes=bloom.num_hashes,
        bits_hex=bloom.bits_hex,
        checksum=stored.checksum,
        cid=stored.cid,
    )
    bucket = IndexBucketDescriptor(
        bucket_id=f"{st.physical_shard_id}-bloom-entity-type",
        kind="bloom_entity_type",
        codec="bloom-v1",
        checksum=stored.checksum,
        size_bytes=stored.size_bytes,
        fields=("entity_type",),
        path=path,
        cid=stored.cid,
        bloom=bloom_with_cid,
        schema_version=schema_version,
    )
    return [bucket], bloom_with_cid


def _encode_car_payload(payload_obj: Mapping[str, Any]) -> bytes:
    """Encode shard payload as CAR-wrapped raw JSON (or plain JSON fallback).

    Prefer ``ipld_car`` when available so published objects are real CAR bytes.
    """
    body = encode_json_block(payload_obj)
    try:
        import ipld_car  # type: ignore
        from multiformats import CID, multihash  # type: ignore

        digest = multihash.digest(body, "sha2-256")
        root = CID("base32", 1, "raw", digest)
        car_mv = ipld_car.encode([root], [(root, body)])
        return bytes(car_mv)
    except Exception:
        # Deterministic fallback: length-prefixed CAR-like envelope.
        # Magic "KGCR" + u32 body length + body. Still codec-labeled "car" for
        # offline tests without multiformats/ipld_car.
        return b"KGCR" + len(body).to_bytes(4, "big") + body


def decode_car_payload(car_bytes: bytes) -> dict[str, Any]:
    """Decode a payload produced by :func:`_encode_car_payload`."""
    from ipfs_datasets_py.knowledge_graphs.storage.sharding.blocks import decode_json_block

    data = bytes(car_bytes)
    if data.startswith(b"KGCR") and len(data) >= 8:
        n = int.from_bytes(data[4:8], "big")
        return decode_json_block(data[8 : 8 + n])

    try:
        import ipld_car  # type: ignore

        roots, blocks = ipld_car.decode(data)
        if roots:
            # blocks may be dict-like or list of pairs
            if hasattr(blocks, "items"):
                pairs = list(blocks.items())
            else:
                pairs = list(blocks)
            # Prefer root block
            root = roots[0]
            for cid, blob in pairs:
                if str(cid) == str(root) or cid == root:
                    return decode_json_block(bytes(blob))
            if pairs:
                return decode_json_block(bytes(pairs[0][1]))
    except Exception:
        pass

    # Last resort: treat entire blob as JSON.
    return decode_json_block(data)


# ---------------------------------------------------------------------------
# Public publisher
# ---------------------------------------------------------------------------


def publish_sharded_graph_v2(
    graph: GraphFragment,
    *,
    physical_shard_ids: Sequence[str] | None = None,
    num_physical_shards: int = 2,
    virtual_shard_count: int = DEFAULT_VIRTUAL_SHARD_COUNT,
    algorithm: str = ROUTING_RENDEZVOUS_HRW,
    seed: str = "kgp-014",
    schema_version: str = "2",
    index_version: str = "2",
    store: BlockStore | None = None,
    index_bucket_target_size: int = 64,
    force_bucket_prefix_len: int | None = None,
    shard_size_limit_bytes: int = DEFAULT_SHARD_SIZE_LIMIT_BYTES,
    target_shard_bytes: int = DEFAULT_TARGET_SHARD_BYTES,
    provenance: ProvenanceDescriptor | None = None,
    materialize_virtual_table: bool = True,
) -> PublishedShardedGraphV2:
    """Publish a knowledge graph as bounded CAR shards + index buckets (v2).

    Args:
        graph: In-memory fragment to shard.
        physical_shard_ids: Explicit physical shard ids (sorted internally).
        num_physical_shards: Used when ``physical_shard_ids`` is omitted.
        virtual_shard_count: Fixed virtual ring size (stable under rebalance).
        algorithm: ``rendezvous-hrw`` or ``hash-modulo``.
        seed: Domain-separated routing seed.
        store: Block store (defaults to :class:`MemoryBlockStore`).
        index_bucket_target_size: Target entries per index bucket (auto prefix).
        force_bucket_prefix_len: Override auto prefix (0 = single blob).
        materialize_virtual_table: Emit full virtual→physical rows in the manifest.

    Returns:
        :class:`PublishedShardedGraphV2` with validated manifest and store.
    """
    if physical_shard_ids is None:
        physical_shard_ids = [f"phys-{i:04d}" for i in range(int(num_physical_shards))]
    pids = tuple(sorted(str(p) for p in physical_shard_ids))
    if not pids:
        raise ValueError("at least one physical shard is required")
    if virtual_shard_count < 1:
        raise ValueError("virtual_shard_count must be >= 1")

    routing = RendezvousRoutingDescriptor(
        algorithm=algorithm,
        hash_function="sha256",
        virtual_shard_count=int(virtual_shard_count),
        seed=seed,
        key_normalization="utf-8",
    )

    virtual_rows: tuple[VirtualShardDescriptor, ...] = ()
    if materialize_virtual_table:
        virtual_rows = build_virtual_to_physical_table(
            virtual_shard_count=routing.virtual_shard_count,
            physical_shard_ids=pids,
            algorithm=routing.algorithm,
            seed=routing.seed,
        )
        vmap = {r.index: r.physical_shard_id for r in virtual_rows}
    else:
        vmap = {}

    router = ShardRouter(
        routing=routing,
        physical_shard_ids=pids,
        virtual_to_physical=vmap,
    )
    store = store if store is not None else MemoryBlockStore()
    states, cross_edges = partition_graph_v2(graph, router=router)

    # Group cross-shard edges by ordered physical pair + direction records.
    # We emit one "outgoing" adjacency block per (src, tgt) pair and one
    # "incoming" block per (tgt, src) so both directions are retained.
    out_groups: dict[tuple[str, str], list[RelationshipRecord]] = defaultdict(list)
    for rel, src_pid, tgt_pid in cross_edges:
        out_groups[(src_pid, tgt_pid)].append(rel)

    adjacency_descriptors: list[CrossShardAdjacencyDescriptor] = []
    for (src_pid, tgt_pid), rels in sorted(out_groups.items()):
        rels_sorted = sorted(rels, key=lambda r: r.relationship_id)
        payload = {
            "v": 1,
            "direction": "outgoing",
            "source_physical_shard_id": src_pid,
            "target_physical_shard_id": tgt_pid,
            "edges": [r.to_dict() for r in rels_sorted],
        }
        path = f"adjacency/{src_pid}__{tgt_pid}__out.json"
        checksum, cid, _size = _put_json(store, payload, path=path)
        adjacency_descriptors.append(
            CrossShardAdjacencyDescriptor(
                adjacency_id=f"adj-{src_pid}-{tgt_pid}-out",
                source_physical_shard_id=src_pid,
                target_physical_shard_id=tgt_pid,
                direction="outgoing",
                edge_count=len(rels_sorted),
                codec="json",
                checksum=checksum,
                path=path,
                cid=cid,
            )
        )
        # Mirror incoming descriptor on the reverse orientation for readers
        # that walk target-side adjacency lists.
        in_payload = {
            "v": 1,
            "direction": "incoming",
            "source_physical_shard_id": src_pid,
            "target_physical_shard_id": tgt_pid,
            "edges": [r.to_dict() for r in rels_sorted],
        }
        in_path = f"adjacency/{tgt_pid}__{src_pid}__in.json"
        in_checksum, in_cid, _ = _put_json(store, in_payload, path=in_path)
        adjacency_descriptors.append(
            CrossShardAdjacencyDescriptor(
                adjacency_id=f"adj-{tgt_pid}-{src_pid}-in",
                source_physical_shard_id=src_pid,
                target_physical_shard_id=tgt_pid,
                direction="incoming",
                edge_count=len(rels_sorted),
                codec="json",
                checksum=in_checksum,
                path=in_path,
                cid=in_cid,
            )
        )

    physical_descriptors: list[PhysicalShardDescriptor] = []
    car_paths: dict[str, str] = {}
    entity_counts: dict[str, int] = {}
    relationship_counts: dict[str, int] = {}

    # Virtual ids claimed per physical from routing table (preferred) or observed.
    vids_by_pid: dict[str, list[str]] = defaultdict(list)
    if virtual_rows:
        for row in virtual_rows:
            vids_by_pid[row.physical_shard_id].append(row.virtual_shard_id)
        for pid in vids_by_pid:
            vids_by_pid[pid] = sorted(vids_by_pid[pid])
    else:
        for pid, st in states.items():
            vids_by_pid[pid] = sorted(st.virtual_shard_ids)

    for pid in pids:
        st = states[pid]
        n_entities = len(st.fragment.entities)
        # Auto bucket when many entities; small graphs stay single-blob.
        if force_bucket_prefix_len is not None:
            prefix_len = int(force_bucket_prefix_len)
        else:
            prefix_len = _auto_prefix_len(
                n_entities,
                target_bucket_size=index_bucket_target_size,
            )

        header_buckets, headers_cid = _publish_headers_buckets(
            store, st, prefix_len=prefix_len, schema_version=schema_version
        )
        type_buckets, type_index_cid = _publish_type_index(
            store, st, schema_version=schema_version
        )
        neighbor_buckets, neighbors_cid = _publish_neighbors_buckets(
            store, st, prefix_len=prefix_len, schema_version=schema_version
        )
        bloom_buckets, entity_bloom = _publish_bloom_bucket(
            store, st, schema_version=schema_version
        )

        # CAR shard: only entities + *intra-shard* relationships.
        payload = st.fragment.to_payload_dict(physical_shard_id=pid)
        car_bytes = _encode_car_payload(payload)
        if len(car_bytes) > shard_size_limit_bytes:
            raise ValueError(
                f"physical shard {pid!r} CAR size {len(car_bytes)} exceeds "
                f"shard_size_limit_bytes {shard_size_limit_bytes}"
            )
        car_path = f"shards/{pid}.car"
        stored = store.put(car_bytes, path=car_path, codec="car")
        car_paths[pid] = car_path

        cross_out = sum(
            1
            for edges in st.outgoing.values()
            for e in edges
            if e.get("cross_shard")
        )
        cross_in = sum(
            1
            for edges in st.incoming.values()
            for e in edges
            if e.get("cross_shard")
        )

        stats = ShardStatistics(
            entity_count=n_entities,
            relationship_count=len(st.fragment.relationships),
            approx_bytes=len(car_bytes),
            cross_shard_out_edges=cross_out,
            cross_shard_in_edges=cross_in,
            virtual_shard_count=len(vids_by_pid.get(pid, [])),
            physical_shard_count=1,
        )

        all_buckets = tuple(
            sorted(
                header_buckets + type_buckets + neighbor_buckets + bloom_buckets,
                key=lambda b: b.bucket_id,
            )
        )

        physical_descriptors.append(
            PhysicalShardDescriptor(
                physical_shard_id=pid,
                codec="car",
                checksum=stored.checksum,
                size_bytes=stored.size_bytes,
                statistics=stats,
                path=car_path,
                car_cid=stored.cid,
                virtual_shard_ids=tuple(vids_by_pid.get(pid, [])),
                index_buckets=all_buckets,
                schema_version=schema_version,
                index_version=index_version,
                headers_cid=headers_cid,
                type_index_cid=type_index_cid,
                neighbors_index_cid=neighbors_cid,
                entity_type_bloom=entity_bloom,
            )
        )
        entity_counts[pid] = n_entities
        relationship_counts[pid] = len(st.fragment.relationships)

    if provenance is None:
        provenance = ProvenanceDescriptor(
            producer_id="producer:kg-shard-publisher",
            producer_version="2.0.0",
            source="kgp-014-publish",
            created_at="2026-07-29T00:00:00Z",
            repository_revision="kgp-014",
            extra={"pipeline": "kgp-014"},
        )

    manifest = build_sharded_graph_manifest(
        routing=routing,
        schema_version=schema_version,
        index_version=index_version,
        codec="car",
        physical_shards=physical_descriptors,
        virtual_shards=virtual_rows,
        cross_shard_adjacency=adjacency_descriptors,
        provenance=provenance,
        version=SHARD_MANIFEST_V2,
        shard_size_limit_bytes=shard_size_limit_bytes,
        target_shard_bytes=target_shard_bytes,
    )

    # Persist manifest itself for offline load.
    manifest_bytes = encode_json_block(manifest.to_dict())
    store.put(manifest_bytes, path="manifest.json", codec="json")

    return PublishedShardedGraphV2(
        manifest=manifest,
        store=store,
        physical_shard_ids=pids,
        entity_counts=entity_counts,
        relationship_counts=relationship_counts,
        cross_shard_edge_count=len(cross_edges),
        car_paths=car_paths,
    )


def publish_entities_relationships_v2(
    entities: Sequence[EntityRecord | Mapping[str, Any]],
    relationships: Sequence[RelationshipRecord | Mapping[str, Any]] = (),
    **kwargs: Any,
) -> PublishedShardedGraphV2:
    """Convenience wrapper around :func:`publish_sharded_graph_v2`."""
    graph = GraphFragment.from_entities_and_relationships(
        entities, relationships, name="publish"
    )
    return publish_sharded_graph_v2(graph, **kwargs)


__all__ = [
    "PublishedShardedGraphV2",
    "publish_sharded_graph_v2",
    "publish_entities_relationships_v2",
    "partition_graph_v2",
    "build_type_bloom_descriptor",
    "decode_car_payload",
]
