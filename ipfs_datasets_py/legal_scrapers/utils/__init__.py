#!/usr/bin/env python3
"""
Legal Scrapers - Utilities

Common utilities and helpers.
"""

from .parallel_scraper import (
    ParallelScraper,
    ScrapingTask,
    ScrapingResult,
    scrape_urls_parallel,
    scrape_urls_parallel_async,
)

# Export functions will be imported from migrated modules when needed
__all__ = [
    'ParallelScraper',
    'ScrapingTask',
    'ScrapingResult',
    'scrape_urls_parallel',
    'scrape_urls_parallel_async',
    # Migrated utilities available for import:
    # - citations (citation extraction)
    # - export (data export utilities) 
    # - state_manager (resumable scraping)
    # - ipfs_storage (IPFS integration)
    # - incremental (incremental updates)
]
