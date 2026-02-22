"""
PDF Cross-Document Analysis Tool - thin MCP wrapper.

Business logic is in:
    ipfs_datasets_py.processors.specialized.pdf.cross_document_engine
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ipfs_datasets_py.mcp_server.tools.mcp_helpers import (
    mcp_error_response,
    mcp_text_response,
    parse_json_object,
)

try:
    from ipfs_datasets_py.processors.specialized.pdf.cross_document_engine import (
        pdf_cross_document_analysis as _engine_fn,
    )
    _ENGINE_AVAILABLE = True
except ImportError:
    _engine_fn = None
    _ENGINE_AVAILABLE = False


async def pdf_cross_document_analysis(
    document_ids: Optional[Any] = None,
    analysis_types: List[str] = None,
    similarity_threshold: float = 0.75,
    max_connections: int = 100,
    temporal_analysis: bool = True,
    include_visualizations: bool = False,
    output_format: str = "detailed",
) -> Dict[str, Any]:
    """Thin MCP wrapper — see cross_document_engine.pdf_cross_document_analysis."""
    if analysis_types is None:
        analysis_types = ["entities", "themes", "citations"]

    # JSON-string entrypoint (MCP unit tests pass a JSON string as document_ids)
    if isinstance(document_ids, str) and analysis_types == ["entities", "themes", "citations"]:
        stripped = document_ids.lstrip()
        if stripped.startswith(("{", "[")) or not stripped:
            data, error = parse_json_object(document_ids)
            if error is not None:
                return error
            if not _ENGINE_AVAILABLE:
                return mcp_error_response("Cross-document analysis engine not available")
            try:
                result = await _engine_fn(
                    document_ids=data.get("document_ids"),
                    analysis_types=data.get("analysis_types") or analysis_types,
                    options=data.get("options") or {},
                )
                return mcp_text_response(result) if isinstance(result, dict) else mcp_text_response({"status": "success", "result": result})
            except Exception as exc:
                return mcp_text_response({"status": "error", "error": str(exc)})

    if not _ENGINE_AVAILABLE:
        return {"status": "error", "message": "Cross-document analysis engine not available"}

    return await _engine_fn(
        document_ids=document_ids,
        analysis_types=analysis_types,
        similarity_threshold=similarity_threshold,
        max_connections=max_connections,
        temporal_analysis=temporal_analysis,
        include_visualizations=include_visualizations,
        output_format=output_format,
    )
