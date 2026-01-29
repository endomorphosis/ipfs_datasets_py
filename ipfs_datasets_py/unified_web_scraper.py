"""Backwards-compatible import shim for the unified web scraper.

The implementation lives in :mod:`ipfs_datasets_py.web_archiving.unified_web_scraper`.
This module preserves the historical import path used by migration tests and
older downstream code.
"""

from ipfs_datasets_py.web_archiving.unified_web_scraper import (  # noqa: F401
    ScraperConfig,
    ScraperResult,
    UnifiedWebScraper,
)

__all__ = [
    "ScraperConfig",
    "ScraperResult",
    "UnifiedWebScraper",
]
