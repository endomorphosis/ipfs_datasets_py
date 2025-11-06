# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/cross_document_lineage.py'

Files last updated: 1751751551.0797882

Stub file last updated: 2025-07-07 02:11:01

## CrossDocumentLineageTracker

```python
class CrossDocumentLineageTracker:
    """
    Tracks lineage across multiple documents and datasets with detailed metadata.

This class provides comprehensive capabilities for tracking, analyzing,
and visualizing data lineage across multiple documents and transformations.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## EnhancedLineageTracker

```python
class EnhancedLineageTracker:
    """
    Enhanced lineage tracking for comprehensive data provenance.

This class provides advanced functionality for tracking data lineage
across document, domain, and system boundaries, enabling comprehensive
understanding of data flows and transformations with fine-grained
metadata and hierarchical relationships.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## LineageBoundary

```python
@dataclass
class LineageBoundary:
    """
    Represents a boundary between domains in the lineage graph.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## LineageDomain

```python
@dataclass
class LineageDomain:
    """
    Represents a logical domain in the data lineage graph.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## LineageLink

```python
@dataclass
class LineageLink:
    """
    Represents a link in the data lineage graph.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## LineageMetrics

```python
class LineageMetrics:
    """
    Calculate metrics for data lineage analysis.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## LineageNode

```python
@dataclass
class LineageNode:
    """
    Represents a node in the data lineage graph.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## LineageSubgraph

```python
@dataclass
class LineageSubgraph:
    """
    Represents a subgraph in the data lineage graph.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## LineageTransformationDetail

```python
@dataclass
class LineageTransformationDetail:
    """
    Detailed representation of a transformation operation in lineage tracking.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## LineageVersion

```python
@dataclass
class LineageVersion:
    """
    Represents a version of a node in the lineage graph.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, provenance_manager = None, storage = None, config = None):
    """
    Initialize the enhanced lineage tracker.

Args:
    provenance_manager: Optional provenance manager to use
    storage: Optional storage backend for lineage data
    config: Optional configuration dictionary
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedLineageTracker

## __init__

```python
def __init__(self, provenance_manager: Optional[Any] = None, storage_path: Optional[str] = None, visualization_engine: str = "matplotlib"):
    """
    Initialize the cross-document lineage tracker.

Args:
    provenance_manager: Optional provenance manager instance
    storage_path: Path to store lineage data
    visualization_engine: Engine to use for visualizations
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentLineageTracker

## _calculate_max_path_length

```python
def _calculate_max_path_length(self, lineage: LineageSubgraph) -> int:
    """
    Calculate the maximum path length in a lineage subgraph.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedLineageTracker

## _check_temporal_consistency

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedLineageTracker

## _count_node_types

```python
def _count_node_types(self, lineage: LineageSubgraph) -> Dict[str, int]:
    """
    Count occurrences of each node type in a lineage subgraph.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedLineageTracker

## _get_ancestors

```python
def _get_ancestors(self, node_id: str, max_depth: int) -> Dict[str, List[str]]:
    """
    Get the ancestors of a node up to a specified depth.

Args:
    node_id: Node ID to get ancestors for
    max_depth: Maximum depth to traverse

Returns:
    Dict[str, List[str]]: Map of node IDs to their children
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentLineageTracker

## _get_descendants

```python
def _get_descendants(self, node_id: str, max_depth: int) -> Dict[str, List[str]]:
    """
    Get the descendants of a node up to a specified depth.

Args:
    node_id: Node ID to get descendants for
    max_depth: Maximum depth to traverse

Returns:
    Dict[str, List[str]]: Map of node IDs to their children
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentLineageTracker

## _link_to_audit_trail

```python
def _link_to_audit_trail(self, source_id: str, target_id: str, relationship_type: str):
    """
    Create bidirectional links to audit trail events.

Args:
    source_id: Source node ID
    target_id: Target node ID
    relationship_type: Type of relationship
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedLineageTracker

## _update_analysis

```python
def _update_analysis(self):
    """
    Update critical paths, hub nodes, and other analysis results.
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentLineageTracker

## _visualize_interactive

```python
def _visualize_interactive(self, subgraph: Optional[LineageSubgraph] = None, output_path: Optional[str] = None, include_domains: bool = True) -> Any:
    """
    Create an interactive visualization using Plotly.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedLineageTracker

## _visualize_static

```python
def _visualize_static(self, subgraph: Optional[LineageSubgraph] = None, output_path: Optional[str] = None, include_domains: bool = True) -> Any:
    """
    Create a static visualization using matplotlib.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedLineageTracker

## _visualize_with_matplotlib

```python
def _visualize_with_matplotlib(self, lineage: Dict[str, Any], title: str, output_path: Optional[str] = None, format: str = "png") -> Optional[str]:
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
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentLineageTracker

## _visualize_with_plotly

```python
def _visualize_with_plotly(self, lineage: Dict[str, Any], title: str, output_path: Optional[str] = None, format: str = "png", interactive: bool = False) -> Optional[str]:
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
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentLineageTracker

## add_metadata_inheritance_rule

```python
def add_metadata_inheritance_rule(self, source_type: str, target_type: str, properties: List[str], condition: Optional[Callable] = None, override: bool = False) -> None:
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
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedLineageTracker

## add_node

```python
def add_node(self, node_id: str, node_type: str, entity_id: Optional[str] = None, record_type: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> str:
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
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentLineageTracker

## add_relationship

```python
def add_relationship(self, source_id: str, target_id: str, relationship_type: str, confidence: float = 1.0, metadata: Optional[Dict[str, Any]] = None, direction: str = "forward") -> bool:
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
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentLineageTracker

## analyze_cross_document_lineage

```python
def analyze_cross_document_lineage(self) -> Dict[str, Any]:
    """
    Analyze cross-document lineage in the graph.

This method identifies and analyzes connections between different
entities/documents in the lineage graph.

Returns:
    Dict[str, Any]: Analysis results
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentLineageTracker

## apply_metadata_inheritance

```python
def apply_metadata_inheritance(self) -> int:
    """
    Apply all metadata inheritance rules to the lineage graph.

This propagates metadata according to the defined rules.

Returns:
    int: Number of metadata values propagated
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedLineageTracker

## calculate_centrality

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** LineageMetrics

## calculate_complexity

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** LineageMetrics

## calculate_dependency_score

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** LineageMetrics

## calculate_impact_score

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** LineageMetrics

## create_domain

```python
def create_domain(self, name: str, description: Optional[str] = None, domain_type: str = "generic", attributes: Optional[Dict[str, Any]] = None, metadata_schema: Optional[Dict[str, Any]] = None, parent_domain_id: Optional[str] = None) -> str:
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
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedLineageTracker

## create_domain_boundary

```python
def create_domain_boundary(self, source_domain_id: str, target_domain_id: str, boundary_type: str, attributes: Optional[Dict[str, Any]] = None, constraints: Optional[List[Dict[str, Any]]] = None) -> str:
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
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedLineageTracker

## create_link

```python
def create_link(self, source_id: str, target_id: str, relationship_type: str, metadata: Optional[Dict[str, Any]] = None, confidence: float = 1.0, direction: str = "forward", cross_domain: bool = False) -> str:
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
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedLineageTracker

## create_node

```python
def create_node(self, node_type: str, metadata: Optional[Dict[str, Any]] = None, domain_id: Optional[str] = None, entity_id: Optional[str] = None) -> str:
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
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedLineageTracker

## create_version

```python
def create_version(self, node_id: str, version_number: str, change_description: Optional[str] = None, parent_version_id: Optional[str] = None, creator_id: Optional[str] = None, attributes: Optional[Dict[str, Any]] = None) -> str:
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
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedLineageTracker

## detect_semantic_relationships

```python
def detect_semantic_relationships(self, confidence_threshold: float = 0.7, max_candidates: int = 100) -> List[Dict[str, Any]]:
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
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedLineageTracker

## example_usage

```python
def example_usage():
    """
    Example usage of the cross-document lineage tracking system.

This function demonstrates the capabilities of the lineage tracking system
with a sample dataset.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## export_lineage_graph

```python
def export_lineage_graph(self, output_format: str = "json") -> Union[Dict[str, Any], str]:
    """
    Export the lineage graph in various formats.

Args:
    output_format: Format to export the graph in (json, networkx, gexf)

Returns:
    Union[Dict[str, Any], str]: Exported graph data
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentLineageTracker

## export_to_ipld

```python
def export_to_ipld(self, include_domains: bool = True, include_versions: bool = False, include_transformation_details: bool = False) -> Optional[str]:
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
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedLineageTracker

## extract_features

```python
def extract_features(node_id):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## extract_subgraph

```python
def extract_subgraph(self, root_id: str, max_depth: int = 3, direction: str = "both", include_domains: bool = True, include_versions: bool = False, include_transformation_details: bool = False, relationship_types: Optional[List[str]] = None, domain_filter: Optional[List[str]] = None) -> LineageSubgraph:
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
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedLineageTracker

## find_paths

```python
def find_paths(self, start_node_id: str, end_node_id: str, max_depth: int = 10, relationship_filter: Optional[List[str]] = None) -> List[List[str]]:
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
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedLineageTracker

## from_ipld

```python
@classmethod
def from_ipld(cls, root_cid: str, ipld_storage = None, config: Optional[Dict[str, Any]] = None) -> Optional['EnhancedLineageTracker']:
    """
    Create an EnhancedLineageTracker instance from an IPLD-stored lineage graph.

Args:
    root_cid: The root CID of the IPLD-stored lineage graph
    ipld_storage: Optional IPLD storage instance to use
    config: Optional configuration for the new tracker

Returns:
    Optional[EnhancedLineageTracker]: New tracker instance or None if import fails
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedLineageTracker

## generate_provenance_report

```python
def generate_provenance_report(self, entity_id: Optional[str] = None, node_id: Optional[str] = None, include_visualization: bool = True, format: str = "json") -> Dict[str, Any]:
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
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedLineageTracker

## generate_sample_lineage_graph

```python
def generate_sample_lineage_graph() -> CrossDocumentLineageTracker:
    """
    Generate a sample lineage graph for demonstration.

Returns:
    CrossDocumentLineageTracker: Tracker with sample data
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## get_entity_lineage

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedLineageTracker

## get_entity_lineage

```python
def get_entity_lineage(self, entity_id: str, direction: str = "both", include_related_entities: bool = True, max_depth: int = 3) -> Dict[str, Any]:
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
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentLineageTracker

## get_lineage

```python
def get_lineage(self, node_id: str, direction: str = "backward", max_depth: int = 5, include_metadata: bool = True) -> Dict[str, Any]:
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
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentLineageTracker

## identify_critical_paths

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** LineageMetrics

## import_from_provenance_manager

```python
def import_from_provenance_manager(self, include_types: Optional[List[str]] = None, max_records: int = 1000, confidence_threshold: float = 0.7) -> int:
    """
    Import lineage data from a provenance manager.

Args:
    include_types: Optional list of record types to include
    max_records: Maximum number of records to import
    confidence_threshold: Minimum confidence for inferred relationships

Returns:
    int: Number of nodes imported
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentLineageTracker

## import_lineage_graph

```python
def import_lineage_graph(self, data: Dict[str, Any]) -> bool:
    """
    Import a lineage graph from exported data.

Args:
    data: Exported graph data

Returns:
    bool: Whether the import was successful
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentLineageTracker

## merge_lineage

```python
def merge_lineage(self, other_tracker: "EnhancedLineageTracker", conflict_resolution: str = "newer", allow_domain_merging: bool = True) -> Dict[str, int]:
    """
    Merge another lineage tracker into this one.

Args:
    other_tracker: The other EnhancedLineageTracker to merge from
    conflict_resolution: How to resolve conflicts ('newer', 'keep', 'replace')
    allow_domain_merging: Whether to merge domains and boundaries

Returns:
    Dict[str, int]: Statistics about the merge operation
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedLineageTracker

## query_lineage

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedLineageTracker

## record_transformation_details

```python
def record_transformation_details(self, transformation_id: str, operation_type: str, inputs: List[Dict[str, Any]], outputs: List[Dict[str, Any]], parameters: Optional[Dict[str, Any]] = None, impact_level: str = "field", confidence: float = 1.0) -> str:
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
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedLineageTracker

## resolve_link

```python
def resolve_link(link_obj):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert to dictionary representation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LineageLink

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert to dictionary representation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LineageNode

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert to dictionary representation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LineageDomain

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert to dictionary representation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LineageBoundary

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert to dictionary representation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LineageTransformationDetail

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert to dictionary representation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LineageVersion

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert to dictionary representation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LineageSubgraph

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert to dictionary representation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedLineageTracker

## validate_temporal_consistency

```python
def validate_temporal_consistency(self) -> List[Dict[str, Any]]:
    """
    Validate temporal consistency across the entire lineage graph.

This ensures that all relationships follow a logical temporal order,
where data flows from earlier nodes to later nodes.

Returns:
    List[Dict[str, Any]]: List of inconsistencies found
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedLineageTracker

## visualize_lineage

```python
def visualize_lineage(self, subgraph: Optional[LineageSubgraph] = None, output_path: Optional[str] = None, visualization_type: str = "interactive", include_domains: bool = True) -> Any:
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
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedLineageTracker

## visualize_lineage

```python
def visualize_lineage(self, node_id: Optional[str] = None, entity_id: Optional[str] = None, direction: str = "both", max_depth: int = 3, include_metadata: bool = False, output_path: Optional[str] = None, format: str = "png", interactive: bool = False) -> Optional[str]:
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
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentLineageTracker
