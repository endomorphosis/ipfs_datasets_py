"""
PDF Entity Extraction Engine

Canonical engine for extracting entities and relationships from PDF documents.
Delegates to processors.specialized.graphrag.integration.GraphRAGIntegration.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from ipfs_datasets_py.processors.specialized.graphrag.integration import GraphRAGIntegration
    _GRAPHRAG_AVAILABLE = True
except ImportError:
    GraphRAGIntegration = None  # type: ignore[assignment,misc]
    _GRAPHRAG_AVAILABLE = False


async def pdf_extract_entities(
    document_id: Optional[str] = None,
    entity_types: Optional[List[str]] = None,
    extraction_method: str = "hybrid",
    confidence_threshold: float = 0.7,
    include_relationships: bool = True,
    context_window: int = 3,
    custom_patterns: Optional[Dict[str, str]] = None,
    # Legacy positional alias accepted as pdf_source
    pdf_source: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Extract named entities and relationships from a PDF document.

    Args:
        document_id: Document ID already ingested into the graph store.
        entity_types: Entity types to extract (PERSON, ORG, LOC, …).
        extraction_method: "ner", "pattern", "hybrid", or "llm".
        confidence_threshold: Minimum confidence [0.0, 1.0].
        include_relationships: Discover relationships between entities.
        context_window: Sentences of context around each entity.
        custom_patterns: Custom regex patterns keyed by entity type.
        pdf_source: Alias for document_id (accepts str or dict with "document_id").

    Returns:
        Dict with status, entities_extracted, entity_relationships, entity_summary.
    """
    # Resolve document_id from pdf_source alias
    if document_id is None and pdf_source is not None:
        if isinstance(pdf_source, dict):
            document_id = pdf_source.get("document_id")
        elif isinstance(pdf_source, str):
            document_id = pdf_source

    if not document_id:
        return {"status": "error", "message": "Missing required field: document_id"}

    if not 0.0 <= confidence_threshold <= 1.0:
        return {"status": "error", "message": "confidence_threshold must be between 0.0 and 1.0"}

    if context_window < 0:
        return {"status": "error", "message": "context_window must be non-negative"}

    if not _GRAPHRAG_AVAILABLE:
        return {
            "status": "error",
            "message": "Entity extraction dependencies not available (processors.specialized.graphrag)",
        }

    try:
        integrator = GraphRAGIntegration()
        result = await integrator.extract_entities(
            document_id=document_id,
            entity_types=entity_types,
            include_relationships=include_relationships,
            min_confidence=confidence_threshold,
            extraction_options=None,
        )

        payload: Dict[str, Any] = {"status": "success"}
        if isinstance(result, dict):
            payload.update(result)
        else:
            payload["result"] = result

        if "entities_extracted" not in payload:
            payload["entities_extracted"] = []
        if "entity_relationships" not in payload:
            payload["entity_relationships"] = []
        if "entity_summary" not in payload:
            payload["entity_summary"] = {}

        payload.setdefault("message", f"Extracted {len(payload['entities_extracted'])} entities from document {document_id}")
        return payload

    except Exception as exc:
        logger.error("Error in pdf_extract_entities: %s", exc)
        return {"status": "error", "message": f"Entity extraction failed: {exc}"}
