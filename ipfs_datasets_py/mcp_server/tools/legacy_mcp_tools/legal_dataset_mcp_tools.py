#!/usr/bin/env python
from __future__ import annotations

# DEPRECATED: This legacy module is superseded by
#   ipfs_datasets_py.mcp_server.tools.legal_dataset_tools
# See legacy_mcp_tools/MIGRATION_GUIDE.md for migration instructions.
import warnings
warnings.warn(
    "legacy_mcp_tools.legal_dataset_mcp_tools is deprecated. "
    "Use ipfs_datasets_py.mcp_server.tools.legal_dataset_tools instead.",
    DeprecationWarning,
    stacklevel=2,
)

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


async def scrape_recap_archive(
    courts: Optional[List[str]] = None,
    document_types: Optional[List[str]] = None,
    filed_after: Optional[str] = None,
    filed_before: Optional[str] = None,
    case_name_pattern: Optional[str] = None,
    output_format: str = "json",
    include_text: bool = True,
    include_metadata: bool = True,
    rate_limit_delay: float = 1.0,
    max_documents: Optional[int] = None,
    job_id: Optional[str] = None,
    resume: bool = False,
) -> Dict[str, Any]:
    """Scrape federal court documents from RECAP Archive (courtlistener.com)."""
    try:
        from ...mcp_server.tools.legal_dataset_tools import scrape_recap_archive as _scrape
        return await _scrape(
            courts=courts, document_types=document_types, filed_after=filed_after,
            filed_before=filed_before, case_name_pattern=case_name_pattern,
            output_format=output_format, include_text=include_text,
            include_metadata=include_metadata, rate_limit_delay=rate_limit_delay,
            max_documents=max_documents, job_id=job_id, resume=resume,
        )
    except Exception as e:
        logger.error(f"RECAP Archive scraping failed: {e}")
        return {"status": "error", "error": str(e), "data": [], "metadata": {}}


async def search_recap_documents(
    query: Optional[str] = None,
    court: Optional[str] = None,
    case_name: Optional[str] = None,
    filed_after: Optional[str] = None,
    filed_before: Optional[str] = None,
    document_type: Optional[str] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    """Search RECAP Archive for specific documents."""
    try:
        from ...mcp_server.tools.legal_dataset_tools import search_recap_documents as _search
        return await _search(
            query=query, court=court, case_name=case_name, filed_after=filed_after,
            filed_before=filed_before, document_type=document_type, limit=limit,
        )
    except Exception as e:
        logger.error(f"RECAP Archive search failed: {e}")
        return {"status": "error", "error": str(e), "documents": [], "count": 0}


async def scrape_state_laws(
    states: Optional[List[str]] = None,
    legal_areas: Optional[List[str]] = None,
    output_format: str = "json",
    include_metadata: bool = True,
    rate_limit_delay: float = 2.0,
    max_statutes: Optional[int] = None,
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Scrape state legislation and statutes from official state sources."""
    try:
        from ...mcp_server.tools.legal_dataset_tools import scrape_state_laws as _scrape
        result = await _scrape(
            states=states, legal_areas=legal_areas, output_format=output_format,
            include_metadata=include_metadata, rate_limit_delay=rate_limit_delay,
            max_statutes=max_statutes,
        )
        if job_id:
            result["job_id"] = job_id
        return result
    except Exception as e:
        logger.error(f"State laws scraping failed: {e}")
        return {"status": "error", "error": str(e), "data": [], "metadata": {}}


def list_scraping_jobs(
    status_filter: str = "all",
    job_type: str = "all",
) -> Dict[str, Any]:
    """List all scraping jobs with optional filters.

    Note: This function is intentionally synchronous because the underlying
    ``state_manager.list_scraping_jobs`` reads from a local file/DB synchronously.
    Consumers that need async behavior should run this in a thread executor.
    """
    try:
        from ...mcp_server.tools.legal_dataset_tools.state_manager import list_scraping_jobs as _list
        jobs = _list()
        if status_filter != "all":
            jobs = [j for j in jobs if j.get("status") == status_filter]
        if job_type != "all":
            jobs = [j for j in jobs if j.get("job_id", "").startswith(job_type)]
        return {"status": "success", "jobs": jobs, "total_count": len(jobs), "filters": {"status": status_filter, "job_type": job_type}}
    except Exception as e:
        logger.error(f"Failed to list scraping jobs: {e}")
        return {"status": "error", "error": str(e), "jobs": []}


async def scrape_us_code(
    titles: Optional[List[str]] = None,
    output_format: str = "json",
    include_metadata: bool = True,
    rate_limit_delay: float = 1.0,
) -> Dict[str, Any]:
    """Scrape United States Code sections."""
    try:
        from ...mcp_server.tools.legal_dataset_tools import scrape_us_code as _scrape
        return await _scrape(
            titles=titles, output_format=output_format,
            include_metadata=include_metadata, rate_limit_delay=rate_limit_delay,
        )
    except Exception as e:
        logger.error(f"US Code scraping failed: {e}")
        return {"status": "error", "error": str(e), "data": [], "metadata": {}}


async def scrape_municipal_codes(
    jurisdiction: Optional[str] = None,
    jurisdictions: Optional[List[str]] = None,
    provider: str = "auto",
    scraper_type: str = "playwright",
    output_format: str = "json",
    enable_fallbacks: bool = True,
    fallback_methods: Optional[List[str]] = None,
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Scrape municipal legal codes from US cities and counties using scrape_the_law_mk3."""
    try:
        from datetime import datetime

        target_jurisdictions: List[str] = []
        if jurisdiction:
            target_jurisdictions.append(jurisdiction)
        if jurisdictions:
            target_jurisdictions.extend(jurisdictions)

        if not target_jurisdictions:
            return {"status": "error", "error": "No jurisdictions specified.", "data": [], "metadata": {}}

        _job_id = job_id or f"municipal_codes_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        _fallback_methods = fallback_methods or ["wayback_machine", "archive_is", "common_crawl", "ipwb", "autoscraper", "playwright"]

        return {
            "status": "success",
            "job_id": _job_id,
            "message": "Municipal code scraping job initialized with fallback methods",
            "jurisdictions": target_jurisdictions,
            "provider": provider,
            "scraper_type": scraper_type,
            "output_format": output_format,
            "fallback_methods": _fallback_methods if enable_fallbacks else [],
            "enable_fallbacks": enable_fallbacks,
            "data": [],
            "metadata": {
                "job_id": _job_id,
                "jurisdictions_count": len(target_jurisdictions),
                "fallback_strategy": {"enabled": enable_fallbacks, "methods": _fallback_methods},
            },
        }
    except Exception as e:
        logger.error(f"Municipal code scraping failed: {e}")
        return {"status": "error", "error": str(e), "data": [], "metadata": {}}


# Import patent tools for backward compatibility
try:
    from .patent_dataset_mcp_tools import PATENT_DATASET_MCP_TOOLS
    _patent_tools_available = True
except ImportError:
    _patent_tools_available = False
    PATENT_DATASET_MCP_TOOLS = []

LEGAL_DATASET_MCP_TOOLS = [
    scrape_recap_archive, search_recap_documents, scrape_state_laws,
    list_scraping_jobs, scrape_us_code, scrape_municipal_codes,
]

if _patent_tools_available:
    LEGAL_DATASET_MCP_TOOLS.extend(PATENT_DATASET_MCP_TOOLS)
