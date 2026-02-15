#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Package-level API for patent dataset tools.

MCP tools should delegate into these functions.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict

import anyio

from .patent_scraper import (
    PatentDatasetBuilder,
    PatentSearchCriteria,
    USPTOPatentScraper,
    search_patents_by_assignee,
    search_patents_by_inventor,
    search_patents_by_keyword,
)

logger = logging.getLogger(__name__)


async def scrape_uspto_patents_from_parameters(parameters: Dict[str, Any]) -> Dict[str, Any]:
    try:
        criteria = PatentSearchCriteria(
            keywords=parameters.get("keywords"),
            inventor_name=parameters.get("inventor_name"),
            assignee_name=parameters.get("assignee_name"),
            patent_number=parameters.get("patent_number"),
            date_from=parameters.get("date_from"),
            date_to=parameters.get("date_to"),
            cpc_classification=parameters.get("cpc_classification"),
            limit=parameters.get("limit", 100),
            offset=parameters.get("offset", 0),
        )

        scraper = USPTOPatentScraper(rate_limit_delay=parameters.get("rate_limit_delay", 1.0))
        builder = PatentDatasetBuilder(scraper)

        output_path = parameters.get("output_path")
        path_obj = Path(output_path) if output_path else None

        return await builder.build_dataset_async(
            criteria=criteria,
            output_format=parameters.get("output_format", "json"),
            output_path=path_obj,
        )
    except Exception as e:
        logger.error("USPTO patent scraping failed: %s", e, exc_info=True)
        return {"status": "error", "error": str(e), "patents": [], "metadata": {}}


async def search_patents_by_keyword_from_parameters(parameters: Dict[str, Any]) -> Dict[str, Any]:
    try:
        patents = await anyio.to_thread.run_sync(
            search_patents_by_keyword,
            parameters["keywords"],
            parameters.get("limit", 100),
            parameters.get("rate_limit_delay", 1.0),
        )
        patents_data = [asdict(p) for p in patents]
        return {
            "status": "success",
            "patents": patents_data,
            "count": len(patents_data),
            "query": {"keywords": parameters["keywords"], "limit": parameters.get("limit", 100)},
        }
    except Exception as e:
        logger.error("Patent keyword search failed: %s", e, exc_info=True)
        return {"status": "error", "error": str(e), "patents": [], "count": 0}


async def search_patents_by_inventor_from_parameters(parameters: Dict[str, Any]) -> Dict[str, Any]:
    try:
        patents = await anyio.to_thread.run_sync(
            search_patents_by_inventor,
            parameters["inventor_name"],
            parameters.get("limit", 100),
            parameters.get("rate_limit_delay", 1.0),
        )
        patents_data = [asdict(p) for p in patents]
        return {
            "status": "success",
            "patents": patents_data,
            "count": len(patents_data),
            "query": {"inventor_name": parameters["inventor_name"], "limit": parameters.get("limit", 100)},
        }
    except Exception as e:
        logger.error("Patent inventor search failed: %s", e, exc_info=True)
        return {"status": "error", "error": str(e), "patents": [], "count": 0}


async def search_patents_by_assignee_from_parameters(parameters: Dict[str, Any]) -> Dict[str, Any]:
    try:
        patents = await anyio.to_thread.run_sync(
            search_patents_by_assignee,
            parameters["assignee_name"],
            parameters.get("limit", 100),
            parameters.get("rate_limit_delay", 1.0),
        )
        patents_data = [asdict(p) for p in patents]
        return {
            "status": "success",
            "patents": patents_data,
            "count": len(patents_data),
            "query": {"assignee_name": parameters["assignee_name"], "limit": parameters.get("limit", 100)},
        }
    except Exception as e:
        logger.error("Patent assignee search failed: %s", e, exc_info=True)
        return {"status": "error", "error": str(e), "patents": [], "count": 0}


async def build_patent_dataset_from_parameters(parameters: Dict[str, Any]) -> Dict[str, Any]:
    try:
        search_params = parameters.get("search_criteria", {}) or {}
        criteria = PatentSearchCriteria(
            keywords=search_params.get("keywords"),
            inventor_name=search_params.get("inventor_name"),
            assignee_name=search_params.get("assignee_name"),
            patent_number=search_params.get("patent_number"),
            date_from=search_params.get("date_from"),
            date_to=search_params.get("date_to"),
            cpc_classification=search_params.get("cpc_classification"),
            limit=search_params.get("limit", 100),
            offset=search_params.get("offset", 0),
        )

        scraper = USPTOPatentScraper(rate_limit_delay=1.0)
        builder = PatentDatasetBuilder(scraper)

        output_path = parameters.get("output_path")
        path_obj = Path(output_path) if output_path else None

        result = await builder.build_dataset_async(
            criteria=criteria,
            output_format=parameters.get("output_format", "json"),
            output_path=path_obj,
        )

        if parameters.get("graphrag_format", True):
            result["graphrag_metadata"] = {
                "entity_types": ["Patent", "Inventor", "Assignee", "Classification"],
                "relationship_types": ["INVENTED_BY", "ASSIGNED_TO", "CLASSIFIED_AS", "CITES"],
                "ready_for_ingestion": True,
                "suggested_embeddings": ["patent_title", "patent_abstract"],
            }

        return result
    except Exception as e:
        logger.error("Patent dataset building failed: %s", e, exc_info=True)
        return {"status": "error", "error": str(e), "metadata": {}}
