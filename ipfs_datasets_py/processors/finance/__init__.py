"""
Finance data processing package for ipfs_datasets_py.

Provides stock scrapers, news scrapers, financial embedding analysis,
and financial theorems for temporal deontic logic reasoning.

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
from .finance_theorems_engine import (
    FinancialEventType,
    FinancialTheorem,
    FinancialTheoremLibrary,
    TheoremApplication,
    STOCK_SPLIT_THEOREM,
    REVERSE_SPLIT_THEOREM,
    DIVIDEND_EX_DATE_THEOREM,
    MERGER_PRICE_CONVERGENCE_THEOREM,
    EARNINGS_ANNOUNCEMENT_THEOREM,
)

__all__ = [
    "StockDataPoint",
    "CorporateAction",
    "StockDataScraper",
    "YahooFinanceScraper",
    "NewsArticle",
    "NewsScraperBase",
    "FinancialEventType",
    "FinancialTheorem",
    "FinancialTheoremLibrary",
    "TheoremApplication",
    "STOCK_SPLIT_THEOREM",
    "REVERSE_SPLIT_THEOREM",
    "DIVIDEND_EX_DATE_THEOREM",
    "MERGER_PRICE_CONVERGENCE_THEOREM",
    "EARNINGS_ANNOUNCEMENT_THEOREM",
]
