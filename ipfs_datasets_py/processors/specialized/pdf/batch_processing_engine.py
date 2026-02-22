"""
PDF Batch Processing Engine

Canonical engine for batch-processing multiple PDF documents.
Delegates to processors.specialized.batch.processor.BatchProcessor.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

try:
    from ipfs_datasets_py.processors.specialized.batch.processor import BatchProcessor
    _BATCH_AVAILABLE = True
except ImportError:
    BatchProcessor = None  # type: ignore[assignment,misc]
    _BATCH_AVAILABLE = False


async def pdf_batch_process(
    pdf_sources: Union[List[Union[str, Dict[str, Any]]], str, None] = None,
    batch_size: int = 5,
    parallel_workers: int = 3,
    enable_ocr: bool = True,
    target_llm: str = "gpt-4",
    chunk_strategy: str = "semantic",
    enable_cross_document: bool = True,
    output_format: str = "detailed",
    progress_callback: Optional[str] = None,
    # JSON-mode input aliases
    pdf_paths: Optional[List[str]] = None,
    batch_options: Optional[Dict[str, Any]] = None,
    processing_options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Batch-process multiple PDF documents through the GraphRAG pipeline.

    Args:
        pdf_sources: List of PDF file paths or source dicts.
        batch_size: Documents per batch.
        parallel_workers: Parallel processing workers.
        enable_ocr: Apply OCR to scanned content.
        target_llm: Target LLM for optimization.
        chunk_strategy: Chunking strategy.
        enable_cross_document: Discover cross-document relationships.
        output_format: Detail level ("summary", "detailed", "full").
        progress_callback: Optional URL for progress updates.
        pdf_paths: Alias accepted when called with keyword args.
        batch_options: Batch configuration overrides.
        processing_options: Per-document processing overrides.

    Returns:
        Dict with status, batch_summary, processed_documents, failed_documents.
    """
    # Resolve sources from aliases
    sources: List[Union[str, Dict[str, Any]]] = []
    if pdf_paths:
        sources = pdf_paths  # type: ignore[assignment]
    elif isinstance(pdf_sources, list):
        sources = pdf_sources
    elif isinstance(pdf_sources, str):
        return {"status": "error", "message": "pdf_sources must be a list, not a string"}

    if not sources:
        return {"status": "error", "message": "No PDF sources provided (use pdf_sources or pdf_paths)"}

    if batch_size <= 0:
        return {"status": "error", "message": "batch_size must be greater than 0"}

    if parallel_workers <= 0:
        return {"status": "error", "message": "parallel_workers must be greater than 0"}

    valid_formats = ["summary", "detailed", "full"]
    if output_format not in valid_formats:
        return {"status": "error", "message": f"Invalid output_format. Must be one of: {valid_formats}"}

    if not _BATCH_AVAILABLE:
        return {
            "status": "error",
            "message": "Batch processing dependencies not available (processors.specialized.batch)",
        }

    try:
        processor = BatchProcessor()
        result = await processor.process_batch(
            pdf_paths=sources,  # type: ignore[arg-type]
            batch_options=batch_options or {},
            processing_options=processing_options or {},
        )

        if isinstance(result, dict) and "status" not in result:
            result["status"] = "success"

        return result if isinstance(result, dict) else {"status": "success", "result": result}

    except Exception as exc:
        logger.error("Error in pdf_batch_process: %s", exc)
        return {"status": "error", "message": f"Batch processing failed: {exc}"}
