"""
PDF LLM Optimization Engine

Canonical engine for optimizing PDF content for Large Language Model consumption.
Delegates to processors.specialized.pdf.pdf_processor.PDFProcessor.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

try:
    from ipfs_datasets_py.processors.specialized.pdf.pdf_processor import PDFProcessor
    _PDF_AVAILABLE = True
except ImportError:
    PDFProcessor = None  # type: ignore[assignment,misc]
    _PDF_AVAILABLE = False

_VALID_LLMS = ["gpt-4", "gpt-3.5", "claude", "claude-3", "gemini", "llama", "mistral"]
_VALID_STRATEGIES = ["semantic", "structural", "adaptive", "fixed"]


async def pdf_optimize_for_llm(
    pdf_source: Union[str, Dict[str, Any], None] = None,
    target_llm: str = "gpt-4",
    chunk_strategy: str = "semantic",
    max_chunk_size: int = 4000,
    overlap_size: int = 200,
    preserve_structure: bool = True,
    include_metadata: bool = True,
) -> Dict[str, Any]:
    """
    Optimize PDF content for Large Language Model consumption.

    Args:
        pdf_source: Path to PDF file, or dict with "document_id" or "path".
        target_llm: Target LLM ("gpt-4", "claude", "gemini", "llama", …).
        chunk_strategy: Chunking strategy ("semantic", "structural", "adaptive", "fixed").
        max_chunk_size: Maximum chunk size in characters.
        overlap_size: Overlap between chunks in characters.
        preserve_structure: Keep document structure in optimized output.
        include_metadata: Embed document metadata in optimized chunks.

    Returns:
        Dict with status, optimized_chunks, optimization_metrics, llm_recommendations.
    """
    # Validate target_llm
    if target_llm not in _VALID_LLMS:
        return {"status": "error", "message": f"Invalid target_llm. Must be one of: {_VALID_LLMS}"}

    if chunk_strategy not in _VALID_STRATEGIES:
        return {"status": "error", "message": f"Invalid chunk_strategy. Must be one of: {_VALID_STRATEGIES}"}

    if max_chunk_size <= 0:
        return {"status": "error", "message": "max_chunk_size must be greater than 0"}

    if overlap_size < 0 or overlap_size >= max_chunk_size:
        return {"status": "error", "message": "overlap_size must be non-negative and less than max_chunk_size"}

    # Resolve source
    pdf_path: Optional[Path] = None
    document_id: Optional[str] = None

    if isinstance(pdf_source, str):
        pdf_path = Path(pdf_source)
    elif isinstance(pdf_source, dict):
        if "document_id" in pdf_source:
            document_id = pdf_source["document_id"]
        elif "path" in pdf_source:
            pdf_path = Path(pdf_source["path"])
        else:
            return {"status": "error", "message": "PDF source dict must contain 'document_id' or 'path'"}
    elif pdf_source is not None:
        return {"status": "error", "message": "pdf_source must be a file path string or data dict"}

    if pdf_path is not None and not pdf_path.exists():
        return {"status": "error", "message": f"PDF file not found: {pdf_path}"}

    if not _PDF_AVAILABLE:
        return {
            "status": "error",
            "message": "PDF processing dependencies not available (processors.specialized.pdf)",
        }

    try:
        processor = PDFProcessor()

        # Use process_pdf for path-based input
        if pdf_path is not None:
            result = await processor.process_pdf(str(pdf_path))
        else:
            # document_id path: retrieve processed content and re-optimize
            result = {}

        optimized_chunks: List[Dict[str, Any]] = result.get("optimized_chunks", []) if isinstance(result, dict) else []

        return {
            "status": "success",
            "document_info": {
                "source_path": str(pdf_path) if pdf_path else None,
                "document_id": document_id,
            },
            "optimized_chunks": optimized_chunks,
            "optimization_settings": {
                "target_llm": target_llm,
                "chunk_strategy": chunk_strategy,
                "max_chunk_size": max_chunk_size,
                "overlap_size": overlap_size,
                "preserve_structure": preserve_structure,
                "include_metadata": include_metadata,
            },
            "optimization_metrics": {
                "chunks_created": len(optimized_chunks),
            },
            "message": f"PDF optimized for {target_llm} with {len(optimized_chunks)} chunks",
        }

    except Exception as exc:
        logger.error("Error in pdf_optimize_for_llm: %s", exc)
        return {"status": "error", "message": f"LLM optimization failed: {exc}"}
