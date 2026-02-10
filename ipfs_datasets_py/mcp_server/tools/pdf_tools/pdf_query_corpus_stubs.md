# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/pdf_tools/pdf_query_corpus.py'

Files last updated: 1751408933.7664564

Stub file last updated: 2025-07-07 01:10:14

## pdf_query_corpus

```python
async def pdf_query_corpus(query: str, query_type: str = "hybrid", max_documents: int = 10, document_filters: Optional[Dict[str, Any]] = None, enable_reasoning: bool = True, include_sources: bool = True, confidence_threshold: float = 0.7) -> Dict[str, Any]:
    """
    Query the PDF corpus using GraphRAG capabilities for comprehensive document analysis.

This tool provides multiple query strategies:
- Semantic search across document content
- Entity-based queries for specific entities and relationships
- Cross-document relationship traversal
- Hybrid queries combining multiple approaches
- Advanced reasoning with LLM integration

Args:
    query: Natural language query or structured query
    query_type: Type of query ("semantic", "entity", "relationship", "hybrid", "cross_document")
    max_documents: Maximum number of documents to include in results
    document_filters: Optional filters (author, date_range, document_type, etc.)
    enable_reasoning: Enable LLM-based reasoning over results
    include_sources: Include source document information in results
    confidence_threshold: Minimum confidence score for results
    
Returns:
    Dict containing:
    - status: "success" or "error"
    - answer: Generated answer or analysis
    - confidence_score: Overall confidence in the answer
    - source_documents: List of source documents with relevance scores
    - entities_found: Relevant entities discovered
    - relationships_found: Relevant relationships discovered
    - cross_document_connections: Cross-document relationships
    - query_analysis: Analysis of the query and processing approach
    - processing_time: Query processing time
    - message: Success/error message
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
