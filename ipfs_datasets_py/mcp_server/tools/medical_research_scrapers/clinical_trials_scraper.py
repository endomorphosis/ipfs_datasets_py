#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ClinicalTrials.gov Data Scraper — thin MCP wrapper.

Business logic lives in the canonical package module:
    ipfs_datasets_py.scrapers.medical.clinical_trials_engine

This file re-exports ClinicalTrialsScraper for backward compatibility and
provides MCP-callable standalone async functions.
"""

import logging
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.scrapers.medical.clinical_trials_engine import (  # noqa: F401
    ClinicalTrialsScraper,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MCP-callable standalone functions
# ---------------------------------------------------------------------------

_scraper: Optional[ClinicalTrialsScraper] = None


def _get_scraper() -> ClinicalTrialsScraper:
    global _scraper
    if _scraper is None:
        _scraper = ClinicalTrialsScraper()
    return _scraper


async def search_clinical_trials(
    query: str,
    condition: Optional[str] = None,
    intervention: Optional[str] = None,
    phase: Optional[str] = None,
    status: Optional[str] = None,
    max_results: int = 100,
) -> Dict[str, Any]:
    """Search ClinicalTrials.gov for matching clinical trials.

    Args:
        query: General search query.
        condition: Specific medical condition filter.
        intervention: Specific intervention/treatment filter.
        phase: Trial phase filter (e.g., ``"Phase 3"``).
        status: Trial status filter (e.g., ``"Completed"``).
        max_results: Maximum number of results.

    Returns:
        Dict with ``status``, ``results``, and ``count`` keys.
    """
    try:
        results = _get_scraper().search_trials(
            query=query,
            condition=condition,
            intervention=intervention,
            phase=phase,
            status=status,
            max_results=max_results,
        )
        return {"status": "success", "results": results, "count": len(results)}
    except Exception as exc:
        logger.error("search_clinical_trials failed: %s", exc)
        return {"status": "error", "error": str(exc), "results": []}


async def get_trial_outcomes(nct_id: str) -> Dict[str, Any]:
    """Get detailed outcome data for a specific clinical trial.

    Args:
        nct_id: ClinicalTrials.gov identifier (e.g., ``"NCT12345678"``).

    Returns:
        Dict with ``status`` and outcome data.
    """
    try:
        data = _get_scraper().get_trial_outcomes(nct_id)
        return {"status": "success", **data}
    except Exception as exc:
        logger.error("get_trial_outcomes failed: %s", exc)
        return {"status": "error", "error": str(exc)}


async def get_trial_demographics(nct_id: str) -> Dict[str, Any]:
    """Get population demographic data for a clinical trial.

    Args:
        nct_id: ClinicalTrials.gov identifier.

    Returns:
        Dict with ``status`` and demographic data.
    """
    try:
        data = _get_scraper().get_population_demographics(nct_id)
        return {"status": "success", **data}
    except Exception as exc:
        logger.error("get_trial_demographics failed: %s", exc)
        return {"status": "error", "error": str(exc)}
