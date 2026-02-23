"""Consistency scoring for GraphRAG ontology critic."""

from __future__ import annotations

import functools

from typing import Any, Dict


def _hierarchy_edges_key(relationships: list[Any]) -> tuple[tuple[str, str], ...]:
    """Return a stable, hashable key for hierarchy-cycle detection.

    Only includes edges from ``is_a`` and ``part_of`` relationships.
    """
    edges: list[tuple[str, str]] = []
    for rel in relationships:
        if not isinstance(rel, dict):
            continue
        if rel.get("type") not in ("is_a", "part_of"):
            continue
        src = rel.get("source_id")
        tgt = rel.get("target_id")
        if isinstance(src, str) and isinstance(tgt, str) and src and tgt:
            edges.append((src, tgt))
    edges.sort()
    return tuple(edges)


@functools.lru_cache(maxsize=512)
def _has_cycle_from_edges(edges: tuple[tuple[str, str], ...]) -> bool:
    """Return True if *edges* contain a directed cycle (DFS).

    Cached so repeated evaluations of identical relationship graphs avoid
    recomputing DFS.
    """
    if not edges:
        return False

    adj: dict[str, list[str]] = {}
    for src, tgt in edges:
        adj.setdefault(src, []).append(tgt)

    visited: set[str] = set()
    rec_stack: set[str] = set()

    def _dfs(node: str) -> bool:
        visited.add(node)
        rec_stack.add(node)
        for nb in adj.get(node, []):
            if nb not in visited:
                if _dfs(nb):
                    return True
            elif nb in rec_stack:
                return True
        rec_stack.discard(node)
        return False

    return any(_dfs(n) for n in adj if n not in visited)


def evaluate_consistency(
    ontology: Dict[str, Any],
    context: Any,
) -> float:
    """Evaluate internal logical consistency.

    Checks for dangling references, duplicate IDs, and circular
    is_a / part_of dependency chains.
    """
    entities = ontology.get("entities", [])
    relationships = ontology.get("relationships", [])

    entity_ids = {e.get("id") for e in entities if isinstance(e, dict) and e.get("id")}

    # Penalty: dangling references
    invalid_refs = 0
    for rel in relationships:
        if not isinstance(rel, dict):
            continue
        if rel.get("source_id") not in entity_ids:
            invalid_refs += 1
        if rel.get("target_id") not in entity_ids:
            invalid_refs += 1

    total_ref_slots = len(relationships) * 2
    ref_score = 1.0 if total_ref_slots == 0 else max(0.0, 1.0 - invalid_refs / total_ref_slots)

    # Penalty: duplicate entity IDs
    all_ids = [e.get("id") for e in entities if isinstance(e, dict) and e.get("id")]
    dup_ratio = (len(all_ids) - len(set(all_ids))) / max(len(all_ids), 1)
    dup_score = 1.0 - dup_ratio

    # Penalty: circular is_a / part_of chains (DFS cycle detection)
    edges_key = _hierarchy_edges_key(relationships)
    cycle_penalty = 0.15 if (edges_key and _has_cycle_from_edges(edges_key)) else 0.0

    score = ref_score * 0.5 + dup_score * 0.3 + (1.0 - cycle_penalty) * 0.2
    return round(min(max(score, 0.0), 1.0), 4)
