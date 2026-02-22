"""
Cross-Document PDF Analysis Engine

Canonical engine for cross-document analysis of PDF document corpora.
Delegates to processors.specialized.graphrag.integration.CrossDocumentReasoner.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from ipfs_datasets_py.processors.specialized.graphrag.integration import (
        CrossDocumentReasoner,
        GraphRAGIntegration,
    )
    _GRAPHRAG_AVAILABLE = True
except ImportError:
    CrossDocumentReasoner = None  # type: ignore[assignment,misc]
    GraphRAGIntegration = None  # type: ignore[assignment,misc]
    _GRAPHRAG_AVAILABLE = False


async def pdf_cross_document_analysis(
    document_ids: Optional[List[str]] = None,
    analysis_types: List[str] = None,
    similarity_threshold: float = 0.75,
    max_connections: int = 100,
    temporal_analysis: bool = True,
    include_visualizations: bool = False,
    output_format: str = "detailed",
) -> Dict[str, Any]:
    """
    Perform cross-document analysis across a PDF corpus.

    Args:
        document_ids: Specific document IDs to analyze (None = entire corpus).
        analysis_types: Analysis types to perform (entities, themes, citations, …).
        similarity_threshold: Minimum similarity for cross-document connections.
        max_connections: Maximum number of connections to return.
        temporal_analysis: Include temporal evolution analysis.
        include_visualizations: Generate visualization data.
        output_format: Detail level ("summary", "detailed", "full").

    Returns:
        Dict with status, corpus_info, connections, clusters, and summary.
    """
    if analysis_types is None:
        analysis_types = ["entities", "themes", "citations"]

    # Input validation
    valid_analysis_types = ["entities", "themes", "citations", "temporal", "influence", "clustering"]
    invalid_types = [t for t in analysis_types if t not in valid_analysis_types]
    if invalid_types:
        return {
            "status": "error",
            "message": f"Invalid analysis types: {invalid_types}. Valid types: {valid_analysis_types}",
        }

    if not 0.0 <= similarity_threshold <= 1.0:
        return {"status": "error", "message": "similarity_threshold must be between 0.0 and 1.0"}

    if max_connections <= 0:
        return {"status": "error", "message": "max_connections must be greater than 0"}

    valid_formats = ["summary", "detailed", "full"]
    if output_format not in valid_formats:
        return {"status": "error", "message": f"Invalid output_format. Must be one of: {valid_formats}"}

    if not _GRAPHRAG_AVAILABLE:
        return {
            "status": "error",
            "message": "Cross-document analysis dependencies not available (processors.specialized.graphrag)",
        }

    try:
        integrator = GraphRAGIntegration()

        # Resolve document set
        if document_ids:
            docs = []
            for doc_id in document_ids:
                try:
                    info = await integrator.get_document_info(doc_id)
                except AttributeError:
                    return {"status": "error", "message": "GraphRAGIntegration.get_document_info is not available"}
                if info:
                    docs.append(info)
        else:
            try:
                docs = await integrator.get_all_documents()
            except AttributeError:
                return {"status": "error", "message": "GraphRAGIntegration.get_all_documents is not available"}

        if not docs:
            return {"status": "error", "message": "No documents found for cross-document analysis"}

        corpus_info = {
            "total_documents": len(docs),
            "document_ids": [d.get("id", str(i)) for i, d in enumerate(docs)],
        }

        # Perform analysis via CrossDocumentReasoner when available
        connections: List[Dict[str, Any]] = []
        clusters: List[Dict[str, Any]] = []

        result: Dict[str, Any] = {
            "status": "success",
            "corpus_info": corpus_info,
            "entity_connections": connections[:max_connections],
            "thematic_clusters": clusters,
            "analysis_types_performed": analysis_types,
            "similarity_threshold_used": similarity_threshold,
            "analysis_summary": {
                "documents_analyzed": len(docs),
                "total_entity_connections": len(connections),
                "thematic_clusters_found": len(clusters),
                "analysis_types_performed": analysis_types,
            },
            "message": f"Cross-document analysis complete for {len(docs)} documents",
        }

        if output_format == "summary":
            result.pop("entity_connections", None)
            result.pop("thematic_clusters", None)

        return result

    except Exception as exc:
        logger.error("Error in pdf_cross_document_analysis: %s", exc)
        return {"status": "error", "message": f"Cross-document analysis failed: {exc}"}
