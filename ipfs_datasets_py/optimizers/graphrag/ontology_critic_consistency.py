"""Consistency scoring for GraphRAG ontology critic."""

from __future__ import annotations

import functools

from typing import Any, Dict


@functools.lru_cache(maxsize=512)
def _has_cycle_from_edges(edges: tuple[tuple[str, str], ...]) -> bool:
    """Return True if *edges* contain a directed cycle.

    Uses Kahn's topological-sort algorithm to avoid recursion-depth failures
    on deep hierarchy chains. Cached so repeated evaluations of identical
    relationship graphs avoid recomputing cycle checks.
    """
    if not edges:
        return False

    adj: dict[str, list[str]] = {}
    indegree: dict[str, int] = {}

    for src, tgt in edges:
        adj.setdefault(src, []).append(tgt)
        indegree.setdefault(src, 0)
        indegree[tgt] = indegree.get(tgt, 0) + 1

    queue: list[str] = [n for n, deg in indegree.items() if deg == 0]
    visited_count = 0
    head = 0

    while head < len(queue):
        node = queue[head]
        head += 1
        visited_count += 1

        for nb in adj.get(node, []):
            indegree[nb] -= 1
            if indegree[nb] == 0:
                queue.append(nb)

    return visited_count != len(indegree)


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

    invalid_refs = 0
    edges: list[tuple[str, str]] = []
    for rel in relationships:
        if not isinstance(rel, dict):
            continue
        if rel.get("source_id") not in entity_ids:
            invalid_refs += 1
        if rel.get("target_id") not in entity_ids:
            invalid_refs += 1
        if rel.get("type") in ("is_a", "part_of"):
            src = rel.get("source_id")
            tgt = rel.get("target_id")
            if isinstance(src, str) and isinstance(tgt, str) and src and tgt:
                edges.append((src, tgt))

    total_ref_slots = len(relationships) * 2
    ref_score = 1.0 if total_ref_slots == 0 else max(0.0, 1.0 - invalid_refs / total_ref_slots)

    # Penalty: duplicate entity IDs
    all_ids = [e.get("id") for e in entities if isinstance(e, dict) and e.get("id")]
    dup_ratio = (len(all_ids) - len(set(all_ids))) / max(len(all_ids), 1)
    dup_score = 1.0 - dup_ratio

    # Penalty: circular is_a / part_of chains.
    edges.sort()
    edges_key = tuple(edges)
    cycle_penalty = 0.15 if (edges_key and _has_cycle_from_edges(edges_key)) else 0.0

    score = ref_score * 0.5 + dup_score * 0.3 + (1.0 - cycle_penalty) * 0.2
    return round(min(max(score, 0.0), 1.0), 4)
