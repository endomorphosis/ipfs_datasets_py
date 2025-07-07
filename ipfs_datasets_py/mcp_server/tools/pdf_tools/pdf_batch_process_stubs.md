# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/pdf_tools/pdf_batch_process.py'

Files last updated: 1751408933.7664564

Stub file last updated: 2025-07-07 01:10:14

## pdf_batch_process

```python
async def pdf_batch_process(pdf_sources: List[Union[str, Dict[str, Any]]], batch_size: int = 5, parallel_workers: int = 3, enable_ocr: bool = True, target_llm: str = "gpt-4", chunk_strategy: str = "semantic", enable_cross_document: bool = True, output_format: str = "detailed", progress_callback: Optional[str] = None) -> Dict[str, Any]:
    """
    Process multiple PDF documents through the complete GraphRAG pipeline with
batch optimization, parallel processing, and comprehensive progress tracking.

This tool provides efficient batch processing with:
- Parallel document processing with configurable workers
- Progress tracking and status updates
- Error handling and recovery for individual documents
- Resource management and memory optimization
- Comprehensive batch reporting
- Cross-document relationship discovery across the batch

Args:
    pdf_sources: List of PDF file paths or data dicts with metadata
    batch_size: Number of documents to process in each batch
    parallel_workers: Number of parallel processing workers
    enable_ocr: Whether to perform OCR on scanned content
    target_llm: Target LLM for optimization
    chunk_strategy: Chunking strategy for content processing
    enable_cross_document: Enable cross-document analysis
    output_format: Output detail level ("summary", "detailed", "full")
    progress_callback: Optional callback URL for progress updates
    
Returns:
    Dict containing:
    - status: "success", "partial_success", or "error"
    - batch_summary: Overall batch processing statistics
    - processed_documents: List of successfully processed documents
    - failed_documents: List of documents that failed processing
    - cross_document_analysis: Cross-document relationships discovered
    - performance_metrics: Processing performance statistics
    - total_processing_time: Total batch processing time
    - message: Summary message
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
