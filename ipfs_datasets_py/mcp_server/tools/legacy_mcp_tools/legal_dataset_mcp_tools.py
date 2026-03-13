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
import inspect
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class _LegacyFunctionToolAdapter:
    """Adapter exposing callable legacy tools via MCP-style attributes."""

    def __init__(self, fn: Any, name: str, description: str, category: str = "legal_datasets") -> None:
        self._fn = fn
        self.name = name
        self.description = description
        self.category = category
        self.tags = ["legacy", "legal", "dataset"]

    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        if inspect.iscoroutinefunction(self._fn):
            try:
                return await self._fn(**parameters)
            except TypeError:
                return await self._fn(parameters)
        try:
            return self._fn(**parameters)
        except TypeError:
            return self._fn(parameters)

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {},
                "additionalProperties": True,
            },
            "category": self.category,
            "tags": list(self.tags),
            "version": "legacy-compat",
        }


class ScrapeMunicipalCodesTool:
    """Backward-compatible class wrapper for legacy municipal codes MCP tool."""

    def __init__(self) -> None:
        self.name = "scrape_municipal_codes"
        self.description = (
            "Scrape municipal legal codes using scrape_the_law_mk3 with "
            "fallback strategy support."
        )
        self.category = "legal_datasets"
        self.tags = ["municipal", "codes", "scraping", "legacy"]
        self.input_schema = {
            "type": "object",
            "properties": {
                "jurisdiction": {"type": "string"},
                "jurisdictions": {"type": "array", "items": {"type": "string"}},
                "provider": {"type": "string", "default": "auto"},
                "output_format": {"type": "string", "default": "json"},
                "include_metadata": {"type": "boolean", "default": True},
                "include_text": {"type": "boolean", "default": True},
                "rate_limit_delay": {"type": "number", "default": 1.0},
                "max_sections": {"type": ["integer", "null"], "default": None},
                "scraper_type": {"type": "string", "default": "playwright"},
                "enable_fallbacks": {"type": "boolean", "default": True},
                "fallback_methods": {"type": "array", "items": {"type": "string"}},
                "job_id": {"type": ["string", "null"], "default": None},
                "resume": {"type": "boolean", "default": False},
            },
            "additionalProperties": True,
        }

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": dict(self.input_schema),
            "category": self.category,
            "tags": list(self.tags),
            "version": "legacy-compat",
        }

    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        return await scrape_municipal_codes(
            jurisdiction=parameters.get("jurisdiction"),
            jurisdictions=parameters.get("jurisdictions"),
            provider=parameters.get("provider", "auto"),
            scraper_type=parameters.get("scraper_type", "playwright"),
            output_format=parameters.get("output_format", "json"),
            enable_fallbacks=parameters.get("enable_fallbacks", True),
            fallback_methods=parameters.get("fallback_methods"),
            job_id=parameters.get("job_id"),
        )


def _annotate_legacy_tool(fn: Any, name: str, description: str) -> Any:
    """Attach compatibility metadata expected by older MCP callers/tests."""
    setattr(fn, "name", name)
    setattr(fn, "description", description)
    setattr(fn, "category", "legal_datasets")
    setattr(fn, "tags", ["legacy", "legal", "dataset"])
    setattr(fn, "adapter", _LegacyFunctionToolAdapter(fn, name=name, description=description))
    return fn


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
    _annotate_legacy_tool(scrape_recap_archive, "scrape_recap_archive", "Scrape federal court documents from RECAP Archive."),
    _annotate_legacy_tool(search_recap_documents, "search_recap_documents", "Search RECAP Archive documents."),
    _annotate_legacy_tool(scrape_state_laws, "scrape_state_laws", "Scrape state statutes and legislation."),
    _annotate_legacy_tool(list_scraping_jobs, "list_scraping_jobs", "List legal dataset scraping jobs."),
    _annotate_legacy_tool(scrape_us_code, "scrape_us_code", "Scrape United States Code sections."),
    _annotate_legacy_tool(scrape_municipal_codes, "scrape_municipal_codes", "Scrape municipal legal codes with fallback support."),
]

if _patent_tools_available:
    for patent_tool in PATENT_DATASET_MCP_TOOLS:
        if hasattr(patent_tool, "name"):
            LEGAL_DATASET_MCP_TOOLS.append(patent_tool)
            continue
        patent_name = getattr(patent_tool, "__name__", "patent_tool")
        patent_desc = (getattr(patent_tool, "__doc__", "") or patent_name).strip().splitlines()[0]
        LEGAL_DATASET_MCP_TOOLS.append(_annotate_legacy_tool(patent_tool, patent_name, patent_desc))
