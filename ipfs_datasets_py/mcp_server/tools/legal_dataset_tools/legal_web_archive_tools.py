#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Legal Web Archive Search MCP tools — thin wrappers.

All business logic lives in:
    ipfs_datasets_py.processors.legal_scrapers.legal_web_archive_search (LegalWebArchiveSearch)

Tools:
- legal_web_archive_search
- legal_search_archives_only
- legal_archive_results
- legal_get_archive_stats
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from ipfs_datasets_py.processors.legal_scrapers import LegalWebArchiveSearch
    _HAVE_LWAS = True
except Exception:
    _HAVE_LWAS = False
    LegalWebArchiveSearch = None  # type: ignore


def _no_service(name: str) -> Dict[str, Any]:
    return {"status": "error", "error": f"LegalWebArchiveSearch unavailable ({name})"}


def legal_web_archive_search(
    query: str,
    max_results: int = 20,
    include_archives: bool = False,
    archive_results: bool = False,
    archive_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Unified legal search across current web + archives with optional archiving."""
    if not _HAVE_LWAS:
        return _no_service("legal_web_archive_search")
    if not query:
        return {"status": "error", "error": "Missing required parameter: query"}
    try:
        searcher = LegalWebArchiveSearch(archive_dir=archive_dir, auto_archive=archive_results)
        results = searcher.unified_search(
            query=query, max_results=max_results,
            include_archives=include_archives, archive_results=archive_results
        )
        return {"status": "success", **results}
    except Exception as exc:
        logger.error("legal_web_archive_search error: %s", exc)
        return {"status": "error", "error": str(exc)}


def legal_search_archives_only(
    query: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    domains: Optional[List[str]] = None,
    max_results: int = 50,
) -> Dict[str, Any]:
    """Search only archived legal documents with optional date-range filtering."""
    if not _HAVE_LWAS:
        return _no_service("legal_search_archives_only")
    if not query:
        return {"status": "error", "error": "Missing required parameter: query"}
    try:
        results = LegalWebArchiveSearch().search_archives(
            query=query, from_date=from_date, to_date=to_date,
            domains=domains, max_results=max_results,
        )
        return {"status": "success", **results}
    except Exception as exc:
        logger.error("legal_search_archives_only error: %s", exc)
        return {"status": "error", "error": str(exc)}


def legal_archive_results(
    query: str,
    results: List[Dict[str, Any]],
    archive_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Archive legal search results for preservation and future reference."""
    if not _HAVE_LWAS:
        return _no_service("legal_archive_results")
    if not query or not results:
        return {"status": "error", "error": "Missing required parameters: query and results"}
    try:
        info = LegalWebArchiveSearch(archive_dir=archive_dir)._archive_search_results(
            query=query, results=results, intent=None
        )
        return {"status": "success", **info}
    except Exception as exc:
        logger.error("legal_archive_results error: %s", exc)
        return {"status": "error", "error": str(exc)}


def legal_get_archive_stats(archive_dir: Optional[str] = None) -> Dict[str, Any]:
    """Get statistics about archived legal content."""
    if not _HAVE_LWAS:
        return _no_service("legal_get_archive_stats")
    try:
        stats = LegalWebArchiveSearch(archive_dir=archive_dir).get_archive_stats()
        return {"status": "success", **stats}
    except Exception as exc:
        logger.error("legal_get_archive_stats error: %s", exc)
        return {"status": "error", "error": str(exc)}


# ---------------------------------------------------------------------------
# Backward-compatible aliases (for __init__.py imports)
# ---------------------------------------------------------------------------
legal_web_archive_search_tool = legal_web_archive_search
legal_search_archives_only_tool = legal_search_archives_only
legal_archive_results_tool = legal_archive_results
legal_get_archive_stats_tool = legal_get_archive_stats

LEGAL_WEB_ARCHIVE_TOOLS = [
    legal_web_archive_search_tool,
    legal_search_archives_only_tool,
    legal_archive_results_tool,
    legal_get_archive_stats_tool,
]


def register_legal_web_archive_tools(tool_registry) -> None:
    """Register Legal Web Archive tools with an MCP tool registry."""
    for fn in LEGAL_WEB_ARCHIVE_TOOLS:
        try:
            tool_registry.register_tool(fn)
        except Exception:
            pass
    logger.info("Registered %d Legal Web Archive tools", len(LEGAL_WEB_ARCHIVE_TOOLS))
