#!/usr/bin/env python3
"""
MCP Tool Registry for Legal Scrapers

Central registry for all legal scraper MCP tools.
"""

import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class LegalScraperToolRegistry:
    """Registry for legal scraper MCP tools."""
    
    def __init__(self):
        """Initialize tool registry."""
        self.tools = []
        self.categories = {}
    
    def register_tool_category(self, category: str, tools: List[Dict[str, Any]]):
        """
        Register a category of tools.
        
        Args:
            category: Category name (e.g., 'municode', 'state_laws')
            tools: List of tool metadata
        """
        self.categories[category] = tools
        self.tools.extend(tools)
        logger.info(f"Registered {len(tools)} tools in category '{category}'")
    
    def get_all_tools(self) -> List[Dict[str, Any]]:
        """Get all registered tools."""
        return self.tools
    
    def get_tools_by_category(self, category: str) -> List[Dict[str, Any]]:
        """Get tools in a specific category."""
        return self.categories.get(category, [])
    
    def get_tool_names(self) -> List[str]:
        """Get names of all registered tools."""
        return [tool['name'] for tool in self.tools]


# Global registry instance
_registry = LegalScraperToolRegistry()


def get_registry() -> LegalScraperToolRegistry:
    """Get the global tool registry."""
    return _registry


def register_all_legal_scraper_tools(server):
    """
    Register all legal scraper tools with an MCP server.
    
    Args:
        server: MCP server instance
        
    Returns:
        MCP server with all tools registered
    """
    logger.info("Registering legal scraper MCP tools...")
    
    # Import and register Municode tools
    try:
        from .municode_tools import register_municode_tools, MUNICODE_TOOLS
        server = register_municode_tools(server)
        _registry.register_tool_category('municode', MUNICODE_TOOLS)
    except ImportError as e:
        logger.error(f"Failed to register Municode tools: {e}")
    
    # TODO: Register other scraper tools
    # from .state_laws_tools import register_state_laws_tools, STATE_LAWS_TOOLS
    # from .federal_register_tools import register_federal_register_tools, FEDERAL_REGISTER_TOOLS
    # etc.
    
    logger.info(f"✓ Registered {len(_registry.tools)} total MCP tools")
    return server


def list_all_tools() -> Dict[str, Any]:
    """
    Get a summary of all available tools.
    
    Returns:
        Dict with tool summary
    """
    return {
        "total_tools": len(_registry.tools),
        "categories": list(_registry.categories.keys()),
        "tools": _registry.get_all_tools()
    }


if __name__ == "__main__":
    # Test the registry
    from .municode_tools import MUNICODE_TOOLS
    
    _registry.register_tool_category('municode', MUNICODE_TOOLS)
    
    print("Legal Scraper MCP Tool Registry")
    print("=" * 60)
    
    summary = list_all_tools()
    print(f"\nTotal tools: {summary['total_tools']}")
    print(f"Categories: {', '.join(summary['categories'])}")
    
    print("\nRegistered tools:")
    for tool in summary['tools']:
        print(f"  • {tool['name']}")
        print(f"    {tool['description']}")
        print()
