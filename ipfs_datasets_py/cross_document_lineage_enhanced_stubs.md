# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/cross_document_lineage_enhanced.py'

Files last updated: 1748635923.4213796

Stub file last updated: 2025-07-07 02:11:01

## CrossDocumentImpactAnalyzer

```python
class CrossDocumentImpactAnalyzer:
    """
    Analyzes the impact of data transformations across document boundaries.

This class helps identify and visualize how changes in one document
affect other documents, measuring cross-document dependencies and
impact propagation.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## CrossDocumentLineageEnhancer

```python
class CrossDocumentLineageEnhancer:
    """
    Provides enhanced functionality for cross-document lineage tracking.

This class works with IPLDProvenanceStorage to extend its cross-document
lineage capabilities with advanced features like:
- Semantic relationship detection
- Document boundary analysis
- Enhanced visualization
- Relationship categorization
- Cross-document impact analysis
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## DetailedLineageIntegrator

```python
class DetailedLineageIntegrator:
    """
    Integrates data provenance with cross-document lineage tracking.

This class provides comprehensive integration between the EnhancedProvenanceManager
and cross-document lineage tracking capabilities, enabling:
- Detailed lineage analysis across document boundaries
- Comprehensive data flow visualization
- Semantic relationship enrichment
- Integrated impact analysis
- Enhanced reporting and visualization
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, storage):
    """
    Initialize the enhancer.

Args:
    storage: IPLDProvenanceStorage instance to enhance
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentLineageEnhancer

## __init__

```python
def __init__(self, provenance_manager, lineage_enhancer):
    """
    Initialize the integrator.

Args:
    provenance_manager: EnhancedProvenanceManager instance
    lineage_enhancer: CrossDocumentLineageEnhancer instance
    """
```
* **Async:** False
* **Method:** True
* **Class:** DetailedLineageIntegrator

## __init__

```python
def __init__(self, storage):
    """
    Initialize the impact analyzer.

Args:
    storage: IPLDProvenanceStorage instance
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentImpactAnalyzer

## _calculate_enhanced_metrics

```python
def _calculate_enhanced_metrics(self, graph):
    """
    Calculate enhanced metrics for the lineage graph.

Args:
    graph: nx.DiGraph to enhance
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentLineageEnhancer

## _detect_semantic_relationships

```python
def _detect_semantic_relationships(self, graph):
    """
    Detect and categorize semantic relationships in the graph.

Args:
    graph: nx.DiGraph to enhance
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentLineageEnhancer

## _enhance_document_boundaries

```python
def _enhance_document_boundaries(self, graph):
    """
    Enhance document boundary detection and labeling.

Args:
    graph: nx.DiGraph to enhance
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentLineageEnhancer

## _enhance_lineage_graph

```python
def _enhance_lineage_graph(self, graph):
    """
    Enhance a lineage graph with additional semantic information.

Args:
    graph: nx.DiGraph to enhance

Returns:
    nx.DiGraph: Enhanced graph
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentLineageEnhancer

## _export_to_cytoscape

```python
def _export_to_cytoscape(self, graph, file_path):
    """
    Export graph to Cytoscape.js format.
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentLineageEnhancer

## _export_to_gexf

```python
def _export_to_gexf(self, graph, file_path):
    """
    Export graph to GEXF format.
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentLineageEnhancer

## _export_to_graphml

```python
def _export_to_graphml(self, graph, file_path):
    """
    Export graph to GraphML format.
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentLineageEnhancer

## _export_to_json

```python
def _export_to_json(self, graph, file_path, include_records):
    """
    Export graph to JSON format.
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentLineageEnhancer

## _perform_document_clustering

```python
def _perform_document_clustering(self, graph):
    """
    Perform document clustering to identify related document groups.

Args:
    graph: nx.DiGraph to enhance
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentLineageEnhancer

## _safe_avg_path_length

```python
def _safe_avg_path_length(self, graph):
    """
    Calculate average path length safely.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DetailedLineageIntegrator

## _safe_diameter

```python
def _safe_diameter(self, graph):
    """
    Calculate graph diameter safely.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DetailedLineageIntegrator

## _visualize_with_matplotlib

```python
def _visualize_with_matplotlib(self, graph, highlight_cross_document, highlight_boundaries, layout, show_clusters, show_metrics, file_path, format, width, height):
    """
    Visualize lineage graph using matplotlib.

Args:
    graph: NetworkX DiGraph to visualize
    highlight_cross_document: Whether to highlight cross-document edges
    highlight_boundaries: Whether to highlight document boundaries
    layout: Layout algorithm to use
    show_clusters: Whether to group nodes by document clusters
    show_metrics: Whether to include metrics in visualization
    file_path: If specified, save visualization to this file
    format: Output format
    width: Width of the visualization in pixels
    height: Height of the visualization in pixels

Returns:
    Visualization result or None if saved to file
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentLineageEnhancer

## _visualize_with_plotly

```python
def _visualize_with_plotly(self, graph, highlight_cross_document, highlight_boundaries, show_clusters, show_metrics, file_path, format, width, height):
    """
    Visualize lineage graph using Plotly for interactive visualization.

Args:
    graph: NetworkX DiGraph to visualize
    highlight_cross_document: Whether to highlight cross-document edges
    highlight_boundaries: Whether to highlight document boundaries
    show_clusters: Whether to group nodes by document clusters
    show_metrics: Whether to include metrics in visualization
    file_path: If specified, save visualization to this file
    format: Output format
    width: Width of the visualization in pixels
    height: Height of the visualization in pixels

Returns:
    Visualization result or None if saved to file
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentLineageEnhancer

## analyze_cross_document_lineage

```python
def analyze_cross_document_lineage(self, lineage_graph = None, record_ids = None, max_depth = 3, include_semantic_analysis = True, include_impact_analysis = True, include_cluster_analysis = True):
    """
    Perform enhanced analysis of cross-document lineage.

This method provides a comprehensive analysis of cross-document
relationships, document boundaries, and data flow patterns.

Args:
    lineage_graph: Optional pre-built lineage graph. If None, built from record_ids
    record_ids: Single record ID or list of record IDs to start from (if lineage_graph is None)
    max_depth: Maximum traversal depth (if lineage_graph is None)
    include_semantic_analysis: Whether to include semantic relationship analysis
    include_impact_analysis: Whether to include impact analysis
    include_cluster_analysis: Whether to include document clustering analysis

Returns:
    dict: Detailed analysis results
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentLineageEnhancer

## analyze_data_flow_patterns

```python
def analyze_data_flow_patterns(self, integrated_graph):
    """
    Analyze data flow patterns in the integrated lineage graph.

This method identifies common data flow patterns, bottlenecks,
and critical paths in the data lineage.

Args:
    integrated_graph: nx.DiGraph - Integrated lineage graph

Returns:
    dict: Data flow pattern analysis
    """
```
* **Async:** False
* **Method:** True
* **Class:** DetailedLineageIntegrator

## analyze_impact

```python
def analyze_impact(self, source_id, max_depth = 3):
    """
    Analyze the impact of a record across document boundaries.

Args:
    source_id: ID of the record to analyze impact for
    max_depth: Maximum traversal depth

Returns:
    dict: Impact analysis results
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentImpactAnalyzer

## build_enhanced_cross_document_lineage_graph

```python
def build_enhanced_cross_document_lineage_graph(self, record_ids, max_depth = 3, link_types = None, include_semantic_analysis = True):
    """
    Build an enhanced cross-document lineage graph with additional semantic information.

This method extends the default graph building with:
- Semantic relationship detection and categorization
- Enhanced boundary detection and classification
- Document clustering and community detection
- Path relevance scoring
- More detailed metadata for nodes and edges

Args:
    record_ids: Single record ID or list of record IDs to start from
    max_depth: Maximum traversal depth
    link_types: Optional filter for specific types of links
    include_semantic_analysis: Whether to include semantic relationship analysis

Returns:
    nx.DiGraph: Enhanced lineage graph with additional attributes
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentLineageEnhancer

## create_unified_lineage_report

```python
def create_unified_lineage_report(self, integrated_graph = None, record_ids = None, include_visualization = True, output_path = None):
    """
    Create a comprehensive unified lineage report.

This method generates a detailed report that combines data provenance
and cross-document lineage information into a unified view.

Args:
    integrated_graph: nx.DiGraph - Integrated lineage graph (created if None)
    record_ids: IDs to start from if integrated_graph is None
    include_visualization: Whether to include visualization in the report
    output_path: Optional path to save the report

Returns:
    dict: Comprehensive lineage report
    """
```
* **Async:** False
* **Method:** True
* **Class:** DetailedLineageIntegrator

## enrich_lineage_semantics

```python
def enrich_lineage_semantics(self, integrated_graph):
    """
    Enrich the integrated lineage graph with additional semantic information.

This method enhances the integrated graph with:
- Improved relationship descriptions
- Data transformation context
- Process step categorization
- Confidence scoring for relationships

Args:
    integrated_graph: nx.DiGraph - Integrated lineage graph

Returns:
    nx.DiGraph: Semantically enriched lineage graph
    """
```
* **Async:** False
* **Method:** True
* **Class:** DetailedLineageIntegrator

## export_cross_document_lineage

```python
def export_cross_document_lineage(self, lineage_graph = None, record_ids = None, max_depth = 3, format = "json", file_path = None, include_records = False):
    """
    Export cross-document lineage to various formats.

Args:
    lineage_graph: Optional pre-built lineage graph. If None, built from record_ids
    record_ids: Single record ID or list of record IDs to start from (if lineage_graph is None)
    max_depth: Maximum traversal depth (if lineage_graph is None)
    format: Export format ("json", "cytoscape", "graphml", "gexf")
    file_path: If specified, save export to this file
    include_records: Whether to include full record data (caution: can be large)

Returns:
    Export data or None if saved to file
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentLineageEnhancer

## integrate_provenance_with_lineage

```python
def integrate_provenance_with_lineage(self, provenance_graph, lineage_graph = None):
    """
    Integrate provenance graph with cross-document lineage.

This method combines the detailed provenance tracking with cross-document
lineage information, creating a comprehensive unified lineage graph.

Args:
    provenance_graph: Provenance graph from EnhancedProvenanceManager
    lineage_graph: Optional cross-document lineage graph

Returns:
    nx.DiGraph: Integrated lineage graph
    """
```
* **Async:** False
* **Method:** True
* **Class:** DetailedLineageIntegrator

## link_cross_document_provenance

```python
def link_cross_document_provenance(self, source_record_id, target_record_id, link_type = "related_to", properties = None, confidence = 1.0, semantic_context = None, boundary_type = None):
    """
    Create an enhanced link between two provenance records that exist in different documents/datasets.

This enhanced version provides more detailed relationship information, including semantic context,
confidence scores, and boundary type classification for better cross-document lineage analysis.

Args:
    source_record_id (str): ID of the source record
    target_record_id (str): ID of the target record
    link_type (str): Type of relationship between the records (e.g., "derived_from", "relates_to", "contains")
    properties (dict, optional): Additional properties for the link
    confidence (float, optional): Confidence score for the relationship (0.0-1.0)
    semantic_context (dict, optional): Semantic information about the relationship
        - category: Semantic category (e.g., "content", "temporal", "causal")
        - description: Human-readable description of the relationship
        - keywords: List of keywords characterizing the relationship
    boundary_type (str, optional): Type of document boundary being crossed
        - "organization": Cross-organizational boundary
        - "system": Cross-system boundary
        - "dataset": Cross-dataset boundary
        - "domain": Cross-domain boundary
        - "temporal": Temporal boundary (different time periods)
        - "format": Format boundary (different data formats)
        - "security": Security boundary (different security contexts)
        - "pii_boundary": Boundary between PII and non-PII data
        - "phi_boundary": Boundary between PHI and non-PHI data
        - "international_transfer": International data transfer boundary

Returns:
    str: CID of the stored link record
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentLineageEnhancer

## track_document_lineage_evolution

```python
def track_document_lineage_evolution(self, document_id, time_range = None):
    """
    Track the evolution of document lineage over time.

This method analyzes how the lineage of a document has evolved
over time, identifying key changes and patterns.

Args:
    document_id: ID of the document to analyze
    time_range: Optional tuple of (start_time, end_time) as timestamps

Returns:
    dict: Document lineage evolution analysis
    """
```
* **Async:** False
* **Method:** True
* **Class:** DetailedLineageIntegrator

## visualize_enhanced_cross_document_lineage

```python
def visualize_enhanced_cross_document_lineage(self, lineage_graph = None, record_ids = None, max_depth = 3, highlight_cross_document = True, highlight_boundaries = True, layout = "hierarchical", show_clusters = True, show_metrics = True, file_path = None, format = "png", width = 1200, height = 800):
    """
    Visualize cross-document lineage with enhanced features.

This enhanced version provides better visualization with:
- Document boundary highlighting
- Document cluster visualization
- Semantic relationship coloring
- Boundary impact visualization
- Interactive capabilities with Plotly (if available)

Args:
    lineage_graph: Optional pre-built lineage graph. If None, built from record_ids
    record_ids: Single record ID or list of record IDs to start from (if lineage_graph is None)
    max_depth: Maximum traversal depth (if lineage_graph is None)
    highlight_cross_document: Whether to highlight cross-document edges
    highlight_boundaries: Whether to highlight document boundaries
    layout: Layout algorithm to use ("hierarchical", "spring", "circular", "spectral")
    show_clusters: Whether to group nodes by document clusters
    show_metrics: Whether to include metrics in visualization
    file_path: If specified, save visualization to this file
    format: Output format ("png", "svg", "pdf", "json", "html")
    width: Width of the visualization in pixels
    height: Height of the visualization in pixels

Returns:
    Visualization result (format dependent) or None if saved to file
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentLineageEnhancer

## visualize_impact

```python
def visualize_impact(self, source_id, max_depth = 3, file_path = None, format = "png"):
    """
    Visualize the impact of a record across document boundaries.

Args:
    source_id: ID of the record to analyze impact for
    max_depth: Maximum traversal depth
    file_path: If specified, save visualization to this file
    format: Output format

Returns:
    Visualization result or None if saved to file
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentImpactAnalyzer
