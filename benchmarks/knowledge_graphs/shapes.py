"""Deterministic graph shape generation for load workloads (KGP-029).

Shapes are fully determined by ``(seed, node_count, edge_count, shape)``.
The same inputs always yield identical entity/relationship IDs, topology,
and content fingerprint so receipts and baseline comparisons are reproducible.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

JSONDict = Dict[str, Any]

# Named topology families used by profiles and corpus replays.
SHAPE_FAMILIES = (
    "star",
    "path",
    "ring",
    "grid",
    "power_law",
    "bipartite",
    "clustered",
    "mixed",
)

ENTITY_TYPES = ("Person", "Organization", "Document", "Concept", "Event")
REL_TYPES = ("KNOWS", "WORKS_AT", "MENTIONS", "RELATED_TO", "PART_OF", "CAUSED")


@dataclass(frozen=True, slots=True)
class GraphShapeSpec:
    """Specification for a deterministic synthetic graph."""

    seed: int
    node_count: int
    edge_count: int
    shape: str = "mixed"
    id_prefix: str = "n"
    tenant: str = "load"
    graph_id: str = "shape"
    shard_count: int = 1

    def __post_init__(self) -> None:
        if self.node_count < 0:
            raise ValueError("node_count must be >= 0")
        if self.edge_count < 0:
            raise ValueError("edge_count must be >= 0")
        if self.shard_count < 1:
            raise ValueError("shard_count must be >= 1")
        if self.shape not in SHAPE_FAMILIES:
            raise ValueError(
                f"unknown shape {self.shape!r}; expected one of {SHAPE_FAMILIES}"
            )


@dataclass(frozen=True, slots=True)
class DeterministicGraph:
    """Materialized deterministic graph with stable IDs and shard mapping."""

    spec: GraphShapeSpec
    entities: Tuple[JSONDict, ...]
    relationships: Tuple[JSONDict, ...]
    shard_map: Mapping[str, int] = field(default_factory=dict)
    fingerprint: str = ""

    @property
    def node_count(self) -> int:
        return len(self.entities)

    @property
    def edge_count(self) -> int:
        return len(self.relationships)

    def to_payload(self) -> JSONDict:
        return {
            "entities": [dict(e) for e in self.entities],
            "relationships": [dict(r) for r in self.relationships],
        }

    def shard_fan_out(self) -> JSONDict:
        """Count entities and edges per logical shard (deterministic routing)."""
        per_shard: Dict[str, Dict[str, int]] = {
            str(i): {"entities": 0, "relationships": 0}
            for i in range(self.spec.shard_count)
        }
        for e in self.entities:
            sid = str(self.shard_map.get(str(e["id"]), 0))
            per_shard.setdefault(sid, {"entities": 0, "relationships": 0})
            per_shard[sid]["entities"] += 1
        for r in self.relationships:
            # Edge lives on the source entity's shard.
            src = str(r.get("source") or r.get("source_id") or "")
            sid = str(self.shard_map.get(src, 0))
            per_shard.setdefault(sid, {"entities": 0, "relationships": 0})
            per_shard[sid]["relationships"] += 1
        distinct = sum(1 for v in per_shard.values() if v["entities"] or v["relationships"])
        return {
            "shard_count": self.spec.shard_count,
            "distinct_shards_touched": distinct,
            "per_shard": per_shard,
            "cross_shard_edges": _count_cross_shard(self.relationships, self.shard_map),
        }


def _entity_id(prefix: str, index: int) -> str:
    return f"{prefix}{index:08d}"


def _rel_id(prefix: str, index: int) -> str:
    return f"r{prefix}{index:08d}"


def _shard_for(entity_id: str, shard_count: int) -> int:
    if shard_count <= 1:
        return 0
    digest = hashlib.sha256(entity_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % shard_count


def _count_cross_shard(
    relationships: Sequence[Mapping[str, Any]],
    shard_map: Mapping[str, int],
) -> int:
    n = 0
    for r in relationships:
        src = str(r.get("source") or r.get("source_id") or "")
        tgt = str(r.get("target") or r.get("target_id") or "")
        if shard_map.get(src, 0) != shard_map.get(tgt, 0):
            n += 1
    return n


def _pair_edges(
    rng: random.Random,
    node_ids: Sequence[str],
    edge_count: int,
    shape: str,
    resource_check: Optional[Callable[[], object]] = None,
) -> List[Tuple[str, str]]:
    """Return ordered (source, target) pairs for the requested topology."""
    n = len(node_ids)
    if n == 0 or edge_count == 0:
        return []
    pairs: List[Tuple[str, str]] = []
    seen: set[Tuple[str, str]] = set()

    def add(a: str, b: str) -> bool:
        if a == b:
            return False
        key = (a, b)
        if key in seen:
            return False
        seen.add(key)
        pairs.append(key)
        return True

    def check_resource(index: int) -> None:
        if resource_check is not None and index % 10_000 == 0:
            resource_check()

    if shape == "path":
        for i in range(min(edge_count, n - 1)):
            add(node_ids[i], node_ids[i + 1])
    elif shape == "ring":
        for i in range(min(edge_count, n)):
            add(node_ids[i], node_ids[(i + 1) % n])
    elif shape == "star":
        hub = node_ids[0]
        for i in range(1, n):
            if len(pairs) >= edge_count:
                break
            add(hub, node_ids[i])
    elif shape == "grid":
        # Approximate square grid: connect right and down neighbors.
        side = max(1, int(n**0.5))
        for i in range(n):
            if len(pairs) >= edge_count:
                break
            row, col = divmod(i, side)
            right = row * side + (col + 1)
            down = (row + 1) * side + col
            if col + 1 < side and right < n:
                add(node_ids[i], node_ids[right])
            if len(pairs) >= edge_count:
                break
            if down < n:
                add(node_ids[i], node_ids[down])
    elif shape == "bipartite":
        mid = max(1, n // 2)
        left = node_ids[:mid]
        right = node_ids[mid:] or node_ids[:1]
        # Cartesian product walk — every (left, right) pair is distinct.
        max_unique = len(left) * len(right)
        for i in range(min(edge_count, max_unique)):
            add(left[i % len(left)], right[(i // len(left)) % len(right)])
    elif shape == "power_law":
        # Prefer edges from lower-index "hub" nodes (Zipf-like).
        weights = [1.0 / (i + 1) for i in range(n)]
        total = sum(weights)
        cum = []
        acc = 0.0
        for w in weights:
            acc += w / total
            cum.append(acc)

        def pick() -> str:
            u = rng.random()
            for idx, c in enumerate(cum):
                if u <= c:
                    return node_ids[idx]
            return node_ids[-1]

        attempts = 0
        max_attempts = max(edge_count * 40, n * n)
        while len(pairs) < edge_count and attempts < max_attempts:
            attempts += 1
            check_resource(attempts)
            a, b = pick(), pick()
            add(a, b)
    elif shape == "clustered":
        # Clusters of ~sqrt(n) with sparse bridges.
        cluster_size = max(2, int(n**0.5))
        clusters = [
            node_ids[i : i + cluster_size] for i in range(0, n, cluster_size)
        ]
        # Intra-cluster edges.
        for cluster in clusters:
            for i in range(len(cluster)):
                for j in range(i + 1, len(cluster)):
                    if len(pairs) >= edge_count:
                        break
                    add(cluster[i], cluster[j])
                if len(pairs) >= edge_count:
                    break
            if len(pairs) >= edge_count:
                break
        # Bridges between adjacent clusters.
        for ci in range(len(clusters) - 1):
            if len(pairs) >= edge_count:
                break
            add(clusters[ci][0], clusters[ci + 1][0])
    else:  # mixed — blend path backbone with random long-range edges
        for i in range(min(edge_count // 2, max(0, n - 1))):
            add(node_ids[i], node_ids[i + 1])
            attempts = 0
            max_attempts = max(edge_count * 40, n * n)
            while len(pairs) < edge_count and attempts < max_attempts:
                attempts += 1
                check_resource(attempts)
                a = node_ids[rng.randrange(n)]
                b = node_ids[rng.randrange(n)]
                add(a, b)

    # Pad with deterministic random edges if topology under-produced.
    # Bound attempts so large graphs cannot hang; prefer systematic walk
    # only when the complete digraph is small enough to enumerate.
    if len(pairs) < edge_count and n >= 2:
        max_digraph = n * (n - 1)
        if max_digraph <= 100_000:
            for i in range(n):
                for j in range(n):
                    if i == j:
                        continue
                    if len(pairs) >= edge_count:
                        break
                    add(node_ids[i], node_ids[j])
                if len(pairs) >= edge_count:
                    break
        else:
            attempts = 0
            max_attempts = min(edge_count * 40, max_digraph)
            while len(pairs) < edge_count and attempts < max_attempts:
                attempts += 1
                check_resource(attempts)
                a = node_ids[rng.randrange(n)]
                b = node_ids[rng.randrange(n)]
                add(a, b)

    return pairs[:edge_count]


def generate_graph(
    spec: GraphShapeSpec,
    *,
    resource_check: Optional[Callable[[], object]] = None,
) -> DeterministicGraph:
    """Generate a fully deterministic graph from *spec*."""
    if (
        resource_check is None
        and (spec.node_count >= 1_000_000 or spec.edge_count >= 10_000_000)
    ):
        # Direct callers receive the same fail-closed protection as the CLI.
        from .safety import synthetic_large_guard

        resource_check = synthetic_large_guard(Path.cwd()).check
    rng = random.Random(int(spec.seed))
    # Mix seed into type selection so different seeds diversify labels
    # even when topology structure is similar.
    type_rng = random.Random(int(spec.seed) ^ 0xA5A5_5A5A)

    node_ids = [_entity_id(spec.id_prefix, i) for i in range(spec.node_count)]
    entities: List[JSONDict] = []
    shard_map: Dict[str, int] = {}
    for i, nid in enumerate(node_ids):
        if resource_check is not None and i % 10_000 == 0:
            resource_check()
        etype = ENTITY_TYPES[type_rng.randrange(len(ENTITY_TYPES))]
        shard = _shard_for(nid, spec.shard_count)
        shard_map[nid] = shard
        entities.append(
            {
                "id": nid,
                "type": etype,
                "name": f"{etype.lower()}-{i}",
                "properties": {
                    "seed": spec.seed,
                    "index": i,
                    "shape": spec.shape,
                    "shard": shard,
                },
            }
        )

    pairs = _pair_edges(
        rng,
        node_ids,
        spec.edge_count,
        spec.shape,
        resource_check=resource_check,
    )
    relationships: List[JSONDict] = []
    for i, (src, tgt) in enumerate(pairs):
        if resource_check is not None and i % 10_000 == 0:
            resource_check()
        rtype = REL_TYPES[type_rng.randrange(len(REL_TYPES))]
        relationships.append(
            {
                "id": _rel_id(spec.id_prefix, i),
                "type": rtype,
                "source": src,
                "target": tgt,
                "properties": {
                    "seed": spec.seed,
                    "index": i,
                    "shape": spec.shape,
                },
            }
        )

    graph = DeterministicGraph(
        spec=spec,
        entities=tuple(entities),
        relationships=tuple(relationships),
        shard_map=dict(shard_map),
        fingerprint="",
    )
    if resource_check is not None:
        resource_check()
    fp = shape_fingerprint(graph, resource_check=resource_check)
    return DeterministicGraph(
        spec=spec,
        entities=graph.entities,
        relationships=graph.relationships,
        shard_map=graph.shard_map,
        fingerprint=fp,
    )


def shape_fingerprint(
    graph: DeterministicGraph,
    *,
    resource_check: Optional[Callable[[], object]] = None,
) -> str:
    """Content-addressed SHA-256 of the canonical graph payload + meta."""
    if resource_check is not None:
        resource_check()
    payload = {
        "seed": graph.spec.seed,
        "shape": graph.spec.shape,
        "node_count": graph.spec.node_count,
        "edge_count": graph.spec.edge_count,
        "shard_count": graph.spec.shard_count,
        "entities": [
            {"id": e["id"], "type": e["type"], "name": e["name"]}
            for e in graph.entities
        ],
        "relationships": [
            {
                "id": r["id"],
                "type": r["type"],
                "source": r["source"],
                "target": r["target"],
            }
            for r in graph.relationships
        ],
    }
    if resource_check is not None:
        resource_check()
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if resource_check is not None:
        resource_check()
    return hashlib.sha256(raw).hexdigest()


def batch_entities(
    entities: Sequence[Mapping[str, Any]], batch_size: int
) -> List[List[JSONDict]]:
    """Split entities into write batches of at most *batch_size*."""
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    items = [dict(e) for e in entities]
    return [items[i : i + batch_size] for i in range(0, len(items), batch_size)]


def batch_relationships(
    relationships: Sequence[Mapping[str, Any]], batch_size: int
) -> List[List[JSONDict]]:
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    items = [dict(r) for r in relationships]
    return [items[i : i + batch_size] for i in range(0, len(items), batch_size)]
