"""
USPTO Patent Scraper Engine.

Canonical business logic for scraping patent data from the USPTO PatentsView API.
This module is the authoritative location for the patent scraper domain classes.

Exposed in ``ipfs_datasets_py.processors.legal_scrapers`` so the same classes can be
used from package imports, CLI tools, and MCP server tools.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import anyio
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


@dataclass
class PatentSearchCriteria:
    """Criteria for searching patents via the USPTO PatentsView API."""

    keywords: Optional[List[str]] = None
    inventor_name: Optional[str] = None
    assignee_name: Optional[str] = None
    patent_number: Optional[str] = None
    application_number: Optional[str] = None
    date_from: Optional[str] = None  # YYYY-MM-DD
    date_to: Optional[str] = None  # YYYY-MM-DD
    cpc_classification: Optional[List[str]] = None
    ipc_classification: Optional[List[str]] = None
    limit: int = 100
    offset: int = 0


@dataclass
class Patent:
    """Represents a single patent document."""

    patent_number: str
    patent_title: str
    patent_abstract: Optional[str] = None
    patent_date: Optional[str] = None
    application_number: Optional[str] = None
    application_date: Optional[str] = None
    inventors: Optional[List[Dict[str, str]]] = None
    assignees: Optional[List[Dict[str, str]]] = None
    cpc_classifications: Optional[List[str]] = None
    ipc_classifications: Optional[List[str]] = None
    claims: Optional[List[str]] = None
    description: Optional[str] = None
    citations: Optional[List[str]] = None
    raw_data: Optional[Dict[str, Any]] = None


class USPTOPatentScraper:
    """Scraper for USPTO PatentsView API.

    The PatentsView API provides access to USPTO patent data without requiring
    authentication.  See https://patentsview.org/apis/purpose for documentation.

    Args:
        rate_limit_delay: Delay between requests in seconds.
    """

    BASE_URL = "https://api.patentsview.org/patents/query"

    def __init__(self, rate_limit_delay: float = 1.0) -> None:
        self.rate_limit_delay = rate_limit_delay
        self.session = self._create_session()
        self.last_request_time: float = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _create_session(self) -> requests.Session:
        """Create a requests session with retry logic."""
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _rate_limit(self) -> None:
        """Enforce rate limiting."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - elapsed)
        self.last_request_time = time.time()

    def _build_query(self, criteria: PatentSearchCriteria) -> Dict[str, Any]:
        """Build a PatentsView API query from search criteria."""
        query_parts: List[Dict[str, Any]] = []

        if criteria.keywords:
            keyword_queries = [
                {"_text_any": {"patent_abstract": kw}} for kw in criteria.keywords
            ]
            if len(keyword_queries) > 1:
                query_parts.append({"_or": keyword_queries})
            else:
                query_parts.extend(keyword_queries)

        if criteria.inventor_name:
            query_parts.append({"inventor_last_name": criteria.inventor_name})

        if criteria.assignee_name:
            query_parts.append({"assignee_organization": criteria.assignee_name})

        if criteria.patent_number:
            query_parts.append({"patent_number": criteria.patent_number})

        if criteria.date_from or criteria.date_to:
            date_query: Dict[str, Any] = {}
            if criteria.date_from:
                date_query["_gte"] = criteria.date_from
            if criteria.date_to:
                date_query["_lte"] = criteria.date_to
            query_parts.append({"patent_date": date_query})

        if criteria.cpc_classification:
            cpc_queries = [
                {"cpc_subgroup_id": cpc} for cpc in criteria.cpc_classification
            ]
            if len(cpc_queries) > 1:
                query_parts.append({"_or": cpc_queries})
            else:
                query_parts.extend(cpc_queries)

        if len(query_parts) > 1:
            return {"_and": query_parts}
        if len(query_parts) == 1:
            return query_parts[0]
        # Default: get recent patents
        return {"_gte": {"patent_date": "2020-01-01"}}

    def _parse_patent(self, data: Dict[str, Any]) -> Patent:
        """Parse patent data from PatentsView API response."""
        inventors = [
            {
                "first_name": inv.get("inventor_first_name", ""),
                "last_name": inv.get("inventor_last_name", ""),
            }
            for inv in data.get("inventors", [])
            if isinstance(inv, dict)
        ]

        assignees = [
            {"organization": org.get("assignee_organization", "")}
            for org in data.get("assignees", [])
            if isinstance(org, dict)
        ]

        cpc_classifications = [
            cpc.get("cpc_subgroup_id", "")
            for cpc in data.get("cpcs", [])
            if isinstance(cpc, dict) and cpc.get("cpc_subgroup_id")
        ]

        citations = [
            cited.get("cited_patent_number", "")
            for cited in data.get("cited_patents", [])
            if isinstance(cited, dict) and cited.get("cited_patent_number")
        ]

        return Patent(
            patent_number=data.get("patent_number", ""),
            patent_title=data.get("patent_title", ""),
            patent_abstract=data.get("patent_abstract", ""),
            patent_date=data.get("patent_date", ""),
            application_number=data.get("app_number", ""),
            application_date=data.get("app_date", ""),
            inventors=inventors or None,
            assignees=assignees or None,
            cpc_classifications=cpc_classifications or None,
            ipc_classifications=None,
            claims=None,
            description=None,
            citations=citations or None,
            raw_data=data,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search_patents(
        self,
        criteria: PatentSearchCriteria,
        fields: Optional[List[str]] = None,
    ) -> List[Patent]:
        """Search patents using the USPTO PatentsView API.

        Args:
            criteria: Search criteria.
            fields: List of fields to retrieve (``None`` uses sensible defaults).

        Returns:
            List of :class:`Patent` objects.

        Raises:
            requests.RequestException: On network error.
        """
        self._rate_limit()

        if fields is None:
            fields = [
                "patent_number",
                "patent_title",
                "patent_abstract",
                "patent_date",
                "app_number",
                "app_date",
                "inventor_last_name",
                "inventor_first_name",
                "assignee_organization",
                "cpc_subgroup_id",
                "cited_patent_number",
            ]

        query = self._build_query(criteria)
        payload = {
            "q": query,
            "f": fields,
            "o": {
                "per_page": min(criteria.limit, 1000),
                "page": (criteria.offset // min(criteria.limit, 1000)) + 1,
            },
        }

        logger.info("Searching USPTO patents with query: %s", json.dumps(query))

        try:
            response = self.session.post(
                self.BASE_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            response.raise_for_status()

            patents_data = response.json().get("patents", [])
            logger.info("Retrieved %d patents from USPTO", len(patents_data))
            return [self._parse_patent(p) for p in patents_data]

        except requests.exceptions.RequestException as exc:
            logger.error("Error searching patents: %s", exc)
            raise

    async def search_patents_async(
        self,
        criteria: PatentSearchCriteria,
        fields: Optional[List[str]] = None,
    ) -> List[Patent]:
        """Async wrapper around :meth:`search_patents`."""
        return await anyio.to_thread.run_sync(self.search_patents, criteria, fields)


class PatentDatasetBuilder:
    """Build patent datasets for ETL into GraphRAG.

    Args:
        scraper: :class:`USPTOPatentScraper` instance.
    """

    def __init__(self, scraper: USPTOPatentScraper) -> None:
        self.scraper = scraper

    def build_dataset(
        self,
        criteria: PatentSearchCriteria,
        output_format: str = "json",
        output_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Build a patent dataset.

        Args:
            criteria: Search criteria.
            output_format: Output format (``"json"`` or ``"parquet"``).
            output_path: Path to save the dataset (optional).

        Returns:
            Dictionary with ``status``, ``metadata``, and ``patents`` keys.
        """
        logger.info("Building patent dataset with criteria: %s", asdict(criteria))

        patents = self.scraper.search_patents(criteria)
        patents_data = [asdict(patent) for patent in patents]

        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            if output_format == "json":
                with open(output_path, "w", encoding="utf-8") as fh:
                    json.dump(patents_data, fh, indent=2, ensure_ascii=False)
            elif output_format == "parquet":
                try:
                    import pandas as pd  # noqa: PLC0415

                    pd.DataFrame(patents_data).to_parquet(output_path, index=False)
                except ImportError:
                    logger.warning("pandas/pyarrow not available, falling back to JSON")
                    output_path = output_path.with_suffix(".json")
                    with open(output_path, "w", encoding="utf-8") as fh:
                        json.dump(patents_data, fh, indent=2, ensure_ascii=False)

        metadata = {
            "dataset_type": "patents",
            "source": "USPTO PatentsView API",
            "created_at": datetime.now().isoformat(),
            "criteria": asdict(criteria),
            "patent_count": len(patents),
            "output_format": output_format,
            "output_path": str(output_path) if output_path else None,
        }

        logger.info("Built patent dataset with %d patents", len(patents))
        return {"status": "success", "metadata": metadata, "patents": patents_data}

    async def build_dataset_async(
        self,
        criteria: PatentSearchCriteria,
        output_format: str = "json",
        output_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Async wrapper around :meth:`build_dataset`."""
        return await anyio.to_thread.run_sync(
            self.build_dataset, criteria, output_format, output_path
        )


# ------------------------------------------------------------------
# Convenience functions
# ------------------------------------------------------------------


def search_patents_by_keyword(
    keywords: List[str],
    limit: int = 100,
    rate_limit_delay: float = 1.0,
) -> List[Patent]:
    """Search patents by keywords.

    Args:
        keywords: List of keywords to search.
        limit: Maximum number of results.
        rate_limit_delay: Delay between requests.

    Returns:
        List of :class:`Patent` objects.
    """
    scraper = USPTOPatentScraper(rate_limit_delay=rate_limit_delay)
    return scraper.search_patents(PatentSearchCriteria(keywords=keywords, limit=limit))


def search_patents_by_inventor(
    inventor_name: str,
    limit: int = 100,
    rate_limit_delay: float = 1.0,
) -> List[Patent]:
    """Search patents by inventor name.

    Args:
        inventor_name: Inventor last name.
        limit: Maximum number of results.
        rate_limit_delay: Delay between requests.

    Returns:
        List of :class:`Patent` objects.
    """
    scraper = USPTOPatentScraper(rate_limit_delay=rate_limit_delay)
    return scraper.search_patents(
        PatentSearchCriteria(inventor_name=inventor_name, limit=limit)
    )


def search_patents_by_assignee(
    assignee_name: str,
    limit: int = 100,
    rate_limit_delay: float = 1.0,
) -> List[Patent]:
    """Search patents by assignee/organization.

    Args:
        assignee_name: Organization name.
        limit: Maximum number of results.
        rate_limit_delay: Delay between requests.

    Returns:
        List of :class:`Patent` objects.
    """
    scraper = USPTOPatentScraper(rate_limit_delay=rate_limit_delay)
    return scraper.search_patents(
        PatentSearchCriteria(assignee_name=assignee_name, limit=limit)
    )
