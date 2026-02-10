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
        try:
            from .patent_scraper import (
                USPTOPatentScraper,
                PatentSearchCriteria,
                PatentDatasetBuilder
            )
            
            # Build search criteria
            criteria = PatentSearchCriteria(
                keywords=parameters.get('keywords'),
                inventor_name=parameters.get('inventor_name'),
                assignee_name=parameters.get('assignee_name'),
                patent_number=parameters.get('patent_number'),
                date_from=parameters.get('date_from'),
                date_to=parameters.get('date_to'),
                cpc_classification=parameters.get('cpc_classification'),
                limit=parameters.get('limit', 100),
                offset=parameters.get('offset', 0)
            )
            
            # Initialize scraper
            scraper = USPTOPatentScraper(
                rate_limit_delay=parameters.get('rate_limit_delay', 1.0)
            )
            
            # Build dataset
            builder = PatentDatasetBuilder(scraper)
            
            output_path = parameters.get('output_path')
            if output_path:
                output_path = Path(output_path)
            
            result = await builder.build_dataset_async(
                criteria=criteria,
                output_format=parameters.get('output_format', 'json'),
                output_path=output_path
            )
            
            return result
            
        except Exception as e:
            logger.error(f"USPTO patent scraping failed: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
                "patents": [],
                "metadata": {}
            }


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
        try:
            from .patent_scraper import search_patents_by_keyword
            
            # Run search in executor
            patents = await anyio.to_thread.run_sync(
                search_patents_by_keyword,
                parameters['keywords'],
                parameters.get('limit', 100),
                parameters.get('rate_limit_delay', 1.0)
            )
            
            # Convert to dict
            from dataclasses import asdict
            patents_data = [asdict(p) for p in patents]
            
            return {
                "status": "success",
                "patents": patents_data,
                "count": len(patents_data),
                "query": {
                    "keywords": parameters['keywords'],
                    "limit": parameters.get('limit', 100)
                }
            }
            
        except Exception as e:
            logger.error(f"Patent keyword search failed: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
                "patents": [],
                "count": 0
            }


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
        try:
            from .patent_scraper import search_patents_by_inventor
            
            # Run search in executor
            patents = await anyio.to_thread.run_sync(
                search_patents_by_inventor,
                parameters['inventor_name'],
                parameters.get('limit', 100),
                parameters.get('rate_limit_delay', 1.0)
            )
            
            # Convert to dict
            from dataclasses import asdict
            patents_data = [asdict(p) for p in patents]
            
            return {
                "status": "success",
                "patents": patents_data,
                "count": len(patents_data),
                "query": {
                    "inventor_name": parameters['inventor_name'],
                    "limit": parameters.get('limit', 100)
                }
            }
            
        except Exception as e:
            logger.error(f"Patent inventor search failed: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
                "patents": [],
                "count": 0
            }


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
        try:
            from .patent_scraper import search_patents_by_assignee
            
            # Run search in executor
            patents = await anyio.to_thread.run_sync(
                search_patents_by_assignee,
                parameters['assignee_name'],
                parameters.get('limit', 100),
                parameters.get('rate_limit_delay', 1.0)
            )
            
            # Convert to dict
            from dataclasses import asdict
            patents_data = [asdict(p) for p in patents]
            
            return {
                "status": "success",
                "patents": patents_data,
                "count": len(patents_data),
                "query": {
                    "assignee_name": parameters['assignee_name'],
                    "limit": parameters.get('limit', 100)
                }
            }
            
        except Exception as e:
            logger.error(f"Patent assignee search failed: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
                "patents": [],
                "count": 0
            }


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
        try:
            from .patent_scraper import (
                USPTOPatentScraper,
                PatentSearchCriteria,
                PatentDatasetBuilder
            )
            
            # Parse search criteria
            search_params = parameters.get('search_criteria', {})
            criteria = PatentSearchCriteria(
                keywords=search_params.get('keywords'),
                inventor_name=search_params.get('inventor_name'),
                assignee_name=search_params.get('assignee_name'),
                patent_number=search_params.get('patent_number'),
                date_from=search_params.get('date_from'),
                date_to=search_params.get('date_to'),
                cpc_classification=search_params.get('cpc_classification'),
                limit=search_params.get('limit', 100),
                offset=search_params.get('offset', 0)
            )
            
            # Initialize scraper and builder
            scraper = USPTOPatentScraper(rate_limit_delay=1.0)
            builder = PatentDatasetBuilder(scraper)
            
            # Build dataset
            output_path = parameters.get('output_path')
            if output_path:
                output_path = Path(output_path)
            
            result = await builder.build_dataset_async(
                criteria=criteria,
                output_format=parameters.get('output_format', 'json'),
                output_path=output_path
            )
            
            # Add GraphRAG-specific metadata if requested
            if parameters.get('graphrag_format', True):
                result['graphrag_metadata'] = {
                    "entity_types": ["Patent", "Inventor", "Assignee", "Classification"],
                    "relationship_types": ["INVENTED_BY", "ASSIGNED_TO", "CLASSIFIED_AS", "CITES"],
                    "ready_for_ingestion": True,
                    "suggested_embeddings": ["patent_title", "patent_abstract"]
                }
            
            return result
            
        except Exception as e:
            logger.error(f"Patent dataset building failed: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
                "metadata": {}
            }


# List of all patent dataset MCP tools
PATENT_DATASET_MCP_TOOLS = [
    ScrapeUSPTOPatentsTool(),
    SearchPatentsByKeywordTool(),
    SearchPatentsByInventorTool(),
    SearchPatentsByAssigneeTool(),
    BuildPatentDatasetTool()
]
