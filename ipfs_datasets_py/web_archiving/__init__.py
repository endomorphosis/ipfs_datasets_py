"""Web archiving and scraping utilities for IPFS Datasets Python.

This module provides tools for web scraping, archiving, and text extraction.
"""

from .web_archive import *
from .web_archive_utils import *
from .web_text_extractor import *
from .simple_crawler import *
from .unified_web_scraper import *
from .scraper_testing_framework import *
from .common_crawl_integration import CommonCrawlSearchEngine, create_search_engine
from .brave_search_client import (
    BraveSearchClient,
    brave_web_search,
    brave_web_search_page,
    brave_search_cache_stats,
    clear_brave_search_cache
)

# Try to import IPFS cache (may not be available without ipfshttpclient)
try:
    from .brave_search_ipfs_cache import BraveSearchIPFSCache
    HAVE_IPFS_CACHE = True
except ImportError:
    BraveSearchIPFSCache = None
    HAVE_IPFS_CACHE = False

__all__ = [
    'web_archive',
    'web_archive_utils',
    'web_text_extractor',
    'simple_crawler',
    'unified_web_scraper',
    'scraper_testing_framework',
    'CommonCrawlSearchEngine',
    'create_search_engine',
    'BraveSearchClient',
    'brave_web_search',
    'brave_web_search_page',
    'brave_search_cache_stats',
    'clear_brave_search_cache',
    'BraveSearchIPFSCache',
    'HAVE_IPFS_CACHE',
]
