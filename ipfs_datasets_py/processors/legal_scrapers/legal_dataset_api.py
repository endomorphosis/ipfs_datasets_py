"""MCP/CLI-friendly APIs for legal dataset scraping.

Core scraping implementations live in the individual scraper modules. This file
provides parameter-driven helper functions so thin wrappers (MCP tools, CLI
commands, SDK calls) can share the same orchestration, defaults, and error
shapes.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

import anyio

logger = logging.getLogger(__name__)


async def scrape_recap_archive_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    try:
        from .recap_archive_scraper import scrape_recap_archive

        return await scrape_recap_archive(
            courts=parameters.get("courts"),
            document_types=parameters.get("document_types"),
            filed_after=parameters.get("filed_after"),
            filed_before=parameters.get("filed_before"),
            case_name_pattern=parameters.get("case_name_pattern"),
            output_format="json",
            include_text=parameters.get("include_text", True),
            include_metadata=parameters.get("include_metadata", True),
            rate_limit_delay=parameters.get("rate_limit_delay", 1.0),
            max_documents=parameters.get("max_documents"),
            job_id=parameters.get("job_id"),
            resume=parameters.get("resume", False),
        )

    except Exception as e:
        logger.error("RECAP Archive scraping failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "data": [],
            "metadata": {},
        }


async def search_recap_documents_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    try:
        from .recap_archive_scraper import search_recap_documents

        return await search_recap_documents(
            query=parameters.get("query"),
            court=parameters.get("court"),
            case_name=parameters.get("case_name"),
            filed_after=parameters.get("filed_after"),
            filed_before=parameters.get("filed_before"),
            document_type=parameters.get("document_type"),
            limit=parameters.get("limit", 100),
        )

    except Exception as e:
        logger.error("RECAP Archive search failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "documents": [],
            "count": 0,
        }


async def scrape_state_laws_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    try:
        from .state_laws_scraper import scrape_state_laws

        result = await scrape_state_laws(
            states=parameters.get("states"),
            legal_areas=parameters.get("legal_areas"),
            output_format=parameters.get("output_format", "json"),
            include_metadata=parameters.get("include_metadata", True),
            rate_limit_delay=parameters.get("rate_limit_delay", 2.0),
            max_statutes=parameters.get("max_statutes"),
        )

        # For forward compatibility with resumable orchestration, include job_id when provided.
        job_id = parameters.get("job_id")
        if job_id:
            result["job_id"] = job_id

        return result

    except Exception as e:
        logger.error("State laws scraping failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "data": [],
            "metadata": {},
        }


async def list_scraping_jobs_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    try:
        from .scraping_state import list_scraping_jobs

        jobs = await anyio.to_thread.run_sync(list_scraping_jobs)

        status_filter = parameters.get("status_filter", "all")
        job_type = parameters.get("job_type", "all")

        filtered_jobs = jobs
        if status_filter != "all":
            filtered_jobs = [j for j in filtered_jobs if j.get("status") == status_filter]

        if job_type != "all":
            filtered_jobs = [
                j for j in filtered_jobs if str(j.get("job_id", "")).startswith(job_type)
            ]

        return {
            "status": "success",
            "jobs": filtered_jobs,
            "total_count": len(filtered_jobs),
            "filters": {"status": status_filter, "job_type": job_type},
        }

    except Exception as e:
        logger.error("Failed to list scraping jobs: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "jobs": [],
        }


async def scrape_us_code_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    try:
        from .us_code_scraper import scrape_us_code

        return await scrape_us_code(
            titles=parameters.get("titles"),
            output_format=parameters.get("output_format", "json"),
            include_metadata=parameters.get("include_metadata", True),
            rate_limit_delay=parameters.get("rate_limit_delay", 1.0),
        )

    except Exception as e:
        logger.error("US Code scraping failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "data": [],
            "metadata": {},
        }


async def scrape_municipal_codes_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    try:
        from .municipal_codes_api import initialize_municipal_codes_job

        return initialize_municipal_codes_job(parameters, tool_version=tool_version)

    except Exception as e:
        logger.error("Municipal code scraping failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "data": [],
            "metadata": {},
        }
