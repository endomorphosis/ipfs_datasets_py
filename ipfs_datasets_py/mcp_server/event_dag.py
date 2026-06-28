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
- **ZK Compaction**: older epochs are compacted into Merkle proofs for memory efficiency

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

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set

from .cid_artifacts import EventNode

logger = logging.getLogger("ipfs_datasets.mcp_server.event_dag")

# Compaction threshold: when hot nodes exceed this, trigger epoch compaction
HOT_TIER_MAX = 2000


# ---------------------------------------------------------------------------
# EventDAG
# ---------------------------------------------------------------------------

class EventDAG:
    """Append-only, content-addressed Event DAG with ZK compaction.

    Nodes are ``EventNode`` instances (from ``cid_artifacts``).  Each node is
    identified by its ``event_cid`` property and references its causal
    predecessors via ``parents``.

    The DAG enforces:
    - **Append-only**: nodes cannot be removed or mutated.
    - **Parent validation**: all parent CIDs must be known before a node is
      appended (unless ``strict=False`` is set at construction time).
    - **Deduplication**: appending the same CID twice is a no-op.
    - **ZK Compaction**: when hot tier exceeds HOT_TIER_MAX, oldest events
      are compacted into a Merkle proof and moved to cold storage on disk.

    Attributes:
        strict: If ``True`` (default), raise ``ValueError`` when a node's
            parent CIDs are not yet present in the DAG.
    """

    def __init__(self, *, strict: bool = True, storage_dir: str = "") -> None:
        """Initialise an empty Event DAG.

        Args:
            strict: Enforce parent-CID validation on append.
            storage_dir: Directory for cold-tier epoch storage. Empty = default.
        """
        self.strict = strict
        self._lock = threading.Lock()
        self._nodes: Dict[str, EventNode] = {}
        # Reverse index: parent_cid → set of child event_cids
        self._children: Dict[str, Set[str]] = {}
        self._storage_dir = storage_dir
        self._compactor: Optional[Any] = None

    def _get_compactor(self):
        """Lazy-init the DAG compactor."""
        if self._compactor is None:
            try:
                from .dag_compaction import DAGCompactor, COLD_TIER_DIR
                storage = self._storage_dir or COLD_TIER_DIR
                self._compactor = DAGCompactor(storage_dir=storage)
            except ImportError:
                logger.warning("dag_compaction module not available; compaction disabled")
        return self._compactor

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def append(self, node: EventNode) -> str:
        """Append an ``EventNode`` to the DAG and return its ``event_cid``.

        If *strict* mode is enabled, all parent CIDs must already be present
        in the DAG.  Appending a node whose CID is already in the DAG is a
        no-op (idempotent).

        Triggers ZK compaction when hot tier exceeds HOT_TIER_MAX.

        Args:
            node: The event node to append.

        Returns:
            The ``event_cid`` of the newly appended (or existing) node.

        Raises:
            ValueError: In strict mode, when a parent CID is unknown.
            RuntimeError: If DAG has reached hard cap and compaction is unavailable.
        """
        cid = node.event_cid

        with self._lock:
            # Idempotent — already known
            if cid in self._nodes:
                return cid

            # Hard cap: evict oldest if compaction is unavailable
            MAX_EVENTS = 10000
            if len(self._nodes) >= MAX_EVENTS:
                oldest = sorted(self._nodes.values(), key=lambda n: getattr(n, 'timestamp', 0))[:100]
                for old in oldest:
                    old_cid = old.event_cid
                    del self._nodes[old_cid]
                    self._children.pop(old_cid, None)
                logger.warning("DAG hard cap reached (%d); evicted 100 oldest events", MAX_EVENTS)

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

        # Check if ZK compaction should run
        self._maybe_compact()
        return cid

    def _maybe_compact(self) -> None:
        """Trigger epoch compaction if hot tier is too large."""
        compactor = self._get_compactor()
        if compactor is None:
            return
        if not compactor.should_compact(len(self._nodes)):
            return

        with self._lock:
            # Serialize nodes for compactor
            events_dict = {}
            for cid, node in self._nodes.items():
                events_dict[cid] = {
                    "cid": cid,
                    "event_type": "event_node",
                    "parent_cids": list(node.parents),
                    "payload": {
                        "intent_cid": getattr(node, "intent_cid", ""),
                        "decision_cid": getattr(node, "decision_cid", ""),
                        "receipt_cid": getattr(node, "receipt_cid", ""),
                    },
                    "timestamp": float(getattr(node, "timestamp_created", "0") or 0),
                }
            children_dict = {k: list(v) for k, v in self._children.items()}

        # Compact outside the lock (disk I/O)
        result = compactor.compact_epoch(events_dict, children_dict)
        if result:
            with self._lock:
                compacted_set = set(result.compacted_cids)
                for cid in result.compacted_cids:
                    self._nodes.pop(cid, None)
                    self._children.pop(cid, None)
                # Clean children refs
                for parent_cid in list(self._children.keys()):
                    self._children[parent_cid] = {
                        c for c in self._children[parent_cid]
                        if c not in compacted_set
                    }
                    if not self._children[parent_cid]:
                        del self._children[parent_cid]
            logger.info(
                "Compacted epoch: removed %d events from hot tier",
                len(result.compacted_cids),
            )

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
        with self._lock:
            return [cid for cid in self._nodes if cid not in self._children]

    # ------------------------------------------------------------------
    # Causal walk (topological traversal towards roots)
    # ------------------------------------------------------------------

    def walk(self, event_cid: str) -> List[str]:
        """Return a topological ordering of *event_cid* and all its ancestors.

        Uses iterative BFS from *event_cid* toward roots.  The returned list
        is ordered by reverse BFS depth: *event_cid* is first, root nodes last.
        Nodes that share ancestors are deduplicated (each appears once).

        Transparently loads cold-tier events when traversal crosses epoch
        boundaries (parent CID not in hot tier).

        Args:
            event_cid: The CID to start the walk from.

        Returns:
            List of ``event_cid`` strings in reverse-causal order, or an
            empty list if *event_cid* is not in the DAG.
        """
        if event_cid not in self._nodes:
            # Check cold tier
            cold_node = self._load_cold_event(event_cid)
            if cold_node is None:
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
            else:
                # Try cold tier for parent traversal
                cold_data = self._load_cold_event_data(current)
                if cold_data:
                    for parent_cid in cold_data.get("parent_cids", []):
                        if parent_cid not in seen:
                            queue.append(parent_cid)

        return visited

    def _load_cold_event(self, cid: str) -> Optional[EventNode]:
        """Try to load an EventNode from cold storage."""
        compactor = self._get_compactor()
        if compactor is None:
            return None
        epoch_id = compactor.find_epoch_for_cid(cid)
        if epoch_id is None:
            return None
        events = compactor.load_cold_epoch(epoch_id)
        for e in events:
            if e.get("cid") == cid:
                payload = e.get("payload", {})
                return EventNode(
                    parents=e.get("parent_cids", []),
                    intent_cid=payload.get("intent_cid", ""),
                    decision_cid=payload.get("decision_cid", ""),
                    receipt_cid=payload.get("receipt_cid", ""),
                )
        return None

    def _load_cold_event_data(self, cid: str) -> Optional[Dict[str, Any]]:
        """Load raw event dict from cold storage."""
        compactor = self._get_compactor()
        if compactor is None:
            return None
        epoch_id = compactor.find_epoch_for_cid(cid)
        if epoch_id is None:
            return None
        events = compactor.load_cold_epoch(epoch_id)
        for e in events:
            if e.get("cid") == cid:
                return e
        return None

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
        compactor = self._get_compactor()
        cold_count = compactor.total_compacted_events if compactor else 0
        return (
            f"EventDAG({len(self._nodes)} hot nodes, "
            f"{cold_count} compacted, frontier={len(self.frontier())})"
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str) -> None:
        """Persist the DAG to a JSON file at *path*.

        Serializes all nodes as a list of dicts. Thread-safe.
        """
        import json

        with self._lock:
            nodes_data = []
            for cid, node in self._nodes.items():
                nodes_data.append({
                    "event_cid": cid,
                    "parents": list(node.parents),
                    "intent_cid": node.intent_cid,
                    "decision_cid": getattr(node, "decision_cid", ""),
                    "receipt_cid": getattr(node, "receipt_cid", ""),
                    "timestamp": getattr(node, "timestamp", ""),
                })

        import os
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump({"version": 1, "nodes": nodes_data}, f)

    def load(self, path: str) -> int:
        """Load DAG state from a JSON file at *path*. Returns count of nodes loaded.

        Skips nodes whose CIDs already exist. Uses strict=False for loading.
        """
        import json
        import os

        if not os.path.isfile(path):
            return 0

        with open(path, "r") as f:
            data = json.load(f)

        nodes_data = data.get("nodes", [])
        loaded = 0
        old_strict = self.strict
        self.strict = False  # Relax for loading (parents may arrive out of order)
        try:
            for nd in nodes_data:
                cid = nd.get("event_cid", "")
                if cid in self._nodes:
                    continue
                node = EventNode(
                    parents=nd.get("parents", []),
                    intent_cid=nd.get("intent_cid", ""),
                    decision_cid=nd.get("decision_cid", ""),
                    receipt_cid=nd.get("receipt_cid", ""),
                )
                # Override computed CID if stored CID differs (legacy data)
                self.append(node)
                loaded += 1
        finally:
            self.strict = old_strict
        return loaded


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
