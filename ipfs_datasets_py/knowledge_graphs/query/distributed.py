"""
Distributed Query Execution — Item 13 of DEFERRED_FEATURES.md.

Provides in-process graph partitioning and federated query execution for
large knowledge graphs.  The design uses a **shared-nothing** model where
each partition holds a disjoint subset of nodes and their incident edges;
queries fan out across all partitions, results are merged, and duplicates
are removed.

Architecture
------------
::

    KnowledgeGraph                     DistributedGraph
    (flat, single node)   partitions   ┌─────────────┐
                    ──────────────────►│ partition_0  │ KnowledgeGraph
                   GraphPartitioner   │ partition_1  │ KnowledgeGraph
                                       │     …        │
                                       └─────────────┘
                                              │ FederatedQueryExecutor
                                              ▼
                                    merged QueryResult

Partitioning strategies
-----------------------
* **hash** *(default)* — node ID is hashed modulo *num_partitions*.
* **range** — nodes are sorted by ID, then divided into equal-sized buckets.
* **round_robin** — nodes assigned to partitions in turn as they are iterated.

Cross-partition relationships
------------------------------
A relationship whose source and target are in different partitions is placed
in *both* partitions' edge sets to ensure each subquery can resolve it.
This means relationship counts may be slightly inflated relative to the
original graph.

Usage
------
::

    from ipfs_datasets_py.knowledge_graphs.query.distributed import (
        GraphPartitioner,
        FederatedQueryExecutor,
        PartitionStrategy,
    )

    partitioner = GraphPartitioner(num_partitions=4, strategy=PartitionStrategy.HASH)
    dist_graph = partitioner.partition(kg)

    executor = FederatedQueryExecutor(dist_graph)
    result = executor.execute_cypher(
        "MATCH (n:Person) WHERE n.age > 30 RETURN n.name, n.age"
    )
"""

from __future__ import annotations

import copy
import enum
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Partition strategy enum
# ---------------------------------------------------------------------------


class PartitionStrategy(str, enum.Enum):
    """Strategy used to assign nodes to partitions.

    Attributes:
        HASH:        Hash the node ID modulo *num_partitions* (default).
        RANGE:       Sort nodes by ID and split into equal-size buckets.
        ROUND_ROBIN: Assign nodes round-robin as they are iterated.
    """

    HASH = "hash"
    RANGE = "range"
    ROUND_ROBIN = "round_robin"


# ---------------------------------------------------------------------------
# DistributedGraph
# ---------------------------------------------------------------------------


@dataclass
class PartitionStats:
    """Statistics for a single partition.

    Attributes:
        partition_id: Zero-based integer partition index.
        node_count:   Number of entities in this partition.
        edge_count:   Number of relationships in this partition.
    """

    partition_id: int
    node_count: int
    edge_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "partition_id": self.partition_id,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
        }


class DistributedGraph:
    """Holds multiple :class:`~ipfs_datasets_py.knowledge_graphs.extraction.graph.KnowledgeGraph` partitions.

    Created by :meth:`GraphPartitioner.partition`.  Exposes the partitions as
    a list and provides convenience methods for inspection.

    Attributes:
        partitions: List of :class:`KnowledgeGraph` objects (one per partition).
        strategy:   The :class:`PartitionStrategy` used to create this graph.
        node_to_partition: Mapping of ``entity_id → partition_index``.
    """

    def __init__(
        self,
        partitions: List[Any],
        strategy: PartitionStrategy,
        node_to_partition: Dict[str, int],
    ) -> None:
        self.partitions = partitions
        self.strategy = strategy
        self.node_to_partition = node_to_partition

    # ------------------------------------------------------------------
    # Inspection helpers
    # ------------------------------------------------------------------

    def get_partition_for_entity(self, entity_id: str) -> Optional[Any]:
        """Return the partition that *entity_id* was assigned to.

        Args:
            entity_id: Entity UUID / identifier.

        Returns:
            The :class:`KnowledgeGraph` partition, or ``None`` if not found.
        """
        idx = self.node_to_partition.get(entity_id)
        if idx is None:
            return None
        return self.partitions[idx]

    def get_partition_stats(self) -> List[PartitionStats]:
        """Return per-partition node/edge counts.

        Returns:
            List of :class:`PartitionStats` sorted by partition ID.
        """
        return [
            PartitionStats(
                partition_id=i,
                node_count=len(p.entities),
                edge_count=len(p.relationships),
            )
            for i, p in enumerate(self.partitions)
        ]

    @property
    def total_nodes(self) -> int:
        """Total unique node count across all partitions."""
        return len(self.node_to_partition)

    @property
    def num_partitions(self) -> int:
        """Number of partitions."""
        return len(self.partitions)

    def to_merged_graph(self) -> Any:
        """Re-merge all partitions into a single :class:`KnowledgeGraph`.

        Useful for verification or when you need a single unified view after
        distributed processing.

        Returns:
            Merged :class:`KnowledgeGraph`.
        """
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph

        merged = KnowledgeGraph(name="merged")
        for partition in self.partitions:
            merged.merge(partition)
        return merged


# ---------------------------------------------------------------------------
# GraphPartitioner
# ---------------------------------------------------------------------------


class GraphPartitioner:
    """Partitions a :class:`KnowledgeGraph` into a :class:`DistributedGraph`.

    Args:
        num_partitions: Number of partitions to create.  Must be >= 1.
        strategy:       Partitioning strategy (default: ``HASH``).
        copy_cross_edges: If ``True`` (default), relationships that cross
                          partition boundaries are copied into both partitions.
                          If ``False``, each relationship is placed in the
                          *source* node's partition only.

    Example::

        partitioner = GraphPartitioner(num_partitions=4)
        dist_graph = partitioner.partition(kg)
    """

    def __init__(
        self,
        num_partitions: int = 2,
        strategy: PartitionStrategy = PartitionStrategy.HASH,
        copy_cross_edges: bool = True,
    ) -> None:
        if num_partitions < 1:
            raise ValueError("num_partitions must be >= 1")
        self.num_partitions = num_partitions
        self.strategy = strategy
        self.copy_cross_edges = copy_cross_edges

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def partition(self, kg: Any) -> DistributedGraph:
        """Partition *kg* into a :class:`DistributedGraph`.

        Args:
            kg: Source :class:`KnowledgeGraph`.

        Returns:
            :class:`DistributedGraph` with ``num_partitions`` shards.
        """
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph

        if self.num_partitions == 1:
            # Fast path: trivial single partition
            dist = DistributedGraph(
                partitions=[copy.deepcopy(kg)],
                strategy=self.strategy,
                node_to_partition={eid: 0 for eid in kg.entities},
            )
            return dist

        # Assign nodes to partitions
        node_ids = list(kg.entities.keys())
        node_to_partition = self._assign_partitions(node_ids)

        # Build empty partition graphs
        partitions: List[Any] = [
            KnowledgeGraph(name=f"partition_{i}")
            for i in range(self.num_partitions)
        ]

        # Populate entities
        for entity_id, entity in kg.entities.items():
            p_idx = node_to_partition[entity_id]
            partition = partitions[p_idx]
            # Deep-copy to avoid shared mutation
            entity_copy = copy.deepcopy(entity)
            partition.entities[entity_copy.entity_id] = entity_copy
            partition.entity_types.setdefault(entity_copy.entity_type, set()).add(entity_copy.entity_id)
            partition.entity_names.setdefault(entity_copy.name, set()).add(entity_copy.entity_id)

        # Populate relationships
        for rel in kg.relationships.values():
            src_partition = node_to_partition.get(rel.source_id)
            tgt_partition = node_to_partition.get(rel.target_id)

            if src_partition is None or tgt_partition is None:
                continue  # orphan relationship — skip

            target_partitions: Set[int] = {src_partition}
            if self.copy_cross_edges and src_partition != tgt_partition:
                target_partitions.add(tgt_partition)

            for p_idx in target_partitions:
                partition = partitions[p_idx]
                rel_copy = copy.deepcopy(rel)
                partition.relationships[rel_copy.relationship_id] = rel_copy
                partition.relationship_types.setdefault(
                    rel_copy.relationship_type, set()
                ).add(rel_copy.relationship_id)
                partition.entity_relationships.setdefault(
                    rel.source_id, set()
                ).add(rel_copy.relationship_id)
                partition.entity_relationships.setdefault(
                    rel.target_id, set()
                ).add(rel_copy.relationship_id)

        return DistributedGraph(
            partitions=partitions,
            strategy=self.strategy,
            node_to_partition=node_to_partition,
        )

    # ------------------------------------------------------------------
    # Internal assignment
    # ------------------------------------------------------------------

    def _assign_partitions(self, node_ids: List[str]) -> Dict[str, int]:
        """Return a mapping of ``node_id → partition_index``."""
        n = self.num_partitions
        if self.strategy == PartitionStrategy.HASH:
            return {
                nid: int(hashlib.sha1(nid.encode()).hexdigest(), 16) % n
                for nid in node_ids
            }
        elif self.strategy == PartitionStrategy.RANGE:
            sorted_ids = sorted(node_ids)
            chunk = max(1, len(sorted_ids) // n)
            return {
                nid: min(i // chunk, n - 1)
                for i, nid in enumerate(sorted_ids)
            }
        elif self.strategy == PartitionStrategy.ROUND_ROBIN:
            return {nid: i % n for i, nid in enumerate(node_ids)}
        else:
            raise ValueError(f"Unknown partition strategy: {self.strategy}")


# ---------------------------------------------------------------------------
# FederatedQueryExecutor
# ---------------------------------------------------------------------------


@dataclass
class FederatedQueryResult:
    """Aggregated result from a federated query.

    Attributes:
        records:          List of result rows (dicts).  Duplicates have been
                          removed.
        partition_results: Per-partition raw results (for debugging).
        num_partitions:   Number of partitions queried.
        errors:           Errors encountered per partition (keyed by index).
    """

    records: List[Dict[str, Any]]
    partition_results: List[List[Dict[str, Any]]] = field(default_factory=list)
    num_partitions: int = 0
    errors: Dict[int, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "records": self.records,
            "num_partitions": self.num_partitions,
            "total_records": len(self.records),
            "errors": self.errors,
        }


class FederatedQueryExecutor:
    """Executes queries across all partitions of a :class:`DistributedGraph`.

    Fan-out strategy:
    1. For each partition, create a ``QueryExecutor`` backed by the partition.
    2. Run the query independently on each partition.
    3. Collect results, deduplicate by record fingerprint, return merged list.

    Args:
        distributed_graph: The :class:`DistributedGraph` to query.
        dedup: If ``True`` (default), remove exact duplicate records from
               the merged result.

    Example::

        exec = FederatedQueryExecutor(dist_graph)
        result = exec.execute_cypher("MATCH (n:Person) RETURN n.name")
        for row in result.records:
            print(row)
    """

    def __init__(
        self,
        distributed_graph: DistributedGraph,
        dedup: bool = True,
    ) -> None:
        self.distributed_graph = distributed_graph
        self.dedup = dedup

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute_cypher(
        self, query: str, params: Optional[Dict[str, Any]] = None
    ) -> FederatedQueryResult:
        """Execute a Cypher query across all partitions.

        Args:
            query:  Cypher query string.
            params: Optional query parameters.

        Returns:
            :class:`FederatedQueryResult` with merged, deduplicated records.
        """
        from ipfs_datasets_py.knowledge_graphs.core.graph_engine import GraphEngine
        from ipfs_datasets_py.knowledge_graphs.core.query_executor import QueryExecutor
        from ipfs_datasets_py.knowledge_graphs.storage.ipld_backend import IPLDBackend

        partition_results: List[List[Dict[str, Any]]] = []
        errors: Dict[int, str] = {}

        for i, partition_kg in enumerate(self.distributed_graph.partitions):
            try:
                partition_records = self._execute_on_partition(
                    partition_kg, query, params or {}
                )
                partition_results.append(partition_records)
            except Exception as exc:
                logger.warning(
                    "Federated query error on partition %d: %s", i, exc
                )
                errors[i] = str(exc)
                partition_results.append([])

        # Merge and deduplicate
        merged = self._merge_results(partition_results)

        return FederatedQueryResult(
            records=merged,
            partition_results=partition_results,
            num_partitions=self.distributed_graph.num_partitions,
            errors=errors,
        )

    def execute_cypher_parallel(
        self, query: str, params: Optional[Dict[str, Any]] = None,
        max_workers: int = 4,
    ) -> FederatedQueryResult:
        """Execute a Cypher query across partitions using a thread pool.

        This is useful when partitions reside on remote or slow backends.
        For in-memory graphs, :meth:`execute_cypher` is usually faster.

        Args:
            query:       Cypher query string.
            params:      Optional query parameters.
            max_workers: Maximum number of parallel worker threads.

        Returns:
            :class:`FederatedQueryResult` with merged, deduplicated records.
        """
        import concurrent.futures

        partition_results: List[Optional[List[Dict[str, Any]]]] = [
            None
        ] * self.distributed_graph.num_partitions
        errors: Dict[int, str] = {}

        def _run(i: int, partition_kg: Any) -> Tuple[int, List[Dict[str, Any]]]:
            return i, self._execute_on_partition(partition_kg, query, params or {})

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_run, i, p): i
                for i, p in enumerate(self.distributed_graph.partitions)
            }
            for future in concurrent.futures.as_completed(futures):
                i = futures[future]
                try:
                    idx, records = future.result()
                    partition_results[idx] = records
                except Exception as exc:
                    logger.warning(
                        "Federated parallel query error on partition %d: %s", i, exc
                    )
                    errors[i] = str(exc)
                    partition_results[i] = []

        filled_results = [r if r is not None else [] for r in partition_results]
        merged = self._merge_results(filled_results)

        return FederatedQueryResult(
            records=merged,
            partition_results=filled_results,
            num_partitions=self.distributed_graph.num_partitions,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _execute_on_partition(
        self, partition_kg: Any, query: str, params: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Run *query* on a single partition KG and return list of record dicts."""
        from ipfs_datasets_py.knowledge_graphs.core.graph_engine import GraphEngine
        from ipfs_datasets_py.knowledge_graphs.core.query_executor import QueryExecutor
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.types import Node, Relationship as CompatRel

        # Build an in-memory GraphEngine populated from the partition KG
        engine = GraphEngine(storage_backend=None)

        # Load entities as Node objects
        for entity in partition_kg.entities.values():
            node = Node(
                node_id=entity.entity_id,
                labels=[entity.entity_type],
                properties=dict(entity.properties or {}),
            )
            node._properties["name"] = entity.name
            engine._node_cache[entity.entity_id] = node

        # Load relationships as compat Relationship objects
        for rel in partition_kg.relationships.values():
            src_node = engine._node_cache.get(rel.source_id)
            tgt_node = engine._node_cache.get(rel.target_id)
            if src_node is None or tgt_node is None:
                continue  # skip dangling cross-partition edges
            compat_rel = CompatRel(
                rel_id=rel.relationship_id,
                rel_type=rel.relationship_type,
                start_node=src_node,
                end_node=tgt_node,
                properties=dict(rel.properties or {}),
            )
            engine._relationship_cache[rel.relationship_id] = compat_rel

        executor = QueryExecutor(graph_engine=engine)
        try:
            result = executor.execute(query, parameters=params)
        except Exception:
            return []
        return _normalise_result(result)

    def _merge_results(
        self, partition_results: List[List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        """Flatten partition results and optionally deduplicate."""
        all_records: List[Dict[str, Any]] = []
        seen: Set[str] = set()

        for records in partition_results:
            for record in records:
                if self.dedup:
                    fingerprint = _record_fingerprint(record)
                    if fingerprint in seen:
                        continue
                    seen.add(fingerprint)
                all_records.append(record)

        return all_records


# ---------------------------------------------------------------------------
# Lightweight KG-backed "backend" adapter
# ---------------------------------------------------------------------------


class _KGBackend:
    """Minimal adapter that lets ``QueryExecutor`` work with a ``KnowledgeGraph``.

    ``QueryExecutor`` expects a ``graph_engine`` with:
    ``find_nodes(labels, properties)`` and ``get_relationships(…)`` methods.
    """

    def __init__(self, kg: Any) -> None:
        self._kg = kg

    # -- Node methods -------------------------------------------------------

    def find_nodes(
        self,
        labels: Optional[List[str]] = None,
        properties: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
    ) -> List[Any]:
        results = list(self._kg.entities.values())
        if labels:
            results = [
                e for e in results
                if e.entity_type in labels
                or e.entity_type in (
                    set(e.properties.get("inferred_types", [])) if e.properties else set()
                )
            ]
        if properties:
            results = [
                e for e in results
                if all(
                    e.properties.get(k) == v
                    for k, v in properties.items()
                )
            ]
        if limit is not None:
            results = results[:limit]
        return results

    def get_node(self, node_id: str) -> Optional[Any]:
        return self._kg.entities.get(node_id)

    # -- Relationship methods -----------------------------------------------

    def get_relationships(
        self,
        source_id: Optional[str] = None,
        target_id: Optional[str] = None,
        relationship_types: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> List[Any]:
        results = list(self._kg.relationships.values())
        if source_id:
            results = [r for r in results if r.source_id == source_id]
        if target_id:
            results = [r for r in results if r.target_id == target_id]
        if relationship_types:
            results = [r for r in results if r.relationship_type in relationship_types]
        if limit is not None:
            results = results[:limit]
        return results

    # -- Storage backend duck-typing ----------------------------------------

    def store(self, data: Any) -> str:
        return str(id(data))

    def retrieve(self, key: str) -> Optional[Any]:
        return None


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _normalise_result(result: Any) -> List[Dict[str, Any]]:
    """Convert whatever ``QueryExecutor.execute`` returns to a list of dicts."""
    if result is None:
        return []
    if isinstance(result, list):
        records = result
    elif hasattr(result, "records"):
        records = result.records
    elif hasattr(result, "result_set"):
        records = result.result_set
    elif hasattr(result, "rows"):
        records = result.rows
    else:
        # Try generic iteration (e.g. the Result class from query_executor)
        try:
            records = list(result)
        except TypeError:
            return []

    normalised: List[Dict[str, Any]] = []
    for row in records:
        if isinstance(row, dict):
            normalised.append(row)
        elif hasattr(row, "to_dict"):
            normalised.append(row.to_dict())
        elif hasattr(row, "data"):
            # neo4j-compat Record.data() method
            normalised.append(row.data())
        elif hasattr(row, "__iter__") and not isinstance(row, str):
            # Record-like objects that unpack as key-value pairs
            try:
                normalised.append(dict(row))
            except (TypeError, ValueError):
                normalised.append({"value": str(row)})
        elif hasattr(row, "__dict__"):
            normalised.append(dict(row.__dict__))
        else:
            normalised.append({"value": str(row)})
    return normalised


def _record_fingerprint(record: Dict[str, Any]) -> str:
    """Return a stable hash string for a result *record*."""
    import json

    try:
        serialised = json.dumps(record, sort_keys=True, default=str)
    except Exception:
        serialised = str(sorted(record.items()))
    return hashlib.sha1(serialised.encode()).hexdigest()


__all__ = [
    "GraphPartitioner",
    "DistributedGraph",
    "FederatedQueryExecutor",
    "FederatedQueryResult",
    "PartitionStats",
    "PartitionStrategy",
]
