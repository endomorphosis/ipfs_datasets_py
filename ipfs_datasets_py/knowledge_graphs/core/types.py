"""
Type aliases, TypedDicts, and Protocols for the core graph engine layer.

These definitions live in one place so public-facing method signatures can use
precise types instead of ``Any`` or bare ``Dict[str, Any]``.

Workstream I: Improve typing at boundaries.

Usage::

    from ipfs_datasets_py.knowledge_graphs.core.types import (
        GraphProperties,
        NodeLabels,
        GraphStats,
        StorageBackend,
    )
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional, Protocol, Tuple, TypedDict

__all__ = [
    # Type aliases
    "GraphProperties",
    "NodeLabels",
    "CID",
    # TypedDicts
    "GraphStats",
    "NodeRecord",
    "RelationshipRecord",
    "WALStats",
    "QuerySummary",
    # Protocols
    "StorageBackend",
    "GraphEngineProtocol",
]


# ---------------------------------------------------------------------------
# Simple type aliases
# ---------------------------------------------------------------------------

#: Property bag for graph nodes and relationships.
GraphProperties = Dict[str, Any]

#: List of label strings attached to a node.
NodeLabels = List[str]

#: Content-Addressable Identifier (IPFS CID) as a plain string.
CID = str


# ---------------------------------------------------------------------------
# TypedDicts — structured dict shapes returned by public APIs
# ---------------------------------------------------------------------------

class GraphStats(TypedDict, total=False):
    """Return type of :meth:`GraphEngine.get_stats` and similar methods."""

    node_count: int
    relationship_count: int
    index_count: int
    storage_backend: Optional[str]


class NodeRecord(TypedDict, total=False):
    """Serialized form of a node (used in export / WAL payloads)."""

    id: str
    labels: NodeLabels
    properties: GraphProperties


class RelationshipRecord(TypedDict, total=False):
    """Serialized form of a relationship (used in export / WAL payloads)."""

    id: str
    type: str
    start_node: str
    end_node: str
    properties: GraphProperties


class WALStats(TypedDict, total=False):
    """Return type of :meth:`WriteAheadLog.get_stats`."""

    head_cid: Optional[CID]
    entry_count: int
    needs_compaction: bool
    compaction_threshold: int


class QuerySummary(TypedDict, total=False):
    """Summary dict included in every :class:`~neo4j_compat.result.Result`."""

    query_type: str
    query: str
    records_returned: int
    ir_operations: int
    error: str
    error_type: str
    error_stage: str
    error_class: str


# ---------------------------------------------------------------------------
# Protocols — structural interfaces
# ---------------------------------------------------------------------------

class StorageBackend(Protocol):
    """
    Minimal interface that any storage backend must satisfy.

    :class:`~ipfs_datasets_py.knowledge_graphs.storage.ipld_backend.IPLDBackend`
    is the primary implementation.  Tests can supply lightweight in-memory stubs
    as long as they implement these four methods.
    """

    def store(
        self,
        data: Any,
        pin: Optional[bool] = None,
        codec: str = "dag-json",
    ) -> CID:
        """Store *data* and return its CID."""
        ...

    def retrieve(self, cid: CID) -> bytes:
        """Retrieve raw bytes for the given CID."""
        ...

    def retrieve_json(self, cid: CID) -> Any:
        """Retrieve and JSON-decode the data at *cid*."""
        ...

    def store_json(self, data: Dict[str, Any]) -> CID:
        """JSON-encode *data*, store it, and return the CID."""
        ...


class GraphEngineProtocol(Protocol):
    """
    Structural interface that any graph engine must satisfy.

    Both :class:`~ipfs_datasets_py.knowledge_graphs.core.graph_engine.GraphEngine`
    and :class:`~ipfs_datasets_py.knowledge_graphs.core._legacy_graph_engine._LegacyGraphEngine`
    implement this protocol.
    """

    def create_node(
        self,
        labels: Optional[NodeLabels] = None,
        properties: Optional[GraphProperties] = None,
    ) -> Any:
        """Create and return a new node."""
        ...

    def get_node(self, node_id: str) -> Optional[Any]:
        """Return the node with *node_id*, or None."""
        ...

    def find_nodes(
        self,
        labels: Optional[NodeLabels] = None,
        properties: Optional[GraphProperties] = None,
        limit: Optional[int] = None,
    ) -> List[Any]:
        """Return nodes matching the given criteria."""
        ...

    def create_relationship(
        self,
        rel_type: str,
        start_node: str,
        end_node: str,
        properties: Optional[GraphProperties] = None,
    ) -> Any:
        """Create and return a new relationship."""
        ...
