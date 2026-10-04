#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PubMed Medical Literature Scraper — thin MCP wrapper.

Business logic lives in the canonical package module:
    ipfs_datasets_py.scrapers.medical.pubmed_engine

This file re-exports PubMedScraper for backward compatibility and provides
MCP-callable standalone async functions.
"""

import logging
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.scrapers.medical.pubmed_engine import PubMedScraper  # noqa: F401

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MCP-callable standalone functions
# ---------------------------------------------------------------------------

_scraper: Optional[PubMedScraper] = None


def _get_scraper() -> PubMedScraper:
    global _scraper
    if _scraper is None:
        _scraper = PubMedScraper()
    return _scraper


async def search_medical_research(
    query: str,
    max_results: int = 100,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    research_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Search PubMed for medical research articles.

    Args:
        query: Search query (MeSH terms, keywords).
        max_results: Maximum number of results.
        start_date: Start date filter (``YYYY/MM/DD``).
        end_date: End date filter (``YYYY/MM/DD``).
        research_type: Filter by publication type (e.g., ``"clinical trial"``).

    Returns:
        Dict with ``status``, ``results``, and ``count`` keys.
    """
    try:
        results = _get_scraper().search_medical_research(
            query=query,
            max_results=max_results,
            start_date=start_date,
            end_date=end_date,
            research_type=research_type,
        )
        return {"status": "success", "results": results, "count": len(results)}
    except Exception as exc:
        logger.error("search_medical_research failed: %s", exc)
        return {"status": "error", "error": str(exc), "results": []}


async def scrape_biochemical_research(
    topic: str,
    max_results: int = 100,
    time_range_days: Optional[int] = None,
) -> Dict[str, Any]:
    """Scrape biochemical research articles from PubMed.

    Args:
        topic: Biochemical research topic.
        max_results: Maximum number of results.
        time_range_days: Limit results to the last N days.

    Returns:
        Dict with ``status``, ``results``, and ``count`` keys.
    """
    try:
        results = _get_scraper().scrape_biochemical_research(
            topic=topic,
            max_results=max_results,
            time_range_days=time_range_days,
        )
        return {"status": "success", "results": results, "count": len(results)}
    except Exception as exc:
        logger.error("scrape_biochemical_research failed: %s", exc)
        return {"status": "error", "error": str(exc), "results": []}


async def scrape_clinical_outcomes(
    condition: str,
    intervention: Optional[str] = None,
    max_results: int = 100,
) -> Dict[str, Any]:
    """Scrape clinical outcome studies from PubMed.

    Args:
        condition: Medical condition (e.g., ``"diabetes"``).
        intervention: Treatment or intervention.
        max_results: Maximum number of results.

    Returns:
        Dict with ``status``, ``results``, and ``count`` keys.
    """
    try:
        results = _get_scraper().scrape_clinical_outcomes(
            condition=condition,
            intervention=intervention,
            max_results=max_results,
        )
        return {"status": "success", "results": results, "count": len(results)}
    except Exception as exc:
        logger.error("scrape_clinical_outcomes failed: %s", exc)
        return {"status": "error", "error": str(exc), "results": []}
