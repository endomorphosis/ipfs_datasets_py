#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Brave Legal Search MCP tools — thin wrappers.

All business logic lives in:
    ipfs_datasets_py.processors.legal_scrapers.brave_legal_search (BraveLegalSearch)

Tools:
- brave_legal_search
- brave_legal_search_generate_terms
- brave_legal_search_explain
- brave_legal_search_entities
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

try:
    from ipfs_datasets_py.processors.legal_scrapers import BraveLegalSearch
    _HAVE_BRAVE = True
except Exception:
    _HAVE_BRAVE = False
    BraveLegalSearch = None  # type: ignore


def _entity_display_name(entity: Any) -> str:
    """Return the best display name for a legal knowledge-base entity."""
    return (
        getattr(entity, "name", None)
        or getattr(entity, "agency_name", None)
        or getattr(entity, "place_name", None)
        or str(entity)
    )


    return {"status": "error", "error": f"BraveLegalSearch unavailable ({name})"}


def brave_legal_search(
    query: str,
    max_results: int = 20,
    country: str = "US",
    lang: str = "en",
) -> Dict[str, Any]:
    """Search for legal rules and regulations using natural language."""
    if not _HAVE_BRAVE:
        return _no_service("brave_legal_search")
    if not query:
        return {"status": "error", "error": "Missing required parameter: query"}
    try:
        results = BraveLegalSearch().search(query=query, max_results=max_results, country=country, lang=lang)
        return {
            "status": "success",
            "query": results["query"],
            "intent": results["intent"],
            "search_terms": results["search_terms"],
            "results": results["results"],
            "total_results": len(results["results"]),
            "metadata": results["metadata"],
        }
    except Exception as exc:
        logger.error("brave_legal_search error: %s", exc)
        return {"status": "error", "error": str(exc)}


def brave_legal_search_generate_terms(query: str) -> Dict[str, Any]:
    """Generate optimised search terms from a natural language legal query."""
    if not _HAVE_BRAVE:
        return _no_service("brave_legal_search_generate_terms")
    if not query:
        return {"status": "error", "error": "Missing required parameter: query"}
    try:
        terms = BraveLegalSearch().generate_search_terms(query)
        return {"status": "success", "query": query, "search_terms": terms}
    except Exception as exc:
        logger.error("brave_legal_search_generate_terms error: %s", exc)
        return {"status": "error", "error": str(exc)}


def brave_legal_search_explain(query: str) -> Dict[str, Any]:
    """Explain how a natural language legal query would be processed."""
    if not _HAVE_BRAVE:
        return _no_service("brave_legal_search_explain")
    if not query:
        return {"status": "error", "error": "Missing required parameter: query"}
    try:
        return {"status": "success", **BraveLegalSearch().explain_query(query)}
    except Exception as exc:
        logger.error("brave_legal_search_explain error: %s", exc)
        return {"status": "error", "error": str(exc)}


def brave_legal_search_entities(query: str, entity_type: str = "all") -> Dict[str, Any]:
    """Search the knowledge base of 21,000+ government entities."""
    if not _HAVE_BRAVE:
        return _no_service("brave_legal_search_entities")
    if not query:
        return {"status": "error", "error": "Missing required parameter: query"}
    try:
        searcher = BraveLegalSearch()
        results = (
            searcher.search_entities(query)
            if entity_type == "all"
            else searcher.search_entities(query, entity_type=entity_type)
        )
        formatted: Dict[str, Any] = {}
        for key, entities in results.items():
            formatted[key] = [
                {"name": _entity_display_name(e), "type": key}
                for e in entities[:10]
            ]
        return {
            "status": "success",
            "query": query,
            "entity_type": entity_type,
            "results": formatted,
            "total_found": sum(len(v) for v in results.values()),
        }
    except Exception as exc:
        logger.error("brave_legal_search_entities error: %s", exc)
        return {"status": "error", "error": str(exc)}


# ---------------------------------------------------------------------------
# Backward-compatible aliases (for __init__.py imports)
# ---------------------------------------------------------------------------
brave_legal_search_tool = brave_legal_search
brave_legal_search_generate_terms_tool = brave_legal_search_generate_terms
brave_legal_search_explain_tool = brave_legal_search_explain
brave_legal_search_entities_tool = brave_legal_search_entities

BRAVE_LEGAL_SEARCH_TOOLS = [
    brave_legal_search_tool,
    brave_legal_search_generate_terms_tool,
    brave_legal_search_explain_tool,
    brave_legal_search_entities_tool,
]


def register_brave_legal_search_tools(tool_registry) -> None:
    """Register Brave Legal Search tools with an MCP tool registry."""
    for fn in BRAVE_LEGAL_SEARCH_TOOLS:
        try:
            tool_registry.register_tool(fn)
        except Exception:
            pass
    logger.info("Registered %d Brave Legal Search tools", len(BRAVE_LEGAL_SEARCH_TOOLS))
