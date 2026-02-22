"""Google Custom Search API integration for web search and data discovery.

This tool provides integration with Google Custom Search API for web search,
enabling dataset creation from search results.

Business logic has been extracted to the canonical package module:
    ipfs_datasets_py/web_archiving/google_search_engine.py

This file is now a thin re-export shim so existing imports continue to work.
"""
from ipfs_datasets_py.web_archiving.google_search_engine import (  # noqa: F401
    search_google,
    search_google_images,
    batch_search_google,
)
