#!/usr/bin/env python3
"""
MCP Tools for Legal Scrapers

Model Context Protocol interface for legal data scrapers.
"""

# Import new unified MCP tools
try:
    from .legal_mcp_tools import (
        scrape_state_laws,
        scrape_us_code,
        scrape_federal_register,
        scrape_recap_documents,
        scrape_municipal_codes
    )
    HAVE_UNIFIED_TOOLS = True
except ImportError as e:
    HAVE_UNIFIED_TOOLS = False

try:
    from .tool_registry import (
        get_registry,
        register_all_legal_scraper_tools,
        list_all_tools
    )
    HAVE_REGISTRY = True
except ImportError as e:
    HAVE_REGISTRY = False
    
    # Provide stub functions
    def get_registry():
        raise ImportError("MCP tool registry not available")
    
    def register_all_legal_scraper_tools(server):
        raise ImportError("MCP tool registry not available")
    
    def list_all_tools():
        return {"total_tools": 0, "categories": [], "tools": []}

__all__ = [
    'get_registry',
    'register_all_legal_scraper_tools',
    'list_all_tools',
    'scrape_state_laws',
    'scrape_us_code',
    'scrape_federal_register',
    'scrape_recap_documents',
    'scrape_municipal_codes',
]
