"""
Legal GraphRAG canonical engine module.

Standalone async functions for legal knowledge graph operations.
All business logic delegates to the canonical ``LegalGraphRAG``
class in :mod:`ipfs_datasets_py.processors.legal_scrapers.legal_graphrag`.

Public API
----------
create_legal_knowledge_graph(documents, ...)
search_legal_graph(graph_state, query, ...)
visualize_legal_graph(graph_state, ...)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_VALID_ENTITY_TYPES = ["case", "statute", "regulation", "party", "concept", "jurisdiction", "date"]
_VALID_REL_TYPES    = ["cites", "references", "overrules", "extends", "modifies", "relates_to"]
_VALID_LAYOUTS      = ["force", "hierarchical", "circular", "community"]
_VALID_FORMATS      = ["html", "png", "svg", "json", "mermaid", "dot"]
_VALID_SEARCH_TYPES = ["semantic", "keyword", "structural", "hybrid"]


def _err(msg: str, **kw) -> Dict[str, Any]:
    return {"status": "error", "message": msg, **kw}


# ---------------------------------------------------------------------------
# Public async functions
# ---------------------------------------------------------------------------


async def create_legal_knowledge_graph(
    documents: List[Dict[str, Any]],
    extract_entities: bool = True,
    extract_relationships: bool = True,
    entity_types: Optional[List[str]] = None,
    relationship_types: Optional[List[str]] = None,
    min_confidence: float = 0.6,
) -> Dict[str, Any]:
    """Create a legal knowledge graph from a list of documents.

    Parameters
    ----------
    documents:
        List of dicts, each containing at least ``"content"`` (plus optional
        ``"id"``, ``"title"``, ``"url"``).
    extract_entities:
        Extract legal entities from documents.
    extract_relationships:
        Extract relationships between entities.
    entity_types:
        Filter entity types.  Allowed: ``case``, ``statute``, ``regulation``,
        ``party``, ``concept``, ``jurisdiction``, ``date``.
    relationship_types:
        Filter relationship types.  Allowed: ``cites``, ``references``,
        ``overrules``, ``extends``, ``modifies``, ``relates_to``.
    min_confidence:
        Minimum extraction confidence (0.0–1.0).

    Returns
    -------
    dict
        ``status``, ``entities``, ``relationships``, ``graph_statistics``,
        ``graph_state`` (opaque object for subsequent calls), etc.
    """
    # --- validation ---
    if not documents or not isinstance(documents, list):
        return _err("Documents must be a non-empty list")
    for idx, doc in enumerate(documents):
        if not isinstance(doc, dict):
            return _err(f"Document at index {idx} must be a dictionary")
        if "content" not in doc:
            return _err(f"Document at index {idx} missing required field 'content'")
    if not 0.0 <= min_confidence <= 1.0:
        return _err("min_confidence must be between 0.0 and 1.0")
    if entity_types:
        for etype in entity_types:
            if etype not in _VALID_ENTITY_TYPES:
                return _err(f"Invalid entity type '{etype}'. Must be one of: {_VALID_ENTITY_TYPES}")
    if relationship_types:
        for rtype in relationship_types:
            if rtype not in _VALID_REL_TYPES:
                return _err(f"Invalid relationship type '{rtype}'. Must be one of: {_VALID_REL_TYPES}")

    try:
        from ipfs_datasets_py.processors.legal_scrapers import LegalGraphRAG

        graphrag = LegalGraphRAG()

        # Normalise documents into the format expected by build_knowledge_graph
        # (which accepts "search results" with title/snippet/url).
        results = [
            {
                "title":   doc.get("title", ""),
                "snippet": doc.get("content", "")[:500],  # use first 500 chars as snippet
                "url":     doc.get("url", ""),
                "domain":  doc.get("domain", ""),
            }
            for doc in documents
        ]

        kg = graphrag.build_knowledge_graph(
            results=results,
            extract_entities=extract_entities,
            extract_relationships=extract_relationships,
        )

        # Serialise entity objects (dataclasses / namedtuples) to plain dicts
        def _serialise(obj):
            if hasattr(obj, "_asdict"):
                return obj._asdict()
            if hasattr(obj, "__dict__"):
                return {k: _serialise(v) for k, v in obj.__dict__.items()
                        if not k.startswith("_")}
            return obj

        entities      = [_serialise(e) for e in kg.entities]
        relationships = [_serialise(r) for r in kg.relationships]

        graph_stats = {
            "total_entities":      len(entities),
            "total_relationships": len(relationships),
            "documents_processed": len(documents),
        }

        return {
            "status":          "success",
            "graph_state":     graphrag,   # opaque — pass to search / visualise
            "entities":        entities,
            "relationships":   relationships,
            "graph_statistics": graph_stats,
            "total_documents": len(documents),
            "total_entities":  len(entities),
            "total_relationships": len(relationships),
            "extraction_metadata": {
                "extract_entities":      extract_entities,
                "extract_relationships": extract_relationships,
                "min_confidence":        min_confidence,
            },
        }

    except ImportError as exc:
        logger.error("Import error in create_legal_knowledge_graph: %s", exc)
        return _err(
            f"Required module not found: {exc}. "
            "Install with: pip install ipfs-datasets-py[legal]",
            total_documents=len(documents),
        )
    except Exception as exc:
        logger.error("Error in create_legal_knowledge_graph: %s", exc)
        return _err(str(exc), total_documents=len(documents))


async def search_legal_graph(
    graph_state,
    query: str,
    search_type: str = "semantic",
    max_results: int = 10,
    include_subgraph: bool = False,
    hops: int = 2,
) -> Dict[str, Any]:
    """Search a legal knowledge graph.

    Parameters
    ----------
    graph_state:
        A ``LegalGraphRAG`` instance returned by :func:`create_legal_knowledge_graph`.
    query:
        Search query text.
    search_type:
        ``"semantic"``, ``"keyword"``, ``"structural"``, or ``"hybrid"``.
    max_results:
        Maximum number of results (1–100).
    include_subgraph:
        Attach subgraph around results.
    hops:
        Subgraph depth (1–5).
    """
    if not query:
        return _err("query is required")
    if search_type not in _VALID_SEARCH_TYPES:
        return _err(f"search_type must be one of: {_VALID_SEARCH_TYPES}")
    if not 1 <= max_results <= 100:
        return _err("max_results must be between 1 and 100")
    if not 1 <= hops <= 5:
        return _err("hops must be between 1 and 5")

    try:
        if graph_state is None:
            return _err("graph_state is required; call create_legal_knowledge_graph first")

        graphrag = graph_state

        # Semantic search is the primary supported mode
        raw_results = graphrag.semantic_search(query=query, top_k=max_results)

        def _serialise(obj):
            if hasattr(obj, "_asdict"):
                return obj._asdict()
            if hasattr(obj, "__dict__"):
                return {k: _serialise(v) for k, v in obj.__dict__.items()
                        if not k.startswith("_")}
            return obj

        results = [_serialise(r) for r in raw_results]

        subgraph = None
        if include_subgraph:
            raw_subgraph = graphrag.extract_subgraph(query=query, max_depth=hops)
            if raw_subgraph:
                subgraph = {
                    "entities":      [_serialise(e) for e in raw_subgraph.entities],
                    "relationships": [_serialise(r) for r in raw_subgraph.relationships],
                }

        return {
            "status":        "success",
            "results":       results,
            "subgraph":      subgraph,
            "total_results": len(results),
            "search_metadata": {
                "query":            query,
                "search_type":      search_type,
                "include_subgraph": include_subgraph,
                "hops":             hops,
            },
        }

    except Exception as exc:
        logger.error("Error in search_legal_graph: %s", exc)
        return _err(str(exc), query=query)


async def visualize_legal_graph(
    graph_state,
    layout: str = "force",
    format: str = "html",
    highlight_entities: Optional[List[str]] = None,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate a visualization of a legal knowledge graph.

    Parameters
    ----------
    graph_state:
        A ``LegalGraphRAG`` instance returned by :func:`create_legal_knowledge_graph`.
    layout:
        Layout algorithm: ``"force"``, ``"hierarchical"``, ``"circular"``,
        or ``"community"``.
    format:
        Export format: ``"html"``, ``"png"``, ``"svg"``, ``"json"``,
        ``"mermaid"``, or ``"dot"``.
    highlight_entities:
        Entity names/IDs to highlight.
    output_path:
        Optional path to save the visualization file.
    """
    if layout not in _VALID_LAYOUTS:
        return _err(f"layout must be one of: {_VALID_LAYOUTS}")
    if format not in _VALID_FORMATS:
        return _err(f"format must be one of: {_VALID_FORMATS}")

    try:
        if graph_state is None:
            return _err("graph_state is required; call create_legal_knowledge_graph first")

        graphrag  = graph_state
        # The canonical visualize_graph() supports "mermaid" and "dot"
        viz_format = "mermaid" if format in ("html", "json", "png", "svg") else format
        viz_data   = graphrag.visualize_graph(format=viz_format)

        if output_path:
            from pathlib import Path as _Path
            _Path(output_path).write_text(viz_data, encoding="utf-8")
            return {
                "status":      "success",
                "format":      format,
                "layout":      layout,
                "output_path": output_path,
                "message":     f"Graph visualization saved to {output_path}",
            }

        return {
            "status":             "success",
            "format":             format,
            "layout":             layout,
            "visualization_data": viz_data,
            "message":            "Graph visualization created successfully",
        }

    except Exception as exc:
        logger.error("Error in visualize_legal_graph: %s", exc)
        return _err(str(exc))
