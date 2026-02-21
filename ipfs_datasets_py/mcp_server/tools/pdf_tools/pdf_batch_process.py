"""
PDF Batch Process Tool - thin MCP wrapper.

Business logic is in:
    ipfs_datasets_py.processors.specialized.pdf.batch_processing_engine
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from ipfs_datasets_py.mcp_server.tools.mcp_helpers import (
    mcp_error_response,
    mcp_text_response,
    parse_json_object,
)

try:
    from ipfs_datasets_py.processors.specialized.pdf.batch_processing_engine import (
        pdf_batch_process as _engine_fn,
    )
    _ENGINE_AVAILABLE = True
except ImportError:
    _engine_fn = None
    _ENGINE_AVAILABLE = False

# Backward-compat alias for the JSON-string entrypoint
try:
    from ipfs_datasets_py.processors.specialized.batch.processor import BatchProcessor
except ImportError:
    BatchProcessor = None  # type: ignore[assignment,misc]


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
) -> Dict[str, Any]:
    """Thin MCP wrapper — see batch_processing_engine.pdf_batch_process."""
    # JSON-string entrypoint (MCP unit tests pass a JSON string as pdf_sources)
    if (
        isinstance(pdf_sources, str)
        and batch_size == 5
        and (pdf_sources.lstrip().startswith(("{", "[")) or not pdf_sources.strip())
    ):
        data, error = parse_json_object(pdf_sources)
        if error is not None:
            return error
        pdf_paths = data.get("pdf_paths")
        if not pdf_paths:
            return mcp_error_response("Missing required field: pdf_paths", error_type="validation")
        if BatchProcessor is None:
            return mcp_error_response("BatchProcessor is not available")
        try:
            processor = BatchProcessor()
            result = await processor.process_batch(
                pdf_paths=pdf_paths,
                batch_options=data.get("batch_options") or {},
                processing_options=data.get("processing_options") or {},
            )
            if isinstance(result, dict):
                return mcp_text_response(result)
            return mcp_text_response({"status": "success", "result": result})
        except Exception as exc:
            return mcp_text_response({"status": "error", "error": str(exc)})

    if not _ENGINE_AVAILABLE:
        return {"status": "error", "message": "Batch processing engine not available"}

    return await _engine_fn(
        pdf_sources=pdf_sources,
        batch_size=batch_size,
        parallel_workers=parallel_workers,
        enable_ocr=enable_ocr,
        target_llm=target_llm,
        chunk_strategy=chunk_strategy,
        enable_cross_document=enable_cross_document,
        output_format=output_format,
        progress_callback=progress_callback,
    )
