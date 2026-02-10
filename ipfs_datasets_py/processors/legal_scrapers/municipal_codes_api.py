"""Package-level API for municipal code scraping orchestration.

The actual scrapers live under :pymod:`ipfs_datasets_py.processors.legal_scrapers`.
This module centralizes request/parameter handling and job initialization so
MCP tools remain thin wrappers.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def initialize_municipal_codes_job(parameters: Dict[str, Any], *, tool_version: str = "1.0.0") -> Dict[str, Any]:
    jurisdiction = parameters.get("jurisdiction")
    jurisdictions = parameters.get("jurisdictions")

    target_jurisdictions: List[str] = []
    if jurisdiction:
        target_jurisdictions.append(jurisdiction)
    if jurisdictions:
        target_jurisdictions.extend(jurisdictions)

    if not target_jurisdictions:
        return {
            "status": "error",
            "error": "No jurisdictions specified. Provide 'jurisdiction' or 'jurisdictions' parameter.",
            "data": [],
            "metadata": {},
        }

    job_id = parameters.get("job_id")
    if not job_id:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        job_id = f"municipal_codes_{timestamp}"

    enable_fallbacks = parameters.get("enable_fallbacks", True)
    fallback_methods = parameters.get(
        "fallback_methods",
        ["wayback_machine", "archive_is", "common_crawl", "ipwb", "autoscraper", "playwright"],
    )

    result = {
        "status": "success",
        "job_id": job_id,
        "message": "Municipal code scraping job initialized with fallback methods",
        "jurisdictions": target_jurisdictions,
        "provider": parameters.get("provider", "auto"),
        "scraper_type": parameters.get("scraper_type", "playwright"),
        "output_format": parameters.get("output_format", "json"),
        "fallback_methods": fallback_methods if enable_fallbacks else [],
        "enable_fallbacks": enable_fallbacks,
        "note": "Municipal codes scraping integration initialized (scraping backend may be configured separately).",
        "data": [],
        "metadata": {
            "job_id": job_id,
            "jurisdictions_count": len(target_jurisdictions),
            "fallback_strategy": {
                "enabled": enable_fallbacks,
                "methods": fallback_methods,
                "description": "Fallback methods will be attempted in order if primary scraping fails",
            },
            "parameters": parameters,
            "tool_version": tool_version,
        },
    }

    logger.info(
        "Municipal code scraping job %s initialized for %s jurisdictions",
        job_id,
        len(target_jurisdictions),
    )
    return result
