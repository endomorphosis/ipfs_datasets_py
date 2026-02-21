"""
PDF Entity Extraction Tool - thin MCP wrapper.

Business logic is in:
    ipfs_datasets_py.processors.specialized.pdf.entity_extraction_engine
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from ipfs_datasets_py.mcp_server.tools.mcp_helpers import (
    mcp_error_response,
    mcp_text_response,
    parse_json_object,
)

try:
    from ipfs_datasets_py.processors.specialized.pdf.entity_extraction_engine import (
        pdf_extract_entities as _engine_fn,
    )
    _ENGINE_AVAILABLE = True
except ImportError:
    _engine_fn = None
    _ENGINE_AVAILABLE = False

# Lazy backward-compat alias kept from the original JSON-string path
try:
    from ipfs_datasets_py.processors.specialized.graphrag.integration import (
        GraphRAGIntegration as GraphRAGIntegrator,
    )
except ImportError:
    GraphRAGIntegrator = None  # type: ignore[assignment,misc]


async def pdf_extract_entities(
    pdf_source: Union[str, dict, None] = None,
    entity_types: Optional[List[str]] = None,
    extraction_method: str = "hybrid",
    confidence_threshold: float = 0.7,
    include_relationships: bool = True,
    context_window: int = 3,
    custom_patterns: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Thin MCP wrapper — see entity_extraction_engine.pdf_extract_entities."""
    # JSON-string entrypoint (MCP unit tests pass a JSON string as pdf_source)
    if (
        isinstance(pdf_source, str)
        and entity_types is None
        and extraction_method == "hybrid"
        and (pdf_source.lstrip().startswith(("{", "[")) or not pdf_source.strip())
    ):
        data, error = parse_json_object(pdf_source)
        if error is not None:
            return error
        document_id = data.get("document_id")
        if not document_id:
            return mcp_error_response("Missing required field: document_id", error_type="validation")
        if GraphRAGIntegrator is None:
            return mcp_error_response("GraphRAGIntegrator is not available")
        try:
            integrator = GraphRAGIntegrator()
            result = await integrator.extract_entities(
                document_id=document_id,
                entity_types=data.get("entity_types"),
                include_relationships=data.get("include_relationships", True),
                min_confidence=data.get("min_confidence", data.get("confidence_threshold", 0.7)),
                extraction_options=data.get("extraction_options"),
            )
            payload: Dict[str, Any] = {"status": "success"}
            if isinstance(result, dict):
                payload.update(result)
            else:
                payload["result"] = result
            return mcp_text_response(payload)
        except Exception as exc:
            return mcp_text_response({"status": "error", "error": str(exc)})

    if not _ENGINE_AVAILABLE:
        return {"status": "error", "message": "Entity extraction engine not available"}

    return await _engine_fn(
        pdf_source=pdf_source,
        entity_types=entity_types,
        extraction_method=extraction_method,
        confidence_threshold=confidence_threshold,
        include_relationships=include_relationships,
        context_window=context_window,
        custom_patterns=custom_patterns,
    )
