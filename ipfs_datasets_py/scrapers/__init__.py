"""
Unified Scraping Infrastructure

This package provides centralized, deduplicated scraping functionality with:
- Intelligent fallback mechanisms
- Content-addressed deduplication
- WARC import/export
- Multi-source archive searches
- Parallel scraping support

All scraping in the codebase should use these unified scrapers rather than
implementing custom BeautifulSoup/Playwright/requests logic.
"""

from ipfs_datasets_py.unified_web_scraper import (
    UnifiedWebScraper,
    ScraperConfig,
    ScraperMethod,
    ScraperResult,
    scrape_url,
    scrape_urls
)

from ipfs_datasets_py.content_addressed_scraper import (
    ContentAddressedScraper
)

__all__ = [
    'UnifiedWebScraper',
    'ScraperConfig',
    'ScraperMethod',
    'ScraperResult',
    'ContentAddressedScraper',
    'scrape_url',
    'scrape_urls'
]
