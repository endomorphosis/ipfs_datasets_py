"""PDF corpus query API.

Core implementation behind the MCP tool `pdf_tools.pdf_query_corpus`.

This module is MCP-agnostic and can be used by CLI wrappers.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


async def pdf_query_corpus(
    query: str,
    query_type: str = "hybrid",
    max_documents: int = 10,
    document_filters: Optional[Dict[str, Any]] = None,
    enable_reasoning: bool = True,
    include_sources: bool = True,
    confidence_threshold: float = 0.7,
) -> Dict[str, Any]:
    """Query the PDF corpus using GraphRAG capabilities.

    Behavior intentionally matches the MCP tool response shape.
    """

    try:
        from ipfs_datasets_py.processors.pdf_processing import QueryEngine
        from ipfs_datasets_py.monitoring import track_operation

        query_engine = QueryEngine()

        valid_query_types = ["semantic", "entity", "relationship", "hybrid", "cross_document"]
        if query_type not in valid_query_types:
            return {"status": "error", "message": f"Invalid query type. Must be one of: {valid_query_types}"}

        if not isinstance(query, str) or not query.strip():
            return {"status": "error", "message": "Query cannot be empty"}

        if max_documents <= 0:
            return {"status": "error", "message": "max_documents must be greater than 0"}

        if not 0.0 <= confidence_threshold <= 1.0:
            return {"status": "error", "message": "confidence_threshold must be between 0.0 and 1.0"}

        with track_operation("pdf_query_corpus"):
            if query_type == "semantic":
                result = await query_engine.semantic_search(
                    query=query,
                    max_results=max_documents,
                    filters=document_filters,
                    confidence_threshold=confidence_threshold,
                )
            elif query_type == "entity":
                result = await query_engine.entity_query(
                    query=query,
                    max_results=max_documents,
                    filters=document_filters,
                    confidence_threshold=confidence_threshold,
                )
            elif query_type == "relationship":
                result = await query_engine.relationship_query(
                    query=query,
                    max_results=max_documents,
                    filters=document_filters,
                    confidence_threshold=confidence_threshold,
                )
            elif query_type == "cross_document":
                result = await query_engine.cross_document_query(
                    query=query,
                    max_results=max_documents,
                    filters=document_filters,
                    confidence_threshold=confidence_threshold,
                )
            else:
                result = await query_engine.hybrid_query(
                    query=query,
                    max_results=max_documents,
                    filters=document_filters,
                    enable_reasoning=enable_reasoning,
                    confidence_threshold=confidence_threshold,
                )

            source_documents = []
            if include_sources and isinstance(result, dict) and "documents" in result:
                for doc in result.get("documents") or []:
                    source_documents.append(
                        {
                            "document_id": doc.get("document_id"),
                            "title": doc.get("title", "Unknown"),
                            "relevance_score": doc.get("score", 0.0),
                            "page_numbers": doc.get("pages", []),
                            "excerpt": doc.get("excerpt", ""),
                            "metadata": doc.get("metadata", {}),
                        }
                    )

            entities_found = result.get("entities", []) if isinstance(result, dict) else []
            relationships_found = result.get("relationships", []) if isinstance(result, dict) else []
            cross_document_connections = result.get("cross_document_relationships", []) if isinstance(result, dict) else []

            return {
                "status": "success",
                "answer": result.get("answer", "") if isinstance(result, dict) else "",
                "confidence_score": result.get("confidence", 0.0) if isinstance(result, dict) else 0.0,
                "source_documents": source_documents,
                "entities_found": entities_found,
                "relationships_found": relationships_found,
                "cross_document_connections": cross_document_connections,
                "query_analysis": {
                    "query_type": query_type,
                    "query_complexity": result.get("query_complexity", "medium") if isinstance(result, dict) else "unknown",
                    "processing_strategy": result.get("strategy", "standard") if isinstance(result, dict) else "unknown",
                    "documents_searched": result.get("documents_searched", 0) if isinstance(result, dict) else 0,
                    "total_matches": len(source_documents),
                },
                "processing_time": result.get("processing_time", 0) if isinstance(result, dict) else 0,
                "message": f"Successfully processed {query_type} query with {len(source_documents)} relevant documents found",
            }

    except ImportError as e:
        logger.error("Query processing dependencies not available: %s", e)
        return {"status": "error", "message": f"Query processing dependencies not available: {str(e)}"}
    except Exception as e:
        logger.error("Error querying PDF corpus: %s", e)
        return {"status": "error", "message": f"Failed to query PDF corpus: {str(e)}"}
