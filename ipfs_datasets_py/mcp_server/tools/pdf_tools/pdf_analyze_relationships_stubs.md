# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/pdf_tools/pdf_analyze_relationships.py'

Files last updated: 1751408933.7664564

Stub file last updated: 2025-07-07 01:10:14

## pdf_analyze_relationships

```python
async def pdf_analyze_relationships(document_id: str, analysis_type: str = "comprehensive", include_cross_document: bool = True, relationship_types: Optional[List[str]] = None, min_confidence: float = 0.6, max_relationships: int = 100) -> Dict[str, Any]:
    """
    Analyze relationships for a specific PDF document or across the corpus.

This tool provides comprehensive relationship analysis including:
- Entity co-occurrence analysis
- Semantic relationship discovery
- Citation and reference networks
- Cross-document entity connections
- Thematic relationship clustering

Args:
    document_id: ID of the document to analyze (or "all" for corpus-wide)
    analysis_type: Type of analysis ("entities", "citations", "themes", "comprehensive")
    include_cross_document: Include relationships with other documents
    relationship_types: Specific relationship types to focus on
    min_confidence: Minimum confidence threshold for relationships
    max_relationships: Maximum number of relationships to return
    
Returns:
    Dict containing:
    - status: "success" or "error"
    - document_info: Information about the analyzed document(s)
    - entity_relationships: Entity-based relationships found
    - citation_network: Citation and reference relationships
    - thematic_relationships: Thematic connections
    - cross_document_relationships: Relationships with other documents
    - relationship_graph: Graph representation of relationships
    - analysis_summary: Summary statistics and insights
    - processing_time: Analysis processing time
    - message: Success/error message
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
