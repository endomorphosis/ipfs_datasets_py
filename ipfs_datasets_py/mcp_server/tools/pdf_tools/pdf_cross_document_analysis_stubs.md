# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/pdf_tools/pdf_cross_document_analysis.py'

Files last updated: 1751408933.7664564

Stub file last updated: 2025-07-07 01:10:14

## pdf_cross_document_analysis

```python
async def pdf_cross_document_analysis(document_ids: Optional[List[str]] = None, analysis_types: List[str] = ['entities', 'themes', 'citations'], similarity_threshold: float = 0.75, max_connections: int = 100, temporal_analysis: bool = True, include_visualizations: bool = False, output_format: str = "detailed") -> Dict[str, Any]:
    """
    Perform comprehensive cross-document analysis across PDF corpus with
entity linking, thematic analysis, citation networks, and knowledge discovery.

This tool provides advanced cross-document analysis including:
- Entity co-reference resolution across documents
- Thematic similarity and clustering analysis
- Citation and reference network construction
- Temporal evolution tracking of concepts
- Knowledge graph relationship discovery
- Document influence and authority analysis

Args:
    document_ids: Specific document IDs to analyze (None for entire corpus)
    analysis_types: Types of analysis to perform
    similarity_threshold: Minimum similarity for cross-document connections
    max_connections: Maximum number of connections to return
    temporal_analysis: Include temporal evolution analysis
    include_visualizations: Generate visualization data
    output_format: Output detail level ("summary", "detailed", "full")
    
Returns:
    Dict containing:
    - status: "success" or "error"
    - corpus_info: Information about the analyzed corpus
    - entity_connections: Cross-document entity connections
    - thematic_clusters: Thematic clusters and relationships
    - citation_networks: Citation and reference networks
    - temporal_evolution: Temporal analysis of concepts and themes
    - influence_analysis: Document influence and authority scores
    - knowledge_discoveries: Novel relationships discovered
    - visualization_data: Data for visualization (if requested)
    - analysis_summary: Summary statistics and insights
    - processing_time: Analysis processing time
    - message: Success/error message
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
