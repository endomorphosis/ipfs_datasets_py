#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Legal Dataset MCP Tools — standalone function wrappers.

Business logic is in ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_TOOL_VERSION = "1.0.0"


async def scrape_recap_archive(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Scrape federal court documents from RECAP Archive."""
    from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
        scrape_recap_archive_from_parameters,
    )
    return await scrape_recap_archive_from_parameters(parameters, tool_version=_TOOL_VERSION)


async def search_recap_documents(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Search RECAP Archive for specific court documents."""
    from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
        search_recap_documents_from_parameters,
    )
    return await search_recap_documents_from_parameters(parameters, tool_version=_TOOL_VERSION)


async def scrape_state_laws(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Scrape state legislation and statutes."""
    from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
        scrape_state_laws_from_parameters,
    )
    return await scrape_state_laws_from_parameters(parameters, tool_version=_TOOL_VERSION)


async def list_scraping_jobs(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """List all scraping jobs with resume capability."""
    from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
        list_scraping_jobs_from_parameters,
    )
    return await list_scraping_jobs_from_parameters(parameters, tool_version=_TOOL_VERSION)


async def scrape_us_code(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Scrape United States Code sections."""
    from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
        scrape_us_code_from_parameters,
    )
    return await scrape_us_code_from_parameters(parameters, tool_version=_TOOL_VERSION)


async def scrape_municipal_codes(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Scrape US municipal codes using scrape_the_law_mk3."""
    from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
        scrape_municipal_codes_from_parameters,
    )
    return await scrape_municipal_codes_from_parameters(parameters, tool_version=_TOOL_VERSION)


# Import patent tools for backward compatibility
try:
    from .patent_dataset_mcp_tools import PATENT_DATASET_MCP_TOOLS
    _patent_tools_available = True
except ImportError:
    _patent_tools_available = False
    PATENT_DATASET_MCP_TOOLS = []

LEGAL_DATASET_MCP_TOOLS: List[Any] = [
    scrape_recap_archive,
    search_recap_documents,
    scrape_state_laws,
    list_scraping_jobs,
    scrape_us_code,
    scrape_municipal_codes,
]

if _patent_tools_available:
    LEGAL_DATASET_MCP_TOOLS.extend(PATENT_DATASET_MCP_TOOLS)

__all__ = [
    "scrape_recap_archive",
    "search_recap_documents",
    "scrape_state_laws",
    "list_scraping_jobs",
    "scrape_us_code",
    "scrape_municipal_codes",
    "LEGAL_DATASET_MCP_TOOLS",
]
