#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Legal Web Archive Search MCP Tools for Model Context Protocol.

This module exposes the unified Legal Web Archive Search system as MCP tools,
combining natural language legal search with web archiving capabilities.

Tools included:
- legal_web_archive_search: Unified search across current + archived content
- legal_search_archives_only: Search only archived legal documents
- legal_archive_results: Archive specific legal search results
- legal_get_archive_stats: Get archive statistics
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.mcp_server.tool_registry import ClaudeMCPTool

logger = logging.getLogger(__name__)


class LegalWebArchiveSearchTool(ClaudeMCPTool):
    """
    MCP Tool for unified legal search with web archive integration.
    
    This tool searches both current legal content (via Brave Search) and
    archived legal documents (via Common Crawl), with optional automatic
    archiving of important .gov results.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "legal_web_archive_search"
        self.description = "Unified legal search across current web + archives with optional result archiving"
        self.category = "legal_datasets"
        self.tags = ["legal", "search", "archive", "brave", "common-crawl", "historical"]
        self.version = "1.0.0"
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language query about legal rules or regulations",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100
                },
                "include_archives": {
                    "type": "boolean",
                    "description": "Whether to include archived content in results",
                    "default": False
                },
                "archive_results": {
                    "type": "boolean",
                    "description": "Whether to archive the search results",
                    "default": False
                },
                "archive_dir": {
                    "type": "string",
                    "description": "Directory for storing archived results (optional)"
                }
            },
            "required": ["query"]
        }
    
    def execute(self, **kwargs: Any) -> Dict[str, Any]:
        """
        Execute unified legal search with optional archiving.
        
        Args:
            query: Natural language query about legal rules
            max_results: Maximum number of results (default: 20)
            include_archives: Include archived content (default: False)
            archive_results: Archive the results (default: False)
            archive_dir: Directory for archives (optional)
            
        Returns:
            Dict containing current results, archived results, and combined results
        """
        try:
            from ipfs_datasets_py.processors.legal_scrapers import LegalWebArchiveSearch
            
            # Extract parameters
            query = kwargs.get('query')
            max_results = kwargs.get('max_results', 20)
            include_archives = kwargs.get('include_archives', False)
            archive_results = kwargs.get('archive_results', False)
            archive_dir = kwargs.get('archive_dir')
            
            if not query:
                return {
                    'status': 'error',
                    'error': 'Missing required parameter: query'
                }
            
            # Create searcher instance
            searcher = LegalWebArchiveSearch(
                archive_dir=archive_dir,
                auto_archive=archive_results
            )
            
            # Execute unified search
            results = searcher.unified_search(
                query=query,
                max_results=max_results,
                include_archives=include_archives,
                archive_results=archive_results
            )
            
            return {
                'status': 'success',
                **results
            }
            
        except Exception as e:
            logger.error(f"Error in legal_web_archive_search: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }


class LegalSearchArchivesOnlyTool(ClaudeMCPTool):
    """
    MCP Tool for searching only archived legal documents.
    
    This tool searches Common Crawl and other web archives for historical
    legal documents with optional date range filtering.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "legal_search_archives_only"
        self.description = "Search only archived legal documents with date range filtering"
        self.category = "legal_datasets"
        self.tags = ["legal", "archive", "historical", "common-crawl"]
        self.version = "1.0.0"
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language query about legal rules"
                },
                "from_date": {
                    "type": "string",
                    "description": "Start date for search (YYYY-MM-DD format)",
                },
                "to_date": {
                    "type": "string",
                    "description": "End date for search (YYYY-MM-DD format)",
                },
                "domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of domains to search (e.g., ['epa.gov', 'regulations.gov'])"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum results to return",
                    "default": 50
                }
            },
            "required": ["query"]
        }
    
    def execute(self, **kwargs: Any) -> Dict[str, Any]:
        """
        Search archived legal documents only.
        
        Args:
            query: Natural language query
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)
            domains: List of domains to search
            max_results: Maximum results
            
        Returns:
            Dict with archived search results
        """
        try:
            from ipfs_datasets_py.processors.legal_scrapers import LegalWebArchiveSearch
            
            query = kwargs.get('query')
            from_date = kwargs.get('from_date')
            to_date = kwargs.get('to_date')
            domains = kwargs.get('domains')
            max_results = kwargs.get('max_results', 50)
            
            if not query:
                return {
                    'status': 'error',
                    'error': 'Missing required parameter: query'
                }
            
            searcher = LegalWebArchiveSearch()
            results = searcher.search_archives(
                query=query,
                from_date=from_date,
                to_date=to_date,
                domains=domains,
                max_results=max_results
            )
            
            return {
                'status': 'success',
                **results
            }
            
        except Exception as e:
            logger.error(f"Error in legal_search_archives_only: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }


class LegalArchiveResultsTool(ClaudeMCPTool):
    """
    MCP Tool for archiving legal search results.
    
    This tool takes search results and archives them for future reference,
    prioritizing .gov sites and important legal documents.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "legal_archive_results"
        self.description = "Archive legal search results for preservation and future reference"
        self.category = "legal_datasets"
        self.tags = ["legal", "archive", "preservation"]
        self.version = "1.0.0"
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Original search query"
                },
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string"},
                            "title": {"type": "string"},
                            "relevance_score": {"type": "number"}
                        }
                    },
                    "description": "List of search results to archive"
                },
                "archive_dir": {
                    "type": "string",
                    "description": "Directory for storing archived content"
                }
            },
            "required": ["query", "results"]
        }
    
    def execute(self, **kwargs: Any) -> Dict[str, Any]:
        """
        Archive search results.
        
        Args:
            query: Original search query
            results: List of results to archive
            archive_dir: Directory for archives
            
        Returns:
            Dict with archiving information
        """
        try:
            from ipfs_datasets_py.processors.legal_scrapers import LegalWebArchiveSearch
            
            query = kwargs.get('query')
            results = kwargs.get('results', [])
            archive_dir = kwargs.get('archive_dir')
            
            if not query or not results:
                return {
                    'status': 'error',
                    'error': 'Missing required parameters: query and results'
                }
            
            searcher = LegalWebArchiveSearch(archive_dir=archive_dir)
            archive_info = searcher._archive_search_results(
                query=query,
                results=results,
                intent=None
            )
            
            return {
                'status': 'success',
                **archive_info
            }
            
        except Exception as e:
            logger.error(f"Error in legal_archive_results: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }


class LegalGetArchiveStatsTool(ClaudeMCPTool):
    """
    MCP Tool for getting archive statistics.
    
    This tool returns information about archived legal content including
    counts, storage location, and configuration.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "legal_get_archive_stats"
        self.description = "Get statistics about archived legal content"
        self.category = "legal_datasets"
        self.tags = ["legal", "archive", "statistics"]
        self.version = "1.0.0"
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "archive_dir": {
                    "type": "string",
                    "description": "Directory of archives to check"
                }
            },
            "required": []
        }
    
    def execute(self, **kwargs: Any) -> Dict[str, Any]:
        """
        Get archive statistics.
        
        Args:
            archive_dir: Directory to check (optional)
            
        Returns:
            Dict with archive statistics
        """
        try:
            from ipfs_datasets_py.processors.legal_scrapers import LegalWebArchiveSearch
            
            archive_dir = kwargs.get('archive_dir')
            
            searcher = LegalWebArchiveSearch(archive_dir=archive_dir)
            stats = searcher.get_archive_stats()
            
            return {
                'status': 'success',
                **stats
            }
            
        except Exception as e:
            logger.error(f"Error in legal_get_archive_stats: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }


# Tool instances for registration
legal_web_archive_search_tool = LegalWebArchiveSearchTool()
legal_search_archives_only_tool = LegalSearchArchivesOnlyTool()
legal_archive_results_tool = LegalArchiveResultsTool()
legal_get_archive_stats_tool = LegalGetArchiveStatsTool()

# List of all tools for easy registration
LEGAL_WEB_ARCHIVE_TOOLS = [
    legal_web_archive_search_tool,
    legal_search_archives_only_tool,
    legal_archive_results_tool,
    legal_get_archive_stats_tool,
]


def register_legal_web_archive_tools(tool_registry) -> None:
    """
    Register all Legal Web Archive tools with the MCP tool registry.
    
    Args:
        tool_registry: The MCP tool registry instance
    """
    for tool in LEGAL_WEB_ARCHIVE_TOOLS:
        tool_registry.register_tool(tool)
    
    logger.info(f"Registered {len(LEGAL_WEB_ARCHIVE_TOOLS)} Legal Web Archive MCP tools")
