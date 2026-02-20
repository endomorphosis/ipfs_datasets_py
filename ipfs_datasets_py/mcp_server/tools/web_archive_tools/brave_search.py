"""Brave Search API integration for web search and data discovery.

Business logic has been extracted to the canonical package module:
    ipfs_datasets_py/web_archiving/brave_search_engine.py

This file is now a thin re-export shim so existing imports continue to work.
"""
from ipfs_datasets_py.web_archiving.brave_search_engine import (  # noqa: F401
    BraveSearchAPI,
    HAVE_BRAVE_CLIENT,
    search_brave,
    search_brave_news,
    search_brave_images,
    batch_search_brave,
    get_brave_cache_stats,
    clear_brave_cache,
)
