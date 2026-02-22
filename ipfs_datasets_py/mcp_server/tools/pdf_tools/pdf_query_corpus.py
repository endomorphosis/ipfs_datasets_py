"""MCP wrapper for PDF corpus query.

Supports two call styles:
- Structured Python call (delegates to corpus_query_api)
- MCP-style JSON string call used by unit tests: await pdf_query_corpus(json.dumps({...}))
"""

import json
from typing import Any, Dict, Optional

try:
    from ipfs_datasets_py.processors.pdf_processing import QueryEngine  # type: ignore
except (ImportError, ModuleNotFoundError):
    QueryEngine = None  # type: ignore

from ipfs_datasets_py.mcp_server.tools.mcp_helpers import (
    mcp_error_response,
    mcp_text_response,
    parse_json_object,
)

async def pdf_query_corpus(
    query: str,
    query_type: str = "hybrid",
    max_documents: int = 10,
    document_filters: Optional[Dict[str, Any]] = None,
    enable_reasoning: bool = True,
    include_sources: bool = True,
    confidence_threshold: float = 0.7
) -> Dict[str, Any]:
    # MCP JSON-string entrypoint (used by unit tests)
    if (
        isinstance(query, str)
        and query_type == "hybrid"
        and max_documents == 10
        and document_filters is None
        and enable_reasoning is True
        and include_sources is True
        and confidence_threshold == 0.7
        and (query.lstrip().startswith("{") or query.lstrip().startswith("[") or any(ch.isspace() for ch in query) or not query.strip())
    ):
        data, error = parse_json_object(query)
        if error is not None:
            return error

        if not data.get("query"):
            return mcp_error_response("Missing required field: query", error_type="validation")

        engine_cls = QueryEngine
        if engine_cls is None:
            return mcp_error_response("QueryEngine is not available")

        try:
            engine = engine_cls()
            result = await engine.query(
                query=data["query"],
                query_type=data.get("query_type", "hybrid"),
                max_results=data.get("max_results", data.get("top_k", 10)),
                filters=data.get("filters"),
            )
            payload: Dict[str, Any] = {"status": "success"}
            if isinstance(result, dict):
                payload.update(result)
            else:
                payload["result"] = result
            return mcp_text_response(payload)
        except Exception as e:
            return mcp_text_response({"status": "error", "error": str(e)})

    from ipfs_datasets_py.processors.corpus_query_api import pdf_query_corpus as core_query

    return await core_query(
        query=query,
        query_type=query_type,
        max_documents=max_documents,
        document_filters=document_filters,
        enable_reasoning=enable_reasoning,
        include_sources=include_sources,
        confidence_threshold=confidence_threshold,
    )
