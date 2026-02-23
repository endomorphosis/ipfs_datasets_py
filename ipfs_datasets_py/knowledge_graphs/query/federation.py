"""
Federated Knowledge Graphs — deferred v4.0+ feature (§21 of DEFERRED_FEATURES.md).

Provides cross-graph entity resolution and unified query execution across
multiple independent :class:`~ipfs_datasets_py.knowledge_graphs.extraction.graph.KnowledgeGraph`
instances.

Unlike :mod:`~ipfs_datasets_py.knowledge_graphs.query.distributed`, which
partitions a *single* graph for scale, federation here joins *separate*
graphs that may have independently-managed entities that represent the same
real-world objects.

Architecture
------------

::

    kg_a (HR database)    ──┐
    kg_b (CRM database)   ──┤  FederatedKnowledgeGraph
    kg_c (Wiki extract)   ──┘
                               │
                               ▼  resolve_entities()
                          EntityMatch list (cross-graph pairs)
                               │
                               ▼  to_merged_graph()
                          single KnowledgeGraph (deduplicated)

Entity resolution strategies
-----------------------------
* **EXACT_NAME** — entities are considered the same when their ``name``
  fields are identical (case-insensitive).
* **TYPE_AND_NAME** *(default)* — ``(entity_type.lower(), name.lower())``
  pair must match.  Prevents a "person:Alice" from merging with
  "company:Alice".
* **PROPERTY_MATCH** — additionally checks that at least one non-trivial
  property key/value pair matches.

Usage
-----

::

    from ipfs_datasets_py.knowledge_graphs.query.federation import (
        FederatedKnowledgeGraph,
        EntityResolutionStrategy,
    )
    from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph

    # Build two independent graphs
    kg_a = KnowledgeGraph(name="hr")
    alice_a = kg_a.add_entity("person", "Alice", properties={"dept": "eng"})
    bob_a   = kg_a.add_entity("person", "Bob")
    kg_a.add_relationship("manages", alice_a, bob_a)

    kg_b = KnowledgeGraph(name="crm")
    alice_b = kg_b.add_entity("person", "Alice", properties={"region": "west"})
    acme    = kg_b.add_entity("company", "Acme")
    kg_b.add_relationship("works_at", alice_b, acme)

    fed = FederatedKnowledgeGraph()
    fed.add_graph(kg_a, name="hr")
    fed.add_graph(kg_b, name="crm")

    # Find the same entity across graphs
    matches = fed.resolve_entities()
    # [EntityMatch(entity_a_id=<alice_a.entity_id>, entity_b_id=<alice_b.entity_id>,
    #              kg_a_index=0, kg_b_index=1, score=1.0,
    #              strategy=EntityResolutionStrategy.TYPE_AND_NAME)]

    # Merge all graphs into one (Alice deduplicated, properties merged)
    merged = fed.to_merged_graph()

    # Query entity across all graphs
    hits = fed.query_entity(name="Alice")
    # [(0, alice_a), (1, alice_b)]
"""
from __future__ import annotations

import copy
import enum
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

class EntityResolutionStrategy(str, enum.Enum):
    """Strategy used by :meth:`FederatedKnowledgeGraph.resolve_entities`.

    Attributes:
        EXACT_NAME: Entities match when ``name.lower()`` is identical.
        TYPE_AND_NAME: Entities match when both ``entity_type.lower()`` and
            ``name.lower()`` are identical.  This is the default and avoids
            false merges like "person:Alice" ↔ "company:Alice".
        PROPERTY_MATCH: Entities match when ``(type, name)`` matches **and**
            at least one property key/value pair is shared.
    """
    EXACT_NAME = "exact_name"
    TYPE_AND_NAME = "type_and_name"
    PROPERTY_MATCH = "property_match"


@dataclass
class EntityMatch:
    """A pair of entities from different graphs that are considered the same.

    Attributes:
        entity_a_id: ``entity_id`` in the first graph (``kg_a_index``).
        entity_b_id: ``entity_id`` in the second graph (``kg_b_index``).
        kg_a_index: Index of the first graph in
            :attr:`FederatedKnowledgeGraph._graphs`.
        kg_b_index: Index of the second graph.
        score: Match confidence (currently always ``1.0`` for rule-based
            strategies; reserved for future probabilistic matching).
        strategy: The :class:`EntityResolutionStrategy` that produced this
            match.
    """
    entity_a_id: str
    entity_b_id: str
    kg_a_index: int
    kg_b_index: int
    score: float = 1.0
    strategy: EntityResolutionStrategy = EntityResolutionStrategy.TYPE_AND_NAME


@dataclass
class FederationQueryResult:
    """Aggregated result from running a query across all federated graphs.

    Attributes:
        per_graph_results: Mapping of graph index → query output (whatever
            type the caller's *query_fn* returns).
        merged_entities: Optional flat list of entities from all graphs
            (populated only when the query function returns a
            ``List[Entity]``-like object).
        total_matches: Sum of ``len(result)`` for results that are lists.
        query_errors: Mapping of graph index → exception message for any
            graph that raised an exception during execution.
    """
    per_graph_results: Dict[int, Any] = field(default_factory=dict)
    merged_entities: List[Any] = field(default_factory=list)
    total_matches: int = 0
    query_errors: Dict[int, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class FederatedKnowledgeGraph:
    """Federated view over multiple independent
    :class:`~ipfs_datasets_py.knowledge_graphs.extraction.graph.KnowledgeGraph`
    instances.

    Graphs registered with :meth:`add_graph` retain their own state and are
    never mutated by federation operations.  All results are copies or
    read-only views.

    Example:
        >>> fed = FederatedKnowledgeGraph()
        >>> idx_a = fed.add_graph(kg_a, name="hr")
        >>> idx_b = fed.add_graph(kg_b, name="crm")
        >>> matches = fed.resolve_entities()
    """

    def __init__(self) -> None:
        # list of (name: str, kg: KnowledgeGraph)
        self._graphs: List[Tuple[str, Any]] = []

    # ------------------------------------------------------------------
    # Graph registration
    # ------------------------------------------------------------------

    def add_graph(self, kg: Any, name: Optional[str] = None) -> int:
        """Register a knowledge graph with the federation.

        Args:
            kg: A :class:`~ipfs_datasets_py.knowledge_graphs.extraction.graph.KnowledgeGraph`
                instance.
            name: Human-readable label.  Defaults to ``kg.name``.

        Returns:
            The integer index assigned to this graph (used in
            :class:`EntityMatch`, :class:`FederationQueryResult`, etc.).
        """
        label = name if name is not None else getattr(kg, "name", f"graph_{len(self._graphs)}")
        self._graphs.append((label, kg))
        return len(self._graphs) - 1

    def get_graph(self, index: int) -> Any:
        """Return the graph registered at *index*.

        Raises:
            IndexError: If *index* is out of range.
        """
        return self._graphs[index][1]

    def list_graphs(self) -> List[Tuple[int, str]]:
        """Return ``[(index, name), ...]`` for all registered graphs."""
        return [(i, name) for i, (name, _) in enumerate(self._graphs)]

    @property
    def num_graphs(self) -> int:
        """Number of graphs in the federation."""
        return len(self._graphs)

    # ------------------------------------------------------------------
    # Entity resolution helpers
    # ------------------------------------------------------------------

    @staticmethod
    def get_entity_fingerprint(
        entity: Any,
        strategy: EntityResolutionStrategy = EntityResolutionStrategy.TYPE_AND_NAME,
    ) -> str:
        """Compute a string fingerprint for an entity under *strategy*.

        Args:
            entity: An
                :class:`~ipfs_datasets_py.knowledge_graphs.extraction.entities.Entity`.
            strategy: The resolution strategy.

        Returns:
            A lowercase string that two entities must share to be considered
            the same under this strategy.
        """
        name = (getattr(entity, "name", "") or "").lower().strip()
        etype = (getattr(entity, "entity_type", "") or "").lower().strip()

        if strategy == EntityResolutionStrategy.EXACT_NAME:
            return name
        elif strategy == EntityResolutionStrategy.TYPE_AND_NAME:
            return f"{etype}:{name}"
        else:  # PROPERTY_MATCH — base fingerprint; caller verifies property overlap
            return f"{etype}:{name}"

    @staticmethod
    def _properties_overlap(entity_a: Any, entity_b: Any) -> bool:
        """Return True if the two entities share at least one property k/v pair."""
        props_a: Dict = getattr(entity_a, "properties", None) or {}
        props_b: Dict = getattr(entity_b, "properties", None) or {}
        for key, val in props_a.items():
            if val is not None and props_b.get(key) == val:
                return True
        return False

    # ------------------------------------------------------------------
    # Core federation operations
    # ------------------------------------------------------------------

    def resolve_entities(
        self,
        strategy: EntityResolutionStrategy = EntityResolutionStrategy.TYPE_AND_NAME,
    ) -> List[EntityMatch]:
        """Find entities that appear in more than one graph.

        All pairs of registered graphs are compared; for each pair every entity
        in the first graph is checked against every entity in the second.

        Args:
            strategy: Matching algorithm (see :class:`EntityResolutionStrategy`).

        Returns:
            A list of :class:`EntityMatch` objects, one per matched entity
            pair.  The list may be empty when there are fewer than two graphs
            or no overlapping entities are found.
        """
        matches: List[EntityMatch] = []

        for i in range(len(self._graphs)):
            for j in range(i + 1, len(self._graphs)):
                kg_a = self._graphs[i][1]
                kg_b = self._graphs[j][1]

                # Build fingerprint → entity_id map for kg_b
                fp_to_b: Dict[str, str] = {}
                for eid, ent in getattr(kg_b, "entities", {}).items():
                    fp = self.get_entity_fingerprint(ent, strategy)
                    if fp:
                        fp_to_b[fp] = eid

                # Match entities from kg_a against kg_b
                for eid_a, ent_a in getattr(kg_a, "entities", {}).items():
                    fp_a = self.get_entity_fingerprint(ent_a, strategy)
                    if not fp_a:
                        continue
                    eid_b = fp_to_b.get(fp_a)
                    if eid_b is None:
                        continue

                    # Extra check for PROPERTY_MATCH
                    if strategy == EntityResolutionStrategy.PROPERTY_MATCH:
                        ent_b = kg_b.entities.get(eid_b)
                        if ent_b is not None and not self._properties_overlap(ent_a, ent_b):
                            continue

                    matches.append(EntityMatch(
                        entity_a_id=eid_a,
                        entity_b_id=eid_b,
                        kg_a_index=i,
                        kg_b_index=j,
                        score=1.0,
                        strategy=strategy,
                    ))

        return matches

    def get_entity_cluster(
        self,
        fingerprint: str,
        strategy: EntityResolutionStrategy = EntityResolutionStrategy.TYPE_AND_NAME,
    ) -> List[Tuple[int, str]]:
        """Return all ``(graph_index, entity_id)`` pairs matching *fingerprint*.

        Args:
            fingerprint: A fingerprint string as returned by
                :meth:`get_entity_fingerprint`.
            strategy: Must match the strategy used to produce *fingerprint*.

        Returns:
            List of ``(graph_index, entity_id)`` tuples; empty if none found.
        """
        result: List[Tuple[int, str]] = []
        for gi, (_, kg) in enumerate(self._graphs):
            for eid, ent in getattr(kg, "entities", {}).items():
                fp = self.get_entity_fingerprint(ent, strategy)
                if fp == fingerprint:
                    result.append((gi, eid))
        return result

    def query_entity(
        self,
        name: Optional[str] = None,
        entity_type: Optional[str] = None,
    ) -> List[Tuple[int, Any]]:
        """Find entities across all graphs by name and/or type.

        Args:
            name: Case-insensitive entity name filter (``None`` = any name).
            entity_type: Case-insensitive entity type filter (``None`` = any type).

        Returns:
            List of ``(graph_index, entity)`` pairs for every entity that
            matches all supplied filters.
        """
        hits: List[Tuple[int, Any]] = []
        name_lower = name.lower() if name else None
        type_lower = entity_type.lower() if entity_type else None

        for gi, (_, kg) in enumerate(self._graphs):
            for ent in getattr(kg, "entities", {}).values():
                ent_name = (getattr(ent, "name", "") or "").lower()
                ent_type = (getattr(ent, "entity_type", "") or "").lower()
                if name_lower is not None and ent_name != name_lower:
                    continue
                if type_lower is not None and ent_type != type_lower:
                    continue
                hits.append((gi, ent))

        return hits

    def execute_across(
        self,
        query_fn: Callable[[Any], Any],
    ) -> FederationQueryResult:
        """Apply *query_fn* to every registered graph and aggregate results.

        Args:
            query_fn: A callable that accepts a single ``KnowledgeGraph``
                argument and returns any value.  Exceptions are caught and
                recorded in :attr:`FederationQueryResult.query_errors`; they
                do not stop execution of subsequent graphs.

        Returns:
            A :class:`FederationQueryResult` with per-graph outputs.
        """
        per_graph: Dict[int, Any] = {}
        errors: Dict[int, str] = {}
        merged: List[Any] = []
        total = 0

        for gi, (_, kg) in enumerate(self._graphs):
            try:
                result = query_fn(kg)
                per_graph[gi] = result
                if isinstance(result, list):
                    merged.extend(result)
                    total += len(result)
            except Exception as exc:  # noqa: BLE001 — excludes SystemExit/KeyboardInterrupt (BaseException)
                logger.debug("FederatedKnowledgeGraph.execute_across error on graph %d: %s", gi, exc)
                errors[gi] = str(exc)

        return FederationQueryResult(
            per_graph_results=per_graph,
            merged_entities=merged,
            total_matches=total,
            query_errors=errors,
        )

    def to_merged_graph(
        self,
        strategy: EntityResolutionStrategy = EntityResolutionStrategy.TYPE_AND_NAME,
        merged_name: Optional[str] = None,
    ) -> Any:
        """Merge all federated graphs into one :class:`KnowledgeGraph`.

        Entities sharing the same fingerprint under *strategy* are
        deduplicated: the first occurrence is kept and its properties are
        updated with any additional properties from later occurrences.
        Relationships are re-mapped to the canonical (first-seen) entity IDs.

        Args:
            strategy: Entity deduplication strategy.
            merged_name: Name for the resulting graph.  Defaults to a
                combination of all component graph names.

        Returns:
            A new :class:`~ipfs_datasets_py.knowledge_graphs.extraction.graph.KnowledgeGraph`
            containing all entities and relationships.
        """
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph

        if merged_name is None:
            names = [name for name, _ in self._graphs]
            merged_name = "+".join(names) or "merged"

        merged = KnowledgeGraph(name=merged_name)

        # fingerprint → canonical entity_id in merged graph
        fp_to_canonical: Dict[str, str] = {}
        # (source_graph_index, original_entity_id) → merged_entity_id
        orig_to_merged: Dict[Tuple[int, str], str] = {}

        # Pass 1: add / deduplicate entities
        for gi, (_, kg) in enumerate(self._graphs):
            for eid, ent in getattr(kg, "entities", {}).items():
                fp = self.get_entity_fingerprint(ent, strategy)

                if fp and fp in fp_to_canonical:
                    # Already present — merge properties into existing entity
                    canonical_id = fp_to_canonical[fp]
                    orig_to_merged[(gi, eid)] = canonical_id
                    canon_ent = merged.entities.get(canonical_id)
                    if canon_ent is not None:
                        extra = {
                            k: v
                            for k, v in (getattr(ent, "properties", None) or {}).items()
                            if k not in (getattr(canon_ent, "properties", None) or {})
                        }
                        if extra:
                            if canon_ent.properties is None:
                                canon_ent.properties = {}
                            canon_ent.properties.update(extra)
                else:
                    # New entity — deep copy to avoid mutating the source graph
                    new_ent = copy.deepcopy(ent)
                    new_eid = new_ent.entity_id
                    merged.entities[new_eid] = new_ent
                    # Rebuild indexes
                    merged.entity_types[new_ent.entity_type].add(new_eid)
                    merged.entity_names[new_ent.name].add(new_eid)
                    orig_to_merged[(gi, eid)] = new_eid
                    if fp:
                        fp_to_canonical[fp] = new_eid

        # Pass 2: add relationships (re-map entity references)
        seen_rels: set = set()
        for gi, (_, kg) in enumerate(self._graphs):
            for rid, rel in getattr(kg, "relationships", {}).items():
                src_orig = getattr(getattr(rel, "source_entity", None), "entity_id", None)
                tgt_orig = getattr(getattr(rel, "target_entity", None), "entity_id", None)
                if src_orig is None or tgt_orig is None:
                    continue

                src_merged = orig_to_merged.get((gi, src_orig))
                tgt_merged = orig_to_merged.get((gi, tgt_orig))
                if src_merged is None or tgt_merged is None:
                    continue

                # Deduplicate relationships by (type, src, tgt)
                rel_fp = (
                    (getattr(rel, "relationship_type", "") or "").lower(),
                    src_merged,
                    tgt_merged,
                )
                if rel_fp in seen_rels:
                    continue
                seen_rels.add(rel_fp)

                src_ent = merged.entities.get(src_merged)
                tgt_ent = merged.entities.get(tgt_merged)
                if src_ent is None or tgt_ent is None:
                    continue

                new_rel = copy.deepcopy(rel)
                new_rel.source_entity = src_ent
                new_rel.target_entity = tgt_ent
                merged.relationships[new_rel.relationship_id] = new_rel
                # Rebuild indexes
                merged.relationship_types[new_rel.relationship_type].add(new_rel.relationship_id)
                merged.entity_relationships[src_merged].add(new_rel.relationship_id)
                merged.entity_relationships[tgt_merged].add(new_rel.relationship_id)

        return merged
