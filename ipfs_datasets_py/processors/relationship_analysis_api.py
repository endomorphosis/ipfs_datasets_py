"""PDF relationship analysis API.

Core implementation behind the MCP tool `pdf_tools.pdf_analyze_relationships`.

This module is MCP-agnostic and can be used by CLI wrappers.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


async def pdf_analyze_relationships(
    document_id: str,
    analysis_type: str = "comprehensive",
    include_cross_document: bool = True,
    relationship_types: Optional[List[str]] = None,
    min_confidence: float = 0.6,
    max_relationships: int = 100,
) -> Dict[str, Any]:
    """Analyze relationships for a PDF document or corpus.

    Behavior intentionally matches the MCP tool response shape.
    """

    try:
        from ipfs_datasets_py.processors.pdf_processing import GraphRAGIntegrator
        from ipfs_datasets_py.processors.relationship_analyzer import RelationshipAnalyzer
        from ipfs_datasets_py.monitoring import track_operation

        integrator = GraphRAGIntegrator()
        analyzer = RelationshipAnalyzer()

        valid_analysis_types = ["entities", "citations", "themes", "comprehensive"]
        if analysis_type not in valid_analysis_types:
            return {"status": "error", "message": f"Invalid analysis type. Must be one of: {valid_analysis_types}"}

        if not 0.0 <= min_confidence <= 1.0:
            return {"status": "error", "message": "min_confidence must be between 0.0 and 1.0"}

        if max_relationships <= 0:
            return {"status": "error", "message": "max_relationships must be greater than 0"}

        with track_operation("pdf_analyze_relationships"):
            if document_id == "all":
                document_info = {"type": "corpus_wide", "document_count": "all"}
                documents = await integrator.get_all_documents()
            else:
                document_info = await integrator.get_document_info(document_id)
                if not document_info:
                    return {"status": "error", "message": f"Document not found: {document_id}"}
                documents = [document_info]

            results: Dict[str, Any] = {}

            if analysis_type in ["entities", "comprehensive"]:
                entity_results = await analyzer.analyze_entity_relationships(
                    documents=documents,
                    min_confidence=min_confidence,
                    max_relationships=max_relationships,
                    relationship_types=relationship_types,
                )
                results["entity_relationships"] = entity_results

            if analysis_type in ["citations", "comprehensive"]:
                citation_results = await analyzer.analyze_citation_network(
                    documents=documents,
                    include_cross_document=include_cross_document,
                    min_confidence=min_confidence,
                )
                results["citation_network"] = citation_results

            if analysis_type in ["themes", "comprehensive"]:
                theme_results = await analyzer.analyze_thematic_relationships(
                    documents=documents,
                    include_cross_document=include_cross_document,
                    min_confidence=min_confidence,
                )
                results["thematic_relationships"] = theme_results

            cross_doc_relationships: List[Any] = []
            if include_cross_document and document_id != "all":
                cross_doc_results = await analyzer.find_cross_document_relationships(
                    source_document_id=document_id,
                    min_confidence=min_confidence,
                    max_relationships=max_relationships,
                )
                if isinstance(cross_doc_results, dict):
                    cross_doc_relationships = cross_doc_results.get("relationships", [])

            relationship_graph = await analyzer.build_relationship_graph(
                results,
                include_cross_document=include_cross_document,
            )

            def _count_listish(value: Any) -> int:
                return len(value) if isinstance(value, list) else 0

            analysis_summary = {
                "total_relationships": sum(
                    _count_listish(v) for v in results.values() if isinstance(v, list)
                ),
                "entity_count": len(results.get("entity_relationships", {}).get("entities", [])),
                "citation_count": len(results.get("citation_network", {}).get("citations", [])),
                "theme_count": len(results.get("thematic_relationships", {}).get("themes", [])),
                "cross_document_count": len(cross_doc_relationships),
                "analysis_type": analysis_type,
                "confidence_range": {"min": min_confidence, "max": 1.0},
            }

            return {
                "status": "success",
                "document_info": document_info,
                "entity_relationships": results.get("entity_relationships", {}),
                "citation_network": results.get("citation_network", {}),
                "thematic_relationships": results.get("thematic_relationships", {}),
                "cross_document_relationships": cross_doc_relationships,
                "relationship_graph": relationship_graph,
                "analysis_summary": analysis_summary,
                "processing_time": sum(
                    r.get("processing_time", 0)
                    for r in results.values()
                    if isinstance(r, dict)
                ),
                "message": (
                    f"Successfully analyzed {analysis_type} relationships for document(s). "
                    f"Found {analysis_summary['total_relationships']} relationships."
                ),
            }

    except ImportError as e:
        logger.error("Relationship analysis dependencies not available: %s", e)
        return {"status": "error", "message": f"Relationship analysis dependencies not available: {str(e)}"}
    except Exception as e:
        logger.error("Error analyzing relationships: %s", e)
        return {"status": "error", "message": f"Failed to analyze relationships: {str(e)}"}
