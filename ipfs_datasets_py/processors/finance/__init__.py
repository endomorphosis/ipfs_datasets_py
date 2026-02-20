"""
Finance data processing package for ipfs_datasets_py.

Provides stock scrapers, news scrapers, and financial embedding analysis.

Reusable by:
- MCP server tools (mcp_server/tools/finance_data_tools/)
- CLI commands
- Direct Python imports
"""
from .stock_scraper_engine import (
    StockDataPoint,
    CorporateAction,
    StockDataScraper,
    YahooFinanceScraper,
)
from .news_scraper_engine import (
    NewsArticle,
    NewsScraperBase,
)

__all__ = [
    "StockDataPoint",
    "CorporateAction",
    "StockDataScraper",
    "YahooFinanceScraper",
    "NewsArticle",
    "NewsScraperBase",
]
