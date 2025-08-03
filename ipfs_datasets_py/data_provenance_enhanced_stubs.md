# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/data_provenance_enhanced.py'

Files last updated: 1748635923.4213796

Stub file last updated: 2025-07-07 02:11:01

## AnnotationRecord

```python
@dataclass
class AnnotationRecord(ProvenanceRecord):
    """
    Record for manual annotation or note.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## DAGLink

```python
class DAGLink:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## DAGNode

```python
class DAGNode:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## EnhancedProvenanceManager

```python
class EnhancedProvenanceManager(BaseProvenanceManager):
    """
    Enhanced provenance manager with advanced features for detailed lineage tracking.

This class extends the base ProvenanceManager with additional capabilities:
- Interactive visualization with multiple formats and layouts
- Advanced reporting with custom templates
- Integration with audit logging system
- Enhanced IPLD storage with cryptographic verification
- Time-based analysis and temporal queries
- Semantic search for provenance records
- Cryptographic verification of provenance records
- IPLD-based content-addressable storage with advanced traversal
- Incremental loading of partial provenance graphs
- Graph partitioning for efficient storage and retrieval
- DAG-PB integration for optimized linked data
- CAR file import/export support with selective loading
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## EnhancedProvenanceRecordType

```python
class EnhancedProvenanceRecordType(Enum):
    """
    Additional record types for enhanced provenance tracking.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## IPLDProvenanceStorage

```python
class IPLDProvenanceStorage:
    """
    Enhanced IPLD-based storage for provenance data with advanced traversal capabilities.

This class provides specialized storage, retrieval, and traversal functionality
for provenance data using IPLD as the underlying storage layer. It supports
incremental loading, efficient batch operations, and integration with DAG-PB.

Features:
- Content-addressable storage and retrieval of provenance records
- Advanced graph traversal using IPLD links
- Incremental loading of partial provenance graphs
- Batch operations for efficient processing
- Integration with DAG-PB for efficient storage
- IPLD-based cryptographic verification of linked data integrity
- Graph partitioning for working with large provenance graphs
- Time-based and entity-based slicing of provenance
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ModelInferenceRecord

```python
@dataclass
class ModelInferenceRecord(ProvenanceRecord):
    """
    Record for model inference event.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ModelTrainingRecord

```python
@dataclass
class ModelTrainingRecord(ProvenanceRecord):
    """
    Record for model training event.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ProvenanceCryptoVerifier

```python
class ProvenanceCryptoVerifier:
    """
    Cryptographic verification and signing for provenance records.

This class provides mechanisms to cryptographically sign and verify
provenance records, ensuring their integrity and authenticity.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ProvenanceIPLDSchema

```python
class ProvenanceIPLDSchema:
    """
    Defines IPLD schemas for provenance records and related structures.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ProvenanceMetrics

```python
class ProvenanceMetrics:
    """
    Calculates metrics for provenance graphs.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## VerificationRecord

```python
@dataclass
class VerificationRecord(ProvenanceRecord):
    """
    Record for data verification/validation.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, data = None, links = None):
```
* **Async:** False
* **Method:** True
* **Class:** DAGNode

## __init__

```python
def __init__(self, name = "", cid = None, size = 0):
```
* **Async:** False
* **Method:** True
* **Class:** DAGLink

## __init__

```python
def __init__(self, secret_key: Optional[str] = None):
    """
    Initialize the crypto verifier.

Args:
    secret_key: Secret key for signing (generated if not provided)
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceCryptoVerifier

## __init__

```python
def __init__(self, ipld_storage: Optional[IPLDStorage] = None, base_dir: Optional[str] = None, ipfs_api: str = "/ip4/127.0.0.1/tcp/5001", enable_dagpb: bool = True, batch_size: int = 100, enable_partitioning: bool = True, partition_size_limit: int = 1000, crypto_verifier: Optional['ProvenanceCryptoVerifier'] = None):
    """
    Initialize the IPLD provenance storage.

Args:
    ipld_storage: Optional IPLDStorage instance to use
    base_dir: Base directory for local storage
    ipfs_api: IPFS API endpoint
    enable_dagpb: Use DAG-PB for storage when available
    batch_size: Default batch size for operations
    enable_partitioning: Enable graph partitioning for large graphs
    partition_size_limit: Maximum records per partition
    crypto_verifier: Cryptographic verifier for record integrity
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDProvenanceStorage

## __init__

```python
def __init__(self, storage_path: Optional[str] = None, enable_ipld_storage: bool = False, default_agent_id: Optional[str] = None, tracking_level: str = "detailed", audit_logger: Optional[Any] = None, visualization_engine: str = "matplotlib", enable_crypto_verification: bool = False, crypto_secret_key: Optional[str] = None, ipfs_api: str = "/ip4/127.0.0.1/tcp/5001"):
    """
    Initialize the enhanced provenance manager.

Args:
    storage_path: Path to store provenance data, None for in-memory only
    enable_ipld_storage: Whether to use IPLD for provenance storage
    default_agent_id: Default agent ID for provenance records
    tracking_level: Level of detail for provenance tracking
    audit_logger: AuditLogger instance for audit integration
    visualization_engine: Engine to use for visualizations
    enable_crypto_verification: Whether to enable cryptographic verification
    crypto_secret_key: Secret key for crypto verification (generated if not provided)
    ipfs_api: IPFS API endpoint for IPLD storage
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## _add_lineage_graph_metrics

```python
def _add_lineage_graph_metrics(self, graph: nx.DiGraph) -> None:
    """
    Add computed metrics to a lineage graph for analysis.

Args:
    graph: The cross-document lineage graph to analyze
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDProvenanceStorage

## _assign_depth_to_nodes

```python
def _assign_depth_to_nodes(self, graph: nx.DiGraph) -> None:
    """
    Assign a depth attribute to each node in the graph based on topological order.

This ensures that the multipartite_layout function works correctly by providing
each node with a required 'depth' attribute.

Args:
    graph: The directed graph to process
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## _audit_log_record

```python
def _audit_log_record(self, record: ProvenanceRecord, operation_type: str) -> None:
    """
    Log a provenance record to the audit system if available.

Args:
    record: The provenance record to log
    operation_type: Type of operation for categorization
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## _calculate_max_depth

```python
def _calculate_max_depth(self, graph: nx.DiGraph, target_node: str) -> int:
    """
    Calculate the maximum depth from any source node to the target.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## _create_dagnode_for_record

```python
def _create_dagnode_for_record(self, record: "ProvenanceRecord", record_dict: dict) -> DAGNode:
    """
    Create a DAG-PB node for a provenance record.

Args:
    record: The provenance record
    record_dict: Dictionary representation of the record

Returns:
    DAGNode: DAG-PB node for the record
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDProvenanceStorage

## _create_interactive_lineage_visualization

```python
def _create_interactive_lineage_visualization(self, lineage_graph: nx.DiGraph, start_record_id: str, output_file: Optional[str] = None, highlight_path: bool = True) -> nx.DiGraph:
    """
    Create an interactive visualization of the lineage graph using Plotly.

Args:
    lineage_graph: The lineage graph to visualize
    start_record_id: ID of the starting record
    output_file: Path to save the visualization
    highlight_path: Whether to highlight critical paths

Returns:
    nx.DiGraph: The lineage graph
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## _create_static_lineage_visualization

```python
def _create_static_lineage_visualization(self, lineage_graph: nx.DiGraph, start_record_id: str, output_file: Optional[str] = None, layout: str = "dot", highlight_path: bool = True) -> nx.DiGraph:
    """
    Create a static visualization of the lineage graph using matplotlib.

Args:
    lineage_graph: The lineage graph to visualize
    start_record_id: ID of the starting record
    output_file: Path to save the visualization
    layout: Graph layout algorithm
    highlight_path: Whether to highlight critical paths

Returns:
    nx.DiGraph: The lineage graph
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## _create_visualization_subgraph

```python
def _create_visualization_subgraph(self, data_ids: Optional[List[str]], max_depth: int) -> nx.DiGraph:
    """
    Create a subgraph for visualization based on specified data IDs.

Args:
    data_ids: List of data entity IDs to visualize, None for all
    max_depth: Maximum depth to trace back

Returns:
    nx.DiGraph: Subgraph for visualization
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## _dict_to_record

```python
def _dict_to_record(self, record_dict: dict, record_class = None) -> "ProvenanceRecord":
    """
    Convert a dictionary to a provenance record.

Args:
    record_dict: Dictionary representation of record
    record_class: Optional class to use for instantiation

Returns:
    ProvenanceRecord: The constructed record
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDProvenanceStorage

## _filter_graph_by_criteria

```python
def _filter_graph_by_criteria(self, criteria: Dict) -> nx.DiGraph:
    """
    Filter the in-memory graph based on criteria.

Args:
    criteria: Filtering criteria

Returns:
    nx.DiGraph: Filtered graph
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## _get_schema_name_for_record

```python
def _get_schema_name_for_record(self, record: "ProvenanceRecord") -> str:
    """
    Get the schema name for a given record type.

Args:
    record: Provenance record

Returns:
    str: Schema name
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDProvenanceStorage

## _index_for_semantic_search

```python
def _index_for_semantic_search(self, record: ProvenanceRecord) -> None:
    """
    Index a record for semantic search.

Args:
    record: The provenance record to index
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## _index_for_temporal_queries

```python
def _index_for_temporal_queries(self, record: ProvenanceRecord) -> None:
    """
    Index a record for temporal queries.

Args:
    record: The provenance record to index
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## _partition_graph

```python
def _partition_graph(self, graph: nx.DiGraph) -> Dict[str, nx.DiGraph]:
    """
    Partition a large provenance graph into manageable subgraphs.

Args:
    graph: NetworkX directed graph

Returns:
    Dict[str, nx.DiGraph]: Mapping from partition ID to subgraph
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDProvenanceStorage

## _process_imported_graph

```python
def _process_imported_graph(self, graph_data: Dict) -> None:
    """
    Process an imported graph structure from IPLD.

Args:
    graph_data: Graph data from IPLD storage
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## _process_imported_partition_index

```python
def _process_imported_partition_index(self, partition_index: Dict) -> None:
    """
    Process an imported partition index from IPLD.

Args:
    partition_index: Partition index data
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## _provenance_ipld_example

```python
def _provenance_ipld_example():
    """
    Example demonstrating the enhanced data provenance tracking with IPLD integration.

This function shows how to:
1. Create a provenance manager with enhanced IPLD storage
2. Record provenance for data processing operations
3. Use advanced graph traversal for lineage tracking
4. Export/import provenance with CAR files
5. Perform efficient incremental loading of large provenance graphs
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _rebuild_indices

```python
def _rebuild_indices(self) -> None:
    """
    Rebuild all indices after importing records.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## _record_to_dict

```python
def _record_to_dict(self, record: "ProvenanceRecord") -> dict:
    """
    Convert a provenance record to a dictionary.

Args:
    record: Provenance record

Returns:
    dict: Dictionary representation of the record
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDProvenanceStorage

## _register_ipld_schemas

```python
def _register_ipld_schemas(self) -> None:
    """
    Register provenance record schemas with IPLD storage.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## _register_schemas

```python
def _register_schemas(self):
    """
    Register all provenance schemas with IPLD storage.
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDProvenanceStorage

## _store_partitioned_graph

```python
def _store_partitioned_graph(self, graph: nx.DiGraph) -> str:
    """
    Store a provenance graph as multiple partitions in IPLD.

Args:
    graph: NetworkX directed graph

Returns:
    str: CID of the root partition index
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDProvenanceStorage

## _store_record_in_ipld

```python
def _store_record_in_ipld(self, record: ProvenanceRecord) -> Optional[str]:
    """
    Store a provenance record in IPLD.

Args:
    record: The provenance record to store

Returns:
    Optional[str]: CID of the stored record, or None if storage failed
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## _store_single_graph

```python
def _store_single_graph(self, graph: nx.DiGraph) -> str:
    """
    Store a provenance graph as a single IPLD structure.

Args:
    graph: NetworkX directed graph

Returns:
    str: CID of the graph
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDProvenanceStorage

## _update_ipld_graph

```python
def _update_ipld_graph(self) -> Optional[str]:
    """
    Update the IPLD representation of the full provenance graph.

Returns:
    Optional[str]: CID of the graph root, or None if update failed
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## _visualize_with_dash

```python
def _visualize_with_dash(self, subgraph: nx.DiGraph, include_parameters: bool, show_timestamps: bool, layout: str, highlight_critical_path: bool, include_metrics: bool, file_path: Optional[str], width: int, height: int, custom_colors: Optional[Dict[str, str]]) -> Optional[str]:
    """
    Visualize provenance graph using Dash with Cytoscape.

Args:
    subgraph: Subgraph to visualize
    include_parameters: Whether to include operation parameters
    show_timestamps: Whether to show timestamps
    layout: Layout algorithm to use
    highlight_critical_path: Whether to highlight the critical path
    include_metrics: Whether to include metrics in the visualization
    file_path: Path to save the visualization
    width: Width of the visualization
    height: Height of the visualization
    custom_colors: Custom colors for node types

Returns:
    Optional[str]: HTML string if successful
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## _visualize_with_matplotlib

```python
def _visualize_with_matplotlib(self, subgraph: nx.DiGraph, include_parameters: bool, show_timestamps: bool, layout: str, highlight_critical_path: bool, include_metrics: bool, file_path: Optional[str], format: str, return_base64: bool, width: int, height: int, custom_colors: Optional[Dict[str, str]]) -> Optional[str]:
    """
    Visualize provenance graph using matplotlib.

Args:
    subgraph: Subgraph to visualize
    include_parameters: Whether to include operation parameters
    show_timestamps: Whether to show timestamps
    layout: Layout algorithm to use
    highlight_critical_path: Whether to highlight the critical path
    include_metrics: Whether to include metrics in the visualization
    file_path: Path to save the visualization
    format: Output format
    return_base64: Whether to return the image as base64
    width: Width of the visualization
    height: Height of the visualization
    custom_colors: Custom colors for node types

Returns:
    Optional[str]: Base64-encoded image if return_base64 is True
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## _visualize_with_plotly

```python
def _visualize_with_plotly(self, subgraph: nx.DiGraph, include_parameters: bool, show_timestamps: bool, layout: str, highlight_critical_path: bool, include_metrics: bool, file_path: Optional[str], format: str, width: int, height: int, custom_colors: Optional[Dict[str, str]]) -> Optional[Union[str, Dict[str, Any]]]:
    """
    Visualize provenance graph using plotly.

Args:
    subgraph: Subgraph to visualize
    include_parameters: Whether to include operation parameters
    show_timestamps: Whether to show timestamps
    layout: Layout algorithm to use
    highlight_critical_path: Whether to highlight the critical path
    include_metrics: Whether to include metrics in the visualization
    file_path: Path to save the visualization
    format: Output format
    width: Width of the visualization
    height: Height of the visualization
    custom_colors: Custom colors for node types

Returns:
    Optional[Union[str, Dict[str, Any]]]: HTML string or JSON dict if format is "html" or "json"
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## add_record

```python
def add_record(self, record: ProvenanceRecord) -> str:
    """
    Add a provenance record directly to the manager.

This is a utility method for incorporating externally created records.

Args:
    record: The provenance record to add

Returns:
    str: ID of the added record
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## analyze_cross_document_lineage

```python
def analyze_cross_document_lineage(self, lineage_graph: Optional[nx.DiGraph] = None, record_ids: Optional[List[str]] = None, max_depth: int = 3) -> Dict[str, Any]:
    """
    Analyze cross-document lineage to identify key patterns and insights.

This method performs in-depth analysis of cross-document lineage relationships,
calculating various metrics and identifying important patterns. The analysis
includes identification of critical paths, hub records, and cross-document
clusters, as well as metrics on cross-document coverage and connectivity.

Args:
    lineage_graph: Optional pre-built lineage graph (built if not provided)
    record_ids: List of record IDs to include if building a new graph
    max_depth: Maximum traversal depth for cross-document relationships

Returns:
    Dict[str, Any]: Analysis results with metrics and insights
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDProvenanceStorage

## analyze_cross_document_lineage

```python
def analyze_cross_document_lineage(self, lineage_graph: Optional[nx.DiGraph] = None, record_ids: Optional[Union[str, List[str]]] = None, max_depth: int = 3, link_types: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Analyze cross-document lineage for records and their relationships.

This method builds a lineage graph and computes comprehensive metrics
and statistics about cross-document relationships, document boundaries,
and critical paths through the provenance graph.

Args:
    lineage_graph: Optional pre-built lineage graph to analyze
    record_ids: ID or list of record IDs to analyze (if graph not provided)
    max_depth: Maximum traversal depth
    link_types: Optional filter for specific link types to include

Returns:
    Dict[str, Any]: Comprehensive analysis results including metrics,
                    statistics, and document-level insights
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## build_cross_document_lineage_graph

```python
def build_cross_document_lineage_graph(self, record_ids: Union[str, List[str]], max_depth: int = 3, link_types: Optional[List[str]] = None) -> nx.DiGraph:
    """
    Build a comprehensive cross-document lineage graph for a set of records.

This method constructs a directed graph representing the lineage relationships
across multiple documents or datasets, enabling detailed cross-document
provenance analysis. The graph includes nodes from multiple partitions or
provenance graphs that are linked through cross-document relationships.

Enhanced version with improved document boundary tracking, relationship analysis,
and metadata enrichment for better cross-document lineage understanding.

Args:
    record_ids: Single record ID or list of record IDs to start the lineage graph from
    max_depth: Maximum traversal depth for cross-document relationships
    link_types: Optional filter for specific types of links to include

Returns:
    nx.DiGraph: A directed graph representing cross-document lineage with enhanced metadata
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDProvenanceStorage

## build_cross_document_lineage_graph

```python
def build_cross_document_lineage_graph(self, start_record_id: str, max_depth: int = 5) -> nx.DiGraph:
    """
    Build a comprehensive lineage graph by traversing cross-document links.

This method starts from a given record and traverses all cross-document
links in both directions (incoming and outgoing) to build a complete
lineage graph that spans multiple documents/datasets.

Args:
    start_record_id: ID of the record to start traversal from
    max_depth: Maximum traversal depth to prevent infinite loops

Returns:
    nx.DiGraph: Directed graph representing the cross-document lineage
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## bulk_sign_records

```python
def bulk_sign_records(self, records: List['ProvenanceRecord']) -> Dict[str, str]:
    """
    Sign multiple records efficiently.

Args:
    records: List of provenance records to sign

Returns:
    Dict[str, str]: Map from record ID to signature
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceCryptoVerifier

## calculate_centrality

```python
@staticmethod
def calculate_centrality(graph: nx.DiGraph, node_type: Optional[str] = None) -> Dict[str, float]:
    """
    Calculate centrality measures for nodes in the provenance graph.

Args:
    graph: The provenance graph
    node_type: Optional filter by node type

Returns:
    Dict[str, float]: Node IDs to centrality score
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceMetrics

## calculate_complexity

```python
@staticmethod
def calculate_complexity(graph: nx.DiGraph, data_id: str) -> Dict[str, float]:
    """
    Calculate complexity metrics for a data entity's provenance.

Args:
    graph: The provenance graph
    data_id: ID of the data entity

Returns:
    Dict[str, float]: Dictionary of complexity metrics
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceMetrics

## calculate_data_impact

```python
@staticmethod
def calculate_data_impact(graph: nx.DiGraph, node_id: str) -> float:
    """
    Calculate the impact factor of a data node by counting downstream nodes.

Args:
    graph: The provenance graph
    node_id: ID of the node to analyze

Returns:
    float: Impact factor score
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceMetrics

## calculate_data_metrics

```python
def calculate_data_metrics(self, data_id: str) -> Dict[str, Any]:
    """
    Calculate comprehensive metrics for a data entity's provenance.

Args:
    data_id: ID of the data entity

Returns:
    Dict[str, Any]: Dictionary of metrics
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## create_cross_document_lineage

```python
def create_cross_document_lineage(self, output_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Creates detailed lineage tracking with cross-document relationships.

This method integrates the current provenance graph with cross-document
lineage tracking, enabling more detailed analysis of data flows between
different documents and systems.

Args:
    output_path: Optional path to export the lineage graph visualization

Returns:
    Optional[Dict[str, Any]]: Detailed lineage data or None if generation failed
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## create_cross_document_lineage

```python
def create_cross_document_lineage(self, output_path: Optional[str] = None, include_visualization: bool = True) -> Optional[Dict[str, Any]]:
    """
    Creates detailed lineage tracking with cross-document relationships.

This method integrates the current provenance graph with cross-document
lineage tracking, enabling more detailed analysis of data flows between
different documents and systems.

Args:
    output_path: Optional path to export the lineage graph visualization and report
    include_visualization: Whether to include visualization in the output

Returns:
    Optional[Dict[str, Any]]: Detailed lineage data or None if generation failed
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## export_cross_document_lineage

```python
def export_cross_document_lineage(self, lineage_graph: Optional[nx.DiGraph] = None, record_ids: Optional[List[str]] = None, max_depth: int = 3, format: str = "json", file_path: Optional[str] = None, include_records: bool = False) -> Optional[Union[str, Dict[str, Any]]]:
    """
    Export cross-document lineage data in various formats.

This method exports cross-document lineage data for external analysis
or visualization. The data can be exported in various formats including
JSON, GraphML, and GEXF, and can optionally include the full records.

Args:
    lineage_graph: Optional pre-built lineage graph (built if not provided)
    record_ids: List of record IDs to include if building a new graph
    max_depth: Maximum traversal depth for cross-document relationships
    format: Export format ("json", "graphml", "gexf", "csv", "dot")
    file_path: Optional path to save the export
    include_records: Whether to include full record data in the export

Returns:
    Optional[Union[str, Dict[str, Any]]]: Export data if file_path is None
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDProvenanceStorage

## export_cross_document_lineage

```python
def export_cross_document_lineage(self, record_id: str, max_depth: int = 3, output_format: str = "json", output_file: Optional[str] = None) -> Union[str, Dict, None]:
    """
    Export cross-document lineage in various formats.

Args:
    record_id: ID of the record to export lineage for
    max_depth: Maximum traversal depth
    output_format: Format to export ('json', 'graphml', 'gexf', 'cytoscape')
    output_file: Path to save the exported lineage

Returns:
    Union[str, Dict, None]: Exported lineage data or None if export failed
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## export_to_car

```python
def export_to_car(self, output_path: str, include_records: bool = True, include_graph: bool = True, records: Optional[List[str]] = None) -> str:
    """
    Export provenance data to a CAR file.

Args:
    output_path: Path to output CAR file
    include_records: Whether to include individual records
    include_graph: Whether to include the graph structure
    records: Optional list of specific record IDs to include

Returns:
    str: Root CID of exported data
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDProvenanceStorage

## export_to_car

```python
def export_to_car(self, output_path: str, include_records: bool = True, include_graph: bool = True, selective_record_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Export provenance data to a CAR (Content Addressable aRchive) file.

This function exports the provenance graph and optionally all records to a
CAR file that can be imported into any IPFS node or IPLD-compatible system.
The function supports selective export by specifying record IDs.

Args:
    output_path: Path to output CAR file
    include_records: Whether to include record data
    include_graph: Whether to include graph structure
    selective_record_ids: Optional list of record IDs to include (None = all)

Returns:
    Dict[str, Any]: Export statistics and root CID
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## export_to_car

```python
def export_to_car(self, output_path: str) -> Optional[str]:
    """
    Export the entire provenance graph to a CAR file.

Args:
    output_path: Path to write the CAR file

Returns:
    Optional[str]: Root CID of the exported data, or None if export failed
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## get_cross_document_links

```python
def get_cross_document_links(self, record_id: str) -> List[Dict[str, Any]]:
    """
    Get all cross-document links for a specific record.

Args:
    record_id: ID of the record to get links for

Returns:
    List[Dict[str, Any]]: List of cross-document link records
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDProvenanceStorage

## get_document_id

```python
def get_document_id(record_id, record = None):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## get_lineage_graph

```python
def get_lineage_graph(self, record_id: str, depth: int = 5) -> nx.DiGraph:
    """
    Get the lineage graph for a specific record.

Args:
    record_id: ID of the record to get lineage for
    depth: Maximum depth to traverse

Returns:
    nx.DiGraph: Lineage graph
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## import_from_car

```python
def import_from_car(self, car_path: str, root_cid: Optional[str] = None, load_records: bool = True, load_graph: bool = True) -> Dict[str, Any]:
    """
    Import provenance data from a CAR (Content Addressable aRchive) file.

This function imports a provenance graph and optionally records from a CAR
file, supporting selective loading based on specified parameters.

Args:
    car_path: Path to input CAR file
    root_cid: Optional root CID to start import from (auto-detect if None)
    load_records: Whether to load record data
    load_graph: Whether to load graph structure

Returns:
    Dict[str, Any]: Import statistics and root CID
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## import_from_car

```python
def import_from_car(self, car_path: str) -> bool:
    """
    Import a provenance graph from a CAR file.

Args:
    car_path: Path to the CAR file to import

Returns:
    bool: Whether the import was successful
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## incremental_load

```python
def incremental_load(self, root_cid: str, criteria: Optional[Dict] = None) -> nx.DiGraph:
    """
    Incrementally load parts of a provenance graph based on criteria.

Args:
    root_cid: CID of the root graph
    criteria: Filtering criteria (time range, data_ids, record types)

Returns:
    nx.DiGraph: Partial provenance graph
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDProvenanceStorage

## incremental_load_provenance

```python
def incremental_load_provenance(self, criteria: Dict) -> nx.DiGraph:
    """
    Incrementally load parts of the provenance graph based on criteria.

This allows loading only relevant portions of large provenance graphs,
which is more efficient than loading the entire graph.

Args:
    criteria: Filtering criteria with any of these keys:
        - time_start: Minimum timestamp
        - time_end: Maximum timestamp
        - data_ids: List of data IDs to include
        - record_types: List of record types to include

Returns:
    nx.DiGraph: Partial provenance graph matching criteria
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## link_cross_document_provenance

```python
def link_cross_document_provenance(self, source_record_id: str, target_record_id: str, link_type: str = "related_to", properties: Optional[Dict[str, Any]] = None) -> str:
    """
    Create a provenance link between records from different documents or datasets.

This enables tracking cross-document provenance by establishing relationships
between provenance records that may exist in different partitions or graphs.
The resulting link record is itself a provenance record that can be verified.

Args:
    source_record_id: ID of the source provenance record
    target_record_id: ID of the target provenance record
    link_type: Type of relationship between the records
    properties: Additional properties for the link

Returns:
    str: CID of the cross-document link record
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDProvenanceStorage

## load_record

```python
def load_record(self, cid: str, record_class = None) -> "ProvenanceRecord":
    """
    Load a provenance record from IPLD storage.

Args:
    cid: CID of the record to load
    record_class: Optional class to use for instantiation

Returns:
    ProvenanceRecord: The loaded record
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDProvenanceStorage

## load_records_batch

```python
def load_records_batch(self, cids: List[str]) -> Dict[str, 'ProvenanceRecord']:
    """
    Load multiple records in a batch operation.

Args:
    cids: List of CIDs to load

Returns:
    Dict[str, ProvenanceRecord]: Mapping from CID to record
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDProvenanceStorage

## record_annotation

```python
def record_annotation(self, data_id: str, content: str, annotation_type: str = "note", author: str = "", tags: Optional[List[str]] = None, description: str = "", metadata: Optional[Dict[str, Any]] = None) -> str:
    """
    Record a manual annotation or note about a data entity.

Args:
    data_id: ID of the data entity being annotated
    content: Annotation content
    annotation_type: Type of annotation
    author: Author of annotation
    tags: Tags for categorization
    description: Description of the annotation
    metadata: Additional metadata

Returns:
    str: ID of the created annotation record
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## record_model_inference

```python
def record_model_inference(self, model_id: str, input_ids: List[str], output_id: str, model_version: str = "", batch_size: Optional[int] = None, output_type: str = "", performance_metrics: Optional[Dict[str, float]] = None, description: str = "", metadata: Optional[Dict[str, Any]] = None) -> str:
    """
    Record a model inference event.

Args:
    model_id: ID of the model used
    input_ids: IDs of input data entities
    output_id: ID of output data entity (inference results)
    model_version: Model version
    batch_size: Size of inference batch
    output_type: Type of output (predictions, embeddings, etc.)
    performance_metrics: Inference performance metrics
    description: Description of the inference
    metadata: Additional metadata

Returns:
    str: ID of the created model inference record
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## record_model_training

```python
def record_model_training(self, input_ids: List[str], output_id: str, model_type: str, model_framework: str = "", hyperparameters: Optional[Dict[str, Any]] = None, metrics: Optional[Dict[str, float]] = None, model_size: Optional[int] = None, model_hash: Optional[str] = None, description: str = "", metadata: Optional[Dict[str, Any]] = None) -> str:
    """
    Record a model training event.

Args:
    input_ids: IDs of input data entities (training data)
    output_id: ID of output data entity (trained model)
    model_type: Type of model
    model_framework: Framework used (PyTorch, TensorFlow, etc.)
    hyperparameters: Training hyperparameters
    metrics: Training metrics
    model_size: Model size in bytes
    model_hash: Model hash for verification
    description: Description of the training
    metadata: Additional metadata

Returns:
    str: ID of the created model training record
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## record_verification

```python
def record_verification(self, data_id: str, verification_type: str, schema: Optional[Dict[str, Any]] = None, validation_rules: Optional[List[Dict[str, Any]]] = None, pass_count: int = 0, fail_count: int = 0, error_samples: Optional[List[Dict[str, Any]]] = None, description: str = "", metadata: Optional[Dict[str, Any]] = None) -> str:
    """
    Record a data verification/validation event.

Args:
    data_id: ID of the data entity being verified
    verification_type: Type of verification (schema, integrity, etc.)
    schema: Schema used for verification
    validation_rules: Rules applied in validation
    pass_count: Number of records/fields that passed
    fail_count: Number of records/fields that failed
    error_samples: Samples of validation errors
    description: Description of the verification
    metadata: Additional metadata

Returns:
    str: ID of the created verification record
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## rotate_key

```python
def rotate_key(self, new_secret_key: Optional[str] = None) -> str:
    """
    Rotate the secret key and return the old one.

This should be followed by re-signing all records with the new key.

Args:
    new_secret_key: New secret key (generated if not provided)

Returns:
    str: The old secret key
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceCryptoVerifier

## semantic_search

```python
def semantic_search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Search for provenance records using keywords.

Args:
    query: Search query string
    limit: Maximum number of results to return

Returns:
    List[Dict[str, Any]]: Matching records with relevance scores
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## sign_all_records

```python
def sign_all_records(self) -> Dict[str, bool]:
    """
    Add cryptographic signatures to all records.

Returns:
    Dict[str, bool]: Map from record ID to success status
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## sign_record

```python
def sign_record(self, record: "ProvenanceRecord") -> str:
    """
    Create a cryptographic signature for a provenance record.

Args:
    record: The provenance record to sign

Returns:
    str: Hexadecimal signature
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceCryptoVerifier

## sign_record

```python
def sign_record(self, record: ProvenanceRecord) -> bool:
    """
    Add a cryptographic signature to a provenance record.

Args:
    record: The provenance record to sign

Returns:
    bool: Whether the signing was successful
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## store_graph

```python
def store_graph(self, graph: nx.DiGraph, partition: bool = None) -> str:
    """
    Store a provenance graph in IPLD.

Args:
    graph: NetworkX directed graph of provenance records
    partition: Whether to partition the graph (None=use default setting)

Returns:
    str: CID of the root graph
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDProvenanceStorage

## store_record

```python
def store_record(self, record: "ProvenanceRecord", sign: bool = True) -> str:
    """
    Store a provenance record with content addressing.

Args:
    record: The provenance record to store
    sign: Whether to sign the record (if crypto_verifier is available)

Returns:
    str: CID of the stored record
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDProvenanceStorage

## store_records_batch

```python
def store_records_batch(self, records: List['ProvenanceRecord'], sign: bool = True) -> Dict[str, str]:
    """
    Store multiple records in a batch operation.

Args:
    records: List of provenance records to store
    sign: Whether to sign the records

Returns:
    Dict[str, str]: Mapping from record ID to CID
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDProvenanceStorage

## temporal_query

```python
def temporal_query(self, start_time: Optional[float] = None, end_time: Optional[float] = None, time_bucket: str = "daily", record_types: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Query records based on time ranges.

Args:
    start_time: Start timestamp (Unix time)
    end_time: End timestamp (Unix time)
    time_bucket: Time bucket granularity ("daily", "hourly", "monthly")
    record_types: Types of records to include

Returns:
    List[Dict[str, Any]]: Matching records
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## traverse_graph_from_node

```python
def traverse_graph_from_node(self, start_node_id: str, max_depth: int = 3, direction: str = "both", relation_filter: Optional[List[str]] = None) -> nx.DiGraph:
    """
    Traverse the provenance graph from a starting node.

Args:
    start_node_id: ID of the starting node
    max_depth: Maximum traversal depth
    direction: Direction of traversal ("in", "out", or "both")
    relation_filter: Optional list of relation types to follow

Returns:
    nx.DiGraph: Subgraph reachable from the start node
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDProvenanceStorage

## traverse_links

```python
def traverse_links(record_id, current_depth = 0):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## traverse_provenance

```python
def traverse_provenance(self, record_id: str, max_depth: int = 3, direction: str = "both", relation_filter: Optional[List[str]] = None) -> nx.DiGraph:
    """
    Advanced traversal of the provenance graph from a starting record.

This method uses the enhanced IPLD provenance storage capabilities to perform
efficient graph traversal with fine-grained control over traversal direction
and relation types.

Args:
    record_id: ID of the starting record
    max_depth: Maximum traversal depth
    direction: Direction of traversal ("in", "out", or "both")
        - "in": Only traverse to records that input to this record
        - "out": Only traverse to records that this record outputs to
        - "both": Traverse in both directions
    relation_filter: Optional list of relation types to follow

Returns:
    nx.DiGraph: Subgraph reachable from the starting record
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## verify_all_records

```python
def verify_all_records(self) -> Dict[str, bool]:
    """
    Verify the cryptographic signatures of all records.

Returns:
    Dict[str, bool]: Map from record ID to verification result
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## verify_graph_integrity

```python
def verify_graph_integrity(self, records: Dict[str, 'ProvenanceRecord']) -> Dict[str, bool]:
    """
    Verify the integrity of a provenance graph.

This checks both the signatures of individual records and the
consistency of relationships between records.

Args:
    records: Dictionary of record ID to ProvenanceRecord

Returns:
    Dict[str, bool]: Map from record ID to verification result
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceCryptoVerifier

## verify_integrity

```python
def verify_integrity(self, crypto_verifier: Optional['ProvenanceCryptoVerifier'] = None) -> Dict[str, bool]:
    """
    Verify the cryptographic integrity of all provenance records.

Args:
    crypto_verifier: Verifier to use (uses instance verifier if None)

Returns:
    Dict[str, bool]: Mapping from record ID to verification result
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDProvenanceStorage

## verify_record

```python
def verify_record(self, record: "ProvenanceRecord") -> bool:
    """
    Verify the cryptographic signature of a provenance record.

Args:
    record: The provenance record to verify

Returns:
    bool: Whether the signature is valid
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceCryptoVerifier

## verify_record

```python
def verify_record(self, record_id: str) -> bool:
    """
    Verify the cryptographic signature of a provenance record.

Args:
    record_id: ID of the record to verify

Returns:
    bool: Whether the signature is valid
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## visualize_cross_document_clusters

```python
def visualize_cross_document_clusters(self, lineage_graph: Optional[nx.DiGraph] = None, record_ids: Optional[Union[str, List[str]]] = None, max_depth: int = 3, link_types: Optional[List[str]] = None, file_path: Optional[str] = None, format: str = "png", width: int = 1200, height: int = 800) -> Optional[Union[str, Dict[str, Any]]]:
    """
    Visualize cross-document clusters showing document boundaries and relationships.

This method creates a specialized visualization that emphasizes document
boundaries and cross-document relationships, making it easier to understand
how data flows between different documents or datasets.

Args:
    lineage_graph: Optional pre-built lineage graph to analyze
    record_ids: ID or list of record IDs to analyze (if graph not provided)
    max_depth: Maximum traversal depth for graph building
    link_types: Optional filter for specific link types to include
    file_path: Optional path to save the visualization
    format: Output format ("png", "svg", "json")
    width: Width of the visualization in pixels
    height: Height of the visualization in pixels

Returns:
    Optional[Union[str, Dict[str, Any]]]: Visualization result
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDProvenanceStorage

## visualize_cross_document_lineage

```python
def visualize_cross_document_lineage(self, lineage_graph: nx.DiGraph = None, record_ids: Optional[List[str]] = None, max_depth: int = 3, highlight_cross_document: bool = True, layout: str = "hierarchical", show_metrics: bool = True, file_path: Optional[str] = None, format: str = "png", width: int = 1200, height: int = 800) -> Optional[Union[str, Dict[str, Any]]]:
    """
    Visualize cross-document lineage relationships.

This method creates a visualization of cross-document lineage relationships,
with options to highlight cross-document links, show metrics, and use
different layout algorithms. The visualization can be saved to a file
or returned as a base64-encoded string or JSON object.

Args:
    lineage_graph: Optional pre-built lineage graph (built if not provided)
    record_ids: List of record IDs to include if building a new graph
    max_depth: Maximum traversal depth for cross-document relationships
    highlight_cross_document: Whether to highlight cross-document links
    layout: Layout algorithm to use ("hierarchical", "spring", "circular")
    show_metrics: Whether to show graph metrics in the visualization
    file_path: Optional path to save the visualization
    format: Output format ("png", "svg", "html", "json")
    width: Width of the visualization in pixels
    height: Height of the visualization in pixels

Returns:
    Optional[Union[str, Dict[str, Any]]]: Visualization result
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDProvenanceStorage

## visualize_cross_document_lineage

```python
def visualize_cross_document_lineage(self, start_record_id: str, max_depth: int = 3, output_file: Optional[str] = None, show_interactive: bool = False, layout: str = "dot", highlight_path: bool = True) -> Optional[nx.DiGraph]:
    """
    Visualize the cross-document lineage for a record.

This method creates a visualization of cross-document lineage,
showing how records in different documents/datasets are connected.

Args:
    start_record_id: ID of the record to visualize lineage for
    max_depth: Maximum traversal depth
    output_file: Path to save the visualization (PNG, PDF, SVG)
    show_interactive: Whether to show an interactive visualization
    layout: Graph layout algorithm ('dot', 'neato', 'fdp', 'sfdp', etc.)
    highlight_path: Whether to highlight critical paths

Returns:
    Optional[nx.DiGraph]: The lineage graph if successful
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager

## visualize_provenance_enhanced

```python
def visualize_provenance_enhanced(self, data_ids: Optional[List[str]] = None, max_depth: int = 5, include_parameters: bool = False, show_timestamps: bool = True, layout: str = "hierarchical", highlight_critical_path: bool = False, include_metrics: bool = False, file_path: Optional[str] = None, format: str = "png", return_base64: bool = False, width: int = 1200, height: int = 800, custom_colors: Optional[Dict[str, str]] = None) -> Optional[Union[str, Dict[str, Any]]]:
    """
    Enhanced visualization of the provenance graph.

Args:
    data_ids: List of data entity IDs to visualize, None for all
    max_depth: Maximum depth to trace back
    include_parameters: Whether to include operation parameters
    show_timestamps: Whether to show timestamps
    layout: Layout algorithm to use
    highlight_critical_path: Whether to highlight the critical path
    include_metrics: Whether to include metrics in the visualization
    file_path: Path to save the visualization
    format: Output format
    return_base64: Whether to return the image as base64
    width: Width of the visualization
    height: Height of the visualization
    custom_colors: Custom colors for node types

Returns:
    Optional[Union[str, Dict[str, Any]]]: Visualization result
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedProvenanceManager
