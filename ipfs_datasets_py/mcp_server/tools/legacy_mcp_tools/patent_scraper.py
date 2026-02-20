#!/usr/bin/env python

# DEPRECATED: This legacy module is superseded by
#   ipfs_datasets_py.mcp_server.tools.legal_dataset_tools
# See legacy_mcp_tools/MIGRATION_GUIDE.md for migration instructions.
import warnings
warnings.warn(
    "legacy_mcp_tools.patent_scraper is deprecated. "
    "Use ipfs_datasets_py.mcp_server.tools.legal_dataset_tools instead.",
    DeprecationWarning,
    stacklevel=2,
)

# -*- coding: utf-8 -*-
"""
Patent Scraper for USPTO PatentsView API.

This module provides functions to scrape patent data from the USPTO PatentsView API
and optionally from Google Patents (via web scraping).
"""
from __future__ import annotations

import anyio
import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass, asdict
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

@dataclass
class PatentSearchCriteria:
    """Criteria for searching patents."""
    keywords: Optional[List[str]] = None
    inventor_name: Optional[str] = None
    assignee_name: Optional[str] = None
    patent_number: Optional[str] = None
    application_number: Optional[str] = None
    date_from: Optional[str] = None  # YYYY-MM-DD
    date_to: Optional[str] = None    # YYYY-MM-DD
    cpc_classification: Optional[List[str]] = None  # Cooperative Patent Classification
    ipc_classification: Optional[List[str]] = None  # International Patent Classification
    limit: int = 100
    offset: int = 0

@dataclass
class Patent:
    """Represents a patent document."""
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
    """
    Scraper for USPTO PatentsView API.
    
    The PatentsView API provides access to USPTO patent data without requiring authentication.
    Documentation: https://patentsview.org/apis/purpose
    """
    
    BASE_URL = "https://api.patentsview.org/patents/query"
    
    def __init__(self, rate_limit_delay: float = 1.0):
        """
        Initialize the USPTO scraper.
        
        Args:
            rate_limit_delay: Delay between requests in seconds (default: 1.0)
        """
        self.rate_limit_delay = rate_limit_delay
        self.session = self._create_session()
        self.last_request_time = 0
    
    def _create_session(self) -> requests.Session:
        """Create a requests session with retry logic."""
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session
    
    def _rate_limit(self):
        """Enforce rate limiting."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - elapsed)
        self.last_request_time = time.time()
    
    def _build_query(self, criteria: PatentSearchCriteria) -> Dict[str, Any]:
        """
        Build a PatentsView API query from search criteria.
        
        Args:
            criteria: Search criteria
            
        Returns:
            Query dict for PatentsView API
        """
        query_parts = []
        
        # Add keyword search
        if criteria.keywords:
            keyword_queries = [
                {"_text_any": {"patent_abstract": kw}}
                for kw in criteria.keywords
            ]
            if len(keyword_queries) > 1:
                query_parts.append({"_or": keyword_queries})
            else:
                query_parts.extend(keyword_queries)
        
        # Add inventor search
        if criteria.inventor_name:
            query_parts.append({"inventor_last_name": criteria.inventor_name})
        
        # Add assignee search
        if criteria.assignee_name:
            query_parts.append({"assignee_organization": criteria.assignee_name})
        
        # Add patent number search
        if criteria.patent_number:
            query_parts.append({"patent_number": criteria.patent_number})
        
        # Add date range
        if criteria.date_from or criteria.date_to:
            date_query = {}
            if criteria.date_from:
                date_query["_gte"] = criteria.date_from
            if criteria.date_to:
                date_query["_lte"] = criteria.date_to
            query_parts.append({"patent_date": date_query})
        
        # Add CPC classification
        if criteria.cpc_classification:
            cpc_queries = [
                {"cpc_subgroup_id": cpc}
                for cpc in criteria.cpc_classification
            ]
            if len(cpc_queries) > 1:
                query_parts.append({"_or": cpc_queries})
            else:
                query_parts.extend(cpc_queries)
        
        # Combine all query parts
        if len(query_parts) > 1:
            query = {"_and": query_parts}
        elif len(query_parts) == 1:
            query = query_parts[0]
        else:
            # Default: get recent patents
            query = {"_gte": {"patent_date": "2020-01-01"}}
        
        return query
    
    def search_patents(
        self,
        criteria: PatentSearchCriteria,
        fields: Optional[List[str]] = None
    ) -> List[Patent]:
        """
        Search patents using USPTO PatentsView API.
        
        Args:
            criteria: Search criteria
            fields: List of fields to retrieve (None = default fields)
            
        Returns:
            List of Patent objects
        """
        self._rate_limit()
        
        # Build query
        query = self._build_query(criteria)
        
        # Define fields to retrieve
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
                "cited_patent_number"
            ]
        
        # Build API request
        payload = {
            "q": query,
            "f": fields,
            "o": {
                "per_page": min(criteria.limit, 1000),  # API max is 1000
                "page": (criteria.offset // min(criteria.limit, 1000)) + 1
            }
        }
        
        logger.info(f"Searching USPTO patents with query: {json.dumps(query)}")
        
        try:
            response = self.session.post(
                self.BASE_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            response.raise_for_status()
            
            data = response.json()
            patents_data = data.get("patents", [])
            
            logger.info(f"Retrieved {len(patents_data)} patents from USPTO")
            
            # Convert to Patent objects
            patents = []
            for patent_data in patents_data:
                patents.append(self._parse_patent(patent_data))
            
            return patents
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error searching patents: {e}")
            raise
    
    def _parse_patent(self, data: Dict[str, Any]) -> Patent:
        """
        Parse patent data from PatentsView API response.
        
        Args:
            data: Raw patent data from API
            
        Returns:
            Patent object
        """
        # Extract inventors
        inventors = []
        inventor_last_names = data.get("inventors", [])
        for inv in inventor_last_names:
            if isinstance(inv, dict):
                inventors.append({
                    "first_name": inv.get("inventor_first_name", ""),
                    "last_name": inv.get("inventor_last_name", "")
                })
        
        # Extract assignees
        assignees = []
        assignee_orgs = data.get("assignees", [])
        for org in assignee_orgs:
            if isinstance(org, dict):
                assignees.append({
                    "organization": org.get("assignee_organization", "")
                })
        
        # Extract CPC classifications
        cpc_classifications = []
        cpc_groups = data.get("cpcs", [])
        for cpc in cpc_groups:
            if isinstance(cpc, dict):
                cpc_id = cpc.get("cpc_subgroup_id", "")
                if cpc_id:
                    cpc_classifications.append(cpc_id)
        
        # Extract citations
        citations = []
        cited_patents = data.get("cited_patents", [])
        for cited in cited_patents:
            if isinstance(cited, dict):
                cited_num = cited.get("cited_patent_number", "")
                if cited_num:
                    citations.append(cited_num)
        
        return Patent(
            patent_number=data.get("patent_number", ""),
            patent_title=data.get("patent_title", ""),
            patent_abstract=data.get("patent_abstract", ""),
            patent_date=data.get("patent_date", ""),
            application_number=data.get("app_number", ""),
            application_date=data.get("app_date", ""),
            inventors=inventors if inventors else None,
            assignees=assignees if assignees else None,
            cpc_classifications=cpc_classifications if cpc_classifications else None,
            ipc_classifications=None,  # IPC not in basic fields
            claims=None,  # Claims require separate API call
            description=None,  # Full description requires separate call
            citations=citations if citations else None,
            raw_data=data
        )
    
    async def search_patents_async(
        self,
        criteria: PatentSearchCriteria,
        fields: Optional[List[str]] = None
    ) -> List[Patent]:
        """
        Async version of search_patents.
        
        Args:
            criteria: Search criteria
            fields: List of fields to retrieve
            
        Returns:
            List of Patent objects
        """
        # Run synchronous search in executor using anyio
        return await anyio.to_thread.run_sync(
            self.search_patents,
            criteria,
            fields
        )

class PatentDatasetBuilder:
    """
    Build patent datasets for ETL into GraphRAG.
    """
    
    def __init__(self, scraper: USPTOPatentScraper):
        """
        Initialize the dataset builder.
        
        Args:
            scraper: Patent scraper instance
        """
        self.scraper = scraper
    
    def build_dataset(
        self,
        criteria: PatentSearchCriteria,
        output_format: str = "json",
        output_path: Optional[Path] = None
    ) -> Dict[str, Any]:
        """
        Build a patent dataset.
        
        Args:
            criteria: Search criteria
            output_format: Output format ('json' or 'parquet')
            output_path: Path to save the dataset (optional)
            
        Returns:
            Dataset metadata and statistics
        """
        logger.info(f"Building patent dataset with criteria: {asdict(criteria)}")
        
        # Search patents
        patents = self.scraper.search_patents(criteria)
        
        # Convert to dict format
        patents_data = [asdict(patent) for patent in patents]
        
        # Save dataset if output path provided
        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            if output_format == "json":
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(patents_data, f, indent=2, ensure_ascii=False)
            elif output_format == "parquet":
                try:
                    import pandas as pd
                    df = pd.DataFrame(patents_data)
                    df.to_parquet(output_path, index=False)
                except ImportError:
                    logger.warning("pandas/pyarrow not available, falling back to JSON")
                    output_path = output_path.with_suffix('.json')
                    with open(output_path, 'w', encoding='utf-8') as f:
                        json.dump(patents_data, f, indent=2, ensure_ascii=False)
        
        # Build metadata
        metadata = {
            "dataset_type": "patents",
            "source": "USPTO PatentsView API",
            "created_at": datetime.now().isoformat(),
            "criteria": asdict(criteria),
            "patent_count": len(patents),
            "output_format": output_format,
            "output_path": str(output_path) if output_path else None
        }
        
        logger.info(f"Built patent dataset with {len(patents)} patents")
        
        return {
            "status": "success",
            "metadata": metadata,
            "patents": patents_data
        }
    
    async def build_dataset_async(
        self,
        criteria: PatentSearchCriteria,
        output_format: str = "json",
        output_path: Optional[Path] = None
    ) -> Dict[str, Any]:
        """
        Async version of build_dataset.
        
        Args:
            criteria: Search criteria
            output_format: Output format
            output_path: Path to save dataset
            
        Returns:
            Dataset metadata and statistics
        """
        return await anyio.to_thread.run_sync(
            self.build_dataset,
            criteria,
            output_format,
            output_path
        )

# Convenience functions
def search_patents_by_keyword(
    keywords: List[str],
    limit: int = 100,
    rate_limit_delay: float = 1.0
) -> List[Patent]:
    """
    Search patents by keywords.
    
    Args:
        keywords: List of keywords to search
        limit: Maximum number of results
        rate_limit_delay: Delay between requests
        
    Returns:
        List of Patent objects
    """
    scraper = USPTOPatentScraper(rate_limit_delay=rate_limit_delay)
    criteria = PatentSearchCriteria(keywords=keywords, limit=limit)
    return scraper.search_patents(criteria)

def search_patents_by_inventor(
    inventor_name: str,
    limit: int = 100,
    rate_limit_delay: float = 1.0
) -> List[Patent]:
    """
    Search patents by inventor name.
    
    Args:
        inventor_name: Inventor last name
        limit: Maximum number of results
        rate_limit_delay: Delay between requests
        
    Returns:
        List of Patent objects
    """
    scraper = USPTOPatentScraper(rate_limit_delay=rate_limit_delay)
    criteria = PatentSearchCriteria(inventor_name=inventor_name, limit=limit)
    return scraper.search_patents(criteria)

def search_patents_by_assignee(
    assignee_name: str,
    limit: int = 100,
    rate_limit_delay: float = 1.0
) -> List[Patent]:
    """
    Search patents by assignee/organization.
    
    Args:
        assignee_name: Organization name
        limit: Maximum number of results
        rate_limit_delay: Delay between requests
        
    Returns:
        List of Patent objects
    """
    scraper = USPTOPatentScraper(rate_limit_delay=rate_limit_delay)
    criteria = PatentSearchCriteria(assignee_name=assignee_name, limit=limit)
    return scraper.search_patents(criteria)
