"""
Web Scraping Tools for MCP Server

This module exposes the unified web scraping system through the MCP server interface.
"""

from .unified_scraper_tool import (
    scrape_url_tool,
    scrape_multiple_urls_tool,
    check_scraper_methods_tool
)

__all__ = [
    'scrape_url_tool',
    'scrape_multiple_urls_tool',
    'check_scraper_methods_tool'
]
