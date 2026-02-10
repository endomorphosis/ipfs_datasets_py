#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Patent Dataset MCP Tools for Model Context Protocol.

This module exposes patent dataset scraping tools as MCP tools that can be
discovered and called via the MCP protocol.

Tools included:
- scrape_uspto_patents: Scrape patents from USPTO PatentsView API
- search_patents_by_keyword: Search patents by keywords
- search_patents_by_inventor: Search patents by inventor name
- search_patents_by_assignee: Search patents by assignee/organization
- build_patent_dataset: Build a complete patent dataset for GraphRAG ingestion
"""
from __future__ import annotations

import anyio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.mcp_server.tool_registry import ClaudeMCPTool

logger = logging.getLogger(__name__)


class ScrapeUSPTOPatentsTool(ClaudeMCPTool):
    """
    MCP Tool for scraping USPTO patents via PatentsView API.
    
    This tool provides access to USPTO patent data including patent numbers,
    titles, abstracts, inventors, assignees, classifications, and citations.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "scrape_uspto_patents"
        self.description = "Scrape patents from USPTO PatentsView API with advanced search capabilities"
        self.category = "patent_datasets"
        self.tags = ["patents", "uspto", "legal", "dataset", "scraping", "intellectual_property"]
        self.version = "1.0.0"
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Keywords to search in patent abstracts and titles",
                    "default": None
                },
                "inventor_name": {
                    "type": "string",
                    "description": "Inventor last name to search for",
                    "default": None
                },
                "assignee_name": {
                    "type": "string",
                    "description": "Assignee/organization name to search for",
                    "default": None
                },
                "patent_number": {
                    "type": "string",
                    "description": "Specific patent number to retrieve",
                    "default": None
                },
                "date_from": {
                    "type": "string",
                    "description": "Start date for patent date range (YYYY-MM-DD format)",
                    "default": None
                },
                "date_to": {
                    "type": "string",
                    "description": "End date for patent date range (YYYY-MM-DD format)",
                    "default": None
                },
                "cpc_classification": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Cooperative Patent Classification codes (e.g., ['G06F', 'H04L'])",
                    "default": None
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of patents to retrieve (max 1000)",
                    "default": 100
                },
                "offset": {
                    "type": "integer",
                    "description": "Offset for pagination",
                    "default": 0
                },
                "rate_limit_delay": {
                    "type": "number",
                    "description": "Delay between API requests in seconds",
                    "default": 1.0
                },
                "output_format": {
                    "type": "string",
                    "description": "Output format: 'json' or 'parquet'",
                    "default": "json"
                },
                "output_path": {
                    "type": "string",
                    "description": "Path to save the dataset (optional)",
                    "default": None
                }
            },
            "required": []
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute USPTO patent scraping.
        
        Args:
            parameters: Scraping configuration parameters
            
        Returns:
            Dictionary containing scraped patents and metadata
        """
        from ipfs_datasets_py.processors.patent_dataset_api import (
            scrape_uspto_patents_from_parameters,
        )

        return await scrape_uspto_patents_from_parameters(parameters)


class SearchPatentsByKeywordTool(ClaudeMCPTool):
    """
    MCP Tool for searching patents by keywords.
    
    Simple keyword-based patent search interface.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "search_patents_by_keyword"
        self.description = "Search USPTO patents by keywords"
        self.category = "patent_datasets"
        self.tags = ["patents", "search", "keywords"]
        self.version = "1.0.0"
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Keywords to search for in patents"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results",
                    "default": 100
                },
                "rate_limit_delay": {
                    "type": "number",
                    "description": "Delay between requests in seconds",
                    "default": 1.0
                }
            },
            "required": ["keywords"]
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute keyword-based patent search.
        
        Args:
            parameters: Search parameters
            
        Returns:
            Dictionary containing search results
        """
        from ipfs_datasets_py.processors.patent_dataset_api import (
            search_patents_by_keyword_from_parameters,
        )

        return await search_patents_by_keyword_from_parameters(parameters)


class SearchPatentsByInventorTool(ClaudeMCPTool):
    """
    MCP Tool for searching patents by inventor name.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "search_patents_by_inventor"
        self.description = "Search USPTO patents by inventor name"
        self.category = "patent_datasets"
        self.tags = ["patents", "search", "inventor"]
        self.version = "1.0.0"
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "inventor_name": {
                    "type": "string",
                    "description": "Inventor last name to search for"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results",
                    "default": 100
                },
                "rate_limit_delay": {
                    "type": "number",
                    "description": "Delay between requests in seconds",
                    "default": 1.0
                }
            },
            "required": ["inventor_name"]
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute inventor-based patent search.
        
        Args:
            parameters: Search parameters
            
        Returns:
            Dictionary containing search results
        """
        from ipfs_datasets_py.processors.patent_dataset_api import (
            search_patents_by_inventor_from_parameters,
        )

        return await search_patents_by_inventor_from_parameters(parameters)


class SearchPatentsByAssigneeTool(ClaudeMCPTool):
    """
    MCP Tool for searching patents by assignee/organization.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "search_patents_by_assignee"
        self.description = "Search USPTO patents by assignee/organization name"
        self.category = "patent_datasets"
        self.tags = ["patents", "search", "assignee", "organization"]
        self.version = "1.0.0"
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "assignee_name": {
                    "type": "string",
                    "description": "Assignee/organization name to search for"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results",
                    "default": 100
                },
                "rate_limit_delay": {
                    "type": "number",
                    "description": "Delay between requests in seconds",
                    "default": 1.0
                }
            },
            "required": ["assignee_name"]
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute assignee-based patent search.
        
        Args:
            parameters: Search parameters
            
        Returns:
            Dictionary containing search results
        """
        from ipfs_datasets_py.processors.patent_dataset_api import (
            search_patents_by_assignee_from_parameters,
        )

        return await search_patents_by_assignee_from_parameters(parameters)


class BuildPatentDatasetTool(ClaudeMCPTool):
    """
    MCP Tool for building patent datasets for GraphRAG ingestion.
    
    This tool creates structured patent datasets optimized for
    GraphRAG knowledge graph construction.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "build_patent_dataset"
        self.description = "Build structured patent datasets for GraphRAG knowledge graph ingestion"
        self.category = "patent_datasets"
        self.tags = ["patents", "dataset", "graphrag", "knowledge_graph"]
        self.version = "1.0.0"
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "search_criteria": {
                    "type": "object",
                    "description": "Search criteria for patents (keywords, inventor, assignee, dates, etc.)",
                    "default": {}
                },
                "output_format": {
                    "type": "string",
                    "description": "Output format: 'json' or 'parquet'",
                    "default": "json"
                },
                "output_path": {
                    "type": "string",
                    "description": "Path to save the dataset",
                    "default": None
                },
                "include_citations": {
                    "type": "boolean",
                    "description": "Include patent citation graph data",
                    "default": True
                },
                "include_classifications": {
                    "type": "boolean",
                    "description": "Include CPC/IPC classification data",
                    "default": True
                },
                "graphrag_format": {
                    "type": "boolean",
                    "description": "Format output for direct GraphRAG ingestion",
                    "default": True
                }
            },
            "required": []
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build patent dataset for GraphRAG.
        
        Args:
            parameters: Dataset build parameters
            
        Returns:
            Dictionary containing dataset information and metadata
        """
        from ipfs_datasets_py.processors.patent_dataset_api import (
            build_patent_dataset_from_parameters,
        )

        return await build_patent_dataset_from_parameters(parameters)


# List of all patent dataset MCP tools
PATENT_DATASET_MCP_TOOLS = [
    ScrapeUSPTOPatentsTool(),
    SearchPatentsByKeywordTool(),
    SearchPatentsByInventorTool(),
    SearchPatentsByAssigneeTool(),
    BuildPatentDatasetTool()
]
