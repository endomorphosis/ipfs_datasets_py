"""
Graph Types for Neo4j Compatibility

This module provides Node, Relationship, and Path types that are compatible
with Neo4j's Python driver, but backed by IPLD storage on IPFS.

These types enable Neo4j applications to work with IPFS-stored graphs
without code changes.
"""

from typing import Any, Dict, List, Optional, Sequence, Union


class Node:
    """
    Represents a node in the graph.
    
    Compatible with neo4j.graph.Node.
    
    Attributes:
        id: Node identifier (IPLD CID or internal ID)
        labels: Set of labels assigned to this node
        properties: Dictionary of node properties
    """
    
    def __init__(
        self,
        node_id: Union[str, int],
        labels: Optional[Sequence[str]] = None,
        properties: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize a Node.
        
        Args:
            node_id: Unique identifier for the node
            labels: Labels/types for the node
            properties: Key-value properties
        """
        self._id = node_id
        self._labels = frozenset(labels or [])
        self._properties = dict(properties or {})
    
    @property
    def id(self) -> Union[str, int]:
        """Get the node ID."""
        return self._id
    
    @property
    def labels(self) -> frozenset:
        """Get the node labels as a frozenset."""
        return self._labels
    
    @property
    def properties(self) -> Dict[str, Any]:
        """Get the node properties."""
        return self._properties.copy()
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a property value.
        
        Args:
            key: Property key
            default: Default value if key not found
            
        Returns:
            Property value or default
        """
        return self._properties.get(key, default)
    
    def __getitem__(self, key: str) -> Any:
        """Get a property value by key."""
        return self._properties[key]
    
    def __contains__(self, key: str) -> bool:
        """Check if property exists."""
        return key in self._properties
    
    def __eq__(self, other: object) -> bool:
        """Check equality based on ID."""
        if not isinstance(other, Node):
            return False
        return self._id == other._id
    
    def __hash__(self) -> int:
        """Hash based on ID."""
        return hash(self._id)
    
    def __repr__(self) -> str:
        """String representation."""
        labels_str = ":".join(sorted(self._labels))
        props_str = ", ".join(f"{k}={v!r}" for k, v in sorted(self._properties.items()))
        return f"Node({self._id}, labels={{{labels_str}}}, {{{props_str}}})"


class Relationship:
    """
    Represents a relationship (edge) in the graph.
    
    Compatible with neo4j.graph.Relationship.
    
    Attributes:
        id: Relationship identifier
        type: Relationship type
        start_node: Source node ID or Node object
        end_node: Target node ID or Node object
        properties: Dictionary of relationship properties
    """
    
    def __init__(
        self,
        rel_id: Union[str, int],
        rel_type: str,
        start_node: Union[str, int, Node],
        end_node: Union[str, int, Node],
        properties: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize a Relationship.
        
        Args:
            rel_id: Unique identifier for the relationship
            rel_type: Type of the relationship
            start_node: Source node (ID or Node object)
            end_node: Target node (ID or Node object)
            properties: Key-value properties
        """
        self._id = rel_id
        self._type = rel_type
        self._start_node = start_node if isinstance(start_node, (str, int)) else start_node.id
        self._end_node = end_node if isinstance(end_node, (str, int)) else end_node.id
        self._properties = dict(properties or {})
    
    @property
    def id(self) -> Union[str, int]:
        """Get the relationship ID."""
        return self._id
    
    @property
    def type(self) -> str:
        """Get the relationship type."""
        return self._type
    
    @property
    def start_node(self) -> Union[str, int]:
        """Get the start node ID."""
        return self._start_node
    
    @property
    def end_node(self) -> Union[str, int]:
        """Get the end node ID."""
        return self._end_node
    
    @property
    def properties(self) -> Dict[str, Any]:
        """Get the relationship properties."""
        return self._properties.copy()
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a property value.
        
        Args:
            key: Property key
            default: Default value if key not found
            
        Returns:
            Property value or default
        """
        return self._properties.get(key, default)
    
    def __getitem__(self, key: str) -> Any:
        """Get a property value by key."""
        return self._properties[key]
    
    def __contains__(self, key: str) -> bool:
        """Check if property exists."""
        return key in self._properties
    
    def __eq__(self, other: object) -> bool:
        """Check equality based on ID."""
        if not isinstance(other, Relationship):
            return False
        return self._id == other._id
    
    def __hash__(self) -> int:
        """Hash based on ID."""
        return hash(self._id)
    
    def __repr__(self) -> str:
        """String representation."""
        props_str = ", ".join(f"{k}={v!r}" for k, v in sorted(self._properties.items()))
        return f"Relationship({self._id}, type={self._type!r}, " \
               f"start={self._start_node}, end={self._end_node}, {{{props_str}}})"


class Path:
    """
    Represents a path through the graph.
    
    Compatible with neo4j.graph.Path.
    
    A path is a sequence of alternating nodes and relationships.
    """
    
    def __init__(
        self,
        start_node: Node,
        *relationships_and_nodes: Union[Relationship, Node]
    ):
        """
        Initialize a Path.
        
        Args:
            start_node: The starting node
            *relationships_and_nodes: Alternating relationships and nodes
        """
        self._nodes = [start_node]
        self._relationships = []
        
        # Parse alternating relationships and nodes
        for i, item in enumerate(relationships_and_nodes):
            if i % 2 == 0:
                # Should be a relationship
                if not isinstance(item, Relationship):
                    raise TypeError(f"Expected Relationship at position {i}, got {type(item)}")
                self._relationships.append(item)
            else:
                # Should be a node
                if not isinstance(item, Node):
                    raise TypeError(f"Expected Node at position {i}, got {type(item)}")
                self._nodes.append(item)
        
        # Validate path structure
        if len(self._relationships) != len(self._nodes) - 1:
            raise ValueError("Path must have exactly one more node than relationships")
    
    @property
    def start_node(self) -> Node:
        """Get the start node of the path."""
        return self._nodes[0]
    
    @property
    def end_node(self) -> Node:
        """Get the end node of the path."""
        return self._nodes[-1]
    
    @property
    def nodes(self) -> List[Node]:
        """Get all nodes in the path."""
        return list(self._nodes)
    
    @property
    def relationships(self) -> List[Relationship]:
        """Get all relationships in the path."""
        return list(self._relationships)
    
    def __len__(self) -> int:
        """Get the length of the path (number of relationships)."""
        return len(self._relationships)
    
    def __iter__(self):
        """Iterate over alternating relationships and nodes."""
        for i, rel in enumerate(self._relationships):
            yield rel
            yield self._nodes[i + 1]
    
    def __repr__(self) -> str:
        """String representation."""
        path_str = str(self._nodes[0].id)
        for rel, node in zip(self._relationships, self._nodes[1:]):
            path_str += f"-[:{rel.type}]->{node.id}"
        return f"Path({path_str})"


# Type aliases for convenience
GraphObject = Union[Node, Relationship, Path]
