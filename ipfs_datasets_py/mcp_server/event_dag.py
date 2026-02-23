"""Event DAG, Concurrency, and Ordering.

Implements the MCP++ Event DAG specification from:
https://github.com/endomorphosis/Mcp-Plus-Plus/blob/main/docs/spec/event-dag-ordering.md

Each execution step emits an ``EventNode`` (CID-addressed) that references:
- inputs, proofs, decisions, outputs, receipts
- ``parents[]`` — the causally preceding event CIDs

This creates an append-only, content-addressed execution history that enables:
- **Provenance**: trace exactly what inputs produced what outputs
- **Replay**: walk the DAG from any root to reproduce a computation
- **Partial ordering**: events with disjoint parent sets are concurrent

Public API::

    dag = EventDAG()
    cid_a = dag.append(EventNode(parents=[], intent_cid="...", ...))
    cid_b = dag.append(EventNode(parents=[cid_a], intent_cid="...", ...))

    node_a = dag.get(cid_a)
    frontier = dag.frontier()           # leaf nodes (no children)
    history = dag.walk(cid_b)           # topological walk from cid_b to roots
    rollback = dag.rollback_to(cid_a)   # nodes appended after cid_a
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set

from .cid_artifacts import EventNode


# ---------------------------------------------------------------------------
# EventDAG
# ---------------------------------------------------------------------------

class EventDAG:
    """Append-only, content-addressed Event DAG.

    Nodes are ``EventNode`` instances (from ``cid_artifacts``).  Each node is
    identified by its ``event_cid`` property and references its causal
    predecessors via ``parents``.

    The DAG enforces:
    - **Append-only**: nodes cannot be removed or mutated.
    - **Parent validation**: all parent CIDs must be known before a node is
      appended (unless ``strict=False`` is set at construction time).
    - **Deduplication**: appending the same CID twice is a no-op.

    Attributes:
        strict: If ``True`` (default), raise ``ValueError`` when a node's
            parent CIDs are not yet present in the DAG.
    """

    def __init__(self, *, strict: bool = True) -> None:
        """Initialise an empty Event DAG.

        Args:
            strict: Enforce parent-CID validation on append.
        """
        self.strict = strict
        self._nodes: Dict[str, EventNode] = {}
        # Reverse index: parent_cid → set of child event_cids
        self._children: Dict[str, Set[str]] = {}

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def append(self, node: EventNode) -> str:
        """Append an ``EventNode`` to the DAG and return its ``event_cid``.

        If *strict* mode is enabled, all parent CIDs must already be present
        in the DAG.  Appending a node whose CID is already in the DAG is a
        no-op (idempotent).

        Args:
            node: The event node to append.

        Returns:
            The ``event_cid`` of the newly appended (or existing) node.

        Raises:
            ValueError: In strict mode, when a parent CID is unknown.
        """
        cid = node.event_cid

        # Idempotent — already known
        if cid in self._nodes:
            return cid

        # Parent validation
        if self.strict:
            for parent_cid in node.parents:
                if parent_cid not in self._nodes:
                    raise ValueError(
                        f"Unknown parent CID {parent_cid!r}; append parents before children "
                        f"or set strict=False"
                    )

        self._nodes[cid] = node

        # Update reverse index
        for parent_cid in node.parents:
            self._children.setdefault(parent_cid, set()).add(cid)

        return cid

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get(self, event_cid: str) -> Optional[EventNode]:
        """Retrieve a node by its CID.

        Args:
            event_cid: The content-addressed identifier.

        Returns:
            The matching ``EventNode``, or ``None`` if not found.
        """
        return self._nodes.get(event_cid)

    def __contains__(self, event_cid: str) -> bool:
        """Return ``True`` if *event_cid* is present in the DAG."""
        return event_cid in self._nodes

    def __len__(self) -> int:
        """Return the number of nodes in the DAG."""
        return len(self._nodes)

    # ------------------------------------------------------------------
    # Frontier (leaf nodes)
    # ------------------------------------------------------------------

    def frontier(self) -> List[str]:
        """Return the CIDs of all leaf nodes (nodes with no children).

        The *frontier* represents the current "latest" state of the DAG — all
        events that have not yet been superseded by a child event.

        Returns:
            List of ``event_cid`` strings with no known children.
        """
        return [cid for cid in self._nodes if cid not in self._children]

    # ------------------------------------------------------------------
    # Causal walk (topological traversal towards roots)
    # ------------------------------------------------------------------

    def walk(self, event_cid: str) -> List[str]:
        """Return a topological ordering of *event_cid* and all its ancestors.

        Uses iterative BFS from *event_cid* toward roots.  The returned list
        is ordered by reverse BFS depth: *event_cid* is first, root nodes last.
        Nodes that share ancestors are deduplicated (each appears once).

        Args:
            event_cid: The CID to start the walk from.

        Returns:
            List of ``event_cid`` strings in reverse-causal order, or an
            empty list if *event_cid* is not in the DAG.
        """
        if event_cid not in self._nodes:
            return []

        visited: List[str] = []
        seen: Set[str] = set()
        queue: List[str] = [event_cid]

        while queue:
            current = queue.pop(0)
            if current in seen:
                continue
            seen.add(current)
            visited.append(current)
            node = self._nodes.get(current)
            if node:
                for parent_cid in node.parents:
                    if parent_cid not in seen:
                        queue.append(parent_cid)

        return visited

    # ------------------------------------------------------------------
    # Rollback helpers
    # ------------------------------------------------------------------

    def descendants(self, event_cid: str) -> List[str]:
        """Return all nodes that are (direct or transitive) children of *event_cid*.

        This is used for rollback analysis: given a "rollback-to" target, find
        every node that was appended after it (i.e. every descendant).

        Args:
            event_cid: The ancestor CID.

        Returns:
            List of descendant ``event_cid`` strings (BFS order, not including
            *event_cid* itself).
        """
        result: List[str] = []
        seen: Set[str] = set()
        queue: List[str] = list(self._children.get(event_cid, set()))

        while queue:
            current = queue.pop(0)
            if current in seen:
                continue
            seen.add(current)
            result.append(current)
            for child_cid in self._children.get(current, set()):
                if child_cid not in seen:
                    queue.append(child_cid)

        return result

    def rollback_to(self, event_cid: str) -> List[str]:
        """Return the event CIDs that would need to be undone to roll back to *event_cid*.

        Alias for ``descendants()`` — the list of nodes appended after
        *event_cid* that form the "rollback set".

        Args:
            event_cid: The target event to roll back to.

        Returns:
            List of descendant ``event_cid`` strings.
        """
        return self.descendants(event_cid)

    # ------------------------------------------------------------------
    # Concurrency detection
    # ------------------------------------------------------------------

    def are_concurrent(self, cid_a: str, cid_b: str) -> bool:
        """Return ``True`` if *cid_a* and *cid_b* are causally independent.

        Two events are concurrent (have no causal relationship) when neither
        is an ancestor of the other.  This is the MCP++ partial-order model:
        concurrent events need not be globally ordered.

        Args:
            cid_a: First event CID.
            cid_b: Second event CID.

        Returns:
            ``True`` when neither event is an ancestor of the other.
        """
        ancestors_a = set(self.walk(cid_a))
        ancestors_b = set(self.walk(cid_b))
        # b is an ancestor of a ↔ b ∈ ancestors_a
        # a is an ancestor of b ↔ a ∈ ancestors_b
        return cid_b not in ancestors_a and cid_a not in ancestors_b

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:  # pragma: no cover
        return f"EventDAG({len(self._nodes)} nodes, frontier={len(self.frontier())})"


# ---------------------------------------------------------------------------
# Convenience builder
# ---------------------------------------------------------------------------

def build_linear_dag(nodes: Iterable[EventNode]) -> EventDAG:
    """Build an EventDAG from a sequence of nodes treated as a linear chain.

    Each node (after the first) automatically gets the previous node's
    ``event_cid`` prepended to its ``parents`` list before appending.

    This is a convenience helper for tests and single-agent scenarios.

    Args:
        nodes: Iterable of ``EventNode`` objects (order matters).

    Returns:
        A populated ``EventDAG``.
    """
    dag = EventDAG(strict=False)
    prev_cid: Optional[str] = None
    for node in nodes:
        if prev_cid is not None and prev_cid not in node.parents:
            node.parents = [prev_cid] + node.parents
        prev_cid = dag.append(node)
    return dag
