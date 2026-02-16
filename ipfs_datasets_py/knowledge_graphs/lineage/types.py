"""
Core data types for lineage tracking.

This module contains the fundamental dataclasses used throughout the lineage
tracking system. Extracted from cross_document_lineage.py and
cross_document_lineage_enhanced.py.
"""

import time
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict


@dataclass
class LineageNode:
    """
    Represents a node in the data lineage graph.
    
    A node typically represents a data entity, transformation, or operation
    in the lineage tracking system.
    
    Attributes:
        node_id: Unique identifier for the node
        node_type: Type of node (e.g., 'dataset', 'transformation', 'entity')
        entity_id: Optional ID of the entity this node represents
        record_type: Optional type of record
        metadata: Additional metadata about the node
        timestamp: Creation timestamp
    
    Example:
        >>> node = LineageNode(
        ...     node_id="node_123",
        ...     node_type="dataset",
        ...     metadata={"name": "user_data"}
        ... )
    """
    node_id: str
    node_type: str
    entity_id: Optional[str] = None
    record_type: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return asdict(self)


@dataclass
class LineageLink:
    """
    Represents a link/edge in the data lineage graph.
    
    A link connects two nodes and represents a relationship between them,
    such as data flow, transformation, or derivation.
    
    Attributes:
        source_id: ID of the source node
        target_id: ID of the target node
        relationship_type: Type of relationship (e.g., 'derived_from', 'contains')
        confidence: Confidence score for this relationship (0.0-1.0)
        metadata: Additional metadata about the link
        timestamp: Creation timestamp
        direction: Direction of the link ('forward', 'backward', 'bidirectional')
    
    Example:
        >>> link = LineageLink(
        ...     source_id="node_123",
        ...     target_id="node_456",
        ...     relationship_type="derived_from",
        ...     confidence=0.95
        ... )
    """
    source_id: str
    target_id: str
    relationship_type: str
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    direction: str = "forward"  # forward, backward, bidirectional

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return asdict(self)


@dataclass
class LineageDomain:
    """
    Represents a logical domain in the data lineage graph.
    
    Domains group related nodes and help organize lineage information
    across different systems, applications, or workflows.
    
    Attributes:
        domain_id: Unique identifier for the domain
        name: Human-readable name of the domain
        description: Optional description of the domain
        domain_type: Type of domain (e.g., 'application', 'dataset', 'workflow')
        attributes: Domain-specific attributes
        metadata_schema: Optional validation schema for metadata
        parent_domain_id: Optional parent domain for hierarchical organization
        timestamp: Creation timestamp
    
    Example:
        >>> domain = LineageDomain(
        ...     domain_id="domain_ml",
        ...     name="Machine Learning Pipeline",
        ...     domain_type="workflow"
        ... )
    """
    domain_id: str
    name: str
    description: Optional[str] = None
    domain_type: str = "generic"  # generic, application, dataset, workflow, etc.
    attributes: Dict[str, Any] = field(default_factory=dict)
    metadata_schema: Optional[Dict[str, Any]] = None  # Validation schema for metadata
    parent_domain_id: Optional[str] = None  # For hierarchical domains
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return asdict(self)


@dataclass
class LineageBoundary:
    """
    Represents a boundary between domains in the lineage graph.
    
    Boundaries mark transitions between different systems, organizations,
    or security contexts in the data flow.
    
    Attributes:
        boundary_id: Unique identifier for the boundary
        source_domain_id: ID of the source domain
        target_domain_id: ID of the target domain
        boundary_type: Type of boundary (e.g., 'data_transfer', 'api_call', 'etl_process')
        attributes: Boundary-specific attributes
        constraints: List of constraints applied at this boundary
        timestamp: Creation timestamp
    
    Example:
        >>> boundary = LineageBoundary(
        ...     boundary_id="boundary_123",
        ...     source_domain_id="domain_app",
        ...     target_domain_id="domain_db",
        ...     boundary_type="api_call"
        ... )
    """
    boundary_id: str
    source_domain_id: str
    target_domain_id: str
    boundary_type: str  # data_transfer, api_call, etl_process, etc.
    attributes: Dict[str, Any] = field(default_factory=dict)
    constraints: List[Dict[str, Any]] = field(default_factory=list)  # Boundary constraints
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return asdict(self)


@dataclass
class LineageTransformationDetail:
    """
    Detailed representation of a transformation operation in lineage tracking.
    
    Provides fine-grained information about data transformations, including
    input/output mappings, parameters, and impact levels.
    
    Attributes:
        detail_id: Unique identifier for this transformation detail
        transformation_id: ID of the parent transformation
        operation_type: Type of operation (e.g., 'filter', 'join', 'aggregate', 'map')
        inputs: List of input field mappings
        outputs: List of output field mappings
        parameters: Operation parameters
        impact_level: Granularity of impact ('field', 'record', 'dataset')
        confidence: Confidence score for this transformation detail
        metadata: Additional metadata
        timestamp: Creation timestamp
    
    Example:
        >>> detail = LineageTransformationDetail(
        ...     detail_id="detail_123",
        ...     transformation_id="trans_456",
        ...     operation_type="filter",
        ...     parameters={"condition": "age > 18"}
        ... )
    """
    detail_id: str
    transformation_id: str  # ID of the parent transformation
    operation_type: str  # e.g., 'filter', 'join', 'aggregate', 'map', etc.
    inputs: List[Dict[str, Any]] = field(default_factory=list)  # Input field mappings
    outputs: List[Dict[str, Any]] = field(default_factory=list)  # Output field mappings
    parameters: Dict[str, Any] = field(default_factory=dict)  # Operation parameters
    impact_level: str = "field"  # 'field', 'record', 'dataset', etc.
    confidence: float = 1.0  # Confidence score for this transformation detail
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return asdict(self)


@dataclass
class LineageVersion:
    """
    Represents a version in version-aware lineage tracking.
    
    Tracks different versions of data entities and their evolution over time.
    
    Attributes:
        version_id: Unique identifier for this version
        entity_id: ID of the entity this version belongs to
        version_number: Version number (e.g., "1.0.0", "2.1.3")
        parent_version_id: Optional ID of the parent version
        changes: Description of changes in this version
        metadata: Additional version metadata
        timestamp: Creation timestamp
    
    Example:
        >>> version = LineageVersion(
        ...     version_id="v1",
        ...     entity_id="entity_123",
        ...     version_number="1.0.0",
        ...     changes="Initial version"
        ... )
    """
    version_id: str
    entity_id: str
    version_number: str
    parent_version_id: Optional[str] = None
    changes: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return asdict(self)


@dataclass
class LineageSubgraph:
    """
    Represents a subgraph extracted from the lineage graph.
    
    Useful for focused analysis on specific parts of the lineage.
    
    Attributes:
        subgraph_id: Unique identifier for this subgraph
        name: Human-readable name of the subgraph
        node_ids: List of node IDs included in this subgraph
        link_ids: List of link IDs included in this subgraph
        domain_filter: Optional domain filter applied
        metadata: Additional subgraph metadata
        timestamp: Creation timestamp
    
    Example:
        >>> subgraph = LineageSubgraph(
        ...     subgraph_id="sub_123",
        ...     name="ML Pipeline",
        ...     node_ids=["node_1", "node_2", "node_3"]
        ... )
    """
    subgraph_id: str
    name: str
    node_ids: List[str] = field(default_factory=list)
    link_ids: List[str] = field(default_factory=list)
    domain_filter: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return asdict(self)
