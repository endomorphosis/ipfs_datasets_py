#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Legal Dataset MCP Tools for Model Context Protocol.

This module exposes legal dataset scraping tools (RECAP Archive, State Laws, US Code, etc.)
as MCP tools that can be discovered and called via the MCP protocol.

Tools included:
- scrape_recap_archive: Scrape federal court documents from RECAP Archive
- search_recap_documents: Search RECAP Archive for specific documents
- scrape_state_laws: Scrape state legislation and statutes
- scrape_us_code: Scrape United States Code
- scrape_federal_register: Scrape Federal Register documents
- scrape_municipal_codes: Scrape municipal codes using scrape_the_law_mk3
- list_scraping_jobs: List all scraping jobs with resume capability
- get_scraping_job_status: Get status of a specific scraping job
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.mcp_server.tool_registry import ClaudeMCPTool

logger = logging.getLogger(__name__)


class ScrapeRECAPArchiveTool(ClaudeMCPTool):
    """
    MCP Tool for scraping RECAP Archive federal court documents.
    
    This tool scrapes the RECAP Archive from courtlistener.com to build
    datasets of federal court documents including dockets, opinions, and filings.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "scrape_recap_archive"
        self.description = "Scrape federal court documents from RECAP Archive (courtlistener.com) with resume capability"
        self.category = "legal_datasets"
        self.tags = ["legal", "recap", "courts", "dataset", "scraping"]
        self.version = "1.0.0"
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "courts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of court identifiers (e.g., ['ca9', 'nysd']). Use ['all'] for all courts.",
                    "default": None
                },
                "document_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Document types to scrape (e.g., ['opinion', 'complaint', 'docket'])",
                    "default": ["opinion"]
                },
                "filed_after": {
                    "type": "string",
                    "description": "Only include documents filed after this date (YYYY-MM-DD format)",
                    "default": None
                },
                "filed_before": {
                    "type": "string",
                    "description": "Only include documents filed before this date (YYYY-MM-DD format)",
                    "default": None
                },
                "case_name_pattern": {
                    "type": "string",
                    "description": "Pattern to match case names (e.g., 'Smith v.')",
                    "default": None
                },
                "include_text": {
                    "type": "boolean",
                    "description": "Include full document text (increases data size)",
                    "default": True
                },
                "include_metadata": {
                    "type": "boolean",
                    "description": "Include full document metadata",
                    "default": True
                },
                "rate_limit_delay": {
                    "type": "number",
                    "description": "Delay between requests in seconds",
                    "default": 1.0
                },
                "max_documents": {
                    "type": "integer",
                    "description": "Maximum number of documents to scrape",
                    "default": None
                },
                "job_id": {
                    "type": "string",
                    "description": "Job identifier for resume capability (auto-generated if not provided)",
                    "default": None
                },
                "resume": {
                    "type": "boolean",
                    "description": "Resume from previous scraping state if job_id is provided",
                    "default": False
                }
            },
            "required": []
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute RECAP Archive scraping.
        
        Args:
            parameters: Scraping configuration parameters
            
        Returns:
            Dictionary containing scraped documents, metadata, and job information
        """
        from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
            scrape_recap_archive_from_parameters,
        )

        return await scrape_recap_archive_from_parameters(parameters, tool_version=self.version)


class SearchRECAPDocumentsTool(ClaudeMCPTool):
    """
    MCP Tool for searching RECAP Archive documents.
    
    Search the RECAP Archive for specific court documents using various filters.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "search_recap_documents"
        self.description = "Search RECAP Archive for specific court documents"
        self.category = "legal_datasets"
        self.tags = ["legal", "recap", "search", "courts"]
        self.version = "1.0.0"
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Text search query",
                    "default": None
                },
                "court": {
                    "type": "string",
                    "description": "Court identifier (e.g., 'ca9' for 9th Circuit)",
                    "default": None
                },
                "case_name": {
                    "type": "string",
                    "description": "Case name to search for",
                    "default": None
                },
                "filed_after": {
                    "type": "string",
                    "description": "Date filed after (YYYY-MM-DD format)",
                    "default": None
                },
                "filed_before": {
                    "type": "string",
                    "description": "Date filed before (YYYY-MM-DD format)",
                    "default": None
                },
                "document_type": {
                    "type": "string",
                    "description": "Type of document (e.g., 'opinion', 'docket', 'complaint')",
                    "default": None
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results",
                    "default": 100
                }
            },
            "required": []
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute RECAP Archive search.
        
        Args:
            parameters: Search parameters
            
        Returns:
            Dictionary containing search results
        """
        from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
            search_recap_documents_from_parameters,
        )

        return await search_recap_documents_from_parameters(parameters, tool_version=self.version)


class ScrapeStateLawsTool(ClaudeMCPTool):
    """
    MCP Tool for scraping state legislation and statutes.
    
    Scrape state laws from official state legislative websites with support
    for multiple states and legal areas.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "scrape_state_laws"
        self.description = "Scrape state legislation and statutes from official state sources"
        self.category = "legal_datasets"
        self.tags = ["legal", "state_laws", "legislation", "dataset", "scraping"]
        self.version = "1.0.0"
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "states": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of state codes (e.g., ['CA', 'NY', 'TX']). Use ['all'] for all states.",
                    "default": None
                },
                "legal_areas": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Legal areas to scrape (e.g., ['civil', 'criminal', 'family'])",
                    "default": None
                },
                "output_format": {
                    "type": "string",
                    "description": "Output format: 'json' or 'parquet'",
                    "default": "json"
                },
                "include_metadata": {
                    "type": "boolean",
                    "description": "Include statute metadata",
                    "default": True
                },
                "rate_limit_delay": {
                    "type": "number",
                    "description": "Delay between requests in seconds",
                    "default": 2.0
                },
                "max_statutes": {
                    "type": "integer",
                    "description": "Maximum number of statutes to scrape per state",
                    "default": None
                },
                "job_id": {
                    "type": "string",
                    "description": "Job identifier for resume capability",
                    "default": None
                },
                "resume": {
                    "type": "boolean",
                    "description": "Resume from previous scraping state",
                    "default": False
                }
            },
            "required": []
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute state laws scraping.
        
        Args:
            parameters: Scraping configuration parameters
            
        Returns:
            Dictionary containing scraped statutes and metadata
        """
        from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
            scrape_state_laws_from_parameters,
        )

        return await scrape_state_laws_from_parameters(parameters, tool_version=self.version)


class ListScrapingJobsTool(ClaudeMCPTool):
    """
    MCP Tool for listing all scraping jobs.
    
    List all scraping jobs with their status, allowing users to identify
    jobs that can be resumed.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "list_scraping_jobs"
        self.description = "List all scraping jobs with status and resume capability"
        self.category = "legal_datasets"
        self.tags = ["legal", "jobs", "management"]
        self.version = "1.0.0"
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "status_filter": {
                    "type": "string",
                    "description": "Filter by status: 'running', 'completed', 'failed', or 'all'",
                    "default": "all"
                },
                "job_type": {
                    "type": "string",
                    "description": "Filter by job type: 'recap', 'state_laws', 'us_code', or 'all'",
                    "default": "all"
                }
            },
            "required": []
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        List scraping jobs.
        
        Args:
            parameters: Filter parameters
            
        Returns:
            Dictionary containing list of jobs with their status
        """
        from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
            list_scraping_jobs_from_parameters,
        )

        return await list_scraping_jobs_from_parameters(parameters, tool_version=self.version)


class ScrapeUSCodeTool(ClaudeMCPTool):
    """
    MCP Tool for scraping United States Code.
    
    Scrape federal statutes from the United States Code.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "scrape_us_code"
        self.description = "Scrape United States Code federal statutes"
        self.category = "legal_datasets"
        self.tags = ["legal", "us_code", "federal", "dataset", "scraping"]
        self.version = "1.0.0"
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "titles": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "List of USC titles to scrape (e.g., [17, 35] for Copyright and Patents)",
                    "default": None
                },
                "output_format": {
                    "type": "string",
                    "description": "Output format: 'json' or 'parquet'",
                    "default": "json"
                },
                "include_metadata": {
                    "type": "boolean",
                    "description": "Include section metadata",
                    "default": True
                },
                "rate_limit_delay": {
                    "type": "number",
                    "description": "Delay between requests in seconds",
                    "default": 1.0
                }
            },
            "required": []
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute US Code scraping.
        
        Args:
            parameters: Scraping configuration parameters
            
        Returns:
            Dictionary containing scraped code sections and metadata
        """
        from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
            scrape_us_code_from_parameters,
        )

        return await scrape_us_code_from_parameters(parameters, tool_version=self.version)


class ScrapeMunicipalCodesTool(ClaudeMCPTool):
    """
    MCP Tool for scraping US municipal codes using scrape_the_law_mk3.
    
    This tool provides access to the scrape_the_law_mk3 system which scrapes
    municipal legal codes from US cities and counties. It supports various
    legal code providers including LexisNexis, Municode, American Legal,
    and General Code.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "scrape_municipal_codes"
        self.description = "Scrape municipal legal codes from US cities and counties using scrape_the_law_mk3"
        self.category = "legal_datasets"
        self.tags = ["legal", "municipal", "codes", "cities", "counties", "dataset", "scraping"]
        self.version = "1.0.0"
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "jurisdiction": {
                    "type": "string",
                    "description": "Jurisdiction to scrape (e.g., 'New York, NY', 'Los Angeles, CA')",
                    "default": None
                },
                "jurisdictions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of jurisdictions to scrape (e.g., ['New York, NY', 'Los Angeles, CA']). Use ['all'] for all jurisdictions.",
                    "default": None
                },
                "provider": {
                    "type": "string",
                    "description": "Legal code provider: 'municode', 'american_legal', 'general_code', 'lexisnexis', or 'auto' to detect",
                    "default": "auto"
                },
                "output_format": {
                    "type": "string",
                    "description": "Output format: 'json', 'parquet', or 'sql'",
                    "default": "json"
                },
                "include_metadata": {
                    "type": "boolean",
                    "description": "Include full metadata (citation info, version history, etc.)",
                    "default": True
                },
                "include_text": {
                    "type": "boolean",
                    "description": "Include full legal text (increases data size)",
                    "default": True
                },
                "rate_limit_delay": {
                    "type": "number",
                    "description": "Delay between requests in seconds",
                    "default": 2.0
                },
                "max_sections": {
                    "type": "integer",
                    "description": "Maximum number of code sections to scrape per jurisdiction",
                    "default": None
                },
                "scraper_type": {
                    "type": "string",
                    "description": "Scraper backend to use: 'playwright' (async) or 'selenium' (sync)",
                    "default": "playwright"
                },
                "fallback_methods": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Fallback scraping methods: 'common_crawl', 'wayback_machine', 'archive_is', 'autoscraper', 'ipwb', 'playwright'. Order determines priority.",
                    "default": ["wayback_machine", "archive_is", "common_crawl", "ipwb", "autoscraper", "playwright"]
                },
                "enable_fallbacks": {
                    "type": "boolean",
                    "description": "Enable fallback methods if primary scraping fails",
                    "default": True
                },
                "job_id": {
                    "type": "string",
                    "description": "Job identifier for resume capability (auto-generated if not provided)",
                    "default": None
                },
                "resume": {
                    "type": "boolean",
                    "description": "Resume from previous scraping state if job_id is provided",
                    "default": False
                }
            },
            "required": []
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute municipal code scraping using scrape_the_law_mk3.
        
        Args:
            parameters: Scraping configuration parameters
            
        Returns:
            Dictionary containing scraped municipal codes, metadata, and job information
        """
        from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
            scrape_municipal_codes_from_parameters,
        )

        return await scrape_municipal_codes_from_parameters(parameters, tool_version=self.version)


# Import patent tools
try:
    from .patent_dataset_mcp_tools import PATENT_DATASET_MCP_TOOLS
    _patent_tools_available = True
except ImportError:
    _patent_tools_available = False
    PATENT_DATASET_MCP_TOOLS = []

# List of all legal dataset MCP tools
LEGAL_DATASET_MCP_TOOLS = [
    ScrapeRECAPArchiveTool(),
    SearchRECAPDocumentsTool(),
    ScrapeStateLawsTool(),
    ListScrapingJobsTool(),
    ScrapeUSCodeTool(),
    ScrapeMunicipalCodesTool()
]

# Add patent tools if available
if _patent_tools_available:
    LEGAL_DATASET_MCP_TOOLS.extend(PATENT_DATASET_MCP_TOOLS)
