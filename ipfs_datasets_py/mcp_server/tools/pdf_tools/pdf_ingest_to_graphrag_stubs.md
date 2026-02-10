# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/pdf_tools/pdf_ingest_to_graphrag.py'

Files last updated: 1751408933.7664564

Stub file last updated: 2025-07-07 01:10:14

## pdf_ingest_to_graphrag

```python
async def pdf_ingest_to_graphrag(pdf_source: Union[str, dict], metadata: Optional[Dict[str, Any]] = None, enable_ocr: bool = True, target_llm: str = "gpt-4", chunk_strategy: str = "semantic", enable_cross_document: bool = True) -> Dict[str, Any]:
    """
    Ingest a PDF document into the GraphRAG system with full pipeline processing.

This tool executes the complete PDF processing pipeline:
1. PDF validation and decomposition
2. IPLD structuring  
3. Multi-engine OCR processing
4. LLM-optimized content chunking
5. Entity and relationship extraction
6. Vector embedding generation
7. GraphRAG integration and indexing
8. Cross-document relationship discovery

Args:
    pdf_source: Path to PDF file or PDF data dict
    metadata: Additional metadata for the document
    enable_ocr: Whether to perform OCR on scanned content
    target_llm: Target LLM for optimization (gpt-4, claude, etc.)
    chunk_strategy: Chunking strategy ("semantic", "fixed", "adaptive")
    enable_cross_document: Enable cross-document relationship discovery
    
Returns:
    Dict containing:
    - status: "success" or "error"
    - document_id: Unique identifier for the processed document
    - ipld_cid: IPLD content identifier for the document
    - entities_added: Number of entities extracted and added
    - relationships_added: Number of relationships discovered
    - vector_embeddings: Number of vector embeddings created
    - processing_time: Total processing time in seconds
    - pipeline_stages: Status of each pipeline stage
    - message: Success/error message
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
