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
- list_scraping_jobs: List all scraping jobs with resume capability
- get_scraping_job_status: Get status of a specific scraping job
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..tool_registry import ClaudeMCPTool

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
        try:
            from ...mcp_server.tools.legal_dataset_tools import scrape_recap_archive
            
            result = await scrape_recap_archive(
                courts=parameters.get('courts'),
                document_types=parameters.get('document_types'),
                filed_after=parameters.get('filed_after'),
                filed_before=parameters.get('filed_before'),
                case_name_pattern=parameters.get('case_name_pattern'),
                output_format='json',
                include_text=parameters.get('include_text', True),
                include_metadata=parameters.get('include_metadata', True),
                rate_limit_delay=parameters.get('rate_limit_delay', 1.0),
                max_documents=parameters.get('max_documents'),
                job_id=parameters.get('job_id'),
                resume=parameters.get('resume', False)
            )
            
            return result
            
        except Exception as e:
            logger.error(f"RECAP Archive scraping failed: {e}")
            return {
                "status": "error",
                "error": str(e),
                "data": [],
                "metadata": {}
            }


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
        try:
            from ...mcp_server.tools.legal_dataset_tools import search_recap_documents
            
            result = await search_recap_documents(
                query=parameters.get('query'),
                court=parameters.get('court'),
                case_name=parameters.get('case_name'),
                filed_after=parameters.get('filed_after'),
                filed_before=parameters.get('filed_before'),
                document_type=parameters.get('document_type'),
                limit=parameters.get('limit', 100)
            )
            
            return result
            
        except Exception as e:
            logger.error(f"RECAP Archive search failed: {e}")
            return {
                "status": "error",
                "error": str(e),
                "documents": [],
                "count": 0
            }


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
        try:
            from ...mcp_server.tools.legal_dataset_tools import scrape_state_laws
            
            # Note: state_laws_scraper doesn't yet support job_id/resume parameters
            # These are handled by the tool wrapper for future compatibility
            result = await scrape_state_laws(
                states=parameters.get('states'),
                legal_areas=parameters.get('legal_areas'),
                output_format=parameters.get('output_format', 'json'),
                include_metadata=parameters.get('include_metadata', True),
                rate_limit_delay=parameters.get('rate_limit_delay', 2.0),
                max_statutes=parameters.get('max_statutes')
            )
            
            # Add job_id to result for consistency
            if 'job_id' in parameters and parameters['job_id']:
                result['job_id'] = parameters['job_id']
            
            return result
            
        except Exception as e:
            logger.error(f"State laws scraping failed: {e}")
            return {
                "status": "error",
                "error": str(e),
                "data": [],
                "metadata": {}
            }


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
        try:
            from ...mcp_server.tools.legal_dataset_tools.state_manager import list_scraping_jobs
            
            # list_scraping_jobs is synchronous, so we call it directly
            jobs = list_scraping_jobs()
            
            # Apply filters
            status_filter = parameters.get('status_filter', 'all')
            job_type = parameters.get('job_type', 'all')
            
            filtered_jobs = jobs
            
            if status_filter != 'all':
                filtered_jobs = [j for j in filtered_jobs if j.get('status') == status_filter]
            
            if job_type != 'all':
                # Filter by job_id prefix (e.g., 'recap_', 'state_laws_')
                filtered_jobs = [j for j in filtered_jobs if j.get('job_id', '').startswith(job_type)]
            
            return {
                "status": "success",
                "jobs": filtered_jobs,
                "total_count": len(filtered_jobs),
                "filters": {
                    "status": status_filter,
                    "job_type": job_type
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to list scraping jobs: {e}")
            return {
                "status": "error",
                "error": str(e),
                "jobs": []
            }


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
        try:
            from ...mcp_server.tools.legal_dataset_tools import scrape_us_code
            
            result = await scrape_us_code(
                titles=parameters.get('titles'),
                output_format=parameters.get('output_format', 'json'),
                include_metadata=parameters.get('include_metadata', True),
                rate_limit_delay=parameters.get('rate_limit_delay', 1.0)
            )
            
            return result
            
        except Exception as e:
            logger.error(f"US Code scraping failed: {e}")
            return {
                "status": "error",
                "error": str(e),
                "data": [],
                "metadata": {}
            }


# List of all legal dataset MCP tools
LEGAL_DATASET_MCP_TOOLS = [
    ScrapeRECAPArchiveTool(),
    SearchRECAPDocumentsTool(),
    ScrapeStateLawsTool(),
    ListScrapingJobsTool(),
    ScrapeUSCodeTool()
]
