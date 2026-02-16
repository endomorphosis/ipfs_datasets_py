"""
Core lineage tracking functionality.

This module provides the main LineageTracker class and LineageGraph
implementation. Extracted from cross_document_lineage.py (~4,066 lines) and
cross_document_lineage_enhanced.py (~2,357 lines).
"""

import logging
import uuid
import time
from typing import Dict, List, Any, Optional, Set, Tuple
from collections import defaultdict

try:
    import networkx as nx
    NETWORKX_AVAILABLE = True
except ImportError:
    NETWORKX_AVAILABLE = False
    nx = None

from .types import (
    LineageNode,
    LineageLink,
    LineageDomain,
    LineageBoundary,
    LineageTransformationDetail,
    LineageVersion,
    LineageSubgraph,
)

logger = logging.getLogger(__name__)


class LineageGraph:
    """
    Core graph structure for lineage tracking.
    
    Wraps NetworkX DiGraph with lineage-specific operations.
    
    Attributes:
        graph: Underlying NetworkX directed graph
        nodes: Dict of node_id -> LineageNode
        links: Dict of link_id -> LineageLink
        domains: Dict of domain_id -> LineageDomain
        boundaries: Dict of boundary_id -> LineageBoundary
    """
    
    def __init__(self):
        """Initialize empty lineage graph."""
        if not NETWORKX_AVAILABLE:
            raise ImportError(
                "NetworkX is required for lineage tracking. "
                "Install it with: pip install networkx"
            )
        self._graph = nx.DiGraph()
        self._nodes: Dict[str, LineageNode] = {}
        self._links: Dict[str, LineageLink] = {}
        self._domains: Dict[str, LineageDomain] = {}
        self._boundaries: Dict[str, LineageBoundary] = {}
    
    def add_node(self, node: LineageNode) -> str:
        """
        Add a node to the lineage graph.
        
        Args:
            node: LineageNode to add
            
        Returns:
            Node ID
        """
        self._nodes[node.node_id] = node
        self._graph.add_node(
            node.node_id,
            node_type=node.node_type,
            entity_id=node.entity_id,
            record_type=node.record_type,
            metadata=node.metadata,
            timestamp=node.timestamp
        )
        return node.node_id
    
    def add_link(self, link: LineageLink) -> str:
        """
        Add a link between nodes.
        
        Args:
            link: LineageLink to add
            
        Returns:
            Link ID (source:target:relationship)
        """
        link_id = f"{link.source_id}:{link.target_id}:{link.relationship_type}"
        self._links[link_id] = link
        
        # Add edge based on direction
        if link.direction in ("forward", "bidirectional"):
            self._graph.add_edge(
                link.source_id,
                link.target_id,
                relationship_type=link.relationship_type,
                confidence=link.confidence,
                metadata=link.metadata,
                timestamp=link.timestamp
            )
        
        if link.direction in ("backward", "bidirectional"):
            self._graph.add_edge(
                link.target_id,
                link.source_id,
                relationship_type=f"{link.relationship_type}_inverse",
                confidence=link.confidence,
                metadata=link.metadata,
                timestamp=link.timestamp
            )
        
        return link_id
    
    def get_node(self, node_id: str) -> Optional[LineageNode]:
        """Get node by ID."""
        return self._nodes.get(node_id)
    
    def get_neighbors(self, node_id: str, direction: str = "out") -> List[str]:
        """
        Get neighboring nodes.
        
        Args:
            node_id: Node to get neighbors for
            direction: "out" for successors, "in" for predecessors, "both" for all
            
        Returns:
            List of neighbor node IDs
        """
        if node_id not in self._graph:
            return []
        
        if direction == "out":
            return list(self._graph.successors(node_id))
        elif direction == "in":
            return list(self._graph.predecessors(node_id))
        elif direction == "both":
            return list(set(self._graph.successors(node_id)) | 
                       set(self._graph.predecessors(node_id)))
        else:
            raise ValueError(f"Invalid direction: {direction}")
    
    def find_path(self, source_id: str, target_id: str) -> Optional[List[str]]:
        """
        Find shortest path between two nodes.
        
        Args:
            source_id: Source node ID
            target_id: Target node ID
            
        Returns:
            List of node IDs forming path, or None if no path exists
        """
        try:
            return nx.shortest_path(self._graph, source_id, target_id)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None
    
    def get_subgraph(self, node_ids: List[str]) -> 'LineageGraph':
        """
        Extract subgraph containing specified nodes.
        
        Args:
            node_ids: List of node IDs to include
            
        Returns:
            New LineageGraph with subgraph
        """
        subgraph_obj = LineageGraph()
        
        # Add nodes
        for node_id in node_ids:
            if node_id in self._nodes:
                subgraph_obj.add_node(self._nodes[node_id])
        
        # Add links between included nodes
        for link_id, link in self._links.items():
            if link.source_id in node_ids and link.target_id in node_ids:
                subgraph_obj.add_link(link)
        
        return subgraph_obj
    
    @property
    def node_count(self) -> int:
        """Get number of nodes."""
        return len(self._nodes)
    
    @property
    def link_count(self) -> int:
        """Get number of links."""
        return len(self._links)


class LineageTracker:
    """
    Main lineage tracking system.
    
    Provides high-level API for tracking data lineage across documents,
    systems, and transformations.
    
    Example:
        >>> tracker = LineageTracker()
        >>> tracker.track_node("dataset_1", "dataset", metadata={"name": "users"})
        >>> tracker.track_link("dataset_1", "dataset_2", "derived_from")
        >>> path = tracker.find_lineage_path("dataset_1", "dataset_2")
    """
    
    def __init__(self, 
                 enable_temporal_consistency: bool = False,
                 enable_audit_integration: bool = False):
        """
        Initialize lineage tracker.
        
        Args:
            enable_temporal_consistency: Check temporal consistency of links
            enable_audit_integration: Integrate with audit trails
        """
        self.graph = LineageGraph()
        self._transformation_details: Dict[str, LineageTransformationDetail] = {}
        self._versions: Dict[str, LineageVersion] = {}
        self._temporal_consistency_enabled = enable_temporal_consistency
        self._audit_integration_enabled = enable_audit_integration
        self.logger = logger
    
    def track_node(self,
                   node_id: str,
                   node_type: str,
                   entity_id: Optional[str] = None,
                   record_type: Optional[str] = None,
                   metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Track a new node in the lineage graph.
        
        Args:
            node_id: Unique identifier for the node
            node_type: Type of node (e.g., 'dataset', 'transformation', 'entity')
            entity_id: Optional entity ID
            record_type: Optional record type
            metadata: Optional metadata dictionary
            
        Returns:
            Node ID
            
        Example:
            >>> tracker.track_node("ds_1", "dataset", metadata={"size": 1000})
            'ds_1'
        """
        node = LineageNode(
            node_id=node_id,
            node_type=node_type,
            entity_id=entity_id,
            record_type=record_type,
            metadata=metadata or {},
            timestamp=time.time()
        )
        
        return self.graph.add_node(node)
    
    def track_link(self,
                   source_id: str,
                   target_id: str,
                   relationship_type: str,
                   confidence: float = 1.0,
                   metadata: Optional[Dict[str, Any]] = None,
                   direction: str = "forward") -> str:
        """
        Track a link between two nodes.
        
        Args:
            source_id: Source node ID
            target_id: Target node ID
            relationship_type: Type of relationship
            confidence: Confidence score (0.0-1.0)
            metadata: Optional metadata
            direction: Link direction ('forward', 'backward', 'bidirectional')
            
        Returns:
            Link ID
            
        Example:
            >>> tracker.track_link("ds_1", "ds_2", "derived_from", confidence=0.95)
            'ds_1:ds_2:derived_from'
        """
        # Ensure both nodes exist
        if not self.graph.get_node(source_id):
            raise ValueError(f"Source node {source_id} does not exist")
        if not self.graph.get_node(target_id):
            raise ValueError(f"Target node {target_id} does not exist")
        
        link = LineageLink(
            source_id=source_id,
            target_id=target_id,
            relationship_type=relationship_type,
            confidence=confidence,
            metadata=metadata or {},
            timestamp=time.time(),
            direction=direction
        )
        
        # Check temporal consistency if enabled
        if self._temporal_consistency_enabled:
            self._check_temporal_consistency(source_id, target_id)
        
        return self.graph.add_link(link)
    
    def track_transformation(self,
                            transformation_id: str,
                            operation_type: str,
                            inputs: List[Dict[str, Any]],
                            outputs: List[Dict[str, Any]],
                            parameters: Optional[Dict[str, Any]] = None,
                            impact_level: str = "field",
                            confidence: float = 1.0) -> str:
        """
        Track detailed transformation information.
        
        Args:
            transformation_id: ID of the transformation
            operation_type: Type of operation (e.g., 'filter', 'join', 'aggregate')
            inputs: Input field mappings
            outputs: Output field mappings
            parameters: Operation parameters
            impact_level: Impact level ('field', 'record', 'dataset')
            confidence: Confidence score
            
        Returns:
            Detail ID
        """
        detail_id = str(uuid.uuid4())
        
        detail = LineageTransformationDetail(
            detail_id=detail_id,
            transformation_id=transformation_id,
            operation_type=operation_type,
            inputs=inputs,
            outputs=outputs,
            parameters=parameters or {},
            impact_level=impact_level,
            confidence=confidence,
            timestamp=time.time()
        )
        
        self._transformation_details[detail_id] = detail
        return detail_id
    
    def track_version(self,
                     entity_id: str,
                     version_number: str,
                     changes: str = "",
                     parent_version_id: Optional[str] = None) -> str:
        """
        Track a version of an entity.
        
        Args:
            entity_id: Entity being versioned
            version_number: Version identifier
            changes: Description of changes
            parent_version_id: Optional parent version
            
        Returns:
            Version ID
        """
        version_id = str(uuid.uuid4())
        
        version = LineageVersion(
            version_id=version_id,
            entity_id=entity_id,
            version_number=version_number,
            parent_version_id=parent_version_id,
            changes=changes,
            timestamp=time.time()
        )
        
        self._versions[version_id] = version
        return version_id
    
    def find_lineage_path(self, source_id: str, target_id: str) -> Optional[List[str]]:
        """
        Find lineage path between two entities.
        
        Args:
            source_id: Source entity ID
            target_id: Target entity ID
            
        Returns:
            List of node IDs forming path, or None if no path exists
            
        Example:
            >>> path = tracker.find_lineage_path("ds_1", "ds_3")
            ['ds_1', 'ds_2', 'ds_3']
        """
        return self.graph.find_path(source_id, target_id)
    
    def get_upstream_entities(self, node_id: str, max_hops: int = -1) -> List[str]:
        """
        Get all upstream entities (predecessors).
        
        Args:
            node_id: Node to get upstream entities for
            max_hops: Maximum number of hops (-1 for unlimited)
            
        Returns:
            List of upstream node IDs
        """
        if node_id not in self.graph._graph:
            return []
        
        if max_hops == -1:
            # Get all ancestors
            return list(nx.ancestors(self.graph._graph, node_id))
        else:
            # BFS with limited depth
            upstream = set()
            queue = [(node_id, 0)]
            visited = {node_id}
            
            while queue:
                current, depth = queue.pop(0)
                if depth < max_hops:
                    for pred in self.graph._graph.predecessors(current):
                        if pred not in visited:
                            visited.add(pred)
                            upstream.add(pred)
                            queue.append((pred, depth + 1))
            
            return list(upstream)
    
    def get_downstream_entities(self, node_id: str, max_hops: int = -1) -> List[str]:
        """
        Get all downstream entities (successors).
        
        Args:
            node_id: Node to get downstream entities for
            max_hops: Maximum number of hops (-1 for unlimited)
            
        Returns:
            List of downstream node IDs
        """
        if node_id not in self.graph._graph:
            return []
        
        if max_hops == -1:
            # Get all descendants
            return list(nx.descendants(self.graph._graph, node_id))
        else:
            # BFS with limited depth
            downstream = set()
            queue = [(node_id, 0)]
            visited = {node_id}
            
            while queue:
                current, depth = queue.pop(0)
                if depth < max_hops:
                    for succ in self.graph._graph.successors(current):
                        if succ not in visited:
                            visited.add(succ)
                            downstream.add(succ)
                            queue.append((succ, depth + 1))
            
            return list(downstream)
    
    def query(self, **filters) -> List[LineageNode]:
        """
        Query nodes by filters.
        
        Args:
            **filters: Filter criteria (node_type, entity_id, metadata, etc.)
            
        Returns:
            List of matching LineageNode objects
            
        Example:
            >>> nodes = tracker.query(node_type="dataset")
            >>> nodes = tracker.query(entity_id="user_data")
        """
        results = []
        
        for node_id, node in self.graph._nodes.items():
            matches = True
            
            # Check node_type filter
            if 'node_type' in filters and node.node_type != filters['node_type']:
                matches = False
            
            # Check entity_id filter
            if 'entity_id' in filters and node.entity_id != filters['entity_id']:
                matches = False
            
            # Check metadata filters
            if 'metadata' in filters:
                for key, value in filters['metadata'].items():
                    if key not in node.metadata or node.metadata[key] != value:
                        matches = False
                        break
            
            if matches:
                results.append(node)
        
        return results
    
    def _check_temporal_consistency(self, source_id: str, target_id: str) -> bool:
        """
        Check temporal consistency between source and target nodes.
        
        Args:
            source_id: Source node ID
            target_id: Target node ID
            
        Returns:
            Whether the link is temporally consistent
        """
        source_node = self.graph.get_node(source_id)
        target_node = self.graph.get_node(target_id)
        
        if not source_node or not target_node:
            return True
        
        # Allow small time difference (100ms tolerance)
        if target_node.timestamp < source_node.timestamp - 0.1:
            self.logger.warning(
                f"Temporal inconsistency: target {target_id} ({target_node.timestamp}) "
                f"before source {source_id} ({source_node.timestamp})"
            )
            return False
        
        return True
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the lineage graph.
        
        Returns:
            Dictionary with statistics
        """
        return {
            'node_count': self.graph.node_count,
            'link_count': self.graph.link_count,
            'transformation_count': len(self._transformation_details),
            'version_count': len(self._versions),
            'has_cycles': not nx.is_directed_acyclic_graph(self.graph._graph)
        }
