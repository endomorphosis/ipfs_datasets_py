"""
Patent Dataset MCP Tools.

Thin standalone function wrappers around the canonical patent-dataset API.
All business logic lives in ipfs_datasets_py.processors.patent_dataset_api
(which re-exports from ipfs_datasets_py.processors.domains.patent.patent_dataset_api).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level import guard
# ---------------------------------------------------------------------------
try:
    from ipfs_datasets_py.processors.patent_dataset_api import (
        scrape_uspto_patents_from_parameters,
        search_patents_by_keyword_from_parameters,
        search_patents_by_inventor_from_parameters,
        search_patents_by_assignee_from_parameters,
        build_patent_dataset_from_parameters,
    )
    _PATENT_API_AVAILABLE = True
except ImportError as _e:
    logger.warning("patent_dataset_api not available: %s", _e)
    _PATENT_API_AVAILABLE = False

    async def scrape_uspto_patents_from_parameters(p: Dict[str, Any]) -> Dict[str, Any]:  # type: ignore[misc]
        return {"status": "error", "error": "patent_dataset_api not installed"}

    async def search_patents_by_keyword_from_parameters(p: Dict[str, Any]) -> Dict[str, Any]:  # type: ignore[misc]
        return {"status": "error", "error": "patent_dataset_api not installed"}

    async def search_patents_by_inventor_from_parameters(p: Dict[str, Any]) -> Dict[str, Any]:  # type: ignore[misc]
        return {"status": "error", "error": "patent_dataset_api not installed"}

    async def search_patents_by_assignee_from_parameters(p: Dict[str, Any]) -> Dict[str, Any]:  # type: ignore[misc]
        return {"status": "error", "error": "patent_dataset_api not installed"}

    async def build_patent_dataset_from_parameters(p: Dict[str, Any]) -> Dict[str, Any]:  # type: ignore[misc]
        return {"status": "error", "error": "patent_dataset_api not installed"}


# ---------------------------------------------------------------------------
# Standalone async MCP functions
# ---------------------------------------------------------------------------

async def scrape_uspto_patents(
    keywords: Optional[List[str]] = None,
    inventor_name: Optional[str] = None,
    assignee_name: Optional[str] = None,
    patent_number: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 100,
    output_format: str = "json",
    output_path: Optional[str] = None,
    rate_limit_delay: float = 1.0,
) -> Dict[str, Any]:
    """Scrape patents from the USPTO PatentsView API."""
    parameters: Dict[str, Any] = {
        "keywords": keywords or [],
        "inventor_name": inventor_name,
        "assignee_name": assignee_name,
        "patent_number": patent_number,
        "date_from": date_from,
        "date_to": date_to,
        "limit": limit,
        "output_format": output_format,
        "output_path": output_path,
        "rate_limit_delay": rate_limit_delay,
    }
    return await scrape_uspto_patents_from_parameters(parameters)


async def search_patents_by_keyword(
    keywords: List[str],
    limit: int = 100,
    rate_limit_delay: float = 1.0,
) -> Dict[str, Any]:
    """Search USPTO patents by keywords."""
    return await search_patents_by_keyword_from_parameters(
        {"keywords": keywords, "limit": limit, "rate_limit_delay": rate_limit_delay}
    )


async def search_patents_by_inventor(
    inventor_name: str,
    limit: int = 100,
    rate_limit_delay: float = 1.0,
) -> Dict[str, Any]:
    """Search USPTO patents by inventor name."""
    return await search_patents_by_inventor_from_parameters(
        {"inventor_name": inventor_name, "limit": limit, "rate_limit_delay": rate_limit_delay}
    )


async def search_patents_by_assignee(
    assignee_name: str,
    limit: int = 100,
    rate_limit_delay: float = 1.0,
) -> Dict[str, Any]:
    """Search USPTO patents by assignee/organization name."""
    return await search_patents_by_assignee_from_parameters(
        {"assignee_name": assignee_name, "limit": limit, "rate_limit_delay": rate_limit_delay}
    )


async def build_patent_dataset(
    search_criteria: Optional[Dict[str, Any]] = None,
    output_format: str = "json",
    output_path: Optional[str] = None,
    include_citations: bool = True,
    include_classifications: bool = True,
    graphrag_format: bool = True,
) -> Dict[str, Any]:
    """Build a structured patent dataset optimised for GraphRAG ingestion."""
    return await build_patent_dataset_from_parameters({
        "search_criteria": search_criteria or {},
        "output_format": output_format,
        "output_path": output_path,
        "include_citations": include_citations,
        "include_classifications": include_classifications,
        "graphrag_format": graphrag_format,
    })


# ---------------------------------------------------------------------------
# Backward-compatible registry list (functions, not class instances)
# ---------------------------------------------------------------------------
PATENT_DATASET_MCP_TOOLS = [
    scrape_uspto_patents,
    search_patents_by_keyword,
    search_patents_by_inventor,
    search_patents_by_assignee,
    build_patent_dataset,
]
