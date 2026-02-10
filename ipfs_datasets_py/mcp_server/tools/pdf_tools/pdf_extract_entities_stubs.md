# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/pdf_tools/pdf_extract_entities.py'

Files last updated: 1751408933.7664564

Stub file last updated: 2025-07-07 01:10:14

## pdf_extract_entities

```python
async def pdf_extract_entities(pdf_source: Union[str, dict], entity_types: Optional[List[str]] = None, extraction_method: str = "hybrid", confidence_threshold: float = 0.7, include_relationships: bool = True, context_window: int = 3, custom_patterns: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """
    Extract entities from PDF documents with advanced entity recognition,
relationship discovery, and integration with the knowledge graph.

This tool provides comprehensive entity extraction including:
- Named Entity Recognition (NER) for standard entity types
- Custom entity pattern matching
- Contextual entity extraction with surrounding content
- Entity relationship discovery
- Confidence scoring and validation
- Integration with existing knowledge graph entities

Args:
    pdf_source: Path to PDF file or document data dict
    entity_types: Specific entity types to extract (PERSON, ORG, LOC, etc.)
    extraction_method: Method to use ("ner", "pattern", "hybrid", "llm")
    confidence_threshold: Minimum confidence score for extracted entities
    include_relationships: Whether to discover relationships between entities
    context_window: Number of sentences around entities to include as context
    custom_patterns: Custom regex patterns for entity extraction
    
Returns:
    Dict containing:
    - status: "success" or "error"
    - document_info: Information about the processed document
    - entities_extracted: List of extracted entities with details
    - entity_relationships: Relationships discovered between entities
    - entity_summary: Summary statistics by entity type
    - context_information: Contextual information for each entity
    - confidence_analysis: Analysis of extraction confidence
    - processing_time: Entity extraction processing time
    - message: Success/error message
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
