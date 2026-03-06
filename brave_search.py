"""Compatibility shim for legacy top-level ``brave_search`` imports.

This repo now implements Brave search via the in-tree web archiving engine.
Expose the historical top-level module name so scripts and tests do not depend
on the third-party ``brave-search`` package.
"""

from ipfs_datasets_py.processors.web_archiving.brave_search_engine import (
    BraveSearchAPI,
    HAVE_BRAVE_CLIENT,
    batch_search_brave,
    clear_brave_cache,
    get_brave_cache_stats,
    search_brave,
    search_brave_images,
    search_brave_news,
)

__all__ = [
    "BraveSearchAPI",
    "HAVE_BRAVE_CLIENT",
    "search_brave",
    "search_brave_news",
    "search_brave_images",
    "batch_search_brave",
    "get_brave_cache_stats",
    "clear_brave_cache",
]
