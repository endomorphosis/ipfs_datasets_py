"""
Cross-Document Lineage Tracking Module with Enhanced Data Provenance.

This module provides comprehensive data provenance capabilities for tracking lineage
across multiple documents, domains, and data transformations. It enables detailed tracing
of data flows, relationships, and transformations throughout the system with
advanced hierarchical metadata and granular relationship tracking.

Key features:
- Cross-document lineage graph construction and traversal
- Detailed transformation chain analysis with transformation decomposition
- Multi-level lineage with arbitrary depth and domain crossing
- Hierarchical lineage tracking with logical grouping of operations
- Relationship strength and confidence metrics with uncertainty propagation
- Enhanced visualization for complex data flows with interactive drill-down
- Semantic correlation across disparate document formats and domains
- IPLD-based content-addressable lineage tracking with advanced traversal capabilities
- Export and import of lineage graphs with selective transfer
- Automated lineage inference using semantic analysis and pattern matching
- Time-aware data flow visualizations with temporal slicing
- Incremental lineage graph updates with conflict resolution
- Lineage-aware query capabilities with path optimization
- Metadata inheritance with override management
- Bi-directional audit trail integration with cross-referencing
- Semantic relationship detection beyond explicit links
- Multi-domain lineage tracking with domain boundary analysis
- Confidence scoring for inferred lineage relationships
- Fine-grained permission controls for lineage access
- Version-aware lineage tracking with temporal consistency checks
- Transformation composition and decomposition analysis
- Impact and dependency analysis across multiple document types
- Custom metadata schemas for domain-specific lineage tracking
- Temporal consistency verification for lineage relationships
- Hierarchical subgraph extraction with domain filtering
"""

import json
import uuid
import time
import hashlib
import datetime
import logging
import networkx as nx
import matplotlib.pyplot as plt
from typing import Dict, List, Any, Optional, Union, Set, Tuple, Callable
from dataclasses import dataclass, field, asdict

# Try to import required dependencies
try:
    from ipfs_datasets_py.data_provenance import (
        ProvenanceManager, ProvenanceRecord, ProvenanceRecordType
    )
    BASE_PROVENANCE_AVAILABLE = True
except ImportError:
    BASE_PROVENANCE_AVAILABLE = False

try:
    from ipfs_datasets_py.data_provenance_enhanced import (
        EnhancedProvenanceManager, IPLDProvenanceStorage
    )
    ENHANCED_PROVENANCE_AVAILABLE = True
except ImportError:
    ENHANCED_PROVENANCE_AVAILABLE = False

try:
    import plotly.graph_objects as go
    import plotly.io as pio
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

# Initialize logger
logger = logging.getLogger(__name__)


@dataclass
class LineageLink:
    """Represents a link in the data lineage graph."""
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
class LineageNode:
    """Represents a node in the data lineage graph."""
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
class LineageDomain:
    """Represents a logical domain in the data lineage graph."""
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
    """Represents a boundary between domains in the lineage graph."""
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
    """Detailed representation of a transformation operation in lineage tracking."""
    detail_id: str
    transformation_id: str  # ID of the parent transformation
    operation_type: str  # e.g., 'filter', 'join', 'aggregate', 'map', etc.
    inputs: List[Dict[str, Any]] = field(default_factory=list)  # Input field mappings
    outputs: List[Dict[str, Any]] = field(default_factory=list)  # Output field mappings
    parameters: Dict[str, Any] = field(default_factory=dict)  # Operation parameters
    impact_level: str = "field"  # 'field', 'record', 'dataset', etc.
    confidence: float = 1.0  # Confidence score for this transformation detail
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return asdict(self)


@dataclass
class LineageVersion:
    """Represents a version of a node in the lineage graph."""
    version_id: str
    node_id: str  # ID of the versioned node
    version_number: str  # Version identifier
    parent_version_id: Optional[str] = None  # Previous version ID
    change_description: Optional[str] = None
    creator_id: Optional[str] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return asdict(self)


@dataclass
class LineageSubgraph:
    """Represents a subgraph in the data lineage graph."""
    nodes: Dict[str, LineageNode]
    links: List[LineageLink]
    root_id: str
    domains: Dict[str, LineageDomain] = field(default_factory=dict)
    boundaries: List[LineageBoundary] = field(default_factory=list)
    transformation_details: Dict[str, LineageTransformationDetail] = field(default_factory=dict)
    versions: Dict[str, LineageVersion] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    extraction_criteria: Optional[Dict[str, Any]] = None  # Criteria used to extract this subgraph

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "nodes": {node_id: node.to_dict() for node_id, node in self.nodes.items()},
            "links": [link.to_dict() for link in self.links],
            "root_id": self.root_id,
            "domains": {domain_id: domain.to_dict() for domain_id, domain in self.domains.items()},
            "boundaries": [boundary.to_dict() for boundary in self.boundaries],
            "transformation_details": {detail_id: detail.to_dict()
                                    for detail_id, detail in self.transformation_details.items()},
            "versions": {version_id: version.to_dict() for version_id, version in self.versions.items()},
            "metadata": self.metadata,
            "extraction_criteria": self.extraction_criteria
        }


class EnhancedLineageTracker:
    """
    Enhanced lineage tracking for comprehensive data provenance.

    This class provides advanced functionality for tracking data lineage
    across document, domain, and system boundaries, enabling comprehensive
    understanding of data flows and transformations with fine-grained
    metadata and hierarchical relationships.
    """

    def __init__(self, provenance_manager=None, storage=None, config=None):
        """
        Initialize the enhanced lineage tracker.

        Args:
            provenance_manager: Optional provenance manager to use
            storage: Optional storage backend for lineage data
            config: Optional configuration dictionary
        """
        self.provenance_manager = provenance_manager
        self.storage = storage
        self.config = config or {}
        self.logger = logging.getLogger(__name__)

        # Generate a unique ID for this tracker instance
        self.tracker_id = str(uuid.uuid4())

        # Internal storage structures
        self._domains = {}  # Map of domain_id to LineageDomain
        self._boundaries = {}  # Map of boundary_id to LineageBoundary
        self._graph = nx.DiGraph()  # Main lineage graph
        self._transformation_details = {}  # Map of detail_id to LineageTransformationDetail
        self._versions = {}  # Map of version_id to LineageVersion
        self._permission_registry = {}  # Map of node_id to permission settings
        self._metadata_inheritance = {}  # Map of node_id to inheritance rules
        self._semantic_relationships = {}  # Map of relationship_id to confidence and metadata
        self._node_types = {}  # Map of node_type to list of nodes

        # Cache for fast lookups
        self._entity_to_nodes = {}  # Map of entity_id to list of node_ids
        self._domain_hierarchy = {}  # Map of domain_id to list of child domain_ids

        # Enable bidirectional audit trail integration if audit logger is available
        self._audit_integration_enabled = self.config.get("enable_audit_integration", False)
        if self._audit_integration_enabled:
            try:
                from ipfs_datasets_py.audit.integration import AuditProvenanceIntegrator
                self.audit_integrator = AuditProvenanceIntegrator(
                    provenance_manager=self.provenance_manager
                )
            except ImportError:
                self.logger.warning("Audit integration enabled but audit module not available")
                self._audit_integration_enabled = False

        # Initialize temporal consistency checker
        self._temporal_consistency_enabled = self.config.get("enable_temporal_consistency", True)

        # Initialize semantic relationship detector if enabled
        self._semantic_relationship_detection = self.config.get("enable_semantic_detection", False)
        if self._semantic_relationship_detection:
            try:
                import nltk
                from nltk.tokenize import word_tokenize
                from nltk.similarity.vector import cosine_similarity_sparse
                nltk.download('punkt', quiet=True)
                nltk.download('stopwords', quiet=True)
                nltk.download('wordnet', quiet=True)
                self._nltk_available = True
            except ImportError:
                self.logger.warning("Semantic relationship detection enabled but NLTK not available")
                self._nltk_available = False

        # Initialize IPLD storage if enabled
        self._ipld_storage_enabled = self.config.get("enable_ipld_storage", False)
        if self._ipld_storage_enabled:
            try:
                from ipfs_datasets_py.ipld.storage import IPLDStorage
                self.ipld_storage = storage or IPLDStorage()
                self._ipld_blocks = {}  # Cache for IPLD blocks
                self._root_cid = None  # Root CID for the lineage graph
            except ImportError:
                self.logger.warning("IPLD storage enabled but ipld.storage module not available")
                self._ipld_storage_enabled = False

        # Tracking metadata
        self.metadata = {
            "created_at": datetime.datetime.now().isoformat(),
            "version": "2.0.0",
            "tracker_id": self.tracker_id,
            "features": {
                "domain_tracking": True,
                "hierarchical_lineage": True,
                "transformation_decomposition": True,
                "version_tracking": True,
                "semantic_relationship_detection": self._semantic_relationship_detection,
                "temporal_consistency": self._temporal_consistency_enabled,
                "audit_integration": self._audit_integration_enabled,
                "metadata_inheritance": True,
                "ipld_storage": self._ipld_storage_enabled
            }
        }

    def create_domain(self, name: str, description: Optional[str] = None,
                   domain_type: str = "generic", attributes: Optional[Dict[str, Any]] = None,
                   metadata_schema: Optional[Dict[str, Any]] = None,
                   parent_domain_id: Optional[str] = None) -> str:
        """
        Create a new domain for organizing lineage data.

        Args:
            name: Name of the domain
            description: Optional description
            domain_type: Type of domain (generic, application, dataset, workflow, etc.)
            attributes: Optional domain attributes
            metadata_schema: Optional validation schema for metadata
            parent_domain_id: Optional parent domain ID for hierarchical domains

        Returns:
            str: ID of the created domain
        """
        domain_id = str(uuid.uuid4())

        # Validate parent domain if specified
        if parent_domain_id and parent_domain_id not in self._domains:
            raise ValueError(f"Parent domain {parent_domain_id} does not exist")

        # Create new domain
        domain = LineageDomain(
            domain_id=domain_id,
            name=name,
            description=description,
            domain_type=domain_type,
            attributes=attributes or {},
            metadata_schema=metadata_schema,
            parent_domain_id=parent_domain_id
        )

        # Store domain
        self._domains[domain_id] = domain

        # Log domain creation
        self.logger.info(f"Created domain {name} with ID {domain_id}")

        # Add to lineage graph as a special node
        self._graph.add_node(domain_id,
                          node_type="domain",
                          entity_type="domain",
                          name=name,
                          attributes=attributes or {})

        return domain_id

    def create_domain_boundary(self, source_domain_id: str, target_domain_id: str,
                            boundary_type: str, attributes: Optional[Dict[str, Any]] = None,
                            constraints: Optional[List[Dict[str, Any]]] = None) -> str:
        """
        Create a boundary between two domains.

        Args:
            source_domain_id: Source domain ID
            target_domain_id: Target domain ID
            boundary_type: Type of boundary (data_transfer, api_call, etc.)
            attributes: Optional boundary attributes
            constraints: Optional boundary constraints

        Returns:
            str: ID of the created boundary
        """
        # Validate domains
        if source_domain_id not in self._domains:
            raise ValueError(f"Source domain {source_domain_id} does not exist")

        if target_domain_id not in self._domains:
            raise ValueError(f"Target domain {target_domain_id} does not exist")

        boundary_id = str(uuid.uuid4())

        # Create new boundary
        boundary = LineageBoundary(
            boundary_id=boundary_id,
            source_domain_id=source_domain_id,
            target_domain_id=target_domain_id,
            boundary_type=boundary_type,
            attributes=attributes or {},
            constraints=constraints or []
        )

        # Store boundary
        self._boundaries[boundary_id] = boundary

        # Add to lineage graph as a special edge
        self._graph.add_edge(source_domain_id, target_domain_id,
                           edge_type="domain_boundary",
                           boundary_id=boundary_id,
                           boundary_type=boundary_type,
                           attributes=attributes or {})

        return boundary_id

    def create_node(self, node_type: str, metadata: Optional[Dict[str, Any]] = None,
                 domain_id: Optional[str] = None, entity_id: Optional[str] = None) -> str:
        """
        Create a new node in the lineage graph.

        Args:
            node_type: Type of node
            metadata: Optional node metadata
            domain_id: Optional domain to associate with this node
            entity_id: Optional entity ID for linking to external systems

        Returns:
            str: ID of the created node
        """
        node_id = str(uuid.uuid4())

        # Validate domain if specified
        if domain_id and domain_id not in self._domains:
            raise ValueError(f"Domain {domain_id} does not exist")

        # Create LineageNode
        node = LineageNode(
            node_id=node_id,
            node_type=node_type,
            entity_id=entity_id,
            metadata=metadata or {}
        )

        # Apply metadata inheritance if the node is in a domain
        if domain_id:
            if metadata is None:
                node.metadata = {}

            # Add domain information to node metadata
            node.metadata["domain_id"] = domain_id
            node.metadata["domain_name"] = self._domains[domain_id].name

            # Apply domain's metadata schema if available
            domain = self._domains[domain_id]
            if domain.metadata_schema and hasattr(self, '_validate_metadata'):
                self._validate_metadata(node.metadata, domain.metadata_schema)

        # Add node to graph
        self._graph.add_node(node_id,
                          node_type=node_type,
                          entity_id=entity_id,
                          domain_id=domain_id,
                          metadata=node.metadata)

        return node_id

    def create_link(self, source_id: str, target_id: str, relationship_type: str,
                 metadata: Optional[Dict[str, Any]] = None, confidence: float = 1.0,
                 direction: str = "forward", cross_domain: bool = False) -> str:
        """
        Create a link between two nodes in the lineage graph.

        Args:
            source_id: Source node ID
            target_id: Target node ID
            relationship_type: Type of relationship
            metadata: Optional link metadata
            confidence: Confidence score (0.0-1.0)
            direction: Link direction (forward, backward, bidirectional)
            cross_domain: Whether this link crosses domain boundaries

        Returns:
            str: ID of the created link
        """
        # Validate nodes
        if source_id not in self._graph:
            raise ValueError(f"Source node {source_id} does not exist")

        if target_id not in self._graph:
            raise ValueError(f"Target node {target_id} does not exist")

        # Handle cross-domain links
        source_domain = self._graph.nodes[source_id].get("domain_id")
        target_domain = self._graph.nodes[target_id].get("domain_id")

        is_cross_domain = False
        if source_domain and target_domain and source_domain != target_domain:
            is_cross_domain = True

            # Check if there's a boundary between these domains
            boundary_exists = False
            for boundary in self._boundaries.values():
                if (boundary.source_domain_id == source_domain and
                    boundary.target_domain_id == target_domain):
                    boundary_exists = True
                    break

            # If cross-domain linking is enforced, ensure a boundary exists
            if cross_domain and not boundary_exists:
                raise ValueError(f"Cannot create cross-domain link without a domain boundary")

        # Create link
        link = LineageLink(
            source_id=source_id,
            target_id=target_id,
            relationship_type=relationship_type,
            confidence=confidence,
            metadata=metadata or {},
            direction=direction
        )

        # Add cross-domain flag to metadata if applicable
        if is_cross_domain:
            link.metadata["cross_domain"] = True
            link.metadata["source_domain"] = source_domain
            link.metadata["target_domain"] = target_domain

        # Add to graph with appropriate direction
        if direction == "forward" or direction == "bidirectional":
            self._graph.add_edge(source_id, target_id,
                               edge_type=relationship_type,
                               confidence=confidence,
                               metadata=link.metadata)

        if direction == "backward" or direction == "bidirectional":
            self._graph.add_edge(target_id, source_id,
                               edge_type=f"{relationship_type}_inverse",
                               confidence=confidence,
                               metadata=link.metadata)

        # Validate temporal consistency if enabled
        if self._temporal_consistency_enabled:
            self._check_temporal_consistency(source_id, target_id)

        # Create a bidirectional link to audit trails if enabled
        if self._audit_integration_enabled and hasattr(self, 'audit_integrator'):
            self._link_to_audit_trail(source_id, target_id, relationship_type)

        return f"{source_id}:{target_id}:{relationship_type}"

    def record_transformation_details(self, transformation_id: str, operation_type: str,
                                 inputs: List[Dict[str, Any]], outputs: List[Dict[str, Any]],
                                 parameters: Optional[Dict[str, Any]] = None,
                                 impact_level: str = "field",
                                 confidence: float = 1.0) -> str:
        """
        Record detailed information about a transformation operation.

        Args:
            transformation_id: ID of the parent transformation
            operation_type: Type of operation (filter, join, aggregate, map, etc.)
            inputs: Input field mappings
            outputs: Output field mappings
            parameters: Optional operation parameters
            impact_level: Level of impact (field, record, dataset, etc.)
            confidence: Confidence score for this transformation detail

        Returns:
            str: ID of the created transformation detail
        """
        detail_id = str(uuid.uuid4())

        # Create transformation detail
        detail = LineageTransformationDetail(
            detail_id=detail_id,
            transformation_id=transformation_id,
            operation_type=operation_type,
            inputs=inputs,
            outputs=outputs,
            parameters=parameters or {},
            impact_level=impact_level,
            confidence=confidence
        )

        # Store transformation detail
        self._transformation_details[detail_id] = detail

        # Add reference to the transformation node if it exists
        if transformation_id in self._graph:
            if 'transformation_details' not in self._graph.nodes[transformation_id]:
                self._graph.nodes[transformation_id]['transformation_details'] = []

            self._graph.nodes[transformation_id]['transformation_details'].append(detail_id)

        return detail_id

    def create_version(self, node_id: str, version_number: str,
                    change_description: Optional[str] = None,
                    parent_version_id: Optional[str] = None,
                    creator_id: Optional[str] = None,
                    attributes: Optional[Dict[str, Any]] = None) -> str:
        """
        Create a new version of a node.

        Args:
            node_id: ID of the node to version
            version_number: Version identifier
            change_description: Optional description of changes
            parent_version_id: Optional ID of the previous version
            creator_id: Optional ID of the version creator
            attributes: Optional version attributes

        Returns:
            str: ID of the created version
        """
        # Validate node
        if node_id not in self._graph:
            raise ValueError(f"Node {node_id} does not exist")

        # Validate parent version if specified
        if parent_version_id and parent_version_id not in self._versions:
            raise ValueError(f"Parent version {parent_version_id} does not exist")

        # Ensure version number is unique for this node
        for version in self._versions.values():
            if version.node_id == node_id and version.version_number == version_number:
                raise ValueError(f"Version {version_number} already exists for node {node_id}")

        version_id = str(uuid.uuid4())

        # Create version
        version = LineageVersion(
            version_id=version_id,
            node_id=node_id,
            version_number=version_number,
            parent_version_id=parent_version_id,
            change_description=change_description,
            creator_id=creator_id,
            attributes=attributes or {}
        )

        # Store version
        self._versions[version_id] = version

        # Add reference to the node
        if 'versions' not in self._graph.nodes[node_id]:
            self._graph.nodes[node_id]['versions'] = []

        self._graph.nodes[node_id]['versions'].append(version_id)

        # Add direct reference to latest version
        self._graph.nodes[node_id]['latest_version'] = version_id

        return version_id

    def _check_temporal_consistency(self, source_id: str, target_id: str) -> bool:
        """
        Check temporal consistency between source and target nodes.

        This ensures that data doesn't flow backward in time.

        Args:
            source_id: Source node ID
            target_id: Target node ID

        Returns:
            bool: Whether the link is temporally consistent
        """
        # Get timestamps from nodes
        source_time = self._graph.nodes[source_id].get('timestamp', 0)
        target_time = self._graph.nodes[target_id].get('timestamp', 0)

        # Allow for small time differences (processing delay)
        # Target should generally be created after source
        if target_time < source_time - 0.1:  # 100ms tolerance
            self.logger.warning(
                f"Temporal inconsistency detected: target node {target_id} "
                f"({target_time}) created before source node {source_id} ({source_time})"
            )
            return False

        return True

    def _link_to_audit_trail(self, source_id: str, target_id: str, relationship_type: str):
        """
        Create bidirectional links to audit trail events.

        Args:
            source_id: Source node ID
            target_id: Target node ID
            relationship_type: Type of relationship
        """
        try:
            # Map node IDs to provenance record IDs if applicable
            source_provenance_id = self._graph.nodes[source_id].get('provenance_record_id')
            target_provenance_id = self._graph.nodes[target_id].get('provenance_record_id')

            if source_provenance_id or target_provenance_id:
                # Get relevant audit events
                audit_events = self.audit_integrator.find_related_audit_events(
                    record_ids=[r for r in [source_provenance_id, target_provenance_id] if r]
                )

                # Link lineage to audit events
                for event in audit_events:
                    self.audit_integrator.link_lineage_to_audit(
                        lineage_link=f"{source_id}:{target_id}:{relationship_type}",
                        audit_event_id=event.event_id,
                        relationship_type=relationship_type
                    )
        except Exception as e:
            self.logger.warning(f"Error linking to audit trail: {str(e)}")

    def query_lineage(self, query: Dict[str, Any]) -> LineageSubgraph:
        """
        Execute a query against the lineage graph.

        This method provides a flexible query interface for finding nodes and
        relationships that match specific criteria.

        Args:
            query: Dict with query parameters:
                - node_type: Optional str or list - Filter by node type
                - entity_id: Optional str or list - Filter by entity ID
                - domain_id: Optional str or list - Filter by domain ID
                - relationship_type: Optional str or list - Filter by relationship type
                - start_time: Optional float - Filter by timestamp (start)
                - end_time: Optional float - Filter by timestamp (end)
                - metadata_filters: Optional Dict - Filters for node metadata
                - max_results: Optional int - Maximum results to return
                - include_domains: Optional bool - Include domain info in results
                - include_versions: Optional bool - Include version info in results
                - include_transformation_details: Optional bool - Include transformation details

        Returns:
            LineageSubgraph: Subgraph containing query results
        """
        # Validate query parameters
        if not isinstance(query, dict):
            raise ValueError("Query must be a dictionary")

        # Apply node type filter
        filtered_nodes = set(self._graph.nodes())

        if 'node_type' in query:
            node_types = query['node_type']
            if isinstance(node_types, str):
                node_types = [node_types]

            type_filtered = set()
            for node in filtered_nodes:
                node_type = self._graph.nodes[node].get('node_type')
                if node_type in node_types:
                    type_filtered.add(node)
            filtered_nodes = type_filtered

        # Apply entity ID filter
        if 'entity_id' in query:
            entity_ids = query['entity_id']
            if isinstance(entity_ids, str):
                entity_ids = [entity_ids]

            entity_filtered = set()
            for node in filtered_nodes:
                entity_id = self._graph.nodes[node].get('entity_id')
                if entity_id in entity_ids:
                    entity_filtered.add(node)
            filtered_nodes = entity_filtered

        # Apply domain filter
        if 'domain_id' in query:
            domain_ids = query['domain_id']
            if isinstance(domain_ids, str):
                domain_ids = [domain_ids]

            domain_filtered = set()
            for node in filtered_nodes:
                domain_id = self._graph.nodes[node].get('domain_id')
                if domain_id in domain_ids:
                    domain_filtered.add(node)
            filtered_nodes = domain_filtered

        # Apply timestamp filters
        if 'start_time' in query or 'end_time' in query:
            start_time = query.get('start_time', 0)
            end_time = query.get('end_time', float('inf'))

            time_filtered = set()
            for node in filtered_nodes:
                timestamp = self._graph.nodes[node].get('timestamp', 0)
                if start_time <= timestamp <= end_time:
                    time_filtered.add(node)
            filtered_nodes = time_filtered

        # Apply metadata filters
        if 'metadata_filters' in query and isinstance(query['metadata_filters'], dict):
            metadata_filters = query['metadata_filters']

            metadata_filtered = set()
            for node in filtered_nodes:
                metadata = self._graph.nodes[node].get('metadata', {})
                matches = True

                for key, value in metadata_filters.items():
                    if key not in metadata or metadata[key] != value:
                        matches = False
                        break

                if matches:
                    metadata_filtered.add(node)

            filtered_nodes = metadata_filtered

        # Apply relationship type filter by examining edges
        if 'relationship_type' in query:
            relationship_types = query['relationship_type']
            if isinstance(relationship_types, str):
                relationship_types = [relationship_types]

            # Filter nodes by examining their edges
            relationship_filtered = set()

            for node in filtered_nodes:
                # Check outgoing edges
                for _, target, data in self._graph.out_edges(node, data=True):
                    if 'relationship_type' in data and data['relationship_type'] in relationship_types:
                        relationship_filtered.add(node)
                        relationship_filtered.add(target)

                # Check incoming edges
                for source, _, data in self._graph.in_edges(node, data=True):
                    if 'relationship_type' in data and data['relationship_type'] in relationship_types:
                        relationship_filtered.add(node)
                        relationship_filtered.add(source)

            # Only keep nodes that were in the original filtered set
            relationship_filtered = relationship_filtered.intersection(filtered_nodes)
            filtered_nodes = relationship_filtered

        # Limit results if specified
        if 'max_results' in query and isinstance(query['max_results'], int):
            max_results = query['max_results']
            if len(filtered_nodes) > max_results:
                filtered_nodes = set(list(filtered_nodes)[:max_results])

        # If no nodes match, return empty subgraph
        if not filtered_nodes:
            return LineageSubgraph(
                nodes={},
                links=[],
                root_id="query_result",
                extraction_criteria=query
            )

        # Extract subgraph with nodes and their connections
        subgraph = self._graph.subgraph(filtered_nodes).copy()

        # Convert to LineageSubgraph
        lineage_nodes = {}
        for node_id, attrs in subgraph.nodes(data=True):
            node_type = attrs.get('node_type', 'unknown')
            entity_id = attrs.get('entity_id')
            metadata = attrs.get('metadata', {})

            lineage_nodes[node_id] = LineageNode(
                node_id=node_id,
                node_type=node_type,
                entity_id=entity_id,
                metadata=metadata
            )

        lineage_links = []
        for u, v, data in subgraph.edges(data=True):
            relationship_type = data.get('relationship_type', data.get('edge_type', 'unknown'))
            confidence = data.get('confidence', 1.0)
            metadata = data.get('metadata', {})

            lineage_links.append(LineageLink(
                source_id=u,
                target_id=v,
                relationship_type=relationship_type,
                confidence=confidence,
                metadata=metadata
            ))

        # Get domains if requested
        domains = {}
        if query.get('include_domains', True):
            for node_id in filtered_nodes:
                domain_id = self._graph.nodes[node_id].get('domain_id')
                if domain_id and domain_id in self._domains:
                    domains[domain_id] = self._domains[domain_id]

        # Get boundaries between included domains
        boundaries = []
        if query.get('include_domains', True) and domains:
            domain_ids = set(domains.keys())
            for boundary in self._boundaries.values():
                if (boundary.source_domain_id in domain_ids and
                    boundary.target_domain_id in domain_ids):
                    boundaries.append(boundary)

        # Get transformation details if requested
        transformation_details = {}
        if query.get('include_transformation_details', False):
            for node_id in filtered_nodes:
                if 'transformation_details' in self._graph.nodes[node_id]:
                    for detail_id in self._graph.nodes[node_id]['transformation_details']:
                        if detail_id in self._transformation_details:
                            transformation_details[detail_id] = self._transformation_details[detail_id]

        # Get versions if requested
        versions = {}
        if query.get('include_versions', False):
            for node_id in filtered_nodes:
                if 'versions' in self._graph.nodes[node_id]:
                    for version_id in self._graph.nodes[node_id]['versions']:
                        if version_id in self._versions:
                            versions[version_id] = self._versions[version_id]

        # Create final subgraph
        return LineageSubgraph(
            nodes=lineage_nodes,
            links=lineage_links,
            root_id="query_result",
            domains=domains,
            boundaries=boundaries,
            transformation_details=transformation_details,
            versions=versions,
            metadata={
                "node_count": len(lineage_nodes),
                "link_count": len(lineage_links),
                "domain_count": len(domains),
                "query_timestamp": datetime.datetime.now().isoformat()
            },
            extraction_criteria=query
        )

    def find_paths(self, start_node_id: str, end_node_id: str,
                max_depth: int = 10,
                relationship_filter: Optional[List[str]] = None) -> List[List[str]]:
        """
        Find all paths between two nodes in the lineage graph.

        Args:
            start_node_id: ID of the starting node
            end_node_id: ID of the ending node
            max_depth: Maximum path length to consider
            relationship_filter: Optional list of relationship types to consider

        Returns:
            List[List[str]]: List of paths, where each path is a list of node IDs
        """
        if start_node_id not in self._graph or end_node_id not in self._graph:
            self.logger.warning(f"Start node {start_node_id} or end node {end_node_id} not found in graph")
            return []

        # If relationship filter specified, create a view of the graph with only those relationships
        if relationship_filter:
            view = nx.DiGraph()

            # Add all nodes
            for node, attrs in self._graph.nodes(data=True):
                view.add_node(node, **attrs)

            # Add only edges with specified relationship types
            for u, v, data in self._graph.edges(data=True):
                edge_type = data.get('relationship_type', data.get('edge_type', 'unknown'))
                if edge_type in relationship_filter:
                    view.add_edge(u, v, **data)

            graph = view
        else:
            graph = self._graph

        try:
            # Find simple paths with length limit
            paths = list(nx.all_simple_paths(graph, start_node_id, end_node_id, cutoff=max_depth))

            # Sort by path length
            paths.sort(key=len)

            return paths
        except (nx.NetworkXNoPath, nx.NodeNotFound) as e:
            self.logger.info(f"No path found: {str(e)}")
            return []

    def merge_lineage(self, other_tracker: 'EnhancedLineageTracker',
                   conflict_resolution: str = 'newer',
                   allow_domain_merging: bool = True) -> Dict[str, int]:
        """
        Merge another lineage tracker into this one.

        Args:
            other_tracker: The other EnhancedLineageTracker to merge from
            conflict_resolution: How to resolve conflicts ('newer', 'keep', 'replace')
            allow_domain_merging: Whether to merge domains and boundaries

        Returns:
            Dict[str, int]: Statistics about the merge operation
        """
        stats = {
            "nodes_added": 0,
            "nodes_updated": 0,
            "links_added": 0,
            "domains_added": 0,
            "boundaries_added": 0,
            "versions_added": 0,
            "transformation_details_added": 0
        }

        # Merge domains if allowed
        if allow_domain_merging:
            for domain_id, domain in other_tracker._domains.items():
                if domain_id not in self._domains:
                    self._domains[domain_id] = domain
                    stats["domains_added"] += 1
                elif conflict_resolution == 'replace':
                    self._domains[domain_id] = domain
                elif conflict_resolution == 'newer':
                    if domain.timestamp > self._domains[domain_id].timestamp:
                        self._domains[domain_id] = domain

            # Merge boundaries
            for boundary_id, boundary in other_tracker._boundaries.items():
                if boundary_id not in self._boundaries:
                    # Only add if both domains exist
                    if (boundary.source_domain_id in self._domains and
                        boundary.target_domain_id in self._domains):
                        self._boundaries[boundary_id] = boundary
                        stats["boundaries_added"] += 1

        # Merge transformation details
        for detail_id, detail in other_tracker._transformation_details.items():
            if detail_id not in self._transformation_details:
                self._transformation_details[detail_id] = detail
                stats["transformation_details_added"] += 1

        # Merge versions
        for version_id, version in other_tracker._versions.items():
            if version_id not in self._versions:
                self._versions[version_id] = version
                stats["versions_added"] += 1

        # Merge nodes
        for node_id, data in other_tracker._graph.nodes(data=True):
            if node_id not in self._graph:
                # Add new node
                self._graph.add_node(node_id, **data)
                stats["nodes_added"] += 1
            elif conflict_resolution == 'replace':
                # Replace node data
                for key, value in data.items():
                    self._graph.nodes[node_id][key] = value
                stats["nodes_updated"] += 1
            elif conflict_resolution == 'newer':
                # Update if newer
                other_time = data.get('timestamp', 0)
                our_time = self._graph.nodes[node_id].get('timestamp', 0)

                if other_time > our_time:
                    for key, value in data.items():
                        self._graph.nodes[node_id][key] = value
                    stats["nodes_updated"] += 1

        # Merge edges
        for source, target, data in other_tracker._graph.edges(data=True):
            # Only add edge if both nodes exist
            if source in self._graph and target in self._graph:
                if not self._graph.has_edge(source, target):
                    # Add new edge
                    self._graph.add_edge(source, target, **data)
                    stats["links_added"] += 1
                elif conflict_resolution == 'replace':
                    # Replace edge data
                    for key, value in data.items():
                        self._graph[source][target][key] = value
                elif conflict_resolution == 'newer':
                    # Update if newer
                    other_time = data.get('timestamp', 0)
                    our_time = self._graph[source][target].get('timestamp', 0)

                    if other_time > our_time:
                        for key, value in data.items():
                            self._graph[source][target][key] = value

        self.logger.info(f"Merged lineage graph: {stats}")
        return stats

    def extract_subgraph(self, root_id: str, max_depth: int = 3,
                     direction: str = "both", include_domains: bool = True,
                     include_versions: bool = False,
                     include_transformation_details: bool = False,
                     relationship_types: Optional[List[str]] = None,
                     domain_filter: Optional[List[str]] = None) -> LineageSubgraph:
        """
        Extract a subgraph from the lineage graph.

        Args:
            root_id: ID of the root node
            max_depth: Maximum traversal depth
            direction: Traversal direction (forward, backward, both)
            include_domains: Whether to include domain information
            include_versions: Whether to include version history
            include_transformation_details: Whether to include transformation details
            relationship_types: Optional filter for relationship types
            domain_filter: Optional filter for domains

        Returns:
            LineageSubgraph: The extracted subgraph
        """
        # Validate root node
        if root_id not in self._graph:
            raise ValueError(f"Root node {root_id} does not exist")

        # Extract nodes based on traversal direction
        if direction == "forward":
            nodes = set(nx.descendants(self._graph, root_id))
            nodes.add(root_id)
        elif direction == "backward":
            nodes = set(nx.ancestors(self._graph, root_id))
            nodes.add(root_id)
        else:  # "both"
            forward_nodes = set(nx.descendants(self._graph, root_id))
            backward_nodes = set(nx.ancestors(self._graph, root_id))
            nodes = forward_nodes.union(backward_nodes)
            nodes.add(root_id)

        # Apply depth limit
        if max_depth > 0:
            # For each node, calculate shortest path length from root
            all_nodes = list(nodes)
            filtered_nodes = {root_id}

            for node in all_nodes:
                if node == root_id:
                    continue

                try:
                    if direction == "forward":
                        length = nx.shortest_path_length(self._graph, root_id, node)
                    elif direction == "backward":
                        length = nx.shortest_path_length(self._graph, node, root_id)
                    else:  # "both"
                        # Try forward path first
                        try:
                            length = nx.shortest_path_length(self._graph, root_id, node)
                        except (nx.NetworkXNoPath, nx.NodeNotFound):
                            # Try backward path
                            try:
                                length = nx.shortest_path_length(self._graph, node, root_id)
                            except (nx.NetworkXNoPath, nx.NodeNotFound):
                                length = float('inf')

                    if length <= max_depth:
                        filtered_nodes.add(node)
                except (nx.NetworkXNoPath, nx.NodeNotFound):
                    # Node not reachable, skip
                    pass

            nodes = filtered_nodes

        # Apply domain filter if specified
        if domain_filter:
            filtered_nodes = set()
            for node in nodes:
                node_domain = self._graph.nodes[node].get('domain_id')
                if node_domain is None or node_domain in domain_filter:
                    filtered_nodes.add(node)
            nodes = filtered_nodes

        # Extract subgraph
        subgraph = self._graph.subgraph(nodes).copy()

        # Filter edges by relationship type if specified
        if relationship_types:
            edges_to_remove = []
            for u, v, data in subgraph.edges(data=True):
                edge_type = data.get('edge_type')
                if edge_type not in relationship_types:
                    edges_to_remove.append((u, v))

            for u, v in edges_to_remove:
                subgraph.remove_edge(u, v)

        # Convert NetworkX subgraph to LineageSubgraph
        lineage_nodes = {}
        for node_id, attrs in subgraph.nodes(data=True):
            node_type = attrs.get('node_type', 'unknown')
            entity_id = attrs.get('entity_id')
            metadata = attrs.get('metadata', {})

            lineage_nodes[node_id] = LineageNode(
                node_id=node_id,
                node_type=node_type,
                entity_id=entity_id,
                metadata=metadata
            )

        lineage_links = []
        for u, v, data in subgraph.edges(data=True):
            relationship_type = data.get('edge_type', 'unknown')
            confidence = data.get('confidence', 1.0)
            metadata = data.get('metadata', {})

            lineage_links.append(LineageLink(
                source_id=u,
                target_id=v,
                relationship_type=relationship_type,
                confidence=confidence,
                metadata=metadata
            ))

        # Collect domains if requested
        domains = {}
        if include_domains:
            domain_ids = set()
            for node_id, attrs in subgraph.nodes(data=True):
                domain_id = attrs.get('domain_id')
                if domain_id and domain_id in self._domains:
                    domain_ids.add(domain_id)

            for domain_id in domain_ids:
                domains[domain_id] = self._domains[domain_id]

        # Collect boundaries between included domains
        boundaries = []
        if include_domains:
            domain_ids = set(domains.keys())
            for boundary in self._boundaries.values():
                if (boundary.source_domain_id in domain_ids and
                    boundary.target_domain_id in domain_ids):
                    boundaries.append(boundary)

        # Collect transformation details if requested
        transformation_details = {}
        if include_transformation_details:
            for node_id, attrs in subgraph.nodes(data=True):
                if 'transformation_details' in attrs:
                    for detail_id in attrs['transformation_details']:
                        if detail_id in self._transformation_details:
                            transformation_details[detail_id] = self._transformation_details[detail_id]

        # Collect versions if requested
        versions = {}
        if include_versions:
            for node_id, attrs in subgraph.nodes(data=True):
                if 'versions' in attrs:
                    for version_id in attrs['versions']:
                        if version_id in self._versions:
                            versions[version_id] = self._versions[version_id]

        # Create extraction criteria record
        extraction_criteria = {
            "root_id": root_id,
            "max_depth": max_depth,
            "direction": direction,
            "include_domains": include_domains,
            "include_versions": include_versions,
            "include_transformation_details": include_transformation_details,
            "relationship_types": relationship_types,
            "domain_filter": domain_filter,
            "timestamp": time.time()
        }

        # Create the LineageSubgraph
        return LineageSubgraph(
            nodes=lineage_nodes,
            links=lineage_links,
            root_id=root_id,
            domains=domains,
            boundaries=boundaries,
            transformation_details=transformation_details,
            versions=versions,
            metadata={
                "node_count": len(lineage_nodes),
                "link_count": len(lineage_links),
                "domain_count": len(domains),
                "extraction_timestamp": datetime.datetime.now().isoformat()
            },
            extraction_criteria=extraction_criteria
        )

    def detect_semantic_relationships(self, confidence_threshold: float = 0.7,
                             max_candidates: int = 100) -> List[Dict[str, Any]]:
        """
        Detect semantic relationships between nodes based on text similarity and proximity.

        This method analyzes node metadata to find semantically related nodes that may not
        have explicit connections, enabling more comprehensive lineage tracking.

        Args:
            confidence_threshold: Minimum confidence score to consider a relationship valid
            max_candidates: Maximum number of candidate relationships to evaluate

        Returns:
            List[Dict[str, Any]]: List of detected semantic relationships
        """
        if not self._semantic_relationship_detection or not self._nltk_available:
            self.logger.warning("Semantic relationship detection is not enabled or NLTK is not available")
            return []

        try:
            import nltk
            from nltk.tokenize import word_tokenize
            from nltk.corpus import stopwords
            from nltk.stem import WordNetLemmatizer
            from nltk.probability import FreqDist
            from nltk.similarity.vector import cosine_similarity_sparse
            from nltk.util import ngrams

            # Get stopwords and initialize lemmatizer
            stop_words = set(stopwords.words('english'))
            lemmatizer = WordNetLemmatizer()

            # Function to extract text features from node metadata
            def extract_features(node_id):
                # Get node metadata
                metadata = {}
                if node_id in self._graph.nodes:
                    metadata = self._graph.nodes[node_id].get('metadata', {})

                # Extract text from various metadata fields
                text = ""
                for key, value in metadata.items():
                    if isinstance(value, str):
                        text += " " + value
                    elif isinstance(value, (list, tuple)) and all(isinstance(x, str) for x in value):
                        text += " " + " ".join(value)

                # Tokenize, remove stopwords, and lemmatize
                tokens = word_tokenize(text.lower())
                tokens = [lemmatizer.lemmatize(token) for token in tokens if token.isalpha() and token not in stop_words]

                # Create frequency distribution
                freq_dist = FreqDist(tokens)

                # Add bigrams for more context
                bi_grams = list(ngrams(tokens, 2))
                for gram in bi_grams:
                    freq_dist[gram] += 1

                return freq_dist

            # Collect node features
            node_features = {}
            for node_id in self._graph.nodes:
                node_features[node_id] = extract_features(node_id)

            # Generate candidate pairs
            candidate_pairs = []

            # First, consider nodes that share similar entity types
            node_types = {}
            for node_id, attrs in self._graph.nodes(data=True):
                node_type = attrs.get('node_type', 'unknown')
                if node_type not in node_types:
                    node_types[node_type] = []
                node_types[node_type].append(node_id)

            # Generate candidates within the same type
            for node_type, nodes in node_types.items():
                if len(nodes) > 1:
                    for i in range(len(nodes)):
                        for j in range(i+1, len(nodes)):
                            candidate_pairs.append((nodes[i], nodes[j]))

            # If we have too many candidates, limit by taking a random sample
            import random
            if len(candidate_pairs) > max_candidates:
                candidate_pairs = random.sample(candidate_pairs, max_candidates)

            # Calculate similarities and detect relationships
            detected_relationships = []
            for source_id, target_id in candidate_pairs:
                # Skip if direct relationship already exists
                if self._graph.has_edge(source_id, target_id) or self._graph.has_edge(target_id, source_id):
                    continue

                # Calculate similarity using feature distributions
                source_features = node_features[source_id]
                target_features = node_features[target_id]

                # Skip if either node has no features
                if not source_features or not target_features:
                    continue

                similarity = cosine_similarity_sparse(source_features, target_features)

                # If similarity exceeds threshold, create a semantic relationship
                if similarity >= confidence_threshold:
                    relationship_id = f"semantic_{source_id}_{target_id}"

                    # Determine most likely relationship type
                    relationship_type = "semantically_related"

                    # Check for common features to make better type inference
                    common_features = set(source_features.keys()) & set(target_features.keys())
                    if len(common_features) > 3:  # Arbitrary threshold for having enough common features
                        # Domain-specific logic to infer relationship type
                        if "version" in common_features or "revision" in common_features:
                            relationship_type = "version_of"
                        elif "transform" in common_features or "convert" in common_features:
                            relationship_type = "transformed_from"
                        elif "derive" in common_features or "extract" in common_features:
                            relationship_type = "derived_from"
                        elif "contain" in common_features or "part" in common_features:
                            relationship_type = "contains"

                    # Create the relationship in the graph
                    self._graph.add_edge(
                        source_id,
                        target_id,
                        edge_type=relationship_type,
                        relationship_type=relationship_type,
                        confidence=similarity,
                        is_semantic=True,
                        detected_at=time.time()
                    )

                    # Store semantic relationship metadata
                    self._semantic_relationships[relationship_id] = {
                        "source_id": source_id,
                        "target_id": target_id,
                        "relationship_type": relationship_type,
                        "confidence": similarity,
                        "common_features": list(common_features)[:10],  # Limit to first 10 for brevity
                        "detected_at": time.time()
                    }

                    # Add to detected relationships list
                    detected_relationships.append({
                        "relationship_id": relationship_id,
                        "source_id": source_id,
                        "target_id": target_id,
                        "relationship_type": relationship_type,
                        "confidence": similarity,
                        "common_features": list(common_features)[:10]
                    })

            self.logger.info(f"Detected {len(detected_relationships)} semantic relationships")
            return detected_relationships

        except Exception as e:
            self.logger.error(f"Error detecting semantic relationships: {str(e)}")
            return []

    def export_to_ipld(self, include_domains: bool = True,
                    include_versions: bool = False,
                    include_transformation_details: bool = False) -> Optional[str]:
        """
        Export the lineage graph to IPLD format for persistent storage.

        This method encodes the entire lineage graph and associated metadata
        as IPLD blocks, enabling content-addressable storage and decentralized access.

        Args:
            include_domains: Whether to include domain information
            include_versions: Whether to include version history
            include_transformation_details: Whether to include transformation details

        Returns:
            Optional[str]: Root CID of the exported IPLD structure, or None if export fails
        """
        if not self._ipld_storage_enabled:
            self.logger.warning("IPLD storage is not enabled")
            return None

        try:
            import json

            # Create IPLD blocks
            blocks = {}

            # Export nodes as IPLD blocks
            node_cids = {}
            for node_id, node_data in self._graph.nodes(data=True):
                # Encode node data
                node_data_copy = node_data.copy()

                # Replace any non-serializable items
                for k, v in node_data_copy.items():
                    if not isinstance(v, (str, int, float, bool, list, dict, type(None))):
                        node_data_copy[k] = str(v)

                node_json = json.dumps({
                    "node_id": node_id,
                    "data": node_data_copy
                }).encode('utf-8')

                # Create content ID
                node_cid = self.ipld_storage.put(node_json)
                node_cids[node_id] = node_cid
                blocks[node_cid] = node_json

            # Export edges as IPLD blocks
            edge_cids = []
            for source, target, edge_data in self._graph.edges(data=True):
                # Encode edge data
                edge_data_copy = edge_data.copy()

                # Replace any non-serializable items
                for k, v in edge_data_copy.items():
                    if not isinstance(v, (str, int, float, bool, list, dict, type(None))):
                        edge_data_copy[k] = str(v)

                # Replace node IDs with their CIDs
                edge_json = json.dumps({
                    "source": {">/": node_cids[source]},
                    "target": {">/": node_cids[target]},
                    "data": edge_data_copy
                }).encode('utf-8')

                # Create content ID
                edge_cid = self.ipld_storage.put(edge_json)
                edge_cids.append(edge_cid)
                blocks[edge_cid] = edge_json

            # Export domains if requested
            domain_cids = {}
            if include_domains and self._domains:
                for domain_id, domain in self._domains.items():
                    domain_json = json.dumps(domain.to_dict()).encode('utf-8')
                    domain_cid = self.ipld_storage.put(domain_json)
                    domain_cids[domain_id] = domain_cid
                    blocks[domain_cid] = domain_json

                # Export domain boundaries
                boundary_cids = []
                for boundary_id, boundary in self._boundaries.items():
                    # Replace domain IDs with their CIDs
                    boundary_dict = boundary.to_dict()
                    if boundary.source_domain_id in domain_cids:
                        boundary_dict["source_domain"] = {">/": domain_cids[boundary.source_domain_id]}
                    if boundary.target_domain_id in domain_cids:
                        boundary_dict["target_domain"] = {">/": domain_cids[boundary.target_domain_id]}

                    boundary_json = json.dumps(boundary_dict).encode('utf-8')
                    boundary_cid = self.ipld_storage.put(boundary_json)
                    boundary_cids.append(boundary_cid)
                    blocks[boundary_cid] = boundary_json

            # Export versions if requested
            version_cids = {}
            if include_versions and self._versions:
                for version_id, version in self._versions.items():
                    # Link to node CID if available
                    version_dict = version.to_dict()
                    if version.node_id in node_cids:
                        version_dict["node"] = {">/": node_cids[version.node_id]}
                    if version.parent_version_id in version_cids:
                        version_dict["parent_version"] = {">/": version_cids[version.parent_version_id]}

                    version_json = json.dumps(version_dict).encode('utf-8')
                    version_cid = self.ipld_storage.put(version_json)
                    version_cids[version_id] = version_cid
                    blocks[version_cid] = version_json

            # Export transformation details if requested
            transform_detail_cids = {}
            if include_transformation_details and self._transformation_details:
                for detail_id, detail in self._transformation_details.items():
                    detail_json = json.dumps(detail.to_dict()).encode('utf-8')
                    detail_cid = self.ipld_storage.put(detail_json)
                    transform_detail_cids[detail_id] = detail_cid
                    blocks[detail_cid] = detail_json

            # Create root block with metadata and links to all components
            root_data = {
                "metadata": self.metadata,
                "nodes": [{">/": cid} for cid in node_cids.values()],
                "edges": [{">/": cid} for cid in edge_cids],
                "tracker_id": self.tracker_id,
                "created_at": datetime.datetime.now().isoformat()
            }

            # Add optional components if included
            if include_domains and domain_cids:
                root_data["domains"] = [{">/": cid} for cid in domain_cids.values()]
                root_data["boundaries"] = [{">/": cid} for cid in boundary_cids]

            if include_versions and version_cids:
                root_data["versions"] = [{">/": cid} for cid in version_cids.values()]

            if include_transformation_details and transform_detail_cids:
                root_data["transformation_details"] = [{">/": cid} for cid in transform_detail_cids.values()]

            # Encode and store root block
            root_json = json.dumps(root_data).encode('utf-8')
            root_cid = self.ipld_storage.put(root_json)
            blocks[root_cid] = root_json

            # Update root CID reference
            self._root_cid = root_cid

            # Store blocks in IPLD storage
            for cid, block_data in blocks.items():
                if not self.ipld_storage.has(cid):
                    self.ipld_storage.put(block_data, cid=cid)

            # Cache blocks for faster access
            self._ipld_blocks = blocks

            self.logger.info(f"Exported lineage graph to IPLD: root CID {root_cid}")
            self.logger.info(f"Exported {len(node_cids)} nodes, {len(edge_cids)} edges, "
                          f"{len(domain_cids) if include_domains else 0} domains, "
                          f"{len(version_cids) if include_versions else 0} versions, "
                          f"{len(transform_detail_cids) if include_transformation_details else 0} transformation details")

            return root_cid

        except Exception as e:
            self.logger.error(f"Error exporting to IPLD: {str(e)}")
            return None

    @classmethod
    def from_ipld(cls, root_cid: str, ipld_storage=None, config: Optional[Dict[str, Any]] = None) -> Optional['EnhancedLineageTracker']:
        """
        Create an EnhancedLineageTracker instance from an IPLD-stored lineage graph.

        Args:
            root_cid: The root CID of the IPLD-stored lineage graph
            ipld_storage: Optional IPLD storage instance to use
            config: Optional configuration for the new tracker

        Returns:
            Optional[EnhancedLineageTracker]: New tracker instance or None if import fails
        """
        try:
            import json
            from ipfs_datasets_py.ipld.storage import IPLDStorage

            # Create IPLD storage if not provided
            storage = ipld_storage or IPLDStorage()

            # Create configuration with IPLD storage enabled
            effective_config = config or {}
            effective_config["enable_ipld_storage"] = True

            # Create new tracker instance
            tracker = cls(storage=storage, config=effective_config)

            # Get root block
            root_block = storage.get(root_cid)
            if not root_block:
                raise ValueError(f"Root block with CID {root_cid} not found")

            root_data = json.loads(root_block.decode('utf-8'))

            # Extract metadata
            tracker.metadata = root_data.get("metadata", {})
            tracker.tracker_id = root_data.get("tracker_id", str(uuid.uuid4()))

            # Helper function to resolve CID links
            def resolve_link(link_obj):
                if isinstance(link_obj, dict) and ">/>" in link_obj:
                    link_cid = link_obj[">/"]
                    link_block = storage.get(link_cid)
                    if link_block:
                        return json.loads(link_block.decode('utf-8'))
                return None

            # Import nodes
            node_blocks = [resolve_link(link) for link in root_data.get("nodes", [])]
            for node_block in node_blocks:
                if node_block:
                    node_id = node_block.get("node_id")
                    data = node_block.get("data", {})
                    tracker._graph.add_node(node_id, **data)

            # Import edges
            edge_blocks = [resolve_link(link) for link in root_data.get("edges", [])]
            for edge_block in edge_blocks:
                if edge_block:
                    source_data = resolve_link(edge_block.get("source"))
                    target_data = resolve_link(edge_block.get("target"))
                    if source_data and target_data:
                        source_id = source_data.get("node_id")
                        target_id = target_data.get("node_id")
                        edge_data = edge_block.get("data", {})
                        tracker._graph.add_edge(source_id, target_id, **edge_data)

            # Import domains if present
            if "domains" in root_data:
                domain_blocks = [resolve_link(link) for link in root_data.get("domains", [])]
                for domain_block in domain_blocks:
                    if domain_block:
                        domain = LineageDomain(**domain_block)
                        tracker._domains[domain.domain_id] = domain

            # Import boundaries if present
            if "boundaries" in root_data:
                boundary_blocks = [resolve_link(link) for link in root_data.get("boundaries", [])]
                for boundary_block in boundary_blocks:
                    if boundary_block:
                        boundary = LineageBoundary(**boundary_block)
                        tracker._boundaries[boundary.boundary_id] = boundary

            # Import versions if present
            if "versions" in root_data:
                version_blocks = [resolve_link(link) for link in root_data.get("versions", [])]
                for version_block in version_blocks:
                    if version_block:
                        version = LineageVersion(**version_block)
                        tracker._versions[version.version_id] = version

            # Import transformation details if present
            if "transformation_details" in root_data:
                detail_blocks = [resolve_link(link) for link in root_data.get("transformation_details", [])]
                for detail_block in detail_blocks:
                    if detail_block:
                        detail = LineageTransformationDetail(**detail_block)
                        tracker._transformation_details[detail.detail_id] = detail

            # Set root CID reference
            tracker._root_cid = root_cid

            return tracker

        except Exception as e:
            logger.error(f"Error importing from IPLD: {str(e)}")
            return None

    def visualize_lineage(self, subgraph: Optional[LineageSubgraph] = None,
                       output_path: Optional[str] = None,
                       visualization_type: str = "interactive",
                       include_domains: bool = True) -> Any:
        """
        Visualize the lineage graph or a subgraph.

        Args:
            subgraph: Optional subgraph to visualize, if None visualizes the entire graph
            output_path: Path to save visualization output
            visualization_type: Type of visualization (static, interactive, or temporal)
            include_domains: Whether to include domain information in visualization

        Returns:
            Any: Visualization object or path to saved visualization
        """
        try:
            if visualization_type == "interactive" and PLOTLY_AVAILABLE:
                return self._visualize_interactive(subgraph, output_path, include_domains)
            else:
                return self._visualize_static(subgraph, output_path, include_domains)
        except Exception as e:
            self.logger.error(f"Error visualizing lineage: {str(e)}")
            return None

    def _visualize_interactive(self, subgraph: Optional[LineageSubgraph] = None,
                            output_path: Optional[str] = None,
                            include_domains: bool = True) -> Any:
        """Create an interactive visualization using Plotly."""
        import plotly.graph_objects as go
        import networkx as nx
        import numpy as np

        # Get the graph to visualize
        if subgraph:
            graph = nx.DiGraph()
            for node_id, node in subgraph.nodes.items():
                graph.add_node(node_id, **node.to_dict())
            for link in subgraph.links:
                graph.add_edge(link.source_id, link.target_id, **link.to_dict())
        else:
            graph = self._graph

        # Compute layout
        pos = nx.spring_layout(graph, seed=42)

        # Create edges
        edge_trace = go.Scatter(
            x=[],
            y=[],
            line=dict(width=0.5, color='#888'),
            hoverinfo='none',
            mode='lines')

        for edge in graph.edges():
            x0, y0 = pos[edge[0]]
            x1, y1 = pos[edge[1]]
            edge_trace['x'] += tuple([x0, x1, None])
            edge_trace['y'] += tuple([y0, y1, None])

        # Create nodes
        node_x = []
        node_y = []
        for node in graph.nodes():
            x, y = pos[node]
            node_x.append(x)
            node_y.append(y)

        # Node coloring based on type or domain
        colors = []
        node_types = set()
        domains = set()

        for node in graph.nodes():
            if include_domains and 'domain_id' in graph.nodes[node]:
                domains.add(graph.nodes[node]['domain_id'])
            else:
                node_types.add(graph.nodes[node].get('node_type', 'unknown'))

        # Create color map
        color_map = {}
        if include_domains and domains:
            for i, domain in enumerate(domains):
                color_map[domain] = i

            for node in graph.nodes():
                if 'domain_id' in graph.nodes[node]:
                    colors.append(color_map[graph.nodes[node]['domain_id']])
                else:
                    colors.append(0)
        else:
            for i, node_type in enumerate(node_types):
                color_map[node_type] = i

            for node in graph.nodes():
                colors.append(color_map.get(graph.nodes[node].get('node_type', 'unknown'), 0))

        # Create node trace
        node_trace = go.Scatter(
            x=node_x, y=node_y,
            mode='markers',
            hoverinfo='text',
            marker=dict(
                showscale=True,
                colorscale='YlGnBu',
                color=colors,
                size=10,
                colorbar=dict(
                    thickness=15,
                    title='Node Type/Domain',
                    xanchor='left',
                    titleside='right'
                ),
                line_width=2))

        # Create node text information
        node_text = []
        for node in graph.nodes():
            info = f"ID: {node}<br>"
            for key, value in graph.nodes[node].items():
                if key in ('node_type', 'entity_id', 'timestamp'):
                    info += f"{key}: {value}<br>"
            node_text.append(info)

        node_trace.text = node_text

        # Create figure
        fig = go.Figure(data=[edge_trace, node_trace],
                     layout=go.Layout(
                        title='Lineage Graph Visualization',
                        titlefont_size=16,
                        showlegend=False,
                        hovermode='closest',
                        margin=dict(b=20,l=5,r=5,t=40),
                        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False))
                      )

        # Save if path provided
        if output_path:
            pio.write_html(fig, output_path)
            return output_path

        return fig

    def _visualize_static(self, subgraph: Optional[LineageSubgraph] = None,
                       output_path: Optional[str] = None,
                       include_domains: bool = True) -> Any:
        """Create a static visualization using matplotlib."""
        import matplotlib.pyplot as plt
        import networkx as nx

        # Get the graph to visualize
        if subgraph:
            graph = nx.DiGraph()
            for node_id, node in subgraph.nodes.items():
                graph.add_node(node_id, **node.to_dict())
            for link in subgraph.links:
                graph.add_edge(link.source_id, link.target_id, **link.to_dict())
        else:
            graph = self._graph

        # Create figure
        plt.figure(figsize=(12, 10))

        # Node coloring based on type or domain
        if include_domains:
            # Color by domain
            domain_map = {}
            color_list = []
            for i, node in enumerate(graph.nodes()):
                domain_id = graph.nodes[node].get('domain_id')
                if domain_id:
                    if domain_id not in domain_map:
                        domain_map[domain_id] = len(domain_map)
                    color_list.append(domain_map[domain_id])
                else:
                    color_list.append(0)
        else:
            # Color by node type
            type_map = {}
            color_list = []
            for i, node in enumerate(graph.nodes()):
                node_type = graph.nodes[node].get('node_type', 'unknown')
                if node_type not in type_map:
                    type_map[node_type] = len(type_map)
                color_list.append(type_map[node_type])

        # Compute layout
        pos = nx.spring_layout(graph, seed=42)

        # Draw the graph
        nx.draw_networkx(
            graph,
            pos=pos,
            with_labels=True,
            node_color=color_list,
            cmap=plt.cm.tab10,
            node_size=500,
            alpha=0.8,
            arrows=True,
            arrowsize=10,
            width=1.0
        )

        # Add title
        plt.title("Lineage Graph Visualization", fontsize=16)

        # Save if path provided
        if output_path:
            plt.savefig(output_path, dpi=300, bbox_inches='tight')
            plt.close()
            return output_path

        return plt

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "nodes": {node_id: node.to_dict() for node_id, node in self.nodes.items()},
            "links": [link.to_dict() for link in self.links],
            "root_id": self.root_id,
            "metadata": self.metadata
        }


    def add_metadata_inheritance_rule(self, source_type: str, target_type: str,
                               properties: List[str], condition: Optional[Callable] = None,
                               override: bool = False) -> None:
        """
        Add a rule for metadata inheritance between nodes.

        This allows certain metadata properties to automatically propagate
        from one node to related nodes based on their types and relationships.

        Args:
            source_type: Type of source node
            target_type: Type of target node
            properties: List of properties to inherit
            condition: Optional function to determine if rule applies
            override: Whether inherited values should override existing values
        """
        rule_id = f"{source_type}:{target_type}:{','.join(properties)}"

        self._metadata_inheritance[rule_id] = {
            "source_type": source_type,
            "target_type": target_type,
            "properties": properties,
            "condition": condition,
            "override": override
        }

        self.logger.info(f"Added metadata inheritance rule {rule_id}")

    def apply_metadata_inheritance(self) -> int:
        """
        Apply all metadata inheritance rules to the lineage graph.

        This propagates metadata according to the defined rules.

        Returns:
            int: Number of metadata values propagated
        """
        propagated_count = 0

        # Iterate through all edges in the graph
        for source_id, target_id, edge_data in self._graph.edges(data=True):
            source_data = self._graph.nodes[source_id]
            target_data = self._graph.nodes[target_id]

            source_type = source_data.get('node_type', 'unknown')
            target_type = target_data.get('node_type', 'unknown')

            # Check for matching rules
            for rule in self._metadata_inheritance.values():
                if rule['source_type'] == source_type and rule['target_type'] == target_type:
                    # Check condition if present
                    if rule['condition'] is not None:
                        try:
                            if not rule['condition'](source_data, target_data, edge_data):
                                continue
                        except Exception as e:
                            self.logger.warning(f"Error in inheritance rule condition: {str(e)}")
                            continue

                    # Ensure metadata dictionaries exist
                    if 'metadata' not in source_data:
                        source_data['metadata'] = {}
                    if 'metadata' not in target_data:
                        target_data['metadata'] = {}

                    source_metadata = source_data.get('metadata', {})
                    target_metadata = target_data.get('metadata', {})

                    # Propagate properties
                    for prop in rule['properties']:
                        if prop in source_metadata:
                            # Only propagate if property doesn't exist or override is enabled
                            if prop not in target_metadata or rule['override']:
                                target_metadata[prop] = source_metadata[prop]
                                propagated_count += 1

        self.logger.info(f"Applied metadata inheritance: {propagated_count} values propagated")
        return propagated_count

    def validate_temporal_consistency(self) -> List[Dict[str, Any]]:
        """
        Validate temporal consistency across the entire lineage graph.

        This ensures that all relationships follow a logical temporal order,
        where data flows from earlier nodes to later nodes.

        Returns:
            List[Dict[str, Any]]: List of inconsistencies found
        """
        inconsistencies = []

        for source, target, data in self._graph.edges(data=True):
            source_time = self._graph.nodes[source].get('timestamp', 0)
            target_time = self._graph.nodes[target].get('timestamp', 0)

            # Allow small tolerance for processing delays
            if target_time < source_time - 0.1:  # 100ms tolerance
                inconsistency = {
                    "source_id": source,
                    "target_id": target,
                    "relationship_type": data.get('relationship_type', data.get('edge_type', 'unknown')),
                    "source_time": source_time,
                    "target_time": target_time,
                    "time_difference": source_time - target_time
                }
                inconsistencies.append(inconsistency)

        if inconsistencies:
            self.logger.warning(f"Found {len(inconsistencies)} temporal inconsistencies")

        return inconsistencies

    def get_entity_lineage(self, entity_id: str, include_semantic: bool = True) -> LineageSubgraph:
        """
        Get complete lineage for a specific entity.

        This tracks all nodes and relationships associated with this entity.

        Args:
            entity_id: The entity ID to trace
            include_semantic: Whether to include semantic relationships

        Returns:
            LineageSubgraph: Subgraph of the entity's complete lineage
        """
        if entity_id not in self._entity_to_nodes and not hasattr(self, '_build_entity_index'):
            # Build entity index if needed
            self._entity_to_nodes = {}
            for node_id, attrs in self._graph.nodes(data=True):
                entity = attrs.get('entity_id')
                if entity:
                    if entity not in self._entity_to_nodes:
                        self._entity_to_nodes[entity] = []
                    self._entity_to_nodes[entity].append(node_id)

        # Find all nodes for this entity
        entity_nodes = self._entity_to_nodes.get(entity_id, [])
        if not entity_nodes:
            self.logger.warning(f"No nodes found for entity {entity_id}")
            return LineageSubgraph(
                nodes={},
                links=[],
                root_id="entity_lineage",
                metadata={"entity_id": entity_id}
            )

        # Create query that includes this entity and finds its lineage
        query = {
            "entity_id": entity_id,
            "include_domains": True,
            "include_versions": True,
            "include_transformation_details": True
        }

        # Get direct entity nodes
        entity_subgraph = self.query_lineage(query)

        # Find upstream and downstream nodes to complete the lineage
        all_nodes = set(entity_nodes)
        for node_id in entity_nodes:
            # Find upstream nodes (ancestors)
            ancestors = set(nx.ancestors(self._graph, node_id))
            # Find downstream nodes (descendants)
            descendants = set(nx.descendants(self._graph, node_id))

            all_nodes.update(ancestors)
            all_nodes.update(descendants)

        # Include semantic relationships if requested
        if include_semantic and self._semantic_relationships:
            for rel_id, rel_data in self._semantic_relationships.items():
                source_id = rel_data.get('source_id')
                target_id = rel_data.get('target_id')

                if source_id in all_nodes:
                    all_nodes.add(target_id)
                elif target_id in all_nodes:
                    all_nodes.add(source_id)

        # Extract complete subgraph
        return LineageSubgraph(
            nodes={node_id: LineageNode(
                node_id=node_id,
                node_type=self._graph.nodes[node_id].get('node_type', 'unknown'),
                entity_id=self._graph.nodes[node_id].get('entity_id'),
                metadata=self._graph.nodes[node_id].get('metadata', {})
            ) for node_id in all_nodes if node_id in self._graph},
            links=[LineageLink(
                source_id=u,
                target_id=v,
                relationship_type=data.get('relationship_type', data.get('edge_type', 'unknown')),
                confidence=data.get('confidence', 1.0),
                metadata=data.get('metadata', {})
            ) for u, v, data in self._graph.subgraph(all_nodes).edges(data=True)],
            root_id="entity_lineage",
            metadata={
                "entity_id": entity_id,
                "direct_nodes": len(entity_nodes),
                "total_nodes": len(all_nodes),
                "query_timestamp": datetime.datetime.now().isoformat()
            }
        )

    def generate_provenance_report(self,
                               entity_id: Optional[str] = None,
                               node_id: Optional[str] = None,
                               include_visualization: bool = True,
                               format: str = "json") -> Dict[str, Any]:
        """
        Generate a comprehensive provenance report.

        This provides a detailed report on the lineage of a specific entity or node,
        including metrics, visualizations, and detailed path analysis.

        Args:
            entity_id: Optional entity ID to report on
            node_id: Optional node ID to report on
            include_visualization: Whether to include visualization
            format: Report format ('json', 'html', or 'text')

        Returns:
            Dict[str, Any]: Comprehensive provenance report
        """
        report = {
            "generated_at": datetime.datetime.now().isoformat(),
            "tracker_id": self.tracker_id,
            "report_type": "provenance_report"
        }

        # Get lineage
        if entity_id:
            report["entity_id"] = entity_id
            report["report_subject"] = f"Entity: {entity_id}"
            lineage = self.get_entity_lineage(entity_id)
        elif node_id:
            report["node_id"] = node_id
            node_type = self._graph.nodes[node_id].get('node_type', 'unknown') if node_id in self._graph else "unknown"
            report["report_subject"] = f"Node: {node_id} (Type: {node_type})"
            lineage = self.extract_subgraph(node_id, max_depth=5, include_domains=True,
                                         include_versions=True, include_transformation_details=True)
        else:
            # Report on entire graph
            report["report_subject"] = "Complete Lineage Graph"
            # Create a minimal subgraph with summary information
            lineage = LineageSubgraph(
                nodes={},
                links=[],
                root_id="summary",
                metadata={
                    "node_count": len(self._graph.nodes()),
                    "link_count": len(self._graph.edges()),
                    "domain_count": len(self._domains),
                    "timestamp": datetime.datetime.now().isoformat()
                }
            )

        # Basic statistics
        report["statistics"] = {
            "node_count": len(lineage.nodes),
            "link_count": len(lineage.links),
            "domain_count": len(lineage.domains) if hasattr(lineage, 'domains') else 0,
            "max_path_length": self._calculate_max_path_length(lineage),
            "node_types": self._count_node_types(lineage)
        }

        # Add metrics if we have a specific node or entity
        if node_id and node_id in self._graph:
            report["metrics"] = {
                "impact_score": LineageMetrics.calculate_impact_score(self._graph, node_id),
                "dependency_score": LineageMetrics.calculate_dependency_score(self._graph, node_id),
                "centrality": LineageMetrics.calculate_centrality(self._graph).get(node_id, 0),
                "complexity": LineageMetrics.calculate_complexity(self._graph, node_id)
            }

        # Include visualization if requested
        if include_visualization and PLOTLY_AVAILABLE:
            try:
                # Create interactive visualization
                viz = self._visualize_interactive(lineage, include_domains=True)

                # Convert to appropriate format
                if format == "html":
                    import plotly.io as pio
                    # Generate HTML representation
                    html_viz = pio.to_html(viz, include_plotlyjs=True, full_html=True)
                    report["visualization"] = html_viz
                else:
                    # Include JSON representation for other formats
                    report["visualization"] = {
                        "type": "plotly",
                        "data": viz.to_json()
                    }
            except Exception as e:
                self.logger.warning(f"Error generating visualization: {str(e)}")
                report["visualization_error"] = str(e)

        # Format report as requested
        if format == "text":
            # Create text summary of the report
            text_report = f"PROVENANCE REPORT\n"
            text_report += f"Generated: {report['generated_at']}\n"
            text_report += f"Subject: {report['report_subject']}\n\n"
            text_report += f"STATISTICS:\n"
            for key, value in report['statistics'].items():
                text_report += f"- {key}: {value}\n"

            if "metrics" in report:
                text_report += f"\nMETRICS:\n"
                for key, value in report['metrics'].items():
                    if isinstance(value, dict):
                        text_report += f"- {key}:\n"
                        for subkey, subvalue in value.items():
                            text_report += f"  - {subkey}: {subvalue}\n"
                    else:
                        text_report += f"- {key}: {value}\n"

            report["text_summary"] = text_report

        return report

    def _calculate_max_path_length(self, lineage: LineageSubgraph) -> int:
        """Calculate the maximum path length in a lineage subgraph."""
        if not lineage.nodes or len(lineage.nodes) <= 1:
            return 0

        # Create a graph from the lineage
        G = nx.DiGraph()
        for node_id in lineage.nodes:
            G.add_node(node_id)

        for link in lineage.links:
            G.add_edge(link.source_id, link.target_id)

        # Find all paths between all pairs of nodes
        max_length = 0

        # Use a more efficient approach for larger graphs
        if len(G.nodes) > 100:
            # For larger graphs, estimate using diameter
            try:
                # Convert to undirected for diameter calculation
                undirected = G.to_undirected()
                # Get all connected components
                components = list(nx.connected_components(undirected))

                # Find diameter of each component
                for component in components:
                    if len(component) > 1:
                        subgraph = undirected.subgraph(component)
                        length = nx.diameter(subgraph)
                        max_length = max(max_length, length)
            except:
                # Fallback for errors
                self.logger.info("Using shortest paths for path length calculation")
                all_pairs = nx.all_pairs_shortest_path_length(G)
                for source, targets in all_pairs:
                    for target, length in targets.items():
                        max_length = max(max_length, length)
        else:
            # For smaller graphs, calculate all simple paths
            node_list = list(G.nodes())
            for i in range(len(node_list)):
                for j in range(len(node_list)):
                    if i != j:
                        try:
                            paths = list(nx.all_simple_paths(G, node_list[i], node_list[j]))
                            if paths:
                                max_path = max(paths, key=len)
                                max_length = max(max_length, len(max_path) - 1)  # -1 because path length is nodes-1
                        except nx.NetworkXNoPath:
                            pass

        return max_length

    def _count_node_types(self, lineage: LineageSubgraph) -> Dict[str, int]:
        """Count occurrences of each node type in a lineage subgraph."""
        type_counts = {}

        for _, node in lineage.nodes.items():
            node_type = node.node_type
            if node_type not in type_counts:
                type_counts[node_type] = 0
            type_counts[node_type] += 1

        return type_counts


class LineageMetrics:
    """Calculate metrics for data lineage analysis."""

    @staticmethod
    def calculate_impact_score(graph: nx.DiGraph, node_id: str) -> float:
        """
        Calculate the impact score of a node in the lineage graph.

        The impact score measures how many other nodes are affected by this node.

        Args:
            graph: The lineage graph
            node_id: The ID of the node to calculate impact for

        Returns:
            float: Impact score between 0.0 and 1.0
        """
        if node_id not in graph:
            return 0.0

        # Get all nodes reachable from this node
        affected_nodes = set(nx.descendants(graph, node_id))

        # If no descendants, return 0
        if not affected_nodes:
            return 0.0

        # Calculate score based on percentage of nodes affected
        total_nodes = len(graph.nodes())
        if total_nodes <= 1:
            return 0.0

        return len(affected_nodes) / (total_nodes - 1)

    @staticmethod
    def calculate_dependency_score(graph: nx.DiGraph, node_id: str) -> float:
        """
        Calculate the dependency score of a node in the lineage graph.

        The dependency score measures how many other nodes this node depends on.

        Args:
            graph: The lineage graph
            node_id: The ID of the node to calculate dependency for

        Returns:
            float: Dependency score between 0.0 and 1.0
        """
        if node_id not in graph:
            return 0.0

        # Get all nodes that this node depends on
        dependency_nodes = set(nx.ancestors(graph, node_id))

        # If no ancestors, return 0
        if not dependency_nodes:
            return 0.0

        # Calculate score based on percentage of nodes depended on
        total_nodes = len(graph.nodes())
        if total_nodes <= 1:
            return 0.0

        return len(dependency_nodes) / (total_nodes - 1)

    @staticmethod
    def calculate_centrality(graph: nx.DiGraph, node_type: Optional[str] = None) -> Dict[str, float]:
        """
        Calculate centrality metrics for nodes in the lineage graph.

        Args:
            graph: The lineage graph
            node_type: Optional filter for node type

        Returns:
            Dict[str, float]: Dictionary mapping node IDs to centrality scores
        """
        # Use betweenness centrality as default metric
        centrality = nx.betweenness_centrality(graph)

        # Filter by node type if specified
        if node_type:
            centrality = {
                node_id: score for node_id, score in centrality.items()
                if graph.nodes[node_id].get('node_type') == node_type
            }

        return centrality

    @staticmethod
    def identify_critical_paths(graph: nx.DiGraph) -> List[List[str]]:
        """
        Identify critical paths in the lineage graph.

        Critical paths are sequences of nodes with high impact
        that represent important data transformation chains.

        Args:
            graph: The lineage graph

        Returns:
            List[List[str]]: List of critical paths (each path is a list of node IDs)
        """
        critical_paths = []

        # Find all source nodes (nodes with no incoming edges)
        source_nodes = [n for n in graph.nodes() if graph.in_degree(n) == 0]

        # Find all sink nodes (nodes with no outgoing edges)
        sink_nodes = [n for n in graph.nodes() if graph.out_degree(n) == 0]

        # Calculate centrality for all nodes
        centrality = nx.betweenness_centrality(graph)

        # For each source-sink pair, find the path with highest average centrality
        for source in source_nodes:
            for sink in sink_nodes:
                try:
                    # Find all simple paths between source and sink
                    paths = list(nx.all_simple_paths(graph, source, sink))

                    if not paths:
                        continue

                    # Calculate average centrality for each path
                    path_scores = []
                    for path in paths:
                        if len(path) <= 1:
                            continue

                        avg_centrality = sum(centrality[node] for node in path) / len(path)
                        path_scores.append((path, avg_centrality))

                    # Find the path with highest average centrality
                    if path_scores:
                        path_scores.sort(key=lambda x: x[1], reverse=True)
                        best_path, score = path_scores[0]

                        # Only include paths with high enough centrality
                        if score > 0.1:  # Threshold can be adjusted
                            critical_paths.append(best_path)
                except nx.NetworkXNoPath:
                    continue

        return critical_paths

    @staticmethod
    def calculate_complexity(graph: nx.DiGraph, node_id: str) -> Dict[str, Any]:
        """
        Calculate complexity metrics for a node's lineage.

        Args:
            graph: The lineage graph
            node_id: The ID of the node to calculate complexity for

        Returns:
            Dict[str, Any]: Complexity metrics
        """
        if node_id not in graph:
            return {
                "error": f"Node {node_id} not found in graph",
                "node_count": 0,
                "edge_count": 0,
                "max_depth": 0
            }

        # Create a subgraph of all ancestors (dependencies)
        try:
            ancestors = set(nx.ancestors(graph, node_id))
            ancestors.add(node_id)  # Include the node itself
            subgraph = graph.subgraph(ancestors)

            # Calculate basic complexity metrics
            node_count = len(subgraph.nodes())
            edge_count = len(subgraph.edges())

            # Calculate maximum depth (longest path to any ancestor)
            max_depth = 0
            for ancestor in ancestors:
                if ancestor != node_id:
                    try:
                        # Find the longest path from ancestor to node
                        paths = list(nx.all_simple_paths(subgraph, ancestor, node_id))
                        if paths:
                            max_path_length = max(len(path) for path in paths)
                            max_depth = max(max_depth, max_path_length)
                    except (nx.NetworkXNoPath, nx.NodeNotFound):
                        continue

            # Count nodes by type
            node_type_counts = {}
            for node in subgraph.nodes():
                node_type = subgraph.nodes[node].get('node_type', 'unknown')
                node_type_counts[node_type] = node_type_counts.get(node_type, 0) + 1

            record_type_counts = {}
            for node in subgraph.nodes():
                record_type = subgraph.nodes[node].get('record_type', 'unknown')
                record_type_counts[record_type] = record_type_counts.get(record_type, 0) + 1

            return {
                "node_count": node_count,
                "edge_count": edge_count,
                "max_depth": max_depth,
                "node_type_counts": node_type_counts,
                "record_type_counts": record_type_counts
            }

        except Exception as e:
            logger.error(f"Error calculating complexity metrics for node {node_id}: {str(e)}")
            return {
                "error": str(e),
                "node_count": 0,
                "edge_count": 0,
                "max_depth": 0
            }


class CrossDocumentLineageTracker:
    """
    Tracks lineage across multiple documents and datasets with detailed metadata.

    This class provides comprehensive capabilities for tracking, analyzing,
    and visualizing data lineage across multiple documents and transformations.
    """

    def __init__(
        self,
        provenance_manager: Optional[Any] = None,
        storage_path: Optional[str] = None,
        visualization_engine: str = "matplotlib"
    ):
        """
        Initialize the cross-document lineage tracker.

        Args:
            provenance_manager: Optional provenance manager instance
            storage_path: Path to store lineage data
            visualization_engine: Engine to use for visualizations
        """
        self.storage_path = storage_path
        self.visualization_engine = visualization_engine

        # Create a new directed graph for tracking lineage
        self.graph = nx.DiGraph()

        # Reference to provenance manager if available
        self.provenance_manager = provenance_manager

        # Track node and relationship metadata
        self.node_metadata: Dict[str, Dict[str, Any]] = {}
        self.relationship_metadata: Dict[Tuple[str, str], Dict[str, Any]] = {}

        # Track data entities
        self.entities: Dict[str, Dict[str, Any]] = {}

        # Track critical paths and key nodes
        self.critical_paths: List[List[str]] = []
        self.hub_nodes: List[str] = []

        # Track cross-document connections
        self.cross_document_connections: List[Tuple[str, str, float]] = []

        # Initialize lineage metrics
        self.metrics = LineageMetrics()

    def add_node(
        self,
        node_id: str,
        node_type: str,
        entity_id: Optional[str] = None,
        record_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Add a node to the lineage graph.

        Args:
            node_id: Unique identifier for the node
            node_type: Type of node (e.g., 'document', 'transformation', 'dataset')
            entity_id: Optional ID of the entity this node represents
            record_type: Optional record type for provenance integration
            metadata: Additional metadata about the node

        Returns:
            str: The node ID
        """
        metadata = metadata or {}

        # Create node in graph
        self.graph.add_node(
            node_id,
            node_type=node_type,
            entity_id=entity_id,
            record_type=record_type,
            timestamp=metadata.get('timestamp', time.time())
        )

        # Store full metadata separately
        self.node_metadata[node_id] = {
            "node_type": node_type,
            "entity_id": entity_id,
            "record_type": record_type,
            "timestamp": metadata.get('timestamp', time.time()),
            **metadata
        }

        # Register entity if provided
        if entity_id:
            if entity_id not in self.entities:
                self.entities[entity_id] = {
                    "nodes": [node_id],
                    "metadata": metadata.get('entity_metadata', {})
                }
            else:
                self.entities[entity_id]["nodes"].append(node_id)

        return node_id

    def add_relationship(
        self,
        source_id: str,
        target_id: str,
        relationship_type: str,
        confidence: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
        direction: str = "forward"
    ) -> bool:
        """
        Add a relationship between nodes in the lineage graph.

        Args:
            source_id: ID of the source node
            target_id: ID of the target node
            relationship_type: Type of relationship
            confidence: Confidence level of the relationship (0.0 to 1.0)
            metadata: Additional metadata about the relationship
            direction: Direction of relationship (forward, backward, bidirectional)

        Returns:
            bool: Whether the relationship was added successfully
        """
        if source_id not in self.graph or target_id not in self.graph:
            logger.warning(
                f"Cannot add relationship: source {source_id} or target {target_id} "
                f"not found in graph."
            )
            return False

        metadata = metadata or {}

        # Add edge to graph
        self.graph.add_edge(
            source_id,
            target_id,
            relationship_type=relationship_type,
            confidence=confidence,
            timestamp=metadata.get('timestamp', time.time())
        )

        # Store full metadata separately
        self.relationship_metadata[(source_id, target_id)] = {
            "relationship_type": relationship_type,
            "confidence": confidence,
            "direction": direction,
            "timestamp": metadata.get('timestamp', time.time()),
            **metadata
        }

        # Check if this is a cross-document connection
        source_entity = self.node_metadata[source_id].get('entity_id')
        target_entity = self.node_metadata[target_id].get('entity_id')

        if source_entity and target_entity and source_entity != target_entity:
            # This is a cross-document connection
            self.cross_document_connections.append((source_id, target_id, confidence))

        # If bidirectional, add the reverse edge as well
        if direction == "bidirectional":
            self.graph.add_edge(
                target_id,
                source_id,
                relationship_type=relationship_type,
                confidence=confidence,
                timestamp=metadata.get('timestamp', time.time())
            )

            # Store reverse metadata separately
            self.relationship_metadata[(target_id, source_id)] = {
                "relationship_type": relationship_type,
                "confidence": confidence,
                "direction": direction,
                "timestamp": metadata.get('timestamp', time.time()),
                **metadata
            }

        return True

    def import_from_provenance_manager(
        self,
        include_types: Optional[List[str]] = None,
        max_records: int = 1000,
        confidence_threshold: float = 0.7
    ) -> int:
        """
        Import lineage data from a provenance manager.

        Args:
            include_types: Optional list of record types to include
            max_records: Maximum number of records to import
            confidence_threshold: Minimum confidence for inferred relationships

        Returns:
            int: Number of nodes imported
        """
        if not self.provenance_manager:
            logger.warning("No provenance manager available for import.")
            return 0

        # Count of imported nodes
        imported_count = 0

        # Import records from provenance manager
        try:
            # For base ProvenanceManager
            if BASE_PROVENANCE_AVAILABLE and isinstance(self.provenance_manager, ProvenanceManager):
                records = list(self.provenance_manager.records.values())[:max_records]

                # Filter by type if specified
                if include_types:
                    records = [
                        r for r in records
                        if r.record_type.value in include_types
                    ]

                # Import each record as a node
                for record in records:
                    # Generate node ID based on record ID
                    node_id = record.id

                    # Determine node type and entity ID based on record type
                    node_type = "record"
                    entity_id = None

                    if record.record_type == ProvenanceRecordType.SOURCE:
                        node_type = "source"
                        # For source records, entity ID is the source's data ID
                        if record.output_ids:
                            entity_id = record.output_ids[0]
                    elif record.record_type == ProvenanceRecordType.TRANSFORMATION:
                        node_type = "transformation"
                        # For transformations, entity ID is the output data ID
                        if record.output_ids:
                            entity_id = record.output_ids[0]
                    elif record.record_type == ProvenanceRecordType.QUERY:
                        node_type = "query"
                        # For queries, entity ID might be based on the query text
                        entity_id = f"query_{record.id}"
                    elif record.record_type == ProvenanceRecordType.MERGE:
                        node_type = "merge"
                        # For merges, entity ID is the output data ID
                        if record.output_ids:
                            entity_id = record.output_ids[0]

                    # Add node to lineage graph
                    self.add_node(
                        node_id=node_id,
                        node_type=node_type,
                        entity_id=entity_id,
                        record_type=record.record_type.value,
                        metadata=asdict(record)
                    )

                    imported_count += 1

                    # Add relationships based on input and output IDs
                    if hasattr(record, 'input_ids') and record.input_ids:
                        for input_id in record.input_ids:
                            # Find records with this input ID as their output ID
                            for input_record in records:
                                if hasattr(input_record, 'output_ids') and input_record.output_ids:
                                    if input_id in input_record.output_ids:
                                        # Add relationship
                                        self.add_relationship(
                                            source_id=input_record.id,
                                            target_id=record.id,
                                            relationship_type="input",
                                            confidence=1.0
                                        )

                    # Special handling for merge operations
                    if record.record_type == ProvenanceRecordType.MERGE:
                        # Merge operations directly connect input records
                        for input_id in record.input_ids:
                            for other_input_id in record.input_ids:
                                if input_id != other_input_id:
                                    # Add bidirectional relationship with lower confidence
                                    self.add_relationship(
                                        source_id=input_id,
                                        target_id=other_input_id,
                                        relationship_type="merged_with",
                                        confidence=0.8,
                                        direction="bidirectional"
                                    )

            # For EnhancedProvenanceManager
            elif ENHANCED_PROVENANCE_AVAILABLE and isinstance(self.provenance_manager, EnhancedProvenanceManager):
                # Use the query_records method if available
                if hasattr(self.provenance_manager, 'query_records'):
                    records = self.provenance_manager.query_records(limit=max_records)

                    # Filter by type if specified
                    if include_types:
                        records = [
                            r for r in records
                            if hasattr(r, 'record_type') and
                            (isinstance(r.record_type, str) and r.record_type in include_types or
                             hasattr(r.record_type, 'value') and r.record_type.value in include_types)
                        ]

                    # Import each record as a node
                    for record in records:
                        # Generate node ID based on record ID
                        node_id = record.id if hasattr(record, 'id') else str(uuid.uuid4())

                        # Determine node type based on record type
                        node_type = "record"
                        entity_id = None
                        record_type_value = None

                        if hasattr(record, 'record_type'):
                            record_type_value = record.record_type
                            if isinstance(record_type_value, str):
                                record_type_value = record_type_value
                            else:
                                record_type_value = record.record_type.value

                        # Extract common metadata
                        metadata = {}
                        for attr in dir(record):
                            if not attr.startswith('_') and attr not in ('to_dict', 'from_dict'):
                                try:
                                    value = getattr(record, attr)
                                    if not callable(value):
                                        metadata[attr] = value
                                except:
                                    pass

                        # Add node to lineage graph
                        self.add_node(
                            node_id=node_id,
                            node_type=node_type,
                            entity_id=entity_id,
                            record_type=record_type_value,
                            metadata=metadata
                        )

                        imported_count += 1
                else:
                    logger.warning("EnhancedProvenanceManager does not have query_records method.")

            # If available, try to build cross-document lineage
            if ENHANCED_PROVENANCE_AVAILABLE and isinstance(self.provenance_manager, EnhancedProvenanceManager):
                if hasattr(self.provenance_manager, 'storage') and isinstance(
                    self.provenance_manager.storage, IPLDProvenanceStorage
                ):
                    # Get all record IDs in our graph
                    record_ids = list(self.graph.nodes())

                    # Import cross-document lineage
                    try:
                        lineage_graph = self.provenance_manager.storage.build_cross_document_lineage_graph(
                            record_ids=record_ids,
                            max_depth=3
                        )

                        # Merge with our graph
                        for edge in lineage_graph.edges(data=True):
                            source, target, attrs = edge
                            if source in self.graph and target in self.graph:
                                self.add_relationship(
                                    source_id=source,
                                    target_id=target,
                                    relationship_type=attrs.get("type", "related"),
                                    confidence=attrs.get("confidence", 0.9),
                                    metadata=attrs
                                )

                        # Import any additional nodes from lineage graph
                        for node, attrs in lineage_graph.nodes(data=True):
                            if node not in self.graph:
                                self.add_node(
                                    node_id=node,
                                    node_type=attrs.get("record_type", "unknown"),
                                    metadata=attrs
                                )
                                imported_count += 1
                    except Exception as e:
                        logger.warning(f"Error importing cross-document lineage: {str(e)}")

        except Exception as e:
            logger.error(f"Error importing from provenance manager: {str(e)}")

        # Update critical paths and hub nodes
        self._update_analysis()

        return imported_count

    def _update_analysis(self):
        """Update critical paths, hub nodes, and other analysis results."""
        try:
            # Identify critical paths
            self.critical_paths = LineageMetrics.identify_critical_paths(self.graph)

            # Identify hub nodes using centrality
            centrality = LineageMetrics.calculate_centrality(self.graph)
            self.hub_nodes = [
                node for node, score in sorted(
                    centrality.items(), key=lambda x: x[1], reverse=True
                )[:10]  # Top 10 nodes by centrality
            ]
        except Exception as e:
            logger.error(f"Error updating analysis: {str(e)}")

    def get_lineage(
        self,
        node_id: str,
        direction: str = "backward",
        max_depth: int = 5,
        include_metadata: bool = True
    ) -> Dict[str, Any]:
        """
        Get the lineage for a specific node.

        Args:
            node_id: ID of the node to get lineage for
            direction: Direction of lineage (backward, forward, both)
            max_depth: Maximum depth of lineage traversal
            include_metadata: Whether to include full metadata

        Returns:
            Dict[str, Any]: Lineage information
        """
        if node_id not in self.graph:
            return {
                "error": f"Node {node_id} not found in graph",
                "nodes": [],
                "links": []
            }

        # Create subgraph for lineage
        nodes = set([node_id])
        links = []

        # Traverse graph in the specified direction
        if direction in ("backward", "both"):
            # Get ancestors up to max_depth
            ancestors = self._get_ancestors(node_id, max_depth)
            nodes.update(ancestors.keys())

            # Get links between ancestors
            for source, targets in ancestors.items():
                for target in targets:
                    if (source, target) in self.relationship_metadata:
                        metadata = self.relationship_metadata[(source, target)]
                        links.append({
                            "source": source,
                            "target": target,
                            "relationship_type": metadata.get("relationship_type", "unknown"),
                            "confidence": metadata.get("confidence", 1.0),
                            "metadata": metadata if include_metadata else {}
                        })

        if direction in ("forward", "both"):
            # Get descendants up to max_depth
            descendants = self._get_descendants(node_id, max_depth)
            nodes.update(descendants.keys())

            # Get links between descendants
            for source, targets in descendants.items():
                for target in targets:
                    if (source, target) in self.relationship_metadata:
                        metadata = self.relationship_metadata[(source, target)]
                        links.append({
                            "source": source,
                            "target": target,
                            "relationship_type": metadata.get("relationship_type", "unknown"),
                            "confidence": metadata.get("confidence", 1.0),
                            "metadata": metadata if include_metadata else {}
                        })

        # Get node data
        node_data = {}
        for n in nodes:
            node_metadata = self.node_metadata.get(n, {})
            node_data[n] = {
                "node_type": node_metadata.get("node_type", "unknown"),
                "entity_id": node_metadata.get("entity_id"),
                "record_type": node_metadata.get("record_type"),
                "metadata": node_metadata if include_metadata else {}
            }

        # Calculate impact metrics
        try:
            impact_score = LineageMetrics.calculate_impact_score(self.graph, node_id)
            dependency_score = LineageMetrics.calculate_dependency_score(self.graph, node_id)
            complexity = LineageMetrics.calculate_complexity(self.graph, node_id)
        except Exception as e:
            logger.error(f"Error calculating metrics: {str(e)}")
            impact_score = 0.0
            dependency_score = 0.0
            complexity = {"error": str(e)}

        return {
            "node_id": node_id,
            "nodes": node_data,
            "links": links,
            "metrics": {
                "impact_score": impact_score,
                "dependency_score": dependency_score,
                "complexity": complexity
            }
        }

    def _get_ancestors(self, node_id: str, max_depth: int) -> Dict[str, List[str]]:
        """
        Get the ancestors of a node up to a specified depth.

        Args:
            node_id: Node ID to get ancestors for
            max_depth: Maximum depth to traverse

        Returns:
            Dict[str, List[str]]: Map of node IDs to their children
        """
        ancestors = {}
        to_process = [(node_id, 0)]
        processed = set()

        while to_process:
            current, depth = to_process.pop(0)

            if current in processed:
                continue

            processed.add(current)

            if depth >= max_depth:
                continue

            # Get predecessors
            predecessors = list(self.graph.predecessors(current))

            if current not in ancestors:
                ancestors[current] = []

            # Add predecessors to ancestors map
            for pred in predecessors:
                if pred not in ancestors:
                    ancestors[pred] = []

                ancestors[pred].append(current)

                # Add predecessors to process queue
                if pred not in processed:
                    to_process.append((pred, depth + 1))

        return ancestors

    def _get_descendants(self, node_id: str, max_depth: int) -> Dict[str, List[str]]:
        """
        Get the descendants of a node up to a specified depth.

        Args:
            node_id: Node ID to get descendants for
            max_depth: Maximum depth to traverse

        Returns:
            Dict[str, List[str]]: Map of node IDs to their children
        """
        descendants = {}
        to_process = [(node_id, 0)]
        processed = set()

        while to_process:
            current, depth = to_process.pop(0)

            if current in processed:
                continue

            processed.add(current)

            if depth >= max_depth:
                continue

            # Get successors
            successors = list(self.graph.successors(current))

            if current not in descendants:
                descendants[current] = []

            # Add successors to descendants map
            for succ in successors:
                descendants[current].append(succ)

                # Add successors to process queue
                if succ not in processed:
                    to_process.append((succ, depth + 1))

        return descendants

    def get_entity_lineage(
        self,
        entity_id: str,
        direction: str = "both",
        include_related_entities: bool = True,
        max_depth: int = 3
    ) -> Dict[str, Any]:
        """
        Get lineage information for an entity across all its nodes.

        Args:
            entity_id: ID of the entity to get lineage for
            direction: Direction of lineage (backward, forward, both)
            include_related_entities: Whether to include connected entities
            max_depth: Maximum depth of entity traversal

        Returns:
            Dict[str, Any]: Entity lineage information
        """
        if entity_id not in self.entities:
            return {
                "error": f"Entity {entity_id} not found",
                "entities": [],
                "nodes": [],
                "links": []
            }

        # Get all nodes for this entity
        entity_nodes = self.entities[entity_id]["nodes"]

        # Map to track all entities included in the lineage
        included_entities = {entity_id: self.entities[entity_id]}

        # Set to track all nodes included in the lineage
        all_nodes = set(entity_nodes)

        # List to track all links
        all_links = []

        # Process each node for this entity
        for node_id in entity_nodes:
            # Get lineage for this node
            node_lineage = self.get_lineage(
                node_id=node_id,
                direction=direction,
                max_depth=max_depth,
                include_metadata=True
            )

            # Add nodes and links from this lineage
            all_nodes.update(node_lineage["nodes"].keys())
            all_links.extend(node_lineage["links"])

            # If including related entities, identify and add them
            if include_related_entities:
                for node_id, node_data in node_lineage["nodes"].items():
                    related_entity_id = node_data.get("entity_id")
                    if related_entity_id and related_entity_id != entity_id:
                        if related_entity_id in self.entities:
                            included_entities[related_entity_id] = self.entities[related_entity_id]

                            # Add all nodes for this entity
                            related_entity_nodes = self.entities[related_entity_id]["nodes"]
                            all_nodes.update(related_entity_nodes)

        # Get node data
        node_data = {}
        for node_id in all_nodes:
            node_metadata = self.node_metadata.get(node_id, {})
            node_data[node_id] = {
                "node_type": node_metadata.get("node_type", "unknown"),
                "entity_id": node_metadata.get("entity_id"),
                "record_type": node_metadata.get("record_type"),
                "metadata": node_metadata
            }

        # Calculate entity-level metrics
        entity_metrics = {
            "node_count": len(entity_nodes),
            "impact_score": 0.0,
            "dependency_score": 0.0,
            "centrality": 0.0
        }

        # Average metrics across all entity nodes
        if entity_nodes:
            total_impact = 0.0
            total_dependency = 0.0

            for node_id in entity_nodes:
                total_impact += LineageMetrics.calculate_impact_score(self.graph, node_id)
                total_dependency += LineageMetrics.calculate_dependency_score(self.graph, node_id)

            entity_metrics["impact_score"] = total_impact / len(entity_nodes)
            entity_metrics["dependency_score"] = total_dependency / len(entity_nodes)

            # Calculate centrality
            centrality = LineageMetrics.calculate_centrality(self.graph)
            entity_centrality = sum(centrality.get(node_id, 0.0) for node_id in entity_nodes)
            entity_metrics["centrality"] = entity_centrality / len(entity_nodes)

        return {
            "entity_id": entity_id,
            "entities": included_entities,
            "nodes": node_data,
            "links": all_links,
            "metrics": entity_metrics
        }

    def analyze_cross_document_lineage(self) -> Dict[str, Any]:
        """
        Analyze cross-document lineage in the graph.

        This method identifies and analyzes connections between different
        entities/documents in the lineage graph.

        Returns:
            Dict[str, Any]: Analysis results
        """
        # Analysis results
        results = {
            "node_count": len(self.graph.nodes()),
            "edge_count": len(self.graph.edges()),
            "entity_count": len(self.entities),
            "critical_paths": self.critical_paths,
            "critical_paths_count": len(self.critical_paths),
            "hub_nodes": self.hub_nodes,
            "cross_document_connections": self.cross_document_connections,
            "cross_document_connections_count": len(self.cross_document_connections)
        }

        # Find distinct document pairs that have connections
        document_pairs = set()
        for source_id, target_id, _ in self.cross_document_connections:
            source_entity = self.node_metadata[source_id].get('entity_id')
            target_entity = self.node_metadata[target_id].get('entity_id')

            if source_entity and target_entity and source_entity != target_entity:
                document_pairs.add((source_entity, target_entity))

        results["document_pair_count"] = len(document_pairs)

        # Calculate entity impact scores
        entity_impact = {}
        for entity_id, entity_data in self.entities.items():
            # Average impact score across all entity nodes
            total_impact = 0.0
            for node_id in entity_data["nodes"]:
                total_impact += LineageMetrics.calculate_impact_score(self.graph, node_id)

            if entity_data["nodes"]:
                entity_impact[entity_id] = total_impact / len(entity_data["nodes"])
            else:
                entity_impact[entity_id] = 0.0

        results["entity_impact"] = entity_impact

        # Calculate centrality for all nodes
        centrality = LineageMetrics.calculate_centrality(self.graph)
        results["node_centrality"] = centrality

        # Identify high-centrality nodes
        high_centrality_threshold = 0.5  # Adjust as needed
        high_centrality_nodes = {
            node_id: score for node_id, score in centrality.items()
            if score > high_centrality_threshold
        }

        results["high_centrality_nodes"] = high_centrality_nodes

        # Calculate entity centrality by averaging node centrality
        entity_centrality = {}
        for entity_id, entity_data in self.entities.items():
            # Average centrality across all entity nodes
            total_centrality = 0.0
            for node_id in entity_data["nodes"]:
                total_centrality += centrality.get(node_id, 0.0)

            if entity_data["nodes"]:
                entity_centrality[entity_id] = total_centrality / len(entity_data["nodes"])
            else:
                entity_centrality[entity_id] = 0.0

        results["entity_centrality"] = entity_centrality

        # Calculate graph density
        results["graph_density"] = nx.density(self.graph)

        return results

    def export_lineage_graph(self, output_format: str = "json") -> Union[Dict[str, Any], str]:
        """
        Export the lineage graph in various formats.

        Args:
            output_format: Format to export the graph in (json, networkx, gexf)

        Returns:
            Union[Dict[str, Any], str]: Exported graph data
        """
        if output_format == "json":
            # Export as JSON
            data = {
                "nodes": {},
                "links": [],
                "entities": self.entities,
                "metadata": {
                    "created_at": datetime.datetime.now().isoformat(),
                    "node_count": len(self.graph.nodes()),
                    "edge_count": len(self.graph.edges()),
                    "entity_count": len(self.entities)
                }
            }

            # Export nodes
            for node_id, metadata in self.node_metadata.items():
                data["nodes"][node_id] = metadata

            # Export links
            for (source, target), metadata in self.relationship_metadata.items():
                data["links"].append({
                    "source": source,
                    "target": target,
                    **metadata
                })

            return data

        elif output_format == "networkx":
            # Export as NetworkX graph (for direct use in other code)
            return self.graph

        elif output_format == "gexf":
            # Export as GEXF XML string for visualization tools like Gephi
            return nx.generate_gexf(self.graph)

        else:
            logger.warning(f"Unsupported output format: {output_format}")
            return {"error": f"Unsupported output format: {output_format}"}

    def import_lineage_graph(self, data: Dict[str, Any]) -> bool:
        """
        Import a lineage graph from exported data.

        Args:
            data: Exported graph data

        Returns:
            bool: Whether the import was successful
        """
        try:
            # Import nodes
            for node_id, metadata in data.get("nodes", {}).items():
                self.add_node(
                    node_id=node_id,
                    node_type=metadata.get("node_type", "unknown"),
                    entity_id=metadata.get("entity_id"),
                    record_type=metadata.get("record_type"),
                    metadata=metadata
                )

            # Import links
            for link in data.get("links", []):
                source = link.get("source")
                target = link.get("target")

                if source and target:
                    self.add_relationship(
                        source_id=source,
                        target_id=target,
                        relationship_type=link.get("relationship_type", "unknown"),
                        confidence=link.get("confidence", 1.0),
                        metadata=link,
                        direction=link.get("direction", "forward")
                    )

            # Import entities if present
            if "entities" in data:
                for entity_id, entity_data in data["entities"].items():
                    # Only set metadata; nodes are already imported
                    if entity_id in self.entities:
                        self.entities[entity_id]["metadata"].update(entity_data.get("metadata", {}))

            # Update analysis
            self._update_analysis()

            return True

        except Exception as e:
            logger.error(f"Error importing lineage graph: {str(e)}")
            return False

    def visualize_lineage(
        self,
        node_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        direction: str = "both",
        max_depth: int = 3,
        include_metadata: bool = False,
        output_path: Optional[str] = None,
        format: str = "png",
        interactive: bool = False
    ) -> Optional[str]:
        """
        Visualize lineage for a specific node or entity.

        Args:
            node_id: Optional node ID to visualize lineage for
            entity_id: Optional entity ID to visualize lineage for
            direction: Direction of lineage (backward, forward, both)
            max_depth: Maximum depth to visualize
            include_metadata: Whether to include metadata in the visualization
            output_path: Optional path to save the visualization
            format: Output format (png, pdf, html)
            interactive: Whether to create an interactive visualization

        Returns:
            Optional[str]: Path to the output file or HTML string
        """
        # Get lineage data
        if node_id:
            lineage = self.get_lineage(
                node_id=node_id,
                direction=direction,
                max_depth=max_depth,
                include_metadata=include_metadata
            )
            title = f"Lineage for Node: {node_id}"
        elif entity_id:
            lineage = self.get_entity_lineage(
                entity_id=entity_id,
                direction=direction,
                include_related_entities=True,
                max_depth=max_depth
            )
            title = f"Lineage for Entity: {entity_id}"
        else:
            # If neither node nor entity specified, visualize the entire graph
            lineage = {
                "nodes": {
                    node_id: {
                        "node_type": self.node_metadata.get(node_id, {}).get("node_type", "unknown"),
                        "entity_id": self.node_metadata.get(node_id, {}).get("entity_id"),
                        "record_type": self.node_metadata.get(node_id, {}).get("record_type"),
                        "metadata": self.node_metadata.get(node_id, {}) if include_metadata else {}
                    }
                    for node_id in self.graph.nodes()
                },
                "links": [
                    {
                        "source": source,
                        "target": target,
                        "relationship_type": self.relationship_metadata.get((source, target), {}).get("relationship_type", "unknown"),
                        "confidence": self.relationship_metadata.get((source, target), {}).get("confidence", 1.0),
                        "metadata": self.relationship_metadata.get((source, target), {}) if include_metadata else {}
                    }
                    for source, target in self.graph.edges()
                ]
            }
            title = "Complete Lineage Graph"

        # Choose visualization method based on engine
        if self.visualization_engine == "matplotlib" or (
            self.visualization_engine == "plotly" and not PLOTLY_AVAILABLE
        ):
            return self._visualize_with_matplotlib(
                lineage=lineage,
                title=title,
                output_path=output_path,
                format=format
            )
        elif self.visualization_engine == "plotly" and PLOTLY_AVAILABLE:
            return self._visualize_with_plotly(
                lineage=lineage,
                title=title,
                output_path=output_path,
                format=format,
                interactive=interactive
            )
        else:
            logger.warning(f"Unsupported visualization engine: {self.visualization_engine}")
            return None

    def _visualize_with_matplotlib(
        self,
        lineage: Dict[str, Any],
        title: str,
        output_path: Optional[str] = None,
        format: str = "png"
    ) -> Optional[str]:
        """
        Visualize lineage using matplotlib.

        Args:
            lineage: Lineage data to visualize
            title: Title for the visualization
            output_path: Optional path to save the visualization
            format: Output format (png, pdf, svg)

        Returns:
            Optional[str]: Path to the output file
        """
        try:
            # Create a new graph for visualization
            viz_graph = nx.DiGraph()

            # Add nodes to visualization graph
            node_colors = []
            for node_id, node_data in lineage["nodes"].items():
                node_type = node_data.get("node_type", "unknown")
                entity_id = node_data.get("entity_id")
                record_type = node_data.get("record_type")

                # Add node
                viz_graph.add_node(
                    node_id,
                    node_type=node_type,
                    entity_id=entity_id,
                    record_type=record_type
                )

                # Determine node color based on node type
                if node_type == "source":
                    color = "lightblue"
                elif node_type == "transformation":
                    color = "lightgreen"
                elif node_type == "query":
                    color = "lightcoral"
                elif node_type == "merge":
                    color = "orange"
                else:
                    color = "lightgray"

                node_colors.append(color)

            # Add edges to visualization graph
            edge_colors = []
            for link in lineage["links"]:
                source = link.get("source")
                target = link.get("target")
                relationship_type = link.get("relationship_type", "unknown")
                confidence = link.get("confidence", 1.0)

                if source in viz_graph and target in viz_graph:
                    viz_graph.add_edge(
                        source,
                        target,
                        relationship_type=relationship_type,
                        confidence=confidence
                    )

                    # Edge color based on relationship type
                    if relationship_type == "input":
                        color = "blue"
                    elif relationship_type == "output":
                        color = "green"
                    elif relationship_type == "merged_with":
                        color = "orange"
                    else:
                        color = "gray"

                    edge_colors.append(color)

            # Create figure
            plt.figure(figsize=(12, 10))

            # Create layout
            pos = nx.spring_layout(viz_graph, seed=42)

            # Draw nodes
            nx.draw_networkx_nodes(
                viz_graph,
                pos,
                node_color=node_colors,
                node_size=500,
                alpha=0.8
            )

            # Draw edges
            nx.draw_networkx_edges(
                viz_graph,
                pos,
                edge_color=edge_colors,
                width=1.5,
                arrowsize=15,
                alpha=0.7
            )

            # Draw labels
            nx.draw_networkx_labels(
                viz_graph,
                pos,
                font_size=8,
                font_family="sans-serif"
            )

            # Add title
            plt.title(title)

            # Remove axes
            plt.axis("off")

            # Save or show the visualization
            if output_path:
                plt.savefig(output_path, format=format, bbox_inches="tight")
                plt.close()
                return output_path
            else:
                plt.show()
                plt.close()
                return None

        except Exception as e:
            logger.error(f"Error visualizing lineage with matplotlib: {str(e)}")
            return None

    def _visualize_with_plotly(
        self,
        lineage: Dict[str, Any],
        title: str,
        output_path: Optional[str] = None,
        format: str = "png",
        interactive: bool = False
    ) -> Optional[str]:
        """
        Visualize lineage using plotly.

        Args:
            lineage: Lineage data to visualize
            title: Title for the visualization
            output_path: Optional path to save the visualization
            format: Output format (png, pdf, html)
            interactive: Whether to create an interactive visualization

        Returns:
            Optional[str]: Path to the output file or HTML string
        """
        if not PLOTLY_AVAILABLE:
            logger.warning("Plotly is not available for visualization.")
            return None

        try:
            # Create a NetworkX graph for layout calculation
            viz_graph = nx.DiGraph()

            # Add nodes and edges to visualization graph
            for node_id, node_data in lineage["nodes"].items():
                viz_graph.add_node(node_id)

            for link in lineage["links"]:
                source = link.get("source")
                target = link.get("target")
                if source in viz_graph and target in viz_graph:
                    viz_graph.add_edge(source, target)

            # Create layout
            pos = nx.spring_layout(viz_graph, seed=42)

            # Create node traces
            node_traces = {}

            # Group nodes by type
            node_types = set()
            for node_data in lineage["nodes"].values():
                node_types.add(node_data.get("node_type", "unknown"))

            # Create a trace for each node type
            for node_type in node_types:
                node_trace = go.Scatter(
                    x=[],
                    y=[],
                    text=[],
                    mode='markers',
                    hoverinfo='text',
                    name=node_type,
                    marker=dict(
                        size=10,
                        line_width=2
                    )
                )

                # Determine marker color based on node type
                if node_type == "source":
                    node_trace.marker.color = "lightblue"
                elif node_type == "transformation":
                    node_trace.marker.color = "lightgreen"
                elif node_type == "query":
                    node_trace.marker.color = "lightcoral"
                elif node_type == "merge":
                    node_trace.marker.color = "orange"
                else:
                    node_trace.marker.color = "lightgray"

                node_traces[node_type] = node_trace

            # Add nodes to traces
            for node_id, node_data in lineage["nodes"].items():
                node_type = node_data.get("node_type", "unknown")
                x, y = pos[node_id]

                # Get trace for this node type
                node_trace = node_traces[node_type]

                # Add to trace
                node_trace.x = node_trace.x + (x,)
                node_trace.y = node_trace.y + (y,)

                # Create hover text
                hover_text = f"ID: {node_id}<br>Type: {node_type}"
                if node_data.get("entity_id"):
                    hover_text += f"<br>Entity: {node_data['entity_id']}"
                if node_data.get("record_type"):
                    hover_text += f"<br>Record Type: {node_data['record_type']}"

                node_trace.text = node_trace.text + (hover_text,)

            # Create edge trace
            edge_trace = go.Scatter(
                x=[],
                y=[],
                line=dict(width=0.5, color='#888'),
                hoverinfo='none',
                mode='lines'
            )

            # Add edges
            for link in lineage["links"]:
                source = link.get("source")
                target = link.get("target")

                if source in pos and target in pos:
                    x0, y0 = pos[source]
                    x1, y1 = pos[target]

                    edge_trace.x += (x0, x1, None)
                    edge_trace.y += (y0, y1, None)

            # Create figure
            traces = [edge_trace] + list(node_traces.values())

            layout = go.Layout(
                title=title,
                showlegend=True,
                hovermode='closest',
                margin=dict(b=20, l=5, r=5, t=40),
                xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                yaxis=dict(showgrid=False, zeroline=False, showticklabels=False)
            )

            fig = go.Figure(data=traces, layout=layout)

            # Save or return the visualization
            if output_path:
                if format == "html" or interactive:
                    # Save as interactive HTML
                    fig.write_html(output_path)
                else:
                    # Save as static image
                    fig.write_image(output_path, format=format)

                return output_path
            elif interactive:
                # Return HTML string
                return fig.to_html()
            else:
                # Show interactive figure
                fig.show()
                return None

        except Exception as e:
            logger.error(f"Error visualizing lineage with plotly: {str(e)}")
            return None


def generate_sample_lineage_graph() -> CrossDocumentLineageTracker:
    """
    Generate a sample lineage graph for demonstration.

    Returns:
        CrossDocumentLineageTracker: Tracker with sample data
    """
    # Create lineage tracker
    tracker = CrossDocumentLineageTracker()

    # Sample data sources
    sources = [
        ("source1", "Raw customer data", "customer_data"),
        ("source2", "Product catalog", "product_catalog"),
        ("source3", "Sales transactions", "sales_data")
    ]

    # Sample transformations
    transformations = [
        ("transform1", "Data cleaning", "customer_data_clean"),
        ("transform2", "Feature extraction", "customer_features"),
        ("transform3", "Join products with sales", "product_sales"),
        ("transform4", "Merge customer features with product sales", "analysis_data")
    ]

    # Sample query/analysis
    queries = [
        ("query1", "Customer segmentation", "customer_segments"),
        ("query2", "Sales trend analysis", "sales_trends"),
        ("query3", "Product recommendation model", "product_recommendations")
    ]

    # Add source nodes
    for node_id, description, entity_id in sources:
        tracker.add_node(
            node_id=node_id,
            node_type="source",
            entity_id=entity_id,
            record_type="source",
            metadata={
                "description": description,
                "timestamp": time.time() - 86400  # 1 day ago
            }
        )

    # Add transformation nodes
    for node_id, description, entity_id in transformations:
        tracker.add_node(
            node_id=node_id,
            node_type="transformation",
            entity_id=entity_id,
            record_type="transformation",
            metadata={
                "description": description,
                "timestamp": time.time() - 43200  # 12 hours ago
            }
        )

    # Add query nodes
    for node_id, description, entity_id in queries:
        tracker.add_node(
            node_id=node_id,
            node_type="query",
            entity_id=entity_id,
            record_type="query",
            metadata={
                "description": description,
                "timestamp": time.time() - 21600  # 6 hours ago
            }
        )

    # Add relationships
    relationships = [
        # Source to transformation
        ("source1", "transform1", "input", 1.0),
        ("source1", "transform2", "input", 1.0),
        ("source2", "transform3", "input", 1.0),
        ("source3", "transform3", "input", 1.0),

        # Transformation to transformation
        ("transform1", "transform2", "input", 1.0),
        ("transform2", "transform4", "input", 1.0),
        ("transform3", "transform4", "input", 1.0),

        # Transformation to query
        ("transform2", "query1", "input", 1.0),
        ("transform3", "query2", "input", 1.0),
        ("transform4", "query3", "input", 1.0)
    ]

    # Add additional cross-document relationships with lower confidence
    cross_document = [
        ("source1", "source2", "related_to", 0.7),
        ("customer_features", "sales_trends", "influences", 0.8),
        ("product_sales", "customer_segments", "related_to", 0.6)
    ]

    # Add relationships
    for source, target, rel_type, confidence in relationships:
        tracker.add_relationship(
            source_id=source,
            target_id=target,
            relationship_type=rel_type,
            confidence=confidence
        )

    # Add cross-document relationships
    for entity1, entity2, rel_type, confidence in cross_document:
        # Find a node from each entity
        nodes1 = [node_id for node_id, metadata in tracker.node_metadata.items()
                 if metadata.get("entity_id") == entity1]
        nodes2 = [node_id for node_id, metadata in tracker.node_metadata.items()
                 if metadata.get("entity_id") == entity2]

        if nodes1 and nodes2:
            tracker.add_relationship(
                source_id=nodes1[0],
                target_id=nodes2[0],
                relationship_type=rel_type,
                confidence=confidence,
                direction="bidirectional"
            )

    # Update analysis
    tracker._update_analysis()

    return tracker


def example_usage():
    """
    Example usage of the cross-document lineage tracking system.

    This function demonstrates the capabilities of the lineage tracking system
    with a sample dataset.
    """
    print("=== Cross-Document Lineage Tracking Example ===")

    # Create lineage tracker with sample data
    tracker = generate_sample_lineage_graph()

    # Display basic statistics
    print(f"Created sample lineage graph with {len(tracker.graph.nodes())} nodes "
          f"and {len(tracker.graph.edges())} edges.")
    print(f"Entities: {len(tracker.entities)}")
    print(f"Critical paths: {len(tracker.critical_paths)}")
    print(f"Hub nodes: {len(tracker.hub_nodes)}")
    print(f"Cross-document connections: {len(tracker.cross_document_connections)}")

    # Get lineage for a specific node
    node_lineage = tracker.get_lineage(
        node_id="transform4",
        direction="both",
        max_depth=3
    )

    print("\n=== Node Lineage ===")
    print(f"Node: transform4")
    print(f"Nodes in lineage: {len(node_lineage['nodes'])}")
    print(f"Links in lineage: {len(node_lineage['links'])}")
    print(f"Impact score: {node_lineage['metrics']['impact_score']:.2f}")
    print(f"Dependency score: {node_lineage['metrics']['dependency_score']:.2f}")

    # Get entity lineage
    entity_lineage = tracker.get_entity_lineage(
        entity_id="customer_features",
        direction="both"
    )

    print("\n=== Entity Lineage ===")
    print(f"Entity: customer_features")
    print(f"Nodes in lineage: {len(entity_lineage['nodes'])}")
    print(f"Links in lineage: {len(entity_lineage['links'])}")
    print(f"Related entities: {len(entity_lineage['entities']) - 1}")
    print(f"Entity impact score: {entity_lineage['metrics']['impact_score']:.2f}")
    print(f"Entity centrality: {entity_lineage['metrics']['centrality']:.2f}")

    # Analyze cross-document lineage
    analysis = tracker.analyze_cross_document_lineage()

    print("\n=== Cross-Document Analysis ===")
    print(f"Entity count: {analysis['entity_count']}")
    print(f"Cross-document connections: {analysis['cross_document_connections_count']}")
    print(f"Document pairs: {analysis['document_pair_count']}")
    print(f"Graph density: {analysis['graph_density']:.2f}")

    # Visualize lineage
    print("\n=== Visualization ===")
    viz_path = tracker.visualize_lineage(
        entity_id="analysis_data",
        direction="both",
        max_depth=3,
        output_path="analysis_data_lineage.png"
    )

    if viz_path:
        print(f"Visualization saved to: {viz_path}")

    # Export lineage graph
    print("\n=== Export ===")
    export_data = tracker.export_lineage_graph(output_format="json")

    print(f"Exported lineage graph with {len(export_data['nodes'])} nodes "
          f"and {len(export_data['links'])} links.")

    # Integration with provenance manager
    if BASE_PROVENANCE_AVAILABLE or ENHANCED_PROVENANCE_AVAILABLE:
        print("\n=== Provenance Integration ===")

        # Check if provenance manager is available
        if BASE_PROVENANCE_AVAILABLE:
            print("Base provenance module is available.")

            try:
                # Create provenance manager
                from ipfs_datasets_py.data_provenance import ProvenanceManager
                provenance_manager = ProvenanceManager()

                # Create lineage tracker with provenance manager
                lineage_tracker = CrossDocumentLineageTracker(
                    provenance_manager=provenance_manager
                )

                # Import from provenance manager
                imported = lineage_tracker.import_from_provenance_manager()

                print(f"Imported {imported} nodes from provenance manager.")

            except Exception as e:
                print(f"Error creating provenance manager: {str(e)}")

        if ENHANCED_PROVENANCE_AVAILABLE:
            print("Enhanced provenance module is available.")

            try:
                # Create enhanced provenance manager
                from ipfs_datasets_py.data_provenance_enhanced import EnhancedProvenanceManager
                enhanced_manager = EnhancedProvenanceManager()

                # Create lineage tracker with enhanced provenance manager
                enhanced_tracker = CrossDocumentLineageTracker(
                    provenance_manager=enhanced_manager
                )

                # Import from provenance manager
                imported = enhanced_tracker.import_from_provenance_manager()

                print(f"Imported {imported} nodes from enhanced provenance manager.")

            except Exception as e:
                print(f"Error creating enhanced provenance manager: {str(e)}")

    print("\n=== Example Complete ===")
    return tracker


if __name__ == "__main__":
    example_usage()
