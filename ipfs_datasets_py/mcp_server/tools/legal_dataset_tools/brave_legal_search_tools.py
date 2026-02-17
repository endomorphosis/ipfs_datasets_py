#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Brave Legal Search MCP Tools for Model Context Protocol.

This module exposes the Brave Legal Search system as MCP tools that can be
discovered and called via the MCP protocol. It provides natural language
search for legal rules and regulations using the Brave Search API.

Tools included:
- brave_legal_search: Search for legal rules using natural language
- brave_legal_search_generate_terms: Generate search terms without executing search
- brave_legal_search_explain: Explain how a query would be processed
- brave_legal_search_entities: Search the legal entity knowledge base
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.mcp_server.tool_registry import ClaudeMCPTool

logger = logging.getLogger(__name__)


class BraveLegalSearchTool(ClaudeMCPTool):
    """
    MCP Tool for searching legal rules and regulations using natural language.
    
    This tool uses the Brave Search API with an intelligent knowledge base
    of 21,000+ federal, state, and municipal government entities to find
    relevant legal rules and regulations based on natural language queries.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "brave_legal_search"
        self.description = "Search for legal rules and regulations using natural language queries (requires BRAVE_API_KEY)"
        self.category = "legal_datasets"
        self.tags = ["legal", "search", "brave", "regulations", "laws", "natural-language"]
        self.version = "1.0.0"
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language query about legal rules or regulations (e.g., 'EPA water pollution regulations in California')",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100
                },
                "country": {
                    "type": "string",
                    "description": "Country code for search localization",
                    "default": "US"
                },
                "lang": {
                    "type": "string",
                    "description": "Language code for search results",
                    "default": "en"
                }
            },
            "required": ["query"]
        }
    
    def execute(self, **kwargs: Any) -> Dict[str, Any]:
        """
        Execute legal search using natural language.
        
        Args:
            query: Natural language query about legal rules
            max_results: Maximum number of results to return (default: 20)
            country: Country code for search (default: "US")
            lang: Language code for results (default: "en")
            
        Returns:
            Dict containing search results with metadata
        """
        try:
            from ipfs_datasets_py.processors.legal_scrapers import BraveLegalSearch
            
            # Extract parameters
            query = kwargs.get('query')
            max_results = kwargs.get('max_results', 20)
            country = kwargs.get('country', 'US')
            lang = kwargs.get('lang', 'en')
            
            if not query:
                return {
                    'status': 'error',
                    'error': 'Missing required parameter: query'
                }
            
            # Create searcher instance
            searcher = BraveLegalSearch()
            
            # Execute search
            results = searcher.search(
                query=query,
                max_results=max_results,
                country=country,
                lang=lang
            )
            
            return {
                'status': 'success',
                'query': results['query'],
                'intent': results['intent'],
                'search_terms': results['search_terms'],
                'results': results['results'],
                'total_results': len(results['results']),
                'metadata': results['metadata']
            }
            
        except Exception as e:
            logger.error(f"Error in brave_legal_search: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }


class BraveLegalSearchGenerateTermsTool(ClaudeMCPTool):
    """
    MCP Tool for generating search terms from natural language queries.
    
    This tool generates optimized search terms without executing the search,
    useful for understanding how a query will be processed or for manual search.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "brave_legal_search_generate_terms"
        self.description = "Generate optimized search terms from a natural language legal query without executing search"
        self.category = "legal_datasets"
        self.tags = ["legal", "search", "query-processing", "terms"]
        self.version = "1.0.0"
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language query about legal rules or regulations"
                }
            },
            "required": ["query"]
        }
    
    def execute(self, **kwargs: Any) -> Dict[str, Any]:
        """
        Generate search terms from query.
        
        Args:
            query: Natural language query
            
        Returns:
            Dict containing generated search terms
        """
        try:
            from ipfs_datasets_py.processors.legal_scrapers import BraveLegalSearch
            
            query = kwargs.get('query')
            
            if not query:
                return {
                    'status': 'error',
                    'error': 'Missing required parameter: query'
                }
            
            searcher = BraveLegalSearch()
            terms = searcher.generate_search_terms(query)
            
            return {
                'status': 'success',
                'query': query,
                'search_terms': terms
            }
            
        except Exception as e:
            logger.error(f"Error in brave_legal_search_generate_terms: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }


class BraveLegalSearchExplainTool(ClaudeMCPTool):
    """
    MCP Tool for explaining how a query would be processed.
    
    This tool provides detailed explanation of query processing including
    extracted entities, categorization, and search strategy.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "brave_legal_search_explain"
        self.description = "Explain how a natural language legal query would be processed and what search terms would be generated"
        self.category = "legal_datasets"
        self.tags = ["legal", "search", "explain", "query-processing"]
        self.version = "1.0.0"
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language query to explain"
                }
            },
            "required": ["query"]
        }
    
    def execute(self, **kwargs: Any) -> Dict[str, Any]:
        """
        Explain query processing.
        
        Args:
            query: Natural language query
            
        Returns:
            Dict containing detailed explanation
        """
        try:
            from ipfs_datasets_py.processors.legal_scrapers import BraveLegalSearch
            
            query = kwargs.get('query')
            
            if not query:
                return {
                    'status': 'error',
                    'error': 'Missing required parameter: query'
                }
            
            searcher = BraveLegalSearch()
            explanation = searcher.explain_query(query)
            
            return {
                'status': 'success',
                **explanation
            }
            
        except Exception as e:
            logger.error(f"Error in brave_legal_search_explain: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }


class BraveLegalSearchEntitiesTool(ClaudeMCPTool):
    """
    MCP Tool for searching the legal entity knowledge base.
    
    This tool searches the knowledge base of 21,000+ federal, state, and
    municipal government entities directly without using Brave Search API.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "brave_legal_search_entities"
        self.description = "Search the knowledge base of 21,000+ federal, state, and municipal government entities"
        self.category = "legal_datasets"
        self.tags = ["legal", "knowledge-base", "entities", "agencies"]
        self.version = "1.0.0"
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query for entity names"
                },
                "entity_type": {
                    "type": "string",
                    "description": "Type of entity to search for",
                    "enum": ["federal", "state", "municipal", "all"],
                    "default": "all"
                }
            },
            "required": ["query"]
        }
    
    def execute(self, **kwargs: Any) -> Dict[str, Any]:
        """
        Search entity knowledge base.
        
        Args:
            query: Search query
            entity_type: Type filter (federal, state, municipal, or all)
            
        Returns:
            Dict containing matching entities
        """
        try:
            from ipfs_datasets_py.processors.legal_scrapers import BraveLegalSearch
            
            query = kwargs.get('query')
            entity_type = kwargs.get('entity_type', 'all')
            
            if not query:
                return {
                    'status': 'error',
                    'error': 'Missing required parameter: query'
                }
            
            searcher = BraveLegalSearch()
            
            if entity_type == 'all':
                results = searcher.search_entities(query)
            else:
                results = searcher.search_entities(query, entity_type=entity_type)
            
            # Format results for better display
            formatted = {}
            for entity_type_key, entities in results.items():
                formatted[entity_type_key] = [
                    {
                        'name': e.name if hasattr(e, 'name') else (e.agency_name if hasattr(e, 'agency_name') else e.place_name),
                        'type': entity_type_key,
                        'details': str(e)
                    }
                    for e in entities[:10]  # Limit to 10 per type
                ]
            
            return {
                'status': 'success',
                'query': query,
                'entity_type': entity_type,
                'results': formatted,
                'total_found': sum(len(entities) for entities in results.values())
            }
            
        except Exception as e:
            logger.error(f"Error in brave_legal_search_entities: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }


# Tool instances for registration
brave_legal_search_tool = BraveLegalSearchTool()
brave_legal_search_generate_terms_tool = BraveLegalSearchGenerateTermsTool()
brave_legal_search_explain_tool = BraveLegalSearchExplainTool()
brave_legal_search_entities_tool = BraveLegalSearchEntitiesTool()

# List of all tools for easy registration
BRAVE_LEGAL_SEARCH_TOOLS = [
    brave_legal_search_tool,
    brave_legal_search_generate_terms_tool,
    brave_legal_search_explain_tool,
    brave_legal_search_entities_tool,
]


def register_brave_legal_search_tools(tool_registry) -> None:
    """
    Register all Brave Legal Search tools with the MCP tool registry.
    
    Args:
        tool_registry: The MCP tool registry instance
    """
    for tool in BRAVE_LEGAL_SEARCH_TOOLS:
        tool_registry.register_tool(tool)
    
    logger.info(f"Registered {len(BRAVE_LEGAL_SEARCH_TOOLS)} Brave Legal Search MCP tools")
