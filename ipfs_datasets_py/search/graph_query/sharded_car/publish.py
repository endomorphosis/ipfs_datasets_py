from __future__ import annotations

import json
import gzip
import tempfile
import hashlib
import math
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from .... import ipfs_backend_router as ipfs_router
from ....data_transformation.ipld.knowledge_graph import IPLDKnowledgeGraph

from .manifest import GraphShardManifest, ShardInfo, build_type_bloom
from .routing import stable_shard_index


@dataclass(frozen=True)
class PublishedShardedGraph:
    manifest_cid: str
    manifest: GraphShardManifest


@dataclass(frozen=True)
class ShardingReport:
    num_shards: int
    shard_ids_sorted: list[str]
    entity_counts: dict[str, int]
    relationship_counts: dict[str, int]


def validate_deterministic_shard_routing(
    shards: Mapping[str, IPLDKnowledgeGraph],
    *,
    shard_ids_sorted: Sequence[str] | None = None,
) -> None:
    """Validate that entities are placed in shards consistent with stable routing.

    The ShardedCARBackend routes an entity to a shard by:
      `stable_shard_index(entity_id) mod N` over *sorted shard_id order*.

    If published shards do not follow this convention, `ScanType` can return
    entity IDs that later fail header lookup (and silently disappear).
    """

    if not shards:
        raise ValueError("shards must be non-empty")

    shard_ids = list(shard_ids_sorted) if shard_ids_sorted is not None else sorted(shards.keys())
    if len(shard_ids) != len(shards):
        raise ValueError("shard_ids_sorted must include exactly all shard IDs")

    shard_index = {sid: i for i, sid in enumerate(shard_ids)}

    for sid, kg in shards.items():
        if sid not in shard_index:
            raise ValueError(f"Unknown shard_id in shards: {sid}")
        expected_idx = shard_index[sid]
        for entity_id in kg.entities.keys():
            routed_idx = stable_shard_index(entity_id, num_shards=len(shard_ids))
            if routed_idx != expected_idx:
                routed_sid = shard_ids[routed_idx]
                raise ValueError(
                    "Deterministic routing mismatch: "
                    f"entity_id={entity_id} is in shard_id={sid} but routes to shard_id={routed_sid}"
                )


def shard_knowledge_graph_deterministic(
    kg: IPLDKnowledgeGraph,
    *,
    num_shards: int,
    shard_ids: Sequence[str] | None = None,
    include_relationships: str = "intra_only",  # intra_only|source_shard|none
) -> tuple[dict[str, IPLDKnowledgeGraph], ShardingReport]:
    """Shard a KG into routing-consistent shards.

    v1 semantics:
    - Entities are assigned to a shard by `stable_shard_index(entity_id) mod N`.
        - Relationships are included only when both endpoints are in the same shard
            (`include_relationships="intra_only"`). Cross-shard edges are omitted.
        - If `include_relationships="source_shard"`, each relationship is stored in
            the shard of its source entity (including cross-shard edges) for the
            adjacency index. Relationships are not necessarily stored in the shard CAR
            itself.
    """

    if num_shards <= 0:
        raise ValueError("num_shards must be > 0")

    ids = list(shard_ids) if shard_ids is not None else [f"S{i}" for i in range(num_shards)]
    if len(ids) != num_shards:
        raise ValueError("shard_ids length must equal num_shards")

    shard_ids_sorted = sorted(ids)
    shard_kgs: dict[str, IPLDKnowledgeGraph] = {sid: IPLDKnowledgeGraph(name=f"{kg.name}::{sid}") for sid in shard_ids_sorted}

    for ent in kg.entities.values():
        sid = shard_ids_sorted[stable_shard_index(ent.id, num_shards=num_shards)]
        shard_kgs[sid].add_entity(
            entity_type=ent.type,
            name=ent.name,
            entity_id=ent.id,
            properties=dict(ent.properties) if ent.properties is not None else None,
            confidence=getattr(ent, "confidence", 1.0),
            source_text=getattr(ent, "source_text", None),
        )

    if include_relationships not in {"intra_only", "source_shard", "none"}:
        raise ValueError("include_relationships must be 'intra_only', 'source_shard', or 'none'")

    if include_relationships == "intra_only":
        for rel in kg.relationships.values():
            src_idx = stable_shard_index(rel.source_id, num_shards=num_shards)
            tgt_idx = stable_shard_index(rel.target_id, num_shards=num_shards)
            if src_idx != tgt_idx:
                continue
            sid = shard_ids_sorted[src_idx]
            shard_kgs[sid].add_relationship(
                relationship_type=rel.type,
                source=rel.source_id,
                target=rel.target_id,
                properties=dict(rel.properties) if rel.properties is not None else None,
                confidence=getattr(rel, "confidence", 1.0),
                source_text=getattr(rel, "source_text", None),
            )

    if include_relationships == "source_shard":
        # Compute adjacency overrides without mutating shard KGs with cross-shard
        # relationships (which may violate endpoint validation).
        outgoing_by_shard: dict[str, dict[str, list]] = {sid: {} for sid in shard_ids_sorted}
        incoming_by_shard: dict[str, dict[str, list]] = {sid: {} for sid in shard_ids_sorted}

        for rel in kg.relationships.values():
            src_idx = stable_shard_index(rel.source_id, num_shards=num_shards)
            tgt_idx = stable_shard_index(rel.target_id, num_shards=num_shards)
            src_sid = shard_ids_sorted[src_idx]
            tgt_sid = shard_ids_sorted[tgt_idx]

            outgoing_by_shard[src_sid].setdefault(str(rel.source_id), []).append(rel)
            incoming_by_shard[tgt_sid].setdefault(str(rel.target_id), []).append(rel)

        for sid in shard_ids_sorted:
            # Attach overrides used only by the publisher for adjacency index
            # generation. These are intentionally private attributes.
            setattr(shard_kgs[sid], "_adj_outgoing_override", outgoing_by_shard[sid])
            setattr(shard_kgs[sid], "_adj_incoming_override", incoming_by_shard[sid])

    report = ShardingReport(
        num_shards=num_shards,
        shard_ids_sorted=list(shard_ids_sorted),
        entity_counts={sid: len(skg.entities) for sid, skg in shard_kgs.items()},
        relationship_counts={sid: len(skg.relationships) for sid, skg in shard_kgs.items()},
    )

    return shard_kgs, report


def _entity_types_in_shard(kg: IPLDKnowledgeGraph) -> list[str]:
    types = {e.type for e in kg.entities.values() if getattr(e, "type", None)}
    return sorted(types)


def _build_entity_headers_index(kg: IPLDKnowledgeGraph) -> dict[str, dict]:
    # JSON-friendly mapping: entity_id -> {type,name,cid,properties}
    headers: dict[str, dict] = {}
    for ent in kg.entities.values():
        headers[str(ent.id)] = {
            "type": getattr(ent, "type", None),
            "name": getattr(ent, "name", None),
            "cid": getattr(ent, "cid", None),
            "properties": dict(ent.properties) if getattr(ent, "properties", None) is not None else None,
        }
    return headers


def _build_type_index(kg: IPLDKnowledgeGraph) -> dict[str, list[str]]:
    idx: dict[str, list[str]] = {}
    for ent in kg.entities.values():
        et = getattr(ent, "type", None)
        if not et:
            continue
        idx.setdefault(str(et), []).append(str(ent.id))
    for t in list(idx.keys()):
        idx[t] = sorted(set(idx[t]))
    return idx


def _auto_prefix_len(
    num_items: int,
    *,
    target_bucket_size: int = 5000,
    max_prefix_len: int = 8,
) -> int:
    """Choose a sha256-hex prefix length for bucketed JSON indexes.

    Returns 0 when bucketing is unnecessary.
    """

    n = int(num_items)
    target = max(1, int(target_bucket_size))
    if n <= target:
        return 0

    buckets_needed = int(math.ceil(n / float(target)))
    prefix_len = 0
    capacity = 1
    while capacity < buckets_needed and prefix_len < int(max_prefix_len):
        prefix_len += 1
        capacity *= 16  # hex prefix -> 16^prefix_len buckets
    return max(1, prefix_len)


def publish_sharded_graph_to_ipfs(
    shards: Mapping[str, IPLDKnowledgeGraph] | Sequence[IPLDKnowledgeGraph],
    *,
    pin: bool = True,
    backend: str | None = None,
    backend_instance: ipfs_router.IPFSBackend | None = None,
    shard_ids: Sequence[str] | None = None,
    validate_routing: bool = True,
    publish_adjacency_index: bool = False,
    compress_indexes: bool = False,
    type_index_page_size: int | None = None,
    neighbors_index_prefix_len: int = 0,
    headers_index_prefix_len: int = 0,
    index_bucket_target_size: int = 5000,
) -> PublishedShardedGraph:
    """Publish shard CARs + a JSON manifest to IPFS via ipfs_backend_router.

    This is intentionally a minimal v1 publisher intended for demos/benchmarks.

    Args:
        shards: Either a mapping of shard_id->KG, or a sequence of KGs.
        pin: Whether to pin the uploaded bytes.
        backend/backend_instance: Passed through to the router.
        shard_ids: If `shards` is a sequence, explicit shard IDs to assign.

    Returns:
        PublishedShardedGraph containing the manifest CID and parsed manifest.
    """

    if isinstance(shards, Mapping):
        shard_items = list(shards.items())
    else:
        if shard_ids is not None and len(shard_ids) != len(shards):
            raise ValueError("shard_ids length must match shards length")
        ids = list(shard_ids) if shard_ids is not None else [f"S{i}" for i in range(len(shards))]
        shard_items = list(zip(ids, list(shards)))

    shard_map = {str(sid): kg for sid, kg in shard_items}
    if validate_routing:
        validate_deterministic_shard_routing(shard_map)

    shard_infos: list[ShardInfo] = []

    def _maybe_compress(payload: bytes) -> bytes:
        return gzip.compress(payload) if compress_indexes else payload

    for shard_id, kg in shard_items:
        # Publish lightweight indexes first (small JSON blobs).
        headers_obj = _build_entity_headers_index(kg)
        headers_prefix_len = int(headers_index_prefix_len or 0)
        if headers_prefix_len < 0:
            headers_prefix_len = _auto_prefix_len(
                len(headers_obj),
                target_bucket_size=index_bucket_target_size,
            )
        if headers_prefix_len > 0:
            buckets: dict[str, dict[str, dict]] = {}
            for eid, header in headers_obj.items():
                digest = hashlib.sha256(eid.encode("utf-8", errors="strict")).hexdigest()
                bucket_key = digest[:headers_prefix_len]
                bucket = buckets.get(bucket_key)
                if bucket is None:
                    bucket = {}
                    buckets[bucket_key] = bucket
                bucket[eid] = header

            bucket_cids: dict[str, str] = {}
            for bucket_key, bucket_map in buckets.items():
                bucket_bytes = _maybe_compress(json.dumps(bucket_map).encode("utf-8"))
                bucket_cid = ipfs_router.add_bytes(
                    bucket_bytes,
                    pin=pin,
                    backend=backend,
                    backend_instance=backend_instance,
                )
                bucket_cids[str(bucket_key)] = str(bucket_cid)

            meta = {"v": 2, "prefix_len": headers_prefix_len, "buckets": bucket_cids}
            headers_bytes = _maybe_compress(json.dumps(meta).encode("utf-8"))
        else:
            headers_bytes = _maybe_compress(json.dumps(headers_obj).encode("utf-8"))

        headers_cid = ipfs_router.add_bytes(
            headers_bytes,
            pin=pin,
            backend=backend,
            backend_instance=backend_instance,
        )

        # Type index can be stored either as a single JSON blob (v1) or as a
        # paged meta-index (v2) referencing per-type page blocks.
        page_size = int(type_index_page_size) if type_index_page_size is not None else 0
        if page_size < 0:
            page_size = max(1, int(index_bucket_target_size))
        if page_size > 0:
            type_idx = _build_type_index(kg)
            types_to_pages: dict[str, list[str]] = {}
            for et, ids in type_idx.items():
                page_cids: list[str] = []
                for i in range(0, len(ids), page_size):
                    page_ids = ids[i : i + page_size]
                    page_bytes = _maybe_compress(json.dumps(page_ids).encode("utf-8"))
                    page_cid = ipfs_router.add_bytes(
                        page_bytes,
                        pin=pin,
                        backend=backend,
                        backend_instance=backend_instance,
                    )
                    page_cids.append(str(page_cid))
                types_to_pages[str(et)] = page_cids

            meta = {"v": 2, "page_size": page_size, "types": types_to_pages}
            type_index_bytes = _maybe_compress(json.dumps(meta).encode("utf-8"))
        else:
            type_index_bytes = _maybe_compress(json.dumps(_build_type_index(kg)).encode("utf-8"))

        type_index_cid = ipfs_router.add_bytes(
            type_index_bytes,
            pin=pin,
            backend=backend,
            backend_instance=backend_instance,
        )

        neighbors_index_cid = None
        if publish_adjacency_index:
            # Store adjacency per-entity to avoid one huge shard index blob.
            entity_to_adj_cid: dict[str, str] = {}
            # Prefer using the graph's internal relationship ID indexes to avoid
            # repeated method calls for large graphs. Fall back to
            # get_entity_relationships if indexes aren't available.
            src_index = getattr(kg, "_source_relationships", None)
            tgt_index = getattr(kg, "_target_relationships", None)
            outgoing_override = getattr(kg, "_adj_outgoing_override", None)
            incoming_override = getattr(kg, "_adj_incoming_override", None)

            def _rel_dict(r) -> dict:
                return {
                    "relationship_type": r.type,
                    "source_id": r.source_id,
                    "target_id": r.target_id,
                    "relationship_id": r.id,
                }

            for ent_id in list(kg.entities.keys()):
                outgoing: list = []
                incoming: list = []

                # If sharding provided explicit adjacency maps (e.g. cross-shard
                # edges), prefer those.
                if isinstance(outgoing_override, dict) or isinstance(incoming_override, dict):
                    olist = outgoing_override.get(ent_id, []) if isinstance(outgoing_override, dict) else []
                    ilist = incoming_override.get(ent_id, []) if isinstance(incoming_override, dict) else []
                    outgoing = [_rel_dict(r) for r in sorted(olist, key=lambda r: getattr(r, "id", ""))]
                    incoming = [_rel_dict(r) for r in sorted(ilist, key=lambda r: getattr(r, "id", ""))]
                elif isinstance(src_index, dict) and isinstance(tgt_index, dict):
                    out_ids = src_index.get(ent_id, set())
                    in_ids = tgt_index.get(ent_id, set())

                    # Emit stable ordering for deterministic pagination.
                    for rel_id in sorted(out_ids):
                        rel = kg.relationships.get(rel_id)
                        if rel is not None:
                            outgoing.append(_rel_dict(rel))
                    for rel_id in sorted(in_ids):
                        rel = kg.relationships.get(rel_id)
                        if rel is not None:
                            incoming.append(_rel_dict(rel))

                else:
                    outgoing = [_rel_dict(r) for r in kg.get_entity_relationships(ent_id, direction="outgoing", relationship_types=None)]
                    incoming = [_rel_dict(r) for r in kg.get_entity_relationships(ent_id, direction="incoming", relationship_types=None)]

                adj_obj = {
                    "v": 1,
                    "outgoing": outgoing,
                    "incoming": incoming,
                }
                adj_bytes = _maybe_compress(json.dumps(adj_obj).encode("utf-8"))
                adj_cid = ipfs_router.add_bytes(
                    adj_bytes,
                    pin=pin,
                    backend=backend,
                    backend_instance=backend_instance,
                )
                entity_to_adj_cid[str(ent_id)] = str(adj_cid)

            prefix_len = int(neighbors_index_prefix_len or 0)
            if prefix_len < 0:
                prefix_len = _auto_prefix_len(
                    len(entity_to_adj_cid),
                    target_bucket_size=index_bucket_target_size,
                )
            if prefix_len > 0:
                buckets: dict[str, dict[str, str]] = {}
                for eid, cid in entity_to_adj_cid.items():
                    digest = hashlib.sha256(eid.encode("utf-8", errors="strict")).hexdigest()
                    bucket_key = digest[:prefix_len]
                    bucket = buckets.get(bucket_key)
                    if bucket is None:
                        bucket = {}
                        buckets[bucket_key] = bucket
                    bucket[eid] = cid

                bucket_cids: dict[str, str] = {}
                for bucket_key, bucket_map in buckets.items():
                    bucket_bytes = _maybe_compress(json.dumps(bucket_map).encode("utf-8"))
                    bucket_cid = ipfs_router.add_bytes(
                        bucket_bytes,
                        pin=pin,
                        backend=backend,
                        backend_instance=backend_instance,
                    )
                    bucket_cids[str(bucket_key)] = str(bucket_cid)

                meta = {"v": 2, "prefix_len": prefix_len, "buckets": bucket_cids}
                neighbors_index_bytes = _maybe_compress(json.dumps(meta).encode("utf-8"))
            else:
                neighbors_index_bytes = _maybe_compress(json.dumps(entity_to_adj_cid).encode("utf-8"))

            neighbors_index_cid = ipfs_router.add_bytes(
                neighbors_index_bytes,
                pin=pin,
                backend=backend,
                backend_instance=backend_instance,
            )

        with tempfile.NamedTemporaryFile(suffix=".car", delete=True) as handle:
            kg.export_to_car(handle.name)
            car_bytes = open(handle.name, "rb").read()

        car_cid = ipfs_router.add_bytes(
            car_bytes,
            pin=pin,
            backend=backend,
            backend_instance=backend_instance,
        )

        shard_infos.append(
            ShardInfo(
                shard_id=str(shard_id),
                car_cid=str(car_cid),
                approx_bytes=len(car_bytes),
                headers_cid=str(headers_cid),
                type_index_cid=str(type_index_cid),
                neighbors_index_cid=str(neighbors_index_cid) if neighbors_index_cid else None,
                entity_type_bloom=build_type_bloom(_entity_types_in_shard(kg)),
            )
        )

    manifest = GraphShardManifest(shards=shard_infos)
    manifest_bytes = json.dumps(manifest.to_dict()).encode("utf-8")
    manifest_cid = ipfs_router.add_bytes(
        manifest_bytes,
        pin=pin,
        backend=backend,
        backend_instance=backend_instance,
    )

    return PublishedShardedGraph(manifest_cid=str(manifest_cid), manifest=manifest)


def publish_knowledge_graph_sharded_to_ipfs(
    kg: IPLDKnowledgeGraph,
    *,
    num_shards: int,
    shard_ids: Sequence[str] | None = None,
    pin: bool = True,
    backend: str | None = None,
    backend_instance: ipfs_router.IPFSBackend | None = None,
    include_relationships: str = "intra_only",
    publish_adjacency_index: bool = False,
    compress_indexes: bool = False,
    type_index_page_size: int | None = None,
    neighbors_index_prefix_len: int = 0,
    headers_index_prefix_len: int = 0,
    index_bucket_target_size: int = 5000,
) -> PublishedShardedGraph:
    """Deterministically shard a KG, then publish shard CARs + manifest via router.

    This is the safest v1 path because it guarantees routing-consistent shards.
    """

    shard_kgs, _report = shard_knowledge_graph_deterministic(
        kg,
        num_shards=num_shards,
        shard_ids=shard_ids,
        include_relationships=include_relationships,
    )
    return publish_sharded_graph_to_ipfs(
        shard_kgs,
        pin=pin,
        backend=backend,
        backend_instance=backend_instance,
        validate_routing=True,
        publish_adjacency_index=publish_adjacency_index,
        compress_indexes=compress_indexes,
        type_index_page_size=type_index_page_size,
        neighbors_index_prefix_len=neighbors_index_prefix_len,
        headers_index_prefix_len=headers_index_prefix_len,
        index_bucket_target_size=index_bucket_target_size,
    )
