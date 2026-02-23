"""
Knowledge Graph Completion Module

Suggests missing entities and relationships in a KnowledgeGraph using
structural graph-analysis patterns (no external ML libraries required).

Delivered in v3.22.34 as the ROADMAP Research Area
"Knowledge graph completion with AI".

Pattern strategies
------------------
TRIADIC_CLOSURE
    If A→B and B→C (same or any relationship type) exist, suggest A→C.

COMMON_NEIGHBOR
    Entities that share many common neighbors are likely to be related.
    Score uses Jaccard similarity of the neighborhood sets.

SYMMETRIC_RELATION
    If A→(rel_type)→B exists and B→(rel_type)→A is absent, suggest
    the reverse direction (for naturally symmetric types like "knows",
    "similar_to", "collaborates_with").

TRANSITIVE_RELATION
    If A→(rel)→B and B→(rel)→C (same rel_type, all same entity_type),
    suggest A→(rel)→C.

INVERSE_RELATION
    For certain rel_type pairs (e.g. "parent_of"↔"child_of",
    "employed_by"↔"employs") suggest the inverse direction.

TYPE_COMPATIBILITY
    Entities of the same type that co-appear in many relationships
    with a third entity receive a compatibility score.

Usage
-----
>>> from ipfs_datasets_py.knowledge_graphs.query.completion import (
...     KnowledgeGraphCompleter, CompletionReason,
... )
>>> completer = KnowledgeGraphCompleter(kg)
>>> suggestions = completer.find_missing_relationships(min_score=0.4)
>>> for s in suggestions:
...     print(s.score, s.reason.value, s.source_id, "→", s.rel_type, "→", s.target_id)
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple

if TYPE_CHECKING:
    from ..extraction.graph import KnowledgeGraph

# ---------------------------------------------------------------------------
# Inverse-relation pairs (symmetric knowledge)
# ---------------------------------------------------------------------------
_INVERSE_PAIRS: List[Tuple[str, str]] = [
    ("parent_of", "child_of"),
    ("child_of", "parent_of"),
    ("employed_by", "employs"),
    ("employs", "employed_by"),
    ("contains", "contained_by"),
    ("contained_by", "contains"),
    ("owns", "owned_by"),
    ("owned_by", "owns"),
    ("manages", "managed_by"),
    ("managed_by", "manages"),
    ("part_of", "has_part"),
    ("has_part", "part_of"),
    ("precedes", "follows"),
    ("follows", "precedes"),
    ("subclass_of", "superclass_of"),
    ("superclass_of", "subclass_of"),
]
_INVERSE_MAP: Dict[str, str] = dict(_INVERSE_PAIRS)

# Naturally symmetric rel types — suggest missing reverse edge
_SYMMETRIC_REL_TYPES: Set[str] = {
    "knows",
    "similar_to",
    "related_to",
    "collaborates_with",
    "connected_to",
    "associated_with",
    "co_occurs_with",
    "competes_with",
    "allies_with",
    "married_to",
}


# ---------------------------------------------------------------------------
# Public enums and dataclasses
# ---------------------------------------------------------------------------

class CompletionReason(str, enum.Enum):
    """Structural reason for a completion suggestion."""
    TRIADIC_CLOSURE = "triadic_closure"
    COMMON_NEIGHBOR = "common_neighbor"
    SYMMETRIC_RELATION = "symmetric_relation"
    TRANSITIVE_RELATION = "transitive_relation"
    INVERSE_RELATION = "inverse_relation"
    TYPE_COMPATIBILITY = "type_compatibility"


@dataclass
class CompletionSuggestion:
    """A suggested missing relationship in the knowledge graph.

    Attributes:
        source_id: Entity ID of the suggested relationship source.
        target_id: Entity ID of the suggested relationship target.
        rel_type: Suggested relationship type.
        score: Confidence score in [0.0, 1.0]; higher = more likely.
        reason: Structural pattern that produced this suggestion.
        evidence: Human-readable evidence string.
    """
    source_id: str
    target_id: str
    rel_type: str
    score: float
    reason: CompletionReason
    evidence: str = ""

    def to_dict(self) -> dict:
        """Serialise to a plain dict."""
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "rel_type": self.rel_type,
            "score": self.score,
            "reason": self.reason.value,
            "evidence": self.evidence,
        }


# ---------------------------------------------------------------------------
# Main completer class
# ---------------------------------------------------------------------------

class KnowledgeGraphCompleter:
    """Suggests missing relationships using structural graph-analysis patterns.

    No external ML libraries are required — all analysis is pure Python.

    Args:
        kg: The :class:`~..extraction.graph.KnowledgeGraph` to analyse.

    Example::

        completer = KnowledgeGraphCompleter(kg)
        suggestions = completer.find_missing_relationships(min_score=0.5)
        for s in suggestions[:3]:
            print(completer.explain_suggestion(s))
    """

    def __init__(self, kg: "KnowledgeGraph") -> None:
        self._kg = kg

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def find_missing_relationships(
        self,
        entity_id: Optional[str] = None,
        rel_type: Optional[str] = None,
        min_score: float = 0.0,
        max_suggestions: int = 50,
    ) -> List[CompletionSuggestion]:
        """Return ranked suggestions for missing relationships.

        Args:
            entity_id: If given, only return suggestions involving this entity.
            rel_type: If given, only return suggestions of this relationship type.
            min_score: Minimum score threshold (0.0–1.0).
            max_suggestions: Upper bound on results returned.

        Returns:
            List of :class:`CompletionSuggestion` sorted by score descending.
        """
        seen: Set[Tuple[str, str, str]] = set()
        raw: List[CompletionSuggestion] = []

        for fn in (
            self._triadic_closure_suggestions,
            self._symmetric_suggestions,
            self._inverse_suggestions,
            self._transitive_suggestions,
            self._common_neighbor_suggestions,
            self._type_compatibility_suggestions,
        ):
            for s in fn():
                key = (s.source_id, s.target_id, s.rel_type)
                if key in seen:
                    continue
                seen.add(key)
                if s.score < min_score:
                    continue
                if entity_id and entity_id not in (s.source_id, s.target_id):
                    continue
                if rel_type and s.rel_type != rel_type:
                    continue
                raw.append(s)

        raw.sort(key=lambda x: x.score, reverse=True)
        return raw[:max_suggestions]

    def compute_completion_score(
        self, source_id: str, target_id: str, rel_type: str
    ) -> float:
        """Return a [0,1] score for a specific (source, rel_type, target) triple.

        Aggregates evidence across all patterns and caps at 1.0.
        Returns 0.0 if either entity is unknown.
        """
        if source_id not in self._kg.entities or target_id not in self._kg.entities:
            return 0.0
        suggestions = self.find_missing_relationships(
            entity_id=source_id, rel_type=rel_type, min_score=0.0, max_suggestions=200
        )
        total = 0.0
        for s in suggestions:
            if s.source_id == source_id and s.target_id == target_id:
                total += s.score
        return min(1.0, total)

    def find_isolated_entities(self) -> List[str]:
        """Return entity IDs that have no relationships (in or out)."""
        connected: Set[str] = set()
        for rel in self._kg.relationships.values():
            connected.add(rel.source_id)
            connected.add(rel.target_id)
        return [eid for eid in self._kg.entities if eid not in connected]

    def explain_suggestion(self, suggestion: CompletionSuggestion) -> str:
        """Return a human-readable explanation for a suggestion."""
        src = self._kg.entities.get(suggestion.source_id)
        tgt = self._kg.entities.get(suggestion.target_id)
        src_name = src.name if src else suggestion.source_id
        tgt_name = tgt.name if tgt else suggestion.target_id
        base = (
            f"Suggest '{src_name}' --[{suggestion.rel_type}]--> '{tgt_name}'"
            f" (score={suggestion.score:.2f}, reason={suggestion.reason.value})"
        )
        if suggestion.evidence:
            base += f"\n  Evidence: {suggestion.evidence}"
        return base

    # ------------------------------------------------------------------
    # Private pattern methods
    # ------------------------------------------------------------------

    def _existing_triples(self) -> Set[Tuple[str, str, str]]:
        """Return the set of all (source_id, rel_type, target_id) triples."""
        return {
            (r.source_id, r.relationship_type, r.target_id)
            for r in self._kg.relationships.values()
        }

    def _adjacency(self) -> Dict[str, Set[str]]:
        """Outgoing neighbours (any rel_type)."""
        adj: Dict[str, Set[str]] = {eid: set() for eid in self._kg.entities}
        for r in self._kg.relationships.values():
            adj.setdefault(r.source_id, set()).add(r.target_id)
            adj.setdefault(r.target_id, set())
        return adj

    def _typed_adjacency(self) -> Dict[str, Dict[str, Set[str]]]:
        """adj[entity_id][rel_type] → set of target_ids."""
        adj: Dict[str, Dict[str, Set[str]]] = {}
        for r in self._kg.relationships.values():
            adj.setdefault(r.source_id, {}).setdefault(r.relationship_type, set()).add(r.target_id)
        return adj

    def _triadic_closure_suggestions(self) -> List[CompletionSuggestion]:
        """A→B and B→C (any type) → suggest A→(same_type)→C."""
        existing = self._existing_triples()
        results: List[CompletionSuggestion] = []
        # Build: for each rel (A→B, type_ab) and (B→C, type_bc)
        # Group rels by source
        by_src: Dict[str, List] = {}
        for r in self._kg.relationships.values():
            by_src.setdefault(r.source_id, []).append(r)

        for rel_ab in self._kg.relationships.values():
            a_id = rel_ab.source_id
            b_id = rel_ab.target_id
            # find all rels B→C
            for rel_bc in by_src.get(b_id, []):
                c_id = rel_bc.target_id
                if c_id == a_id:
                    continue
                rel_type = rel_ab.relationship_type
                if (a_id, rel_type, c_id) in existing:
                    continue
                score = 0.5 * (rel_ab.confidence + rel_bc.confidence)
                evidence = (
                    f"{self._name(a_id)} -[{rel_ab.relationship_type}]→ "
                    f"{self._name(b_id)} -[{rel_bc.relationship_type}]→ {self._name(c_id)}"
                )
                results.append(
                    CompletionSuggestion(
                        source_id=a_id,
                        target_id=c_id,
                        rel_type=rel_type,
                        score=round(score, 4),
                        reason=CompletionReason.TRIADIC_CLOSURE,
                        evidence=evidence,
                    )
                )
        return results

    def _common_neighbor_suggestions(self) -> List[CompletionSuggestion]:
        """Entities sharing many common neighbours are likely related."""
        existing = self._existing_triples()
        adj = self._adjacency()
        results: List[CompletionSuggestion] = []
        entity_ids = list(self._kg.entities.keys())
        for i, a_id in enumerate(entity_ids):
            for b_id in entity_ids[i + 1:]:
                if a_id == b_id:
                    continue
                na = adj.get(a_id, set())
                nb = adj.get(b_id, set())
                union = na | nb
                if not union:
                    continue
                intersection = na & nb
                if not intersection:
                    continue
                jaccard = len(intersection) / len(union)
                if jaccard < 0.1:
                    continue
                rel_type = "related_to"
                if (a_id, rel_type, b_id) not in existing:
                    evidence = f"{len(intersection)} common neighbours"
                    results.append(
                        CompletionSuggestion(
                            source_id=a_id,
                            target_id=b_id,
                            rel_type=rel_type,
                            score=round(jaccard * 0.8, 4),
                            reason=CompletionReason.COMMON_NEIGHBOR,
                            evidence=evidence,
                        )
                    )
        return results

    def _symmetric_suggestions(self) -> List[CompletionSuggestion]:
        """If A→(sym_type)→B exists but not B→(sym_type)→A, suggest it."""
        existing = self._existing_triples()
        results: List[CompletionSuggestion] = []
        for r in self._kg.relationships.values():
            rtype = r.relationship_type.lower()
            if rtype not in _SYMMETRIC_REL_TYPES:
                continue
            reverse = (r.target_id, r.relationship_type, r.source_id)
            if reverse not in existing:
                evidence = f"'{r.relationship_type}' is a symmetric relationship type"
                results.append(
                    CompletionSuggestion(
                        source_id=r.target_id,
                        target_id=r.source_id,
                        rel_type=r.relationship_type,
                        score=round(r.confidence * 0.9, 4),
                        reason=CompletionReason.SYMMETRIC_RELATION,
                        evidence=evidence,
                    )
                )
        return results

    def _transitive_suggestions(self) -> List[CompletionSuggestion]:
        """If A→(rel)→B and B→(rel)→C (same rel_type), suggest A→(rel)→C."""
        existing = self._existing_triples()
        typed_adj = self._typed_adjacency()
        results: List[CompletionSuggestion] = []
        for a_id, rel_map in typed_adj.items():
            for rel_type, b_set in rel_map.items():
                for b_id in b_set:
                    c_set = typed_adj.get(b_id, {}).get(rel_type, set())
                    for c_id in c_set:
                        if c_id == a_id:
                            continue
                        if (a_id, rel_type, c_id) in existing:
                            continue
                        evidence = (
                            f"{self._name(a_id)} -[{rel_type}]→ "
                            f"{self._name(b_id)} -[{rel_type}]→ {self._name(c_id)}"
                        )
                        results.append(
                            CompletionSuggestion(
                                source_id=a_id,
                                target_id=c_id,
                                rel_type=rel_type,
                                score=0.6,
                                reason=CompletionReason.TRANSITIVE_RELATION,
                                evidence=evidence,
                            )
                        )
        return results

    def _inverse_suggestions(self) -> List[CompletionSuggestion]:
        """If A→(rel_type)→B exists, suggest B→(inverse(rel_type))→A."""
        existing = self._existing_triples()
        results: List[CompletionSuggestion] = []
        for r in self._kg.relationships.values():
            inv_type = _INVERSE_MAP.get(r.relationship_type)
            if not inv_type:
                continue
            if (r.target_id, inv_type, r.source_id) not in existing:
                evidence = (
                    f"'{inv_type}' is the inverse of '{r.relationship_type}'"
                )
                results.append(
                    CompletionSuggestion(
                        source_id=r.target_id,
                        target_id=r.source_id,
                        rel_type=inv_type,
                        score=round(r.confidence * 0.85, 4),
                        reason=CompletionReason.INVERSE_RELATION,
                        evidence=evidence,
                    )
                )
        return results

    def _type_compatibility_suggestions(self) -> List[CompletionSuggestion]:
        """Entities of the same type sharing a common relationship partner."""
        existing = self._existing_triples()
        # For each entity type, collect entities that share ≥1 target via
        # *the same* rel_type.  Score = fraction of shared targets.
        typed_adj = self._typed_adjacency()
        results: List[CompletionSuggestion] = []
        # Group entity IDs by entity_type
        by_type: Dict[str, List[str]] = {}
        for eid, ent in self._kg.entities.items():
            by_type.setdefault(ent.entity_type, []).append(eid)

        for etype, eids in by_type.items():
            if len(eids) < 2:
                continue
            for i, a_id in enumerate(eids):
                for b_id in eids[i + 1:]:
                    a_map = typed_adj.get(a_id, {})
                    b_map = typed_adj.get(b_id, {})
                    all_rtypes = set(a_map) | set(b_map)
                    for rtype in all_rtypes:
                        a_tgts = a_map.get(rtype, set())
                        b_tgts = b_map.get(rtype, set())
                        shared = a_tgts & b_tgts
                        if not shared:
                            continue
                        score = len(shared) / max(len(a_tgts | b_tgts), 1) * 0.7
                        if score < 0.1:
                            continue
                        if (a_id, rtype, b_id) not in existing:
                            evidence = (
                                f"Both are '{etype}' entities sharing "
                                f"{len(shared)} '{rtype}' target(s)"
                            )
                            results.append(
                                CompletionSuggestion(
                                    source_id=a_id,
                                    target_id=b_id,
                                    rel_type=rtype,
                                    score=round(score, 4),
                                    reason=CompletionReason.TYPE_COMPATIBILITY,
                                    evidence=evidence,
                                )
                            )
        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _name(self, entity_id: str) -> str:
        ent = self._kg.entities.get(entity_id)
        return ent.name if ent else entity_id
