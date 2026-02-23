"""
Explainable AI over Knowledge Graphs

Provides human-readable explanations for entities, relationships, paths,
and query results in a KnowledgeGraph.

Delivered in v3.22.34 as the ROADMAP Research Area
"Explainable AI over knowledge graphs".

This module requires no external ML or visualisation libraries.

Components
----------
QueryExplainer
    Main entry point.  Call ``explain_entity()``, ``explain_relationship()``,
    ``explain_path()``, ``explain_query_result()``, ``why_connected()``, or
    ``entity_importance_score()``.

EntityExplanation
    Structured explanation for a single entity.

RelationshipExplanation
    Structured explanation for a single relationship.

PathExplanation
    BFS-shortest-path explanation between two entities.

ExplanationDepth
    Controls verbosity — SURFACE / STANDARD / DEEP.

Usage
-----
>>> from ipfs_datasets_py.knowledge_graphs.query.explanation import QueryExplainer
>>> explainer = QueryExplainer(kg)
>>> exp = explainer.explain_entity("e-alice")
>>> print(exp.narrative)
"Alice (person) — confidence 0.95; 3 relationships (2 outgoing, 1 incoming)."
>>> path_exp = explainer.explain_path("e-alice", "e-charlie")
>>> print(path_exp.narrative)
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple

if TYPE_CHECKING:
    from ..extraction.graph import KnowledgeGraph


# ---------------------------------------------------------------------------
# Depth enum
# ---------------------------------------------------------------------------

class ExplanationDepth(str, enum.Enum):
    """Controls how much detail is included in explanations."""
    SURFACE = "surface"
    STANDARD = "standard"
    DEEP = "deep"


# ---------------------------------------------------------------------------
# Explanation dataclasses
# ---------------------------------------------------------------------------

@dataclass
class EntityExplanation:
    """Structured explanation for a knowledge-graph entity.

    Attributes:
        entity_id: Unique entity identifier.
        entity_type: Ontological type (e.g. ``"person"``).
        entity_name: Human-readable name.
        confidence: Extraction confidence in [0.0, 1.0].
        related_count: Total number of incident relationships.
        outgoing_count: Number of outgoing relationships.
        incoming_count: Number of incoming relationships.
        top_outgoing: Up to 5 ``(rel_type, target_name)`` pairs.
        top_incoming: Up to 5 ``(rel_type, source_name)`` pairs.
        property_summary: Concise string listing non-empty properties.
        cluster_hint: Informal cluster label if detectable, else "".
        narrative: One-sentence human-readable summary.
    """
    entity_id: str
    entity_type: str
    entity_name: str
    confidence: float
    related_count: int
    outgoing_count: int
    incoming_count: int
    top_outgoing: List[Tuple[str, str]] = field(default_factory=list)
    top_incoming: List[Tuple[str, str]] = field(default_factory=list)
    property_summary: str = ""
    cluster_hint: str = ""
    narrative: str = ""

    def to_dict(self) -> dict:
        """Serialise to a plain dict."""
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "entity_name": self.entity_name,
            "confidence": self.confidence,
            "related_count": self.related_count,
            "outgoing_count": self.outgoing_count,
            "incoming_count": self.incoming_count,
            "top_outgoing": self.top_outgoing,
            "top_incoming": self.top_incoming,
            "property_summary": self.property_summary,
            "cluster_hint": self.cluster_hint,
            "narrative": self.narrative,
        }


@dataclass
class RelationshipExplanation:
    """Structured explanation for a knowledge-graph relationship.

    Attributes:
        relationship_id: Unique relationship identifier.
        relationship_type: Type label.
        source_name: Name of the source entity.
        target_name: Name of the target entity.
        source_type: Type of the source entity.
        target_type: Type of the target entity.
        confidence: Extraction confidence in [0.0, 1.0].
        context_chains: Up to 3 alternative paths connecting the same pair.
        symmetry_note: Non-empty string when the inverse relationship exists.
        narrative: One-sentence human-readable summary.
    """
    relationship_id: str
    relationship_type: str
    source_name: str
    target_name: str
    source_type: str = ""
    target_type: str = ""
    confidence: float = 1.0
    context_chains: List[str] = field(default_factory=list)
    symmetry_note: str = ""
    narrative: str = ""

    def to_dict(self) -> dict:
        """Serialise to a plain dict."""
        return {
            "relationship_id": self.relationship_id,
            "relationship_type": self.relationship_type,
            "source_name": self.source_name,
            "target_name": self.target_name,
            "source_type": self.source_type,
            "target_type": self.target_type,
            "confidence": self.confidence,
            "context_chains": self.context_chains,
            "symmetry_note": self.symmetry_note,
            "narrative": self.narrative,
        }


@dataclass
class PathExplanation:
    """Explanation of the shortest path between two entities.

    Attributes:
        start_id: Source entity ID.
        end_id: Target entity ID.
        path_nodes: Ordered list of entity IDs along the path.
        path_rels: Ordered list of relationship types along the path.
        hops: Number of hops (len(path_rels)).
        total_confidence: Product of edge confidences along the path.
        path_labels: Human-readable names for each node.
        narrative: Multi-line explanation of the path.
        reachable: False when no path was found within max_hops.
    """
    start_id: str
    end_id: str
    path_nodes: List[str] = field(default_factory=list)
    path_rels: List[str] = field(default_factory=list)
    hops: int = 0
    total_confidence: float = 0.0
    path_labels: List[str] = field(default_factory=list)
    narrative: str = ""
    reachable: bool = True

    def to_dict(self) -> dict:
        """Serialise to a plain dict."""
        return {
            "start_id": self.start_id,
            "end_id": self.end_id,
            "path_nodes": self.path_nodes,
            "path_rels": self.path_rels,
            "hops": self.hops,
            "total_confidence": self.total_confidence,
            "path_labels": self.path_labels,
            "narrative": self.narrative,
            "reachable": self.reachable,
        }


# ---------------------------------------------------------------------------
# Main explainer
# ---------------------------------------------------------------------------

class QueryExplainer:
    """Produces human-readable explanations for KG entities, relationships,
    and paths.

    Args:
        kg: The :class:`~..extraction.graph.KnowledgeGraph` to explain.

    Example::

        explainer = QueryExplainer(kg)
        exp = explainer.explain_entity(alice.entity_id)
        print(exp.narrative)
        path = explainer.explain_path(alice.entity_id, charlie.entity_id)
        print(path.narrative)
    """

    def __init__(self, kg: "KnowledgeGraph") -> None:
        self._kg = kg

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def explain_entity(
        self,
        entity_id: str,
        depth: ExplanationDepth = ExplanationDepth.STANDARD,
    ) -> EntityExplanation:
        """Return a structured explanation for *entity_id*.

        Args:
            entity_id: ID of the entity to explain.
            depth: Controls how much detail to include.

        Returns:
            :class:`EntityExplanation`.  If the entity does not exist,
            returns a minimal explanation with empty fields.
        """
        entity = self._kg.entities.get(entity_id)
        if entity is None:
            return EntityExplanation(
                entity_id=entity_id,
                entity_type="unknown",
                entity_name=entity_id,
                confidence=0.0,
                related_count=0,
                outgoing_count=0,
                incoming_count=0,
                narrative=f"Entity '{entity_id}' not found in the knowledge graph.",
            )

        # Collect incident relationships
        outgoing = [
            r for r in self._kg.relationships.values() if r.source_id == entity_id
        ]
        incoming = [
            r for r in self._kg.relationships.values() if r.target_id == entity_id
        ]

        top_out = [
            (r.relationship_type, self._name(r.target_id))
            for r in sorted(outgoing, key=lambda r: -r.confidence)[:5]
        ]
        top_in = [
            (r.relationship_type, self._name(r.source_id))
            for r in sorted(incoming, key=lambda r: -r.confidence)[:5]
        ]

        # Property summary
        props = getattr(entity, "properties", {}) or {}
        prop_summary = ""
        if props and depth != ExplanationDepth.SURFACE:
            items = [f"{k}={v!r}" for k, v in list(props.items())[:5]]
            prop_summary = "; ".join(items)

        # Cluster hint — informally, the most common outgoing rel_type target-type
        cluster_hint = ""
        if depth == ExplanationDepth.DEEP and outgoing:
            type_counts: Dict[str, int] = {}
            for r in outgoing:
                tgt = self._kg.entities.get(r.target_id)
                if tgt:
                    type_counts[tgt.entity_type] = type_counts.get(tgt.entity_type, 0) + 1
            if type_counts:
                cluster_hint = max(type_counts, key=type_counts.__getitem__)

        rel_count = len(outgoing) + len(incoming)
        narrative = (
            f"{entity.name} ({entity.entity_type}) — "
            f"confidence {entity.confidence:.2f}; "
            f"{rel_count} relationship{'s' if rel_count != 1 else ''} "
            f"({len(outgoing)} outgoing, {len(incoming)} incoming)."
        )

        return EntityExplanation(
            entity_id=entity_id,
            entity_type=entity.entity_type,
            entity_name=entity.name,
            confidence=entity.confidence,
            related_count=rel_count,
            outgoing_count=len(outgoing),
            incoming_count=len(incoming),
            top_outgoing=top_out,
            top_incoming=top_in,
            property_summary=prop_summary,
            cluster_hint=cluster_hint,
            narrative=narrative,
        )

    def explain_relationship(
        self,
        relationship_id: str,
        depth: ExplanationDepth = ExplanationDepth.STANDARD,
    ) -> RelationshipExplanation:
        """Return a structured explanation for *relationship_id*.

        Args:
            relationship_id: ID of the relationship to explain.
            depth: Controls how much detail to include.

        Returns:
            :class:`RelationshipExplanation`.
        """
        rel = self._kg.relationships.get(relationship_id)
        if rel is None:
            return RelationshipExplanation(
                relationship_id=relationship_id,
                relationship_type="unknown",
                source_name=relationship_id,
                target_name="",
                narrative=f"Relationship '{relationship_id}' not found.",
            )

        src = self._kg.entities.get(rel.source_id)
        tgt = self._kg.entities.get(rel.target_id)
        src_name = src.name if src else rel.source_id
        tgt_name = tgt.name if tgt else rel.target_id
        src_type = src.entity_type if src else ""
        tgt_type = tgt.entity_type if tgt else ""

        # Check for symmetric reverse
        symmetry_note = ""
        if depth != ExplanationDepth.SURFACE:
            reverse_exists = any(
                r.source_id == rel.target_id
                and r.target_id == rel.source_id
                and r.relationship_type == rel.relationship_type
                for r in self._kg.relationships.values()
            )
            if reverse_exists:
                symmetry_note = (
                    f"The inverse '{tgt_name} -[{rel.relationship_type}]→ {src_name}'"
                    " also exists."
                )

        # Context: other paths connecting the same pair
        context_chains: List[str] = []
        if depth == ExplanationDepth.DEEP:
            other_rels = [
                r for r in self._kg.relationships.values()
                if r.source_id == rel.source_id
                and r.target_id == rel.target_id
                and r.relationship_id != relationship_id
            ]
            for other in other_rels[:3]:
                context_chains.append(
                    f"{src_name} -[{other.relationship_type}]→ {tgt_name}"
                )

        narrative = (
            f"{src_name} ({src_type}) -[{rel.relationship_type}]→ "
            f"{tgt_name} ({tgt_type}); confidence {rel.confidence:.2f}."
        )

        return RelationshipExplanation(
            relationship_id=relationship_id,
            relationship_type=rel.relationship_type,
            source_name=src_name,
            target_name=tgt_name,
            source_type=src_type,
            target_type=tgt_type,
            confidence=rel.confidence,
            context_chains=context_chains,
            symmetry_note=symmetry_note,
            narrative=narrative,
        )

    def explain_path(
        self,
        start_id: str,
        end_id: str,
        max_hops: int = 4,
    ) -> PathExplanation:
        """Return a BFS-shortest-path explanation from *start_id* to *end_id*.

        Args:
            start_id: Source entity ID.
            end_id: Target entity ID.
            max_hops: Maximum path length to explore.

        Returns:
            :class:`PathExplanation`.  ``reachable=False`` if no path found.
        """
        if start_id == end_id:
            entity = self._kg.entities.get(start_id)
            name = entity.name if entity else start_id
            return PathExplanation(
                start_id=start_id,
                end_id=end_id,
                path_nodes=[start_id],
                path_rels=[],
                hops=0,
                total_confidence=1.0,
                path_labels=[name],
                narrative=f"'{name}' is the same entity — no traversal needed.",
                reachable=True,
            )

        # BFS
        # Queue entries: (current_id, path_nodes, path_rels, confidence_product)
        from collections import deque

        visited: Set[str] = {start_id}
        queue: deque = deque()
        queue.append(([start_id], [], 1.0))

        # Build outgoing adjacency index: source_id → [(rel_type, confidence, target_id)]
        adj: Dict[str, List[Tuple[str, float, str]]] = {}
        for r in self._kg.relationships.values():
            adj.setdefault(r.source_id, []).append(
                (r.relationship_type, r.confidence, r.target_id)
            )

        while queue:
            nodes, rels, conf = queue.popleft()
            current = nodes[-1]

            if len(rels) >= max_hops:
                continue

            for rel_type, edge_conf, nxt in adj.get(current, []):
                if nxt in visited:
                    continue
                new_nodes = nodes + [nxt]
                new_rels = rels + [rel_type]
                new_conf = conf * edge_conf

                if nxt == end_id:
                    labels = [self._name(n) for n in new_nodes]
                    parts = []
                    for i, label in enumerate(labels):
                        parts.append(label)
                        if i < len(new_rels):
                            parts.append(f"-[{new_rels[i]}]→")
                    narrative = (
                        f"Path ({len(new_rels)} hop{'s' if len(new_rels) != 1 else ''}): "
                        + " ".join(parts)
                        + f" (cumulative confidence: {new_conf:.2f})"
                    )
                    return PathExplanation(
                        start_id=start_id,
                        end_id=end_id,
                        path_nodes=new_nodes,
                        path_rels=new_rels,
                        hops=len(new_rels),
                        total_confidence=round(new_conf, 4),
                        path_labels=labels,
                        narrative=narrative,
                        reachable=True,
                    )

                visited.add(nxt)
                queue.append((new_nodes, new_rels, new_conf))

        # Not reachable
        start_name = self._name(start_id)
        end_name = self._name(end_id)
        return PathExplanation(
            start_id=start_id,
            end_id=end_id,
            path_nodes=[],
            path_rels=[],
            hops=0,
            total_confidence=0.0,
            path_labels=[],
            narrative=(
                f"No path found between '{start_name}' and '{end_name}'"
                f" within {max_hops} hop{'s' if max_hops != 1 else ''}."
            ),
            reachable=False,
        )

    def explain_query_result(
        self,
        entities: List[str],
        depth: ExplanationDepth = ExplanationDepth.SURFACE,
    ) -> List[EntityExplanation]:
        """Return batch entity explanations for a list of entity IDs.

        Args:
            entities: List of entity IDs (e.g. from a Cypher result).
            depth: Explanation depth for each entity.

        Returns:
            List of :class:`EntityExplanation`, one per ID.
        """
        return [self.explain_entity(eid, depth) for eid in entities]

    def why_connected(self, entity_a_id: str, entity_b_id: str) -> str:
        """Return a natural-language explanation of why two entities are connected.

        Checks for direct relationship first, then falls back to BFS path.
        Returns a plain string suitable for display.
        """
        # Direct relationship?
        for r in self._kg.relationships.values():
            if r.source_id == entity_a_id and r.target_id == entity_b_id:
                a_name = self._name(entity_a_id)
                b_name = self._name(entity_b_id)
                return (
                    f"'{a_name}' is directly connected to '{b_name}' via "
                    f"a '{r.relationship_type}' relationship "
                    f"(confidence {r.confidence:.2f})."
                )

        # BFS path
        path_exp = self.explain_path(entity_a_id, entity_b_id)
        if path_exp.reachable:
            return path_exp.narrative
        a_name = self._name(entity_a_id)
        b_name = self._name(entity_b_id)
        return f"'{a_name}' and '{b_name}' are not connected in this graph."

    def entity_importance_score(self, entity_id: str) -> float:
        """Return a normalised [0, 1] importance score for *entity_id*.

        Score is degree-based centrality (in+out degree) weighted by confidence.
        Returns 0.0 when the graph has no relationships or the entity is unknown.
        """
        if entity_id not in self._kg.entities or not self._kg.relationships:
            return 0.0

        entity = self._kg.entities[entity_id]
        degree = sum(
            1
            for r in self._kg.relationships.values()
            if r.source_id == entity_id or r.target_id == entity_id
        )
        max_degree = max(
            sum(
                1
                for r in self._kg.relationships.values()
                if r.source_id == eid or r.target_id == eid
            )
            for eid in self._kg.entities
        )
        if max_degree == 0:
            return 0.0
        centrality = degree / max_degree
        return round(centrality * entity.confidence, 4)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _name(self, entity_id: str) -> str:
        ent = self._kg.entities.get(entity_id)
        return ent.name if ent else entity_id
