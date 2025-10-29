"""
Finance Data Tools for MCP Server.

This module provides comprehensive tools for collecting, processing, and analyzing
financial market data including stocks, currencies, bonds, futures, and cryptocurrencies.
It also includes news scraping capabilities with archive.org fallback support.

Main Components:
- Stock market data scrapers (Yahoo Finance, Alpha Vantage, Polygon.io)
- Currency/Forex data scrapers
- Bonds and Treasury data scrapers
- Futures market data scrapers
- Cryptocurrency data scrapers
- News scrapers (AP, Reuters, Bloomberg) with archive.org fallback
- Time series data storage and management
- Financial knowledge graph construction
- Temporal deontic logic theorem application
"""

from __future__ import annotations

__version__ = "0.1.0"

# Tool categories for MCP server discovery
TOOL_CATEGORIES = [
    "market_data",
    "news_scraping",
    "knowledge_graph",
    "temporal_reasoning",
    "graphrag_analysis"
]

__all__ = [
    "TOOL_CATEGORIES",
    "__version__"
]
