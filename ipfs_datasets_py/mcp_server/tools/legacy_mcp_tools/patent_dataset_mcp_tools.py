#!/usr/bin/env python
from __future__ import annotations

# DEPRECATED: This legacy module is superseded by
#   ipfs_datasets_py.mcp_server.tools.legal_dataset_tools
# See legacy_mcp_tools/MIGRATION_GUIDE.md for migration instructions.
import warnings
warnings.warn(
    "legacy_mcp_tools.patent_dataset_mcp_tools is deprecated. "
    "Use ipfs_datasets_py.mcp_server.tools.legal_dataset_tools instead.",
    DeprecationWarning,
    stacklevel=2,
)

import anyio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


async def scrape_uspto_patents(
    keywords: Optional[List[str]] = None,
    inventor_name: Optional[str] = None,
    assignee_name: Optional[str] = None,
    patent_number: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    cpc_classification: Optional[List[str]] = None,
    limit: int = 100,
    offset: int = 0,
    rate_limit_delay: float = 1.0,
    output_format: str = "json",
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Scrape patents from USPTO PatentsView API."""
    try:
        from ipfs_datasets_py.processors.legal_scrapers.patent_engine import (
            USPTOPatentScraper, PatentSearchCriteria, PatentDatasetBuilder,
        )
        criteria = PatentSearchCriteria(
            keywords=keywords, inventor_name=inventor_name,
            assignee_name=assignee_name, patent_number=patent_number,
            date_from=date_from, date_to=date_to,
            cpc_classification=cpc_classification, limit=limit, offset=offset,
        )
        scraper = USPTOPatentScraper(rate_limit_delay=rate_limit_delay)
        builder = PatentDatasetBuilder(scraper)
        return await builder.build_dataset_async(
            criteria=criteria,
            output_format=output_format,
            output_path=Path(output_path) if output_path else None,
        )
    except Exception as e:
        logger.error(f"USPTO patent scraping failed: {e}", exc_info=True)
        return {"status": "error", "error": str(e), "patents": [], "metadata": {}}


async def search_patents_by_keyword(
    keywords: List[str],
    limit: int = 100,
    rate_limit_delay: float = 1.0,
) -> Dict[str, Any]:
    """Search USPTO patents by keywords."""
    try:
        from ipfs_datasets_py.processors.legal_scrapers.patent_engine import search_patents_by_keyword as _fn
        from dataclasses import asdict
        patents = await anyio.to_thread.run_sync(_fn, keywords, limit, rate_limit_delay)
        patents_data = [asdict(p) for p in patents]
        return {"status": "success", "patents": patents_data, "count": len(patents_data), "query": {"keywords": keywords, "limit": limit}}
    except Exception as e:
        logger.error(f"Patent keyword search failed: {e}", exc_info=True)
        return {"status": "error", "error": str(e), "patents": [], "count": 0}


async def search_patents_by_inventor(
    inventor_name: str,
    limit: int = 100,
    rate_limit_delay: float = 1.0,
) -> Dict[str, Any]:
    """Search USPTO patents by inventor name."""
    try:
        from ipfs_datasets_py.processors.legal_scrapers.patent_engine import search_patents_by_inventor as _fn
        from dataclasses import asdict
        patents = await anyio.to_thread.run_sync(_fn, inventor_name, limit, rate_limit_delay)
        patents_data = [asdict(p) for p in patents]
        return {"status": "success", "patents": patents_data, "count": len(patents_data), "query": {"inventor_name": inventor_name, "limit": limit}}
    except Exception as e:
        logger.error(f"Patent inventor search failed: {e}", exc_info=True)
        return {"status": "error", "error": str(e), "patents": [], "count": 0}


async def search_patents_by_assignee(
    assignee_name: str,
    limit: int = 100,
    rate_limit_delay: float = 1.0,
) -> Dict[str, Any]:
    """Search USPTO patents by assignee/organization name."""
    try:
        from ipfs_datasets_py.processors.legal_scrapers.patent_engine import search_patents_by_assignee as _fn
        from dataclasses import asdict
        patents = await anyio.to_thread.run_sync(_fn, assignee_name, limit, rate_limit_delay)
        patents_data = [asdict(p) for p in patents]
        return {"status": "success", "patents": patents_data, "count": len(patents_data), "query": {"assignee_name": assignee_name, "limit": limit}}
    except Exception as e:
        logger.error(f"Patent assignee search failed: {e}", exc_info=True)
        return {"status": "error", "error": str(e), "patents": [], "count": 0}


async def build_patent_dataset(
    search_criteria: Optional[Dict[str, Any]] = None,
    output_format: str = "json",
    output_path: Optional[str] = None,
    graphrag_format: bool = True,
) -> Dict[str, Any]:
    """Build structured patent datasets for GraphRAG knowledge graph ingestion."""
    try:
        from ipfs_datasets_py.processors.legal_scrapers.patent_engine import (
            USPTOPatentScraper, PatentSearchCriteria, PatentDatasetBuilder,
        )
        sc = search_criteria or {}
        criteria = PatentSearchCriteria(
            keywords=sc.get("keywords"), inventor_name=sc.get("inventor_name"),
            assignee_name=sc.get("assignee_name"), patent_number=sc.get("patent_number"),
            date_from=sc.get("date_from"), date_to=sc.get("date_to"),
            cpc_classification=sc.get("cpc_classification"),
            limit=sc.get("limit", 100), offset=sc.get("offset", 0),
        )
        scraper = USPTOPatentScraper(rate_limit_delay=1.0)
        builder = PatentDatasetBuilder(scraper)
        result = await builder.build_dataset_async(
            criteria=criteria,
            output_format=output_format,
            output_path=Path(output_path) if output_path else None,
        )
        if graphrag_format:
            result["graphrag_metadata"] = {
                "entity_types": ["Patent", "Inventor", "Assignee", "Classification"],
                "relationship_types": ["INVENTED_BY", "ASSIGNED_TO", "CLASSIFIED_AS", "CITES"],
                "ready_for_ingestion": True,
                "suggested_embeddings": ["patent_title", "patent_abstract"],
            }
        return result
    except Exception as e:
        logger.error(f"Patent dataset building failed: {e}", exc_info=True)
        return {"status": "error", "error": str(e), "metadata": {}}


PATENT_DATASET_MCP_TOOLS = [
    scrape_uspto_patents,
    search_patents_by_keyword,
    search_patents_by_inventor,
    search_patents_by_assignee,
    build_patent_dataset,
]
