"""Utilities for comparing and diffing ontologies.

Provides functions to compare two ontologies and produce human-readable diffs
showing entities and relationships that were added, removed, or modified.

Example::

    from ipfs_datasets_py.optimizers.graphrag.ontology_diff import (
        diff_ontologies,
        format_diff,
        DiffResult,
    )

    # Compare two ontology versions
    before = {
        "entities": [
            {"id": "e1", "type": "Person", "text": "Alice", "confidence": 0.9},
            {"id": "e2", "type": "Organization", "text": "ACME", "confidence": 0.8},
        ],
        "relationships": [
            {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "works_for"},
        ],
    }

    after = {
        "entities": [
            {"id": "e1", "type": "Person", "text": "Alice", "confidence": 0.95},  # confidence changed
            {"id": "e3", "type": "Location", "text": "NYC", "confidence": 0.85},  # new entity
        ],
        "relationships": [
            {"id": "r2", "source_id": "e1", "target_id": "e3", "type": "lives_in"},  # new rel
        ],
    }

    diff = diff_ontologies(before, after)
    print(format_diff(diff))

This module is useful for:
- Tracking ontology evolution over refinement rounds
- Debugging changes made by refinement actions
- Generating change logs for ontology versions
- Quality assurance on refinement outcomes

"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Set


@dataclass
class DiffResult:
    """Result of comparing two ontologies.

    Attributes:
        entities_added: Entities present in `after` but not in `before`.
        entities_removed: Entities present in `before` but not in `after`.
        entities_modified: Entities present in both but with different attributes.
        relationships_added: Relationships present in `after` but not in `before`.
        relationships_removed: Relationships present in `before` but not in `after`.
        relationships_modified: Relationships present in both but with different attributes.
        metadata: Additional diff metadata (e.g., timestamp, diff_version).
    """

    entities_added: List[Dict[str, Any]] = field(default_factory=list)
    entities_removed: List[Dict[str, Any]] = field(default_factory=list)
    entities_modified: List[Dict[str, Any]] = field(default_factory=list)
    relationships_added: List[Dict[str, Any]] = field(default_factory=list)
    relationships_removed: List[Dict[str, Any]] = field(default_factory=list)
    relationships_modified: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def has_changes(self) -> bool:
        """Check if there are any changes between the two ontologies.

        Returns:
            True if any entities or relationships were added, removed, or modified.
        """
        return bool(
            self.entities_added
            or self.entities_removed
            or self.entities_modified
            or self.relationships_added
            or self.relationships_removed
            or self.relationships_modified
        )

    @property
    def total_changes(self) -> int:
        """Count total number of changes.

        Returns:
            Sum of all added, removed, and modified items.
        """
        return (
            len(self.entities_added)
            + len(self.entities_removed)
            + len(self.entities_modified)
            + len(self.relationships_added)
            + len(self.relationships_removed)
            + len(self.relationships_modified)
        )


def diff_ontologies(
    before: Dict[str, Any],
    after: Dict[str, Any],
    compare_confidence: bool = True,
    confidence_threshold: float = 0.01,
) -> DiffResult:
    """Compare two ontologies and produce a diff.

    Args:
        before: The earlier/original ontology (dict with ``entities`` and
            ``relationships`` keys).
        after: The later/updated ontology (same structure).
        compare_confidence: If True, entities/relationships with different
            confidence scores are considered modified. If False, confidence
            changes are ignored.
        confidence_threshold: Minimum confidence delta to consider a change.
            Only used if ``compare_confidence=True``.

    Returns:
        A :class:`DiffResult` containing all additions, removals, and modifications.

    Example::

        >>> before = {"entities": [{"id": "e1", "text": "Alice"}], "relationships": []}
        >>> after = {"entities": [{"id": "e1", "text": "Alice"}, {"id": "e2", "text": "Bob"}], "relationships": []}
        >>> diff = diff_ontologies(before, after)
        >>> len(diff.entities_added)
        1
    """
    before_entities = {e["id"]: e for e in before.get("entities", [])}
    after_entities = {e["id"]: e for e in after.get("entities", [])}

    before_rels = {r["id"]: r for r in before.get("relationships", [])}
    after_rels = {r["id"]: r for r in after.get("relationships", [])}

    # Compute entity diffs
    entities_added = [after_entities[eid] for eid in set(after_entities) - set(before_entities)]
    entities_removed = [before_entities[eid] for eid in set(before_entities) - set(after_entities)]

    entities_modified = []
    for eid in set(before_entities) & set(after_entities):
        if _is_entity_different(
            before_entities[eid],
            after_entities[eid],
            compare_confidence=compare_confidence,
            confidence_threshold=confidence_threshold,
        ):
            entities_modified.append({
                "id": eid,
                "before": before_entities[eid],
                "after": after_entities[eid],
            })

    # Compute relationship diffs
    rels_added = [after_rels[rid] for rid in set(after_rels) - set(before_rels)]
    rels_removed = [before_rels[rid] for rid in set(before_rels) - set(after_rels)]

    rels_modified = []
    for rid in set(before_rels) & set(after_rels):
        if _is_relationship_different(
            before_rels[rid],
            after_rels[rid],
            compare_confidence=compare_confidence,
            confidence_threshold=confidence_threshold,
        ):
            rels_modified.append({
                "id": rid,
                "before": before_rels[rid],
                "after": after_rels[rid],
            })

    return DiffResult(
        entities_added=entities_added,
        entities_removed=entities_removed,
        entities_modified=entities_modified,
        relationships_added=rels_added,
        relationships_removed=rels_removed,
        relationships_modified=rels_modified,
    )


def _is_entity_different(
    e1: Dict[str, Any],
    e2: Dict[str, Any],
    compare_confidence: bool,
    confidence_threshold: float,
) -> bool:
    """Check if two entities have meaningful differences.

    Compares ``type``, ``text``, ``properties``, and optionally ``confidence``.
    """
    if e1.get("type") != e2.get("type"):
        return True
    if e1.get("text") != e2.get("text"):
        return True
    if e1.get("properties", {}) != e2.get("properties", {}):
        return True

    if compare_confidence:
        conf_delta = abs(e1.get("confidence", 1.0) - e2.get("confidence", 1.0))
        if conf_delta >= confidence_threshold:
            return True

    return False


def _is_relationship_different(
    r1: Dict[str, Any],
    r2: Dict[str, Any],
    compare_confidence: bool,
    confidence_threshold: float,
) -> bool:
    """Check if two relationships have meaningful differences.

    Compares ``type``, ``source_id``, ``target_id``, ``direction``, and optionally ``confidence``.
    """
    if r1.get("type") != r2.get("type"):
        return True
    if r1.get("source_id") != r2.get("source_id"):
        return True
    if r1.get("target_id") != r2.get("target_id"):
        return True
    if r1.get("direction") != r2.get("direction"):
        return True
    if r1.get("properties", {}) != r2.get("properties", {}):
        return True

    if compare_confidence:
        conf_delta = abs(r1.get("confidence", 1.0) - r2.get("confidence", 1.0))
        if conf_delta >= confidence_threshold:
            return True

    return False


def format_diff(diff: DiffResult, verbose: bool = False) -> str:
    """Format a diff result as a human-readable string.

    Args:
        diff: The :class:`DiffResult` to format.
        verbose: If True, include full details for each change. If False,
            show summary counts only.

    Returns:
        Formatted diff string.

    Example::

        >>> diff = diff_ontologies(before, after)
        >>> print(format_diff(diff))
        Ontology Diff
        =============
        Entities:
          +2 added
          -1 removed
          ~3 modified
        Relationships:
          +1 added
          -0 removed
          ~1 modified
    """
    lines = ["Ontology Diff", "=" * 13, ""]

    # Entity summary
    lines.append("Entities:")
    lines.append(f"  +{len(diff.entities_added)} added")
    lines.append(f"  -{len(diff.entities_removed)} removed")
    lines.append(f"  ~{len(diff.entities_modified)} modified")
    lines.append("")

    # Relationship summary
    lines.append("Relationships:")
    lines.append(f"  +{len(diff.relationships_added)} added")
    lines.append(f"  -{len(diff.relationships_removed)} removed")
    lines.append(f"  ~{len(diff.relationships_modified)} modified")
    lines.append("")

    if verbose:
        # Show detailed changes
        if diff.entities_added:
            lines.append("Entities Added:")
            for e in diff.entities_added:
                lines.append(f"  + {e.get('id')}: {e.get('text')} ({e.get('type')})")
            lines.append("")

        if diff.entities_removed:
            lines.append("Entities Removed:")
            for e in diff.entities_removed:
                lines.append(f"  - {e.get('id')}: {e.get('text')} ({e.get('type')})")
            lines.append("")

        if diff.entities_modified:
            lines.append("Entities Modified:")
            for change in diff.entities_modified:
                eid = change["id"]
                before = change["before"]
                after = change["after"]
                lines.append(f"  ~ {eid}:")
                for key in ["text", "type", "confidence", "properties"]:
                    b_val = before.get(key)
                    a_val = after.get(key)
                    if b_val != a_val:
                        lines.append(f"      {key}: {b_val} → {a_val}")
            lines.append("")

        if diff.relationships_added:
            lines.append("Relationships Added:")
            for r in diff.relationships_added:
                lines.append(
                    f"  + {r.get('id')}: {r.get('source_id')} --{r.get('type')}--> {r.get('target_id')}"
                )
            lines.append("")

        if diff.relationships_removed:
            lines.append("Relationships Removed:")
            for r in diff.relationships_removed:
                lines.append(
                    f"  - {r.get('id')}: {r.get('source_id')} --{r.get('type')}--> {r.get('target_id')}"
                )
            lines.append("")

        if diff.relationships_modified:
            lines.append("Relationships Modified:")
            for change in diff.relationships_modified:
                rid = change["id"]
                before = change["before"]
                after = change["after"]
                lines.append(f"  ~ {rid}:")
                for key in ["type", "source_id", "target_id", "confidence", "direction", "properties"]:
                    b_val = before.get(key)
                    a_val = after.get(key)
                    if b_val != a_val:
                        lines.append(f"      {key}: {b_val} → {a_val}")
            lines.append("")

    lines.append(f"Total changes: {diff.total_changes}")

    return "\n".join(lines)


def compute_diff_stats(diff: DiffResult) -> Dict[str, Any]:
    """Compute summary statistics for a diff.

    Args:
        diff: The :class:`DiffResult` to analyze.

    Returns:
        Dict with keys:
        - ``entities_net_change``: Number of entities added minus removed.
        - ``relationships_net_change``: Number of relationships added minus removed.
        - ``modification_rate``: Fraction of items that were modified (0.0-1.0).
        - ``has_changes``: Boolean indicating if any changes exist.

    Example::

        >>> stats = compute_diff_stats(diff)  
        >>> stats["entities_net_change"]
        2  # 3 added, 1 removed -> net +2
    """
    total_before = (
        len(diff.entities_removed)
        + len(diff.entities_modified)
        + len(diff.relationships_removed)
        + len(diff.relationships_modified)
    )
    total_after = (
        len(diff.entities_added)
        + len(diff.entities_modified)
        + len(diff.relationships_added)
        + len(diff.relationships_modified)
    )

    total_items = max(total_before, total_after, 1)  # Avoid division by zero

    modification_rate = (
        len(diff.entities_modified) + len(diff.relationships_modified)
    ) / total_items

    return {
        "entities_net_change": len(diff.entities_added) - len(diff.entities_removed),
        "relationships_net_change": len(diff.relationships_added) - len(diff.relationships_removed),
        "modification_rate": modification_rate,
        "has_changes": diff.has_changes,
        "total_changes": diff.total_changes,
    }
